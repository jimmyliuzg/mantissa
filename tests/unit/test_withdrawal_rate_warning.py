"""Tests for the withdrawal_rate / withdrawal_strategy warning (issue #1).

`withdrawal_rate` is consulted only by the `percent_of_portfolio` and
`floor_ceiling` strategies. When a user sets it under any other
strategy (including the default `fixed`), it has no effect. Surface
this as a validation warning rather than letting it silently no-op.
"""
import pytest

from retirement_planner.config.validation import validate_config


def _base_config():
    return {
        "schema_version": 1,
        "primary": {"name": "P", "birth_date": "1970-01-01", "retirement_date": "2035-01-01"},
        "spouse": {"name": "S", "birth_date": "1972-01-01", "retirement_date": "2035-01-01"},
        "accounts": [{"id": "a", "name": "B", "type": "brokerage", "balance": 1000}],
    }


def test_withdrawal_rate_with_fixed_strategy_warns():
    cfg = _base_config()
    cfg["withdrawal_rate"] = 0.04
    cfg["withdrawal_strategy"] = "fixed"
    result = validate_config(cfg)
    assert result.valid  # warning, not error
    warnings = [w for w in result.warnings if w.path == "$.withdrawal_rate"]
    assert len(warnings) == 1
    assert "percent_of_portfolio" in warnings[0].message
    assert "floor_ceiling" in warnings[0].message


def test_withdrawal_rate_with_unset_strategy_warns():
    # Default strategy is `fixed`, so a user setting only the rate
    # without setting the strategy also triggers the warning.
    cfg = _base_config()
    cfg["withdrawal_rate"] = 0.04
    result = validate_config(cfg)
    warnings = [w for w in result.warnings if w.path == "$.withdrawal_rate"]
    assert len(warnings) == 1


def test_withdrawal_rate_with_percent_of_portfolio_does_not_warn():
    cfg = _base_config()
    cfg["withdrawal_rate"] = 0.04
    cfg["withdrawal_strategy"] = "percent_of_portfolio"
    result = validate_config(cfg)
    warnings = [w for w in result.warnings if w.path == "$.withdrawal_rate"]
    assert warnings == []


def test_withdrawal_rate_with_floor_ceiling_does_not_warn():
    cfg = _base_config()
    cfg["withdrawal_rate"] = 0.04
    cfg["withdrawal_strategy"] = "floor_ceiling"
    result = validate_config(cfg)
    warnings = [w for w in result.warnings if w.path == "$.withdrawal_rate"]
    assert warnings == []


def test_no_withdrawal_rate_does_not_warn():
    cfg = _base_config()
    result = validate_config(cfg)
    warnings = [w for w in result.warnings if w.path == "$.withdrawal_rate"]
    assert warnings == []
