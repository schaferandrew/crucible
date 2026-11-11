# frozen_string_literal: true

require "json"
require_relative "php"

module Juniper
  # Flat-file storage: rooms in JSON, bookings and coupons in CSV. No database.
  class DataStore
    def initialize(dir)
      @dir = dir.chomp("/")
    end

    def rooms
      JSON.parse(File.read(File.join(@dir, "rooms.json")))
    end

    # Room ids match the way PHP's == matches them: "0101" finds room "101"
    def find_room(id)
      rooms.find { |room| PHP.loose_eq?(room["id"], id) }
    end

    # Each booking is a Hash of strings, exactly as the CSV holds them
    def bookings
      read_csv("bookings.csv")
    end

    def coupons
      read_csv("coupons.csv")
    end

    def find_coupon(code)
      code = code.to_s.strip.upcase
      coupons.find { |coupon| PHP.loose_eq?(coupon["code"], code) }
    end

    private

    # The data files are plain CSV (no quoted fields). Empty fields stay empty strings, trailing ones too.
    def read_csv(name)
      lines = File.read(File.join(@dir, name)).split(/\r?\n/)
      header = lines.shift.split(",", -1)
      lines.reject { |line| line.empty? }.map { |line| header.zip(line.split(",", -1)).to_h }
    end
  end
end
