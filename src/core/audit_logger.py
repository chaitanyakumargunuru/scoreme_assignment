"""
Audit Logger
------------
Records explainable audit events for every meaningful action:
rule evaluations, stage transitions, external calls, retry attempts.

Every decision can be fully reconstructed from the audit trail.
"""
from typing import Any, Dict, List, Optional
from sqlalchemy.orm import Session
from src.models.database import AuditLog


class AuditLogger:
    def __init__(self, db: Session):
        self.db = db

    def log_rule_evaluation(self, request_id: str, stage: str,
                             rules_results: List[Any], outcome: str):
        """Log the result of a rules evaluation pass."""
        self.db.add(AuditLog(
            request_id=request_id,
            event_type="RULE_EVALUATION",
            stage=stage,
            rules_evaluated=[r.to_dict() for r in rules_results],
            decision=outcome.upper(),
            details=(
                f"Evaluated {len(rules_results)} rules. "
                f"Passed: {sum(1 for r in rules_results if r.passed)}. "
                f"Failed: {sum(1 for r in rules_results if not r.passed)}. "
                f"Outcome: {outcome}"
            ),
        ))

    def log_stage_transition(self, request_id: str, from_stage: str,
                              to_stage: str, reason: str = ""):
        """Log a workflow stage transition."""
        self.db.add(AuditLog(
            request_id=request_id,
            event_type="STAGE_TRANSITION",
            stage=to_stage,
            rules_evaluated=None,
            decision=None,
            details=f"Stage: {from_stage} → {to_stage}. {reason}",
        ))

    def log_external_call(self, request_id: str, service: str,
                          success: bool, response_summary: str):
        """Log an external service call result."""
        self.db.add(AuditLog(
            request_id=request_id,
            event_type="EXTERNAL_SERVICE_CALL",
            stage=service,
            rules_evaluated=None,
            decision="SUCCESS" if success else "FAILURE",
            details=f"Service: {service} | Result: {'OK' if success else 'FAILED'} | {response_summary}",
        ))

    def log_retry(self, request_id: str, attempt: int, max_attempts: int, reason: str):
        """Log a retry attempt."""
        self.db.add(AuditLog(
            request_id=request_id,
            event_type="RETRY",
            stage="retry_handler",
            rules_evaluated=None,
            decision="RETRY",
            details=f"Retry attempt {attempt}/{max_attempts}. Reason: {reason}",
        ))

    def log_error(self, request_id: str, stage: str, error: str):
        """Log an unexpected error."""
        self.db.add(AuditLog(
            request_id=request_id,
            event_type="ERROR",
            stage=stage,
            rules_evaluated=None,
            decision="FAILED",
            details=f"Error in stage '{stage}': {error}",
        ))

    def get_audit_trail(self, request_id: str) -> List[Dict]:
        """Return full ordered audit trail for a request — human readable."""
        rows = (
            self.db.query(AuditLog)
            .filter(AuditLog.request_id == request_id)
            .order_by(AuditLog.timestamp)
            .all()
        )
        return [
            {
                "timestamp":       row.timestamp.isoformat(),
                "event_type":      row.event_type,
                "stage":           row.stage,
                "decision":        row.decision,
                "details":         row.details,
                "rules_evaluated": row.rules_evaluated,
            }
            for row in rows
        ]
