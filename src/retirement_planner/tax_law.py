"""
Versioned tax-law engine for Mantissa.

Implements enacted federal + CA tax law by year, with:
- Bracket inflation indexing
- Filing status transitions (MFJ → qualifying survivor)
- AMT, QCD, SALT cap, charitable bunching
- Tax credits (child tax credit, retirement savings credit)
- IRMAA tiers (2-year lookback)
- ACA subsidy parameters
- Estate/gift tax

Tax-law packs: 2024, 2025, 2026 (OBBBA permanent).
User can override with policy_scenario="alternative_*" for counterfactual analysis.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------
class FilingStatus(Enum):
    SINGLE = "single"
    MFJ = "mfj"                # Married Filing Jointly
    MFS = "mfs"                # Married Filing Separately
    HOH = "hoh"                # Head of Household
    QSS = "qss"                # Qualifying Surviving Spouse (widow/er)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Bracket:
    upper: float    # upper limit (inf for top bracket)
    rate: float     # marginal rate as decimal


@dataclass(frozen=True)
class IrmaaTier:
    """IRMAA surcharge per person per month for Part B or Part D."""
    magi_threshold: float
    part_b_surcharge: float   # per person / month
    part_d_surcharge: float   # per person / month


@dataclass(frozen=True)
class AcaTier:
    """ACA applicable percentage by FPL ratio."""
    fpl_ratio: float
    applicable_pct: float


@dataclass(frozen=True)
class TaxLawVersion:
    """Complete tax law for a given year."""
    year: int
    name: str

    # Federal ordinary brackets by filing status
    federal_brackets: Dict[FilingStatus, List[Bracket]]
    # Standard deduction by filing status
    standard_deduction: Dict[FilingStatus, float]
    # LTCG brackets by filing status
    ltcg_brackets: Dict[FilingStatus, List[Bracket]]
    # NIIT (Net Investment Income Tax) thresholds
    niit_thresholds: Dict[FilingStatus, float]
    niit_rate: float = 0.038
    social_security_wage_base: float = 168_600

    # AMT
    amt_exemption: Dict[FilingStatus, float] = field(default_factory=dict)
    amt_phaseout_start: Dict[FilingStatus, float] = field(default_factory=dict)
    amt_phaseout_rate: float = 0.25
    amt_rate: float = 0.26
    amt_26_limit: float = 232_600  # 2024

    # IRMAA (2-year lookback, per person / month)
    irmaa_part_b: List[IrmaaTier] = field(default_factory=list)
    irmaa_part_d: List[IrmaaTier] = field(default_factory=list)
    irmaa_lookback_years: int = 2

    # ACA
    fpl_base: float = 0.0
    fpl_per_additional_person: float = 0.0
    aca_tiers: List[AcaTier] = field(default_factory=list)
    aca_fpl_cliff_ratio: float = 4.0
    aca_silver_premiums: Dict[str, Dict[int, float]] = field(default_factory=dict)

    # Estate / gift tax
    estate_exemption_single: float = 0.0
    estate_exemption_mfj: float = 0.0
    estate_tax_rate: float = 0.40

    # SALT cap
    salt_cap: Optional[float] = 10_000  # None = no cap

    # Charitable / QCD
    qcd_age: float = 70.5  # minimum age for QCD from IRA
    charitable_deduction_floor_pct: float = 0.0  # AGI floor for itemized

    # Credits
    child_tax_credit: float = 2_000  # per qualifying child
    child_tax_credit_phaseout_mfj: float = 400_000
    child_tax_credit_phaseout_single: float = 200_000

    # CA state
    ca_brackets: List[Bracket] = field(default_factory=list)
    ca_brackets_by_status: Dict[FilingStatus, List[Bracket]] = field(default_factory=dict)
    ca_standard_deduction: Dict[FilingStatus, float] = field(default_factory=dict)
    ca_itemized_phaseout_start: Dict[FilingStatus, float] = field(default_factory=dict)
    salt_phaseout_start: Optional[float] = None
    salt_floor: float = 10_000
    itemized_reduction_rate: float = 0.0

    # Inflation factor relative to base year (1.0 = base year)
    inflation_factor: float = 1.0

    citations: List[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Pack-backed registry
class TaxLawRegistry:
    """Select enacted or alternative tax law by year."""

    def __init__(self, policy: Optional[dict] = None):
        # Packs are loaded from immutable, versioned package data. Keep custom
        # registrations local to this instance so scenarios cannot leak state.
        from .rules import RuleRegistry
        self._rules = RuleRegistry(policy)
        self._laws = {}
        self._inflated = {}

    def register(self, law: TaxLawVersion):
        """Register or override a tax-law version."""
        self._laws[law.year] = law
        self._inflated.clear()

    def law_for_year(
        self,
        year: int,
        policy_scenario: str = "enacted",
        fallback_inflation: float = 0.025,
    ) -> TaxLawVersion:
        """Get the applicable tax law for a given year.

        Args:
            year: Calendar year.
            policy_scenario: "enacted" (default), "alternative_*", or "custom:...".
            fallback_inflation: Inflation rate for years beyond registered packs.

        Returns:
            TaxLawVersion for the requested year/scenario.
        """
        if policy_scenario != "enacted":
            # Future: load counterfactual / custom scenarios
            raise ValueError(
                f"Alternative policy scenarios not yet implemented: {policy_scenario}"
            )

        # Explicit registrations remain supported and are instance-local.
        if year in self._laws:
            return self._laws[year]
        custom_years = [known for known in self._laws if known <= year]
        if custom_years:
            base = self._laws[max(custom_years)]
            return _inflate_law(base, year, (1.0 + fallback_inflation) ** (year - base.year))
        return self._rules.law_for_year(year, policy_scenario, fallback_inflation)

    def available_years(self) -> List[int]:
        from .rule_data import available_pack_years
        return sorted(set(available_pack_years("tax")) | set(self._laws))


def _tax_from_pack(data: dict) -> TaxLawVersion:
    """Build the public tax-law value object from one packaged JSON year pack."""
    status = {s.value: s for s in FilingStatus}

    def status_map(mapping):
        return {status[k]: v for k, v in mapping.items()}

    def brackets(rows):
        return [Bracket(float("inf") if row["upper"] == "Infinity" else row["upper"], row["rate"]) for row in rows]

    def bracket_map(mapping):
        return {status[k]: brackets(v) for k, v in mapping.items()}

    values = {k: v for k, v in data.items() if k in TaxLawVersion.__dataclass_fields__}
    for key in ("federal_brackets", "ltcg_brackets"):
        values[key] = bracket_map(values[key])
    for key in ("standard_deduction", "niit_thresholds", "amt_exemption", "amt_phaseout_start", "ca_standard_deduction", "ca_itemized_phaseout_start"):
        values[key] = status_map(values.get(key, {}))
    values["ca_brackets"] = brackets(values.get("ca_brackets", []))
    values["ca_brackets_by_status"] = bracket_map(values.get("ca_brackets_by_status", {}))
    def irmaa_tier(row):
        row = dict(row)
        if row["magi_threshold"] == "Infinity":
            row["magi_threshold"] = float("inf")
        return IrmaaTier(**row)
    values["irmaa_part_b"] = [irmaa_tier(row) for row in values.get("irmaa_part_b", [])]
    values["irmaa_part_d"] = [irmaa_tier(row) for row in values.get("irmaa_part_d", [])]
    values["aca_tiers"] = [AcaTier(**row) for row in values.get("aca_tiers", [])]
    values["aca_silver_premiums"] = {
        region: {int(size) if str(size).isdigit() else size: amount for size, amount in premiums.items()}
        for region, premiums in values.get("aca_silver_premiums", {}).items()
    }
    return TaxLawVersion(**values)


def _inflate_law(base: TaxLawVersion, year: int, factor: float) -> TaxLawVersion:
    """Create a new TaxLawVersion with brackets/deductions scaled by factor."""
    def _scale_brackets(bl):
        return [Bracket(upper=b.upper * factor if b.upper != float('inf') else float('inf'),
                        rate=b.rate) for b in bl]

    def _scale_dict(d):
        return {k: v * factor if isinstance(v, (int, float)) else v for k, v in d.items()}

    return TaxLawVersion(
        year=year,
        name=f"{year} (inflated from {base.year})",
        federal_brackets={fs: _scale_brackets(bl) for fs, bl in base.federal_brackets.items()},
        standard_deduction=_scale_dict(base.standard_deduction),
        ltcg_brackets={fs: _scale_brackets(bl) for fs, bl in base.ltcg_brackets.items()},
        niit_thresholds=dict(base.niit_thresholds),
        niit_rate=base.niit_rate,
        social_security_wage_base=base.social_security_wage_base * factor,
        amt_exemption=_scale_dict(base.amt_exemption),
        amt_phaseout_start=_scale_dict(base.amt_phaseout_start),
        amt_phaseout_rate=base.amt_phaseout_rate,
        amt_rate=base.amt_rate,
        amt_26_limit=base.amt_26_limit * factor,
        irmaa_part_b=[IrmaaTier(t.magi_threshold * factor, t.part_b_surcharge, t.part_d_surcharge)
                      for t in base.irmaa_part_b],
        irmaa_part_d=[IrmaaTier(t.magi_threshold * factor, t.part_b_surcharge, t.part_d_surcharge)
                      for t in base.irmaa_part_d],
        irmaa_lookback_years=base.irmaa_lookback_years,
        fpl_base=base.fpl_base * factor,
        fpl_per_additional_person=base.fpl_per_additional_person * factor,
        aca_tiers=base.aca_tiers,
        aca_fpl_cliff_ratio=base.aca_fpl_cliff_ratio,
        aca_silver_premiums=base.aca_silver_premiums,
        estate_exemption_single=base.estate_exemption_single * factor,
        estate_exemption_mfj=base.estate_exemption_mfj * factor,
        estate_tax_rate=base.estate_tax_rate,
        salt_cap=(40_000 * 1.01 ** (year - 2025) if 2025 <= year <= 2029 else 10_000 if year >= 2030 else base.salt_cap),
        salt_phaseout_start=(500_000 * 1.01 ** (year - 2025) if 2025 <= year <= 2029 else None),
        salt_floor=base.salt_floor,
        itemized_reduction_rate=base.itemized_reduction_rate,
        qcd_age=base.qcd_age,
        charitable_deduction_floor_pct=base.charitable_deduction_floor_pct,
        child_tax_credit=base.child_tax_credit,
        child_tax_credit_phaseout_mfj=base.child_tax_credit_phaseout_mfj,
        child_tax_credit_phaseout_single=base.child_tax_credit_phaseout_single,
        ca_brackets=_scale_brackets(base.ca_brackets),
        ca_brackets_by_status={fs: _scale_brackets(bl) for fs, bl in base.ca_brackets_by_status.items()},
        ca_standard_deduction=_scale_dict(base.ca_standard_deduction),
        ca_itemized_phaseout_start=_scale_dict(base.ca_itemized_phaseout_start),
        inflation_factor=factor,
        citations=base.citations + [f"Inflated {base.year} → {year} at {factor:.4f}"],
    )


# ---------------------------------------------------------------------------
# Tax calculation functions (stateless, law-parameterized)
# ---------------------------------------------------------------------------
def bracket_tax(taxable_income: float, brackets) -> float:
    """Compute tax from brackets.

    Accepts either:
    - List[Bracket] (from tax_law.py)
    - List[Tuple[float, float]] (legacy format: (upper_limit, rate))
    """
    tax = 0.0
    prev = 0.0
    for b in brackets:
        if taxable_income <= prev:
            break
        # Handle both Bracket objects and tuples
        if isinstance(b, tuple):
            upper, rate = b
        else:
            upper, rate = b.upper, b.rate
        in_bracket = min(taxable_income, upper) - prev
        tax += in_bracket * rate
        prev = upper
    return tax


def calculate_niit(
    net_investment_income: float,
    magi: float,
    law: TaxLawVersion,
    status: FilingStatus,
) -> float:
    """Net Investment Income Tax (3.8% on lesser of NII or MAGI above threshold)."""
    threshold = law.niit_thresholds.get(status, 200_000)
    excess = max(0.0, magi - threshold)
    return max(0.0, min(net_investment_income, excess)) * law.niit_rate


def calculate_amt(
    regular_tax: float,
    tax_inputs_ordinary: float,
    tax_inputs_ltcg: float,
    law: TaxLawVersion,
    status: FilingStatus,
) -> float:
    """Alternative Minimum Tax (simplified — AMT base = ordinary + LTCG)."""
    exemption = law.amt_exemption.get(status, 0)
    phaseout_start = law.amt_phaseout_start.get(status, 0)

    # Phaseout: reduce exemption by 25% of AMTI above threshold
    amti = tax_inputs_ordinary + tax_inputs_ltcg
    if amti > phaseout_start:
        reduction = (amti - phaseout_start) * law.amt_phaseout_rate
        exemption = max(0, exemption - reduction)

    amt_base = max(0, amti - exemption)
    cg_base = min(max(0.0, tax_inputs_ltcg), amt_base)
    amt_base -= cg_base
    rate_limit = law.amt_26_limit / (2 if status == FilingStatus.MFS else 1)
    # 26% up to threshold, 28% above
    if amt_base <= rate_limit:
        tentative_min_tax = amt_base * law.amt_rate
    else:
        tentative_min_tax = (
            rate_limit * law.amt_rate
            + (amt_base - rate_limit) * 0.28
        )

    tentative_min_tax += bracket_tax(amt_base + cg_base, law.ltcg_brackets.get(status, [])) - bracket_tax(amt_base, law.ltcg_brackets.get(status, []))

    # AMT = max(0, tentative_min tax - regular tax)
    return max(0.0, tentative_min_tax - regular_tax)


def calculate_irmaa(
    magi_two_years_prior: float,
    law: TaxLawVersion,
    num_people: int = 2,
) -> float:
    """Calculate IRMAA surcharge (annual) based on 2-year-ago MAGI."""
    part_b_monthly = 0.0
    for tier in law.irmaa_part_b:
        if magi_two_years_prior <= tier.magi_threshold:
            part_b_monthly = tier.part_b_surcharge
            break

    part_d_monthly = 0.0
    for tier in law.irmaa_part_d:
        if magi_two_years_prior <= tier.magi_threshold:
            part_d_monthly = tier.part_d_surcharge
            break

    return (part_b_monthly + part_d_monthly) * 12 * num_people


def calculate_aca_subsidy(
    magi: float,
    family_size: int,
    law: TaxLawVersion,
    state: str = "CA",
) -> float:
    """Calculate annual ACA premium subsidy (premium tax credit)."""
    # Federal Poverty Level
    additional = max(0, family_size - 4)
    fpl = law.fpl_base + additional * law.fpl_per_additional_person

    # Household income as % of FPL
    fpl_ratio = magi / fpl if fpl > 0 else 0

    # No subsidy above cliff ratio
    if fpl_ratio > law.aca_fpl_cliff_ratio:
        return 0.0

    # Find applicable percentage
    applicable_pct = 0.0
    for tier in law.aca_tiers:
        if fpl_ratio <= tier.fpl_ratio:
            applicable_pct = tier.applicable_pct
            break
    if not applicable_pct and law.aca_tiers:
        applicable_pct = law.aca_tiers[-1].applicable_pct

    # Expected contribution
    expected_contribution = magi * applicable_pct

    # Benchmark premium (second-lowest silver plan)
    premiums = law.aca_silver_premiums.get(state, law.aca_silver_premiums.get("_default", {}))
    benchmark_annual = premiums.get(family_size, premiums.get(4, 2000)) * 12

    # Subsidy = max(0, benchmark - expected contribution)
    return max(0.0, benchmark_annual - expected_contribution)


# Federal estate tax brackets (IRC §2001(c)): applied to the taxable
# estate (value above the unified credit exemption).  Flat 40% on the
# whole excess overstates tax on the lower brackets for modest estates.
_ESTATE_BRACKETS = [
    (10_000, 0.18), (20_000, 0.20), (40_000, 0.22), (60_000, 0.24),
    (80_000, 0.26), (100_000, 0.28), (150_000, 0.30), (250_000, 0.32),
    (500_000, 0.34), (750_000, 0.37), (1_000_000, 0.39),
    (float('inf'), 0.40),
]


def estate_tax_on_taxable(taxable: float) -> float:
    """Progressive federal estate tax on the taxable amount."""
    if taxable <= 0:
        return 0.0
    tax = 0.0
    prev = 0.0
    for upper, rate in _ESTATE_BRACKETS:
        if taxable <= prev:
            break
        tax += (min(taxable, upper) - prev) * rate
        prev = upper
    return tax


def calculate_estate_tax(
    taxable_estate: float,
    law: TaxLawVersion,
    status: FilingStatus = FilingStatus.MFJ,
) -> float:
    """Federal estate tax (simplified — unified credit, portability via
    the MFJ exemption).  *taxable_estate* must be in NOMINAL dollars:
    the exemption is inflation-indexed (nominal), so comparing a real
    estate value against it understates (usually zeroes) the tax."""
    if status in (FilingStatus.MFJ, FilingStatus.QSS):
        exemption = law.estate_exemption_mfj
    else:
        exemption = law.estate_exemption_single

    taxable = max(0.0, taxable_estate - exemption)
    return estate_tax_on_taxable(taxable)


def calculate_child_tax_credit(
    num_children: int,
    magi: float,
    law: TaxLawVersion,
    status: FilingStatus = FilingStatus.MFJ,
) -> float:
    """Child tax credit with phaseout."""
    if num_children <= 0:
        return 0.0

    credit = num_children * law.child_tax_credit
    phaseout_threshold = (
        law.child_tax_credit_phaseout_mfj
        if status in (FilingStatus.MFJ, FilingStatus.QSS)
        else law.child_tax_credit_phaseout_single
    )

    if magi > phaseout_threshold:
        # Phaseout: $50 per $1,000 (or fraction) above threshold
        excess = magi - phaseout_threshold
        reduction = (excess // 1_000 + 1) * 50
        credit = max(0.0, credit - reduction)

    return credit


def calculate_qcd(
    ira_balance: float,
    age: float,
    charitably_inclined: bool,
    law: TaxLawVersion,
) -> float:
    """Qualified Charitable Distribution from IRA (reduces AGI)."""
    if not charitably_inclined or age < law.qcd_age:
        return 0.0
    # QCD limit: $105,000 (2024), indexed
    qcd_limit = 105_000 * law.inflation_factor
    return min(ira_balance, qcd_limit)


def determine_filing_status(
    primary_alive: bool,
    spouse_alive: bool,
    year_of_death_spouse: Optional[int],
    current_year: int,
    has_dependents: bool,
) -> FilingStatus:
    """Determine filing status based on household state.

    Rules:
    - Both alive → MFJ
    - Spouse died this year → MFJ (married filing jointly for death year)
    - Spouse died prior year, no dependents → Single
    - Spouse died prior year, has dependents → HOH (or QSS for 2 years)
    - QSS available for 2 years after death year if qualifying
    """
    if primary_alive and spouse_alive:
        return FilingStatus.MFJ

    if year_of_death_spouse is None:
        return FilingStatus.MFJ

    death_year = year_of_death_spouse

    # Death year: still MFJ
    if current_year == death_year:
        return FilingStatus.MFJ

    # 2 years after death: QSS (qualifying surviving spouse)
    years_since_death = current_year - death_year
    if years_since_death <= 2 and has_dependents:
        return FilingStatus.QSS

    # After QSS period: HOH if dependents, else Single
    if has_dependents:
        return FilingStatus.HOH

    return FilingStatus.SINGLE
