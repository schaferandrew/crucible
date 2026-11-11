# frozen_string_literal: true

# The legacy fixture tests, ported: every case in tests/fixtures/cases.json is a request, the status
# it must answer with and the body it must return (JSON compared as parsed values, HTML as text).
#
#   ruby test/run_tests.rb
require "json"
require_relative "../app"

cases = JSON.parse(File.read(File.join(__dir__, "..", "tests", "fixtures", "cases.json")))
failed = 0
cases.each do |c|
  status, body = Juniper.handle(c["request"])
  actual = c["body"].is_a?(String) ? body : (JSON.parse(body) rescue body)
  if status == c["status"] && actual == c["body"]
    puts "ok   #{c['request']}"
  else
    failed += 1
    puts "FAIL #{c['request']}\n  expected #{c['status']} #{JSON.generate(c['body'])}\n  got      #{status} #{body}"
  end
end
puts "#{cases.size - failed}/#{cases.size} passed"
exit(failed.zero? && !cases.empty? ? 0 : 1)
