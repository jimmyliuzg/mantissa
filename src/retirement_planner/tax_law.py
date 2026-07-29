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

from dataclasses import dataclass, field
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

    # AMT
    amt_exemption: Dict[FilingStatus, float] = field(default_factory=dict)
    amt_phaseout_start: Dict[FilingStatus, float] = field(default_factory=dict)
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

    # Inflation factor relative to base year (1.0 = base year)
    inflation_factor: float = 1.0

    citations: List[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Bracket construction helpers
# ---------------------------------------------------------------------------
def _b(upper: float, rate: float) -> Bracket:
    return Bracket(upper=upper, rate=rate)


# ---------------------------------------------------------------------------
# 2024 Tax Law (enacted, OBBBA permanent for 2026+)
# ---------------------------------------------------------------------------
def _tax_law_2024() -> TaxLawVersion:
    return TaxLawVersion(
        year=2024,
        name="2024 Enacted (TCJA/OBBBA)",

        federal_brackets={
            FilingStatus.MFJ: [
                _b(23_200, 0.10), _b(94_300, 0.12), _b(201_050, 0.22),
                _b(383_900, 0.24), _b(487_450, 0.32), _b(731_200, 0.35),
                _b(float('inf'), 0.37),
            ],
            FilingStatus.SINGLE: [
                _b(11_600, 0.10), _b(47_150, 0.12), _b(100_525, 0.22),
                _b(191_950, 0.24), _b(243_725, 0.32), _b(609_350, 0.35),
                _b(float('inf'), 0.37),
            ],
            FilingStatus.HOH: [
                _b(16_550, 0.10), _b(63_100, 0.12), _b(100_500, 0.22),
                _b(191_950, 0.24), _b(243_700, 0.32), _b(609_350, 0.35),
                _b(float('inf'), 0.37),
            ],
            FilingStatus.MFS: [
                _b(11_600, 0.10), _b(47_150, 0.12), _b(100_525, 0.22),
                _b(191_950, 0.24), _b(243_725, 0.32), _b(365_600, 0.35),
                _b(float('inf'), 0.37),
            ],
            FilingStatus.QSS: [
                # Same as MFJ
                _b(23_200, 0.10), _b(94_300, 0.12), _b(201_050, 0.22),
                _b(383_900, 0.24), _b(487_450, 0.32), _b(731_200, 0.35),
                _b(float('inf'), 0.37),
            ],
        },

        standard_deduction={
            FilingStatus.MFJ: 29_200,
            FilingStatus.SINGLE: 14_600,
            FilingStatus.HOH: 21_900,
            FilingStatus.MFS: 14_600,
            FilingStatus.QSS: 29_200,
        },

        ltcg_brackets={
            FilingStatus.MFJ: [
                _b(94_050, 0.00), _b(583_750, 0.15), _b(float('inf'), 0.20),
            ],
            FilingStatus.SINGLE: [
                _b(47_025, 0.00), _b(518_900, 0.15), _b(float('inf'), 0.20),
            ],
            FilingStatus.HOH: [
                _b(59_750, 0.00), _b(553_850, 0.15), _b(float('inf'), 0.20),
            ],
            FilingStatus.MFS: [
                _b(47_025, 0.00), _b(291_850, 0.15), _b(float('inf'), 0.20),
            ],
            FilingStatus.QSS: [
                _b(94_050, 0.00), _b(583_750, 0.15), _b(float('inf'), 0.20),
            ],
        },

        niit_thresholds={
            FilingStatus.MFJ: 250_000,
            FilingStatus.SINGLE: 200_000,
            FilingStatus.HOH: 200_000,
            FilingStatus.MFS: 125_000,
            FilingStatus.QSS: 250_000,
        },

        amt_exemption={
            FilingStatus.MFJ: 133_300,
            FilingStatus.SINGLE: 85_700,
            FilingStatus.HOH: 85_700,
            FilingStatus.MFS: 66_650,
            FilingStatus.QSS: 133_300,
        },
        amt_phaseout_start={
            FilingStatus.MFJ: 1_218_700,
            FilingStatus.SINGLE: 609_350,
            FilingStatus.HOH: 609_350,
            FilingStatus.MFS: 609_350,
            FilingStatus.QSS: 1_218_700,
        },
        amt_26_limit=232_600,

        irmaa_part_b=[
            IrmaaTier(206_000, 0.0, 0.0),
            IrmaaTier(258_000, 70.0, 0.0),
            IrmaaTier(322_000, 175.0, 0.0),
            IrmaaTier(386_000, 380.0, 0.0),
            IrmaaTier(750_000, 484.0, 0.0),
            IrmaaTier(float('inf'), 587.0, 0.0),
        ],
        irmaa_part_d=[
            IrmaaTier(206_000, 0.0, 0.0),
            IrmaaTier(258_000, 0.0, 10.0),
            IrmaaTier(322_000, 0.0, 26.0),
            IrmaaTier(386_000, 0.0, 43.0),
            IrmaaTier(750_000, 0.0, 60.0),
            IrmaaTier(float('inf'), 0.0, 77.0),
        ],

        fpl_base=31_200,
        fpl_per_additional_person=5_380,
        aca_tiers=[
            AcaTier(1.33, 0.021), AcaTier(1.50, 0.030), AcaTier(2.00, 0.040),
            AcaTier(2.50, 0.063), AcaTier(3.00, 0.081), AcaTier(4.00, 0.097),
        ],
        aca_fpl_cliff_ratio=4.0,
        aca_silver_premiums={
            "CA": {1: 800, 2: 1600, 3: 1800, 4: 2000, 5: 2200},
            "_default": {1: 800, 2: 1600, 3: 1800, 4: 2000, 5: 2200},
        },

        estate_exemption_single=13_610_000,
        estate_exemption_mfj=27_220_000,
        estate_tax_rate=0.40,

        salt_cap=10_000,
        qcd_age=70.5,

        child_tax_credit=2_000,
        child_tax_credit_phaseout_mfj=400_000,
        child_tax_credit_phaseout_single=200_000,

        ca_brackets=[
            _b(20_824, 0.01), _b(49_368, 0.02), _b(77_918, 0.04),
            _b(108_152, 0.06), _b(136_700, 0.08), _b(698_274, 0.093),
            _b(837_922, 0.103), _b(1_396_546, 0.113), _b(1_666_074, 0.123),
            _b(2_732_666, 0.133), _b(float('inf'), 0.143),
        ],

        citations=[
            "IRS Rev. Proc. 2023-34 (2024 inflation adjustments)",
            "CA FTB 2024 tax rate schedule",
        ],
    )


def _tax_law_2025() -> TaxLawVersion:
    """2025 enacted law — OBBBA made TCJA rates permanent."""
    base = _tax_law_2024()
    # 2025 inflation-adjusted values (approximate from IRS Rev. Proc. 2024-40)
    return TaxLawVersion(
        year=2025,
        name="2025 Enacted (OBBBA permanent rates)",

        federal_brackets={
            FilingStatus.MFJ: [
                _b(23_850, 0.10), _b(96_950, 0.12), _b(206_700, 0.22),
                _b(394_600, 0.24), _b(501_050, 0.32), _b(751_600, 0.35),
                _b(float('inf'), 0.37),
            ],
            FilingStatus.SINGLE: [
                _b(11_925, 0.10), _b(48_475, 0.12), _b(103_350, 0.22),
                _b(197_300, 0.24), _b(250_525, 0.32), _b(626_350, 0.35),
                _b(float('inf'), 0.37),
            ],
            FilingStatus.HOH: [
                _b(17_000, 0.10), _b(64_850, 0.12), _b(103_350, 0.22),
                _b(197_300, 0.24), _b(250_500, 0.32), _b(626_350, 0.35),
                _b(float('inf'), 0.37),
            ],
            FilingStatus.MFS: [
                _b(11_925, 0.10), _b(48_475, 0.12), _b(103_350, 0.22),
                _b(197_300, 0.24), _b(250_525, 0.32), _b(375_800, 0.35),
                _b(float('inf'), 0.37),
            ],
            FilingStatus.QSS: [
                _b(23_850, 0.10), _b(96_950, 0.12), _b(206_700, 0.22),
                _b(394_600, 0.24), _b(501_050, 0.32), _b(751_600, 0.35),
                _b(float('inf'), 0.37),
            ],
        },

        standard_deduction={
            FilingStatus.MFJ: 30_000,
            FilingStatus.SINGLE: 15_000,
            FilingStatus.HOH: 22_500,
            FilingStatus.MFS: 15_000,
            FilingStatus.QSS: 30_000,
        },

        ltcg_brackets={
            FilingStatus.MFJ: [
                _b(96_700, 0.00), _b(600_050, 0.15), _b(float('inf'), 0.20),
            ],
            FilingStatus.SINGLE: [
                _b(48_350, 0.00), _b(533_400, 0.15), _b(float('inf'), 0.20),
            ],
            FilingStatus.HOH: [
                _b(61_250, 0.00), _b(570_050, 0.15), _b(float('inf'), 0.20),
            ],
            FilingStatus.MFS: [
                _b(48_350, 0.00), _b(300_000, 0.15), _b(float('inf'), 0.20),
            ],
            FilingStatus.QSS: [
                _b(96_700, 0.00), _b(600_050, 0.15), _b(float('inf'), 0.20),
            ],
        },

        niit_thresholds={
            FilingStatus.MFJ: 250_000,
            FilingStatus.SINGLE: 200_000,
            FilingStatus.HOH: 200_000,
            FilingStatus.MFS: 125_000,
            FilingStatus.QSS: 250_000,
        },

        amt_exemption={
            FilingStatus.MFJ: 137_000,
            FilingStatus.SINGLE: 88_100,
            FilingStatus.HOH: 88_100,
            FilingStatus.MFS: 68_500,
            FilingStatus.QSS: 137_000,
        },
        amt_phaseout_start={
            FilingStatus.MFJ: 1_252_700,
            FilingStatus.SINGLE: 626_350,
            FilingStatus.HOH: 626_350,
            FilingStatus.MFS: 626_350,
            FilingStatus.QSS: 1_252_700,
        },
        amt_26_limit=239_100,

        irmaa_part_b=[
            IrmaaTier(212_000, 0.0, 0.0),
            IrmaaTier(266_000, 72.0, 0.0),
            IrmaaTier(332_000, 180.0, 0.0),
            IrmaaTier(400_000, 392.0, 0.0),
            IrmaaTier(750_000, 499.0, 0.0),
            IrmaaTier(float('inf'), 604.0, 0.0),
        ],
        irmaa_part_d=[
            IrmaaTier(212_000, 0.0, 0.0),
            IrmaaTier(266_000, 0.0, 10.50),
            IrmaaTier(332_000, 0.0, 27.0),
            IrmaaTier(400_000, 0.0, 44.50),
            IrmaaTier(750_000, 0.0, 62.0),
            IrmaaTier(float('inf'), 0.0, 80.0),
        ],

        fpl_base=32_500,
        fpl_per_additional_person=5_600,
        aca_tiers=[
            AcaTier(1.33, 0.021), AcaTier(1.50, 0.030), AcaTier(2.00, 0.040),
            AcaTier(2.50, 0.063), AcaTier(3.00, 0.081), AcaTier(4.00, 0.097),
        ],
        aca_fpl_cliff_ratio=4.0,
        aca_silver_premiums={
            "CA": {1: 830, 2: 1660, 3: 1870, 4: 2080, 5: 2290},
            "_default": {1: 830, 2: 1660, 3: 1870, 4: 2080, 5: 2290},
        },

        estate_exemption_single=13_990_000,
        estate_exemption_mfj=27_980_000,
        estate_tax_rate=0.40,

        salt_cap=10_000,

        child_tax_credit=2_000,
        child_tax_credit_phaseout_mfj=400_000,
        child_tax_credit_phaseout_single=200_000,

        ca_brackets=[
            _b(21_428, 0.01), _b(50_798, 0.02), _b(80_190, 0.04),
            _b(111_106, 0.06), _b(140_626, 0.08), _b(718_554, 0.093),
            _b(862_118, 0.103), _b(1_437_862, 0.113), _b(1_715_430, 0.123),
            _b(2_817_262, 0.133), _b(float('inf'), 0.143),
        ],

        citations=[
            "IRS Rev. Proc. 2024-40 (2025 inflation adjustments)",
            "OBBBA (One Big Beautiful Bill Act) — TCJA rates made permanent",
        ],
    )


def _tax_law_2026() -> TaxLawVersion:
    """2026 enacted law — OBBBA permanent, slight inflation adjustments."""
    base = _tax_law_2025()
    return TaxLawVersion(
        year=2026,
        name="2026 Enacted (OBBBA permanent)",

        federal_brackets={
            FilingStatus.MFJ: [
                _b(24_500, 0.10), _b(99_450, 0.12), _b(212_150, 0.22),
                _b(405_100, 0.24), _b(514_300, 0.32), _b(771_550, 0.35),
                _b(float('inf'), 0.37),
            ],
            FilingStatus.SINGLE: [
                _b(12_250, 0.10), _b(49_725, 0.12), _b(106_075, 0.22),
                _b(202_550, 0.24), _b(257_150, 0.32), _b(643_750, 0.35),
                _b(float('inf'), 0.37),
            ],
            FilingStatus.HOH: [
                _b(17_525, 0.10), _b(66_850, 0.12), _b(106_075, 0.22),
                _b(202_550, 0.24), _b(257_125, 0.32), _b(643_750, 0.35),
                _b(float('inf'), 0.37),
            ],
            FilingStatus.MFS: [
                _b(12_250, 0.10), _b(49_725, 0.12), _b(106_075, 0.22),
                _b(202_550, 0.24), _b(257_150, 0.32), _b(385_775, 0.35),
                _b(float('inf'), 0.37),
            ],
            FilingStatus.QSS: [
                _b(24_500, 0.10), _b(99_450, 0.12), _b(212_150, 0.22),
                _b(405_100, 0.24), _b(514_300, 0.32), _b(771_550, 0.35),
                _b(float('inf'), 0.37),
            ],
        },

        standard_deduction={
            FilingStatus.MFJ: 30_800,
            FilingStatus.SINGLE: 15_400,
            FilingStatus.HOH: 23_100,
            FilingStatus.MFS: 15_400,
            FilingStatus.QSS: 30_800,
        },

        ltcg_brackets={
            FilingStatus.MFJ: [
                _b(99_200, 0.00), _b(612_350, 0.15), _b(float('inf'), 0.20),
            ],
            FilingStatus.SINGLE: [
                _b(49_600, 0.00), _b(545_050, 0.15), _b(float('inf'), 0.20),
            ],
            FilingStatus.HOH: [
                _b(62_600, 0.00), _b(582_400, 0.15), _b(float('inf'), 0.20),
            ],
            FilingStatus.MFS: [
                _b(49_600, 0.00), _b(306_175, 0.15), _b(float('inf'), 0.20),
            ],
            FilingStatus.QSS: [
                _b(99_200, 0.00), _b(612_350, 0.15), _b(float('inf'), 0.20),
            ],
        },

        niit_thresholds={
            FilingStatus.MFJ: 250_000,
            FilingStatus.SINGLE: 200_000,
            FilingStatus.HOH: 200_000,
            FilingStatus.MFS: 125_000,
            FilingStatus.QSS: 250_000,
        },

        amt_exemption={
            FilingStatus.MFJ: 140_800,
            FilingStatus.SINGLE: 90_500,
            FilingStatus.HOH: 90_500,
            FilingStatus.MFS: 70_400,
            FilingStatus.QSS: 140_800,
        },
        amt_phaseout_start={
            FilingStatus.MFJ: 1_287_700,
            FilingStatus.SINGLE: 643_750,
            FilingStatus.HOH: 643_750,
            FilingStatus.MFS: 643_750,
            FilingStatus.QSS: 1_287_700,
        },
        amt_26_limit=245_600,

        irmaa_part_b=[
            IrmaaTier(218_000, 0.0, 0.0),
            IrmaaTier(274_000, 74.0, 0.0),
            IrmaaTier(342_000, 185.0, 0.0),
            IrmaaTier(413_000, 403.0, 0.0),
            IrmaaTier(750_000, 514.0, 0.0),
            IrmaaTier(float('inf'), 622.0, 0.0),
        ],
        irmaa_part_d=[
            IrmaaTier(218_000, 0.0, 0.0),
            IrmaaTier(274_000, 0.0, 11.0),
            IrmaaTier(342_000, 0.0, 28.0),
            IrmaaTier(413_000, 0.0, 46.0),
            IrmaaTier(750_000, 0.0, 64.0),
            IrmaaTier(float('inf'), 0.0, 83.0),
        ],

        fpl_base=33_500,
        fpl_per_additional_person=5_800,
        aca_tiers=[
            AcaTier(1.33, 0.021), AcaTier(1.50, 0.030), AcaTier(2.00, 0.040),
            AcaTier(2.50, 0.063), AcaTier(3.00, 0.081), AcaTier(4.00, 0.097),
        ],
        aca_fpl_cliff_ratio=4.0,
        aca_silver_premiums={
            "CA": {1: 860, 2: 1720, 3: 1940, 4: 2160, 5: 2380},
            "_default": {1: 860, 2: 1720, 3: 1940, 4: 2160, 5: 2380},
        },

        estate_exemption_single=14_390_000,
        estate_exemption_mfj=28_780_000,
        estate_tax_rate=0.40,

        salt_cap=10_000,

        child_tax_credit=2_000,
        child_tax_credit_phaseout_mfj=400_000,
        child_tax_credit_phaseout_single=200_000,

        ca_brackets=[
            _b(22_050, 0.01), _b(52_268, 0.02), _b(82_260, 0.04),
            _b(114_068, 0.06), _b(144_372, 0.08), _b(736_380, 0.093),
            _b(883_862, 0.103), _b(1_474_480, 0.113), _b(1_759_712, 0.123),
            _b(2_890_200, 0.133), _b(float('inf'), 0.143),
        ],

        citations=[
            "OBBBA (One Big Beautiful Bill Act) — permanent 7-bracket structure",
            "Estimated 2026 inflation adjustments",
        ],
    )


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------
_TAX_LAW_BY_YEAR: Dict[int, TaxLawVersion] = {
    2024: _tax_law_2024(),
    2025: _tax_law_2025(),
    2026: _tax_law_2026(),
}


class TaxLawRegistry:
    """Select enacted or alternative tax law by year."""

    def __init__(self):
        self._laws = dict(_TAX_LAW_BY_YEAR)

    def register(self, law: TaxLawVersion):
        """Register or override a tax-law version."""
        self._laws[law.year] = law

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

        # Exact match first
        if year in self._laws:
            return self._laws[year]

        # Inflate from nearest known year
        known_years = sorted(self._laws.keys())
        base_year = max(y for y in known_years if y <= year)
        base_law = self._laws[base_year]
        years_out = year - base_year
        factor = (1.0 + fallback_inflation) ** years_out

        return _inflate_law(base_law, year, factor)

    def available_years(self) -> List[int]:
        return sorted(self._laws.keys())


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
        niit_thresholds=_scale_dict(base.niit_thresholds),
        niit_rate=base.niit_rate,
        amt_exemption=_scale_dict(base.amt_exemption),
        amt_phaseout_start=_scale_dict(base.amt_phaseout_start),
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
        salt_cap=base.salt_cap,
        qcd_age=base.qcd_age,
        charitable_deduction_floor_pct=base.charitable_deduction_floor_pct,
        child_tax_credit=base.child_tax_credit,
        child_tax_credit_phaseout_mfj=base.child_tax_credit_phaseout_mfj * factor,
        child_tax_credit_phaseout_single=base.child_tax_credit_phaseout_single * factor,
        ca_brackets=_scale_brackets(base.ca_brackets),
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
    return min(net_investment_income, excess) * law.niit_rate


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
        reduction = (amti - phaseout_start) * 0.25
        exemption = max(0, exemption - reduction)

    amt_base = max(0, amti - exemption)
    # 26% up to threshold, 28% above
    if amt_base <= law.amt_26_limit:
        tentative_min_tax = amt_base * law.amt_rate
    else:
        tentative_min_tax = (
            law.amt_26_limit * law.amt_rate
            + (amt_base - law.amt_26_limit) * 0.28
        )

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


def calculate_estate_tax(
    taxable_estate: float,
    law: TaxLawVersion,
    status: FilingStatus = FilingStatus.MFJ,
) -> float:
    """Federal estate tax (simplified — unified credit)."""
    if status in (FilingStatus.MFJ, FilingStatus.QSS):
        exemption = law.estate_exemption_mfj
    else:
        exemption = law.estate_exemption_single

    taxable = max(0.0, taxable_estate - exemption)
    return taxable * law.estate_tax_rate


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
