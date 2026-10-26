"""Subprocess helpers (macOS and Linux).

Agents are launched in their own session so a timeout or Ctrl+C can tear down
the whole tree (agent + MCP servers + shells it spawned): killpg(SIGTERM),
escalating to SIGKILL.
"""
from __future__ import annotations

import os
import shlex
import shutil
import signal
import subprocess
from pathlib import Path

def resolve_executable(name: str) -> str:
    """Absolute path to an executable on PATH."""
    path = shutil.which(name)
    if path is None:
        raise FileNotFoundError(f"'{name}' not found on PATH")
    return path


SECRET_ENV_MARKERS = ("KEY", "TOKEN", "SECRET", "PASSWORD")


def format_command(cmd: list[str], env: dict[str, str] | None = None) -> str:
    """Shell-pasteable rendering of a command (for command.sh records).

    Secret-looking variables are redacted so run directories never hold keys.
    """
    def shown(name: str, value: str) -> str:
        return "<redacted>" if any(m in name.upper() for m in SECRET_ENV_MARKERS) else value

    lines = [f"export {k}={shlex.quote(shown(k, v))}" for k, v in (env or {}).items()]
    lines.append(shlex.join(cmd))
    return "\n".join(lines)


def kill_tree(proc: subprocess.Popen, grace: int = 10) -> None:
    """Terminate proc and everything it spawned; best effort, never raises."""
    if proc.poll() is not None:
        return
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        proc.wait(timeout=grace)
    except (ProcessLookupError, subprocess.TimeoutExpired):
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except ProcessLookupError:
            pass


def spawn(cmd: list[str], *, cwd: Path | str | None = None, env: dict | None = None,
          stdin=None, stdout=None, stderr=None) -> subprocess.Popen:
    """Start cmd in its own session, so kill_tree can stop everything it spawns."""
    cmd = [resolve_executable(cmd[0]), *cmd[1:]]
    return subprocess.Popen(cmd, cwd=cwd, env=env, stdin=stdin, stdout=stdout, stderr=stderr,
                            start_new_session=True)


def wait(proc: subprocess.Popen, timeout: int, label: str) -> dict:
    """Wait for proc, killing its tree on timeout/interrupt/shutdown.

    The finally block is a safety net for every exit path (e.g. SIGTERM while
    SIGINT is ignored in backgrounded shells) so agents are never orphaned.
    """
    timed_out = False
    try:
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        print(f"[TIMEOUT] {label} timed out after {timeout}s")
    except KeyboardInterrupt:
        print("\n[INTERRUPTED] Killing agent process tree...")
        raise
    finally:
        kill_tree(proc)
    return {"returncode": proc.returncode, "timed_out": timed_out}


def run_logged(cmd: list[str], run_dir: Path, timeout: int, label: str, *,
               cwd: Path | str | None = None, env: dict | None = None) -> dict:
    """Run headless, streaming output live to stdout.txt/stderr.txt.

    Streams instead of buffering so progress can be observed (tail -f) while
    the test runs.
    """
    with open(run_dir / "stdout.txt", "wb") as out_f, \
         open(run_dir / "stderr.txt", "wb") as err_f:
        # Headless agents never need stdin; DEVNULL stops them waiting on it.
        proc = spawn(cmd, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                     stdout=out_f, stderr=err_f)
        return wait(proc, timeout, label)


def run_interactive(cmd: list[str], timeout: int, label: str, *,
                    cwd: Path | str | None = None, env: dict | None = None) -> dict:
    """Run an agent TUI attached to the terminal; output is not captured."""
    proc = spawn(cmd, cwd=cwd, env=env)
    return wait(proc, timeout, label)
