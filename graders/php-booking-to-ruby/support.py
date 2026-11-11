"""Helpers for the hidden tests: run the Ruby port from the grading copy's root, like the front desk would."""
import json
import subprocess
from pathlib import Path

from expected_outputs import EXPECTED

ROOT = Path(__file__).resolve().parent.parent  # the grading copy: the seeded repo with the model's app.rb, lib/ and test/


def ruby(*args, cwd=ROOT):
    return subprocess.run(["ruby", *map(str, args)], cwd=cwd, capture_output=True, text=True, timeout=60)


def run(request):
    """(exit status, stdout) of `ruby app.rb <request>`."""
    assert (ROOT / "app.rb").is_file(), "no app.rb in the repo root"
    result = ruby("app.rb", request)
    return result.returncode, result.stdout, result.stderr


def response(request):
    """The port's response, checked against the PHP reference's exit status; the body parsed when it's JSON."""
    want = EXPECTED[request]
    code, out, err = run(request)
    want_code = 0 if 200 <= want["status"] < 300 else 1
    assert code == want_code, f"{request}: exit {code}, the PHP app exits {want_code}. stderr: {err.strip()[-300:]}"
    if isinstance(want["body"], str):
        return out.rstrip("\n")
    try:
        return json.loads(out)
    except ValueError:
        raise AssertionError(f"{request}: stdout is not JSON: {out.strip()[:300]!r}") from None


def same_as_php(request, *keys):
    """The response equals the PHP reference's: the whole body, or only `keys` of a JSON object body."""
    body = response(request)
    want = EXPECTED[request]["body"]
    if not keys:
        assert body == want, f"{request}:\n got  {json.dumps(body)[:600]}\n want {json.dumps(want)[:600]}"
        return
    assert isinstance(body, dict), f"{request}: expected a JSON object, got {json.dumps(body)[:300]}"
    for key in keys:
        assert key in body, f"{request}: no '{key}' in the response"
        assert body[key] == want[key], f"{request}: {key} is {json.dumps(body[key])}, the PHP app gives {json.dumps(want[key])}"
