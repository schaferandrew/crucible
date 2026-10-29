"""What `crucible run` prints: per-test header and result, suite summary."""
from __future__ import annotations

from pathlib import Path

RULE = "=" * 60


def print_header(title: str, rows: list[tuple[str, object]]) -> None:
    print(f"\n{RULE}\n{title}")
    for label, value in rows:
        print(f"{label}: {value}")
    print(f"{RULE}\n")


def _known(m: dict, *keys: str) -> bool:
    return all(m.get(k) is not None for k in keys)


def _tests(m: dict) -> str | None:
    counts = [f"{m[k]} {k.split('_')[1]}" for k in ("tests_passed", "tests_failed")
              if m.get(k) is not None]
    return "tests " + " / ".join(counts) if counts else None


def _ttft(m: dict) -> str | None:
    if not _known(m, "ttft_s"):
        return None
    avg = (f" (avg {m['ttft_avg_s']:.2f}s)"
           if (m.get("model_responses") or 0) > 1 and _known(m, "ttft_avg_s") else "")
    return f"TTFT {m['ttft_s']:.2f}s{avg}"


# Each returns its fragment of the metrics line, or None when not captured
METRIC_FORMATTERS = [
    lambda m: f"{m['tool_calls']} tool calls" if _known(m, "tool_calls") else None,
    _tests,
    lambda m: (f"tokens {m['tokens_in']} in / {m['tokens_out']} out"
               if _known(m, "tokens_in") else None),
    _ttft,
    lambda m: (f"{m.get('model_responses') or 0} model responses, "
               f"avg {m['response_time_avg_s']:.2f}s"
               if _known(m, "response_time_avg_s") else None),
    lambda m: (f"cost ${m['cost_usd']:.4f} ({m.get('cost_source')})"
               if _known(m, "cost_usd") else None),
]


def metrics_summary(metrics: dict) -> str:
    """One-line digest of the metrics that were captured."""
    return ", ".join(part for fmt in METRIC_FORMATTERS if (part := fmt(metrics)))


def print_result(meta: dict, run_dir: Path) -> None:
    """Closing block for one task: status, time, output dir, metrics, next step."""
    status = meta["outcome"]["harness_status"]
    print(f"\n[{status}] {meta['run_path']}")
    print(f"  Elapsed: {meta['elapsed_s']:.1f}s")
    print(f"  Output: {run_dir}")
    summary = metrics_summary(meta["metrics"])
    if summary:
        print(f"  Metrics: {summary}")
    if status != "COMPLETE":
        stderr = (run_dir / "stderr.txt").read_text(encoding="utf-8", errors="replace")
        last_line = (stderr.strip().splitlines() or [""])[-1]
        if last_line:
            print(f"  Error: {last_line[:200]}")
    # Deterministic tasks are scored on the spot; the rest wait for review, which isn't built yet
    if not status.startswith(("TIMEOUT", "ERROR")) and not (run_dir / "scores").is_dir():
        print("  Not scored automatically: this task still needs review (a future feature).")


def print_suite_summary(rows: list[tuple[str, str, float | None]]) -> None:
    """rows: (status, elapsed seconds or None, run path) per completed run."""
    print(f"\n{RULE}\nCompleted {len(rows)} run(s)")
    for status, elapsed, run_id in rows:
        took = f"{elapsed:>7.1f}s" if isinstance(elapsed, (int, float)) else "      ?s"
        print(f"  {status:<14} {took}  {run_id}")
    print(RULE)
