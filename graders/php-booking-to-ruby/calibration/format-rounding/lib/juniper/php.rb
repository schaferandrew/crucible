# frozen_string_literal: true

module Juniper
  # The handful of PHP 8 value rules the legacy app leans on, so the port behaves the same for the
  # same input. Keep these explicit: Ruby's own rules differ for every one of them.
  module PHP
    NUMERIC = /\A[ \t\n\r\v\f]*[+-]?(\d+(\.\d*)?|\.\d+)([eE][+-]?\d+)?[ \t\n\r\v\f]*\z/.freeze

    module_function

    # is_numeric(): "89.00", " 12", "1e3" yes; "", "12abc", "abc" no
    def numeric?(value)
      case value
      when Integer, Float then true
      when String then NUMERIC.match?(value)
      else false
      end
    end

    # A numeric value as a number: "210" -> 210, "124.50" -> 124.5, 20 -> 20
    def num(value)
      case value
      when Integer, Float then value
      when nil, false then 0
      when true then 1
      when String
        raise TypeError, "non-numeric value: #{value.inspect}" unless numeric?(value)
        s = value.strip
        s.match?(/\A[+-]?\d+\z/) ? Integer(s, 10) : Float(s)
      else
        raise TypeError, "non-numeric value: #{value.inspect}"
      end
    end

    # (int)$value: "3.7" -> 3, "12abc" -> 12, "abc" -> 0
    def int(value)
      case value
      when Integer then value
      when Float then value.truncate
      when nil, false then 0
      when true then 1
      else
        m = value.to_s.match(/\A[ \t\n\r\v\f]*[+-]?(\d+(\.\d*)?|\.\d+)([eE][+-]?\d+)?/)
        m ? Float(m[0].strip).truncate : 0
      end
    end

    # Boolean conversion: "", "0", 0, 0.0, nil, false and [] are false
    def truthy?(value)
      !(value.nil? || value == false || value == 0 || value == "" || value == "0" ||
        (value.respond_to?(:empty?) && !value.is_a?(String) && value.empty?))
    end

    # empty($value)
    def empty?(value)
      !truthy?(value)
    end

    # $a == $b (PHP 8 loose comparison) for the scalars the app compares
    def loose_eq?(a, b)
      return truthy?(a) == truthy?(b) if [true, false].include?(a) || [true, false].include?(b)
      if a.nil? || b.nil? # null == "x" compares "" with "x"; null == 0 compares as booleans
        other = a.nil? ? b : a
        return other.is_a?(String) ? other == "" : !truthy?(other)
      end
      if numeric?(a) && numeric?(b)
        num(a) == num(b)
      elsif a.is_a?(String) && b.is_a?(String)
        a == b
      else # a number and a non-numeric string compare as strings
        a.to_s == b.to_s
      end
    end

    # $a <=> $b for numbers and numeric strings (both numeric strings compare as numbers)
    def cmp(a, b)
      if numeric?(a) && numeric?(b)
        num(a) <=> num(b)
      else
        a.to_s <=> b.to_s
      end
    end

    # round($value, $places)
    def round(value, places = 0)
      format("%.#{places}f", num(value).to_f).to_f
    end

    # number_format($value, $decimals): rounded half away from zero, comma thousands
    def number_format(value, decimals = 0)
      rounded = round(value, decimals)
      whole, frac = format("%.#{decimals}f", rounded.abs).split(".")
      whole = whole.reverse.scan(/\d{1,3}/).join(",").reverse
      sign = rounded.negative? && rounded != 0 ? "-" : ""
      frac ? "#{sign}#{whole}.#{frac}" : "#{sign}#{whole}"
    end

    # htmlspecialchars() with PHP 8.1's default flags (ENT_QUOTES)
    def h(value)
      value.to_s.gsub("&", "&amp;").gsub('"', "&quot;").gsub("'", "&#039;").gsub("<", "&lt;").gsub(">", "&gt;")
    end

    # json_encode() of an array: a list when its keys are 0..n-1 in order, an object otherwise.
    # `pairs` is [[key, value], ...] with the keys PHP would hold.
    def php_array(pairs)
      if pairs.each_with_index.all? { |(key, _), i| key == i }
        pairs.map { |_, value| value }
      else
        pairs.each_with_object({}) { |(key, value), out| out[key.to_s] = value }
      end
    end
  end
end
