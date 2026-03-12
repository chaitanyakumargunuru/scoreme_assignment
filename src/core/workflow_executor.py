"""
Workflow Executor
-----------------
The heart of the platform. Orchestrates each stage defined in a workflow config:
  - validation
  - rules_evaluation
  - external_dependency
  - terminal (approved / rejected / manual_review)
  - retry

Each stage is self-contained and maps cleanly to the config structure.
"""
import time
from typing import Dict, Any

from sqlalchemy.orm import Session

from src.core.config_loader    import ConfigLoader
from src.core.schema_validator import SchemaValidator
from src.core.rules_engine     import RulesEngine
from src.core.state_manager    import StateManager
from src.core.audit_logger     import AuditLogger
from src.services.mock_external import get_service, ExternalServiceError


class WorkflowExecutor:
    def __init__(self, db: Session):
        self.db      = db
        self.state   = StateManager(db)
        self.audit   = AuditLogger(db)

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def execute(self, request_id: str, workflow_type: str, payload: Dict[str, Any]) -> Dict:
        """
        Execute a complete workflow for the given request.
        Returns a summary dict with final status, stage, and audit reference.
        """
        config = ConfigLoader.load_workflow(workflow_type)
        stages = ConfigLoader.get_stages(workflow_type)

        req = self.state.create_request(request_id, workflow_type, payload)
        self.state.transition(request_id, "IN_PROGRESS", stage="started")
        self.db.commit()

        stage_map = {s["name"]: s for s in stages}
        current_stage_name = stages[0]["name"]  # Start at first stage

        while True:
            stage = stage_map.get(current_stage_name)
            if not stage:
                self._fail(request_id, current_stage_name, f"Stage '{current_stage_name}' not found in config")
                break

            stage_type = stage.get("type")

            if stage_type == "validation":
                current_stage_name = self._run_validation(request_id, stage, payload, workflow_type)

            elif stage_type == "rules":
                current_stage_name = self._run_rules(request_id, stage, payload, workflow_type)

            elif stage_type == "external_dependency":
                current_stage_name = self._run_external(request_id, stage, payload)

            elif stage_type == "terminal":
                self._run_terminal(request_id, stage)
                break

            elif stage_type == "retry":
                result = self._run_retry(request_id, stage)
                if result == "exhausted":
                    on_exhausted = stage.get("on_exhausted", "manual_review")
                    current_stage_name = on_exhausted
                else:
                    # Go back to the stage that caused the failure
                    current_stage_name = stage.get("retry_target", stages[0]["name"])
            else:
                self._fail(request_id, current_stage_name, f"Unknown stage type '{stage_type}'")
                break

            self.db.commit()

        self.db.commit()
        req = self.state.get_request(request_id)
        return {
            "request_id":    request_id,
            "workflow_type": workflow_type,
            "status":        req.status,
            "stage":         req.current_stage,
            "retry_count":   req.retry_count,
        }

    # ------------------------------------------------------------------
    # Stage handlers
    # ------------------------------------------------------------------

    def _run_validation(self, request_id: str, stage: Dict, payload: Dict, workflow_type: str) -> str:
        """Validate the input payload against the workflow schema."""
        schema     = ConfigLoader.get_input_schema(workflow_type)
        validator  = SchemaValidator(schema)
        valid, errors = validator.validate(payload)

        self.audit.log_stage_transition(request_id, "intake", stage["name"])

        if valid:
            self.audit.log_stage_transition(
                request_id, stage["name"], stage["on_success"],
                "Validation passed"
            )
            return stage["on_success"]
        else:
            error_summary = "; ".join(errors)
            self.audit.log_error(request_id, stage["name"], f"Validation failed: {error_summary}")
            self.state.transition(
                request_id, "REJECTED",
                stage=stage["name"],
                notes=f"Input validation failed: {error_summary}"
            )
            return stage["on_failure"]

    def _run_rules(self, request_id: str, stage: Dict, payload: Dict, workflow_type: str) -> str:
        """Evaluate the rules set defined in this stage."""
        rules_set_name = stage.get("rules_set")
        rules          = ConfigLoader.get_rules(workflow_type, rules_set_name)
        engine         = RulesEngine(payload)
        outcome, results = engine.evaluate_all(rules)

        self.audit.log_rule_evaluation(request_id, stage["name"], results, outcome)

        if outcome == "approve":
            next_stage = stage.get("on_success")
            self.audit.log_stage_transition(
                request_id, stage["name"], next_stage, "All rules passed"
            )
            return next_stage

        elif outcome == "reject":
            failed = [r.reason for r in results if not r.passed]
            self.state.transition(
                request_id, "REJECTED",
                stage=stage["name"],
                notes="Rules rejection: " + "; ".join(failed)
            )
            return stage.get("on_reject", "rejected")

        else:  # manual_review
            flagged = [r.reason for r in results if not r.passed]
            self.state.transition(
                request_id, "MANUAL_REVIEW",
                stage=stage["name"],
                notes="Flagged for review: " + "; ".join(flagged)
            )
            return stage.get("on_manual_review", "manual_review")

    def _run_external(self, request_id: str, stage: Dict, payload: Dict) -> str:
        """Call an external service; handle failures by routing to retry."""
        service_name = stage.get("service")
        service      = get_service(service_name)

        try:
            if service_name == "credit_bureau":
                result = service.verify(
                    applicant_id=payload.get("applicant_id"),
                    declared_credit_score=payload.get("credit_score", 0),
                )
            elif service_name == "document_verification":
                result = service.verify(
                    applicant_id=payload.get("applicant_id"),
                    document_types=payload.get("document_types", []),
                )
            else:
                result = {"verified": True}

            self.audit.log_external_call(
                request_id, service_name, True,
                f"Response: {result}"
            )
            next_stage = stage.get("on_success")
            self.audit.log_stage_transition(
                request_id, stage["name"], next_stage,
                f"External service '{service_name}' succeeded"
            )
            return next_stage

        except ExternalServiceError as e:
            self.audit.log_external_call(request_id, service_name, False, str(e))
            self.state.transition(
                request_id, "RETRY",
                stage=stage["name"],
                notes=str(e)
            )
            return stage.get("on_failure", "retry")

    def _run_retry(self, request_id: str, stage: Dict) -> str:
        """Handle retry logic with backoff. Returns 'retry' or 'exhausted'."""
        max_attempts  = stage.get("max_attempts", 3)
        backoff_secs  = stage.get("backoff_seconds", 1)

        attempt = self.state.increment_retry(request_id)
        self.audit.log_retry(request_id, attempt, max_attempts, "Retrying after failure")

        if attempt >= max_attempts:
            self.audit.log_stage_transition(
                request_id, "retry",
                stage.get("on_exhausted", "manual_review"),
                f"Max retries ({max_attempts}) exhausted"
            )
            self.state.transition(
                request_id, "MANUAL_REVIEW",
                stage="retry_exhausted",
                notes=f"Retries exhausted after {attempt} attempts"
            )
            return "exhausted"

        # Backoff before retry (simulated, keep short in tests)
        time.sleep(backoff_secs * 0.1)   # 10% of real backoff during execution
        self.state.transition(request_id, "IN_PROGRESS", stage="retry", notes=f"Retry attempt {attempt}")
        return "retry"

    def _run_terminal(self, request_id: str, stage: Dict):
        """Handle terminal stages (approved/rejected/manual_review)."""
        status_map = {
            "approved":      "APPROVED",
            "rejected":      "REJECTED",
            "manual_review": "MANUAL_REVIEW",
        }
        terminal_status = stage.get("status") or status_map.get(stage["name"], "FAILED")

        req = self.state.get_request(request_id)
        # Only transition if not already in a terminal state
        if req.status not in {"APPROVED", "REJECTED", "MANUAL_REVIEW", "FAILED"}:
            self.state.transition(
                request_id, terminal_status,
                stage=stage["name"],
                notes=f"Terminal stage reached: {stage['name']}"
            )
        self.audit.log_stage_transition(
            request_id, req.current_stage, stage["name"],
            f"Workflow complete with status: {terminal_status}"
        )

    def _fail(self, request_id: str, stage: str, reason: str):
        """Hard failure — unexpected error in executor itself."""
        self.audit.log_error(request_id, stage, reason)
        req = self.state.get_request(request_id)
        if req and req.status not in {"APPROVED", "REJECTED", "MANUAL_REVIEW", "FAILED"}:
            self.state.transition(request_id, "FAILED", stage=stage, notes=reason)
