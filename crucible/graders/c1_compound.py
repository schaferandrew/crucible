#!/usr/bin/env python3
"""C1 / C1b — Compound interest calculator grader.

Verifies that a generated workspace contains: passing tests, correct compound
interest math, input validation code, and a README with usage examples.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path


def _find_python_package(workspace: Path) -> Path | None:
    """Find the calculator package/importable module in the workspace."""
    candidates = ["interest_calc", "interest_calculator", "calculator",
                 "interestcalc", "compound_interest"]
    for name in candidates:
        pkg_dir = workspace / name
        if pkg_dir.is_dir():
            return pkg_dir
    for py_file in workspace.rglob("*.py"):
        if py_file.stem in ("calculations", "calc", "interest", "main", "__init__"):
            return py_file.parent if py_file.stem != "main" else workspace
    return workspace if (workspace / "pyproject.toml").exists() else None


def _run_workspace_tests(workspace: Path) -> tuple[bool, int | None]:
    """Run pytest in the workspace. Returns (all_passed, num_tests)."""
    if not (workspace / "pytest.ini").exists() and not (workspace / "pyproject.toml").exists():
        pass
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", "--no-header", "-p", "no:cacheprovider"],
            cwd=workspace, capture_output=True, text=True, timeout=60,
        )
        m = re.search(r'(\d+)\s+passed', result.stdout + result.stderr)
        passed = int(m.group(1)) if m else None
        all_passed = result.returncode == 0
        return all_passed, passed
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False, None


def _verify_compound_math(workspace: Path) -> bool:
    """Import the calculator and verify the compound interest formula against known values."""
    try:
        import importlib
        import types

        sys.path.insert(0, str(workspace))
        try:
            calc_module = None
            pkg = _find_python_package(workspace)
            if pkg and pkg.is_dir():
                for init_file in pkg.glob("__init__.py"):
                    try:
                        mod = importlib.import_module(pkg.name)
                        calc_module = mod
                        break
                    except (ImportError, ModuleNotFoundError):
                        pass

            if calc_module is None:
                for module_name in ["interest_calc.calculations", "calculator", "interest_calc"]:
                    try:
                        calc_module = importlib.import_module(module_name)
                        break
                    except (ImportError, ModuleNotFoundError):
                        continue

            if calc_module is None:
                for pkg_name in ["interest_calc", "interest_calculator"]:
                    try:
                        calc_module = importlib.import_module(pkg_name)
                        break
                    except (ImportError, ModuleNotFoundError):
                        continue

            if calc_module is None:
                return False

            compound_fn = getattr(calc_module, "compound_interest", None)
            if compound_fn is None:
                for attr in dir(calc_module):
                    sub = getattr(calc_module, attr)
                    if isinstance(sub, types.ModuleType):
                        compound_fn = getattr(sub, "compound_interest", None)
                        if compound_fn:
                            break

            if compound_fn is None:
                return False

            # Verify: P=1000, r=5%, t=2, annually → 1102.50
            try:
                result = compound_fn(1000, 5, 2, 1)
                if hasattr(result, "future_value"):
                    return abs(result.future_value - 1102.50) < 0.01
                elif isinstance(result, dict) and "future_value" in result:
                    return abs(result["future_value"] - 1102.50) < 0.01
                elif isinstance(result, (int, float)):
                    return abs(result - 1102.50) < 0.01
            except TypeError:
                from enum import Enum

                class Freq(Enum):
                    ANNUALLY = 1

                try:
                    result = compound_fn(principal=1000, annual_rate=5, time_years=2,
                                         compounding_frequency=Freq.ANNUALLY)
                    if hasattr(result, "future_value"):
                        return abs(result.future_value - 1102.50) < 0.01
                except Exception:
                    return False
            return False

        finally:
            if str(workspace) in sys.path:
                sys.path.remove(str(workspace))
            for mod_name in list(sys.modules):
                if mod_name.startswith(("interest_calc", "interest_calculator", "calculator")):
                    del sys.modules[mod_name]
    except Exception:
        return False


def _check_readme(workspace: Path) -> bool:
    """Check that a README with command examples exists."""
    readme = workspace / "README.md"
    if not readme.exists():
        return False
    content = readme.read_text(encoding="utf-8", errors="replace").lower()
    return "usage" in content or "example" in content or "python" in content


def _check_validation(workspace: Path) -> bool:
    """Check that input validation code exists in the workspace."""
    for py_file in workspace.rglob("*.py"):
        try:
            content = py_file.read_text(encoding="utf-8", errors="replace").lower()
            if any(kw in content for kw in ["invalid", "negative", "error", "raise",
                                            "validate", "sys.exit"]):
                return True
        except OSError:
            continue
    return False


# --------------------------------------------------------------------------
# Public grader entry point
# --------------------------------------------------------------------------

def grade(prompt_def: dict, run_dir: Path, model_output: str) -> dict[str, float]:
    """C1: Interest calculator — verify math, tests, docs, validation."""
    rubric = {item["criterion"]: item["max_score"]
              for item in prompt_def.get("rubric", [])}
    scores = {}

    workspace = run_dir / "workspace"
    if not workspace.is_dir():
        # Direct-mode run: no workspace
        scores["Tests"] = 0.0
        scores["Correct financial math"] = 0.0
        scores["Input validation"] = 0.0
        scores["UX / docs"] = 0.0
        return scores

    # Tests
    all_pass, num_passed = _run_workspace_tests(workspace)
    if all_pass and num_passed is not None and num_passed > 0:
        scores["Tests"] = float(rubric.get("Tests", 2))
    else:
        scores["Tests"] = 0.0

    # Correct financial math
    if _verify_compound_math(workspace):
        scores["Correct financial math"] = float(rubric.get("Correct financial math", 3))
    else:
        scores["Correct financial math"] = 0.0

    # Input validation
    if _check_validation(workspace):
        scores["Input validation"] = float(rubric.get("Input validation", 2))
    else:
        scores["Input validation"] = 0.0

    # UX / docs
    if _check_readme(workspace):
        scores["UX / docs"] = float(rubric.get("UX / docs", 1))
    else:
        scores["UX / docs"] = 0.0

    return scores
