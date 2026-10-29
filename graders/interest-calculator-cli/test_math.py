"""Known-value cases, computed independently: interest is credited at the end of each compounding
period (1, 4, 12 or 365 a year) and a contribution is added at the end of its period."""
import pytest

from support import assert_close, calc


class TestCompounding:
    """math: compounding"""

    def test_monthly_ten_years(self):
        assert_close(calc(principal=10000, rate=5, years=10, compound="monthly")["final_balance"], 16470.09)

    def test_annual_three_years(self):
        assert_close(calc(principal=1000, rate=7, years=3, compound="annually")["final_balance"], 1225.04)

    def test_quarterly_five_years(self):
        assert_close(calc(principal=5000, rate=6, years=5, compound="quarterly")["final_balance"], 6734.28)

    def test_daily_one_year(self):
        assert_close(calc(principal=10000, rate=5, years=1, compound="daily")["final_balance"], 10512.67)

    def test_daily_ten_years(self):
        assert_close(calc(principal=2500, rate=3.5, years=10, compound="daily")["final_balance"], 3547.61)

    def test_monthly_eighteen_months(self):
        assert_close(calc(principal=5000, rate=4.8, months=18, compound="monthly")["final_balance"], 5372.51)

    def test_quarterly_eighteen_months(self):
        assert_close(calc(principal=8000, rate=6, months=18, compound="quarterly")["final_balance"], 8747.55)

    def test_interest_earned_is_the_difference(self):
        r = calc(principal=10000, rate=5, years=10, compound="monthly")
        assert_close(r["interest_earned"], 6470.09, "interest_earned")
        assert_close(r["principal"], 10000, "principal")
        assert_close(r["total_contributions"], 0, "total_contributions")


class TestZeroRate:
    """math: zero rate"""

    def test_balance_stays_the_principal(self):
        r = calc(principal=2500, rate=0, years=5, compound="monthly")
        assert_close(r["final_balance"], 2500)
        assert_close(r["interest_earned"], 0, "interest_earned")

    def test_monthly_contributions_only_add_up(self):
        r = calc(principal=1000, rate=0, years=2, compound="monthly", contribution=50, frequency="monthly")
        assert_close(r["final_balance"], 2200)
        assert_close(r["total_contributions"], 1200, "total_contributions")
        assert_close(r["interest_earned"], 0, "interest_earned")

    def test_annual_contributions_only_add_up(self):
        r = calc(principal=0, rate=0, years=4, compound="annually", contribution=300, frequency="annually")
        assert_close(r["final_balance"], 1200)
        assert_close(r["total_contributions"], 1200, "total_contributions")


class TestYearsAndMonths:
    """math: years and months"""

    def test_twenty_four_months_is_two_years(self):
        by_months = calc(principal=1000, rate=6, months=24, compound="monthly")
        assert_close(by_months["final_balance"], 1127.16)
        assert by_months == calc(principal=1000, rate=6, years=2, compound="monthly")

    def test_twelve_months_is_one_year(self):
        assert calc(principal=4000, rate=3, months=12, compound="quarterly") == \
            calc(principal=4000, rate=3, years=1, compound="quarterly")

    def test_sixty_months_with_contributions_is_five_years(self):
        by_months = calc(principal=1000, rate=6, months=60, compound="monthly", contribution=200, frequency="monthly")
        assert_close(by_months["final_balance"], 15302.86)
        assert by_months == calc(principal=1000, rate=6, years=5, compound="monthly", contribution=200, frequency="monthly")


class TestContributions:
    """math: contributions"""

    def test_monthly_contributions_monthly_compounding(self):
        r = calc(principal=1000, rate=6, years=5, compound="monthly", contribution=200, frequency="monthly")
        assert_close(r["final_balance"], 15302.86)
        assert_close(r["total_contributions"], 12000, "total_contributions")
        assert_close(r["interest_earned"], 2302.86, "interest_earned")

    def test_annual_contributions_annual_compounding(self):
        r = calc(principal=5000, rate=4, years=10, compound="annually", contribution=1200, frequency="annually")
        assert_close(r["final_balance"], 21808.55)
        assert_close(r["total_contributions"], 12000, "total_contributions")

    def test_annual_contributions_monthly_compounding(self):
        r = calc(principal=2000, rate=6, years=5, compound="monthly", contribution=1000, frequency="annually")
        assert_close(r["final_balance"], 8353.71)
        assert_close(r["total_contributions"], 5000, "total_contributions")

    def test_annual_contributions_daily_compounding(self):
        r = calc(principal=1000, rate=5, years=2, compound="daily", contribution=500, frequency="annually")
        assert_close(r["final_balance"], 2130.80)

    def test_principal_zero_with_monthly_contributions(self):
        r = calc(principal=0, rate=12, years=2, compound="monthly", contribution=100, frequency="monthly")
        assert_close(r["final_balance"], 2697.35)
        assert_close(r["total_contributions"], 2400, "total_contributions")
