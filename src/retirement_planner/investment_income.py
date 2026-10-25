"""Small annual distribution calculation; returns already include these yields."""


def distribute(account, opening_balance, closing_balance, basis, opening_price_factor=1.0):
    """Return (balance, basis, ordinary, qualified, cash, capital_gains) in active dollars.

    Yields are nominal rates on opening value. A severe loss caps cash
    distributions at remaining assets. Retirement accounts compound internally.
    Reinvestment adds basis without adding cash income or extra total return.
    """
    if account.tax_treatment != "taxable" or account.account_type in {"real_estate", "vehicle"}:
        return closing_balance, basis, 0.0, 0.0, 0.0, 0.0
    interest = opening_balance / opening_price_factor * account.interest_yield
    dividends = opening_balance / opening_price_factor * account.dividend_yield
    capital_gains = opening_balance / opening_price_factor * account.capital_gain_yield
    total = interest + dividends + capital_gains
    if total <= 0:
        return closing_balance, basis, 0.0, 0.0, 0.0, 0.0
    scale = min(1.0, max(0.0, closing_balance) / total)
    interest *= scale
    dividends *= scale
    capital_gains *= scale
    total *= scale
    qualified = dividends * account.qualified_dividend_share
    if account.reinvest_distributions:
        return closing_balance, basis + total, interest + dividends - qualified, qualified, 0.0, capital_gains
    return closing_balance - total, basis, interest + dividends - qualified, qualified, total, capital_gains
