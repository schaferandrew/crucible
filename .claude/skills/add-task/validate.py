"""Score answers against a task's checks and print a table: answer, expected score, actual score.

    uv run python .claude/skills/add-task/validate.py <task> <cases.yaml>

cases.yaml is a list of {name, expect, answer}; `expect` is the score out of 10 worked out by hand
(items passed / all items x 10), and `answer` the model's whole reply. For a task with `tool_calls`
checks (the calendar tasks), a case can add `tools`, the calls the agent made: a list of
[name, {args}] pairs. Caps (`cap_if_failed`) apply as in a run. Exits 1 if any case misses.
"""
import sys
from pathlib import Path

import yaml

from crucible import checks, workspace


def score(task: dict, text: str, tools: list | None = None) -> tuple[float, list[dict]]:
    calls = [{"name": name, "args": args} for name, args in tools] if tools is not None else None
    results = checks.run_checks(task, text, tool_calls=calls)
    earned = checks.criterion_scores(task, results)
    got = round(sum(earned.values()) / sum(item["max_score"] for item in task["rubric"]) * 10, 2)
    cap = checks._cap(task, earned)
    return (min(got, cap) if cap is not None else got), results


def main() -> None:
    task = workspace.load_task(workspace.resolve(sys.argv[1])[0])
    cases = yaml.safe_load(Path(sys.argv[2]).read_text(encoding="utf-8"))
    misses = 0
    print("| Answer | Expected | Actual |\n|---|---|---|")
    for case in cases:
        got, results = score(task, case.get("answer") or "", case.get("tools"))
        ok = abs(got - round(float(case["expect"]), 2)) < 0.01
        misses += not ok
        print(f"| {case['name']} | {float(case['expect']):.2f} | {got:.2f}{'' if ok else '  MISS'} |")
        if not ok:
            for r in results:
                print(f"    {r['id']}: {r['detail']}")
    print(f"\n{len(cases) - misses}/{len(cases)} as expected")
    sys.exit(1 if misses else 0)


if __name__ == "__main__":
    main()
