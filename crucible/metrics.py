"""Raw metrics recorded in meta.json for every run (None = unknown, not zero)."""
from __future__ import annotations

import re
from pathlib import Path

from crucible.agents import Agent
from crucible.cost import run_cost
from crucible.session import count_tool_calls


def timing_summary(responses: list[dict]) -> dict:
    """Run-level latency metrics from per-model-response timings.

    responses: in call order, each {"ttft_s": float | None, "duration_s":
    float | None} where ttft_s is request sent -> first streamed token and
    duration_s is request sent -> response complete. Unknowns stay None so
    agents only report what they actually measured.
    """
    def avg(values):
        values = [v for v in values if v is not None]
        return round(sum(values) / len(values), 3) if values else None

    first = responses[0].get("ttft_s") if responses else None
    return {
        "model_responses": len(responses) or None,
        "ttft_s": round(first, 3) if first is not None else None,
        "ttft_avg_s": avg(r.get("ttft_s") for r in responses),
        "response_time_avg_s": avg(r.get("duration_s") for r in responses),
    }


def _test_counts(run_dir: Path) -> tuple[int | None, int | None]:
    """'N passed' / 'N failed' from the transcript (test output the agent ran)."""
    try:
        text = (run_dir / "stdout.txt").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None, None
    found = {word: re.search(rf"(\d+) {word}", text) for word in ("passed", "failed")}
    passed, failed = (int(m.group(1)) if m else None for m in found.values())
    if failed == 0 and passed is None:
        passed = 0
    return passed, failed


def extract_metrics(run_dir: Path, agent: Agent, billed_usd: float | None = None) -> dict:
    """Best-effort metrics from the run's artifacts and the agent's own records.

    billed_usd: provider-billed spend measured around the run (crucible.cost).
    """
    tests_passed, tests_failed = _test_counts(run_dir)
    session_path = run_dir / "session.json"
    # Output tokens include reasoning tokens where the agent reports them
    tokens_in, tokens_out = agent.token_usage(run_dir) or (None, None)
    return {
        "tests_passed": tests_passed,
        "tests_failed": tests_failed,
        "tool_calls": count_tool_calls(session_path) if session_path.exists() else None,
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        **timing_summary(agent.response_timings(run_dir)),
        **run_cost(agent.name, agent.cost_estimate(run_dir), billed_usd),
    }
