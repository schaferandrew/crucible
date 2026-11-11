<?php
/**
 * The one HTML page: the room list for the lobby screen.
 */
class Views
{
    public static function roomsPage(array $rooms)
    {
        $html = "<!DOCTYPE html>\n";
        $html .= "<html>\n<head><meta charset=\"utf-8\"><title>Juniper Inn rooms</title></head>\n<body>\n";
        $html .= "<h1>Rooms</h1>\n<table>\n";
        $html .= "<tr><th>Room</th><th>Name</th><th>Sleeps</th><th>Nightly</th></tr>\n";
        foreach ($rooms as $room) {
            $html .= '<tr><td>' . htmlspecialchars($room['id']) . '</td>'
                . '<td>' . htmlspecialchars($room['name']) . '</td>'
                . '<td>' . (int)$room['max_guests'] . '</td>'
                . '<td>$' . number_format($room['rate'], 2) . "</td></tr>\n";
        }
        $html .= "</table>\n</body>\n</html>";
        return $html;
    }
}
