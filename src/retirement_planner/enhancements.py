"""
Enhanced features: Roth conversions, Social Security, scenario comparison.
"""
from typing import Dict, List, Optional, Tuple
from datetime import date, datetime
from dataclasses import dataclass
import json


@dataclass
class RothConversionPlan:
    """Roth conversion strategy."""
    year: int
    source_account: str
    target_account: str
    amount: float
    tax_bracket: float
    tax_cost: float


class RothConversionOptimizer:
    """Optimize Roth conversion timing and amounts."""
    
    def __init__(self, planner):
        self.planner = planner
        self.scenario = planner.scenario
    
    def find_optimal_conversions(
        self,
        max_annual_amount: float = 500_000,
        target_bracket: float = 0.24
    ) -> List[RothConversionPlan]:
        """
        Find optimal Roth conversion strategy.
        
        Key insight: Convert during low-income years (early retirement)
        to stay in lower tax brackets, reducing lifetime taxes.
        
        Strategy:
        1. Identify low-income years (post-retirement, pre-SS)
        2. Calculate how much to convert to fill lower brackets
        3. Balance against future tax rates and RMDs
        """
        conversions = []
        
        # Get cash flow projection
        projections = self.planner.project_cash_flow()
        
        # Find Roth IRA account
        roth_account = None
        trad_account = None
        for account in self.scenario.accounts:
            if account.account_type == "roth_ira":
                roth_account = account
            if account.account_type == "trad_ira":
                trad_account = account
        
        if not roth_account or not trad_account:
            return conversions
        
        # Tax brackets for MFJ (2024)
        brackets = [
            (23_200, 0.10),
            (94_300, 0.12),
            (201_050, 0.22),
            (383_900, 0.24),
            (487_450, 0.32),
            (731_200, 0.35),
            (float('inf'), 0.37),
        ]
        
        # Identify low-income years (retirement to SS claiming)
        primary_retire_year = self.scenario.primary.retirement_date.year
        ss_start_year = primary_retire_year + (self.scenario.social_security.primary_claiming_age - 
                                               (primary_retire_year - self.scenario.primary.birth_date.year))
        
        for proj in projections:
            year = proj["year"]
            income = proj["income"]
            
            # Only consider low-income years
            if year < primary_retire_year or year > ss_start_year:
                continue
            
            # Calculate room in current bracket
            taxable_income = max(0, income - 29_200)  # Standard deduction
            
            # Find current bracket
            current_bracket_limit = 0
            current_bracket_rate = 0.10
            for limit, rate in brackets:
                if taxable_income < limit:
                    current_bracket_limit = limit
                    current_bracket_rate = rate
                    break
            
            # Calculate how much we can convert at this bracket
            room_in_bracket = current_bracket_limit - taxable_income
            conversion_amount = min(room_in_bracket, max_annual_amount)
            
            if conversion_amount > 0:
                # Estimate tax cost
                tax_cost = conversion_amount * current_bracket_rate
                
                conversions.append(RothConversionPlan(
                    year=year,
                    source_account=trad_account.id,
                    target_account=roth_account.id,
                    amount=conversion_amount,
                    tax_bracket=current_bracket_rate,
                    tax_cost=tax_cost,
                ))
        
        return conversions
    
    def calculate_conversion_benefit(self, conversions: List[RothConversionPlan]) -> Dict:
        """Calculate the benefit of Roth conversions."""
        total_converted = sum(c.amount for c in conversions)
        total_tax_cost = sum(c.tax_cost for c in conversions)
        
        # Estimate tax savings (vs taking as RMD later at higher bracket)
        # Assume 32% bracket in retirement for RMDs
        future_bracket = 0.32
        estimated_future_tax = total_converted * future_bracket
        tax_savings = estimated_future_tax - total_tax_cost
        
        return {
            "total_converted": total_converted,
            "total_tax_cost": total_tax_cost,
            "estimated_future_tax": estimated_future_tax,
            "tax_savings": tax_savings,
            "num_conversion_years": len(conversions),
            "avg_annual_conversion": total_converted / len(conversions) if conversions else 0,
        }


class SocialSecurityOptimizer:
    """Optimize Social Security claiming strategy."""
    
    def __init__(self, planner):
        self.planner = planner
        self.scenario = planner.scenario
    
    def calculate_benefit_at_age(self, person, claiming_age: int) -> float:
        """Calculate monthly benefit at claiming age."""
        ss = self.scenario.social_security
        
        if person.name == "Primary":
            full_benefit = ss.primary_benefit_at_67
        else:
            full_benefit = ss.spouse_benefit_at_67
        
        # Adjustment for early/late claiming
        if claiming_age < 67:
            # Early claiming: 6.67% reduction per year before 67 (first 3 years)
            # 5% per year after that
            years_early = 67 - claiming_age
            if years_early <= 3:
                reduction = years_early * 0.0667
            else:
                reduction = 3 * 0.0667 + (years_early - 3) * 0.05
            return full_benefit * (1 - reduction)
        elif claiming_age > 67:
            # Late claiming: 8% credit per year after 67
            years_late = claiming_age - 67
            return full_benefit * (1 + years_late * 0.08)
        else:
            return full_benefit
    
    def compare_strategies(self) -> Dict:
        """Compare different claiming strategies."""
        strategies = {}
        
        for primary_age in [62, 64, 66, 67, 68, 70]:
            for spouse_age in [62, 64, 66, 67, 68, 70]:
                key = f"primary_{primary_age}_spouse_{spouse_age}"
                
                # Calculate lifetime benefits
                primary_benefit = self.calculate_benefit_at_age(self.scenario.primary, primary_age)
                spouse_benefit = self.calculate_benefit_at_age(self.scenario.spouse, spouse_age)
                
                # Simplified: assume claiming from age to 90
                primary_years = 90 - primary_age
                spouse_years = 90 - spouse_age
                
                total_jimmy = primary_benefit * 12 * primary_years
                total_faith = spouse_benefit * 12 * spouse_years
                total = total_jimmy + total_faith
                
                strategies[key] = {
                    "primary_claiming_age": primary_age,
                    "spouse_claiming_age": spouse_age,
                    "primary_monthly": primary_benefit,
                    "spouse_monthly": spouse_benefit,
                    "primary_lifetime": total_jimmy,
                    "spouse_lifetime": total_faith,
                    "total_lifetime": total,
                }
        
        # Find optimal
        optimal_key = max(strategies.keys(), key=lambda k: strategies[k]["total_lifetime"])
        
        return {
            "strategies": strategies,
            "optimal": strategies[optimal_key],
        }
    
    def project_ss_income(self, primary_claiming_age: int = 67, spouse_claiming_age: int = 67) -> List[Dict]:
        """Project Social Security income year by year."""
        projections = []
        
        primary_birth = self.scenario.primary.birth_date.year
        spouse_birth = self.scenario.spouse.birth_date.year
        
        primary_monthly = self.calculate_benefit_at_age(self.scenario.primary, primary_claiming_age)
        spouse_monthly = self.calculate_benefit_at_age(self.scenario.spouse, spouse_claiming_age)
        
        current_year = datetime.now().year
        
        for year in range(current_year, 2090):
            primary_age = year - primary_birth
            spouse_age = year - spouse_birth
            
            primary_income = 0
            spouse_income = 0
            
            if primary_age >= primary_claiming_age:
                years_since = primary_age - primary_claiming_age
                cola = self.scenario.social_security.cola_rate
                primary_income = primary_monthly * 12 * (1 + cola) ** years_since
            
            if spouse_age >= spouse_claiming_age:
                years_since = spouse_age - spouse_claiming_age
                cola = self.scenario.social_security.cola_rate
                spouse_income = spouse_monthly * 12 * (1 + cola) ** years_since
            
            projections.append({
                "year": year,
                "primary_age": primary_age,
                "spouse_age": spouse_age,
                "primary_income": primary_income,
                "spouse_income": spouse_income,
                "total_ss": primary_income + spouse_income,
            })
        
        return projections


class ScenarioComparator:
    """Compare multiple retirement scenarios."""
    
    def __init__(self, planners: Dict[str, object]):
        """
        Args:
            planners: Dictionary of scenario_name -> RetirementPlanner
        """
        self.planners = planners
    
    def compare_cash_flow(self, scenarios: List[str] = None) -> Dict:
        """Compare year-by-year cash flow across scenarios."""
        if scenarios is None:
            scenarios = list(self.planners.keys())
        
        comparison = {}
        for scenario_name in scenarios:
            planner = self.planners[scenario_name]
            projections = planner.project_cash_flow()
            comparison[scenario_name] = projections
        
        return comparison
    
    def compare_monte_carlo(
        self,
        scenarios: List[str] = None,
        num_simulations: int = 1000
    ) -> Dict:
        """Compare Monte Carlo results across scenarios."""
        from .simulators import MonteCarloEngine
        
        if scenarios is None:
            scenarios = list(self.planners.keys())
        
        comparison = {}
        for scenario_name in scenarios:
            planner = self.planners[scenario_name]
            mc = MonteCarloEngine(planner)
            comparison[scenario_name] = mc.run(num_simulations)
        
        return comparison
    
    def compare_net_worth(self, year: int, scenarios: List[str] = None) -> Dict:
        """Compare net worth at a specific year."""
        if scenarios is None:
            scenarios = list(self.planners.keys())
        
        comparison = {}
        for scenario_name in scenarios:
            planner = self.planners[scenario_name]
            nw = planner.calculate_net_worth(year)
            comparison[scenario_name] = nw
        
        return comparison
    
    def sensitivity_analysis(
        self,
        base_scenario: str,
        variable: str,
        values: List[float]
    ) -> Dict:
        """
        Run sensitivity analysis on a single variable.
        
        Modifies the scenario and re-runs Monte Carlo to show
        how changes in one variable affect the outcome.
        """
        from .simulators import MonteCarloEngine
        
        results = {}
        base_planner = self.planners[base_scenario]
        
        for value in values:
            # Create a modified scenario
            # This is a simplified version - full implementation would
            # deep copy and modify the specific variable
            results[value] = {
                "variable": variable,
                "value": value,
                # Would run Monte Carlo here
            }
        
        return results


class TaxCalculator:
    """Advanced tax calculations."""
    
    def __init__(self, state: str = "CA"):
        self.state = state
    
    def calculate_federal_tax(self, taxable_income: float, filing_status: str = "MFJ") -> float:
        """Calculate federal income tax."""
        if filing_status == "MFJ":
            brackets = [
                (23_200, 0.10),
                (94_300, 0.12),
                (201_050, 0.22),
                (383_900, 0.24),
                (487_450, 0.32),
                (731_200, 0.35),
                (float('inf'), 0.37),
            ]
            standard_deduction = 29_200
        else:  # Single
            brackets = [
                (11_600, 0.10),
                (47_150, 0.12),
                (100_525, 0.22),
                (191_950, 0.24),
                (243_725, 0.32),
                (609_350, 0.35),
                (float('inf'), 0.37),
            ]
            standard_deduction = 14_600
        
        taxable = max(0, taxable_income - standard_deduction)
        
        tax = 0
        prev_limit = 0
        for limit, rate in brackets:
            if taxable <= prev_limit:
                break
            taxable_in_bracket = min(taxable, limit) - prev_limit
            tax += taxable_in_bracket * rate
            prev_limit = limit
        
        return tax
    
    def calculate_state_tax(self, taxable_income: float, state: str = None) -> float:
        """Calculate state income tax."""
        state = state or self.state
        
        if state == "CA":
            brackets = [
                (20_824, 0.01),
                (49_368, 0.02),
                (77_918, 0.04),
                (108_152, 0.06),
                (136_700, 0.08),
                (698_274, 0.093),
                (837_922, 0.103),
                (1_396_546, 0.113),
                (1_666_074, 0.123),
                (2_732_666, 0.133),
                (float('inf'), 0.143),
            ]
        elif state == "TX":
            return 0  # No state income tax
        elif state == "WA":
            return 0  # No state income tax (has capital gains tax)
        else:
            # Default to 5% flat
            return taxable_income * 0.05
        
        tax = 0
        prev_limit = 0
        for limit, rate in brackets:
            if taxable_income <= prev_limit:
                break
            taxable_in_bracket = min(taxable_income, limit) - prev_limit
            tax += taxable_in_bracket * rate
            prev_limit = limit
        
        return tax
    
    def calculate_total_tax(self, income: float, filing_status: str = "MFJ") -> float:
        """Calculate total federal + state tax."""
        federal = self.calculate_federal_tax(income, filing_status)
        state = self.calculate_state_tax(income)
        return federal + state
    
    def calculate_marginal_rate(self, income: float, filing_status: str = "MFJ") -> float:
        """Calculate marginal tax rate."""
        tax1 = self.calculate_total_tax(income, filing_status)
        tax2 = self.calculate_total_tax(income + 1000, filing_status)
        return (tax2 - tax1) / 1000
    
    def optimize_roth_conversion(
        self,
        current_income: float,
        trad_ira_balance: float,
        max_conversion: float = 500_000
    ) -> Dict:
        """
        Find optimal Roth conversion amount to stay in target bracket.
        
        Returns conversion amount and tax cost.
        """
        # Try different conversion amounts
        best_amount = 0
        best_bracket = 0.10
        
        for amount in range(0, min(int(max_conversion), int(trad_ira_balance)) + 10000, 10000):
            total_income = current_income + amount
            marginal_rate = self.calculate_marginal_rate(total_income)
            
            if marginal_rate <= 0.24:  # Stay in 24% bracket
                best_amount = amount
                best_bracket = marginal_rate
        
        tax_cost = self.calculate_total_tax(current_income + best_amount) - self.calculate_total_tax(current_income)
        
        return {
            "conversion_amount": best_amount,
            "tax_bracket": best_bracket,
            "tax_cost": tax_cost,
            "effective_rate": tax_cost / best_amount if best_amount > 0 else 0,
        }
