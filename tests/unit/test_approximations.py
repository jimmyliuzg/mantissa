"""Tests for approximation and warning metadata (Phase 3.4)."""
from retirement_planner.approximations import (
    ApproximationCategory, ApproximationWarning, ApproximationTracker,
    AGGREGATE_BASIS_WARNING, DETERMINISTIC_TAXES_WARNING,
    EXPERIMENTAL_OPTIMIZER_WARNING, DETERMINISTIC_RETURNS_WARNING,
)


# ---------------------------------------------------------------------------
# ApproximationCategory enum
# ---------------------------------------------------------------------------
def test_category_values_are_strings():
    assert isinstance(ApproximationCategory.AGGREGATE_BASIS.value, str)
    assert ApproximationCategory.AGGREGATE_BASIS.value == "aggregate_basis"


def test_all_categories_exist():
    expected = [
        "aggregate_basis", "simplified_deterministic_taxes",
        "historical_bond_data", "simplified_amt", "simplified_estate_tax",
        "experimental_optimizer", "deterministic_returns",
        "social_security_modeling", "healthcare_inflation",
    ]
    actual = [c.value for c in ApproximationCategory]
    assert sorted(actual) == sorted(expected)


# ---------------------------------------------------------------------------
# ApproximationWarning dataclass
# ---------------------------------------------------------------------------
def test_warning_defaults():
    w = ApproximationWarning(
        category=ApproximationCategory.AGGREGATE_BASIS,
        message="test message",
    )
    assert w.severity == "warning"
    assert w.source == ""
    assert w.year is None


def test_warning_as_dict_minimal():
    w = ApproximationWarning(
        category=ApproximationCategory.AGGREGATE_BASIS,
        message="test",
    )
    d = w.as_dict()
    assert d["category"] == "aggregate_basis"
    assert d["message"] == "test"
    assert d["severity"] == "warning"
    assert "source" not in d
    assert "year" not in d


def test_warning_as_dict_with_all_fields():
    w = ApproximationWarning(
        category=ApproximationCategory.EXPERIMENTAL_OPTIMIZER,
        message="experimental",
        severity="critical",
        source="optimizer",
        year=2036,
    )
    d = w.as_dict()
    assert d["source"] == "optimizer"
    assert d["year"] == 2036
    assert d["severity"] == "critical"


def test_warning_str_format():
    w = ApproximationWarning(
        category=ApproximationCategory.AGGREGATE_BASIS,
        message="aggregate basis used",
        year=2036,
    )
    s = str(w)
    assert "[WARNING]" in s
    assert "aggregate_basis" in s
    assert "(year 2036)" in s
    assert "aggregate basis used" in s


def test_warning_str_info_severity():
    w = ApproximationWarning(
        category=ApproximationCategory.DETERMINISTIC_RETURNS,
        message="fixed returns",
        severity="info",
    )
    assert "[INFO]" in str(w)


# ---------------------------------------------------------------------------
# Pre-defined warnings
# ---------------------------------------------------------------------------
def test_predefined_warnings_have_correct_categories():
    assert AGGREGATE_BASIS_WARNING.category == ApproximationCategory.AGGREGATE_BASIS
    assert DETERMINISTIC_TAXES_WARNING.category == ApproximationCategory.SIMPLIFIED_DETERMINISTIC_TAXES
    assert EXPERIMENTAL_OPTIMIZER_WARNING.category == ApproximationCategory.EXPERIMENTAL_OPTIMIZER
    assert DETERMINISTIC_RETURNS_WARNING.category == ApproximationCategory.DETERMINISTIC_RETURNS


def test_predefined_warnings_have_sources():
    assert AGGREGATE_BASIS_WARNING.source != ""
    assert DETERMINISTIC_TAXES_WARNING.source != ""
    assert EXPERIMENTAL_OPTIMIZER_WARNING.source != ""


def test_experimental_optimizer_is_critical():
    assert EXPERIMENTAL_OPTIMIZER_WARNING.severity == "critical"


# ---------------------------------------------------------------------------
# ApproximationTracker
# ---------------------------------------------------------------------------
def test_tracker_add_deduplicates():
    tracker = ApproximationTracker()
    tracker.add(AGGREGATE_BASIS_WARNING)
    tracker.add(AGGREGATE_BASIS_WARNING)  # duplicate
    assert len(tracker.warnings) == 1


def test_tracker_add_different_years():
    tracker = ApproximationTracker()
    w1 = ApproximationWarning(
        category=ApproximationCategory.AGGREGATE_BASIS,
        message="year 2030", year=2030,
    )
    w2 = ApproximationWarning(
        category=ApproximationCategory.AGGREGATE_BASIS,
        message="year 2031", year=2031,
    )
    tracker.add(w1)
    tracker.add(w2)
    assert len(tracker.warnings) == 2  # different years = not duplicate


def test_tracker_add_all():
    tracker = ApproximationTracker()
    tracker.add_all([AGGREGATE_BASIS_WARNING, DETERMINISTIC_TAXES_WARNING])
    assert len(tracker.warnings) == 2


def test_tracker_for_year():
    tracker = ApproximationTracker()
    tracker.add(AGGREGATE_BASIS_WARNING)  # year=None (all years)
    w_year = ApproximationWarning(
        category=ApproximationCategory.EXPERIMENTAL_OPTIMIZER,
        message="specific", year=2036,
    )
    tracker.add(w_year)

    # Year None applies to all years
    assert len(tracker.for_year(2036)) == 2
    assert len(tracker.for_year(2040)) == 1  # only the None-year warning


def test_tracker_by_severity():
    tracker = ApproximationTracker()
    tracker.add(DETERMINISTIC_RETURNS_WARNING)  # info
    tracker.add(EXPERIMENTAL_OPTIMIZER_WARNING)  # critical
    assert len(tracker.by_severity("info")) == 1
    assert len(tracker.by_severity("critical")) == 1
    assert len(tracker.by_severity("warning")) == 0


def test_tracker_has_critical():
    tracker = ApproximationTracker()
    assert not tracker.has_critical()
    tracker.add(EXPERIMENTAL_OPTIMIZER_WARNING)
    assert tracker.has_critical()


def test_tracker_summary():
    tracker = ApproximationTracker()
    assert "No approximations" in tracker.summary()
    tracker.add(AGGREGATE_BASIS_WARNING)
    s = tracker.summary()
    assert "1 total" in s
    assert "aggregate_basis" in s


def test_tracker_as_dict():
    tracker = ApproximationTracker()
    tracker.add(AGGREGATE_BASIS_WARNING)
    d = tracker.as_dict()
    assert d["count"] == 1
    assert d["warnings"][0]["category"] == "aggregate_basis"


# ---------------------------------------------------------------------------
# Integration: SimulationState with approximations
# ---------------------------------------------------------------------------
def test_simulation_state_has_approximations_field():
    from retirement_planner.projection.state import SimulationState
    state = SimulationState(year=2036, primary_age=40, spouse_age=38)
    assert state.approximations == []
    state.approximations.append(AGGREGATE_BASIS_WARNING)
    assert len(state.approximations) == 1


def test_simulation_state_as_dict_includes_approximations():
    from retirement_planner.projection.state import SimulationState
    state = SimulationState(year=2036, primary_age=40, spouse_age=38)
    state.approximations.append(AGGREGATE_BASIS_WARNING)
    d = state.as_dict()
    assert "approximations" in d
    assert len(d["approximations"]) == 1
    assert d["approximations"][0]["category"] == "aggregate_basis"


# ---------------------------------------------------------------------------
# Integration: DecisionTrace with approximations
# ---------------------------------------------------------------------------
def test_decision_trace_has_approximations():
    from retirement_planner.optimizer import DecisionTrace, YearDecision
    trace = DecisionTrace(
        year=2036,
        selected=YearDecision(),
        selected_label="test",
    )
    assert trace.approximations == []
    trace.approximations.append(EXPERIMENTAL_OPTIMIZER_WARNING)
    assert len(trace.approximations) == 1


def test_decision_trace_explain_shows_approximations():
    from retirement_planner.optimizer import DecisionTrace, YearDecision
    trace = DecisionTrace(
        year=2036,
        selected=YearDecision(),
        selected_label="test",
        reasons=["reason"],
    )
    trace.approximations.append(EXPERIMENTAL_OPTIMIZER_WARNING)
    explanation = trace.explain()
    assert "Approximations:" in explanation
    assert "experimental_optimizer" in explanation
