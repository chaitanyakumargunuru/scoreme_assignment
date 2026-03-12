"""
State Manager
-------------
Manages the lifecycle of a WorkflowRequest.
All status transitions are persisted to StateHistory for full auditability.

Valid statuses: PENDING, IN_PROGRESS, APPROVED, REJECTED, MANUAL_REVIEW, RETRY, FAILED
"""
import datetime
from typing import Optional
from sqlalchemy.orm import Session
from src.models.database import WorkflowRequest, StateHistory


VALID_STATUSES = {
    "PENDING", "IN_PROGRESS", "APPROVED",
    "REJECTED", "MANUAL_REVIEW", "RETRY", "FAILED"
}

# Allowed transitions — prevents illegal state jumps
ALLOWED_TRANSITIONS = {
    "PENDING":        {"IN_PROGRESS", "REJECTED"},
    "IN_PROGRESS":    {"APPROVED", "REJECTED", "MANUAL_REVIEW", "RETRY", "FAILED"},
    "RETRY":          {"IN_PROGRESS", "FAILED", "MANUAL_REVIEW"},  # MANUAL_REVIEW on exhaustion
    "APPROVED":       set(),   # Terminal
    "REJECTED":       set(),   # Terminal
    "MANUAL_REVIEW":  set(),   # Terminal (human takes over)
    "FAILED":         set(),   # Terminal
}


class StateManager:
    def __init__(self, db: Session):
        self.db = db

    def get_request(self, request_id: str) -> Optional[WorkflowRequest]:
        return (
            self.db.query(WorkflowRequest)
            .filter(WorkflowRequest.request_id == request_id)
            .first()
        )

    def create_request(self, request_id: str, workflow_type: str, payload: dict) -> WorkflowRequest:
        """Create a new workflow request in PENDING state."""
        req = WorkflowRequest(
            request_id=request_id,
            workflow_type=workflow_type,
            payload=payload,
            status="PENDING",
            current_stage="intake",
            retry_count=0,
        )
        self.db.add(req)
        self.db.flush()
        self._record_transition(request_id, None, "PENDING", "intake", "Request created")
        return req

    def transition(self, request_id: str, new_status: str,
                   stage: str = None, notes: str = "") -> WorkflowRequest:
        """
        Transition a request to a new status.
        Validates the transition is legal before persisting.
        """
        if new_status not in VALID_STATUSES:
            raise ValueError(f"Invalid status '{new_status}'")

        req = self.get_request(request_id)
        if not req:
            raise LookupError(f"Request '{request_id}' not found")

        current = req.status
        allowed = ALLOWED_TRANSITIONS.get(current, set())
        if new_status not in allowed:
            raise ValueError(
                f"Illegal transition: {current} → {new_status} "
                f"(allowed from {current}: {allowed or 'none — terminal state'})"
            )

        self._record_transition(request_id, current, new_status, stage or req.current_stage, notes)

        req.status        = new_status
        req.current_stage = stage or req.current_stage
        req.updated_at    = datetime.datetime.now(datetime.UTC)
        self.db.flush()
        return req

    def increment_retry(self, request_id: str) -> int:
        """Increment retry counter and return new count."""
        req = self.get_request(request_id)
        if not req:
            raise LookupError(f"Request '{request_id}' not found")
        req.retry_count += 1
        req.updated_at   = datetime.datetime.now(datetime.UTC)
        self.db.flush()
        return req.retry_count

    def get_history(self, request_id: str) -> list:
        """Return full state transition history for a request."""
        rows = (
            self.db.query(StateHistory)
            .filter(StateHistory.request_id == request_id)
            .order_by(StateHistory.timestamp)
            .all()
        )
        return [
            {
                "from_status": r.from_status,
                "to_status":   r.to_status,
                "stage":       r.stage,
                "notes":       r.notes,
                "timestamp":   r.timestamp.isoformat(),
            }
            for r in rows
        ]

    def _record_transition(self, request_id: str, from_status: Optional[str],
                           to_status: str, stage: str, notes: str):
        entry = StateHistory(
            request_id=request_id,
            from_status=from_status,
            to_status=to_status,
            stage=stage,
            notes=notes,
        )
        self.db.add(entry)