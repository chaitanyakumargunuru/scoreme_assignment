"""
API Integration Tests.
Covers: happy path, invalid input, idempotency, missing workflow, audit trail.
"""
import pytest


VALID_LOAN_PAYLOAD = {
    "request_id":    "REQ-LOAN-001",
    "workflow_type": "loan_approval",
    "payload": {
        "applicant_id":      "APP001",
        "loan_amount":       50000,
        "credit_score":      750,
        "annual_income":     100000,
        "loan_purpose":      "home",
        "employment_status": "employed",
    },
}


# ── Health check ─────────────────────────────────────────────────────────────

def test_health_endpoint(client):
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


# ── Happy path ───────────────────────────────────────────────────────────────

def test_submit_valid_loan_application(client):
    response = client.post("/api/v1/submit", json=VALID_LOAN_PAYLOAD)
    assert response.status_code == 200
    data = response.json()
    assert data["request_id"] == "REQ-LOAN-001"
    assert data["status"] in {"APPROVED", "MANUAL_REVIEW"}  # External service may succeed or retry
    assert data["idempotent"] is False


def test_list_workflows(client):
    response = client.get("/api/v1/workflows")
    assert response.status_code == 200
    workflows = response.json()["workflows"]
    assert "loan_approval" in workflows
    assert "vendor_approval" in workflows


# ── Invalid input ────────────────────────────────────────────────────────────

def test_missing_required_field_rejects(client):
    """Submitting without credit_score should result in REJECTED."""
    payload = {
        "request_id":    "REQ-INVALID-001",
        "workflow_type": "loan_approval",
        "payload": {
            "applicant_id":      "APP002",
            "loan_amount":       50000,
            # credit_score missing
            "annual_income":     80000,
            "loan_purpose":      "car",
            "employment_status": "employed",
        },
    }
    response = client.post("/api/v1/submit", json=payload)
    assert response.status_code == 200
    assert response.json()["status"] == "REJECTED"


def test_wrong_type_rejects(client):
    """Submitting credit_score as a string should fail validation."""
    payload = {
        "request_id":    "REQ-TYPE-001",
        "workflow_type": "loan_approval",
        "payload": {
            "applicant_id":      "APP003",
            "loan_amount":       50000,
            "credit_score":      "not_a_number",   # wrong type
            "annual_income":     80000,
            "loan_purpose":      "car",
            "employment_status": "employed",
        },
    }
    response = client.post("/api/v1/submit", json=payload)
    assert response.status_code == 200
    assert response.json()["status"] == "REJECTED"


def test_unemployed_applicant_rejected(client):
    """Unemployment should trigger rule rejection."""
    payload = {
        "request_id":    "REQ-UNEMP-001",
        "workflow_type": "loan_approval",
        "payload": {
            "applicant_id":      "APP004",
            "loan_amount":       50000,
            "credit_score":      700,
            "annual_income":     80000,
            "loan_purpose":      "home",
            "employment_status": "unemployed",
        },
    }
    response = client.post("/api/v1/submit", json=payload)
    assert response.status_code == 200
    assert response.json()["status"] == "REJECTED"


def test_low_credit_score_rejected(client):
    payload = {
        "request_id":    "REQ-CREDIT-001",
        "workflow_type": "loan_approval",
        "payload": {
            "applicant_id":      "APP005",
            "loan_amount":       50000,
            "credit_score":      450,
            "annual_income":     80000,
            "loan_purpose":      "home",
            "employment_status": "employed",
        },
    }
    response = client.post("/api/v1/submit", json=payload)
    assert response.status_code == 200
    assert response.json()["status"] == "REJECTED"


# ── Idempotency ──────────────────────────────────────────────────────────────

def test_duplicate_request_returns_same_result(client):
    """Submitting the same request_id twice should return stored result."""
    # First submission
    r1 = client.post("/api/v1/submit", json=VALID_LOAN_PAYLOAD)
    assert r1.status_code == 200
    first_result = r1.json()

    # Second submission (same request_id)
    r2 = client.post("/api/v1/submit", json=VALID_LOAN_PAYLOAD)
    assert r2.status_code == 200
    second_result = r2.json()

    assert second_result["idempotent"] is True
    assert second_result["status"] == first_result["status"]
    assert second_result["request_id"] == first_result["request_id"]


def test_duplicate_different_payload_returns_original(client):
    """
    Even if a duplicate request has a different payload, it returns the
    original stored result — idempotency is keyed on request_id only.
    """
    r1 = client.post("/api/v1/submit", json=VALID_LOAN_PAYLOAD)
    original_status = r1.json()["status"]

    tampered = {**VALID_LOAN_PAYLOAD, "payload": {**VALID_LOAN_PAYLOAD["payload"], "credit_score": 100}}
    r2 = client.post("/api/v1/submit", json=tampered)
    assert r2.json()["status"] == original_status
    assert r2.json()["idempotent"] is True


# ── Status and audit endpoints ───────────────────────────────────────────────

def test_get_status(client):
    client.post("/api/v1/submit", json=VALID_LOAN_PAYLOAD)
    response = client.get(f"/api/v1/status/{VALID_LOAN_PAYLOAD['request_id']}")
    assert response.status_code == 200
    assert response.json()["request_id"] == VALID_LOAN_PAYLOAD["request_id"]


def test_get_audit_trail(client):
    client.post("/api/v1/submit", json=VALID_LOAN_PAYLOAD)
    response = client.get(f"/api/v1/audit/{VALID_LOAN_PAYLOAD['request_id']}")
    assert response.status_code == 200
    data = response.json()
    assert data["total_events"] > 0
    # Should contain a rule evaluation event
    event_types = [e["event_type"] for e in data["audit_trail"]]
    assert "RULE_EVALUATION" in event_types


def test_get_state_history(client):
    client.post("/api/v1/submit", json=VALID_LOAN_PAYLOAD)
    response = client.get(f"/api/v1/history/{VALID_LOAN_PAYLOAD['request_id']}")
    assert response.status_code == 200
    history = response.json()["history"]
    assert len(history) >= 2  # At least PENDING → IN_PROGRESS → something


# ── Not found ────────────────────────────────────────────────────────────────

def test_status_not_found(client):
    response = client.get("/api/v1/status/NONEXISTENT-ID")
    assert response.status_code == 404


def test_unknown_workflow_type(client):
    payload = {
        "request_id":    "REQ-UNKNOWN-001",
        "workflow_type": "does_not_exist",
        "payload":       {"some": "data"},
    }
    response = client.post("/api/v1/submit", json=payload)
    assert response.status_code == 404


# ── Vendor workflow ──────────────────────────────────────────────────────────

def test_valid_vendor_submission(client):
    payload = {
        "request_id":    "REQ-VENDOR-001",
        "workflow_type": "vendor_approval",
        "payload": {
            "vendor_id":         "VND001",
            "company_name":      "TechCorp Ltd",
            "annual_revenue":    500000,
            "years_in_business": 7,
            "category":          "technology",
            "has_insurance":     True,
            "document_types":    ["business_license", "insurance_cert"],
        },
    }
    response = client.post("/api/v1/submit", json=payload)
    assert response.status_code == 200
    assert response.json()["status"] in {"APPROVED", "MANUAL_REVIEW"}


def test_vendor_no_insurance_rejected(client):
    payload = {
        "request_id":    "REQ-VENDOR-002",
        "workflow_type": "vendor_approval",
        "payload": {
            "vendor_id":         "VND002",
            "company_name":      "No Insurance Co",
            "annual_revenue":    500000,
            "years_in_business": 5,
            "category":          "logistics",
            "has_insurance":     False,
        },
    }
    response = client.post("/api/v1/submit", json=payload)
    assert response.status_code == 200
    assert response.json()["status"] == "REJECTED"
