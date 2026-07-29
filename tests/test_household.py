"""Tests for household.py — mortality, survivor, healthcare, spending phases."""
import pytest
from retirement_planner.household import (
    MortalityModel, HouseholdLifetime, sample_household_lifetimes,
    compute_survivor_transition,
    HealthcarePhase, DEFAULT_HEALTHCARE_PHASES, calculate_healthcare_cost,
    SpendingPhaseProfile, HouseholdState,
)


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
