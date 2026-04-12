"""Structured output management with JSON schema validation."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass


@dataclass
class SchemaConstraint:
    """Describes the JSON schema constraint for LLM output."""

    schema: dict           # JSON Schema object
    strict: bool = True    # If True, retry on validation failure
    max_retries: int = 2
    extract_json: bool = True  # Extract JSON from markdown code blocks


class StructuredOutputManager:
    """Manages structured (schema-constrained) output from LLM.

    When a JSON schema is specified:
    1. Adds schema instruction to the system prompt
    2. Post-validates the LLM output against the schema
    3. Retries if validation fails (up to max_retries)
    4. Extracts JSON from markdown code blocks if needed
    """

    def __init__(self, constraint: SchemaConstraint | None = None) -> None:
        self._constraint = constraint

    @property
    def active(self) -> bool:
        return self._constraint is not None

    @property
    def constraint(self) -> SchemaConstraint | None:
        return self._constraint

    def set_schema(self, schema: dict, strict: bool = True) -> None:
        """Set a new schema constraint."""
        self._constraint = SchemaConstraint(schema=schema, strict=strict)

    def clear(self) -> None:
        """Remove the current schema constraint."""
        self._constraint = None

    def build_instruction(self) -> str:
        """Generate instruction text to append to system prompt."""
        if not self._constraint:
            return ""
        schema_str = json.dumps(self._constraint.schema, indent=2)
        return (
            "\n\nIMPORTANT: Your response MUST be valid JSON matching this schema:\n"
            f"```json\n{schema_str}\n```\n"
            "Respond with ONLY the JSON object, no other text."
        )

    def extract_json(self, text: str) -> str | None:
        """Extract JSON from text, handling markdown code blocks.

        Tries direct parse first, then extracts from ````` blocks.
        Returns the raw JSON string if found, else ``None``.
        """
        stripped = text.strip()

        # Try direct parse
        try:
            json.loads(stripped)
            return stripped
        except (json.JSONDecodeError, ValueError):
            pass

        # Try extracting from ```json ... ``` or ``` ... ```
        pattern = r"```(?:json)?\s*\n?([\s\S]*?)\n?\s*```"
        matches = re.findall(pattern, stripped)
        for match in matches:
            candidate = match.strip()
            try:
                json.loads(candidate)
                return candidate
            except (json.JSONDecodeError, ValueError):
                continue

        return None

    def validate(self, text: str) -> tuple[bool, dict | list | None, str]:
        """Validate output against schema.

        Returns ``(is_valid, parsed_data, error_message)``.
        """
        if not self._constraint:
            return True, None, ""

        raw_json = self.extract_json(text) if self._constraint.extract_json else text.strip()
        if raw_json is None:
            return False, None, "No valid JSON found in response"

        try:
            data = json.loads(raw_json)
        except (json.JSONDecodeError, ValueError) as exc:
            return False, None, f"JSON parse error: {exc}"

        errors = self._validate_value(data, self._constraint.schema)
        if errors:
            return False, data, "; ".join(errors)

        return True, data, ""

    # ------------------------------------------------------------------
    # Lightweight recursive schema validation
    # ------------------------------------------------------------------

    def _validate_value(self, value: object, schema: dict, path: str = "") -> list[str]:
        """Recursive schema validation supporting type, required, enum,
        properties, items, and const."""
        errors: list[str] = []

        # type check
        expected_type = schema.get("type")
        if expected_type:
            if not self._check_type(value, expected_type):
                errors.append(
                    f"{path or 'root'}: expected type '{expected_type}', "
                    f"got '{type(value).__name__}'"
                )
                return errors  # no point validating further

        # enum
        if "enum" in schema:
            if value not in schema["enum"]:
                errors.append(
                    f"{path or 'root'}: value {value!r} not in enum {schema['enum']}"
                )

        # const
        if "const" in schema:
            if value != schema["const"]:
                errors.append(
                    f"{path or 'root'}: expected const {schema['const']!r}, got {value!r}"
                )

        # object properties
        if expected_type == "object" and isinstance(value, dict):
            # required
            for req in schema.get("required", []):
                if req not in value:
                    errors.append(f"{path}.{req}: required field missing")

            # validate each property
            props = schema.get("properties", {})
            for key, prop_schema in props.items():
                if key in value:
                    errors.extend(
                        self._validate_value(value[key], prop_schema, f"{path}.{key}")
                    )

        # array items
        if expected_type == "array" and isinstance(value, list):
            items_schema = schema.get("items")
            if items_schema:
                for i, item in enumerate(value):
                    errors.extend(
                        self._validate_value(item, items_schema, f"{path}[{i}]")
                    )

        return errors

    @staticmethod
    def _check_type(value: object, expected: str) -> bool:
        """Check if *value* matches the JSON Schema *expected* type."""
        type_map: dict[str, type | tuple[type, ...]] = {
            "string": str,
            "number": (int, float),
            "integer": int,
            "boolean": bool,
            "array": list,
            "object": dict,
            "null": type(None),
        }
        py_type = type_map.get(expected)
        if py_type is None:
            return True  # unknown type, skip
        # In Python bool is a subclass of int; exclude booleans from integer/number
        if expected in ("integer", "number") and isinstance(value, bool):
            return False
        return isinstance(value, py_type)
