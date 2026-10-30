"""The audit_log and workspace_unchanged checks (login-recovery), and the isolated-regression path helpers."""
import hashlib
import json
import subprocess

from crucible import checks, graders


def write_log(workspace, events, tamper=None):
    path = workspace / ".crucible" / "audit.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    prev, lines = "genesis", []
    for n, event in enumerate(events, 1):
        line = json.dumps({"seq": n, "prev": prev, "ts": "t", **event})
        prev = hashlib.sha256(line.encode()).hexdigest()
        lines.append(line)
    if tamper is not None:
        lines[tamper] = lines[tamper].replace("login_failed", "login_success")
    path.write_text("\n".join(lines) + "\n")


SESSION = {"id": "s", "type": "audit_log", "log": ".crucible/audit.jsonl",
           "sequence": [{"event": "login_success", "user": "u", "session": "$s"},
                        {"event": "dashboard_ok", "session": "$s"}],
           "then_none": [{"event": "logout", "session": "$s"}]}


def run(tmp_path, check, events=None, tamper=None):
    ws = tmp_path / "workspace"
    ws.mkdir(exist_ok=True)
    if events is not None:
        write_log(ws, events, tamper)
    return checks.CHECKS[check["type"]]({**check, "_run_dir": tmp_path}, "an answer")[:2]


def test_sequence_binds_the_session_and_respects_then_none(tmp_path):
    good = [{"event": "login_success", "user": "u", "session": "a"}, {"event": "dashboard_ok", "session": "a"}]
    assert run(tmp_path, SESSION, good)[0]
    # a dashboard served to another session doesn't count
    other = [{"event": "login_success", "user": "u", "session": "a"}, {"event": "dashboard_ok", "session": "b"}]
    assert not run(tmp_path, SESSION, other)[0]
    # logged out afterwards
    out = good + [{"event": "logout", "session": "a"}]
    assert "followed by" in run(tmp_path, SESSION, out)[1]
    # order matters
    assert not run(tmp_path, SESSION, good[::-1])[0]


def test_a_second_valid_session_after_a_logout_passes(tmp_path):
    events = [{"event": "login_success", "user": "u", "session": "a"}, {"event": "dashboard_ok", "session": "a"},
              {"event": "logout", "session": "a"},
              {"event": "login_success", "user": "u", "session": "b"}, {"event": "dashboard_ok", "session": "b"}]
    assert run(tmp_path, SESSION, events)[0]


def test_a_broken_chain_or_missing_log_counts_for_nothing(tmp_path):
    events = [{"event": "login_failed", "user": "u"}, {"event": "login_success", "user": "u", "session": "a"},
              {"event": "dashboard_ok", "session": "a"}]
    assert run(tmp_path, SESSION, events)[0]
    ok, detail = run(tmp_path, SESSION, events, tamper=0)
    assert not ok and "altered" in detail
    (tmp_path / "empty" / "workspace").mkdir(parents=True)
    assert "no .crucible" in run(tmp_path / "empty", SESSION)[1]


def git(ws, *args):
    subprocess.run(["git", "-c", "user.name=c", "-c", "user.email=c@l", *args], cwd=ws, check=True, capture_output=True)


def test_workspace_unchanged_compares_with_the_seeded_commit(tmp_path):
    ws = tmp_path / "workspace"
    (ws / "public").mkdir(parents=True)
    (ws / "server.js").write_text("a")
    (ws / "public" / "x.html").write_text("x")
    for args in (["init", "-q"], ["add", "-A"], ["commit", "-q", "-m", "seed"]):
        git(ws, *args)
    check = {"id": "c", "type": "workspace_unchanged", "paths": ["server.js", "public"],
             "log": ".crucible/audit.jsonl", "any_event": ["login_failed"]}
    used = [{"event": "login_failed", "user": "u"}]
    assert run(tmp_path, check, used) == (True, "as seeded")
    (ws / "notes.txt").write_text("scratch files are fine")
    assert run(tmp_path, check, used)[0]
    (ws / "public" / "new.html").write_text("new")
    assert run(tmp_path, check, used) == (False, "changed: public/new.html")
    (ws / "public" / "new.html").unlink()
    (ws / "server.js").write_text("b")
    assert run(tmp_path, check, used) == (False, "changed: server.js")
    git(ws, "commit", "-qam", "edit")  # committing the edit doesn't hide it
    assert run(tmp_path, check, used)[0] is False


def test_workspace_unchanged_needs_the_app_to_have_been_used(tmp_path):
    ws = tmp_path / "workspace"
    ws.mkdir()
    (ws / "server.js").write_text("a")
    for args in (["init", "-q"], ["add", "-A"], ["commit", "-q", "-m", "seed"]):
        git(ws, *args)
    check = {"id": "c", "type": "workspace_unchanged", "paths": ["server.js"],
             "log": ".crucible/audit.jsonl", "any_event": ["login_failed"]}
    assert run(tmp_path, check, [{"event": "server_start"}]) == (False, "the app was never used")


def test_empty_answer_fails_audit_checks(tmp_path):
    ws = tmp_path / "workspace"
    ws.mkdir()
    write_log(ws, [{"event": "login_success", "user": "u", "session": "a"}, {"event": "dashboard_ok", "session": "a"}])
    task = {"checks": [SESSION], "prompt": ""}
    assert checks.run_checks(task, "", tmp_path)[0]["passed"] is False
    assert checks.run_checks(task, "done", tmp_path)[0]["passed"] is True


def test_regression_helpers_accept_js_tests_and_a_repo_root():
    assert graders.TEST_FILE.search("server.test.js") and graders.TEST_FILE.search("a/b.spec.mjs")
    assert graders.TEST_FILE.search("x.test.tsx") and not graders.TEST_FILE.search("test.js")
    assert graders._within("server.test.js", ".") and graders._within("apps/api/x.ts", "apps/api")
    assert not graders._within("apps/web/x.ts", "apps/api")
