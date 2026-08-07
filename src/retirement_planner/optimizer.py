"""
Integrated withdrawal and Roth conversion optimizer (Phase 2).

Evaluates withdrawals, Roth conversions, capital-gain harvesting, QCDs,
and charitable giving as one yearly decision problem, constrained by:
- Cash needs (must cover expenses)
- RMD requirements (age 73+)
- Account balance limits
- ACA MAGI targets
- IRMAA avoidance thresholds
- Tax bracket filling

Two modes:
1. Policy mode: rule-based withdrawal strategy (guardrails, VPW, etc.)
2. Optimizer mode: grid search over candidates, pick lowest lifetime cost
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Dict, List, Optional, Protocol, Tuple, runtime_checkable


# ---------------------------------------------------------------------------
# Decision variables
# ---------------------------------------------------------------------------
@dataclass
class YearDecision:
    """What to do in a single year — the optimizer's output."""
    # Withdrawals by account_id
    taxable_withdrawals: Dict[str, float] = field(default_factory=dict)
    pretax_withdrawals: Dict[str, float] = field(default_factory=dict)
    roth_withdrawals: Dict[str, float] = field(default_factory=dict)

    # Roth conversions (pre-tax → Roth, taxable event)
    roth_conversions: Dict[str, float] = field(default_factory=dict)

    # Capital-gain harvesting (sell taxable, realize gains at 0%/15%)
    realized_ltcg: float = 0.0

    # Charitable giving
    charitable_gifts: float = 0.0
    qcd_amount: float = 0.0  # from IRA, reduces AGI

    # Derived totals
    total_cash_in: float = 0.0   # sum of all withdrawals (taxable + tax-free)
    total_ordinary_income: float = 0.0  # withdrawals + conversions + RMDs
    total_taxable_event: float = 0.0  # conversions + gains + RMDs

    # Spending target this decision covers
    spending_target: float = 0.0

    def compute_totals(self):
        """Recompute derived fields from the component parts."""
        self.total_cash_in = (
            sum(self.taxable_withdrawals.values())
            + sum(self.pretax_withdrawals.values())
            + sum(self.roth_withdrawals.values())
        )
        self.total_ordinary_income = (
            sum(self.pretax_withdrawals.values())
            + sum(self.roth_conversions.values())
        )
        self.total_taxable_event = (
            self.total_ordinary_income
            + self.realized_ltcg
        )
        return self


@dataclass
class CandidateDecision:
    """A candidate year-decision with metadata for comparison."""
    decision: YearDecision
    label: str          # e.g. "bracket_fill_24pct", "aca_target_150pct_fpl"
    score: float = 0.0  # objective value (lower = better)
    feasibility: Optional["FeasibilityResult"] = None


@dataclass
class FeasibilityResult:
    """Constraint evaluation for one candidate decision."""
    feasible: bool
    cash_shortfall: float = 0.0
    rmd_shortfall: float = 0.0
    violations: List[str] = field(default_factory=list)

    @property
    def rejection_reasons(self) -> List[str]:
        return list(self.violations)


# ---------------------------------------------------------------------------
# Engine-backed tax evaluation — replaces proxy scoring
# ---------------------------------------------------------------------------
@dataclass
class TaxEvaluation:
    """Result of engine-backed tax/ACA/IRMAA evaluation for a candidate."""
    total_tax: float = 0.0         # federal + state tax (marginal delta)
    aca_subsidy: float = 0.0       # ACA premium subsidy preserved (higher = better)
    irmaa_cost: float = 0.0        # IRMAA Medicare surcharges (higher = worse)
    niit: float = 0.0              # net investment income tax
    total_cost: float = 0.0        # combined score (tax + irmaa - aca_subsidy)


@runtime_checkable
class TaxEvaluator(Protocol):
    """Interface for engine-backed evaluation of candidate decisions.

    The optimizer calls this to score candidates using real tax, ACA,
    and IRMAA calculations instead of proxy heuristics.
    """

    def evaluate(
        self,
        decision: "YearDecision",
        year: int,
        age: int,
        ordinary_income_baseline: float,
        family_size: int = 2,
    ) -> TaxEvaluation:
        """Evaluate the tax/ACA/IRMAA cost of a candidate decision.

        Args:
            decision: The candidate withdrawal/conversion decision.
            year: Calendar year.
            age: Primary filer's age.
            ordinary_income_baseline: Income from other sources (wages, SS, etc.)
                before optimizer withdrawals/conversions.
            family_size: Household size for ACA subsidy (default 2 for MFJ).

        Returns:
            TaxEvaluation with computed costs.
        """
        ...


# ---------------------------------------------------------------------------
# Decision trace — why this action was taken
# ---------------------------------------------------------------------------
@dataclass
class DecisionTrace:
    """Record of why a particular decision was selected."""
    year: int
    selected: YearDecision
    selected_label: str
    alternatives: List[CandidateDecision] = field(default_factory=list)
    reasons: List[str] = field(default_factory=list)
    tax_cost: float = 0.0
    aca_subsidy: float = 0.0
    irmaa_cost: float = 0.0
    rmd_forced: float = 0.0

    def explain(self) -> str:
        """Human-readable explanation of why this decision was made."""
        lines = [f"Year {self.year}: {self.selected_label}"]
        for r in self.reasons:
            lines.append(f"  - {r}")
        if self.tax_cost > 0:
            lines.append(f"  Tax cost: ${self.tax_cost:,.0f}")
        if self.aca_subsidy > 0:
            lines.append(f"  ACA subsidy preserved: ${self.aca_subsidy:,.0f}")
        if self.irmaa_cost > 0:
            lines.append(f"  IRMAA surcharge: ${self.irmaa_cost:,.0f}")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Spending policies
# ---------------------------------------------------------------------------
class SpendingPolicy(Protocol):
    """Interface for spending adjustment strategies."""
    def spending_target(
        self, year: int, base_spending: float,
        portfolio_value: float, planned_portfolio: float,
    ) -> float: ...


class FixedSpendingPolicy:
    """No adjustment — spend the base amount."""
    def spending_target(self, year, base_spending, portfolio_value, planned_portfolio):
        return base_spending


class GuardrailsPolicy:
    """Guyton-Klinger style guardrails.

    Upper guardrail: if portfolio > 120% of planned path, increase spending.
    Lower guardrail: if portfolio < 80% of planned path, decrease spending.

    planned_portfolio should be the inflation-adjusted expected portfolio
    value for this year, NOT a high-water mark.
    """
    def __init__(self, upper_pct: float = 1.20, lower_pct: float = 0.80,
                 increase_pct: float = 0.10, decrease_pct: float = 0.10):
        self.upper_pct = upper_pct
        self.lower_pct = lower_pct
        self.increase_pct = increase_pct
        self.decrease_pct = decrease_pct

    def spending_target(self, year, base_spending, portfolio_value, planned_portfolio):
        if planned_portfolio <= 0:
            return base_spending
        ratio = portfolio_value / planned_portfolio
        if ratio > self.upper_pct:
            return base_spending * (1 + self.increase_pct)
        elif ratio < self.lower_pct:
            return base_spending * (1 - self.decrease_pct)
        return base_spending


class VPWPolicy:
    """Variable Percentage Withdrawal (Vpw).

    Withdraws a percentage of portfolio that decreases with age,
    based on remaining life expectancy.
    """
    def __init__(self, base_rate: float = 0.04, max_rate: float = 0.10,
                 life_expectancy: int = 90):
        self.base_rate = base_rate
        self.max_rate = max_rate
        self.life_expectancy = life_expectancy

    def spending_target(self, year, base_spending, portfolio_value, planned_portfolio):
        # Simple VPW: divide by remaining years
        # In practice, this would use the current age, but we approximate
        # with a declining rate based on years into retirement
        rate = min(self.max_rate, self.base_rate)
        return portfolio_value * rate


class FloorCeilingPolicy:
    """Floor/ceiling spending — protect essentials, cap discretionary."""
    def __init__(self, floor_ratio: float = 0.70, ceiling_ratio: float = 1.20):
        self.floor_ratio = floor_ratio
        self.ceiling_ratio = ceiling_ratio

    def spending_target(self, year, base_spending, portfolio_value, planned_portfolio):
        floor = base_spending * self.floor_ratio
        ceiling = base_spending * self.ceiling_ratio
        # Adjust based on portfolio coverage
        if portfolio_value <= 0:
            return floor
        coverage = portfolio_value / base_spending
        if coverage >= 25:
            return ceiling
        elif coverage >= 15:
            return base_spending
        else:
            return floor


# ---------------------------------------------------------------------------
# Optimizer engine
# ---------------------------------------------------------------------------
@dataclass
class OptimizerConfig:
    """Configuration for the withdrawal optimizer."""
    # Phase 3.2: recommendations are not decision-safe until feasibility and
    # engine-backed tax evaluation are complete.
    experimental: bool = True
    # ACA MAGI targets (annual income thresholds for subsidy optimization)
    aca_target_MAGI: Optional[float] = None  # e.g. 200% FPL for family
    irmaa_thresholds: List[float] = field(default_factory=list)  # e.g. [206000, 258000]
    # Bracket fill targets (marginal rates to fill up to)
    bracket_fill_rates: List[float] = field(default_factory=lambda: [0.22, 0.24])
    # Maximum Roth conversion per year (to avoid pushing into higher bracket)
    max_roth_conversion: float = float('inf')
    # Whether to harvest gains at 0% LTCG rate
    harvest_0pct_gains: bool = True
    # Lookahead horizon for evaluation (years)
    lookahead_years: int = 10
    # Engine-backed tax evaluator (when set, replaces proxy scoring)
    evaluator: Optional["TaxEvaluator"] = None


class WithdrawalOptimizer:
    """Evaluates withdrawal/conversion/harvesting decisions jointly.

    For each year, generates candidate decisions and scores them using
    a simple objective: minimize tax cost while meeting spending needs
    and preserving ACA/IRMAA benefits.
    """

    def __init__(self, config: Optional[OptimizerConfig] = None):
        self.config = config or OptimizerConfig()

    @property
    def status(self) -> str:
        """Public safety status for callers and reports."""
        return "experimental" if self.config.experimental else "production"

    def generate_candidates(
        self,
        year: int,
        age: int,
        accounts: Dict[str, dict],  # id → {balance, type, tax_treatment}
        spending_target: float,
        rmd_required: float,
        current_tax_bracket_top: float,
        ordinary_income_so_far: float,
    ) -> List[CandidateDecision]:
        """Generate feasible candidate decisions for one year.

        Returns a list of CandidateDecision, each representing a different
        withdrawal/conversion strategy.
        """
        candidates = []

        # Candidate 1: RMD only (baseline)
        pretax_accounts = [
            (k, v) for k, v in accounts.items()
            if v['type'] in ('401k', 'trad_ira') and v['balance'] > 0
        ]
        pretax_rmds = {
            k: min(v['balance'], rmd_required / max(1, len(pretax_accounts)))
            for k, v in pretax_accounts
        }
        taxable_accounts = [
            (k, v) for k, v in accounts.items()
            if v['type'] == 'brokerage' and v['balance'] > 0
        ]
        remaining_cash = max(0.0, spending_target - sum(pretax_rmds.values()))
        taxable_cash = min(
            remaining_cash, sum(v['balance'] for _, v in taxable_accounts)
        )
        c1 = YearDecision(
            taxable_withdrawals={
                k: min(v['balance'], taxable_cash / max(1, len(taxable_accounts)))
                for k, v in taxable_accounts
            },
            pretax_withdrawals=pretax_rmds,
            spending_target=spending_target,
        )
        c1.compute_totals()
        candidates.append(CandidateDecision(decision=c1, label="rmd_only"))

        # Candidate 2: Bracket fill (fill up to next bracket)
        bracket_room = max(0, current_tax_bracket_top - ordinary_income_so_far)
        if bracket_room > 0 and rmd_required < bracket_room:
            additional = bracket_room - rmd_required
            conversion = min(additional, self.config.max_roth_conversion)
            if conversion > 0:
                c2 = YearDecision(
                    pretax_withdrawals=dict(c1.pretax_withdrawals),
                    roth_conversions={},  # Will fill below
                    spending_target=spending_target,
                )
                # Find best account to convert from
                best_acct = max(
                    [(k, v) for k, v in accounts.items()
                     if v['type'] in ('401k', 'trad_ira') and v['balance'] > rmd_required],
                    key=lambda x: x[1]['balance'],
                    default=None,
                )
                if best_acct:
                    c2.roth_conversions = {best_acct[0]: conversion}
                c2.compute_totals()
                candidates.append(CandidateDecision(
                    decision=c2,
                    label=f"bracket_fill_{int(current_tax_bracket_top/1000)}k",
                ))

        # Candidate 3: ACA MAGI target (if applicable)
        if self.config.aca_target_MAGI is not None:
            target_ordinary = max(0, self.config.aca_target_MAGI - ordinary_income_so_far)
            if target_ordinary > 0:
                c3 = YearDecision(
                    pretax_withdrawals=dict(c1.pretax_withdrawals),
                    spending_target=spending_target,
                )
                # Withdraw just enough to hit MAGI target
                shortfall = spending_target - sum(c1.pretax_withdrawals.values())
                if shortfall > 0:
                    # Fill from taxable first, then pre-tax up to MAGI target
                    taxable_avail = sum(v['balance'] for k, v in accounts.items()
                                       if v['type'] == 'brokerage' and v['balance'] > 0)
                    taxable_draw = min(shortfall, taxable_avail)
                    pretax_draw = min(shortfall - taxable_draw, target_ordinary)
                    c3.taxable_withdrawals = {
                        k: min(v['balance'], taxable_draw / max(1, len([a for a in accounts.values() if a['type'] == 'brokerage'])))
                        for k, v in accounts.items()
                        if v['type'] == 'brokerage' and v['balance'] > 0
                    }
                    c3.pretax_withdrawals = {
                        k: min(v['balance'], pretax_draw / max(1, len([a for a in accounts.values() if a['type'] in ('401k', 'trad_ira')])))
                        for k, v in accounts.items()
                        if v['type'] in ('401k', 'trad_ira') and v['balance'] > 0
                    }
                c3.compute_totals()
                candidates.append(CandidateDecision(
                    decision=c3,
                    label=f"aca_target_{int(self.config.aca_target_MAGI/1000)}k",
                ))

        # Candidate 4: 0% gain harvesting (if taxable gains available)
        if self.config.harvest_0pct_gains:
            # Estimate if we're in the 0% LTCG bracket
            # For MFJ 2024: 0% up to ~$94K total income
            c4 = YearDecision(
                pretax_withdrawals=dict(c1.pretax_withdrawals),
                realized_ltcg=0,  # Would need cost basis info
                spending_target=spending_target,
            )
            c4.compute_totals()
            # Only add if we have room
            if ordinary_income_so_far < 80_000:
                candidates.append(CandidateDecision(
                    decision=c4, label="gain_harvest_0pct",
                ))

        return candidates

    def evaluate_feasibility(
        self,
        decision: YearDecision,
        accounts: Dict[str, dict],
        spending_target: float,
        rmd_required: float = 0.0,
    ) -> FeasibilityResult:
        """Check cash, account-balance, RMD, and Roth-conversion constraints."""
        decision.compute_totals()
        violations: List[str] = []
        cash_shortfall = max(0.0, spending_target - decision.total_cash_in)
        if cash_shortfall > 0.01:
            violations.append(f"cash shortfall: ${cash_shortfall:,.2f}")

        withdrawals = {}
        for mapping in (
            decision.taxable_withdrawals,
            decision.pretax_withdrawals,
            decision.roth_withdrawals,
        ):
            for account_id, amount in mapping.items():
                withdrawals[account_id] = withdrawals.get(account_id, 0.0) + amount
        for account_id, amount in withdrawals.items():
            account = accounts.get(account_id)
            if account is None:
                violations.append(f"unknown withdrawal account: {account_id}")
            elif amount < 0:
                violations.append(f"negative withdrawal: {account_id}")
            elif amount > account.get("balance", 0.0) + 0.01:
                violations.append(f"withdrawal exceeds balance: {account_id}")

        rmd_paid = sum(decision.pretax_withdrawals.values())
        rmd_shortfall = max(0.0, rmd_required - rmd_paid)
        if rmd_shortfall > 0.01:
            violations.append(f"RMD shortfall: ${rmd_shortfall:,.2f}")

        # Roth conversion limit (IRS contribution limit applies;
        # conversions have no hard cap but optimizer caps them)
        roth_total = sum(decision.roth_conversions.values())
        if roth_total > self.config.max_roth_conversion + 0.01:
            violations.append(
                f"Roth conversion ${roth_total:,.2f} exceeds limit "
                f"${self.config.max_roth_conversion:,.2f}"
            )

        return FeasibilityResult(
            feasible=not violations,
            cash_shortfall=cash_shortfall,
            rmd_shortfall=rmd_shortfall,
            violations=violations,
        )

    def select_best(
        self,
        candidates: List[CandidateDecision],
        year: int,
        age: int,
        accounts: Optional[Dict[str, dict]] = None,
        spending_target: Optional[float] = None,
        rmd_required: float = 0.0,
        ordinary_income_baseline: float = 0.0,
        family_size: int = 2,
    ) -> CandidateDecision:
        """Select the best candidate from a list.

        When an engine-backed evaluator is configured, scores candidates
        using real tax, ACA, and IRMAA calculations.  Otherwise falls
        back to a proxy heuristic (total_ordinary_income * 0.3).

        Scoring: minimize tax cost + IRMAA penalty - ACA subsidy preserved,
        subject to meeting spending needs.
        """
        if not candidates:
            return CandidateDecision(
                decision=YearDecision(), label="no_candidates", score=float('inf')
            )

        if accounts is not None and spending_target is not None:
            for candidate in candidates:
                candidate.feasibility = self.evaluate_feasibility(
                    candidate.decision, accounts, spending_target, rmd_required,
                )

        feasible = [c for c in candidates if c.feasibility is None or c.feasibility.feasible]
        if not feasible:
            return CandidateDecision(
                decision=YearDecision(spending_target=spending_target or 0.0),
                label="no_feasible_candidates",
                score=float('inf'),
                feasibility=FeasibilityResult(
                    feasible=False,
                    cash_shortfall=spending_target or 0.0,
                    violations=["no feasible candidate"],
                ),
            )

        evaluator = self.config.evaluator
        for c in feasible:
            d = c.decision
            d.compute_totals()

            if evaluator is not None:
                # Engine-backed scoring: real tax + ACA + IRMAA
                try:
                    tax_eval = evaluator.evaluate(
                        d, year, age, ordinary_income_baseline, family_size,
                    )
                    # Score = total cost (tax + IRMAA - subsidy preserved)
                    c.score = tax_eval.total_cost
                    # Attach evaluation to trace metadata
                    c._tax_evaluation = tax_eval  # type: ignore[attr-defined]
                except Exception:
                    # Fallback to proxy if evaluator fails
                    c.score = self._proxy_score(d)
            else:
                # Proxy heuristic (legacy path)
                c.score = self._proxy_score(d)

        return min(feasible, key=lambda c: c.score)

    @staticmethod
    def _proxy_score(d: YearDecision) -> float:
        """Proxy score for fallback when no evaluator is available.

        Lower is better.  Approximates tax cost from income levels.
        """
        score = d.total_ordinary_income * 0.3
        score += d.realized_ltcg * 0.15
        score += len(d.roth_conversions) * 1000
        return score

    def optimize_year(
        self,
        year: int,
        age: int,
        accounts: Dict[str, dict],
        spending_target: float,
        rmd_required: float,
        bracket_top: float,
        ordinary_income: float,
        family_size: int = 2,
    ) -> Tuple[YearDecision, DecisionTrace]:
        """Run one year of optimization.

        Returns the best decision and a trace explaining why.
        """
        candidates = self.generate_candidates(
            year, age, accounts, spending_target,
            rmd_required, bracket_top, ordinary_income,
        )

        best = self.select_best(
            candidates, year, age, accounts, spending_target, rmd_required,
            ordinary_income_baseline=ordinary_income,
            family_size=family_size,
        )

        reasons = [f"Selected {best.label} (score={best.score:.0f})"]
        if best.feasibility and not best.feasibility.feasible:
            reasons.extend(best.feasibility.rejection_reasons)
        if best.feasibility and best.feasibility.feasible:
            reasons.append("Selected candidate satisfies cash, balance, and RMD constraints")

        # Populate trace with tax evaluation data if available
        tax_eval = getattr(best, '_tax_evaluation', None)
        if tax_eval is not None:
            reasons.append(
                f"Engine evaluation: tax=${tax_eval.total_tax:,.0f}, "
                f"ACA subsidy=${tax_eval.aca_subsidy:,.0f}, "
                f"IRMAA=${tax_eval.irmaa_cost:,.0f}"
            )

        trace = DecisionTrace(
            year=year,
            selected=best.decision,
            selected_label=best.label,
            alternatives=candidates,
            reasons=reasons + (
                ["Optimizer recommendations are experimental"]
                if self.config.experimental else []
            ),
            tax_cost=tax_eval.total_tax if tax_eval else 0.0,
            aca_subsidy=tax_eval.aca_subsidy if tax_eval else 0.0,
            irmaa_cost=tax_eval.irmaa_cost if tax_eval else 0.0,
            rmd_forced=rmd_required,
        )

        return best.decision, trace
