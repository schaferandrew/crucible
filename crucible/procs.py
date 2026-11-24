"""Subprocess helpers (macOS and Linux).

Agents are launched in their own session so a timeout or Ctrl+C can tear down
the whole tree (agent + MCP servers + shells it spawned): killpg(SIGTERM),
escalating to SIGKILL.

That misses whatever an agent's tools start in a process group of their own (pi runs
each shell command detached), so runs also sweep by working directory: a watchdog kills
any process in the workspace past a memory limit while the agent runs, and every
process still in the workspace is stopped when it ends.
"""
from __future__ import annotations

import os
import shlex
import shutil
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

# Test runners an agent starts: one worker at a time, and a heap cap on every Node
# process, so a stuck or orphaned worker can't take the machine's memory
NODE_HEAP_MB = 3072
# A process in the workspace past this resident size is killed mid-run
WATCHDOG_RSS_MB = 4096
WATCHDOG_INTERVAL_S = 10.0

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


def test_runner_limits(environ: dict[str, str] | None = None) -> dict[str, str]:
    """Env for an agent's test runners: vitest on one worker, Node heaps capped.

    Values already set in the environment win, so a user can loosen them.
    """
    environ = os.environ if environ is None else environ
    limits = {name: environ.get(name, "1") for name in
              ("VITEST_MAX_FORKS", "VITEST_MIN_FORKS", "VITEST_MAX_THREADS", "VITEST_MIN_THREADS")}
    node_options = environ.get("NODE_OPTIONS", "")
    if "--max-old-space-size" not in node_options:
        node_options = f"{node_options} --max-old-space-size={NODE_HEAP_MB}".strip()
    limits["NODE_OPTIONS"] = node_options
    return limits


def _under(path: str, root: str) -> bool:
    return path == root or path.startswith(root.rstrip("/") + "/")


def pids_in(directory: Path | str) -> list[int]:
    """Processes (other than this one) whose working directory is in directory."""
    root = os.path.realpath(directory)
    found: list[int] = []
    if Path("/proc/self/cwd").exists():  # Linux
        for entry in Path("/proc").iterdir():
            if entry.name.isdigit():
                try:
                    cwd = os.readlink(entry / "cwd")
                except OSError:
                    continue
                if _under(cwd, root):
                    found.append(int(entry.name))
    elif shutil.which("lsof"):  # macOS
        out = subprocess.run(["lsof", "-nP", "-d", "cwd", "-Fpn"], capture_output=True, text=True).stdout
        pid = None
        for line in out.splitlines():
            if line.startswith("p"):
                pid = int(line[1:])
            elif line.startswith("n") and pid is not None and _under(line[1:], root):
                found.append(pid)
    return [p for p in found if p != os.getpid()]


def _rss_mb(pids: list[int]) -> dict[int, tuple[float, str]]:
    """{pid: (resident MB, command name)} for the pids still alive."""
    if not pids:
        return {}
    out = subprocess.run(["ps", "-o", "pid=,rss=,comm=", "-p", ",".join(map(str, pids))],
                         capture_output=True, text=True).stdout
    sizes = {}
    for line in out.splitlines():
        parts = line.split(None, 2)
        if len(parts) >= 2 and parts[0].isdigit():
            sizes[int(parts[0])] = (int(parts[1]) / 1024, parts[2] if len(parts) > 2 else "?")
    return sizes


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    # A zombie is dead but still listed until its parent reaps it
    state = subprocess.run(["ps", "-o", "stat=", "-p", str(pid)], capture_output=True, text=True).stdout.strip()
    return bool(state) and not state.startswith("Z")


def _kill(pids: list[int], grace: float = 2.0) -> None:
    """SIGTERM, then SIGKILL whatever is left after grace seconds."""
    for sig in (signal.SIGTERM, signal.SIGKILL):
        for pid in pids:
            try:
                os.kill(pid, sig)
            except (ProcessLookupError, PermissionError):
                pass
        if sig == signal.SIGTERM:
            deadline = time.time() + grace
            while time.time() < deadline and any(_alive(p) for p in pids):
                time.sleep(0.1)


def stop_workspace_processes(workspace: Path | str | None) -> list[int]:
    """Stop every process still running in the workspace (servers, test workers...)."""
    if workspace is None or not Path(workspace).exists():
        return []
    pids = pids_in(workspace)
    if pids:
        _kill(pids)
        print(f"  Stopped {len(pids)} process(es) the agent left running in its workspace")
    return pids


class Watchdog:
    """While a run is going, kill any process in the workspace past a memory limit."""

    def __init__(self, workspace: Path | str | None, limit_mb: float = WATCHDOG_RSS_MB,
                 interval: float = WATCHDOG_INTERVAL_S):
        self.workspace, self.limit_mb, self.interval = workspace, limit_mb, interval
        self.killed: list[dict] = []
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, daemon=True)

    def __enter__(self) -> "Watchdog":
        if self.workspace is not None:
            self._thread.start()
        return self

    def __exit__(self, *exc) -> None:
        self._stop.set()
        if self._thread.is_alive():
            self._thread.join()

    def _loop(self) -> None:
        while not self._stop.wait(self.interval):
            try:
                self.check()
            except Exception as exc:  # never take the run down with it
                print(f"[WATCHDOG] check failed: {exc}", file=sys.stderr)

    def check(self) -> None:
        if not Path(self.workspace).exists():
            return
        for pid, (mb, name) in _rss_mb(pids_in(self.workspace)).items():
            if mb > self.limit_mb:
                _kill([pid])
                self.killed.append({"pid": pid, "command": name, "rss_mb": round(mb)})
                print(f"[WATCHDOG] killed {name} (pid {pid}): {mb / 1024:.1f} GB in the workspace, "
                      f"over the {self.limit_mb / 1024:.1f} GB limit")


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


def wait(proc: subprocess.Popen, timeout: int, label: str, workspace: Path | str | None = None) -> dict:
    """Wait for proc, killing its tree on timeout/interrupt/shutdown.

    The finally block is a safety net for every exit path (e.g. SIGTERM while
    SIGINT is ignored in backgrounded shells) so agents are never orphaned.
    With a workspace, a Watchdog runs meanwhile, and whatever is left running
    in the workspace afterwards (outside proc's group) is stopped too.
    """
    timed_out = False
    try:
        with Watchdog(workspace):
            proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        print(f"[TIMEOUT] {label} timed out after {timeout}s")
    except KeyboardInterrupt:
        print("\n[INTERRUPTED] Killing agent process tree...")
        raise
    finally:
        kill_tree(proc)
        stop_workspace_processes(workspace)
    return {"returncode": proc.returncode, "timed_out": timed_out}


def run_logged(cmd: list[str], run_dir: Path, timeout: int, label: str, *,
               cwd: Path | str | None = None, env: dict | None = None,
               workspace: Path | str | None = None) -> dict:
    """Run headless, streaming output live to stdout.txt/stderr.txt.

    Streams instead of buffering so progress can be observed (tail -f) while
    the test runs.
    """
    with open(run_dir / "stdout.txt", "wb") as out_f, \
         open(run_dir / "stderr.txt", "wb") as err_f:
        # Headless agents never need stdin; DEVNULL stops them waiting on it.
        proc = spawn(cmd, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                     stdout=out_f, stderr=err_f)
        return wait(proc, timeout, label, workspace)


def run_interactive(cmd: list[str], timeout: int, label: str, *,
                    cwd: Path | str | None = None, env: dict | None = None,
                    workspace: Path | str | None = None) -> dict:
    """Run an agent TUI attached to the terminal; output is not captured."""
    proc = spawn(cmd, cwd=cwd, env=env)
    return wait(proc, timeout, label, workspace)
