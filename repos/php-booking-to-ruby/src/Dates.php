<?php
/**
 * Date helpers. Everything runs in UTC (app.php sets the default timezone).
 *
 * Accepted check-in formats: 2024-03-09 and 03/09/2024 (month/day/year, as the front desk types it).
 */
class Dates
{
    const LABEL = 'D j M Y';

    /** A timestamp for midnight on that date, or false. */
    public static function parse($value)
    {
        if (empty($value)) {
            return false;
        }
        $value = trim($value);
        $iso = '/^\d{4}-(0[1-9]|1[0-2])-([0-2]\d|3[01])$/';
        $us = '/^(0?[1-9]|1[0-2])\/(0?[1-9]|[12]\d|3[01])\/\d{4}$/';
        if (!preg_match($iso, $value) && !preg_match($us, $value)) {
            return false;
        }
        return strtotime($value);
    }

    public static function addDays($ts, $days)
    {
        return strtotime('+' . $days . ' days', $ts);
    }

    public static function iso($ts)
    {
        return date('Y-m-d', $ts);
    }

    public static function label($ts)
    {
        return date(self::LABEL, $ts);
    }

    /** Saturday and Sunday nights are charged as weekend nights. */
    public static function isWeekend($ts)
    {
        return date('N', $ts) >= 6;
    }
}
