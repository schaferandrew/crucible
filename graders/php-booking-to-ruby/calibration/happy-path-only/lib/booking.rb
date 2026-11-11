# frozen_string_literal: true

# Calibration fixture: an idiomatic Ruby port that follows the README and the fixtures, with Ruby's own
# value rules instead of PHP's (strict ==, String#empty?, integer division, Date.parse, wday, Arrays
# for every list). It passes the legacy fixtures.
require "json"
require "date"
require "uri"
require "cgi"

module Booking
  TAX_RATE = 0.125
  WEEKEND_SURCHARGE = 0.25
  BASE_GUESTS = 2

  class Store
    def initialize(dir)
      @dir = dir
    end

    def rooms
      JSON.parse(File.read(File.join(@dir, "rooms.json")))
    end

    def find_room(id)
      rooms.find { |room| room["id"] == id }
    end

    def bookings
      csv("bookings.csv")
    end

    def find_coupon(code)
      csv("coupons.csv").find { |c| c["code"] == code.strip.upcase }
    end

    private

    def csv(name)
      header, *rows = File.readlines(File.join(@dir, name), chomp: true).reject(&:empty?)
      keys = header.split(",")
      rows.map { |row| keys.zip(row.split(",")).to_h }
    end
  end

  class App
    def initialize(store)
      @store = store
    end

    def call(request)
      path, qs = request.split("?", 2)
      q = qs ? URI.decode_www_form(qs).to_h : {}
      case path
      when "/rooms" then ok(@store.rooms.map { |r| summary(r) })
      when "/rooms.html" then [200, rooms_page]
      when "/room"
        room = @store.find_room(q["id"].to_s)
        room ? ok(summary(room)) : error(404, "Room not found")
      when "/quote" then quote(q)
      when "/bookings"
        list = @store.bookings
        list = list.select { |b| b["room_id"] == q["room"] } if q.key?("room")
        ok(list)
      when "/report" then report
      else error(404, "Not found")
      end
    end

    private

    def quote(q)
      room = @store.find_room(q["room"].to_s)
      return error(404, "Room not found") unless room
      nights = q["nights"].to_i
      return error(422, "Nights must be at least 1") if nights < 1
      guests = q["guests"].nil? || q["guests"].empty? ? 1 : q["guests"].to_i
      return error(422, "Too many guests for this room") if guests > room["max_guests"].to_i
      checkin = begin
        Date.parse(q["checkin"].to_s)
      rescue ArgumentError
        nil
      end
      return error(422, "Invalid check-in date") unless checkin

      rate = room["rate"].to_f
      base = rate * nights
      weekend = (0...nights).count { |i| (checkin + i).wday >= 6 }
      lines = [{ "label" => "Room (#{plural(nights)})", "amount" => base.round(2) }]
      lines << { "label" => "Weekend surcharge (#{plural(weekend)})", "amount" => (rate * WEEKEND_SURCHARGE * weekend).round(2) } if weekend > 0
      extra = guests - BASE_GUESTS
      lines << { "label" => "Extra guests (#{extra} x #{plural(nights)})", "amount" => (extra * room["extra_guest_fee"].to_f * nights).round(2) } if extra > 0
      fee = room["cleaning_fee"]
      lines << { "label" => "Cleaning", "amount" => fee.to_f.round(2) } unless fee.nil? || fee.to_s.empty?
      subtotal = lines.sum { |l| l["amount"] }

      discount = 0
      code = nil
      coupon = q["coupon"].to_s.empty? ? nil : @store.find_coupon(q["coupon"])
      if coupon && nights >= coupon["min_nights"].to_i
        discount = (-subtotal * coupon["percent"].to_f / 100).round(2)
        code = coupon["code"]
        lines << { "label" => "Coupon #{code} (#{coupon['percent']}%)", "amount" => discount }
      end
      tax = ((subtotal + discount) * TAX_RATE).round(2)
      total = (subtotal + discount + tax).round(2)
      checkout = checkin + nights
      ok({
        "room" => room["id"], "checkin" => checkin.iso8601, "checkout" => checkout.iso8601,
        "checkin_label" => checkin.strftime("%a %d %b %Y"), "checkout_label" => checkout.strftime("%a %d %b %Y"),
        "nights" => nights, "guests" => guests, "lines" => lines, "coupon" => code,
        "subtotal" => subtotal.round(2), "discount" => discount, "tax" => tax, "total" => total,
        "per_guest" => (total / guests).round(2)
      })
    end

    def report
      bookings = @store.bookings
      nights = bookings.sum { |b| b["nights"].to_i }
      ok({
        "bookings" => bookings.size,
        "nights" => nights,
        "average_nights" => bookings.empty? ? 0 : nights / bookings.size,
        "unpaid" => bookings.count { |b| b["paid"] != "1" },
        "by_room" => bookings.group_by { |b| b["room_id"] }.transform_values(&:size)
      })
    end

    def rooms_page
      rows = @store.rooms.map do |r|
        price = format("%.2f", r["rate"].to_f).sub(/(\d)(?=(\d{3})+\.)/, '\1,')
        "<tr><td>#{CGI.escapeHTML(r['id'])}</td><td>#{CGI.escapeHTML(r['name'])}</td>" \
          "<td>#{r['max_guests'].to_i}</td><td>$#{price}</td></tr>\n"
      end
      "<!DOCTYPE html>\n<html>\n<head><meta charset=\"utf-8\"><title>Juniper Inn rooms</title></head>\n<body>\n" \
        "<h1>Rooms</h1>\n<table>\n<tr><th>Room</th><th>Name</th><th>Sleeps</th><th>Nightly</th></tr>\n" \
        "#{rows.join}</table>\n</body>\n</html>"
    end

    def summary(room)
      { "id" => room["id"], "name" => room["name"], "rate" => room["rate"].to_f.round(2), "max_guests" => room["max_guests"].to_i }
    end

    def plural(n)
      "#{n} night#{n == 1 ? '' : 's'}"
    end

    def ok(data)
      [200, JSON.generate(data)]
    end

    def error(status, message)
      [status, JSON.generate("error" => message)]
    end
  end

  def self.handle(request)
    App.new(Store.new(File.join(__dir__, "..", "data"))).call(request)
  end
end
