<?php
/**
 * Flat-file storage: rooms in JSON, bookings and coupons in CSV. No database.
 */
class DataStore
{
    private $dir;

    public function __construct($dir)
    {
        $this->dir = rtrim($dir, '/');
    }

    public function rooms()
    {
        $json = file_get_contents($this->dir . '/rooms.json');
        return json_decode($json, true);
    }

    public function findRoom($id)
    {
        foreach ($this->rooms() as $room) {
            if ($room['id'] == $id) {
                return $room;
            }
        }
        return null;
    }

    public function bookings()
    {
        return $this->readCsv('bookings.csv');
    }

    public function coupons()
    {
        return $this->readCsv('coupons.csv');
    }

    public function findCoupon($code)
    {
        $code = strtoupper(trim($code));
        foreach ($this->coupons() as $coupon) {
            if ($coupon['code'] == $code) {
                return $coupon;
            }
        }
        return null;
    }

    private function readCsv($name)
    {
        $rows = [];
        $handle = fopen($this->dir . '/' . $name, 'r');
        $header = fgetcsv($handle, 0, ',', '"', '\\');
        while (($row = fgetcsv($handle, 0, ',', '"', '\\')) !== false) {
            if ($row === [null]) {
                continue; // blank line
            }
            $rows[] = array_combine($header, $row);
        }
        fclose($handle);
        return $rows;
    }
}
