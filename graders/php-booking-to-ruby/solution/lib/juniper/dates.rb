# frozen_string_literal: true

require "date"
require_relative "php"

module Juniper
  # Date helpers. Check-in dates come as 2024-03-09 or 03/09/2024 (month/day/year).
  module Dates
    ISO = %r{\A(\d{4})-(0[1-9]|1[0-2])-([0-2]\d|3[01])\z}.freeze
    US = %r{\A(0?[1-9]|1[0-2])/(0?[1-9]|[12]\d|3[01])/(\d{4})\z}.freeze

    module_function

    # A Date, or nil. Like PHP's strtotime, a day past the end of the month rolls into the next
    # month (2024-02-30 is 1 March) and day 00 is the last day of the month before.
    def parse(value)
      return nil if PHP.empty?(value)
      value = value.to_s.strip
      if (m = ISO.match(value))
        year, month, day = m[1].to_i, m[2].to_i, m[3].to_i
      elsif (m = US.match(value))
        month, day, year = m[1].to_i, m[2].to_i, m[3].to_i
      else
        return nil
      end
      Date.new(year, month, 1) + (day - 1)
    end

    def add_days(date, days)
      date + days
    end

    def iso(date)
      date.strftime("%Y-%m-%d")
    end

    # PHP's 'D j M Y': "Sun 3 Mar 2024", no leading zero on the day
    def label(date)
      date.strftime("%a %-d %b %Y")
    end

    # Saturday and Sunday nights (ISO day 6 and 7) are weekend nights
    def weekend?(date)
      date.cwday >= 6
    end
  end
end
