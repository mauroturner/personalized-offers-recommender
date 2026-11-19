"""The closing evaluation (U14; RF18, AC21, AC22, AC23, AC25; C01-C10; risk item 1: the test is evaluated once; decisions D08, D15, D16, D19, D21): the figures are what was issued joined to what was bought, recomputed
here by hand with nothing of the package; the evaluation is stored once and sealed once, a repetition reproduces it, and the A/A, the balance and the evidence of the CRM are the ones of the replay."""

from __future__ import annotations

import dataclasses
import hashlib
import json
import math
import re
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pytest

from personaloffers import evaluation, registry, reporting
from personaloffers.crm.client import ContactOffers, Offer
from personaloffers.evaluation import EvaluationError
from personaloffers.registry import SealMismatchError
from tests.fixtures.worlds import copy_world, crm_client

TEST_ROUNDS = ["R2011-03-28", "R2011-04-04", "R2011-04-11"]
CENSORED = "R2011-04-18"
RUN = reporting.RunMeta("run-6", datetime(2011, 4, 24))


@pytest.fixture
def world(evaluated, workbook, quick_cfg, tmp_path):
    """A copy of the folder in which the replay was delivered and evaluated."""
    made = copy_world(evaluated.root, workbook, quick_cfg, tmp_path / "evaluated")
    yield made
    made.conn.close()


@pytest.fixture
def before(delivered, workbook, quick_cfg, tmp_path):
    """A copy of the delivered replay that was not evaluated."""
    made = copy_world(delivered.root, workbook, quick_cfg, tmp_path / "delivered")
    yield made
    made.conn.close()


def tables_digest(conn) -> str:
    digest = hashlib.sha256()
    for table in reporting.TABLES:
        digest.update(repr(conn.execute(f"SELECT * FROM {table} ORDER BY 1, 2, 3, 4, 5").fetchall()).encode("utf-8"))
    return digest.hexdigest()


def file_digest(path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def evidence_of(world):
    return evaluation.crm_evidence(world.conn, crm_client(world), private_dir=world.cfg.paths.private_dir, batch_size=world.cfg.crm.batch_size)


# --- what is evaluated is what was issued, by hand --------------------------------------------------------------------------------------------------------


def hand_pairs(conn, round_id):
    """The evaluated pairs of a round by hand: the customers of its base that bought a purchase line in its week, with the set of products they bought."""
    monday = datetime.strptime(round_id[1:], "%Y-%m-%d")
    end = monday + timedelta(days=5 if round_id == CENSORED else 7)
    bought: dict[int, set[str]] = {}
    base = {r[0] for r in conn.execute("SELECT customer_id FROM contact_base WHERE round_id = ?", (round_id,))}
    for customer, code in conn.execute("SELECT customer_id, stock_code FROM lines WHERE role = 'purchase' AND customer_id IS NOT NULL AND invoice_date >= ? AND invoice_date < ?",
                                       (monday.strftime("%Y-%m-%d %H:%M:%S"), end.strftime("%Y-%m-%d %H:%M:%S"))):
        if customer in base:
            bought.setdefault(customer, set()).add(code)
    return bought


def hand_metrics(listed: list[str], bought: set[str]) -> tuple[int, float, float, float]:
    """hit, recall, precision and NDCG of one list against the products that were bought, as the definitions of requirements 8.1 say."""
    hits = [1 if code in bought else 0 for code in listed]
    gain = sum(h / math.log2(rank + 1) for rank, h in enumerate(hits, start=1))
    ideal = sum(1 / math.log2(rank + 1) for rank in range(1, min(len(bought), len(listed)) + 1))
    return int(any(hits)), sum(hits) / len(bought), sum(hits) / len(listed), gain / ideal


def test_every_pair_of_the_test_has_the_four_metrics_of_the_list_and_of_each_baseline_as_the_definitions_say_by_hand(world):
    """AC21, AC25: for every method and variant, each pair's hit, recall, precision and NDCG are recomputed here from ``offer_lists`` or ``baseline_lists`` and from the lines, with nothing of the package."""
    checked = 0
    stored = {}
    for row in world.conn.execute("SELECT round_id, customer_id, method, variant, hit, recall, precision, ndcg, test_products FROM eval_pairs WHERE seal_state = 'sealed'"):
        stored[(row[0], row[1], row[2], row[3])] = row[4:]
    for round_id in (*TEST_ROUNDS, CENSORED):
        pairs = hand_pairs(world.conn, round_id)
        lists: dict[tuple[str, str, int], list[str]] = {}
        for customer, rank, code in world.conn.execute("SELECT customer_id, rank, stock_code FROM offer_lists WHERE round_id = ? ORDER BY customer_id, rank", (round_id,)):
            lists.setdefault(("offer_list", "unrestricted", customer), []).append(code)
        for method, variant, customer, rank, code in world.conn.execute("SELECT method, variant, customer_id, rank, stock_code FROM baseline_lists WHERE round_id = ? ORDER BY method, variant, customer_id, rank", (round_id,)):
            lists.setdefault((method, variant, customer), []).append(code)
        methods = {(m, v) for m, v, _ in lists}
        assert len(methods) == 17
        for method, variant in sorted(methods):
            for customer, products in pairs.items():
                hit, recall, precision, ndcg = hand_metrics(lists[(method, variant, customer)], products)
                got = stored[(round_id, customer, method, variant)]
                assert got[0] == hit and got[1] == pytest.approx(recall, abs=1e-12) and got[2] == pytest.approx(precision, abs=1e-12) and got[3] == pytest.approx(ndcg, abs=1e-12) and got[4] == len(products)
                checked += 1
    assert checked == len(stored) > 1000, "no pair is missing and none is extra"


def test_the_pairs_are_the_customers_of_the_base_that_bought_in_the_week_and_both_groups_are_in_and_the_censored_round_is_beside_the_test(world):
    rows = world.conn.execute("SELECT DISTINCT round_id, customer_id FROM eval_pairs WHERE seal_state = 'sealed'").fetchall()
    assert {r[0] for r in rows} == {*TEST_ROUNDS, CENSORED}
    for round_id in (*TEST_ROUNDS, CENSORED):
        assert {r[1] for r in rows if r[0] == round_id} == set(hand_pairs(world.conn, round_id)), round_id
    groups = {r[0] for r in world.conn.execute("SELECT DISTINCT a.grp FROM eval_pairs p JOIN holdout_assignments a ON a.customer_id = p.customer_id")}
    assert groups == {"offer", "control"}, "the control group's list is as valid as the other to measure an order (D14)"
    total = world.conn.execute("SELECT pairs FROM eval_methods WHERE method = 'offer_list' AND variant = 'unrestricted' AND round_id = 'all'").fetchone()[0]
    assert total == sum(len(hand_pairs(world.conn, r)) for r in TEST_ROUNDS), "the total is the test: the censored round is beside it"


def test_the_totals_are_the_mean_over_the_pairs_of_the_test_and_every_method_and_variant_has_its_rows(world):
    rows = world.conn.execute("SELECT method, variant, round_id, pairs, hit_rate, recall, precision, ndcg, coverage, ci_low, ci_high, wilson_low, wilson_high FROM eval_methods WHERE seal_state = 'sealed'").fetchall()
    keys = {(r[0], r[1]) for r in rows}
    assert len(keys) == 17 and ("offer_list", "new_only") not in keys and ("chosen_discovery", "new_only") in keys
    assert {r[2] for r in rows} == {"all", *TEST_ROUNDS, CENSORED} and len(rows) == 17 * 5
    for method, variant in sorted(keys):
        pairs = world.conn.execute("SELECT hit, recall, precision, ndcg FROM eval_pairs WHERE method = ? AND variant = ? AND round_id IN ('R2011-03-28', 'R2011-04-04', 'R2011-04-11')", (method, variant)).fetchall()
        total = next(r for r in rows if r[:3] == (method, variant, "all"))
        assert total[3] == len(pairs) and total[4] == pytest.approx(np.mean([p[0] for p in pairs])) and total[5] == pytest.approx(np.mean([p[1] for p in pairs]))
        assert total[6] == pytest.approx(np.mean([p[2] for p in pairs])) and total[7] == pytest.approx(np.mean([p[3] for p in pairs]))
        assert total[9] <= total[4] <= total[10] and 0 <= total[11] <= total[4] <= total[12] <= 1, "the interval of the customers and Wilson's both hold the rate"
        for round_id in TEST_ROUNDS:
            one = next(r for r in rows if r[:3] == (method, variant, round_id))
            of_round = [p for p, r in zip(pairs, world.conn.execute("SELECT round_id FROM eval_pairs WHERE method = ? AND variant = ? AND round_id IN ('R2011-03-28', 'R2011-04-04', 'R2011-04-11')", (method, variant))) if r[0] == round_id]
            assert one[3] == len(of_round) and one[4] == pytest.approx(np.mean([p[0] for p in of_round])) and one[9] is None, "the interval is of the whole test"


def test_the_coverage_is_the_distinct_products_of_all_the_lists_of_the_round_over_the_products_bought_in_the_year_before(world):
    for round_id in TEST_ROUNDS:
        monday = datetime.strptime(round_id[1:], "%Y-%m-%d")
        listed = {r[0] for r in world.conn.execute("SELECT DISTINCT stock_code FROM offer_lists WHERE round_id = ?", (round_id,))}
        catalogue = {r[0] for r in world.conn.execute("SELECT DISTINCT stock_code FROM lines WHERE role IN ('purchase', 'guest_purchase') AND invoice_date >= ? AND invoice_date < ?",
                                                      ((monday - timedelta(days=365)).strftime("%Y-%m-%d %H:%M:%S"), monday.strftime("%Y-%m-%d %H:%M:%S")))}
        got = world.conn.execute("SELECT coverage FROM eval_methods WHERE method = 'offer_list' AND variant = 'unrestricted' AND round_id = ?", (round_id,)).fetchone()[0]
        assert got == pytest.approx(len(listed) / len(catalogue)), round_id
    mean = np.mean([world.conn.execute("SELECT coverage FROM eval_methods WHERE method = 'offer_list' AND round_id = ?", (r,)).fetchone()[0] for r in TEST_ROUNDS])
    assert world.conn.execute("SELECT coverage FROM eval_methods WHERE method = 'offer_list' AND round_id = 'all'").fetchone()[0] == pytest.approx(mean), "the mean of the rounds of the test"


def test_the_paired_differences_are_the_differences_of_the_rates_and_their_interval_comes_from_resampling_customers(evaluated, world):
    figures = evaluated.seal["test"]["metrics"]
    rate = {k: v["hit_rate"] for k, v in figures["methods"].items()}
    for key, a, b in (("list_vs_b2", "offer_list:unrestricted", "b2:unrestricted"), ("list_vs_b3", "offer_list:unrestricted", "b3:unrestricted"), ("chosen_vs_b2_new", "chosen_discovery:new_only", "b2:new_only")):
        d = figures["diffs"][key]
        assert d["value"] == pytest.approx(rate[a] - rate[b]) and d["a_rate"] == pytest.approx(rate[a]) and d["b_rate"] == pytest.approx(rate[b]) and d["ci_low"] <= d["value"] <= d["ci_high"]
        assert d["pairs"] == figures["pairs"]
    # the same draws for both: the paired interval is not wider than the two separate intervals' reach
    own = figures["methods"]["offer_list:unrestricted"]
    other = figures["methods"]["b2:unrestricted"]
    assert figures["diffs"]["list_vs_b2"]["ci_high"] - figures["diffs"]["list_vs_b2"]["ci_low"] <= (own["ci_high"] - own["ci_low"]) + (other["ci_high"] - other["ci_low"]) + 1e-12


def test_a_follow_up_that_is_not_the_one_recomputed_from_the_lines_stops_the_evaluation(world):
    """What was followed up is what is evaluated: a round whose products counted in the follow-up are not the ones of the lines is refused (no figure is made from a pair that does not add up)."""
    world.conn.execute("DROP TRIGGER round_outcomes_no_update")
    world.conn.execute("UPDATE round_outcomes SET products = products + 1, products_in_offer = products_in_offer WHERE round_id = 'R2011-04-04' AND bought = 1 AND customer_id = (SELECT MIN(customer_id) FROM round_outcomes WHERE round_id = 'R2011-04-04' AND bought = 1)")
    with pytest.raises(EvaluationError, match="seguimiento"):
        evaluation.evaluate_rankings(world.conn, world.view)


# --- the A/A, the balance and what the CRM says --------------------------------------------------------------------------------------------------------


def test_the_experiment_is_the_launch_cohort_with_its_outcomes_by_hand_and_the_balance_is_the_standardized_difference_by_hand(world, evaluated):
    figures = evaluated.seal["test"]["metrics"]
    cohort = [r[0] for r in world.conn.execute("SELECT customer_id FROM holdout_assignments WHERE method = 'stratified' ORDER BY customer_id")]
    group = dict(world.conn.execute("SELECT customer_id, grp FROM holdout_assignments WHERE method = 'stratified'"))
    assert figures["balance"]["customers"] == len(cohort) == 300 and sum(1 for g in group.values() if g == "control") == sum(1 for c in cohort if group[c] == "control")
    weeks = [datetime(2011, 3, 28) + timedelta(days=7 * n) for n in range(3)]
    spend, active = {c: 0.0 for c in cohort}, {c: set() for c in cohort}
    for customer, quantity, price, date in world.conn.execute("SELECT customer_id, quantity, price, invoice_date FROM lines WHERE role = 'purchase' AND customer_id IS NOT NULL AND invoice_date >= '2011-03-28 00:00:00' AND invoice_date < '2011-04-18 00:00:00'"):
        if customer in spend:
            spend[customer] += quantity * float(price)
            active[customer].add(int((datetime.strptime(date, "%Y-%m-%d %H:%M:%S") - weeks[0]).days // 7))
    m1 = np.array([len(active[c]) / 3 for c in cohort])
    control = np.array([group[c] == "control" for c in cohort])
    raw = figures["aa"]["m1"]["normal_raw"]
    assert raw["diff"] == pytest.approx(m1[~control].mean() - m1[control].mean(), abs=1e-12)
    assert figures["outcomes"]["m1"]["mean"] == pytest.approx(m1.mean()) and figures["outcomes"]["m2"]["mean"] == pytest.approx(np.mean([spend[c] for c in cohort]))
    covariate = {r[0]: r[1] for r in world.conn.execute("SELECT customer_id, recency_days FROM contact_base WHERE round_id = 'R2011-03-28'")}
    x = np.array([covariate[c] for c in cohort])
    pooled = math.sqrt((x[~control].var(ddof=1) + x[control].var(ddof=1)) / 2)
    row = world.conn.execute("SELECT offer_mean, control_mean, smd FROM eval_balance WHERE covariate = 'recency_days' AND seal_state = 'sealed'").fetchone()
    assert row[2] == pytest.approx((x[~control].mean() - x[control].mean()) / pooled) and row[0] == pytest.approx(x[~control].mean()) and row[1] == pytest.approx(x[control].mean())
    smds = {r[0]: r[1] for r in world.conn.execute("SELECT covariate, smd FROM eval_balance")}
    assert set(smds) == {"recency_days", "invoices_365", "spend_365", "tenure_days", "bulk"} and figures["balance"]["max_abs_smd"] == pytest.approx(max(abs(v) for v in smds.values()))
    assert smds[figures["balance"]["covariate"]] == pytest.approx(max(smds.values(), key=abs))


def test_the_aa_has_the_preregistered_test_and_the_two_normal_ones_for_each_metric_and_a_calibration_for_each(world, evaluated):
    rows = world.conn.execute("SELECT metric, kind, aa_diff, aa_p, aa_ci_low, aa_ci_high, calibration_rejection FROM eval_experiment WHERE seal_state = 'sealed' ORDER BY metric, kind").fetchall()
    assert [(r[0], r[1]) for r in rows] == [(m, k) for m in ("m1", "m2") for k in ("normal_cuped", "normal_raw", "preregistered")]
    for metric, kind, diff, p, low, high, rejection in rows:
        assert 0 < p <= 1 and low <= diff <= high and 0 <= rejection <= 1, (metric, kind)
    figures = evaluated.seal["test"]["metrics"]["calibration"]
    assert figures["seeds"] == 40 and figures["permutations"] == 100 and figures["alpha"] == 0.05 and set(figures["rejection"]) == {f"{m}_{k}" for m in ("m1", "m2") for k in ("preregistered", "normal_raw", "normal_cuped")}
    p_min = 1 / (world.cfg.experiment.permutations + 1)
    assert all(r[3] >= p_min - 1e-12 for r in rows if r[1] == "preregistered"), "a permutation p is never under one over the permutations plus one"


def test_the_minimum_detectable_effect_is_listed_for_each_share_of_control_and_gets_smaller_as_the_control_grows(world):
    rows = world.conn.execute("SELECT metric, holdout_share, holdout_size, mde, mde_relative FROM eval_mde WHERE seal_state = 'sealed' ORDER BY metric, holdout_share").fetchall()
    assert [(r[0], r[1]) for r in rows] == [(m, s) for m in ("m1", "m2") for s in (0.1, 0.2, 0.3)]
    assert [r[2] for r in rows[:3]] == [30, 60, 90]
    for first in (0, 3):
        assert rows[first][3] > rows[first + 1][3] > rows[first + 2][3] > 0 and rows[first][4] > 0


def test_the_evidence_of_the_crm_is_what_the_replay_delivered_and_the_criterion_that_reads_it_is_met(world, evaluated):
    crm = evaluated.crm
    assert (crm.rounds, crm.csv_files, crm.control_in_crm, crm.control_in_csv, crm.repeat_created) == (4, 4, 0, 0, 0) and crm.repeat_round == CENSORED
    offers = sum(r[0] for r in world.conn.execute("SELECT offer_size FROM rounds"))
    assert crm.lists == crm.read_back_equal == offers and crm.repeat_contacts == world.conn.execute("SELECT offer_size FROM rounds WHERE round_id = ?", (CENSORED,)).fetchone()[0]
    c09 = next(c for c in evaluated.outcome["criteria"] if c.criterion_id == "C09")
    assert c09.passed is True and "no se puede calcular" not in c09.verdict_es


def test_a_customer_of_the_control_group_in_the_crm_or_in_a_file_fails_c09_and_a_missing_file_cannot_be_computed(world):
    client = crm_client(world)
    control = world.conn.execute("SELECT customer_id FROM holdout_assignments WHERE grp = 'control' ORDER BY customer_id LIMIT 1").fetchone()[0]
    client.put_offers("R2011-04-04", [ContactOffers(control, tuple(Offer(r, f"9500{r % 10}{r // 10}", "repeat") for r in range(1, 11)))])
    assert evidence_of(world).control_in_crm == 1
    figures = evidence_of(world).figures()
    criteria = {c.criterion_id: c for c in evaluation.criteria_of({"variants": 17, "rounds": 3, "crm": figures}, dataclasses.asdict(world.view.criteria))}
    assert criteria["C09"].passed is False and "1 clientes del control llegaron al CRM" in criteria["C09"].verdict_es
    path = world.cfg.paths.private_dir / "email" / "R2011-04-04.csv"
    path.write_bytes(path.read_bytes() + f"{control},1,95000,x,repeat\n".encode("utf-8"))
    assert evidence_of(world).control_in_csv == 1
    path.unlink()
    assert evidence_of(world).csv_files == 3
    cannot = evaluation.criteria_of({"variants": 17, "crm": evidence_of(world).figures()}, dataclasses.asdict(world.view.criteria))[8]
    assert cannot.passed is False and "no se puede calcular" in cannot.verdict_es and "3 de 4" in cannot.verdict_es


def test_without_a_delivery_there_is_no_evidence_and_c09_cannot_be_computed(before):
    empty = sqlite3.connect(":memory:")
    from personaloffers import warehouse

    warehouse.apply_schema(empty)
    assert evaluation.crm_evidence(empty, crm_client(before), private_dir=before.cfg.paths.private_dir, batch_size=500) == evaluation.CrmEvidence(0, 0, 0, 0, 0, 0, "", 0, 0)


# --- once --------------------------------------------------------------------------------------------------------------------------------------------------------


def test_the_evaluation_is_stored_once_sealed_once_and_a_repetition_reproduces_it(evaluated, world):
    outcome = evaluated.outcome
    assert outcome["state"] == "first" and outcome["seal"] == "written"
    assert outcome["rows"]["eval_criteria"] == 10 and outcome["rows"]["eval_pairs"] == world.conn.execute("SELECT COUNT(*) FROM eval_pairs").fetchone()[0] > 2000
    seal = evaluated.seal
    assert set(seal) == {"version", "launch", "test"} and set(seal["test"]) == registry.TEST_KEYS and seal["test"]["run_key"] == "run-5" and seal["test"]["as_of"] == "2011-04-23 00:00:00"
    assert [e["id"] for e in seal["test"]["criteria"]] == [f"C{n:02d}" for n in range(1, 11)]
    before_rows, before_seal = tables_digest(world.conn), file_digest(world.seal_path)
    again = reporting.evaluate(world.conn, world.view, RUN, seal_path=world.seal_path, crm=evidence_of(world))
    assert again["state"] == "repeat" and again["seal"] == "unchanged" and again["rows"] == {}
    assert tables_digest(world.conn) == before_rows and file_digest(world.seal_path) == before_seal, "nothing changed: not a row and not a byte of the seal"
    assert [c.seal_entry() for c in again["criteria"]] == seal["test"]["criteria"] or all(round(a[k], 6) == round(b[k], 6) if isinstance(a[k], float) else a[k] == b[k] for a, b in zip([c.seal_entry() for c in again["criteria"]], seal["test"]["criteria"]) for k in a)


def test_a_repetition_whose_figures_are_not_the_sealed_ones_is_refused_and_writes_nothing(world, monkeypatch):
    before_rows, before_seal = tables_digest(world.conn), file_digest(world.seal_path)
    real = evaluation.run_experiment

    def shifted(*args, **kwargs):
        found = real(*args, **kwargs)
        found["balance"]["max_abs_smd"] += 0.01
        return found

    monkeypatch.setattr(evaluation, "run_experiment", shifted)
    with pytest.raises(SealMismatchError, match="R7"):
        reporting.evaluate(world.conn, world.view, RUN, seal_path=world.seal_path, crm=evidence_of(world))
    assert tables_digest(world.conn) == before_rows and file_digest(world.seal_path) == before_seal


def test_before_the_close_the_evaluation_is_refused_and_nothing_is_written(launched, workbook, quick_cfg, tmp_path):
    """The launch ran and no week has arrived: the test is not evaluated, and neither the warehouse nor the seal changes."""
    world = copy_world(launched.root, workbook, quick_cfg, tmp_path / "launch_only")
    try:
        before_seal = file_digest(world.seal_path)
        with pytest.raises(EvaluationError, match="seguimiento"):
            reporting.evaluate(world.conn, world.view, RUN, seal_path=world.seal_path, crm=evaluation.CrmEvidence(0, 0, 0, 0, 0, 0, "", 0, 0))
        assert world.conn.execute("SELECT COUNT(*) FROM eval_criteria").fetchone()[0] == 0 and file_digest(world.seal_path) == before_seal
    finally:
        world.conn.close()


def test_the_launch_part_of_the_seal_is_the_one_of_the_launch_and_the_seal_holds_no_customer_number(evaluated, launched):
    assert evaluated.seal["launch"] == launched.seal["launch"], "the test part was added and the launch part is as it was"
    text = json.dumps(evaluated.seal["test"], sort_keys=True)
    assert not re.search(r"(?<![\d.])90[0-3]\d\d(?!\d)", text), "no number of a customer of the fixture is in what the seal keeps of the test"


def test_the_rows_of_the_validation_are_the_sealed_ones_of_the_launch_and_one_candidate_is_chosen(world, evaluated):
    candidates = evaluated.seal["launch"]["validation"]["candidates"]
    rows = world.conn.execute("SELECT candidate, round_id, pairs, hits, hit_new, coverage, kept, chosen, fit_rounds FROM eval_choice WHERE seal_state = 'sealed'").fetchall()
    assert len(rows) == len(candidates) * 3, "each candidate in the two rounds of the validation and in all of them"
    chosen = [r for r in rows if r[7] == 1]
    assert len(chosen) == 1 and chosen[0][1] == "all" and chosen[0][0] == evaluated.seal["launch"]["validation"]["recipe"]
    for candidate in candidates:
        total = next(r for r in rows if r[0] == candidate["name"] and r[1] == "all")
        assert total[2] == candidate["pairs"] and total[3] == candidate["hits"] and total[4] == pytest.approx(candidate["hit_new"]) and total[8] == len(candidate["fit_rounds"]) == 2


def test_all_the_criteria_are_computed_and_the_summary_of_the_replay_names_the_one_that_is_not_met(evaluated):
    criteria = {c.criterion_id: c for c in evaluated.outcome["criteria"]}
    assert all("no se puede calcular" not in c.verdict_es for c in criteria.values()) and criteria["C10"].passed is None
    assert all(c.passed in (True, False) for cid, c in criteria.items() if cid != "C10")


# --- the rows are insert-only and what is post-seal is kept apart --------------------------------------------------------------------------------------


def test_the_sealed_rows_cannot_be_changed_deleted_or_written_again_and_a_post_seal_row_can_be_replaced(world):
    one = {"eval_pairs": ("round_id = 'R2011-03-28'", "hit = 1 - hit"), "eval_methods": ("round_id = 'all'", "pairs = 0"), "eval_segments": ("1 = 1", "pairs = 1"), "eval_experiment": ("metric = 'm1'", "aa_p = 1"),
           "eval_mde": ("metric = 'm1'", "mde = 0"), "eval_balance": ("covariate = 'bulk'", "smd = 0"), "eval_criteria": ("criterion_id = 'C01'", "passed = 0"), "eval_choice": ("round_id = 'all'", "kept = 0")}
    for table, (where, assignment) in one.items():
        snapshot = world.conn.execute(f"SELECT * FROM {table} ORDER BY 1, 2, 3, 4, 5").fetchall()
        for statement in (f"UPDATE {table} SET {assignment} WHERE {where}", f"DELETE FROM {table} WHERE {where}", f"INSERT OR REPLACE INTO {table} SELECT * FROM {table} WHERE {where}"):
            with pytest.raises(sqlite3.DatabaseError, match="solo inserción"):
                world.conn.execute(statement)
        assert world.conn.execute(f"SELECT * FROM {table} ORDER BY 1, 2, 3, 4, 5").fetchall() == snapshot, table
    world.conn.execute("INSERT INTO eval_balance SELECT covariate, 'post_seal', offer_mean, control_mean, smd FROM eval_balance WHERE covariate = 'bulk'")
    world.conn.execute("UPDATE eval_balance SET smd = 0.5 WHERE seal_state = 'post_seal'")
    world.conn.execute("DELETE FROM eval_balance WHERE seal_state = 'post_seal'")
    assert world.conn.execute("SELECT COUNT(*) FROM eval_balance WHERE seal_state = 'sealed'").fetchone()[0] == 5


def test_the_same_test_with_another_configuration_after_the_seal_is_kept_apart_and_the_sealed_rows_and_the_seal_are_untouched(world):
    other = dataclasses.replace(world.view, criteria=dataclasses.replace(world.view.criteria, c05_min_coverage=0.99))
    sealed_rows, sealed_seal = tables_digest(world.conn), file_digest(world.seal_path)
    first = reporting.evaluate(world.conn, other, RUN, seal_path=world.seal_path, crm=evidence_of(world))
    assert first["state"] == "post_seal" and first["seal"] == "post_seal" and file_digest(world.seal_path) == sealed_seal
    apart = {r[0]: r[1] for r in world.conn.execute("SELECT criterion_id, passed FROM eval_criteria WHERE seal_state = 'post_seal'")}
    assert apart["C05"] == 0 and len(apart) == 10, "with the limit at 0.99 the coverage does not reach it: said apart, and the sealed C05 is as it was"
    assert world.conn.execute("SELECT passed FROM eval_criteria WHERE criterion_id = 'C05' AND seal_state = 'sealed'").fetchone()[0] == 1
    sealed_only = world.conn.execute("SELECT COUNT(*) FROM eval_pairs WHERE seal_state = 'sealed'").fetchone()[0]
    assert world.conn.execute("SELECT COUNT(*) FROM eval_pairs WHERE seal_state = 'post_seal'").fetchone()[0] == sealed_only
    again = reporting.evaluate(world.conn, other, reporting.RunMeta("run-7", datetime(2011, 4, 25)), seal_path=world.seal_path, crm=evidence_of(world))
    assert again["state"] == "post_seal" and world.conn.execute("SELECT COUNT(*) FROM eval_criteria WHERE seal_state = 'post_seal'").fetchone()[0] == 10, "the post-seal rows are replaced, not added"
    for table in reporting.TABLES:
        rows = world.conn.execute(f"SELECT * FROM {table} WHERE seal_state = 'sealed' ORDER BY 1, 2, 3, 4, 5").fetchall()
        assert rows, table
    assert tables_digest(world.conn) != sealed_rows and file_digest(world.seal_path) == sealed_seal
    world.conn.execute("DELETE FROM eval_pairs WHERE seal_state = 'post_seal'")


def test_the_schema_of_the_evaluation_refuses_what_cannot_be_a_row(before):
    """A wrong row is refused at the door: an unknown method, a hit that is not 0 or 1, a probability out of range, a state nobody defined, a criterion that does not exist."""
    wrong = [
        "INSERT INTO eval_pairs VALUES ('R2011-03-28', 1, 'b9', 'unrestricted', 'sealed', 'retail|repeat', 1, 1, 1, 1, 1)",
        "INSERT INTO eval_pairs VALUES ('R2011-03-28', 1, 'b2', 'unrestricted', 'sealed', 'retail|repeat', 2, 1, 1, 1, 1)",
        "INSERT INTO eval_pairs VALUES ('R2011-03-28', 1, 'b2', 'unrestricted', 'sealed', 'retail|repeat', 1, 1.5, 1, 1, 1)",
        "INSERT INTO eval_pairs VALUES ('R2011-03-28', 1, 'b2', 'unrestricted', 'maybe', 'retail|repeat', 1, 1, 1, 1, 1)",
        "INSERT INTO eval_pairs VALUES ('R2011-03-28', 1, 'b2', 'unrestricted', 'sealed', 'retail|repeat', 1, 1, 1, 1, 0)",
        "INSERT INTO eval_pairs VALUES ('R2011-09-05', 1, 'b2', 'unrestricted', 'sealed', 'retail|repeat', 1, 1, 1, 1, 1)",
        "INSERT INTO eval_experiment VALUES ('m3', 'preregistered', 'sealed', 0, 0.5, 0, 0, 0.05)",
        "INSERT INTO eval_experiment VALUES ('m1', 'preregistered', 'sealed', 0, 1.5, 0, 0, 0.05)",
        "INSERT INTO eval_experiment VALUES ('m1', 'bootstrap', 'sealed', 0, 0.5, 0, 0, 0.05)",
        "INSERT INTO eval_balance VALUES ('age', 'sealed', 1, 1, 0)",
        "INSERT INTO eval_criteria VALUES ('C11', 'sealed', 'n', NULL, 'x', NULL, NULL, NULL, 't', 1, 'sí', 'sí', 'v')",
        "INSERT INTO eval_criteria VALUES ('C01', 'sealed', 'n', NULL, 'x', NULL, NULL, NULL, 't', 2, 'sí', 'sí', 'v')",
        "INSERT INTO eval_mde VALUES ('m1', 1.5, 'sealed', 10, 0.1, 0.1)",
        "INSERT INTO eval_choice VALUES ('a', 'all', 'sealed', 'forest', 1, NULL, 0, 1, 1, 1, 1, 0.5, 0.5, 1, 1, 1)",
    ]
    for statement in wrong:
        with pytest.raises(sqlite3.IntegrityError):
            before.conn.execute(statement)
    for table in reporting.TABLES:
        assert before.conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0, table


# --- the edges of the windows and the pinned seed ---------------------------------------------------------------------------------------------------------


def add_line(conn, key, code, when, customer=90001, role="purchase"):
    conn.execute("INSERT INTO lines (line_key, delivery_id, invoice, stock_code, description, quantity, invoice_date, price, customer_id, country, internal_repeat, role) "
                 "VALUES (?, 'L2011-03-27', ?, ?, 'X', 1, ?, '1.00', ?, 'United Kingdom', 0, ?)", (key, f"X{key}", code, when, customer, role))


def test_a_purchase_at_the_midnight_that_ends_a_week_is_not_in_that_week(world):
    """The window is ``[Monday, next Monday)``: a line at exactly the next Monday's midnight is of the next round and changes nothing of this one (and the follow-up that was written does not count it either)."""
    before = evaluation.evaluate_rankings(world.conn, world.view)
    buyer = world.conn.execute("SELECT customer_id FROM round_outcomes WHERE round_id = 'R2011-04-04' AND bought = 1 ORDER BY customer_id LIMIT 1").fetchone()[0]
    unknown = world.conn.execute("SELECT stock_code FROM products WHERE stock_code NOT IN (SELECT stock_code FROM lines WHERE customer_id = ? AND invoice_date >= '2011-04-04' AND invoice_date < '2011-04-11') LIMIT 1", (buyer,)).fetchone()[0]
    add_line(world.conn, 99_000_001, unknown, "2011-04-11 00:00:00", customer=buyer)
    after = evaluation.evaluate_rankings(world.conn, world.view)
    assert after.pairs.equals(before.pairs) and after.figures["diffs"] == before.figures["diffs"]


def test_the_catalogue_of_the_coverage_includes_the_day_that_is_365_days_before_the_round(world):
    add_line(world.conn, 99_000_002, "95999", "2010-03-28 00:00:00", customer=90002)
    world.conn.execute("INSERT INTO products VALUES ('95999', 'PRODUCTO SINTÉTICO 95999', '2010-03-28', 0)")
    ranking = evaluation.evaluate_rankings(world.conn, world.view)
    monday = datetime(2011, 3, 28)
    catalogue = {r[0] for r in world.conn.execute("SELECT DISTINCT stock_code FROM lines WHERE role IN ('purchase', 'guest_purchase') AND invoice_date >= ? AND invoice_date < ?",
                                                  ((monday - timedelta(days=365)).strftime("%Y-%m-%d %H:%M:%S"), monday.strftime("%Y-%m-%d %H:%M:%S")))}
    assert "95999" in catalogue
    listed = {r[0] for r in world.conn.execute("SELECT DISTINCT stock_code FROM offer_lists WHERE round_id = 'R2011-03-28'")}
    row = next(m for m in ranking.methods if (m["method"], m["variant"], m["round_id"]) == ("offer_list", "unrestricted", "R2011-03-28"))
    assert row["coverage"] == pytest.approx(len(listed) / len(catalogue))


def test_cuped_adjusts_with_the_same_number_of_weeks_before_the_first_round_by_hand_and_the_sealed_test_uses_the_pinned_seed(world, evaluated):
    cohort = [r[0] for r in world.conn.execute("SELECT customer_id FROM holdout_assignments WHERE method = 'stratified' ORDER BY customer_id")]
    group = dict(world.conn.execute("SELECT customer_id, grp FROM holdout_assignments WHERE method = 'stratified'"))
    stratum = dict(world.conn.execute("SELECT customer_id, stratum FROM holdout_assignments WHERE method = 'stratified'"))

    def active(first, weeks):
        found = {c: set() for c in cohort}
        end = first + timedelta(days=7 * weeks)
        for customer, date in world.conn.execute("SELECT customer_id, invoice_date FROM lines WHERE role = 'purchase' AND customer_id IS NOT NULL AND invoice_date >= ? AND invoice_date < ?",
                                                 (first.strftime("%Y-%m-%d %H:%M:%S"), end.strftime("%Y-%m-%d %H:%M:%S"))):
            if customer in found:
                found[customer].add((datetime.strptime(date, "%Y-%m-%d %H:%M:%S") - first).days // 7)
        return np.array([len(found[c]) / weeks for c in cohort])

    y, x = active(datetime(2011, 3, 28), 3), active(datetime(2011, 3, 7), 3)
    assert x.var(ddof=1) > 0 and not np.array_equal(x, active(datetime(2011, 2, 28), 3))
    theta = np.cov(y, x, ddof=1)[0, 1] / x.var(ddof=1)
    adjusted = y - theta * (x - x.mean())
    control = np.array([group[c] == "control" for c in cohort])
    metrics = evaluated.seal["test"]["metrics"]
    assert metrics["aa"]["m1"]["normal_cuped"]["diff"] == pytest.approx(adjusted[~control].mean() - adjusted[control].mean(), abs=1e-12) and metrics["outcomes"]["m1"]["theta"] == pytest.approx(theta)
    strata = np.array([stratum[c] for c in cohort])
    from personaloffers import experiment

    draws = experiment.draw_assignments(strata, control, world.cfg.experiment.permutations, np.random.default_rng(100_000))
    expected = experiment.stratified_permutation(adjusted, control, strata, world.cfg.experiment.permutations, None, assignments=draws)
    assert metrics["aa"]["m1"]["preregistered"]["p"] == pytest.approx(expected.p, abs=1e-12) and evaluation.AA_SEED == 100_000 == experiment.PERMUTATION_SEED_BASE


def test_a_batch_that_was_not_read_back_equal_is_not_counted_as_delivered_in_the_evidence(world):
    first = evidence_of(world)
    world.conn.execute("INSERT INTO crm_deliveries (round_id, batch, attempt, status, contacts, created, unchanged, conflicts, sends, readback_equal, seconds, run_key) "
                       "VALUES ('R2011-03-28', 9, 1, 'ok', 7, 7, 0, 0, 1, 0, 0.1, 'run-4')")
    world.conn.execute("INSERT INTO crm_deliveries (round_id, batch, attempt, status, contacts, created, unchanged, conflicts, sends, readback_equal, seconds, run_key) "
                       "VALUES ('R2011-03-28', 10, 1, 'failed', 5, 0, 0, 5, 1, 0, 0.1, 'run-4')")
    assert evidence_of(world).read_back_equal == first.read_back_equal, "neither a batch read back different nor one that failed counts"


def test_a_candidate_whose_rounds_do_not_add_up_to_its_sealed_pairs_and_hits_stops_the_evaluation_and_writes_nothing(before, evaluated):
    """L128's warning: the rows of ``eval_choice`` for every round are checked against the figures of the «all» row that the seal holds, so that the two never tell different totals."""
    before_rows, document = tables_digest(before.conn), json.loads(before.seal_path.read_text(encoding="utf-8"))
    candidate = document["launch"]["validation"]["candidates"][0]
    round_id = next(iter(candidate["per_round"]))
    assert sum(r[0] for r in candidate["per_round"].values()) == candidate["pairs"] and sum(r[1] for r in candidate["per_round"].values()) == candidate["hits"], "as the launch sealed it"
    for index, what in ((0, "pares"), (1, "aciertos")):
        broken = json.loads(json.dumps(document))
        broken["launch"]["validation"]["candidates"][0]["per_round"][round_id][index] += 1
        before.seal_path.write_text(json.dumps(broken, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
        tampered = file_digest(before.seal_path)
        with pytest.raises(registry.SealError, match=rf"{what} por ronda del candidato {candidate['name']}.*R7"):
            reporting.evaluate(before.conn, before.view, RUN, seal_path=before.seal_path, crm=evaluated.crm)
        assert tables_digest(before.conn) == before_rows and file_digest(before.seal_path) == tampered, f"nothing is written when the {what} do not add up"
    assert json.loads(before.seal_path.read_text(encoding="utf-8")).get("test") is None


def test_the_rows_of_the_choice_are_one_per_round_and_one_for_all_of_them_with_the_sealed_figures(evaluated, world):
    """The rows of every candidate as they were: a row per round of the validation with its own pairs and hits, and the «all» row with the sealed totals (the previous behavior of ``eval_choice``)."""
    for candidate in evaluated.seal["launch"]["validation"]["candidates"]:
        rows = world.conn.execute("SELECT round_id, pairs, hits, hit_new, coverage, kept, chosen FROM eval_choice WHERE candidate = ? AND seal_state = 'sealed' ORDER BY round_id", (candidate["name"],)).fetchall()
        per_round = [(round_id, pairs, hits) for round_id, (pairs, hits, _distinct, _catalogue) in sorted(candidate["per_round"].items())]
        assert [r[:3] for r in rows if r[0] != "all"] == per_round
        (total,) = [r for r in rows if r[0] == "all"]
        assert total[1:] == (candidate["pairs"], candidate["hits"], candidate["hit_new"], candidate["coverage"], int(candidate["kept"]), int(candidate["chosen"]))
