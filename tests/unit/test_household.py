"""Tests for household.py — mortality, survivor, healthcare, spending phases."""
from datetime import date

import pytest
from retirement_planner.household import (
    MortalityModel, HouseholdLifetime, sample_household_lifetimes,
    compute_survivor_transition,
    HealthcarePhase, DEFAULT_HEALTHCARE_PHASES, calculate_healthcare_cost,
    SpendingPhaseProfile, HouseholdState,
)
from retirement_planner.models import Person


# ---------------------------------------------------------------------------
# Mortality
# ---------------------------------------------------------------------------
class TestMortalityModel:

    def test_young_high_survival(self):
        m = MortalityModel()
        p = m.survival_probability(35, is_male=True)
        assert p > 0.99

    def test_old_lower_survival(self):
        m = MortalityModel()
        p = m.survival_probability(85, is_male=True)
        assert p < 0.90

    def test_female_higher_survival(self):
        m = MortalityModel()
        p_male = m.survival_probability(75, is_male=True)
        p_female = m.survival_probability(75, is_male=False)
        assert p_female > p_male

    def test_expected_remaining_years(self):
        m = MortalityModel()
        remaining = m.expected_remaining_years(65, is_male=True)
        assert 10 < remaining < 30  # ~20 years for 65-year-old male

    def test_longevity_boost(self):
        m = MortalityModel(longevity_boost=1.1)
        p_boosted = m.survival_probability(80, is_male=True)
        m2 = MortalityModel(longevity_boost=1.0)
        p_normal = m2.survival_probability(80, is_male=True)
        assert p_boosted > p_normal

    def test_sample_death_age(self):
        m = MortalityModel()
        death_age = m.sample_death_age(65, is_male=True)
        assert 65 <= death_age <= 105


class TestSampleHouseholdLifetimes:

    def test_returns_statistics(self):
        median_p, median_s, lifetimes = sample_household_lifetimes(
            primary_age=30, spouse_age=30,
            num_simulations=100,
        )
        assert 60 < median_p < 100
        assert 60 < median_s < 100
        assert len(lifetimes) == 100

    def test_lifetimes_have_fields(self):
        _, _, lifetimes = sample_household_lifetimes(30, 30, num_simulations=10)
        for lt in lifetimes:
            assert lt.primary_death_age >= 30
            assert lt.spouse_death_age >= 30
            assert lt.years_together >= 0


# ---------------------------------------------------------------------------
# Survivor transitions
# ---------------------------------------------------------------------------
class TestSurvivorTransition:

    def test_death_year_still_mfj(self):
        t = compute_survivor_transition(
            year_of_death=2040, current_year=2040, deceased="spouse",
            primary_age=70, has_dependents=False,
            ss_primary_annual=30000, ss_spouse_annual=20000,
            household_expenses=80000,
        )
        assert t.new_filing_status == "MFJ"

    def test_qss_with_dependents(self):
        t = compute_survivor_transition(
            year_of_death=2040, current_year=2041, deceased="spouse",
            primary_age=71, has_dependents=True,
            ss_primary_annual=30000, ss_spouse_annual=20000,
            household_expenses=80000,
        )
        assert t.new_filing_status == "QSS"
        assert t.years_until_qss_expiry == 1

    def test_single_without_dependents(self):
        t = compute_survivor_transition(
            year_of_death=2040, current_year=2041, deceased="spouse",
            primary_age=71, has_dependents=False,
            ss_primary_annual=30000, ss_spouse_annual=20000,
            household_expenses=80000,
        )
        assert t.new_filing_status == "Single"

    def test_expense_reduction(self):
        t = compute_survivor_transition(
            year_of_death=2040, current_year=2041, deceased="spouse",
            primary_age=71, has_dependents=False,
            ss_primary_annual=30000, ss_spouse_annual=20000,
            household_expenses=80000,
        )
        assert t.expense_change < 0  # Expenses decrease
        assert t.expense_change == pytest.approx(-80000 * 0.25)

    def test_survivor_ss_benefit(self):
        # Spouse dies, primary gets higher of own or survivor benefit
        t = compute_survivor_transition(
            year_of_death=2040, current_year=2041, deceased="spouse",
            primary_age=71, has_dependents=False,
            ss_primary_annual=20000, ss_spouse_annual=30000,
            household_expenses=80000,
        )
        # Survivor gets $30K (higher of own $20K or deceased $30K)
        # Was getting average of $25K → increase of $5K
        assert t.ss_benefit_change == pytest.approx(5000)


# ---------------------------------------------------------------------------
# Healthcare
# ---------------------------------------------------------------------------
class TestHealthcareCost:

    def test_aca_age(self):
        cost = calculate_healthcare_cost(age=50, num_people=2)
        assert cost > 0
        # ACA: $800/mo × 12 × 2 = $19,200
        assert cost == pytest.approx(800 * 12 * 2)

    def test_medicare_age(self):
        cost = calculate_healthcare_cost(age=70, num_people=2)
        assert cost > 0
        # Medicare AB ($175) + Medigap ($200) = $375/mo × 12 × 2 = $9,000
        assert cost == pytest.approx(375 * 12 * 2)

    def test_inflation(self):
        cost_now = calculate_healthcare_cost(age=50, years_from_base=0)
        cost_future = calculate_healthcare_cost(age=50, years_from_base=5, inflation_rate=0.04)
        assert cost_future > cost_now

    def test_irmaa_adds_cost(self):
        cost_base = calculate_healthcare_cost(age=70, irmaa_surcharge_monthly=0)
        cost_irmaa = calculate_healthcare_cost(age=70, irmaa_surcharge_monthly=200)
        assert cost_irmaa > cost_base
        assert cost_irmaa - cost_base == pytest.approx(200 * 12 * 2)


# ---------------------------------------------------------------------------
# Spending phases
# ---------------------------------------------------------------------------
class TestSpendingPhaseProfile:

    def test_accumulation(self):
        p = SpendingPhaseProfile()
        assert p.apply(100_000, 50) == 100_000  # 1.0x

    def test_go_go(self):
        p = SpendingPhaseProfile()
        assert p.apply(100_000, 70) == pytest.approx(115_000)  # 1.15x

    def test_slow_go(self):
        p = SpendingPhaseProfile()
        assert p.apply(100_000, 80) == pytest.approx(90_000)  # 0.90x

    def test_no_go(self):
        p = SpendingPhaseProfile()
        assert p.apply(100_000, 90) == pytest.approx(70_000)  # 0.70x

    def test_multiplier_transitions(self):
        p = SpendingPhaseProfile()
        assert p.spending_multiplier(64) == 1.0
        assert p.spending_multiplier(65) == 1.15
        assert p.spending_multiplier(74) == 1.15   # still go-go
        assert p.spending_multiplier(75) == 1.15   # boundary: go-go end
        assert p.spending_multiplier(76) == 0.90   # slow-go
        assert p.spending_multiplier(84) == 0.90   # still slow-go
        assert p.spending_multiplier(85) == 0.90   # boundary: slow-go end
        assert p.spending_multiplier(86) == 0.70   # no-go


# ---------------------------------------------------------------------------
# Household state
# ---------------------------------------------------------------------------
class TestHouseholdState:

    def test_initial_state(self):
        s = HouseholdState(year=2026, primary_age=30, spouse_age=30)
        assert s.filing_status == "MFJ"
        assert s.primary_alive is True
        assert s.spouse_alive is True

    def test_spouse_death_changes_status(self):
        s = HouseholdState(year=2040, primary_age=70, spouse_age=70)
        s.spouse_alive = False
        s._update_filing_status()
        assert s.filing_status == "Single"

    def test_spouse_death_with_dependents(self):
        s = HouseholdState(year=2040, primary_age=70, spouse_age=70, num_dependents=1)
        s.spouse_alive = False
        s._update_filing_status()
        assert s.filing_status == "QSS"

    def test_spending_phase_update(self):
        s = HouseholdState(year=2026, primary_age=30, spouse_age=30)
        s.primary_age = 70
        s.spouse_age = 70
        s._update_spending_phase()
        assert s.spending_phase == "go_go"


# ---------------------------------------------------------------------------
# Person.coverage_at_age — per-person healthcare coverage
# ---------------------------------------------------------------------------
class TestCoverageAtAge:

    def test_auto_medicare_at_65(self):
        """Auto coverage → Medicare when age >= 65."""
        p = Person(name="A", birth_date=date(1960, 1, 1),
                    retirement_date=date(2025, 1, 1))
        assert p.coverage_at_age(65) == "medicare"
        assert p.coverage_at_age(70) == "medicare"

    def test_auto_aca_under_65(self):
        """Auto coverage → ACA when age < 65."""
        p = Person(name="A", birth_date=date(1970, 1, 1),
                    retirement_date=date(2035, 1, 1))
        assert p.coverage_at_age(50) == "aca"
        assert p.coverage_at_age(64) == "aca"

    def test_explicit_employer_overrides_auto(self):
        """Explicit 'employer' overrides auto Medicare at age 67."""
        p = Person(name="A", birth_date=date(1960, 1, 1),
                    retirement_date=date(2025, 1, 1),
                    coverage_type="employer")
        assert p.coverage_at_age(67) == "employer"
        assert p.coverage_at_age(50) == "employer"

    def test_explicit_medicare_at_young_age(self):
        """Explicit 'medicare' works even below 65 (e.g. disability)."""
        p = Person(name="A", birth_date=date(1980, 1, 1),
                    retirement_date=date(2045, 1, 1),
                    coverage_type="medicare")
        assert p.coverage_at_age(50) == "medicare"

    def test_explicit_none(self):
        """Explicit 'none' means no coverage at any age."""
        p = Person(name="A", birth_date=date(1970, 1, 1),
                    retirement_date=date(2035, 1, 1),
                    coverage_type="none")
        assert p.coverage_at_age(40) == "none"
        assert p.coverage_at_age(70) == "none"

    def test_explicit_aca_at_70(self):
        """Explicit 'aca' keeps ACA even past 65."""
        p = Person(name="A", birth_date=date(1955, 1, 1),
                    retirement_date=date(2020, 1, 1),
                    coverage_type="aca")
        assert p.coverage_at_age(70) == "aca"


# ---------------------------------------------------------------------------
# Mixed-age couple coverage scenarios
# ---------------------------------------------------------------------------
class TestMixedAgeCoverage:
    """Simulate mixed-age couples to verify per-person IRMAA and ACA."""

    def test_medicare_plus_aca(self):
        """Person A 67 (Medicare) + Person B 62 (ACA) → correct coverage."""
        from retirement_planner.engine import RetirementPlanner
        from retirement_planner.models import (
            EconomicAssumptions, Scenario,
        )
        from datetime import date

        # Person A born 1959 (age 67 in 2026), Person B born 1964 (age 62 in 2026)
        primary = Person(
            name="Primary",
            birth_date=date(1959, 1, 1),
            retirement_date=date(2024, 1, 1),
            longevity_age=90,
        )
        spouse = Person(
            name="Spouse",
            birth_date=date(1964, 1, 1),
            retirement_date=date(2029, 1, 1),
            longevity_age=90,
        )
        # Both use auto coverage
        assert primary.coverage_at_age(67) == "medicare"
        assert spouse.coverage_at_age(62) == "aca"

    def test_employer_overrides_medicare_plus_aca(self):
        """Person A 67 (employer) + Person B 62 (ACA) → employer overrides."""
        from datetime import date

        primary = Person(
            name="Primary",
            birth_date=date(1959, 1, 1),
            retirement_date=date(2024, 1, 1),
            longevity_age=90,
            coverage_type="employer",
        )
        spouse = Person(
            name="Spouse",
            birth_date=date(1964, 1, 1),
            retirement_date=date(2029, 1, 1),
            longevity_age=90,
        )
        # Employer overrides Medicare for primary
        assert primary.coverage_at_age(67) == "employer"
        assert spouse.coverage_at_age(62) == "aca"

    def test_both_medicare(self):
        """Both age >= 65 with auto → both Medicare."""
        from datetime import date

        primary = Person(
            name="Primary",
            birth_date=date(1955, 1, 1),
            retirement_date=date(2020, 1, 1),
            longevity_age=90,
        )
        spouse = Person(
            name="Spouse",
            birth_date=date(1957, 1, 1),
            retirement_date=date(2022, 1, 1),
            longevity_age=90,
        )
        assert primary.coverage_at_age(71) == "medicare"
        assert spouse.coverage_at_age(69) == "medicare"

    def test_both_aca(self):
        """Both under 65 with auto → both ACA."""
        from datetime import date

        primary = Person(
            name="Primary",
            birth_date=date(1970, 1, 1),
            retirement_date=date(2035, 1, 1),
            longevity_age=90,
        )
        spouse = Person(
            name="Spouse",
            birth_date=date(1972, 1, 1),
            retirement_date=date(2037, 1, 1),
            longevity_age=90,
        )
        assert primary.coverage_at_age(56) == "aca"
        assert spouse.coverage_at_age(54) == "aca"
