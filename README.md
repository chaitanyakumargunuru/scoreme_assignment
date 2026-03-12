# Workflow Decision Platform

A configurable, rule-driven workflow engine built with FastAPI + SQLAlchemy.
Supports multiple business workflows via YAML config — no code changes needed to add new workflows or rules.

---

## Setup

```bash
# 1. Create and activate virtual environment
python3 -m venv venv
source venv/bin/activate       # Windows: venv\Scripts\activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Start the server
uvicorn main:app --reload

# API docs available at: http://localhost:8000/docs
```

---

## Project Structure

```
workflow_platform/
├── main.py                         # FastAPI app entry point
├── requirements.txt
├── config/
│   └── workflows/
│       ├── loan_approval.yaml      # Loan workflow (configurable)
│       └── vendor_approval.yaml    # Vendor workflow (configurable)
├── src/
│   ├── models/
│   │   └── database.py             # SQLAlchemy ORM models
│   ├── core/
│   │   ├── config_loader.py        # Reads YAML workflow configs
│   │   ├── schema_validator.py     # Validates incoming request payloads
│   │   ├── rules_engine.py         # Evaluates business rules
│   │   ├── workflow_executor.py    # Orchestrates all workflow stages
│   │   ├── state_manager.py        # Tracks status transitions + history
│   │   └── audit_logger.py         # Explainable audit trail
│   ├── services/
│   │   └── mock_external.py        # Simulated external dependencies
│   └── api/
│       └── routes.py               # REST API endpoints
└── tests/
    ├── conftest.py
    ├── test_rules_engine.py
    ├── test_api.py
    └── test_retry.py
```

---

## API Endpoints

| Method | Endpoint                  | Description                               |
|--------|---------------------------|-------------------------------------------|
| POST   | `/api/v1/submit`          | Submit a workflow request                 |
| GET    | `/api/v1/status/{id}`     | Get current status                        |
| GET    | `/api/v1/audit/{id}`      | Get full explainable audit trail          |
| GET    | `/api/v1/history/{id}`    | Get state transition history              |
| GET    | `/api/v1/workflows`       | List available workflow types             |
| POST   | `/api/v1/reload/{type}`   | Reload a config from disk (no restart)    |
| GET    | `/api/v1/health`          | Health check                              |

---

## Example: Submit a Loan Application

```bash
curl -X POST http://localhost:8000/api/v1/submit \
  -H "Content-Type: application/json" \
  -d '{
    "request_id": "REQ-2024-001",
    "workflow_type": "loan_approval",
    "payload": {
      "applicant_id": "APP001",
      "loan_amount": 50000,
      "credit_score": 720,
      "annual_income": 100000,
      "loan_purpose": "home",
      "employment_status": "employed"
    }
  }'
```

**Response:**
```json
{
  "request_id": "REQ-2024-001",
  "workflow_type": "loan_approval",
  "status": "APPROVED",
  "stage": "approved",
  "retry_count": 0,
  "idempotent": false
}
```

**Idempotency — resending the same request_id returns the cached result:**
```json
{
  "request_id": "REQ-2024-001",
  "status": "APPROVED",
  "idempotent": true
}
```

---

## Adding a New Workflow (Zero Code Changes)

1. Create `config/workflows/my_workflow.yaml`
2. Define `input_schema`, `stages`, and `rules_sets`
3. Hit `POST /api/v1/reload/my_workflow` (or restart server)
4. Submit requests with `"workflow_type": "my_workflow"`

---

## Running Tests

```bash
pytest tests/ -v
```

Test coverage includes:
- ✅ Happy path (all rules pass, service succeeds)
- ✅ Invalid input / missing fields
- ✅ Type validation failures
- ✅ Rule failures (credit score, income ratio, employment)
- ✅ Duplicate request idempotency
- ✅ External service failure → retry → manual_review
- ✅ Retry count tracking
- ✅ Audit trail completeness
- ✅ Unknown workflow type (404)
- ✅ Operator coverage (eq, neq, gt, gte, lt, lte, in, not_in)
- ✅ Dynamic value expressions

---

## Workflow Statuses

| Status          | Meaning                                      |
|-----------------|----------------------------------------------|
| `PENDING`       | Request received, not yet processed          |
| `IN_PROGRESS`   | Actively being evaluated                     |
| `APPROVED`      | All checks passed                            |
| `REJECTED`      | Failed a mandatory rule or validation        |
| `MANUAL_REVIEW` | Flagged for human review (borderline/risky)  |
| `RETRY`         | External service failed, retrying            |
| `FAILED`        | Unexpected system error                      |

---

## Architecture Decisions

| Decision | Rationale |
|---|---|
| YAML config for workflows | Rules and stages changeable without code edits |
| SQLite (swappable to Postgres) | Simple for dev; change `DATABASE_URL` for production |
| Idempotency via request_id | Caller-supplied key prevents duplicate processing |
| All rules evaluated before deciding | Produces complete audit trace (no silent short-circuit) |
| Rejection beats manual_review | Deterministic priority prevents ambiguity |
| Mock external services | Demonstrates real retry logic without external dependencies |

---

## Scaling Considerations

- **Database**: Replace SQLite with PostgreSQL + connection pooling
- **Async execution**: Move workflow execution to a task queue (Celery/Redis)
- **Config hot-reload**: `/reload` endpoint allows rule changes without downtime  
- **Horizontal scaling**: Idempotency key prevents double-execution across instances
- **Observability**: Audit log table can feed into data warehouse for analytics
