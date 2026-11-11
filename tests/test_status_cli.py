"""`crucible status` reports what it just recorded."""
import pytest

from crucible import runrecord
from tests.records import run_meta, write_run


def _status(monkeypatch, capsys, run_dir, *flags):
    monkeypatch.setattr("sys.argv", ["crucible", str(run_dir), *flags])
    runrecord.status_main()
    return capsys.readouterr().out.strip()


def test_status_prints_withdrawn_not_invalid(tmp_path, monkeypatch, capsys):
    meta = run_meta("some-task")
    run_dir = write_run(tmp_path / "m" / "t" / "20260101_000000", meta)
    assert _status(monkeypatch, capsys, run_dir).endswith(": valid")
    assert _status(monkeypatch, capsys, run_dir, "--withdrawn", "published by mistake").endswith(": withdrawn: published by mistake")
    assert "withdrawn" in runrecord.statuses(run_dir)[-1]
    assert _status(monkeypatch, capsys, run_dir, "--invalid", "stale server").endswith(": invalid: stale server")
    assert _status(monkeypatch, capsys, run_dir, "--valid").endswith(": valid")
    _status(monkeypatch, capsys, run_dir, "--withdrawn", "again")
    assert _status(monkeypatch, capsys, run_dir).endswith(": withdrawn: again")
