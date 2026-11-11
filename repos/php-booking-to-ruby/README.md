# Juniper Inn booking desk

The front desk's quoting tool, written in PHP in 2014 and patched since. It has no database: rooms
live in `data/rooms.json`, bookings and coupons in CSV files under `data/`.

## Running it

It runs from the command line with one argument, the request:

```bash
php app.php '/rooms'
php app.php '/rooms.html'
php app.php '/room?id=102'
php app.php '/quote?room=101&checkin=2024-03-19&nights=2&guests=1'
php app.php '/quote?room=401&checkin=2024-03-12&nights=2&guests=4&coupon=spring10'
php app.php '/bookings?room=101'
php app.php '/report'
```

It prints the response body (JSON, or HTML for `/rooms.html`) and exits 0 for a 2xx response,
1 for anything else (errors come back as `{"error": "..."}`).

## Pricing

- The nightly rate covers two guests; each extra guest pays the room's extra-guest fee per night.
- Saturday and Sunday nights cost 25% more.
- A room's cleaning fee is charged once per stay.
- Coupons (`data/coupons.csv`) take a percentage off the subtotal once the stay is long enough.
- County lodging tax is 12.5% of the discounted subtotal.
- Every money figure is rounded to cents.

Check-in dates are accepted as `2024-03-19` or `03/19/2024`. All dates are UTC.

## Tests

```bash
php tests/run_tests.php
```

Runs every request in `tests/fixtures/cases.json` and compares the status and body.

## Layout

- `app.php`: entry point
- `src/Router.php`: routes
- `src/DataStore.php`: reads the files in `data/`
- `src/Pricing.php`: the quote calculator
- `src/Dates.php`: date parsing and formatting
- `src/Views.php`: the HTML rooms page
