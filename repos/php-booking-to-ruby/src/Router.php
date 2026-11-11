<?php
/**
 * Maps a request line like "/quote?room=101&nights=2" to [status, body].
 *
 *   /rooms          all rooms, JSON
 *   /rooms.html     the rooms page, HTML
 *   /room?id=       one room, JSON
 *   /quote?room=&checkin=&nights=&guests=&coupon=
 *   /bookings       all bookings; ?room= for one room's bookings
 *   /report         booking statistics
 */
class Router
{
    private $store;

    public function __construct(DataStore $store)
    {
        $this->store = $store;
    }

    public function dispatch($request)
    {
        $parts = explode('?', $request, 2);
        $path = $parts[0];
        $query = [];
        if (isset($parts[1])) {
            parse_str($parts[1], $query);
        }

        switch ($path) {
            case '/rooms':
                return $this->json(200, array_map([$this, 'roomSummary'], $this->store->rooms()));
            case '/rooms.html':
                return [200, Views::roomsPage($this->store->rooms())];
            case '/room':
                $room = $this->store->findRoom(isset($query['id']) ? $query['id'] : '');
                if ($room === null) {
                    return $this->error(404, 'Room not found');
                }
                return $this->json(200, $this->roomSummary($room));
            case '/quote':
                return $this->quote($query);
            case '/bookings':
                return $this->bookings($query);
            case '/report':
                return $this->report();
            default:
                return $this->error(404, 'Not found');
        }
    }

    private function quote(array $q)
    {
        $room = $this->store->findRoom(isset($q['room']) ? $q['room'] : '');
        if ($room === null) {
            return $this->error(404, 'Room not found');
        }
        $nights = isset($q['nights']) ? (int)$q['nights'] : 0;
        if ($nights < 1) {
            return $this->error(422, 'Nights must be at least 1');
        }
        $guests = empty($q['guests']) ? 1 : $q['guests'];
        if ($guests > $room['max_guests']) {
            return $this->error(422, 'Too many guests for this room');
        }
        $checkin = Dates::parse(isset($q['checkin']) ? $q['checkin'] : '');
        if ($checkin === false) {
            return $this->error(422, 'Invalid check-in date');
        }
        $coupon = empty($q['coupon']) ? null : $this->store->findCoupon($q['coupon']);

        $checkout = Dates::addDays($checkin, $nights);
        $quote = Pricing::quote($room, $checkin, $nights, $guests, $coupon);
        return $this->json(200, array_merge([
            'room' => $room['id'],
            'checkin' => Dates::iso($checkin),
            'checkout' => Dates::iso($checkout),
            'checkin_label' => Dates::label($checkin),
            'checkout_label' => Dates::label($checkout),
        ], $quote));
    }

    private function bookings(array $q)
    {
        $bookings = $this->store->bookings();
        if (isset($q['room'])) {
            $room = $q['room'];
            $bookings = array_filter($bookings, function ($b) use ($room) {
                return $b['room_id'] == $room;
            });
        }
        return $this->json(200, $bookings);
    }

    private function report()
    {
        $bookings = $this->store->bookings();
        $nights = 0;
        $unpaid = 0;
        $byRoom = [];
        foreach ($bookings as $b) {
            $nights += $b['nights'];
            if ($b['paid'] == false) {
                $unpaid++;
            }
            if (!isset($byRoom[$b['room_id']])) {
                $byRoom[$b['room_id']] = 0;
            }
            $byRoom[$b['room_id']]++;
        }
        $count = count($bookings);
        return $this->json(200, [
            'bookings' => $count,
            'nights' => $nights,
            'average_nights' => $count ? round($nights / $count, 2) : 0,
            'unpaid' => $unpaid,
            'by_room' => $byRoom,
        ]);
    }

    private function roomSummary(array $room)
    {
        return [
            'id' => $room['id'],
            'name' => $room['name'],
            'rate' => round($room['rate'], 2),
            'max_guests' => (int)$room['max_guests'],
        ];
    }

    private function json($status, $data)
    {
        return [$status, json_encode($data)];
    }

    private function error($status, $message)
    {
        return $this->json($status, ['error' => $message]);
    }
}
