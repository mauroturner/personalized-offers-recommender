"""The figures of the test written by hand (U14), in the shape ``evaluation.criteria_of`` reads and the seal keeps: what each criterion compares with its limit is a number that is not the
point value of the same figure, so a criterion that tests the wrong quantity fails here."""

from __future__ import annotations

import copy
from typing import Any

LIMITS = {"c01_min_diff_low": 0.0, "c02_min_diff_low": -0.05, "c03_min_diff_low": 0.0, "c04_min_diff_low": 0.0, "c05_min_coverage": 0.10, "c06_max_abs_smd": 0.10,
          "c07_rejection_band": [0.031, 0.069], "c08_min_p": 0.05}


def test(diff: float, p: float, low: float, high: float) -> dict[str, float]:
    return {"diff": diff, "p": p, "ci_low": low, "ci_high": high}


def figures(**changes: Any) -> dict[str, Any]:
    """The hand case: C01, C02, C04 to C09 are met and C03 is not (the list loses 2 points to the customer's own repeats and its upper limit is below zero)."""
    base: dict[str, Any] = {
        "rounds": 18, "variants": 17, "censored_round": "R2011-12-05",
        "diffs": {
            "list_vs_b2": {"a_rate": 0.76, "b_rate": 0.54, "value": 0.22, "ci_low": 0.195, "ci_high": 0.245, "pairs": 12000},
            "list_vs_b3": {"a_rate": 0.77, "b_rate": 0.79, "value": -0.02, "ci_low": -0.03, "ci_high": -0.01, "pairs": 12000},
            "chosen_vs_b2_new": {"a_rate": 0.35, "b_rate": 0.31, "value": 0.04, "ci_low": 0.023, "ci_high": 0.056, "pairs": 12000},
        },
        "coverage_list": 0.158,
        "balance": {"max_abs_smd": 0.062, "covariate": "recency_days", "customers": 4326},
        "aa": {"m1": {"preregistered": test(0.0043, 0.088, -0.0005, 0.0092), "normal_raw": test(0.0071, 0.034, 0.0005, 0.0136), "normal_cuped": test(0.0043, 0.077, -0.0005, 0.0092)},
               "m2": {"preregistered": test(56.4, 0.313, -15.0, 127.9), "normal_raw": test(165.6, 0.002, 58.7, 272.6), "normal_cuped": test(56.4, 0.12, -15.0, 127.9)}},
        "calibration": {"seeds": 500, "permutations": 500, "alpha": 0.05, "rejection": {"m1_preregistered": 0.042, "m2_preregistered": 0.044, "m1_normal_raw": 0.026, "m2_normal_raw": 0.078,
                                                                                         "m1_normal_cuped": 0.042, "m2_normal_cuped": 0.024}},
        "crm": {"rounds": 18, "lists": 62000, "read_back_equal": 62000, "control_in_crm": 0, "control_in_csv": 0, "csv_files": 18, "repeat_round": "R2011-12-05", "repeat_created": 0, "repeat_contacts": 3461},
    }
    out = copy.deepcopy(base)
    for key, value in changes.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _merge(out[key], value)
        else:
            out[key] = value
    return out


def _merge(base: dict[str, Any], top: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in top.items():
        merged[key] = _merge(merged[key], value) if isinstance(value, dict) and isinstance(merged.get(key), dict) else value
    return merged
