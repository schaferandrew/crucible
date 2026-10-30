import pytest

from crucible import plan as planner
from crucible import workspace
from crucible.taxonomy import (AREAS, CATEGORY_WEIGHTS, MODE_HARNESSES, TASK_STATUSES, TIERS, harness_problem,
                               mode_for, validate_area, validate_category, validate_status, validate_tier)


class TestModesAndAreas:
    def test_every_task_has_an_area_in_its_mode(self):
        for t in workspace.all_task_ids():
            validate_area(workspace.load_task(t))

    def test_area_must_match_mode(self):
        with pytest.raises(ValueError):
            validate_area({"id": "x", "needs_tools": False, "area": "coding"})

    def test_areas_belong_to_one_mode(self):
        assert not set(AREAS["chat"]) & set(AREAS["agentic"])

    def test_mode_decides_harness(self):
        chat, agentic = {"needs_tools": False}, {"needs_tools": True}
        assert mode_for(chat) == "chat" and mode_for(agentic) == "agentic"
        assert harness_problem(chat, "direct") is None
        assert harness_problem(chat, "opencode")
        assert harness_problem(agentic, "direct")
        assert harness_problem(agentic, "pi") is None


class TestSelection:
    def test_all_is_everything_not_retired(self):
        live = [t for t in workspace.all_task_ids() if workspace.load_task(t).get("status") != "retired"]
        assert sorted(planner.select([])) == sorted(live) == sorted(planner.select(["all"]))

    def test_chat_comes_before_agentic_and_tiers_easiest_first(self):
        prompts = planner.all_prompts()
        tests = planner.select(["all"])
        modes = [mode_for(prompts[t]) for t in tests]
        assert modes == sorted(modes, key=["chat", "agentic"].index)

    def test_filters_narrow(self):
        prompts = planner.all_prompts()
        tests = planner.select(["chat"], tier="spark")
        assert tests and all(mode_for(prompts[t]) == "chat" and prompts[t]["tier"] == "spark" for t in tests)
        assert set(planner.select(["writing"])) == {t for t, p in prompts.items()
                                                    if p.get("area") == "writing" and p.get("status") != "retired"}

    def test_slugs_and_old_ids_select_the_same_task(self, capsys):
        assert planner.select(["names-for-one-character"]) == ["names-for-one-character"]
        assert capsys.readouterr().out == ""
        # Earlier IDs, in any case and from any generation, resolve with a one-line notice
        assert planner.select(["writ-2b"]) == ["names-for-one-character"]
        assert "writ-2b is now names-for-one-character" in capsys.readouterr().out
        assert planner.select(["C11"]) == ["editorial-review-workflow"]  # C11 -> CODE-11 -> slug
        with pytest.raises(ValueError):
            planner.select(["nope"])

    def test_chat_steps_run_direct_whatever_the_agent(self):
        plan = planner.build("lmstudio/x", ["novel-character-names", "interest-cli-open-ended"], harness="pi")
        assert {s.task_id: s.harness for s in plan.steps} == {"novel-character-names": "direct",
                                                              "interest-cli-open-ended": "pi"}
        assert all(s.harness in MODE_HARNESSES[s.mode] for s in plan.steps)

    def test_tier_timeouts(self):
        tasks = ["proofread-customer-email", "novel-character-names", "editorial-review-workflow"]
        plan = planner.build("m/x", tasks)
        assert [s.timeout for s in plan.steps] == [300, 900, 1200]
        assert all(s.timeout == 1200 for s in planner.build("m/x", tasks[2:], timeout=3600).steps)
        assert planner.build("m/x", tasks[2:], timeout=3600, allow_long=True).steps[0].timeout == 3600
        assert all(s.timeout == 60 for s in planner.build("m/x", tasks, timeout=60).steps)

    def test_command_line_round_trips(self):
        plan = planner.build("lmstudio/x", planner.select(["chat"], tier="spark"))
        cmd = planner.command_line(plan, ["chat"], None, None, "spark", None, None, False)
        assert cmd == "crucible run chat --model lmstudio/x --tier spark"


class TestCategory:
    def test_known_categories_pass(self):
        for cat in CATEGORY_WEIGHTS:
            validate_category(cat)

    def test_unknown_category_raises(self):
        with pytest.raises(ValueError):
            validate_category("coding_build_typo")

    def test_weights_sum_to_one(self):
        assert abs(sum(CATEGORY_WEIGHTS.values()) - 1.0) < 1e-9


class TestTiersAndStatus:
    def test_tiers(self):
        assert TIERS == ("spark", "temper", "forge")
        for t in TIERS:
            validate_tier(t)
        with pytest.raises(ValueError):
            validate_tier("hard")

    def test_statuses(self):
        for s in TASK_STATUSES:
            validate_status(s)
        with pytest.raises(ValueError):
            validate_status("draft")
