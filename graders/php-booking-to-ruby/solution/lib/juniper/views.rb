# frozen_string_literal: true

require_relative "php"

module Juniper
  # The one HTML page: the room list for the lobby screen.
  module Views
    module_function

    def rooms_page(rooms)
      html = +"<!DOCTYPE html>\n"
      html << "<html>\n<head><meta charset=\"utf-8\"><title>Juniper Inn rooms</title></head>\n<body>\n"
      html << "<h1>Rooms</h1>\n<table>\n"
      html << "<tr><th>Room</th><th>Name</th><th>Sleeps</th><th>Nightly</th></tr>\n"
      rooms.each do |room|
        html << "<tr><td>#{PHP.h(room['id'])}</td>" \
                "<td>#{PHP.h(room['name'])}</td>" \
                "<td>#{PHP.int(room['max_guests'])}</td>" \
                "<td>$#{PHP.number_format(room['rate'], 2)}</td></tr>\n"
      end
      html << "</table>\n</body>\n</html>"
      html
    end
  end
end
