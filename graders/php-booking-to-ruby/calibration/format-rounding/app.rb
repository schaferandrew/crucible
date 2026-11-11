# frozen_string_literal: true

# Juniper Inn booking desk, command-line entry point.
#
#   ruby app.rb '/quote?room=101&checkin=2024-03-19&nights=2&guests=1'
#
# Prints the response body. Exit status 0 for a 2xx response, 1 otherwise.
require_relative "lib/juniper/router"

module Juniper
  def self.handle(request)
    Router.new(DataStore.new(File.join(__dir__, "data"))).dispatch(request)
  end
end

if $PROGRAM_NAME == __FILE__
  status, body = Juniper.handle(ARGV[0] || "/")
  puts body
  exit(status >= 200 && status < 300 ? 0 : 1)
end
