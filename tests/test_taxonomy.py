import pytest

from crucible.taxonomy import CATEGORY_WEIGHTS, derive_suites, suite_for, validate_category


class TestSuiteFor:
    def test_prefixes_map_to_suites(self):
        assert suite_for("C1") == "coding"
        assert suite_for("C1b") == "coding"
        assert suite_for("W2b") == "writing"
        assert suite_for("E4") == "everyday"
        assert suite_for("G3") == "reasoning"
        assert suite_for("H1") == "home"

    def test_lowercase_prefix_accepted(self):
        assert suite_for("c1") == "coding"

    def test_unknown_prefix_raises(self):
        with pytest.raises(ValueError):
            suite_for("X9")


class TestValidateCategory:
    def test_known_categories_pass(self):
        for cat in CATEGORY_WEIGHTS:
            validate_category(cat)

    def test_unknown_category_raises(self):
        with pytest.raises(ValueError):
            validate_category("coding_build_typo")

    def test_weights_sum_to_one(self):
        assert abs(sum(CATEGORY_WEIGHTS.values()) - 1.0) < 1e-9


class TestDeriveSuites:
    def test_groups_by_prefix_sorted(self):
        suites = derive_suites(["C2", "C1b", "E1", "C1", "W1a"])
        assert suites == {
            "coding": ["C1", "C1b", "C2"],
            "everyday": ["E1"],
            "writing": ["W1a"],
        }

    def test_everyday_includes_e4(self):
        suites = derive_suites(["E1", "E2", "E3", "E4"])
        assert suites["everyday"] == ["E1", "E2", "E3", "E4"]

    def test_empty(self):
        assert derive_suites([]) == {}
