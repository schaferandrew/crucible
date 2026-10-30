"""pytest plugin for `runner: pytest` graders (see graders.py): writes every test's result as JSON.

Loaded with `-p pytest_report --crucible-report=FILE`. A test passes only if setup, call and teardown
all passed (a skip counts as not passed). Its group is the first line of its class's docstring, else the
class name, else the module name; collection errors are listed under `errors`.
"""
import json

import pytest

_tests: dict = {}
_errors: list = []


def pytest_addoption(parser):
    parser.addoption("--crucible-report", default=None, help="Write per-test results as JSON to this file")


def _group(item) -> str:
    cls = getattr(item, "cls", None)
    if cls is not None:
        doc = (cls.__doc__ or "").strip().splitlines()
        return doc[0].strip() if doc else cls.__name__
    module = item.module.__name__.rsplit(".", 1)[-1]
    return module[5:] if module.startswith("test_") else module


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    report = outcome.get_result()
    entry = _tests.setdefault(item.nodeid, {"file": item.path.name, "group": _group(item), "name": item.name,
                                            "passed": True, "error": None})
    if report.outcome != "passed" and entry["passed"]:
        entry["passed"] = False
        entry["error"] = (str(report.longrepr).strip().splitlines() or ["failed"])[-1][:300]


def pytest_collectreport(report):
    if report.failed:
        _errors.append(f"{report.nodeid}: {(str(report.longrepr).strip().splitlines() or ['collection failed'])[-1][:300]}")


def pytest_sessionfinish(session):
    path = session.config.getoption("--crucible-report")
    if path:
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"tests": list(_tests.values()), "errors": _errors}, f)
