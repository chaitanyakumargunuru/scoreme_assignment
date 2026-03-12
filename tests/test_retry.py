"""
Tests for retry logic, failure handling, and external service resilience.
"""
import pytest
from unittest.mock import patch
from src.services.mock_external import MockCreditBureauService, ExternalServiceError


# ── External service mock tests ──────────────────────────────────────────────

def test_credit_bureau_success():
    service = MockCreditBureauService(failure_rate=0.0)
    result  = service.verify("APP001", 720)
    assert result["verified"] is True
    assert "bureau_score" in result
    assert result["applicant_id"] == "APP001"


def test_credit_bureau_forced_failure():
    service = MockCreditBureauService(force_failure=True)
    with pytest.raises(ExternalServiceError):
        service.verify("APP001", 720)


def test_credit_bureau_score_range():
    """Bureau score should always stay within 300–850."""
    service = MockCreditBureauService(failure_rate=0.0)
    for _ in range(20):
        result = service.verify("APP001", 720)
        assert 300 <= result["bureau_score"] <= 850


# ── Retry flow via API ───────────────────────────────────────────────────────

def test_retry_flow_lands_in_manual_review(client):
    """
    When external service always fails, request should exhaust retries
    and end in MANUAL_REVIEW.
    """
    with patch(
        "src.core.workflow_executor.get_service",
        side_effect=lambda name, **kw: _always_failing_service()
    ):
        payload = {
            "request_id":    "REQ-RETRY-001",
            "workflow_type": "loan_approval",
            "payload": {
                "applicant_id":      "APP010",
                "loan_amount":       50000,
                "credit_score":      750,
                "annual_income":     100000,
                "loan_purpose":      "home",
                "employment_status": "employed",
            },
        }
        response = client.post("/api/v1/submit", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "MANUAL_REVIEW"
        assert data["retry_count"] > 0


def test_retry_count_increments(client):
    """Verify retry_count field increments correctly."""
    with patch(
        "src.core.workflow_executor.get_service",
        side_effect=lambda name, **kw: _always_failing_service()
    ):
        payload = {
            "request_id":    "REQ-RETRY-002",
            "workflow_type": "loan_approval",
            "payload": {
                "applicant_id":      "APP011",
                "loan_amount":       50000,
                "credit_score":      750,
                "annual_income":     100000,
                "loan_purpose":      "home",
                "employment_status": "employed",
            },
        }
        response = client.post("/api/v1/submit", json=payload)
        data = response.json()
        # max_attempts in loan_approval config is 3
        assert data["retry_count"] == 3


def test_retry_audit_events_logged(client):
    """Audit trail should contain RETRY events when service fails."""
    with patch(
        "src.core.workflow_executor.get_service",
        side_effect=lambda name, **kw: _always_failing_service()
    ):
        request_id = "REQ-RETRY-AUDIT-001"
        payload = {
            "request_id":    request_id,
            "workflow_type": "loan_approval",
            "payload": {
                "applicant_id":      "APP012",
                "loan_amount":       50000,
                "credit_score":      750,
                "annual_income":     100000,
                "loan_purpose":      "home",
                "employment_status": "employed",
            },
        }
        client.post("/api/v1/submit", json=payload)
        audit_response = client.get(f"/api/v1/audit/{request_id}")
        event_types = [e["event_type"] for e in audit_response.json()["audit_trail"]]
        assert "RETRY" in event_types
        assert "EXTERNAL_SERVICE_CALL" in event_types


# ── Helper ───────────────────────────────────────────────────────────────────

class _AlwaysFailingService:
    def verify(self, *args, **kwargs):
        raise ExternalServiceError("Simulated permanent failure")


def _always_failing_service():
    return _AlwaysFailingService()
