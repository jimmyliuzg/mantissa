"""Conservative spending access. Principal/cohorts use nominal dollars.

SEPP, separation-from-service and other exceptions are not inferred.
"""
from calendar import monthrange
from copy import deepcopy
from datetime import date


def reaches_age(birth, age, on_date):
    months = round(age * 12)
    year = birth.year + (birth.month - 1 + months) // 12
    month = (birth.month - 1 + months) % 12 + 1
    return on_date >= date(year, month, min(birth.day, monthrange(year, month)[1]))


class AccessLedger:
    def __init__(self, accounts, start_year):
        self.contributions, self.conversions, self.first_year = {}, {}, {}
        for account in accounts.values():
            owner = (account.owner or "primary").lower()
            if account.tax_treatment != "roth" or account.account_type != "roth_ira":
                continue
            first = account.roth_first_contribution_year or min(
                [start_year] + [c["year"] for c in account.roth_conversion_basis])
            self.first_year[owner] = min(self.first_year.get(owner, first), first)
            if account.account_type == "roth_ira":
                self.contributions[owner] = self.contributions.get(owner, 0.0) + account.roth_contribution_basis
                self.conversions.setdefault(owner, []).extend(dict(c) for c in account.roth_conversion_basis)
        for cohorts in self.conversions.values():
            cohorts.sort(key=lambda c: c["year"])

    def snapshot(self):
        return deepcopy((self.contributions, self.conversions, self.first_year))

    def restore(self, snapshot):
        self.contributions, self.conversions, self.first_year = deepcopy(snapshot)

    def add_contribution(self, owner, amount, year):
        self.contributions[owner] = self.contributions.get(owner, 0.0) + amount
        self.first_year[owner] = min(self.first_year.get(owner, year), year)

    def add_conversion(self, owner, amount, year):
        self.conversions.setdefault(owner, []).append(dict(year=year, amount=amount))
        self.conversions[owner].sort(key=lambda c: c["year"])
        self.first_year[owner] = min(self.first_year.get(owner, year), year)

    def qualified(self, owner, year, old_enough):
        return old_enough and year >= self.first_year.get(owner, year) + 5

    def available_principal(self, owner, year, old_enough):
        total = self.contributions.get(owner, 0.0)
        for cohort in self.conversions.get(owner, []):
            if not old_enough and year < cohort["year"] + 5:
                break
            total += cohort["amount"]
        return total

    def consume(self, owner, amount):
        regular = min(amount, self.contributions.get(owner, 0.0))
        self.contributions[owner] = self.contributions.get(owner, 0.0) - regular
        remaining = amount - regular
        for cohort in self.conversions.get(owner, []):
            used = min(remaining, cohort["amount"])
            cohort["amount"] -= used
            remaining -= used

    def schedule(self):
        return [dict(owner=owner, conversion_year=c["year"],
                     penalty_free_year=c["year"] + 5, remaining_nominal=c["amount"])
                for owner, cohorts in self.conversions.items() for c in cohorts if c["amount"] > 0]
