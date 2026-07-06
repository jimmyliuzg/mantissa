"""
Core retirement planning engine.
"""
from typing import Dict, List, Optional
from datetime import datetime
import math
import random

from .models import (
    Scenario, Person, Account, IncomeStream, Expense,
    Mortgage, Windfall, HousingEvent, RothConversion,
    EconomicAssumptions, SocialSecurity
)


class RetirementPlanner:
    """
    Main retirement planning engine.
    
    Projects year-by-year cash flow, account balances, taxes,
    and runs Monte Carlo simulations to calculate success rates.
    """
    
    def __init__(self, scenario: Scenario):
        self.scenario = scenario
        self.accounts = {a.id: a for a in scenario.accounts}
        self.start_year = datetime.now().year
    
    @classmethod
    def from_config(cls, config_path: str) -> 'RetirementPlanner':
        """Load planner from JSON config file."""
        import json
        with open(config_path) as f:
            config = json.load(f)
        
        # Parse config into Scenario
        # This is a simplified parser - full implementation would handle all fields
        from datetime import date
        
        primary = Person(
            name=config["primary"]["name"],
            birth_date=date.fromisoformat(config["primary"]["birth_date"]),
            retirement_date=date.fromisoformat(config["primary"]["retirement_date"]),
            longevity_age=config["primary"].get("longevity_age", 90),
        )
        
        spouse = Person(
            name=config["spouse"]["name"],
            birth_date=date.fromisoformat(config["spouse"]["birth_date"]),
            retirement_date=date.fromisoformat(config["spouse"]["retirement_date"]),
            longevity_age=config["spouse"].get("longevity_age", 90),
        )
        
        # Parse accounts
        accounts = []
        for acc_config in config.get("accounts", []):
            accounts.append(Account(
                id=acc_config["id"],
                name=acc_config["name"],
                account_type=acc_config["type"],
                tax_treatment=acc_config.get("tax_treatment", "taxable"),
                balance=acc_config["balance"],
                growth_rate=acc_config.get("growth_rate", 0.088),
            ))
        
        # Parse other components...
        economic = EconomicAssumptions(
            general_inflation=config.get("economic", {}).get("inflation", 0.0254),
        )
        
        scenario = Scenario(
            name=config.get("name", "Default Scenario"),
            description=config.get("description", ""),
            primary=primary,
            spouse=spouse,
            economic=economic,
            accounts=accounts,
            income_streams=[],  # TODO: parse from config
            expenses=[],  # TODO: parse from config
            mortgages=[],  # TODO: parse from config
            legacy_goal=config.get("legacy_goal", 2_000_000),
            state=config.get("state", "CA"),
        )
        
        return cls(scenario)
    
    def get_account_balance(self, account_id: str, year: int, scenario: str = "mean") -> float:
        """Get projected account balance for a given year."""
        account = self.accounts.get(account_id)
        if not account:
            return 0.0
        
        years = year - self.start_year
        rates = self.scenario.economic.get_rate(scenario)
        
        if account.account_type == "real_estate":
            rate = rates["housing_appreciation"]
        elif account.is_depreciating:
            rate = -0.04
        elif account.growth_rate == 0:
            rate = 0
        else:
            rate = account.growth_rate
        
        return account.project_balance(years, rate)
    
    def calculate_net_worth(self, year: int, scenario: str = "mean") -> Dict:
        """Calculate net worth at a given year."""
        total_assets = 0
        total_liabilities = 0
        account_balances = {}
        
        for account_id, account in self.accounts.items():
            balance = self.get_account_balance(account_id, year, scenario)
            account_balances[account_id] = balance
            
            if balance >= 0:
                total_assets += balance
            else:
                total_liabilities += abs(balance)
        
        return {
            "total_assets": total_assets,
            "total_liabilities": total_liabilities,
            "net_worth": total_assets - total_liabilities,
            "accounts": account_balances,
        }
    
    def calculate_annual_income(self, year: int, scenario: str = "mean") -> Dict:
        """Calculate total income for a year."""
        total_income = 0
        income_by_source = {}
        
        for stream in self.scenario.income_streams:
            if stream.start_date.year <= year <= stream.end_date.year:
                years_active = year - stream.start_date.year
                amount = stream.monthly_amount * 12 * (1 + stream.growth_rate) ** years_active
                total_income += amount
                income_by_source[stream.name] = amount
        
        return {
            "total": total_income,
            "by_source": income_by_source,
        }
    
    def calculate_annual_expenses(self, year: int, scenario: str = "mean") -> Dict:
        """Calculate total expenses for a year."""
        rates = self.scenario.economic.get_rate(scenario)
        total_expenses = 0
        expenses_by_category = {}
        
        for expense in self.scenario.expenses:
            if expense.is_one_time:
                if expense.one_time_date and expense.one_time_date.year == year:
                    total_expenses += expense.one_time_amount
                    expenses_by_category[expense.name] = expense.one_time_amount
            else:
                if expense.start_date.year <= year <= expense.end_date.year:
                    years_active = year - expense.start_date.year
                    inflation_rate = rates.get("general_inflation", 0.025)
                    if expense.category == "medical":
                        inflation_rate = rates.get("medical_inflation", 0.033)
                    
                    amount = expense.monthly_amount * 12 * (1 + inflation_rate) ** years_active
                    total_expenses += amount
                    expenses_by_category[expense.name] = amount
        
        # Add mortgage payments
        for mortgage in self.scenario.mortgages:
            if mortgage.start_date.year <= year <= mortgage.end_date.year:
                amount = mortgage.monthly_payment * 12
                total_expenses += amount
                expenses_by_category[f"Mortgage - {mortgage.name}"] = amount
        
        return {
            "total": total_expenses,
            "by_category": expenses_by_category,
        }
    
    def calculate_taxes(self, year: int, income: float, scenario: str = "mean") -> float:
        """Simplified federal + state tax calculation."""
        # 2024 MFJ brackets (simplified)
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
        taxable_income = max(0, income - standard_deduction)
        
        federal_tax = 0
        prev_limit = 0
        for limit, rate in brackets:
            if taxable_income <= prev_limit:
                break
            taxable_in_bracket = min(taxable_income, limit) - prev_limit
            federal_tax += taxable_in_bracket * rate
            prev_limit = limit
        
        # California state tax (simplified)
        ca_brackets = [
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
        
        ca_tax = 0
        prev_limit = 0
        for limit, rate in ca_brackets:
            if taxable_income <= prev_limit:
                break
            taxable_in_bracket = min(taxable_income, limit) - prev_limit
            ca_tax += taxable_in_bracket * rate
            prev_limit = limit
        
        return federal_tax + ca_tax
    
    def calculate_social_security(self, year: int, person: Person) -> float:
        """Calculate Social Security benefit for a year."""
        age = year - person.birth_date.year
        ss = self.scenario.social_security
        
        if person.name == "Jimmy":
            claiming_age = ss.jimmy_claiming_age
            benefit_at_67 = ss.jimmy_benefit_at_67
        else:
            claiming_age = ss.faith_claiming_age
            benefit_at_67 = ss.faith_benefit_at_67
        
        if age < claiming_age:
            return 0.0
        
        # Calculate benefit with COLA
        years_since_claiming = age - claiming_age
        cola = ss.cola_rate
        monthly_benefit = benefit_at_67 * (1 + cola) ** years_since_claiming
        
        return monthly_benefit * 12
    
    def run_single_simulation(self, scenario_name: str = "mean", return_volatility: float = 0.15) -> Dict:
        """Run a single year-by-year projection."""
        total_taxes = 0
        total_ss = 0
        peak_nw = 0
        out_of_savings_year = None
        
        # Starting balances
        balances = {}
        for account_id, account in self.accounts.items():
            balances[account_id] = account.balance
        
        rates = self.scenario.economic.get_rate(scenario_name)
        
        for year in range(self.start_year, self.scenario.primary.birth_date.year + self.scenario.primary.longevity_age + 1):
            primary_age = year - self.scenario.primary.birth_date.year
            spouse_age = year - self.scenario.spouse.birth_date.year
            
            if primary_age > self.scenario.primary.longevity_age and spouse_age > self.scenario.spouse.longevity_age:
                break
            
            # Investment returns (with volatility in Monte Carlo)
            for account_id, balance in list(balances.items()):
                if balance <= 0:
                    continue
                account = self.accounts[account_id]
                
                if account.account_type == "real_estate":
                    base_rate = rates["housing_appreciation"]
                elif account.is_depreciating:
                    base_rate = -0.04
                elif account.growth_rate == 0:
                    base_rate = 0
                else:
                    base_rate = account.growth_rate
                
                if return_volatility > 0:
                    actual_rate = random.gauss(base_rate, return_volatility)
                else:
                    actual_rate = base_rate
                
                growth = balance * actual_rate
                balances[account_id] = balance + growth
            
            # Income
            income_data = self.calculate_annual_income(year, scenario_name)
            annual_income = income_data["total"]
            
            # Social Security
            ss_income = 0
            if primary_age >= self.scenario.social_security.jimmy_claiming_age:
                ss_income += self.calculate_social_security(year, self.scenario.primary)
            if spouse_age >= self.scenario.social_security.faith_claiming_age:
                ss_income += self.calculate_social_security(year, self.scenario.spouse)
            annual_income += ss_income
            total_ss += ss_income
            
            # Expenses
            expense_data = self.calculate_annual_expenses(year, scenario_name)
            annual_expenses = expense_data["total"]
            
            # Taxes
            taxes = self.calculate_taxes(year, annual_income, scenario_name)
            total_taxes += taxes
            
            # Net cash flow
            net_cash = annual_income - annual_expenses - taxes
            
            # Add excess to savings
            if net_cash > 0:
                for account_id, account in self.accounts.items():
                    if account.account_type == "brokerage" and "joint" in account.name.lower():
                        balances[account_id] = balances.get(account_id, 0) + net_cash
                        break
            
            # Windfalls
            for windfall in self.scenario.windfalls:
                if windfall.date.year == year:
                    if windfall.goes_to_account and windfall.goes_to_account in balances:
                        balances[windfall.goes_to_account] += windfall.amount
            
            # Calculate net worth
            total_assets = sum(b for b in balances.values() if b > 0)
            net_worth = total_assets - sum(abs(b) for b in balances.values() if b < 0)
            
            if net_worth > peak_nw:
                peak_nw = net_worth
            
            if net_worth <= 0 and out_of_savings_year is None:
                out_of_savings_year = year
        
        final_nw = sum(balances.values())
        success = final_nw > self.scenario.legacy_goal and out_of_savings_year is None
        
        return {
            "success": success,
            "final_net_worth": final_nw,
            "peak_net_worth": peak_nw,
            "lifetime_taxes": total_taxes,
            "lifetime_ss": total_ss,
            "out_of_savings_year": out_of_savings_year,
        }
    
    def project_cash_flow(self, scenario_name: str = "mean") -> List[Dict]:
        """Generate year-by-year cash flow projection."""
        projections = []
        
        for year in range(self.start_year, self.scenario.primary.birth_date.year + self.scenario.primary.longevity_age + 1):
            primary_age = year - self.scenario.primary.birth_date.year
            spouse_age = year - self.scenario.spouse.birth_date.year
            
            if primary_age > self.scenario.primary.longevity_age and spouse_age > self.scenario.spouse.longevity_age:
                break
            
            income = self.calculate_annual_income(year, scenario_name)
            expenses = self.calculate_annual_expenses(year, scenario_name)
            taxes = self.calculate_taxes(year, income["total"], scenario_name)
            net_worth = self.calculate_net_worth(year, scenario_name)
            
            projections.append({
                "year": year,
                "primary_age": primary_age,
                "spouse_age": spouse_age,
                "income": income["total"],
                "income_by_source": income["by_source"],
                "expenses": expenses["total"],
                "expenses_by_category": expenses["by_category"],
                "taxes": taxes,
                "net_cash_flow": income["total"] - expenses["total"] - taxes,
                "net_worth": net_worth["net_worth"],
                "total_assets": net_worth["total_assets"],
                "total_liabilities": net_worth["total_liabilities"],
            })
        
        return projections
