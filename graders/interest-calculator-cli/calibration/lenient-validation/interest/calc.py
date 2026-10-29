"""The arithmetic: interest is credited at the end of each compounding period, a contribution is
added at the end of its period, after any interest credited at that same moment."""
from decimal import ROUND_HALF_UP, Decimal, getcontext
from fractions import Fraction

getcontext().prec = 50

PERIODS_PER_YEAR = {"annually": 1, "quarterly": 4, "monthly": 12, "daily": 365}
CONTRIBUTIONS_PER_YEAR = {"monthly": 12, "annually": 1}
CENT = Decimal("0.01")


def cents(amount: Decimal) -> Decimal:
    return amount.quantize(CENT, rounding=ROUND_HALF_UP)


def calculate(principal, rate_percent, months, compound, contribution=None, contribution_frequency=None):
    """Returns principal, total_contributions, interest_earned and final_balance, each rounded to cents."""
    principal, rate_percent = Decimal(str(principal)), Decimal(str(rate_percent))
    per_year = PERIODS_PER_YEAR[compound]
    period_rate = rate_percent / 100 / per_year
    horizon = Fraction(months, 12)

    events = [(Fraction(k, per_year), 0) for k in range(1, int(horizon * per_year) + 1)]
    if contribution is not None:
        every = Fraction(1, CONTRIBUTIONS_PER_YEAR[contribution_frequency])
        events += [(every * k, 1) for k in range(1, int(horizon / every) + 1)]
    events.sort()  # at the same moment, interest (0) comes before the contribution (1)

    balance, contributed = principal, Decimal(0)
    for _, kind in events:
        if kind == 0:
            balance *= 1 + period_rate
        else:
            balance += Decimal(str(contribution))
            contributed += Decimal(str(contribution))

    final = cents(balance)
    return {
        "principal": cents(principal),
        "total_contributions": cents(contributed),
        "interest_earned": cents(balance - principal - contributed),
        "final_balance": final,
    }
