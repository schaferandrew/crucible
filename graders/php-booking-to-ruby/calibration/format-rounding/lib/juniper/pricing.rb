# frozen_string_literal: true

require_relative "php"
require_relative "dates"

module Juniper
  # Quote calculator: nightly rate, weekend surcharge, extra guests, cleaning, coupon, lodging tax.
  # Every money figure is rounded to cents, half away from zero (PHP's round()).
  module Pricing
    TAX_RATE = 0.125          # county lodging tax, 12.5%
    WEEKEND_SURCHARGE = 0.25  # +25% on weekend nights
    BASE_GUESTS = 2           # the rate covers two guests

    module_function

    # guests is a number or a numeric string, as the router passes it on
    def quote(room, checkin, nights, guests, coupon)
      rate = PHP.num(room["rate"])
      guest_count = PHP.num(guests)
      base = 0
      surcharge = 0
      weekend_nights = 0
      nights.times do |i|
        night = Dates.add_days(checkin, i)
        base += rate
        next unless Dates.weekend?(night)
        surcharge += rate * WEEKEND_SURCHARGE
        weekend_nights += 1
      end

      lines = [{ "label" => "Room (#{nights_label(nights)})", "amount" => PHP.round(base, 2) }]
      if weekend_nights > 0
        lines << { "label" => "Weekend surcharge (#{nights_label(weekend_nights)})",
                   "amount" => PHP.round(surcharge, 2) }
      end
      extra = guest_count - BASE_GUESTS
      if extra > 0
        lines << { "label" => "Extra guests (#{extra} x #{nights_label(nights)})",
                   "amount" => PHP.round(extra * PHP.num(room["extra_guest_fee"]) * nights, 2) }
      end
      unless PHP.empty?(room["cleaning_fee"])
        lines << { "label" => "Cleaning", "amount" => PHP.round(room["cleaning_fee"], 2) }
      end

      # Left to right like array_sum (Array#sum compensates for float error, which PHP doesn't)
      subtotal = lines.inject(0) { |sum, line| sum + line["amount"] }

      discount = 0
      code = nil
      if coupon && PHP.cmp(nights, coupon["min_nights"]) >= 0
        # Same operation order as the legacy code, so the floats come out bit-for-bit the same
        discount = PHP.round(-subtotal * PHP.num(coupon["percent"]) / 100.0, 2)
        code = coupon["code"]
        lines << { "label" => "Coupon #{code} (#{coupon['percent']}%)", "amount" => discount }
      end

      taxable = subtotal + discount
      tax = PHP.round(taxable * TAX_RATE, 2)
      total = PHP.round(taxable + tax, 2)

      {
        "nights" => nights,
        "guests" => PHP.int(guests),
        "lines" => lines,
        "coupon" => code,
        "subtotal" => PHP.round(subtotal, 2),
        "discount" => discount,
        "tax" => tax,
        "total" => total,
        "per_guest" => PHP.round(total / guest_count.to_f, 2)
      }
    end

    def nights_label(n)
      "#{n} night#{n == 1 ? '' : 's'}"
    end
  end
end
