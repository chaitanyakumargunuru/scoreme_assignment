"""
Tests for the Rules Engine.
Covers: operators, value expressions, priority order, outcomes.
"""
import pytest
from src.core.rules_engine import RulesEngine


SAMPLE_PAYLOAD = {
    "applicant_id":      "APP001",
    "loan_amount":       100000,
    "credit_score":      720,
    "annual_income":     80000,
    "employment_status": "employed",
    "loan_purpose":      "home",
}

SAMPLE_RULES = [
    {
        "id": "credit_score_check",
        "description": "Credit score >= 600",
        "priority": 1,
        "condition": {"field": "credit_score", "operator": "gte", "value": 600},
        "on_fail": "reject",
    },
    {
        "id": "income_ratio",
        "description": "Loan <= 5x income",
        "priority": 2,
        "condition": {
            "field": "loan_amount",
            "operator": "lte",
            "value_expression": "annual_income * 5",
        },
        "on_fail": "reject",
    },
    {
        "id": "high_value_review",
        "description": "Loans > 500k need review",
        "priority": 3,
        "condition": {"field": "loan_amount", "operator": "lte", "value": 500000},
        "on_fail": "manual_review",
    },
]


# ── Happy path ──────────────────────────────────────────────────────────────

def test_all_rules_pass():
    engine = RulesEngine(SAMPLE_PAYLOAD)
    outcome, results = engine.evaluate_all(SAMPLE_RULES)
    assert outcome == "approve"
    assert all(r.passed for r in results)


# ── Rejection scenarios ─────────────────────────────────────────────────────

def test_low_credit_score_rejects():
    payload = {**SAMPLE_PAYLOAD, "credit_score": 500}
    engine  = RulesEngine(payload)
    outcome, results = engine.evaluate_all(SAMPLE_RULES)
    assert outcome == "reject"
    assert not results[0].passed   # credit_score_check should fail


def test_income_ratio_breach_rejects():
    # loan_amount > annual_income * 5
    payload = {**SAMPLE_PAYLOAD, "loan_amount": 600000, "annual_income": 50000}
    engine  = RulesEngine(payload)
    outcome, results = engine.evaluate_all(SAMPLE_RULES)
    assert outcome == "reject"


# ── Manual review scenarios ─────────────────────────────────────────────────

def test_high_value_loan_manual_review():
    payload = {**SAMPLE_PAYLOAD, "loan_amount": 750000, "annual_income": 500000}
    engine  = RulesEngine(payload)
    outcome, results = engine.evaluate_all(SAMPLE_RULES)
    assert outcome == "manual_review"


# ── Rejection takes priority over manual_review ────────────────────────────

def test_rejection_beats_manual_review():
    # Credit score fails (reject) AND high-value loan (manual_review)
    payload = {**SAMPLE_PAYLOAD, "credit_score": 400, "loan_amount": 750000, "annual_income": 500000}
    engine  = RulesEngine(payload)
    outcome, results = engine.evaluate_all(SAMPLE_RULES)
    assert outcome == "reject"


# ── Operator coverage ───────────────────────────────────────────────────────

@pytest.mark.parametrize("operator,field_val,compare_val,expected_pass", [
    ("eq",      100,  100,   True),
    ("eq",      100,  200,   False),
    ("neq",     100,  200,   True),
    ("gt",      200,  100,   True),
    ("gt",      100,  200,   False),
    ("gte",     100,  100,   True),
    ("lt",      50,   100,   True),
    ("lte",     100,  100,   True),
    ("in",      "A",  ["A","B"], True),
    ("not_in",  "C",  ["A","B"], True),
])
def test_operators(operator, field_val, compare_val, expected_pass):
    payload = {"test_field": field_val}
    rule    = {
        "id": "op_test", "description": "op test", "priority": 1,
        "condition": {"field": "test_field", "operator": operator, "value": compare_val},
        "on_fail": "reject",
    }
    engine = RulesEngine(payload)
    result = engine.evaluate_rule(rule)
    assert result.passed == expected_pass


# ── Missing field ───────────────────────────────────────────────────────────

def test_missing_field_fails_rule():
    payload = {"other_field": 100}
    rule    = {
        "id": "missing_test", "description": "test", "priority": 1,
        "condition": {"field": "credit_score", "operator": "gte", "value": 600},
        "on_fail": "reject",
    }
    engine = RulesEngine(payload)
    result = engine.evaluate_rule(rule)
    assert not result.passed
    assert "missing" in result.reason.lower()


# ── Value expression ────────────────────────────────────────────────────────

def test_value_expression_resolves():
    payload = {"loan_amount": 200000, "annual_income": 50000}
    rule    = {
        "id": "expr_test", "description": "test expr", "priority": 1,
        "condition": {
            "field": "loan_amount",
            "operator": "lte",
            "value_expression": "annual_income * 5",  # = 250000
        },
        "on_fail": "reject",
    }
    engine = RulesEngine(payload)
    result = engine.evaluate_rule(rule)
    assert result.passed   # 200000 <= 250000


def test_value_expression_fails_correctly():
    payload = {"loan_amount": 300000, "annual_income": 50000}
    rule    = {
        "id": "expr_fail", "description": "test expr fail", "priority": 1,
        "condition": {
            "field": "loan_amount",
            "operator": "lte",
            "value_expression": "annual_income * 5",  # = 250000
        },
        "on_fail": "reject",
    }
    engine = RulesEngine(payload)
    result = engine.evaluate_rule(rule)
    assert not result.passed   # 300000 > 250000
