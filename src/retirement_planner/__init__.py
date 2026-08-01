"""
Retirement Planner - A flexible retirement planning engine

A Python library for modeling retirement scenarios with:
- Account growth projections
- Income and expense modeling
- Tax calculations
- Monte Carlo simulation
- Scenario comparison
- Roth conversion planning
- Social Security optimization

Usage:
    from retirement_planner import Planner, Scenario
    
    # Load from config
    planner = Planner.from_config("my_plan.json")
    
    # Run single projection
    result = planner.project("baseline")
    
    # Run Monte Carlo
    mc = planner.monte_carlo(num_simulations=1000)
    
    # Compare scenarios
    comparison = planner.compare_scenarios(["baseline", "early_retire", "high_spending"])
"""

__version__ = "0.1.0"

from .models import (
    Person, Account, IncomeStream, Expense, Mortgage,
    Windfall, HousingEvent, RothConversion, EconomicAssumptions,
    RSUGrant, RefresherPolicy, Bonus, EquityComp,
    MonetaryConvention,
)
from .engine import RetirementPlanner
from .simulators import MonteCarloEngine, ScenarioComparator
from .reports import (
    generate_summary_report,
    generate_cash_flow_report,
    generate_mc_report,
    export_json,
    export_csv,
    export_markdown,
)
try:
    from .pdf_report import generate_pdf_report
except ImportError:
    generate_pdf_report = None
try:
    from .charts import (
        plot_net_worth_trajectory,
        plot_mc_fan_chart,
        plot_income_vs_expenses,
        plot_tax_breakdown,
    )
except ImportError:
    pass
from .sensitivity import SensitivityAnalyzer
from .tax_law import (
    TaxLawVersion, TaxLawRegistry, FilingStatus,
    bracket_tax, calculate_niit, calculate_amt, calculate_irmaa,
    calculate_aca_subsidy, calculate_estate_tax, calculate_child_tax_credit,
    calculate_qcd, determine_filing_status,
)
from .monthly_events import (
    MonthlyEvent, calculate_monthly_aca_subsidy, calculate_irmaa_assessment,
    calculate_rmd_events, process_year_events,
)
from .optimizer import (
    YearDecision, CandidateDecision, FeasibilityResult, DecisionTrace,
    WithdrawalOptimizer, OptimizerConfig,
    FixedSpendingPolicy, GuardrailsPolicy, VPWPolicy, FloorCeilingPolicy,
)
from .portfolio import (
    AssetClass, DEFAULT_ASSET_CLASSES, CapitalMarketModel, MarketYear,
    BondTentPolicy, STRESS_SCENARIOS, optimize_asset_location, rebalance_portfolio,
)
from .household import (
    MortalityModel, HouseholdLifetime, sample_household_lifetimes,
    SurvivorTransition, compute_survivor_transition,
    HealthcarePhase, DEFAULT_HEALTHCARE_PHASES, calculate_healthcare_cost,
    SpendingPhaseProfile, HouseholdState,
)
from .explain import (
    TaxTrace, build_tax_trace, ThresholdWarning, check_thresholds,
    ReproducibilityMetadata, ScenarioDiff, compare_scenarios,
    ValidationResult, validate_projection,
)
from .fixes import (
    HousingEventResult, process_housing_event,
    RothConversionResult, process_roth_conversions,
    apply_medical_inflation, process_medical_expenses,
)
from .tax_lots import (
    TaxLot, TaxLotTracker, LiquidationResult,
    calculate_121_exclusion,
)
from .sim_integration import (
    determine_annual_filing_status, compute_survivor_ss_benefit,
    GBMParams, simulate_gbm_path, simulate_rsu_value,
    ContributionLimits, get_contribution_limits,
    calculate_401k_limit, calculate_ira_limit, calculate_hsa_limit,
)
from .tech_comp import (
    ESPPGrant, ESPPDisposition, calculate_espp_purchase_price,
    calculate_espp_income, simulate_espp_period,
    NQSOGrant, NQSOExercise, exercise_nqso, calculate_nqso_spread_tax,
    MegaBackdoorRoth, AfterTaxAccount,
)
from .ltc_solver import (
    LTCConfig, LTCEvent, simulate_ltc_events, calculate_ltc_annual_cost,
    ltc_probability_by_age, SolverResult, reverse_solve,
    solve_retirement_age, solve_savings_rate, solve_spending,
)
