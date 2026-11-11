# frozen_string_literal: true

require "json"
require_relative "../app"

cases = JSON.parse(File.read(File.expand_path("../tests/fixtures/cases.json", __dir__)))
failures = cases.reject do |c|
  status, body = Booking.handle(c["request"])
  status == c["status"] && (c["body"].is_a?(String) ? body : JSON.parse(body)) == c["body"]
end
failures.each { |c| puts "FAIL #{c['request']}" }
puts "#{cases.size - failures.size}/#{cases.size} passed"
exit(failures.empty? ? 0 : 1)
