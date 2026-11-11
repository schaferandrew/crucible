<?php
/**
 * Juniper Inn booking desk, command-line entry point.
 *
 *   php app.php '/quote?room=101&checkin=2024-03-19&nights=2&guests=1'
 *
 * Prints the response body. Exit status 0 for a 2xx response, 1 otherwise.
 */
date_default_timezone_set('UTC');

require __DIR__ . '/src/DataStore.php';
require __DIR__ . '/src/Dates.php';
require __DIR__ . '/src/Pricing.php';
require __DIR__ . '/src/Views.php';
require __DIR__ . '/src/Router.php';

function handle($request)
{
    $router = new Router(new DataStore(__DIR__ . '/data'));
    return $router->dispatch($request);
}

if (PHP_SAPI === 'cli' && realpath($argv[0]) === __FILE__) {
    list($status, $body) = handle(isset($argv[1]) ? $argv[1] : '/');
    echo $body, "\n";
    exit($status >= 200 && $status < 300 ? 0 : 1);
}
