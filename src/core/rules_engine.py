"""
Rules Engine
------------
Evaluates a list of rule definitions (from config) against a request payload.
Each rule specifies a condition, what to do on failure (reject / manual_review / flag),
and a priority. Rules are evaluated in priority order.

Supports operators: eq, neq, gt, gte, lt, lte, in, not_in, contains
Supports value_expression for dynamic thresholds (e.g., "annual_income * 5")
"""
import re
from typing import Any, Dict, List, Tuple


OPERATORS = {
    "eq":       lambda a, b: a == b,
    "neq":      lambda a, b: a != b,
    "gt":       lambda a, b: a > b,
    "gte":      lambda a, b: a >= b,
    "lt":       lambda a, b: a < b,
    "lte":      lambda a, b: a <= b,
    "in":       lambda a, b: a in b,
    "not_in":   lambda a, b: a not in b,
    "contains": lambda a, b: b in str(a),
}


class RuleResult:
    def __init__(self, rule_id: str, passed: bool, reason: str,
                 field: str = None, value_checked=None, action_on_fail: str = None):
        self.rule_id       = rule_id
        self.passed        = passed
        self.reason        = reason
        self.field         = field
        self.value_checked = value_checked
        self.action_on_fail= action_on_fail  # reject / manual_review / flag

    def to_dict(self):
        return {
            "rule_id":        self.rule_id,
            "passed":         self.passed,
            "reason":         self.reason,
            "field":          self.field,
            "value_checked":  self.value_checked,
            "action_on_fail": self.action_on_fail,
        }


class RulesEngine:
    def __init__(self, payload: Dict[str, Any]):
        self.payload = payload

    def _resolve_value(self, rule_condition: Dict) -> Any:
        """
        Resolve the comparison value. Supports:
        - Static 'value' field
        - Dynamic 'value_expression' using payload fields (e.g., 'annual_income * 5')
        """
        if "value_expression" in rule_condition:
            expr = rule_condition["value_expression"]
            # Safe evaluation: substitute payload field names with their values
            safe_expr = expr
            for key, val in self.payload.items():
                if isinstance(val, (int, float)):
                    safe_expr = re.sub(rf'\b{re.escape(key)}\b', str(val), safe_expr)
            try:
                return eval(safe_expr, {"__builtins__": {}})
            except Exception as e:
                raise ValueError(f"Failed to evaluate expression '{expr}': {e}")
        return rule_condition.get("value")

    def evaluate_rule(self, rule: Dict) -> RuleResult:
        """Evaluate a single rule definition against the payload."""
        rule_id     = rule.get("id", "unknown")
        description = rule.get("description", "")
        condition   = rule.get("condition", {})
        on_fail     = rule.get("on_fail", "reject")

        field    = condition.get("field")
        operator = condition.get("operator")

        # Check field exists in payload
        if field not in self.payload:
            return RuleResult(
                rule_id=rule_id,
                passed=False,
                reason=f"Field '{field}' missing from payload",
                field=field,
                action_on_fail=on_fail,
            )

        actual_value  = self.payload[field]
        compare_value = self._resolve_value(condition)
        op_fn         = OPERATORS.get(operator)

        if not op_fn:
            return RuleResult(
                rule_id=rule_id,
                passed=False,
                reason=f"Unknown operator '{operator}'",
                field=field,
                action_on_fail=on_fail,
            )

        try:
            passed = op_fn(actual_value, compare_value)
        except Exception as e:
            return RuleResult(
                rule_id=rule_id,
                passed=False,
                reason=f"Evaluation error: {e}",
                field=field,
                action_on_fail=on_fail,
            )

        reason = (
            f"{description} — "
            f"{field}={actual_value} {operator} {compare_value} → {'PASS' if passed else 'FAIL'}"
        )
        return RuleResult(
            rule_id=rule_id,
            passed=passed,
            reason=reason,
            field=field,
            value_checked=actual_value,
            action_on_fail=on_fail,
        )

    def evaluate_all(self, rules: List[Dict]) -> Tuple[str, List[RuleResult]]:
        """
        Evaluate all rules sorted by priority.
        Returns (overall_outcome, list_of_results).
        Overall outcome: 'approve' | 'reject' | 'manual_review'
        
        Rejection takes precedence over manual_review.
        All rules are evaluated (no short-circuit) to produce full audit trace.
        """
        sorted_rules = sorted(rules, key=lambda r: r.get("priority", 99))
        results      = [self.evaluate_rule(r) for r in sorted_rules]

        outcome = "approve"
        for result in results:
            if not result.passed:
                if result.action_on_fail == "reject":
                    outcome = "reject"
                    break                          # Rejection is final
                elif result.action_on_fail == "manual_review" and outcome != "reject":
                    outcome = "manual_review"

        return outcome, results
