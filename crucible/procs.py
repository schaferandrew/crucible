"""Cross-platform subprocess helpers (macOS, Linux, Windows).

Agents are launched in their own process group so a timeout or Ctrl+C can
tear down the whole tree (agent + MCP servers + shells it spawned):

- POSIX: start_new_session + killpg(SIGTERM), escalating to SIGKILL
- Windows: CREATE_NEW_PROCESS_GROUP + `taskkill /T /F`

npm-installed CLIs (pi, opencode) are `.cmd` shims on Windows that Popen
cannot find by bare name, so executables are resolved with shutil.which.
"""
from __future__ import annotations

import os
import shlex
import shutil
import signal
import subprocess
from pathlib import Path

IS_WINDOWS = os.name == "nt"


def resolve_executable(name: str) -> str:
    """Absolute path to an executable on PATH (honours PATHEXT on Windows)."""
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
    if IS_WINDOWS:
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)],
                       capture_output=True, check=False)
        try:
            proc.wait(timeout=grace)
        except subprocess.TimeoutExpired:
            proc.kill()
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
          stdin=None, stdout=None, stderr=None,
          interactive: bool = False) -> subprocess.Popen:
    """Start cmd in its own process group.

    interactive=True is for TUIs: on Windows they must stay in the console's
    process group to receive keyboard input, so no new group is created.
    (TUIs put the console in raw mode, so Ctrl+C reaches the TUI as a key.)
    """
    cmd = [resolve_executable(cmd[0]), *cmd[1:]]
    kwargs: dict = {"cwd": cwd, "env": env, "stdin": stdin, "stdout": stdout, "stderr": stderr}
    if IS_WINDOWS:
        if not interactive:
            kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True
    return subprocess.Popen(cmd, **kwargs)


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
    proc = spawn(cmd, cwd=cwd, env=env, interactive=True)
    return wait(proc, timeout, label)
