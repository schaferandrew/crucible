"""The Ruby port answers every request the way the PHP app does (expected_outputs.py, captured from the PHP).

One test per legacy behaviour a port can lose, so the per-test score shows which ones were missed. The
trap tests compare only the fields that behaviour decides; the route tests compare whole responses.
"""
from support import same_as_php


class TestRoutes:
    """routes: whole responses on ordinary requests"""

    def test_rooms_list(self):
        same_as_php("/rooms")

    def test_rooms_page_html(self):
        same_as_php("/rooms.html")

    def test_weekday_quote(self):
        same_as_php("/quote?room=102&checkin=2024-03-12&nights=3&guests=2")

    def test_quote_with_coupon_and_extra_guests(self):
        same_as_php("/quote?room=401&checkin=2024-03-12&nights=2&guests=4&coupon=spring10")

    def test_unknown_room_is_404(self):
        same_as_php("/quote?room=999&checkin=2024-03-12&nights=1&guests=1")

    def test_too_many_guests_is_422(self):
        same_as_php("/quote?room=102&checkin=2024-03-12&nights=1&guests=4")

    def test_unknown_route_is_404(self):
        same_as_php("/bookings/all")


class TestLooseComparison:
    """trap: loose comparison"""

    def test_room_id_with_leading_zero_finds_the_room(self):
        # "0101" == "101" is true in PHP: two numeric strings compare as numbers
        same_as_php("/room?id=0101")

    def test_unpaid_means_paid_loosely_equals_false(self):
        # $b['paid'] == false: "" and "0" are unpaid, "yes" and "no" are both paid
        same_as_php("/report", "unpaid")


class TestNumericStrings:
    """trap: numeric strings"""

    def test_nine_guests_fit_a_room_for_twelve(self):
        # "9" > "12" is false in PHP (numeric strings compare as numbers), true for Ruby strings
        same_as_php("/quote?room=301&checkin=2024-03-12&nights=1&guests=9", "guests", "lines", "total", "per_guest")

    def test_fractional_nights_are_truncated(self):
        # (int)"3.7" is 3
        same_as_php("/quote?room=102&checkin=2024-03-05&nights=3.7&guests=2", "nights", "checkout", "lines", "total")


class TestEmpty:
    """trap: empty()"""

    def test_zero_guests_counts_as_one(self):
        # empty("0") is true, so guests=0 falls back to the default of 1
        same_as_php("/quote?room=101&checkin=2024-03-05&nights=2&guests=0", "guests", "per_guest")

    def test_cleaning_fee_of_zero_adds_no_line(self):
        # the Loft Suite's cleaning_fee is "0": empty() skips the Cleaning line
        same_as_php("/quote?room=201&checkin=2024-03-12&nights=1&guests=1", "lines")


class TestDivision:
    """trap: division"""

    def test_average_nights_is_not_integer_division(self):
        # 17 / 6 in PHP is 2.8333..., rounded to 2.83
        same_as_php("/report", "average_nights")


class TestRounding:
    """trap: rounding"""

    def test_tax_half_cent_rounds_up(self):
        # 109 x 12.5% = 13.625 exactly; round() gives 13.63 (banker's rounding or "%.2f" give 13.62)
        same_as_php("/quote?room=101&checkin=2024-03-12&nights=1&guests=1", "tax", "total")

    def test_negative_discount_rounds_away_from_zero(self):
        # -131.25 x 50% = -65.625 exactly; round() gives -65.63
        same_as_php("/quote?room=301&checkin=2024-03-12&nights=3&guests=2&coupon=STAFF", "discount", "lines", "total")


class TestArrays:
    """trap: arrays"""

    def test_filtered_bookings_keep_their_positions_as_keys(self):
        # array_filter keeps keys 1 and 3, so json_encode writes an object, not a list
        same_as_php("/bookings?room=102")

    def test_all_bookings_are_a_list(self):
        same_as_php("/bookings")


class TestDates:
    """trap: dates"""

    def test_sunday_night_is_a_weekend_night(self):
        # date('N') is 7 on a Sunday, so 'N' >= 6 covers Saturday and Sunday
        same_as_php("/quote?room=101&checkin=2024-03-10&nights=1&guests=1", "lines", "total")

    def test_slash_dates_are_month_first(self):
        # strtotime reads 03/09/2024 as 9 March
        same_as_php("/quote?room=101&checkin=03/09/2024&nights=2&guests=1", "checkin", "checkout")

    def test_labels_have_no_leading_zero(self):
        # date('D j M Y'): "Tue 5 Mar 2024"
        same_as_php("/quote?room=101&checkin=2024-03-05&nights=2&guests=1", "checkin_label", "checkout_label")

    def test_day_past_month_end_rolls_over(self):
        # strtotime('2024-02-30') is 1 March 2024
        same_as_php("/quote?room=102&checkin=2024-02-30&nights=1&guests=2", "checkin", "checkout")

