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
from .pdf_report import generate_pdf_report
from .charts import (
    plot_net_worth_trajectory,
    plot_mc_fan_chart,
    plot_income_vs_expenses,
    plot_tax_breakdown,
)
from .sensitivity import SensitivityAnalyzer
