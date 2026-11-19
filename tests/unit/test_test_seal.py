"""The test part of the seal (U14; RF18, AC16, AC24; decision D21; risk item 1): the test is evaluated once. What evaluating means is decided before anything is read (the first one is the one that is sealed,
a repetition must reproduce it, another configuration after the seal is kept apart and one before it is refused), the test part is added to a seal whose launch part is kept exactly as it was, and what a repetition
does not reproduce (the key of its run and the hour of its delivery) is the only thing that may differ."""

from __future__ import annotations

import copy
import json

import pytest

from personaloffers import registry
from personaloffers.registry import EvaluationRefusedError, SealError, SealMismatchError
from tests.unit.test_seal import launch_part, put

TEST_PART = {
    "config_sha256": "", "run_key": "run-9", "as_of": "2011-04-23 00:00:00", "criteria": [{"id": "C01", "tested_value": 0.1950001, "point_value": 0.22, "ci_low": 0.195, "ci_high": 0.245, "passed": True, "verdict_es": "x"}],
    "metrics": {"rounds": 3, "diffs": {"list_vs_b2": {"ci_low": 0.1950001}}, "coverage_list": 0.158}, "operation": {"rounds": 3, "pairs": 130, "customers": 105},
}


def make_part(view, **changes):
    return {**copy.deepcopy(TEST_PART), "config_sha256": registry.config_fingerprint(view), **changes}


@pytest.fixture
def sealed(tmp_path, quick_view):
    seal = tmp_path / "reports" / "model_seal.json"
    registry.write_launch_seal(seal, launch_part(quick_view))
    return seal


def test_a_seal_that_is_not_there_refuses_the_evaluation_and_says_to_seal_first(tmp_path, quick_view):
    with pytest.raises(EvaluationRefusedError, match="no hay sello"):
        registry.check_test_evaluation(tmp_path / "model_seal.json", quick_view)
    assert issubclass(EvaluationRefusedError, SealError) and list(tmp_path.iterdir()) == []


def test_the_first_evaluation_with_the_sealed_configuration_is_the_one_that_is_sealed(sealed, quick_view):
    assert registry.check_test_evaluation(sealed, quick_view) == "first"


def test_another_configuration_before_the_test_part_is_refused_naming_the_keys_that_differ_and_writes_nothing(sealed, quick_view):
    before = sealed.read_bytes()
    other = put(quick_view, "criteria.c01_min_diff_low", 0.01)
    with pytest.raises(EvaluationRefusedError, match="criteria.c01_min_diff_low") as caught:
        registry.check_test_evaluation(sealed, other)
    assert "R7" in str(caught.value) and "D21" in str(caught.value) and sealed.read_bytes() == before
    two = put(put(quick_view, "experiment.alpha", 0.1), "holdout.share", 0.25)
    with pytest.raises(EvaluationRefusedError) as caught:
        registry.check_test_evaluation(sealed, two)
    assert "experiment.alpha" in str(caught.value) and "holdout.share" in str(caught.value) and "criteria.c01" not in str(caught.value)


def test_the_test_part_is_added_once_and_the_launch_part_is_kept_exactly_as_it_was(sealed, quick_view):
    document = json.loads(sealed.read_text(encoding="utf-8"))
    part = make_part(quick_view)
    assert registry.write_test_seal(sealed, part) == "written"
    after = json.loads(sealed.read_text(encoding="utf-8"))
    assert after["launch"] == document["launch"] and after["test"] == part and set(after) == {"version", "launch", "test"} and after["version"] == 1
    text = sealed.read_bytes()
    assert text.endswith(b"\n") and text == (json.dumps(after, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")
    assert registry.check_test_evaluation(sealed, quick_view) == "repeat"
    assert registry.seal_state(sealed, registry.config_fingerprint(quick_view)) == "match"
    assert [p.name for p in sealed.parent.iterdir()] == ["model_seal.json"], "no temporary file is left"


def test_a_repetition_that_reproduces_the_sealed_values_to_six_decimals_changes_nothing_and_the_run_key_and_the_hour_are_not_compared(sealed, quick_view):
    registry.write_test_seal(sealed, make_part(quick_view))
    written = sealed.read_bytes()
    again = make_part(quick_view, run_key="run-10", as_of="2011-04-24 00:00:00", criteria=[{**TEST_PART["criteria"][0], "tested_value": 0.1950004}])
    assert registry.write_test_seal(sealed, again) == "unchanged" and sealed.read_bytes() == written
    assert json.loads(written.decode("utf-8"))["test"]["run_key"] == "run-9", "the first one stays"


def test_a_repetition_that_does_not_reproduce_a_sealed_value_is_refused_and_names_each_value(sealed, quick_view):
    registry.write_test_seal(sealed, make_part(quick_view))
    written = sealed.read_bytes()
    different = make_part(quick_view)
    different["metrics"]["coverage_list"] = 0.159
    different["metrics"]["diffs"]["list_vs_b2"]["ci_low"] = 0.2
    with pytest.raises(SealMismatchError, match="R7") as caught:
        registry.write_test_seal(sealed, different)
    message = str(caught.value)
    assert "metrics.coverage_list" in message and "metrics.diffs.list_vs_b2.ci_low" in message and "0.158" in message and "0.159" in message
    assert sealed.read_bytes() == written


def test_a_test_evaluated_with_another_configuration_after_the_seal_is_post_seal_and_the_seal_stays(sealed, quick_view):
    registry.write_test_seal(sealed, make_part(quick_view))
    written = sealed.read_bytes()
    other = put(quick_view, "criteria.c05_min_coverage", 0.5)
    assert registry.check_test_evaluation(sealed, other) == "post_seal"
    assert registry.write_test_seal(sealed, make_part(other)) == "post_seal" and sealed.read_bytes() == written


def test_a_test_part_without_its_keys_or_with_a_value_that_is_not_a_finite_number_is_refused_before_writing(sealed, quick_view):
    before = sealed.read_bytes()
    good = make_part(quick_view)
    for broken in ({k: v for k, v in good.items() if k != "metrics"}, {**good, "extra": 1}, {**good, "config_sha256": "short"}, {**good, "config_sha256": "G" * 64}, {**good, "run_key": ""},
                   {**good, "metrics": {"x": float("nan")}}, {**good, "metrics": {"x": float("inf")}}, {**good, "metrics": {"x": object()}}):
        with pytest.raises(SealError):
            registry.write_test_seal(sealed, broken)
    assert sealed.read_bytes() == before


def test_a_test_part_cannot_be_written_without_a_launch_part_and_a_seal_that_cannot_be_read_is_an_error(tmp_path, quick_view):
    with pytest.raises(SealError, match="no hay sello"):
        registry.write_test_seal(tmp_path / "model_seal.json", make_part(quick_view))
    broken = tmp_path / "broken.json"
    broken.write_text("not json", encoding="utf-8")
    with pytest.raises(SealError):
        registry.write_test_seal(broken, make_part(quick_view))
    with pytest.raises(SealError):
        registry.check_test_evaluation(broken, quick_view)


def test_the_diff_of_two_configurations_names_the_keys_by_section_and_name():
    assert registry.differing_keys({"a": {"x": 1, "y": [1, 2]}, "b": 2}, {"a": {"x": 1, "y": [1, 3]}, "b": 2, "c": 3}) == ["a.y.1", "c"]
    assert registry.differing_keys({"a": 1}, {"a": 1}) == []


def test_the_six_decimal_rule_rounds_every_float_inside_a_mapping_a_list_or_a_tuple_and_touches_nothing_else():
    """L128's warning: a seal is compared at six decimals by one rule, whoever asks (the repetition of the test and the rebuild of the criteria)."""
    value = {"a": 0.1234567891, "b": [1, 2.0000004, (3.0000006, {"c": 0.9999996})], "d": "0.1234567891", "e": None, "f": True, "g": 7}
    assert registry.rounded(value) == {"a": 0.123457, "b": [1, 2.0, [3.000001, {"c": 1.0}]], "d": "0.1234567891", "e": None, "f": True, "g": 7}
    assert registry.rounded(0.0000004) == 0.0 and registry.rounded(-0.0000006) == -0.000001 and registry.rounded("x") == "x" and registry.rounded([]) == [] and registry.rounded({}) == {}
    assert value["a"] == 0.1234567891 and value["b"][1] == 2.0000004, "the input is not changed"


def test_a_repetition_that_differs_by_one_millionth_is_a_different_value_and_by_less_than_half_of_it_is_the_same_one(sealed, quick_view):
    registry.write_test_seal(sealed, make_part(quick_view, criteria=[{**TEST_PART["criteria"][0], "point_value": 0.22}]))
    written = sealed.read_bytes()
    same = make_part(quick_view, run_key="run-10", criteria=[{**TEST_PART["criteria"][0], "point_value": 0.2200004}])
    assert registry.write_test_seal(sealed, same) == "unchanged" and sealed.read_bytes() == written
    other = make_part(quick_view, run_key="run-11", criteria=[{**TEST_PART["criteria"][0], "point_value": 0.2200006}])
    with pytest.raises(SealMismatchError, match="criteria.0.point_value") as caught:
        registry.write_test_seal(sealed, other)
    assert "R7" in str(caught.value) and sealed.read_bytes() == written
