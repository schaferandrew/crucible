"""Score answers against a task's checks and print a table: answer, expected score, actual score.

    uv run python .claude/skills/add-task/validate.py <task> <cases.yaml>

cases.yaml is a list of {name, expect, answer}; `expect` is the score out of 10 worked out by hand
(items passed / all items x 10), and `answer` the model's whole reply. Exits 1 if any case misses.
"""
import sys
from pathlib import Path

import yaml

from crucible import checks, workspace


def score(task: dict, text: str) -> tuple[float, list[dict]]:
    results = checks.run_checks(task, text)
    earned = checks.criterion_scores(task, results)
    return round(sum(earned.values()) / sum(item["max_score"] for item in task["rubric"]) * 10, 2), results


def main() -> None:
    task = workspace.load_task(workspace.resolve(sys.argv[1])[0])
    cases = yaml.safe_load(Path(sys.argv[2]).read_text(encoding="utf-8"))
    misses = 0
    print("| Answer | Expected | Actual |\n|---|---|---|")
    for case in cases:
        got, results = score(task, case.get("answer") or "")
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
