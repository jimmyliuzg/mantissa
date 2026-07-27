"""Tests for cash-flow-driven savings allocation (contribution priority)."""
import json
import pytest

from retirement_planner.engine import RetirementPlanner, WithdrawalEngine, CostBasisTracker
from retirement_planner.models import Account


def _account(id, priority=0, cap=0.0, match=0.0, match_limit=0.0,
             tax_treatment="pre_tax"):
    return Account(
        id=id,
        name=id,
        account_type="401k" if tax_treatment == "pre_tax" else "brokerage",
        tax_treatment=tax_treatment,
        balance=1000.0,
        contribution_priority=priority,
        annual_contribution_cap=cap,
        employer_match=match,
        employer_match_limit=match_limit,
    )


def _engine(accounts):
    return WithdrawalEngine({a.id: a for a in accounts}, CostBasisTracker())


class TestContribute:
    def test_priority_order_and_caps(self):
        accounts = [
            _account("k401", priority=1, cap=23500),
            _account("hsa", priority=2, cap=8300),
            _account("brokerage", priority=4, cap=0, tax_treatment="taxable"),
        ]
        engine = _engine(accounts)
        balances = {a.id: 0.0 for a in accounts}

        contribs = engine.contribute(balances, 50_000)

        assert contribs["k401"] == 23500
        assert contribs["hsa"] == 8300
        # Remainder flows to unlimited brokerage
        assert contribs["brokerage"] == pytest.approx(50_000 - 23500 - 8300)
        assert balances["k401"] == 23500
        assert balances["hsa"] == 8300

    def test_limited_savings_stops_at_first_cap(self):
        accounts = [
            _account("k401", priority=1, cap=23500),
            _account("hsa", priority=2, cap=8300),
        ]
        engine = _engine(accounts)
        balances = {a.id: 0.0 for a in accounts}

        contribs = engine.contribute(balances, 10_000)

        assert contribs == {"k401": 10_000}
        assert balances["hsa"] == 0.0

    def test_priority_zero_skipped(self):
        accounts = [
            _account("k401", priority=0, cap=23500),
            _account("hsa", priority=1, cap=8300),
        ]
        engine = _engine(accounts)
        balances = {a.id: 0.0 for a in accounts}

        contribs = engine.contribute(balances, 50_000)

        assert "k401" not in contribs
        # Leftover savings with no eligible account stays undistributed
        assert contribs["hsa"] == 8300

    def test_no_contribution_when_no_savings(self):
        accounts = [_account("k401", priority=1, cap=23500)]
        engine = _engine(accounts)
        balances = {"k401": 0.0}

        assert engine.contribute(balances, 0.0) == {}
        assert engine.contribute(balances, -500.0) == {}

    def test_employer_match_added_on_top(self):
        accounts = [
            _account("k401", priority=1, cap=23500, match=0.5, match_limit=825),
        ]
        engine = _engine(accounts)
        balances = {"k401": 0.0}

        contribs = engine.contribute(balances, 30_000)

        employee = 23500
        match = min(employee, 825) * 0.5
        assert contribs["k401"] == pytest.approx(employee + match)
        assert balances["k401"] == pytest.approx(employee + match)

    def test_taxable_contribution_increases_basis(self):
        tracker = CostBasisTracker()
        acct = _account("brokerage", priority=1, cap=0, tax_treatment="taxable")
        engine = WithdrawalEngine({acct.id: acct}, tracker)
        balances = {"brokerage": 0.0}

        engine.contribute(balances, 12_000)

        assert tracker.get_basis("brokerage") == pytest.approx(12_000)


class TestConfigParsing:
    def _write_config(self, tmp_path, accounts, savings_order=None):
        config = {
            "name": "t",
            "primary": {"name": "P", "birth_date": "1990-01-01",
                        "retirement_date": "2050-01-01"},
            "spouse": {"name": "S", "birth_date": "1990-01-01",
                       "retirement_date": "2050-01-01"},
            "accounts": accounts,
        }
        if savings_order is not None:
            config["savings_order"] = savings_order
        path = tmp_path / "cfg.json"
        path.write_text(json.dumps(config))
        return str(path)

    def test_savings_order_sets_priorities(self, tmp_path):
        path = self._write_config(
            tmp_path,
            [
                {"id": "a", "name": "a", "type": "401k", "balance": 0},
                {"id": "b", "name": "b", "type": "hsa", "balance": 0},
                {"id": "c", "name": "c", "type": "brokerage", "balance": 0},
            ],
            savings_order=["b", "a"],
        )
        planner = RetirementPlanner.from_config(path)
        assert planner.accounts["b"].contribution_priority == 1
        assert planner.accounts["a"].contribution_priority == 2
        # Not in savings_order → no auto-contribution
        assert planner.accounts["c"].contribution_priority == 0
        assert planner.scenario.savings_order == ["b", "a"]

    def test_explicit_priority_beats_savings_order(self, tmp_path):
        path = self._write_config(
            tmp_path,
            [
                {"id": "a", "name": "a", "type": "401k", "balance": 0,
                 "contribution_priority": 5},
            ],
            savings_order=["a"],
        )
        planner = RetirementPlanner.from_config(path)
        assert planner.accounts["a"].contribution_priority == 5

    def test_legacy_monthly_contribution_backward_compat(self, tmp_path):
        path = self._write_config(
            tmp_path,
            [
                {"id": "k401", "name": "k", "type": "401k", "balance": 0,
                 "monthly_contribution": 1625, "employer_match": 0.5,
                 "employer_match_limit": 825},
            ],
        )
        planner = RetirementPlanner.from_config(path)
        acct = planner.accounts["k401"]
        assert acct.contribution_priority == 1
        assert acct.annual_contribution_cap == pytest.approx(1625 * 12)
        assert acct.employer_match == 0.5
        assert acct.employer_match_limit == 825

    def test_new_fields_parsed(self, tmp_path):
        path = self._write_config(
            tmp_path,
            [
                {"id": "hsa", "name": "h", "type": "hsa", "balance": 0,
                 "contribution_priority": 2, "annual_contribution_cap": 8300},
            ],
        )
        planner = RetirementPlanner.from_config(path)
        acct = planner.accounts["hsa"]
        assert acct.contribution_priority == 2
        assert acct.annual_contribution_cap == 8300
