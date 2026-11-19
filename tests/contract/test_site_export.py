"""The six JSON files that the personal site copies (U17, risk item 3: another repository consumes their shape; RF22, AC28; decisions D16, D30, D38; plan section 21): the envelope that ties them to one export, the keys
of each file, what is empty until the test is sealed, the manifest written last, the cap, the cells under the minimum and the words that claim an effect. A change of shape is a change of this file."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import pandas as pd
import pytest

from personaloffers import registry, reporting, site_export
from personaloffers.site_export import SITE_FILES, SiteExportError, SiteSetError
from personaloffers.warehouse import connect
from tests.fixtures.sites import SOURCE_COUNTS, export_site_of
from tests.fixtures.stars import RUN, export_world

ENVELOPE = ("schema_version", "run_key", "as_of", "config_sha256", "source_sha256", "attribution", "no_effect_note_es")
KEYS = {
    "summary": {"status", "evaluation_status", "headline", "criteria", "seal", "sealed_from"},
    "data": {"source", "roles", "countries", "products", "baskets", "customers", "repurchase", "bulk", "discount_lines", "calendar"},
    "algorithms": {"methods", "by_round", "choice", "rules_example", "example_lists"},
    "operation": {"rounds", "crm", "email"},
    "control": {"holdout", "balance", "aa", "calibration", "mde", "what_it_cannot_measure_es"},
    "validation_rules": {"rules", "totals"},
}
HEADLINE = ("rounds", "base_mean", "offer_mean", "control_mean", "hit_offer_list", "hit_b2", "hit_b3", "hit_new_chosen", "hit_new_b2", "coverage", "max_abs_smd", "aa_p_m1", "aa_p_m2", "mde_m1_points_20", "mde_m2_gbp_20")
ALLOWED = re.compile(r"menor efecto detectable|no es el efecto de nada|no es un efecto|permite medir el efecto de una oferta")
EFFECT_WORDS = re.compile(r"efecto|aumento|uplift|lift|incremental|causal", re.IGNORECASE)
LOCAL_PATH = re.compile(r"(?<![A-Za-z])[A-Za-z]:[\\/]|/(?:home|Users)/|\\Users\\")


def text_of(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def walk(node, where=""):
    """Every (location, key-or-None, value) of a document: the keys are visited as well as the values."""
    if isinstance(node, dict):
        for key, value in node.items():
            yield f"{where}/{key}", key, None
            yield from walk(value, f"{where}/{key}")
    elif isinstance(node, list):
        for i, item in enumerate(node):
            yield from walk(item, f"{where}[{i}]")
    else:
        yield where, None, node


# --- the set ----------------------------------------------------------------------------------------------------------------------------------------


def test_the_six_files_and_the_manifest_are_one_export_with_the_same_envelope(sited):
    assert [p.name for p in sited.paths] == list(SITE_FILES) and sorted(p.name for p in sited.out.iterdir()) == sorted([*SITE_FILES, "manifest.json"])
    manifest = json.loads(text_of(sited.out / "manifest.json"))
    assert set(manifest) == {*ENVELOPE, "files"} and sorted(manifest["files"]) == sorted(SITE_FILES) and manifest["schema_version"] == 1
    assert manifest["run_key"] == RUN.run_key and manifest["as_of"] == "2011-04-23 00:00:00" and re.fullmatch(r"[0-9a-f]{64}", manifest["config_sha256"]) and re.fullmatch(r"[0-9a-f]{64}", manifest["source_sha256"])
    assert manifest["attribution"].startswith("Chen, D. (2012). Online Retail II") and "CC BY 4.0" in manifest["attribution"]
    total = 0
    for name in SITE_FILES:
        raw = (sited.out / name).read_bytes()
        total += len(raw)
        document = json.loads(raw.decode("utf-8"))
        assert all(document[key] == manifest[key] for key in ENVELOPE), name
        assert set(document) == {*ENVELOPE, *KEYS[name.removesuffix(".json")]}, name
        assert raw.decode("utf-8") == json.dumps(document, ensure_ascii=False, sort_keys=True, indent=1, allow_nan=False) + "\n", "one canonical text"
        assert manifest["files"][name] == {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
    assert total <= 204800 and site_export.verify_site(sited.out) == []
    assert manifest["config_sha256"] == registry.config_fingerprint(sited.view)


def test_the_files_are_read_back_whole_through_the_reader(sited):
    assert sited.site.manifest["run_key"] == RUN.run_key and sited.site.summary["run_key"] == RUN.run_key
    assert {name: json.loads(text_of(sited.out / name)) for name in SITE_FILES} == {f"{k}.json": getattr(sited.site, k) for k in KEYS}


# --- the summary ----------------------------------------------------------------------------------------------------------------------------------------


def test_the_summary_of_a_sealed_replay_tells_the_ten_criteria_in_order_and_the_headline_of_the_seal(sited, evaluated):
    summary = sited.site.summary
    assert summary["evaluation_status"] == "sealed" and summary["sealed_from"] == "warehouse" and summary["status"] == "running"
    assert [c["criterion_id"] for c in summary["criteria"]] == [f"C{n:02d}" for n in range(1, 11)]
    assert all(set(c) == {"criterion_id", "name_es", "threshold_es", "tested_value_es", "point_value", "ci_low", "ci_high", "passed", "verdict_es"} for c in summary["criteria"])
    expected = {c["criterion_id"]: c for c in reporting.criteria_rows(sited.conn)}
    assert {c["criterion_id"]: (c["tested_value_es"], c["passed"], c["verdict_es"]) for c in summary["criteria"]} == {k: (v["tested_value_es"], v["passed"], v["verdict_es"]) for k, v in expected.items()}
    headline = summary["headline"]
    assert set(headline) == set(HEADLINE) and headline["rounds"] == 3
    metrics = evaluated.seal["test"]["metrics"]
    assert headline["hit_offer_list"] == round(metrics["methods"]["offer_list:unrestricted"]["hit_rate"], 3) and headline["hit_b2"] == round(metrics["methods"]["b2:unrestricted"]["hit_rate"], 3)
    assert headline["aa_p_m1"] == round(metrics["aa"]["m1"]["preregistered"]["p"], 3) and headline["max_abs_smd"] == round(metrics["balance"]["max_abs_smd"], 3)
    assert all(isinstance(v, (int, type(None))) or len(repr(v).split(".")[-1]) <= 3 for v in headline.values()), "floats to three decimals"
    assert summary["seal"]["launch"]["config_sha256"] == evaluated.seal["launch"]["config_sha256"] and summary["seal"]["test"]["run_key"] == evaluated.seal["test"]["run_key"]


def test_every_figure_of_the_site_is_the_figure_of_the_star_model(sited, exported):
    total = pd.read_parquet(exported.out / "fact_method_total.parquet")
    total = total[total["seal_state"] == "sealed"].set_index(["method_key", "variant_key"])
    methods = {(m["method_key"], m["variant_key"]): m for m in sited.site.algorithms["methods"]}
    assert set(methods) == set(total.index) and len(methods) == 17
    for key, row in total.iterrows():
        m = methods[key]
        assert (m["pairs"], m["hit_rate"] is None) == (None if pd.isna(row["pairs"]) else int(row["pairs"]), pd.isna(row["hit_rate"]))
        if not pd.isna(row["hit_rate"]):
            assert m["hit_rate"] == pytest.approx(round(row["hit_rate"], 3)) and m["ci_low"] == pytest.approx(round(row["ci_low"], 3)) and m["coverage"] == pytest.approx(round(row["coverage"], 3))
    experiment = pd.read_parquet(exported.out / "fact_experiment.parquet")
    aa = sited.site.control["aa"]["m1"]["preregistered"]
    row = experiment[(experiment["metric"] == "m1") & (experiment["test"] == "preregistered") & (experiment["seal_state"] == "sealed")].iloc[0]
    assert aa["p"] == pytest.approx(round(row["aa_p"], 3)) and aa["diff"] == pytest.approx(round(row["aa_diff"], 4))


# --- nothing of the test before the seal ---------------------------------------------------------------------------------------------------------------


@pytest.fixture
def pending(delivered, workbook, quick_cfg, tmp_path):
    """The delivered replay (nothing evaluated, the seal without its test part) exported and its site written."""
    star = export_world(delivered.root, workbook, quick_cfg, tmp_path / "star")
    star.conn.close()
    made = export_site_of(star.world.warehouse_path, star.world, star.view, tmp_path)
    yield made
    made.conn.close()


def test_until_the_test_is_sealed_every_result_of_it_is_empty_or_null(pending):
    site = pending.site
    assert site.summary["evaluation_status"] == "pending" and site.summary["headline"] is None and site.summary["sealed_from"] is None and site.summary["seal"]["test"] is None
    assert [c["passed"] for c in site.summary["criteria"]] == [None] * 10 and [c["tested_value_es"] for c in site.summary["criteria"]] == [None] * 10
    assert all(c["point_value"] is None and c["ci_low"] is None and c["ci_high"] is None for c in site.summary["criteria"]) and all(c["threshold_es"] for c in site.summary["criteria"])
    assert site.algorithms["methods"] == [] and site.algorithms["by_round"] == []
    assert site.control["aa"] is None and site.control["calibration"] is None and site.control["mde"] == []
    assert len(site.algorithms["choice"]) >= 4 and site.algorithms["choice"][0]["val_hit_new"] is not None, "the choice is validation, not the test"
    assert len(site.operation["rounds"]) == 4 and all(r["base"] == 300 for r in site.operation["rounds"]), "the rounds that already ran are follow-up, not the test"
    assert site.control["balance"] and all(b["smd"] is not None for b in site.control["balance"]), "the balance is of the draw, sealed at the launch"


def test_a_configuration_that_is_not_the_sealed_one_publishes_no_result_of_the_test(evaluated, workbook, quick_cfg, tmp_path):
    star = export_world(evaluated.root, workbook, quick_cfg, tmp_path / "star", minimum=11)
    star.conn.close()
    made = export_site_of(star.world.warehouse_path, star.world, star.view, tmp_path)
    try:
        assert made.site.summary["evaluation_status"] == "post_seal" and made.site.summary["headline"] is None and made.site.algorithms["methods"] == [] and made.site.control["aa"] is None
        assert [c["passed"] for c in made.site.summary["criteria"]] == [None] * 10
    finally:
        made.conn.close()


# --- no effect, no path, nothing under the minimum ----------------------------------------------------------------------------------------------------


def test_no_published_field_or_text_claims_an_effect(sited, pending):
    for made in (sited, pending):
        for name in SITE_FILES:
            document = json.loads(text_of(made.out / name))
            for where, key, value in walk(document):
                if key is not None:
                    assert not EFFECT_WORDS.search(key.replace("rule_lift", "")), f"{name}{where}: a field that names an effect"
                elif isinstance(value, str) and EFFECT_WORDS.search(value.replace("rule_lift", "")):
                    assert ALLOWED.search(value.lower()), f"{name}{where}: {value}"


def test_the_envelope_says_that_the_file_has_no_offers(sited):
    assert sited.site.summary["no_effect_note_es"] == "El archivo no tiene ofertas: estas cifras dicen qué anticipa cada lista, no cuánto vende una oferta"
    assert sited.site.control["what_it_cannot_measure_es"] and all(isinstance(t, str) and t.endswith(".") for t in sited.site.control["what_it_cannot_measure_es"])


def test_no_file_holds_a_path_of_this_machine_or_a_number_of_a_customer(sited):
    text = "\n".join(text_of(sited.out / name) for name in (*SITE_FILES, "manifest.json"))
    assert not LOCAL_PATH.search(text) and not re.search(r"(?<![\d.])90[0-3]\d\d(?!\d)", text)


def test_a_count_of_customers_under_the_minimum_is_not_published(sited, evaluated, workbook, quick_cfg, tmp_path):
    """The minimum of a cell is the sealed ``[privacy] min_cell_customers``: with it at 200 (more than the 300 customers' parts) every count of customers is null, with 10 the ones that are bigger are shown."""
    star = export_world(evaluated.root, workbook, quick_cfg, tmp_path / "star", minimum=200)
    star.conn.close()
    made = export_site_of(star.world.warehouse_path, star.world, star.view, tmp_path)
    try:
        shown, hidden = sited.site, made.site
        assert shown.data["customers"]["with_two_or_more_invoices"] is not None and hidden.data["customers"]["with_two_or_more_invoices"] is None or shown.data["customers"]["with_two_or_more_invoices"] >= 200
        assert hidden.control["holdout"]["groups"]["control"] is None and shown.control["holdout"]["groups"]["control"] is not None
        assert all(r["control"] is None for r in hidden.operation["rounds"]) and all(r["buyers_of_listed"] == {"offer": None, "control": None} for r in hidden.operation["rounds"])
    finally:
        made.conn.close()


# --- data, operation, control -----------------------------------------------------------------------------------------------------------------------------


def test_the_data_file_counts_what_the_warehouse_holds_and_what_the_source_took_out(sited):
    data = sited.site.data
    lines = sited.conn.execute("SELECT COUNT(*), COALESCE(SUM(customer_id IS NULL), 0), COALESCE(SUM(internal_repeat), 0) FROM lines").fetchone()
    assert data["source"]["rows_loaded"] == lines[0] and data["source"]["rows_without_customer"] == lines[1] and data["source"]["internal_repeats"] == lines[2]
    assert data["source"]["copies_removed"] == SOURCE_COUNTS["copies_removed"] and data["source"]["rows_by_sheet"] == SOURCE_COUNTS["rows_by_sheet"]
    assert data["source"]["share_without_customer"] == pytest.approx(round(lines[1] / lines[0], 3))
    assert data["roles"] == dict(sited.conn.execute("SELECT role, COUNT(*) FROM lines GROUP BY role ORDER BY role")) and sum(data["roles"].values()) == lines[0]
    assert data["discount_lines"] == sited.conn.execute("SELECT COUNT(*) FROM lines WHERE stock_code = 'D'").fetchone()[0]
    assert data["calendar"]["launch_last_day"] == "2011-03-27" and data["calendar"]["rounds"] == ["R2011-03-28", "R2011-04-04", "R2011-04-11"] and data["calendar"]["censored_round"] == "R2011-04-18"
    assert data["products"]["distinct"] == sited.conn.execute("SELECT COUNT(DISTINCT stock_code) FROM lines WHERE role IN ('purchase', 'guest_purchase')").fetchone()[0]
    assert data["baskets"]["median_products"] >= 1 and data["repurchase"]["share_of_pairs"] is not None and 0 <= data["repurchase"]["share_of_pairs"] <= 1
    assert sum(c["lines"] for c in data["countries"]) <= lines[0] and len(data["countries"]) <= 10


def test_without_the_counts_of_the_source_the_data_file_says_so_and_publishes_none(sited, evaluated, workbook, quick_cfg, tmp_path):
    star = export_world(evaluated.root, workbook, quick_cfg, tmp_path / "star")
    star.conn.close()
    made = export_site_of(star.world.warehouse_path, star.world, star.view, tmp_path, source_counts=None)
    try:
        assert made.site.data["source"]["copies_removed"] is None and made.site.data["source"]["rows_by_sheet"] is None
    finally:
        made.conn.close()


def test_the_operation_of_each_round_is_the_star_table_with_its_hidden_cells_null(sited, exported):
    ops = pd.read_parquet(exported.out / "fact_round_ops.parquet").set_index("round_key")
    rounds = {r["round_key"]: r for r in sited.site.operation["rounds"]}
    assert list(rounds) == sorted(ops.index) and all(set(r) == {"round_key", "monday", "period", "base", "offer", "control", "delivered", "fallback_share", "buyers", "buyers_of_listed", "seconds"} for r in rounds.values())
    for key, row in ops.iterrows():
        assert rounds[key]["base"] == (None if pd.isna(row["base"]) else int(row["base"])) and rounds[key]["fallback_share"] == round(row["fallback_share"], 3)
    assert rounds["R2011-03-28"]["monday"] == "2011-03-28" and rounds["R2011-04-18"]["period"] == "censored"


def test_the_crm_and_the_email_files_are_counted_and_never_read(sited):
    crm = sited.site.operation["crm"]
    row = sited.conn.execute("SELECT COALESCE(SUM(contacts), 0), COALESCE(SUM(created), 0), COALESCE(SUM(unchanged), 0), COALESCE(SUM(conflicts), 0), COALESCE(SUM(readback_equal), 0), COUNT(*) FROM crm_deliveries WHERE status = 'ok'").fetchone()
    assert (crm["lists"], crm["created"], crm["unchanged"], crm["conflicts"], crm["batches_read_back_equal"], crm["batches"]) == row
    email = sited.site.operation["email"]
    csvs = sorted((Path(sited.private_dir) / "email").glob("*.csv"))
    assert email == {"files": len(csvs), "rows": sum(len(p.read_text(encoding="utf-8").splitlines()) - 1 for p in csvs)} and email["files"] == 4


def test_the_example_lists_have_ten_products_with_their_origin_and_no_customer_and_come_from_big_segments(sited):
    lists = sited.site.algorithms["example_lists"]
    assert 1 <= len(lists) <= 3
    for example in lists:
        assert set(example) == {"profile_es", "segment_key", "round_key", "customers_in_segment", "products"} and example["customers_in_segment"] >= 10 and len(example["products"]) == 10
        assert [p["rank"] for p in example["products"]] == list(range(1, 11)) and {p["source_key"] for p in example["products"]} <= {"repeat", "discovery", "fallback"}
        assert all(set(p) == {"rank", "stock_code", "description_es", "source_key"} for p in example["products"])
    assert len({e["segment_key"] for e in lists}) == len(lists), "one list for each profile"


def test_the_rules_example_are_the_ten_of_the_highest_lift_with_the_support_that_the_plan_asks(sited):
    rules = sited.site.algorithms["rules_example"]
    assert len(rules) <= 10 and all(r["support"] >= 50 for r in rules) and [r["rule_lift"] for r in rules] == sorted((r["rule_lift"] for r in rules), reverse=True)
    stored = sited.conn.execute("SELECT COUNT(*) FROM star_fact_rule WHERE support >= 50").fetchone()[0]
    assert len(rules) == min(10, stored)


def test_the_balance_and_the_calibration_and_the_minimum_detectable_difference(sited, evaluated):
    control = sited.site.control
    assert control["holdout"]["share"] == 0.2 and control["holdout"]["strata"] == 18 and set(control["holdout"]["groups"]) == {"offer", "control"}
    assert {b["covariate_key"] for b in control["balance"]} == {"recency_days", "invoices_365", "spend_365", "tenure_days", "bulk"} and all(abs(b["smd"]) <= 1 for b in control["balance"])
    assert set(control["aa"]) == {"m1", "m2"} and set(control["aa"]["m1"]) == {"preregistered", "normal_raw", "normal_cuped"} and set(control["aa"]["m1"]["preregistered"]) == {"diff", "p", "ci_low", "ci_high"}
    assert control["calibration"]["band"] == [0.031, 0.069] and set(control["calibration"]["rejection"]) == {"m1", "m2"} and control["calibration"]["alpha"] == 0.05
    assert [(m["metric"], m["holdout_share"]) for m in control["mde"]] == [(metric, share) for metric in ("m1", "m2") for share in (0.1, 0.2, 0.3)]
    assert control["mde"][0]["holdout_size"] == 30 and control["mde"][0]["mde"] is not None


def test_cumulative_rules_are_read_once_from_the_latest_loaded_run(sited, evaluated, workbook, quick_cfg, tmp_path):
    """A rule that counts something cumulative (``source``, ``latest``) is read once, from the latest loaded run that recorded it, and never summed over the runs (project 03, D94)."""
    star = export_world(evaluated.root, workbook, quick_cfg, tmp_path / "star")
    conn = star.conn
    try:
        conn.execute("DROP TRIGGER validation_results_no_update")
        conn.execute("DROP TRIGGER validation_results_no_delete")
        conn.execute("UPDATE validation_results SET aggregation = 'latest', rows_affected = 5 WHERE rule_id = 'V14'")
        conn.commit()
        v14 = lambda rules: next(r for r in rules if r["rule_id"] == "V14")   # noqa: E731
        made = export_site_of(star.world.warehouse_path, star.world, star.view, tmp_path)
        try:
            runs = conn.execute("SELECT COUNT(*) FROM validation_results v JOIN deliveries d ON d.run_key = v.run_key AND d.status = 'loaded' WHERE v.rule_id = 'V14'").fetchone()[0]
            assert runs == 5 and v14(made.site.validation_rules["rules"])["rows_affected"] == 5, "five runs recorded the rule, and the count is the latest's alone"
        finally:
            made.conn.close()
        conn.execute("UPDATE validation_results SET aggregation = 'per_run' WHERE rule_id = 'V14'")
        conn.commit()
        again = export_site_of(star.world.warehouse_path, star.world, star.view, tmp_path / "again")
        try:
            assert v14(again.site.validation_rules["rules"])["rows_affected"] == 25, "a per-run rule is the sum of its runs"
        finally:
            again.conn.close()
    finally:
        conn.close()


def test_the_rules_are_the_ones_of_the_plan_in_order_with_their_worst_status(sited):
    rules = sited.site.validation_rules["rules"]
    assert [r["rule_id"] for r in rules] == [f"V{n}" for n in range(10, 19)]
    assert all(set(r) == {"rule_id", "name_es", "severity", "scope", "aggregation", "status", "rows_affected"} for r in rules)
    assert {r["rule_id"]: r["status"] for r in rules}["V10"] == "pasa" and sited.site.validation_rules["totals"]["deliveries_loaded"] == 5 and sited.site.validation_rules["totals"]["deliveries_rejected"] == 0


# --- writing and reading the set ----------------------------------------------------------------------------------------------------------------------------


def copy_of(sited, folder: Path) -> Path:
    out = folder / "copy"
    out.mkdir(parents=True)
    for name in (*SITE_FILES, "manifest.json"):
        (out / name).write_bytes((sited.out / name).read_bytes())
    return out


def test_a_failure_in_the_middle_of_the_writes_leaves_a_set_that_is_refused(sited, monkeypatch, tmp_path):
    """The old manifest is removed before the first file is replaced and the new one is written last: a failure between two replacements leaves two files of the new export and four of the old one, with no manifest."""
    out = copy_of(sited, tmp_path)
    before = {name: (out / name).read_bytes() for name in SITE_FILES}
    original = site_export.write_atomic
    calls = []

    def failing(path, data):
        calls.append(Path(path).name)
        if len(calls) == 3:
            raise OSError("disk full")
        return original(path, data)

    monkeypatch.setattr(site_export, "write_atomic", failing)
    with pytest.raises(OSError, match="disk full"):
        site_export.export_site(sited.conn, out, reporting.RunMeta("run-6", RUN.as_of), sited.view, seal_path=sited.seal_path, private_dir=sited.private_dir, max_total_bytes=sited.cap, source_counts=SOURCE_COUNTS)
    assert calls == list(SITE_FILES[:3]) and not (out / "manifest.json").exists()
    problems = site_export.verify_site(out)
    assert problems and "manifest.json" in problems[0]
    with pytest.raises(SiteSetError, match="manifest.json"):
        site_export.read_site(out)
    changed = [name for name in SITE_FILES if (out / name).read_bytes() != before[name]]
    assert changed == list(SITE_FILES[:2]), "two files of the new export and four of the old one: a mixed set that nobody reads"


def test_a_set_with_a_file_of_another_export_is_refused_and_nothing_is_read(sited, tmp_path):
    out = copy_of(sited, tmp_path)
    document = json.loads(text_of(out / "data.json"))
    document["run_key"] = "run-other"
    (out / "data.json").write_text(json.dumps(document, ensure_ascii=False, sort_keys=True, indent=1) + "\n", encoding="utf-8")
    problems = site_export.verify_site(out)
    assert len(problems) == 1 and "data.json" in problems[0] and "SHA-256" in problems[0]
    with pytest.raises(SiteSetError, match="data.json"):
        site_export.read_site(out)
    (out / "summary.json").unlink()
    assert any("falta summary.json" in p for p in site_export.verify_site(out))
    (out / "manifest.json").write_text("{}", encoding="utf-8")
    assert site_export.verify_site(out) and "no se puede leer" in site_export.verify_site(out)[0]


def test_a_set_whose_files_carry_the_envelope_of_another_run_is_refused(sited, tmp_path):
    out = copy_of(sited, tmp_path)
    manifest = json.loads(text_of(out / "manifest.json"))
    document = json.loads(text_of(out / "control.json"))
    document["run_key"] = "run-other"
    raw = (json.dumps(document, ensure_ascii=False, sort_keys=True, indent=1, allow_nan=False) + "\n").encode("utf-8")
    (out / "control.json").write_bytes(raw)
    manifest["files"]["control.json"] = {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
    (out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=1) + "\n", encoding="utf-8")
    assert any("envoltorio" in p for p in site_export.verify_site(out))


def test_a_set_that_would_pass_the_cap_is_refused_before_a_file_is_written(sited, tmp_path):
    out = tmp_path / "capped"
    out.mkdir()
    with pytest.raises(SiteExportError, match="tope"):
        site_export.export_site(sited.conn, out, RUN, sited.view, seal_path=sited.seal_path, private_dir=sited.private_dir, max_total_bytes=3000, source_counts=SOURCE_COUNTS)
    assert list(out.iterdir()) == []


def test_the_export_needs_the_star_model(launched, workbook, quick_cfg, tmp_path):
    from tests.fixtures.worlds import copy_world

    world = copy_world(launched.root, workbook, quick_cfg, tmp_path / "bare")
    try:
        with pytest.raises(SiteExportError, match="modelo estrella"):
            site_export.export_site(world.conn, tmp_path / "site", RUN, world.view, seal_path=world.seal_path, private_dir=world.cfg.paths.private_dir, max_total_bytes=204800)
        assert not (tmp_path / "site").exists()
    finally:
        world.conn.close()


def test_closing_a_run_rewrites_only_the_summary_and_the_manifest(sited, tmp_path):
    out = copy_of(sited, tmp_path)
    before = {name: (out / name).read_bytes() for name in SITE_FILES}
    conn = connect(sited.conn.execute("PRAGMA database_list").fetchone()[2])
    try:
        conn.execute("UPDATE pipeline_runs SET status = 'ok' WHERE run_key = ?", (RUN.run_key,)) if conn.execute("SELECT 1 FROM pipeline_runs WHERE run_key = ?", (RUN.run_key,)).fetchone() else conn.execute(
            "INSERT INTO pipeline_runs (run_key, started_at, status) VALUES (?, '2011-04-23 00:00:00', 'ok')", (RUN.run_key,))
        conn.commit()
        path = site_export.export_summary(conn, out, RUN, sited.view, seal_path=sited.seal_path, max_total_bytes=sited.cap)
    finally:
        conn.close()
    assert path.name == "summary.json" and site_export.verify_site(out) == []
    assert json.loads(text_of(out / "summary.json"))["status"] == "ok" and json.loads(text_of(sited.out / "summary.json"))["status"] == "running"
    assert all((out / name).read_bytes() == before[name] for name in SITE_FILES if name != "summary.json")


def test_closing_a_run_does_not_write_over_a_set_that_is_not_one_export_or_is_of_another_run(sited, tmp_path):
    out = copy_of(sited, tmp_path)
    (out / "manifest.json").unlink()
    with pytest.raises(SiteExportError, match="no se reescribe"):
        site_export.export_summary(sited.conn, out, RUN, sited.view, seal_path=sited.seal_path, max_total_bytes=sited.cap)
    assert not (out / "manifest.json").exists()
    out2 = copy_of(sited, tmp_path / "two")
    with pytest.raises(SiteExportError, match="otra corrida"):
        site_export.export_summary(sited.conn, out2, reporting.RunMeta("run-6", RUN.as_of), sited.view, seal_path=sited.seal_path, max_total_bytes=sited.cap)


@pytest.mark.parametrize("minimum", [32, 33, 60])
def test_the_minimum_of_a_cell_is_the_sealed_one_and_a_cell_that_reaches_it_is_shown(minimum, sited, evaluated, workbook, quick_cfg, tmp_path):
    """A count equal to the minimum is shown and one under it is not: the base has profiles of 268 and 32 customers (the second is an example list with a minimum of 32 and not with 33) and the control group has
    exactly 60 customers."""
    star = export_world(evaluated.root, workbook, quick_cfg, tmp_path / "star", minimum=minimum)
    star.conn.close()
    made = export_site_of(star.world.warehouse_path, star.world, star.view, tmp_path)
    try:
        lists = made.site.algorithms["example_lists"]
        assert [(e["segment_key"], e["customers_in_segment"]) for e in lists] == [("retail|repeat", 268), ("retail|one_invoice", 32)][: 2 if minimum == 32 else 1]
        assert made.site.control["holdout"]["groups"] == {"offer": 240, "control": 60} and made.site.data["customers"]["with_a_purchase"] == 300
        assert made.site.data["bulk"]["customers_in_the_launch_base"] == 300
    finally:
        made.conn.close()
