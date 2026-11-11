"""The legacy fixture tests, ported to Ruby: `ruby test/run_tests.rb` passes and really checks tests/fixtures/cases.json."""
import json
import shutil
import tempfile
from pathlib import Path

from support import ROOT, ruby

RUNNER = "test/run_tests.rb"


class TestRubyTests:
    """ruby tests"""

    def test_ruby_tests_pass(self):
        assert (ROOT / RUNNER).is_file(), f"no {RUNNER}"
        result = ruby(RUNNER)
        assert result.returncode == 0, f"`ruby {RUNNER}` exits {result.returncode}: {(result.stdout + result.stderr).strip()[-400:]}"

    def test_ruby_tests_read_the_legacy_fixtures(self):
        # The same tests in a copy whose fixtures expect different bodies must fail
        assert (ROOT / RUNNER).is_file(), f"no {RUNNER}"
        assert ruby(RUNNER).returncode == 0, f"`ruby {RUNNER}` fails on the real fixtures"
        with tempfile.TemporaryDirectory() as tmp:
            copy = Path(tmp) / "repo"
            shutil.copytree(ROOT, copy, ignore=shutil.ignore_patterns("crucible_hidden", ".git"))
            cases_path = copy / "tests" / "fixtures" / "cases.json"
            cases = json.loads(cases_path.read_text(encoding="utf-8"))
            for case in cases:
                case["body"] = "<html>not this</html>" if isinstance(case["body"], str) else {"error": "not this"}
            cases_path.write_text(json.dumps(cases), encoding="utf-8")
            result = ruby(RUNNER, cwd=copy)
            assert result.returncode != 0, f"`ruby {RUNNER}` still passes when every fixture's expected body is changed"
