import argparse
import json
import sys
from decimal import Decimal, InvalidOperation

from interest.calc import CONTRIBUTIONS_PER_YEAR, PERIODS_PER_YEAR, calculate


class UsageError(Exception):
    pass


def _number(text, flag, minimum=0, strict=False):
    return Decimal(text)  # no checks: bad text is an uncaught exception


def _whole(text, flag):
    return int(text)


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise UsageError(message)


def build_parser() -> argparse.ArgumentParser:
    parser = Parser(prog="python -m interest", description="Compound-interest calculator.")
    parser.add_argument("--principal", required=True, help="starting balance, 0 or more")
    parser.add_argument("--rate", required=True, help="annual interest rate in percent (5 means 5%%)")
    parser.add_argument("--years", help="time in whole years (or use --months)")
    parser.add_argument("--months", help="time in whole months (or use --years)")
    parser.add_argument("--compound", required=True, choices=list(PERIODS_PER_YEAR), help="how often interest compounds")
    parser.add_argument("--contribution", help="amount added at the end of each contribution period")
    parser.add_argument("--contribution-frequency", choices=list(CONTRIBUTIONS_PER_YEAR), help="monthly or annually")
    parser.add_argument("--json", action="store_true", help="print the result as JSON")
    return parser


def parse(argv):
    args = build_parser().parse_args(argv)
    months = _whole(args.years, "--years") * 12 if args.years is not None else _whole(args.months, "--months")
    contribution = _number(args.contribution, "--contribution", strict=True) if args.contribution is not None else None
    return {
        "principal": _number(args.principal, "--principal"),
        "rate_percent": _number(args.rate, "--rate"),
        "months": months,
        "compound": args.compound,
        "contribution": contribution,
        "contribution_frequency": args.contribution_frequency,
    }, args.json


def money(value: Decimal) -> str:
    return f"${value:,.2f}"


def main(argv=None) -> int:
    try:
        params, as_json = parse(sys.argv[1:] if argv is None else argv)
    except UsageError as exc:  # only argparse's own errors reach here
        print(f"error: {exc}", file=sys.stderr)
        return 2
    result = calculate(**params)
    if as_json:
        print(json.dumps({key: float(value) for key, value in result.items()}))
    else:
        print(f"Principal:           {money(result['principal'])}")
        print(f"Total contributions: {money(result['total_contributions'])}")
        print(f"Interest earned:     {money(result['interest_earned'])}")
        print(f"Final balance:       {money(result['final_balance'])}")
    return 0
