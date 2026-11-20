"""The criteria and the texts that tell them (U14; AC23; plan section 16; decisions D16, D19, D20; risk item 1): each criterion is built from the quantity that its threshold compares and says it in its
own unit, each verdict names its own comparison, a tie never beats, a criterion that cannot be computed is not passed and says why, and no text names an effect of an offer. The figures are worked out by hand
(``tests.fixtures.figures``)."""

from __future__ import annotations

import dataclasses

import pytest

from personaloffers import texts
from personaloffers.evaluation import Criterion, criteria_of
from personaloffers.texts import es
from tests.fixtures.figures import LIMITS, figures


def by_id(criteria):
    return {c.criterion_id: c for c in criteria}


def got(**changes):
    return by_id(criteria_of(figures(**changes), LIMITS))


def test_each_criterion_uses_its_preregistered_quantity_and_unit():
    """AC23, the lesson B1 of project 07: the number that is compared with each limit is the one of requirements 8.1, in its unit; the same figure's point value or another denominator does not decide."""
    base = got()
    assert [c.criterion_id for c in base.values()] == [f"C{n:02d}" for n in range(1, 11)]
    # C01 to C04: the lower limit of the interval of the difference, in points; the point value is shown as context and never decides
    for cid, key, limit in (("C01", "list_vs_b2", 0.0), ("C02", "list_vs_b3", -0.05), ("C03", "list_vs_b3", 0.0), ("C04", "chosen_vs_b2_new", 0.0)):
        figs = figures()
        assert base[cid].tested_value == pytest.approx(figs["diffs"][key]["ci_low"]) and base[cid].ci_low == figs["diffs"][key]["ci_low"] and base[cid].ci_high == figs["diffs"][key]["ci_high"]
        assert base[cid].point_value == pytest.approx(figs["diffs"][key]["value"])
        above = got(diffs={key: {"value": limit - 0.5, "ci_low": limit + 0.01}})[cid]
        below = got(diffs={key: {"value": limit + 0.5, "ci_low": limit - 0.01}})[cid]
        assert above.passed is True and below.passed is False, f"{cid} is decided by the lower limit, whatever the point value says"
    assert base["C01"].tested_value_es == "19,5 puntos (límite inferior)" and base["C02"].tested_value_es == "−3,0 puntos (límite inferior)" and base["C04"].tested_value_es == "2,3 puntos (límite inferior)"
    assert [base[c].passed for c in ("C01", "C02", "C03", "C04")] == [True, True, False, True], "the list loses to the repeats by 3 points at the lower limit: C02 is met by the 5 points of slack and C03 is not"
    # C05: the mean coverage of the lists of the round, a fraction of the catalogue, at least 0.10
    assert base["C05"].tested_value == 0.158 and base["C05"].tested_value_es == "0,158 (cobertura media)"
    assert got(coverage_list=0.10)["C05"].passed is True and got(coverage_list=0.0999)["C05"].passed is False
    # C06: the largest absolute standardized difference of the five covariates, at most 0.10
    assert base["C06"].tested_value == 0.062 and base["C06"].tested_value_es == "0,062 (mayor diferencia estandarizada absoluta)"
    assert got(balance={"max_abs_smd": 0.10})["C06"].passed is True and got(balance={"max_abs_smd": 0.1001})["C06"].passed is False
    # C07: the two rejection rates of the preregistered test, both inside the band; the normal tests' rates beside them do not count
    assert base["C07"].tested_value is None and base["C07"].tested_value_es == "4,2 % y 4,4 % (tasas de rechazo de M1 y de M2)"
    for m1, m2, passed in ((0.031, 0.069, True), (0.0309, 0.05, False), (0.05, 0.0691, False), (0.05, 0.05, True)):
        assert got(calibration={"rejection": {"m1_preregistered": m1, "m2_preregistered": m2}})["C07"].passed is passed, (m1, m2)
    assert got(calibration={"rejection": {"m2_normal_raw": 0.104, "m1_normal_raw": 0.0}})["C07"].passed is True, "the unadjusted normal tests are C10's, not C07's"
    # C08: the two p of the preregistered test in the sealed A/A, both at least 0.05
    assert base["C08"].tested_value is None and base["C08"].tested_value_es == "p = 0,088 y p = 0,313 (M1 y M2)"
    for p1, p2, passed in ((0.05, 0.05, True), (0.0499, 0.5, False), (0.5, 0.0499, False)):
        assert got(aa={"m1": {"preregistered": {"p": p1}}, "m2": {"preregistered": {"p": p2}}})["C08"].passed is passed, (p1, p2)
    assert got(aa={"m2": {"normal_raw": {"p": 0.0001}}})["C08"].passed is True, "the normal test that is not the preregistered one does not decide"
    # C09: all that was delivered read back equal, nobody of the control group in the CRM or in the file, and nothing created by repeating the last round
    assert base["C09"].tested_value is None and base["C09"].passed is True
    assert base["C09"].tested_value_es == "62.000 de 62.000 listas leídas de vuelta iguales; 0 del control en el CRM o en el CSV; 0 nuevas al repetir la última ronda"
    for change in ({"read_back_equal": 61999}, {"control_in_crm": 1}, {"control_in_csv": 1}, {"repeat_created": 1}):
        assert got(crm=change)["C09"].passed is False, change
    assert base["C10"].passed is None and base["C10"].tested_value is None and base["C10"].tested_value_es == "sin umbral"


def test_a_tie_with_the_limit_does_not_beat_it_and_a_limit_that_is_reached_passes_where_the_criterion_says_at_least_or_at_most():
    tie = got(diffs={"list_vs_b2": {"ci_low": 0.0}, "list_vs_b3": {"ci_low": -0.05}, "chosen_vs_b2_new": {"ci_low": 0.0}})
    assert tie["C01"].passed is False and tie["C02"].passed is False and tie["C03"].passed is False and tie["C04"].passed is False, "greater than, never equal"
    reached = got(coverage_list=0.10, balance={"max_abs_smd": 0.10}, aa={"m1": {"preregistered": {"p": 0.05}}})
    assert reached["C05"].passed is True and reached["C06"].passed is True and reached["C08"].passed is True, "at least, at most and at least"


def test_a_criterion_that_cannot_be_computed_is_not_passed_and_says_why():
    empty = by_id(criteria_of({"variants": 0}, LIMITS))
    for cid in [f"C{n:02d}" for n in range(1, 10)]:
        assert empty[cid].passed is False and empty[cid].tested_value is None and empty[cid].ci_low is None and "no se puede calcular" in empty[cid].verdict_es, cid
        assert empty[cid].tested_value_es == "sin dato", cid
    assert empty["C10"].passed is None
    no_files = got(crm={"csv_files": 17})["C09"]
    assert no_files.passed is False and "no se puede calcular" in no_files.verdict_es and "17 de 18" in no_files.verdict_es, "a file of a round that is missing is not a file without the control group"
    none_delivered = got(crm={"lists": 0, "read_back_equal": 0})["C09"]
    assert none_delivered.passed is False and "no se puede calcular" in none_delivered.verdict_es, "nothing was delivered: nothing to prove, not a pass"
    no_p = got(aa={"m1": {"preregistered": {"p": None}}})["C08"]
    assert no_p.passed is False and "no se puede calcular" in no_p.verdict_es
    nan = got(diffs={"list_vs_b2": {"ci_low": float("nan")}})["C01"]
    assert nan.passed is False and "no se puede calcular" in nan.verdict_es, "a limit that is not a number does not pass"


def test_each_verdict_names_its_own_comparison_and_its_own_unit():
    c = got()
    assert c["C01"].verdict_es == ("En 18 rondas semanales, la lista acertó al menos un producto en el 76,0 % de los clientes que compraron y lo más vendido (B2) en el 54,0 %; "
                                  "el límite inferior de la diferencia es 19,5 puntos y el umbral era 0,0 puntos.")
    assert "recompra propia (B3)" in c["C02"].verdict_es and "−3,0 puntos" in c["C02"].verdict_es and "−5,0 puntos" in c["C02"].verdict_es and "77,0 %" in c["C02"].verdict_es and "79,0 %" in c["C02"].verdict_es
    assert c["C03"].verdict_es.endswith("No se cumple.") and "recompra propia (B3)" in c["C03"].verdict_es and "mayor que 0,0 puntos" in c["C03"].verdict_es
    assert "nunca había comprado" in c["C04"].verdict_es and "modelo elegido" in c["C04"].verdict_es and "35,0 %" in c["C04"].verdict_es and "31,0 %" in c["C04"].verdict_es and "2,3 puntos" in c["C04"].verdict_es
    assert "0,158" in c["C05"].verdict_es and "365 días" in c["C05"].verdict_es and "0,10" in c["C05"].verdict_es
    assert "0,062" in c["C06"].verdict_es and "recencia" in c["C06"].verdict_es and "4.326" in c["C06"].verdict_es and "0,10" in c["C06"].verdict_es
    assert "500 sorteos" in c["C07"].verdict_es and "4,2 %" in c["C07"].verdict_es and "4,4 %" in c["C07"].verdict_es and "3,1 %" in c["C07"].verdict_es and "6,9 %" in c["C07"].verdict_es
    assert "p = 0,088" in c["C08"].verdict_es and "p = 0,313" in c["C08"].verdict_es and "0,05" in c["C08"].verdict_es
    assert "62.000 de 62.000" in c["C09"].verdict_es and "R2011-12-05" in c["C09"].verdict_es and "3.461 contactos" in c["C09"].verdict_es
    assert "informativo" in c["C10"].verdict_es.lower() and "17 variantes" in c["C10"].verdict_es
    passed = [x for x in c.values() if x.passed is True]
    assert passed and not any("No se cumple" in x.verdict_es for x in passed), "the verdict of a criterion that is met does not say it was not"
    assert [x.criterion_id for x in c.values() if x.passed is False] == ["C03"] and all("No se cumple." in x.verdict_es for x in c.values() if x.passed is False)


def test_the_thresholds_are_written_with_the_sealed_limits_and_say_what_they_compare():
    thresholds = texts.thresholds_from(LIMITS)
    assert thresholds["C01"] == "límite inferior del intervalo del 95 % de hit@10(lista) − hit@10(B2) > 0,0 puntos"
    assert thresholds["C02"] == "límite inferior del intervalo del 95 % de hit@10(lista) − hit@10(B3) > −5,0 puntos"
    assert thresholds["C03"].endswith("> 0,0 puntos") and thresholds["C04"].startswith("límite inferior del intervalo del 95 % de hit@10 solo nuevos(modelo elegido)")
    assert thresholds["C05"] == "cobertura media de las listas de la ronda ≥ 0,10" and thresholds["C06"] == "mayor diferencia estandarizada absoluta de las cinco covariables ≤ 0,10"
    assert "entre 3,1 % y 6,9 %" in thresholds["C07"] and thresholds["C08"].endswith("p ≥ 0,05") and thresholds["C10"] == "sin umbral"
    changed = texts.thresholds_from({**LIMITS, "c05_min_coverage": 0.2, "c07_rejection_band": [0.04, 0.06]})
    assert changed["C05"].endswith("≥ 0,20") and "entre 4,0 % y 6,0 %" in changed["C07"]
    assert by_id(criteria_of(figures(), LIMITS))["C02"].threshold_es == thresholds["C02"]


def test_what_the_research_and_the_planner_saw_is_the_table_of_requirements():
    seen = {cid: (t.seen_by_research, t.seen_by_planner) for cid, t in texts.CRITERIA.items()}
    assert seen == {"C01": ("sí", "sí"), "C02": ("en parte", "sí"), "C03": ("en parte", "sí"), "C04": ("sí", "sí"), "C05": ("sí", "sí"), "C06": ("sí", "sí"), "C07": ("sí", "sí"), "C08": ("sí", "sí"),
                    "C09": ("no", "no"), "C10": ("en parte", "en parte")}
    c = got()
    assert (c["C09"].seen_by_research, c["C09"].seen_by_planner) == ("no", "no") and c["C02"].seen_by_research == "en parte"


def test_the_numbers_of_a_text_are_written_the_way_spanish_does():
    assert es(0.931, 1, percent=True) == "93,1 %" and es(1234.5, 2) == "1.234,50" and es(-1.8, 1) == "−1,8" and es(None) == "sin dato" and es(float("nan")) == "sin dato"
    assert es(-0.0001, 2) == "0,00", "a number that rounds to zero has no minus sign"
    assert es(0.02, 0, percent=True) == "2 %" and es(0.0095, 2, percent=True) == "0,95 %"
    assert texts.pct(0.5) == "50 %" and texts.pct(0.0095) == "0,95 %" and texts.pct(0.1234) == "12,3 %" and texts.pct(None) == "sin dato"
    assert texts.points(0.195) == "19,5 puntos" and texts.points(-0.03) == "−3,0 puntos" and texts.points(None) == "sin dato"


def test_no_threshold_verdict_or_name_of_the_criteria_names_an_effect_of_an_offer():
    """D16: ``effect``, ``uplift`` and ``lift`` are banned as names; the texts that tell the criteria never say the word of an offer's effect (C08 is shown as «no marca una diferencia que no existe»)."""
    criteria = list(got().values()) + list(by_id(criteria_of({"variants": 0}, LIMITS)).values())
    for criterion in criteria:
        assert not {f.name for f in dataclasses.fields(Criterion)} & {"effect", "uplift", "lift"}
        for text in (criterion.name_es, criterion.threshold_es, criterion.verdict_es, criterion.tested_value_es):
            assert "lift" not in text.lower() and "aumento" not in text.lower() and "uplift" not in text.lower(), text
            assert "efecto" not in text.lower().replace("menor efecto detectable", ""), text
    assert "efecto" not in "".join(t.threshold_es for t in texts.CRITERIA.values()).lower()


def _c05(sealed: float, denominator: float, definition: float) -> dict:
    return {"rounds": 18, "sealed": {"value": sealed}, "preregistered": {"value": sealed, "threshold": 0.10, "passed": True}, "p01_denominator": {"value": denominator}, "p01_definition": {"value": definition}}


def test_the_p01_sentence_says_comparable_only_within_the_stated_tolerance_and_the_numerator_only_when_it_is():
    """N2 of the recheck: the plan's validation figure (0.158) is fixed text; whether the test's figure is comparable with it is decided by the computed ``p01_definition`` figure and a stated tolerance, and «sobre todo
    el numerador» only when the numerator explains more of the distance than the denominator does."""
    tolerance = texts.PLAN_VALIDATION_TOLERANCE
    real = texts.c05_p01_line(_c05(0.5586, 0.4656, 0.1527))                       # the real figures (D49)
    assert "comparable con el 0,158" in real and "sobre todo el numerador" in real
    edge = texts.c05_p01_line(_c05(0.5586, 0.4656, texts.PLAN_VALIDATION_C05 + tolerance))
    assert "comparable con el 0,158" in edge, "the tolerance is inclusive"
    far = texts.c05_p01_line(_c05(0.60, 0.50, 0.359))
    assert "comparable" not in far and "0,359" in far and "0,158" in far and "sobre todo el numerador" not in far
    assert "0,01" in far and "0,201" in far, "the tolerance and how far apart the two figures are"
    assert "0,100" in far and "0,141" in far, "what the denominator and the numerator explain of the distance to the `p01` figure"
    denominator = texts.c05_p01_line(_c05(0.60, 0.20, 0.159))                  # near the plan's figure, but the denominator explains more than the numerator
    assert "comparable con el 0,158" in denominator and "sobre todo el numerador" not in denominator and "sobre todo el denominador" in denominator
