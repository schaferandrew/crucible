<?php
/**
 * Quote calculator: nightly rate, weekend surcharge, extra guests, cleaning, coupon, lodging tax.
 * Every money figure is rounded to cents with round().
 */
class Pricing
{
    const TAX_RATE = 0.125;          // county lodging tax, 12.5%
    const WEEKEND_SURCHARGE = 0.25;  // +25% on weekend nights
    const BASE_GUESTS = 2;           // the rate covers two guests

    public static function quote(array $room, $checkin, $nights, $guests, $coupon)
    {
        $base = 0;
        $surcharge = 0;
        $weekendNights = 0;
        for ($i = 0; $i < $nights; $i++) {
            $night = Dates::addDays($checkin, $i);
            $base += $room['rate'];
            if (Dates::isWeekend($night)) {
                $surcharge += $room['rate'] * self::WEEKEND_SURCHARGE;
                $weekendNights++;
            }
        }

        $lines = [];
        $lines[] = ['label' => 'Room (' . self::nights($nights) . ')', 'amount' => round($base, 2)];
        if ($weekendNights > 0) {
            $lines[] = ['label' => 'Weekend surcharge (' . self::nights($weekendNights) . ')',
                        'amount' => round($surcharge, 2)];
        }
        $extra = $guests - self::BASE_GUESTS;
        if ($extra > 0) {
            $lines[] = ['label' => 'Extra guests (' . $extra . ' x ' . self::nights($nights) . ')',
                        'amount' => round($extra * $room['extra_guest_fee'] * $nights, 2)];
        }
        if (!empty($room['cleaning_fee'])) {
            $lines[] = ['label' => 'Cleaning', 'amount' => round($room['cleaning_fee'], 2)];
        }

        $subtotal = array_sum(array_column($lines, 'amount'));

        $discount = 0;
        $code = null;
        if ($coupon !== null && $nights >= $coupon['min_nights']) {
            $discount = round(-$subtotal * $coupon['percent'] / 100, 2);
            $code = $coupon['code'];
            $lines[] = ['label' => 'Coupon ' . $code . ' (' . $coupon['percent'] . '%)', 'amount' => $discount];
        }

        $taxable = $subtotal + $discount;
        $tax = round($taxable * self::TAX_RATE, 2);
        $total = round($taxable + $tax, 2);

        return [
            'nights' => $nights,
            'guests' => (int)$guests,
            'lines' => $lines,
            'coupon' => $code,
            'subtotal' => round($subtotal, 2),
            'discount' => $discount,
            'tax' => $tax,
            'total' => $total,
            'per_guest' => round($total / $guests, 2),
        ];
    }

    private static function nights($n)
    {
        return $n . ' night' . ($n == 1 ? '' : 's');
    }
}
