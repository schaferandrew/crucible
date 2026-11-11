# frozen_string_literal: true

require "json"
require "uri"
require_relative "php"
require_relative "dates"
require_relative "pricing"
require_relative "views"
require_relative "data_store"

module Juniper
  # Maps a request line like "/quote?room=101&nights=2" to [status, body].
  #
  #   /rooms          all rooms, JSON
  #   /rooms.html     the rooms page, HTML
  #   /room?id=       one room, JSON
  #   /quote?room=&checkin=&nights=&guests=&coupon=
  #   /bookings       all bookings; ?room= for one room's bookings
  #   /report         booking statistics
  class Router
    def initialize(store)
      @store = store
    end

    def dispatch(request)
      path, query_string = request.split("?", 2)
      query = parse_query(query_string)

      case path
      when "/rooms" then json(200, @store.rooms.map { |room| room_summary(room) })
      when "/rooms.html" then [200, Views.rooms_page(@store.rooms)]
      when "/room"
        room = @store.find_room(query.fetch("id", ""))
        room ? json(200, room_summary(room)) : error(404, "Room not found")
      when "/quote" then quote(query)
      when "/bookings" then bookings(query)
      when "/report" then report
      else error(404, "Not found")
      end
    end

    private

    # parse_str(): the last value of a repeated key wins
    def parse_query(query_string)
      return {} if query_string.nil? || query_string.empty?
      URI.decode_www_form(query_string).each_with_object({}) { |(key, value), out| out[key] = value }
    rescue ArgumentError
      {}
    end

    def quote(q)
      room = @store.find_room(q.fetch("room", ""))
      return error(404, "Room not found") unless room

      nights = q.key?("nights") ? PHP.int(q["nights"]) : 0
      return error(422, "Nights must be at least 1") if nights < 1

      guests = PHP.empty?(q["guests"]) ? 1 : q["guests"] # "0" counts as not given
      return error(422, "Too many guests for this room") if PHP.cmp(guests, room["max_guests"]) > 0

      checkin = Dates.parse(q.fetch("checkin", ""))
      return error(422, "Invalid check-in date") unless checkin

      coupon = PHP.empty?(q["coupon"]) ? nil : @store.find_coupon(q["coupon"])
      checkout = Dates.add_days(checkin, nights)
      result = Pricing.quote(room, checkin, nights, guests, coupon)
      json(200, {
        "room" => room["id"],
        "checkin" => Dates.iso(checkin),
        "checkout" => Dates.iso(checkout),
        "checkin_label" => Dates.label(checkin),
        "checkout_label" => Dates.label(checkout)
      }.merge(result))
    end

    # PHP's array_filter keeps each booking's original position as its key, and json_encode then
    # writes an object ({"1": ..., "3": ...}) unless the positions happen to be 0..n-1.
    def bookings(q)
      pairs = @store.bookings.each_with_index.map { |booking, i| [i, booking] }
      if q.key?("room")
        pairs = pairs.select { |_, booking| PHP.loose_eq?(booking["room_id"], q["room"]) }
      end
      json(200, PHP.php_array(pairs))
    end

    def report
      bookings = @store.bookings
      nights = 0
      unpaid = 0
      by_room = {}
      bookings.each do |b|
        nights += PHP.num(b["nights"])
        unpaid += 1 if PHP.loose_eq?(b["paid"], false) # "" and "0" are unpaid; "no" is not
        by_room[b["room_id"]] = by_room.fetch(b["room_id"], 0) + 1
      end
      count = bookings.size
      json(200, {
        "bookings" => count,
        "nights" => nights,
        "average_nights" => count.zero? ? 0 : PHP.round(nights.to_f / count, 2),
        "unpaid" => unpaid,
        "by_room" => by_room
      })
    end

    def room_summary(room)
      {
        "id" => room["id"],
        "name" => room["name"],
        "rate" => PHP.round(room["rate"], 2),
        "max_guests" => PHP.int(room["max_guests"])
      }
    end

    def json(status, data)
      [status, JSON.generate(data)]
    end

    def error(status, message)
      json(status, { "error" => message })
    end
  end
end
