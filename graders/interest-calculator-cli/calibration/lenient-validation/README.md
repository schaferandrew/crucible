# Compound-interest calculator

A small command-line calculator for compound interest, with optional recurring contributions.
Python 3, standard library only.

## Usage

Run it from this folder:

```bash
python -m interest --principal 10000 --rate 5 --years 10 --compound monthly
```

```
Principal:           $10,000.00
Total contributions: $0.00
Interest earned:     $6,470.09
Final balance:       $16,470.09
```

Add `--json` for machine-readable output (amounts rounded to cents):

```bash
python -m interest --principal 1000 --rate 6 --years 5 --compound monthly \
    --contribution 200 --contribution-frequency monthly --json
```

### Flags

| Flag | Meaning |
|---|---|
| `--principal` | starting balance, 0 or more |
| `--rate` | annual rate in percent (`5` is 5%) |
| `--years` or `--months` | time, a positive whole number; give exactly one |
| `--compound` | `annually`, `quarterly`, `monthly` or `daily` (1, 4, 12 and 365 times a year) |
| `--contribution`, `--contribution-frequency` | an amount added at the end of every `monthly` or `annually` period; give both or neither |
| `--json` | print `{"principal", "total_contributions", "interest_earned", "final_balance"}` |

Interest is credited at the end of each compounding period. A contribution is added at the end of its
period, after any interest credited at that moment.

Invalid input (negative numbers, both `--years` and `--months`, a contribution without a frequency, ...)
prints a message on stderr and exits with a non-zero status.

## Tests

```bash
python -m unittest discover -s tests
```
