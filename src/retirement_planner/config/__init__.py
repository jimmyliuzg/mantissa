"""Configuration loading, validation, and schema support."""

from .validation import (
    CURRENT_SCHEMA_VERSION,
    ValidationIssue,
    ValidationResult,
    validate_config,
    schema_dict,
)

__all__ = [
    "CURRENT_SCHEMA_VERSION", "ValidationIssue", "ValidationResult",
    "validate_config", "schema_dict",
]
