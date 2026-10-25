"""Realize aggregate strategy changes against individual expense allowances."""


def realize_spending(planned, allowances, target):
    """Allocate cuts proportionally to remaining allowances, by expense ID.

    Required expenses never participate. Increases use a separate discretionary
    line, preserving the tax classification of the original planned categories.
    """
    total = sum(planned.values())
    budget = sum(allowances.values())
    cut = min(max(0.0, total - target), budget)
    actual = dict(planned)
    if budget > 0:
        for key, allowance in allowances.items():
            actual[key] = max(0.0, actual.get(key, 0.0) - cut * allowance / budget)
    if target > total:
        actual["__strategy_extra"] = target - total
    return actual
