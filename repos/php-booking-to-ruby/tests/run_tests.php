<?php
/**
 * Fixture tests: every case in fixtures/cases.json is a request, the status it must answer with and
 * the body it must return (JSON compared as decoded values, HTML as text).
 *
 *   php tests/run_tests.php
 */
require __DIR__ . '/../app.php';

$cases = json_decode(file_get_contents(__DIR__ . '/fixtures/cases.json'), true);
$failed = 0;
foreach ($cases as $case) {
    list($status, $body) = handle($case['request']);
    $actual = is_string($case['body']) ? $body : json_decode($body, true);
    $ok = $status === $case['status'] && $actual == $case['body'];
    if (!$ok) {
        $failed++;
        echo "FAIL {$case['request']}\n  expected {$case['status']} " . json_encode($case['body'])
            . "\n  got      $status $body\n";
    } else {
        echo "ok   {$case['request']}\n";
    }
}
echo count($cases) - $failed, '/', count($cases), " passed\n";
exit($failed ? 1 : 0);
