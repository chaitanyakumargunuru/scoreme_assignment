"""
Schema Validator
----------------
Validates incoming request payloads against the schema defined in workflow config.
Returns structured errors rather than raising exceptions, so callers can decide handling.
"""
from typing import Any, Dict, List, Tuple


TYPE_MAP = {
    "string":  str,
    "integer": int,
    "number":  (int, float),
    "boolean": bool,
    "array":   list,
    "object":  dict,
}


class SchemaValidator:
    def __init__(self, schema: Dict[str, Any]):
        self.required_fields: List[str] = schema.get("required", [])
        self.field_types: Dict[str, str] = schema.get("types", {})
        self.constraints: Dict[str, Any] = schema.get("constraints", {})

    def validate(self, payload: Dict[str, Any]) -> Tuple[bool, List[str]]:
        """
        Validate payload against schema.
        Returns (is_valid: bool, errors: List[str])
        """
        errors = []
        type_failed_fields = set()  # Track fields that failed type check

        # 1. Check all required fields are present
        for field in self.required_fields:
            if field not in payload or payload[field] is None:
                errors.append(f"Missing required field: '{field}'")

        # 2. Check type correctness for present fields
        for field, expected_type in self.field_types.items():
            if field in payload and payload[field] is not None:
                python_type = TYPE_MAP.get(expected_type)
                if python_type and not isinstance(payload[field], python_type):
                    actual = type(payload[field]).__name__
                    errors.append(
                        f"Field '{field}' expected type '{expected_type}', got '{actual}'"
                    )
                    type_failed_fields.add(field)  # Mark: skip constraints for this field

        # 3. Check value constraints — only for fields that passed type check
        for field, constraint in self.constraints.items():
            if field in type_failed_fields:
                continue  # Don't compare strings against numeric min/max
            if field not in payload or payload[field] is None:
                continue
            value = payload[field]

            try:
                if "min" in constraint and value < constraint["min"]:
                    errors.append(
                        f"Field '{field}' value {value} is below minimum {constraint['min']}"
                    )
                if "max" in constraint and value > constraint["max"]:
                    errors.append(
                        f"Field '{field}' value {value} exceeds maximum {constraint['max']}"
                    )
            except TypeError:
                errors.append(f"Field '{field}' has incompatible type for range check")

            if "allowed_values" in constraint and value not in constraint["allowed_values"]:
                errors.append(
                    f"Field '{field}' value '{value}' not in allowed values: "
                    f"{constraint['allowed_values']}"
                )

        return (len(errors) == 0, errors)