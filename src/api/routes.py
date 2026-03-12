"""
API Routes
----------
REST API endpoints for the Workflow Decision Platform.

POST /submit          — Submit a new workflow request
GET  /status/{id}     — Get current status of a request
GET  /audit/{id}      — Get full audit trail for a request
GET  /history/{id}    — Get state transition history
GET  /workflows       — List available workflow types
POST /reload/{type}   — Reload a workflow config from disk
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Any, Dict, Optional
from sqlalchemy.orm import Session

from src.models.database     import get_db
from src.core.state_manager  import StateManager
from src.core.audit_logger   import AuditLogger
from src.core.workflow_executor import WorkflowExecutor
from src.core.config_loader  import ConfigLoader

router = APIRouter()


# ── Request / Response schemas ─────────────────────────────────────────────

class WorkflowSubmitRequest(BaseModel):
    request_id:    str                  # Caller-supplied idempotency key
    workflow_type: str                  # Must match a config file name
    payload:       Dict[str, Any]       # Business data for the workflow


class WorkflowSubmitResponse(BaseModel):
    request_id:    str
    workflow_type: str
    status:        str
    stage:         str
    retry_count:   int
    idempotent:    bool = False         # True if this was a duplicate request


# ── Endpoints ───────────────────────────────────────────────────────────────

@router.post("/submit", response_model=WorkflowSubmitResponse)
def submit_workflow(body: WorkflowSubmitRequest, db: Session = Depends(get_db)):
    """
    Submit a workflow request.
    
    Idempotency: if request_id was already processed, returns the stored result
    without re-executing the workflow.
    """
    state = StateManager(db)
    existing = state.get_request(body.request_id)

    # ── Idempotency check ────────────────────────────────────────────────
    if existing:
        return WorkflowSubmitResponse(
            request_id=existing.request_id,
            workflow_type=existing.workflow_type,
            status=existing.status,
            stage=existing.current_stage or "",
            retry_count=existing.retry_count,
            idempotent=True,
        )

    # ── Validate workflow type exists ────────────────────────────────────
    try:
        ConfigLoader.load_workflow(body.workflow_type)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))

    # ── Execute workflow ──────────────────────────────────────────────────
    try:
        executor = WorkflowExecutor(db)
        result   = executor.execute(body.request_id, body.workflow_type, body.payload)
        return WorkflowSubmitResponse(**result, idempotent=False)
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Workflow execution failed: {str(e)}")


@router.get("/status/{request_id}")
def get_status(request_id: str, db: Session = Depends(get_db)):
    """Get the current status and stage of a request."""
    state = StateManager(db)
    req   = state.get_request(request_id)
    if not req:
        raise HTTPException(status_code=404, detail=f"Request '{request_id}' not found")
    return {
        "request_id":    req.request_id,
        "workflow_type": req.workflow_type,
        "status":        req.status,
        "current_stage": req.current_stage,
        "retry_count":   req.retry_count,
        "created_at":    req.created_at.isoformat(),
        "updated_at":    req.updated_at.isoformat(),
    }


@router.get("/audit/{request_id}")
def get_audit(request_id: str, db: Session = Depends(get_db)):
    """
    Get the full audit trail for a request.
    Shows every rule evaluated, decision made, and why.
    """
    state = StateManager(db)
    if not state.get_request(request_id):
        raise HTTPException(status_code=404, detail=f"Request '{request_id}' not found")

    audit  = AuditLogger(db)
    trail  = audit.get_audit_trail(request_id)
    return {
        "request_id":  request_id,
        "audit_trail": trail,
        "total_events": len(trail),
    }


@router.get("/history/{request_id}")
def get_history(request_id: str, db: Session = Depends(get_db)):
    """Get the state transition history for a request."""
    state = StateManager(db)
    req   = state.get_request(request_id)
    if not req:
        raise HTTPException(status_code=404, detail=f"Request '{request_id}' not found")

    return {
        "request_id": request_id,
        "status":     req.status,
        "history":    state.get_history(request_id),
    }


@router.get("/workflows")
def list_workflows():
    """List all available workflow configurations."""
    return {
        "workflows": ConfigLoader.list_workflows()
    }


@router.post("/reload/{workflow_type}")
def reload_workflow(workflow_type: str):
    """
    Force reload a workflow config from disk.
    Use this after editing a YAML file without restarting the server.
    """
    try:
        config = ConfigLoader.reload_workflow(workflow_type)
        return {
            "message":       f"Workflow '{workflow_type}' reloaded",
            "workflow_name": config.get("workflow", {}).get("name"),
            "version":       config.get("workflow", {}).get("version"),
        }
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/health")
def health():
    """Health check endpoint."""
    return {"status": "ok", "service": "Workflow Decision Platform"}
