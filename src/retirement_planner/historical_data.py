"""
Historical market return data for Monte Carlo simulations.

Uses actual S&P 500 real (inflation-adjusted) annual returns from 1926-2023.
Source: Ibbotson Associates / Morningstar SBBI data.

Instead of generating random gaussian returns, simulations can replay
historical return sequences. This captures sequence-of-returns risk
(e.g., a bear market early in retirement is devastating) much better
than independent random draws.
"""
from typing import Dict, Optional

# S&P 500 real (inflation-adjusted) annual returns, 1926-2023
HISTORICAL_SNP500_REAL_RETURNS: Dict[int, float] = {
    1926: 0.058, 1927: 0.286, 1928: 0.380, 1929: -0.312, 1930: -0.257,
    1931: -0.439, 1932: -0.098, 1933: 0.540, 1934: -0.014, 1935: 0.472,
    1936: 0.328, 1937: -0.358, 1938: 0.299, 1939: -0.011, 1940: -0.100,
    1941: -0.116, 1942: 0.203, 1943: 0.259, 1944: 0.197, 1945: 0.364,
    1946: -0.098, 1947: 0.057, 1948: 0.051, 1949: 0.181, 1950: 0.307,
    1951: 0.240, 1952: 0.188, 1953: -0.013, 1954: 0.525, 1955: 0.316,
    1956: 0.066, 1957: -0.108, 1958: 0.434, 1959: 0.120, 1960: 0.005,
    1961: 0.269, 1962: -0.088, 1963: 0.228, 1964: 0.164, 1965: 0.125,
    1966: -0.101, 1967: 0.240, 1968: 0.111, 1969: -0.084, 1970: 0.040,
    1971: 0.143, 1972: 0.190, 1973: -0.147, 1974: -0.265, 1975: 0.372,
    1976: 0.238, 1977: -0.072, 1978: 0.066, 1979: 0.184, 1980: 0.324,
    1981: -0.049, 1982: 0.214, 1983: 0.225, 1984: 0.021, 1985: 0.322,
    1986: 0.185, 1987: 0.020, 1988: 0.265, 1989: 0.197, 1990: -0.052,
    1991: 0.305, 1992: 0.076, 1993: 0.101, 1994: -0.004, 1995: 0.376,
    1996: 0.230, 1997: 0.334, 1998: 0.286, 1999: 0.210, 2000: -0.091,
    2001: -0.119, 2002: -0.221, 2003: 0.287, 2004: 0.109, 2005: 0.049,
    2006: 0.158, 2007: 0.055, 2008: -0.370, 2009: 0.265, 2010: 0.151,
    2011: 0.021, 2012: 0.160, 2013: 0.324, 2014: 0.137, 2015: 0.014,
    2016: 0.120, 2017: 0.218, 2018: -0.044, 2019: 0.315, 2020: 0.184,
    2021: 0.287, 2022: -0.181, 2023: 0.263,
}

# SYNTHETIC bond returns — NOT real historical data.
# Approximated from decade-level average real yields for intermediate-term
# government bonds. Equity series (HISTORICAL_SNP500_VALUES) are real
# annual observations; bond series is a simplified model.
# TODO: replace with annual nominal total-return dataset from FRED or similar.
HISTORICAL_BOND_REAL_RETURNS: Dict[int, float] = {}
_decade_rates = {
    (1926, 1929): 0.04,
    (1930, 1939): 0.05,
    (1940, 1949): 0.01,
    (1950, 1959): 0.01,
    (1960, 1969): 0.015,
    (1970, 1979): -0.02,
    (1980, 1989): 0.05,
    (1990, 1999): 0.035,
    (2000, 2009): 0.03,
    (2010, 2019): 0.01,
    (2020, 2024): 0.015,
}
for year in range(1926, 2024):
    rate = 0.02  # fallback
    for (start, end), r in _decade_rates.items():
        if start <= year <= end:
            rate = r
            break
    HISTORICAL_BOND_REAL_RETURNS[year] = rate

# Ordered lists for sequential access (index = offset from first year)
HISTORICAL_YEARS = sorted(HISTORICAL_SNP500_REAL_RETURNS.keys())
_HISTORICAL_SNP500_VALUES = [HISTORICAL_SNP500_REAL_RETURNS[y] for y in HISTORICAL_YEARS]
_HISTORICAL_BOND_VALUES = [HISTORICAL_BOND_REAL_RETURNS[y] for y in HISTORICAL_YEARS]


def get_historical_return(year: int, asset_class: str = "equity") -> float:
    """Return the historical real annual return for a given year and asset class.

    Args:
        calendar year (e.g. 1926-2023)
        asset_class: "equity" for S&P 500, "bond" for intermediate-term bonds

    Returns:
        Real (inflation-adjusted) annual return as a decimal.
        If the year is outside the available range, wraps around cyclically.
    """
    if asset_class == "bond":
        years = HISTORICAL_YEARS
        values = _HISTORICAL_BOND_VALUES
    else:
        years = HISTORICAL_YEARS
        values = _HISTORICAL_SNP500_VALUES

    first_year = years[0]
    last_year = years[-1]
    span = len(years)

    # Wrap around cyclically if year is outside range
    idx = (year - first_year) % span
    return values[idx]


def get_historical_sequence(num_years: int, start_year_index: Optional[int] = None,
                            asset_class: str = "equity") -> list:
    """Return a sequence of historical returns for *num_years* starting at
    *start_year_index* into the historical data.

    Args:
        num_years: How many years of returns needed
        start_year_index: Offset into HISTORICAL_YEARS (0-based).
            If None, a random starting index is chosen.
        asset_class: "equity" or "bond"

    Returns:
        List of real annual returns, wrapping cyclically if num_years > data length.
    """  # noqa: E501
    if asset_class == "bond":
        values = _HISTORICAL_BOND_VALUES
    else:
        values = _HISTORICAL_SNP500_VALUES

    span = len(values)

    if start_year_index is None:
        import random as _random
        start_year_index = _random.randint(0, span - 1)

    return [values[(start_year_index + i) % span] for i in range(num_years)]
