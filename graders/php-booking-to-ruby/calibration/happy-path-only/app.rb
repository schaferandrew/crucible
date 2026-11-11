# frozen_string_literal: true

require_relative "lib/booking"

if $PROGRAM_NAME == __FILE__
  status, body = Booking.handle(ARGV[0] || "/")
  puts body
  exit(status < 300 ? 0 : 1)
end
