"""Lightweight JSON Schema validator for tool arguments."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ValidationError:
    field: str
    message: str
    expected_type: str
    actual_value: Any


@dataclass
class ValidationResult:
    valid: bool
    errors: list[ValidationError] = field(default_factory=list)


class SchemaValidator:
    """Validates tool arguments against JSON Schema before execution."""

    def validate(self, arguments: dict, schema: dict) -> ValidationResult:
        """Validate arguments against a tool's parameter schema.

        Checks:
        1. Required fields present
        2. Types match (string, integer, number, boolean, array, object)
        3. No unknown fields (if additionalProperties is false in schema)
        4. Enum values are valid (if enum is specified)
        5. String length constraints (minLength, maxLength)
        6. Numeric range constraints (minimum, maximum)
        """
        errors: list[ValidationError] = []
        properties = schema.get("properties", {})
        required = schema.get("required", [])

        # Check required fields
        for field_name in required:
            if field_name not in arguments:
                errors.append(
                    ValidationError(
                        field=field_name,
                        message=f"Required field '{field_name}' is missing",
                        expected_type=properties.get(field_name, {}).get("type", "unknown"),
                        actual_value=None,
                    )
                )

        # Check unknown fields
        if schema.get("additionalProperties") is False:
            for key in arguments:
                if key not in properties:
                    errors.append(
                        ValidationError(
                            field=key,
                            message=f"Unknown field '{key}' is not allowed",
                            expected_type="N/A",
                            actual_value=arguments[key],
                        )
                    )

        # Validate each provided field
        for field_name, value in arguments.items():
            if field_name in properties:
                field_errors = self._validate_field(
                    field_name, value, properties[field_name]
                )
                errors.extend(field_errors)

        return ValidationResult(valid=len(errors) == 0, errors=errors)

    def _validate_type(self, value: Any, expected_type: str) -> bool:
        """Check if value matches the expected JSON Schema type."""
        if expected_type == "string":
            return isinstance(value, str)
        elif expected_type == "integer":
            return isinstance(value, int) and not isinstance(value, bool)
        elif expected_type == "number":
            return isinstance(value, (int, float)) and not isinstance(value, bool)
        elif expected_type == "boolean":
            return isinstance(value, bool)
        elif expected_type == "array":
            return isinstance(value, list)
        elif expected_type == "object":
            return isinstance(value, dict)
        return True

    def _validate_field(
        self, name: str, value: Any, field_schema: dict
    ) -> list[ValidationError]:
        """Validate a single field against its schema."""
        errors: list[ValidationError] = []
        expected_type = field_schema.get("type")

        # Type check
        if expected_type and not self._validate_type(value, expected_type):
            errors.append(
                ValidationError(
                    field=name,
                    message=f"Expected type '{expected_type}', got '{type(value).__name__}'",
                    expected_type=expected_type,
                    actual_value=value,
                )
            )
            return errors  # Skip further checks if type is wrong

        # Enum check
        if "enum" in field_schema:
            if value not in field_schema["enum"]:
                errors.append(
                    ValidationError(
                        field=name,
                        message=f"Value '{value}' not in allowed values: {field_schema['enum']}",
                        expected_type=expected_type or "enum",
                        actual_value=value,
                    )
                )

        # String constraints
        if expected_type == "string" and isinstance(value, str):
            if "minLength" in field_schema and len(value) < field_schema["minLength"]:
                errors.append(
                    ValidationError(
                        field=name,
                        message=f"String length {len(value)} is less than minimum {field_schema['minLength']}",
                        expected_type="string",
                        actual_value=value,
                    )
                )
            if "maxLength" in field_schema and len(value) > field_schema["maxLength"]:
                errors.append(
                    ValidationError(
                        field=name,
                        message=f"String length {len(value)} exceeds maximum {field_schema['maxLength']}",
                        expected_type="string",
                        actual_value=value,
                    )
                )

        # Numeric constraints
        if expected_type in ("integer", "number") and isinstance(value, (int, float)):
            if "minimum" in field_schema and value < field_schema["minimum"]:
                errors.append(
                    ValidationError(
                        field=name,
                        message=f"Value {value} is less than minimum {field_schema['minimum']}",
                        expected_type=expected_type,
                        actual_value=value,
                    )
                )
            if "maximum" in field_schema and value > field_schema["maximum"]:
                errors.append(
                    ValidationError(
                        field=name,
                        message=f"Value {value} exceeds maximum {field_schema['maximum']}",
                        expected_type=expected_type,
                        actual_value=value,
                    )
                )

        # Nested object validation
        if expected_type == "object" and isinstance(value, dict):
            if "properties" in field_schema:
                nested_result = SchemaValidator().validate(value, field_schema)
                for err in nested_result.errors:
                    errors.append(
                        ValidationError(
                            field=f"{name}.{err.field}",
                            message=err.message,
                            expected_type=err.expected_type,
                            actual_value=err.actual_value,
                        )
                    )

        return errors
