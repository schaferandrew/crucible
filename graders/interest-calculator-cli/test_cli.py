"""Output shape and input validation, through the command line."""
import json
import re

import pytest

from support import assert_close, calc, flags, run


class TestSummaryOutput:
    """output: summary"""

    def test_default_output_shows_all_four_figures(self):
        result = run(*flags(principal=1000, rate=6, years=5, compound="monthly", contribution=200, frequency="monthly"))
        assert result.returncode == 0, result.stderr[-200:]
        text = result.stdout.lower().replace(",", "").replace("$", "")
        for label in ("principal", "contribution", "interest", "balance"):
            assert label in text, f"no '{label}' in the summary"
        for figure in ("1000.00", "12000.00", "2302.86", "15302.86"):
            assert figure in text, f"{figure} is missing from the summary"

    def test_default_output_is_not_json(self):
        result = run(*flags(years=1))
        assert result.returncode == 0
        with pytest.raises(ValueError):
            json.loads(result.stdout)


class TestJsonOutput:
    """output: json"""

    def test_exactly_the_four_keys(self):
        result = run(*flags(principal=10000, rate=5, years=10), "--json")
        assert result.returncode == 0, result.stderr[-200:]
        data = json.loads(result.stdout)  # stdout is the JSON and nothing else
        assert set(data) == {"principal", "total_contributions", "interest_earned", "final_balance"}
        assert all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in data.values())

    def test_amounts_are_rounded_to_cents(self):
        data = calc(principal=3333.33, rate=4.17, years=7, compound="daily", contribution=77.77, frequency="monthly")
        for key, value in data.items():
            assert round(value, 2) == value, f"{key} = {value} is not rounded to cents"
        assert_close(data["principal"], 3333.33, "principal")
        assert_close(data["total_contributions"], 77.77 * 84, "total_contributions")

    def test_figures_add_up(self):
        data = calc(principal=1500, rate=3.3, years=4, compound="quarterly", contribution=120, frequency="annually")
        assert_close(data["principal"] + data["total_contributions"] + data["interest_earned"], data["final_balance"],
                     "principal + contributions + interest")


GOOD = flags(principal=1000, rate=5, years=2, compound="monthly")
GOOD_CONTRIB = flags(principal=1000, rate=5, years=2, compound="monthly", contribution=50, frequency="monthly")


def rejected(good, bad):
    """The valid command works, and the changed one exits non-zero with a message on stderr (no traceback)."""
    ok = run(*good)
    assert ok.returncode == 0, f"the valid command should work: exit {ok.returncode}: {ok.stderr.strip()[-200:]}"
    result = run(*bad)
    assert result.returncode != 0, "should exit non-zero"
    assert result.stderr.strip(), "should explain the problem on stderr"
    assert "Traceback" not in result.stderr, "should print a message, not a traceback"


class TestValidation:
    """validation: invalid input is rejected"""

    def test_negative_principal(self):
        rejected(GOOD, flags(principal=-1000, years=2))

    def test_negative_rate(self):
        rejected(GOOD, flags(rate=-5, years=2))

    def test_negative_time(self):
        rejected(GOOD, flags(years=-2))

    def test_negative_contribution(self):
        rejected(GOOD_CONTRIB, flags(years=2, contribution=-50, frequency="monthly"))

    def test_text_instead_of_a_number(self):
        rejected(GOOD, flags(principal="lots", years=2))

    def test_both_years_and_months(self):
        rejected(GOOD, flags(years=2, months=6))

    def test_neither_years_nor_months(self):
        rejected(GOOD, flags())

    def test_contribution_without_frequency(self):
        rejected(GOOD_CONTRIB, flags(years=2, contribution=50))

    def test_frequency_without_contribution(self):
        rejected(GOOD_CONTRIB, flags(years=2, frequency="monthly"))

    def test_unknown_compounding(self):
        rejected(GOOD, flags(years=2, compound="weekly"))

    def test_unknown_contribution_frequency(self):
        rejected(GOOD_CONTRIB, flags(years=2, contribution=50, frequency="weekly"))

    def test_missing_principal(self):
        rejected(GOOD, ["--rate", "5", "--years", "2", "--compound", "monthly"])
