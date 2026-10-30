import json
import subprocess
import sys
import unittest
from decimal import Decimal
from pathlib import Path

from interest.calc import calculate

ROOT = Path(__file__).resolve().parent.parent


def cli(*args):
    return subprocess.run([sys.executable, "-m", "interest", *args], cwd=ROOT, capture_output=True, text=True)


class Math(unittest.TestCase):
    def test_monthly_compounding_known_value(self):
        self.assertEqual(calculate(10000, 5, 120, "monthly")["final_balance"], Decimal("16470.09"))

    def test_annual_compounding(self):
        self.assertEqual(calculate(1000, 7, 36, "annually")["final_balance"], Decimal("1225.04"))

    def test_zero_interest(self):
        result = calculate(2500, 0, 60, "monthly", 50, "monthly")
        self.assertEqual(result["final_balance"], Decimal("5500.00"))
        self.assertEqual(result["interest_earned"], Decimal("0.00"))

    def test_months_match_years(self):
        by_years = cli("--principal", "1000", "--rate", "6", "--years", "2", "--compound", "monthly", "--json")
        by_months = cli("--principal", "1000", "--rate", "6", "--months", "24", "--compound", "monthly", "--json")
        self.assertEqual(by_years.stdout, by_months.stdout)

    def test_daily_compounding(self):
        self.assertEqual(calculate(10000, 5, 12, "daily")["final_balance"], Decimal("10512.67"))

    def test_monthly_contributions(self):
        result = calculate(1000, 6, 60, "monthly", 200, "monthly")
        self.assertEqual(result["final_balance"], Decimal("15302.86"))
        self.assertEqual(result["total_contributions"], Decimal("12000.00"))

    def test_annual_contributions(self):
        self.assertEqual(calculate(5000, 4, 120, "annually", 1200, "annually")["final_balance"], Decimal("21808.55"))


class Cli(unittest.TestCase):
    def test_json_output(self):
        result = cli("--principal", "10000", "--rate", "5", "--years", "10", "--compound", "monthly", "--json")
        self.assertEqual(result.returncode, 0)
        data = json.loads(result.stdout)
        self.assertEqual(set(data), {"principal", "total_contributions", "interest_earned", "final_balance"})
        self.assertEqual(data["final_balance"], 16470.09)

    def test_readable_output(self):
        result = cli("--principal", "10000", "--rate", "5", "--years", "10", "--compound", "monthly")
        self.assertEqual(result.returncode, 0)
        self.assertIn("$16,470.09", result.stdout)

    def test_years_and_months_together_are_rejected(self):
        result = cli("--principal", "1", "--rate", "5", "--years", "1", "--months", "6", "--compound", "monthly")
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(result.stderr.strip())

    def test_negative_principal_is_rejected(self):
        result = cli("--principal", "-5", "--rate", "5", "--years", "1", "--compound", "monthly")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("--principal", result.stderr)

    def test_contribution_needs_a_frequency(self):
        result = cli("--principal", "1", "--rate", "5", "--years", "1", "--compound", "monthly", "--contribution", "10")
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("Traceback", result.stderr)


if __name__ == "__main__":
    unittest.main()
