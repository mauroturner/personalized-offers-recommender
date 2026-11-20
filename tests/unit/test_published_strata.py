"""The scan of the published files for a stratum's size (D30, D48; the suggestion on ``tests/e2e/test_real.py`` of the native review of c5): it matches the strata by **field or key**, never by the value of an
offer and control pair, so an aggregate that happens to hold the same two numbers as a stratum is not a stratum, and a real leak of the strata still fails it."""

from __future__ import annotations

from tests.fixtures.published import stratum_leaks

STRATA = {"0": {"control": 31, "offer": 126}, "1": {"control": 2, "offer": 8}, "2": {"control": 72, "offer": 290}, "3": {"control": 7, "offer": 28}}


def test_an_aggregate_pair_equal_to_a_stratums_is_not_a_stratum():
    coincidence = {"holdout": {"offer": 126, "control": 31}, "round": {"offer": 8, "control": 2}, "by_week": [{"offer": 290, "control": 72}]}
    assert stratum_leaks(coincidence, "site", STRATA) == []


def test_a_dictionary_keyed_by_the_strata_ids_with_their_sizes_is_a_leak():
    leak = {"holdout": {"sizes": {"0": {"offer": 126, "control": 31}, "2": {"offer": 290, "control": 72}}}}
    found = stratum_leaks(leak, "site", STRATA)
    assert len(found) == 2 and all("stratum" in item for item in found)


def test_a_key_that_is_a_strata_id_with_another_pair_is_not_a_leak():
    assert stratum_leaks({"0": {"offer": 5000, "control": 1000}}, "site", STRATA) == []


def test_a_list_that_holds_every_stratum_pair_without_ids_is_a_leak():
    rows = {"cells": [{"offer": v["offer"], "control": v["control"], "week": i} for i, v in enumerate(STRATA.values())]}
    assert len(stratum_leaks(rows, "site", STRATA)) == 1


def test_a_list_that_holds_only_some_of_the_pairs_is_a_coincidence():
    assert stratum_leaks({"cells": [{"offer": 126, "control": 31}, {"offer": 8, "control": 2}]}, "site", STRATA) == []


def test_a_field_named_after_the_strata_is_a_leak_except_the_count_the_control_file_allows():
    assert stratum_leaks({"a": {"stratum_id": 3}}, "site", STRATA) == ["site/a/stratum_id: a field of the strata"]
    assert stratum_leaks({"holdout": {"strata": 18}}, "control", STRATA, allowed={"control/holdout/strata"}) == []
