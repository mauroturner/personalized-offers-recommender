"""The star model for Power BI (U15; RF20, AC26; decisions D30, D37; risk item 3: a contract that others consume; plan section 19): eleven dimensions and fourteen facts with their keys, the 20 relationships (one to many,
single direction, active), the marts that fill them from the warehouse, the controls that undo them and the Parquet files with the schema of the specification, the run and the attribution in their metadata."""

from __future__ import annotations

import dataclasses
import json
import shutil
import sqlite3
from datetime import datetime
from html import escape
from pathlib import Path

import numpy as np
import pyarrow.parquet as pq
import pytest

from personaloffers import export, reporting, texts, warehouse
from personaloffers.dashboard.semantic_model import ARROW_TYPES, MODEL, RELATIONSHIP_SPEC, arrow_schema, validate_model
from personaloffers.export import STAR_MANIFEST, export_run_table, export_star_schema, verify_star_schema
from personaloffers.recommend import rules
from personaloffers.warehouse import CheckFailedError
from tests.fixtures.stars import RUN, export_world, with_minimum
from tests.fixtures.worlds import copy_world


def read(folder: Path, name: str):
    return pq.read_table(Path(folder) / f"{name}.parquet")


def frame(folder: Path, name: str):
    return read(folder, name).to_pandas()


def test_every_relationship_is_one_to_many_single_and_keys_exist(exported):
    """AC26: the model of the plan is coherent, and in the files that were written every key is unique and not empty, every relationship is one to many, single and active, and every foreign key is a key of its dimension."""
    tables = {t.name: t for t in MODEL.tables}
    assert len(MODEL.relationships) == 20 and {r.rel_id: (r.dim_table, r.fact_table, r.fact_column) for r in MODEL.relationships} == RELATIONSHIP_SPEC and validate_model(MODEL) == []
    for r in MODEL.relationships:
        dim, fact = tables[r.dim_table], tables[r.fact_table]
        assert (r.cardinality, r.cross_filter, r.active) == ("one_to_many", "single", True) and dim.kind == "dimension" and fact.kind == "fact" and dim.key == (r.dim_column,), r.rel_id
        keys = set(frame(exported.out, dim.name)[r.dim_column])
        values = frame(exported.private if fact.private else exported.out, fact.name)[r.fact_column]
        assert values.notna().all() and set(values) <= keys, f"{r.rel_id}: every {fact.name}[{r.fact_column}] is a key of {dim.name}"
    for table in MODEL.tables:
        data = frame(exported.private if table.private else exported.out, table.name)
        assert not data[list(table.key)].isna().any().any() and not data.duplicated(list(table.key)).any(), f"{table.name}: the key is unique and whole"


def test_the_files_are_the_tables_of_the_model_with_the_schema_of_the_specification_and_the_run_in_their_metadata(exported):
    assert sorted(p.name for p in exported.out.glob("*.parquet")) == sorted(f"{t.name}.parquet" for t in MODEL.public)
    assert [p.name for p in exported.private.glob("*.parquet")] == ["fact_offer_customer.parquet"] and len(exported.paths) == 25
    for table in MODEL.tables:
        file = pq.read_table((exported.private if table.private else exported.out) / f"{table.name}.parquet")
        assert file.schema.remove_metadata().equals(arrow_schema(table)) and file.column_names == list(table.column_names), table.name
        meta = {k.decode(): v.decode() for k, v in file.schema.metadata.items() if k.decode().startswith("personaloffers.")}
        assert set(meta) == set(export.METADATA_KEYS) and meta["personaloffers.run_key"] == "run-5" and meta["personaloffers.as_of"] == "2011-04-23 00:00:00" and len(meta["personaloffers.config_sha256"]) == 64
        assert meta["personaloffers.attribution"] == texts.ATTRIBUTION and "doi.org/10.24432/C5CG6D" in meta["personaloffers.attribution"] and "CC BY 4.0" in meta["personaloffers.attribution"]
    assert {c.dtype for t in MODEL.tables for c in t.columns} <= set(ARROW_TYPES)


def test_no_published_table_has_a_column_of_customer_and_the_one_that_has_it_is_in_the_private_folder(exported):
    for table in MODEL.public:
        assert not [c for c in read(exported.out, table.name).column_names if "customer" in c.replace("customers", "")], table.name
    private = frame(exported.private, "fact_offer_customer")
    assert list(private.columns) == list(MODEL.table("fact_offer_customer").column_names) and private["customer_id"].nunique() == 300 and len(private) == 12000, "four rounds, 300 customers, ten products"
    assert str(exported.private) != str(exported.out) and not list(exported.out.rglob("*private*"))
    manifest = json.loads((exported.out / STAR_MANIFEST).read_text(encoding="utf-8"))
    assert "fact_offer_customer.parquet" not in {f["name"] for f in manifest["files"]}


def test_the_dimensions_are_what_the_warehouse_and_the_code_hold(exported):
    conn = sqlite3.connect(exported.world.warehouse_path)
    try:
        rounds = frame(exported.out, "dim_round")
        assert list(rounds["round_key"]) == [r[0] for r in conn.execute("SELECT round_id FROM rounds ORDER BY round_id")] and list(rounds["period"]) == ["test", "test", "test", "censored"]
        assert list(rounds["days_observed"]) == [7, 7, 7, 5] and [str(d) for d in rounds["monday"]] == ["2011-03-28", "2011-04-04", "2011-04-11", "2011-04-18"]
        products = frame(exported.out, "dim_product")
        assert len(products) == conn.execute("SELECT COUNT(*) FROM products").fetchone()[0] and products["popularity_band"].between(0, 10).all()
        launch = dict(conn.execute("SELECT stock_code, launch_invoices FROM products"))
        by_invoices = products.assign(n=products["product_key"].map(launch)).query("n > 0").groupby("popularity_band")["n"].agg(["min", "max"]).sort_index()
        assert list(by_invoices["max"].iloc[:-1] <= by_invoices["min"].iloc[1:].to_numpy()) == [True] * (len(by_invoices) - 1), "a higher band never has fewer invoices"
        assert (products.loc[products["product_key"].map(launch) == 0, "popularity_band"] == 0).all() and products["popularity_band"].max() == 10
        assert list(frame(exported.out, "dim_method")["method_key"]) == sorted(texts.METHOD_LABELS) and list(frame(exported.out, "dim_variant")["variant_key"]) == ["new_only", "unrestricted"]
        assert list(frame(exported.out, "dim_source")["source_key"]) == ["discovery", "fallback", "repeat"] and list(frame(exported.out, "dim_group")["group_key"]) == ["control", "offer"]
        assert len(frame(exported.out, "dim_segment")) == 4 and list(frame(exported.out, "dim_covariate")["covariate_key"]) == ["bulk", "invoices_365", "recency_days", "spend_365", "tenure_days"]
        criteria = frame(exported.out, "dim_criterion")
        assert list(criteria["criterion_key"]) == [f"C{n:02d}" for n in range(1, 11)] and list(criteria["threshold_es"]) == [texts.thresholds_from(dataclasses.asdict(exported.view.criteria))[f"C{n:02d}"] for n in range(1, 11)]
        dates = frame(exported.out, "dim_date")
        assert dates["date_key"].is_monotonic_increasing and int(dates["date_key"].iloc[0]) == 20101206 and int(dates["date_key"].iloc[-1]) == 20110422
        assert set(dates["period"]) == {"history", "validation", "test", "close"} and (dates.loc[dates["date_key"] == 20110328, "period"] == "test").all() and (dates.loc[dates["date_key"] == 20110327, "period"] == "validation").all()
        runs = frame(exported.out, "dim_pipeline_run")
        assert list(runs["run_key"]) == [r[0] for r in conn.execute("SELECT run_key FROM pipeline_runs ORDER BY run_key")] and runs["started_at"].notna().all()
    finally:
        conn.close()


def test_the_facts_with_nothing_hidden_are_the_warehouse_by_hand(evaluated, workbook, quick_cfg, tmp_path):
    """With a minimum of 3 customers the fixture's cells are shown and each number is recomputed here from the tables of the flow with nothing of the export."""
    star = export_world(evaluated.root, workbook, quick_cfg, tmp_path, minimum=3)
    conn = star.conn
    try:
        ops = frame(star.out, "fact_round_ops").set_index("round_key")
        for round_id, base, offer, control, new, delivered, fallback, seconds in conn.execute("SELECT round_id, base, offer, control, new_assignments, delivered, fallback_share, seconds FROM round_ops"):
            row = ops.loc[round_id]
            assert (row["base"], row["offer"], row["control"], row["delivered"]) == (base, offer, control, delivered) and row["fallback_share"] == pytest.approx(fallback) and row["seconds"] == pytest.approx(seconds)
        assert ops["new_assignments"].isna().all() and ops["suppressed"].all(), "no newcomers in the fixture: the cell is a zero, fewer than the minimum, and is hidden"
        group = frame(star.out, "fact_round_group").set_index(["round_key", "group_key", "segment_key"])
        hand = conn.execute("SELECT c.round_id, h.grp, c.segment, COUNT(*), SUM(o.bought), SUM(o.products_in_offer > 0), SUM(CAST(o.spend AS REAL)) FROM contact_base c JOIN holdout_assignments h ON h.customer_id = c.customer_id "
                            "JOIN round_outcomes o ON o.round_id = c.round_id AND o.customer_id = c.customer_id GROUP BY 1, 2, 3").fetchall()
        shown = 0
        for round_id, grp, segment, customers, buyers, listed, spend in hand:
            row = group.loc[(round_id, grp, segment)]
            if not row["suppressed"]:
                assert (row["customers"], row["buyers"], row["buyers_of_listed"]) == (customers, buyers, listed) and row["spend"] == pytest.approx(round(spend, 2))
                shown += 1
        assert shown >= 2 and len(group) == len(hand)
        offered = frame(star.out, "fact_offer_product")
        by_hand = {}
        for round_id, code, source, customer in conn.execute("SELECT round_id, stock_code, source, customer_id FROM offer_lists WHERE grp = 'offer'"):
            by_hand.setdefault((round_id, code, source), set()).add(customer)
        bought = {(r, c, s) for r, c, s in conn.execute("SELECT round_id, customer_id, stock_code FROM ref_week_purchase")}
        for row in offered.itertuples():
            customers = by_hand[(row.round_key, row.product_key, row.source_key)]
            assert row.offered_to == len(customers) >= 3
            if not row.suppressed:
                assert row.bought_by == sum(1 for c in customers if (row.round_key, c, row.product_key) in bought)
        totals = frame(star.out, "fact_method_total").set_index(["method_key", "variant_key", "seal_state"])
        for method, variant, state, pairs, hit, low, high, recall, precision, ndcg, coverage in conn.execute("SELECT method, variant, seal_state, pairs, hit_rate, ci_low, ci_high, recall, precision, ndcg, coverage FROM eval_methods WHERE round_id = 'all'"):
            row = totals.loc[(method, variant, state)]
            assert (row["pairs"], row["hit_rate"], row["ci_low"], row["ci_high"], row["recall"], row["precision"], row["ndcg"], row["coverage"]) == pytest.approx((pairs, hit, low, high, recall, precision, ndcg, coverage))
        assert len(totals) == 17 and set(frame(star.out, "fact_method_round")["round_key"]) == set(ops.index)
        choice = frame(star.out, "fact_choice")
        candidates = json.loads(star.world.seal_path.read_text(encoding="utf-8"))["launch"]["validation"]["candidates"]
        assert sorted(choice["candidate"]) == sorted(c["name"] for c in candidates) and choice["chosen"].sum() == 1 and (choice["fit_rounds"] == 2).all()
        chosen = next(c for c in candidates if c["chosen"])
        assert choice.set_index("candidate").loc[chosen["name"], "val_hit_new"] == pytest.approx(chosen["hit_new"])
        validation = frame(star.out, "fact_validation")
        stored = {(r[0], r[1]): ("pasa" if r[2] else "falla", r[3]) for r in conn.execute("SELECT run_key, rule_id, passed, severity FROM validation_results")}
        assert {(r.run_key, r.rule_id): (r.status, r.severity) for r in validation.itertuples()} == stored and len(validation) == len(stored)
        assert not [r for r in validation.itertuples() if r.severity == "bloqueante" and r.status == "falla"], "a delivery that was loaded passed every blocking rule"
        balance = frame(star.out, "fact_balance")
        assert len(balance) == 5 and balance["smd"].abs().max() == pytest.approx(star.world.conn.execute("SELECT MAX(ABS(smd)) FROM eval_balance").fetchone()[0])
        assert len(frame(star.out, "fact_experiment")) == 6 and len(frame(star.out, "fact_mde")) == 6
    finally:
        conn.close()


def test_the_pair_rules_are_the_ones_with_the_highest_lift_and_enough_support_of_the_launch_history(evaluated, workbook, quick_cfg, tmp_path, monkeypatch):
    monkeypatch.setattr(export, "RULES_MIN_SUPPORT", 5)
    monkeypatch.setattr(export, "RULES_TOP", 12)
    star = export_world(evaluated.root, workbook, quick_cfg, tmp_path)
    try:
        found = frame(star.out, "fact_rule")
        assert 0 < len(found) <= 12 and (found["support"] >= 5).all() and (found["rule_lift"] > 1.0).all()
        lines = warehouse.read_lines(star.conn)
        history = lines[lines["invoice_date"] < datetime(2011, 3, 28)]
        codes = np.array(sorted(history["stock_code"].dropna().astype(str).unique()))
        every = rules.select(rules.pair_counts(history, datetime(2011, 3, 28).date(), codes), 5, 1.0)
        best = sorted(zip(every.rule_lift, every.support, codes[every.antecedent], codes[every.consequent], strict=True), key=lambda r: (-r[0], -r[1], r[2], r[3]))[:12]
        assert sorted(zip(found["antecedent_key"], found["consequent_key"])) == sorted((a, c) for _, _, a, c in best)
        descriptions = dict(star.conn.execute("SELECT stock_code, description_es FROM products"))
        assert all(row.antecedent_es == descriptions[row.antecedent_key] and row.consequent_es == descriptions[row.consequent_key] for row in found.itertuples())
        assert set(found["antecedent_key"]) | set(found["consequent_key"]) <= set(frame(star.out, "dim_product")["product_key"])
    finally:
        star.conn.close()


def test_the_verdict_text_in_the_parquet_and_the_design_is_the_summary_text(exported, rendered):
    """N2 of project 07: what the star model and the design tell of each criterion is what the summary tells, word for word, and the design's table has the column of what the threshold tests."""
    conn = sqlite3.connect(exported.world.warehouse_path)
    try:
        summary = reporting.build_summary(conn, exported.view, seal_path=exported.world.seal_path)
    finally:
        conn.close()
    table = frame(exported.out, "fact_evaluation_summary").set_index(["criterion_key", "seal_state"])
    assert len(table) == 10
    for c in summary["criteria"]:
        row = table.loc[(c["criterion_id"], "sealed")]
        assert row["verdict_es"] == c["verdict_es"] and row["tested_value_es"] == c["tested_value_es"] and (row["passed"] is None or bool(row["passed"]) == c["passed"] or (c["passed"] is None and row["passed"] != row["passed"]))
        assert row["seen_by_research"] == c["seen_by_research"] and row["seen_by_planner"] == c["seen_by_planner"]
        assert escape(c["verdict_es"]) in rendered.html and escape(c["tested_value_es"]) in rendered.html and escape(c["threshold_es"]) in rendered.html, c["criterion_id"]
    assert "Lo que prueba el umbral" in rendered.html and "<th>Valor</th>" not in rendered.html


def test_before_the_close_the_tables_of_the_test_are_empty_and_the_validation_is_there(delivered, workbook, quick_cfg, tmp_path):
    star = export_world(delivered.root, workbook, quick_cfg, tmp_path)
    try:
        for name in ("fact_method_round", "fact_method_total", "fact_segment", "fact_balance", "fact_experiment", "fact_mde", "fact_evaluation_summary"):
            assert len(read(star.out, name)) == 0 and read(star.out, name).schema.remove_metadata().equals(arrow_schema(MODEL.table(name))), name
        assert len(read(star.out, "fact_choice")) == 6 and len(read(star.out, "fact_round_ops")) == 4 and len(read(star.out, "fact_offer_product")) > 0
        assert verify_star_schema(star.out) == []
    finally:
        star.conn.close()


# --- the controls undo it ------------------------------------------------------------------------------------------------------------------


def test_a_control_that_finds_a_row_undoes_the_marts_and_writes_no_file(evaluated, workbook, quick_cfg, tmp_path, monkeypatch):
    first = export_world(evaluated.root, workbook, quick_cfg, tmp_path / "first")
    before = first.conn.execute("SELECT COUNT(*) FROM star_fact_round_ops").fetchone()[0]
    marts_before = sorted(r[0] for r in first.conn.execute("SELECT name FROM sqlite_master WHERE name LIKE 'star\\_%' ESCAPE '\\'"))
    broken = tmp_path / "sql"
    shutil.copytree(warehouse.SQL_DIR, broken)
    (broken / "checks" / "model" / "chk_Z99_always_fails.sql").write_text("SELECT 'x' AS broken\n", encoding="utf-8")
    monkeypatch.setattr(warehouse, "SQL_DIR", broken)
    other = tmp_path / "other"
    with pytest.raises(CheckFailedError, match="chk_Z99_always_fails"):
        export_star_schema(first.conn, other / "powerbi", other / "private", MODEL, RUN, first.view, seal_path=first.world.seal_path)
    assert not other.exists(), "no file was written"
    assert first.conn.execute("SELECT COUNT(*) FROM star_fact_round_ops").fetchone()[0] == before
    assert sorted(r[0] for r in first.conn.execute("SELECT name FROM sqlite_master WHERE name LIKE 'star\\_%' ESCAPE '\\'")) == marts_before and not first.conn.in_transaction
    first.conn.close()


def test_each_control_of_the_model_finds_the_row_it_was_written_for(exported):
    """A mutation of a mart is caught by its control: the tables are changed by hand, in a copy of the database, and the control of that rule says the table and the cell."""
    conn = sqlite3.connect(exported.world.warehouse_path)
    conn.execute("PRAGMA foreign_keys=OFF")
    params = {"min_cell_customers": 10}
    cases = {
        "chk_R01_fact_round_ops_round_key": "UPDATE star_fact_round_ops SET round_key = 'R1999-01-04' WHERE round_key = 'R2011-03-28'",
        "chk_R14_fact_offer_product_source_key": "UPDATE star_fact_offer_product SET source_key = 'luck' WHERE rowid = 1",
        "chk_K01_every_key_is_unique_and_not_null": "INSERT INTO star_dim_group SELECT * FROM star_dim_group LIMIT 1",
        "chk_K02_a_hidden_cell_holds_no_number": "UPDATE star_fact_round_group SET customers = 40 WHERE suppressed = 1",
        "chk_K03_no_shown_cell_counts_fewer_customers_than_the_minimum": "UPDATE star_fact_method_total SET pairs = 3, suppressed = 0 WHERE rowid = 1",
        "chk_K04_a_group_never_hides_just_one_cell": "UPDATE star_fact_segment SET suppressed = 0 WHERE method_key = 'b0' AND variant_key = 'new_only' AND segment_key = 'retail|repeat'",
        "chk_K05_the_operation_of_a_round_adds_up": "UPDATE star_fact_round_ops SET offer = 241, suppressed = 0",
        "chk_K06_every_rate_is_a_rate_and_every_interval_holds_its_rate": "UPDATE star_fact_method_total SET hit_rate = 1.5 WHERE rowid = 1",
    }
    try:
        for control, damage in cases.items():
            conn.execute("BEGIN")
            if control.startswith("chk_K04"):
                conn.execute("UPDATE star_fact_segment SET suppressed = 1, pairs = NULL, hit_rate = NULL, ci_low = NULL, ci_high = NULL WHERE method_key = 'b0' AND variant_key = 'new_only' AND segment_key = 'retail|one_invoice'")
            conn.execute(damage)
            found = warehouse.run_checks(conn, "model", params, only=[control])
            assert found[0].violations > 0, control
            conn.execute("ROLLBACK")
        assert not [c for c in warehouse.run_checks(conn, "model", params) if c.violations], "the export as it was passes every control"
    finally:
        conn.close()


# --- the manifest and the run table ------------------------------------------------------------------------------------------------------


def test_the_manifest_lists_every_published_file_with_its_bytes_and_hash_and_is_written_last(exported):
    assert verify_star_schema(exported.out) == []
    manifest = json.loads((exported.out / STAR_MANIFEST).read_text(encoding="utf-8"))
    assert manifest["version"] == 1 and manifest["run_key"] == "run-5" and [f["name"] for f in manifest["files"]] == [f"{t.name}.parquet" for t in MODEL.public]
    assert (exported.out / STAR_MANIFEST).stat().st_mtime_ns >= max(p.stat().st_mtime_ns for p in exported.out.glob("*.parquet")) - 1_000_000


def test_a_set_that_changed_or_that_was_left_half_written_is_refused(exported, tmp_path):
    folder = tmp_path / "copy"
    shutil.copytree(exported.out, folder)
    assert verify_star_schema(folder) == []
    (folder / "dim_group.parquet").write_bytes((folder / "dim_group.parquet").read_bytes() + b"x")
    assert verify_star_schema(folder) == ["dim_group.parquet: los bytes no son los del manifiesto"]
    (folder / "dim_source.parquet").unlink()
    (folder / "extra.parquet").write_bytes(b"x")
    assert sorted(verify_star_schema(folder)) == ["dim_group.parquet: los bytes no son los del manifiesto", "dim_source.parquet: falta el archivo que lista el manifiesto", "extra.parquet: el manifiesto no lo lista"]
    (folder / STAR_MANIFEST).unlink()
    assert "manifiesto legible" in verify_star_schema(folder)[0]


def test_a_failure_while_the_files_are_written_leaves_a_set_without_a_manifest_that_is_refused(evaluated, workbook, quick_cfg, tmp_path, monkeypatch):
    star = export_world(evaluated.root, workbook, quick_cfg, tmp_path / "first")
    calls = []
    real = export.write_atomic

    def failing(path, data):
        calls.append(path)
        if len(calls) == 8:
            raise OSError("disk full")
        return real(path, data)

    monkeypatch.setattr(export, "write_atomic", failing)
    with pytest.raises(OSError, match="disk full"):
        export_star_schema(star.conn, star.out, star.private, MODEL, reporting.RunMeta("run-6", datetime(2011, 4, 24)), star.view, seal_path=star.world.seal_path)
    assert not (star.out / STAR_MANIFEST).exists() and "manifiesto legible" in verify_star_schema(star.out)[0]
    star.conn.close()


def test_a_file_over_the_limit_is_an_error_before_anything_is_written(evaluated, workbook, quick_cfg, tmp_path, monkeypatch):
    world = copy_world(evaluated.root, workbook, quick_cfg, tmp_path / "w")
    monkeypatch.setattr(export, "MAX_PARQUET_BYTES", 2000)
    with pytest.raises(ValueError, match="pesa"):
        export_star_schema(world.conn, tmp_path / "out", tmp_path / "private", MODEL, RUN, world.view, seal_path=world.seal_path)
    assert not (tmp_path / "out").exists() and not (tmp_path / "private").exists()
    world.conn.close()


def test_an_incoherent_model_is_refused_before_the_marts_are_touched(evaluated, workbook, quick_cfg, tmp_path):
    world = copy_world(evaluated.root, workbook, quick_cfg, tmp_path / "w")
    bad = dataclasses.replace(MODEL, relationships=(dataclasses.replace(MODEL.relationships[0], cardinality="many_to_many"), *MODEL.relationships[1:]))
    with pytest.raises(ValueError, match="incoherente"):
        export_star_schema(world.conn, tmp_path / "out", tmp_path / "private", bad, RUN, world.view, seal_path=world.seal_path)
    assert not (tmp_path / "out").exists() and world.conn.execute("SELECT COUNT(*) FROM sqlite_master WHERE name = 'star_dim_group'").fetchone()[0] == 0
    world.conn.close()


def test_the_same_run_exports_the_same_bytes(evaluated, workbook, quick_cfg, tmp_path):
    first = export_world(evaluated.root, workbook, quick_cfg, tmp_path / "a")
    second = export_world(evaluated.root, workbook, quick_cfg, tmp_path / "b")
    for table in MODEL.tables:
        folder_a, folder_b = (first.private, second.private) if table.private else (first.out, second.out)
        assert (folder_a / f"{table.name}.parquet").read_bytes() == (folder_b / f"{table.name}.parquet").read_bytes(), table.name
    assert (first.out / STAR_MANIFEST).read_bytes() == (second.out / STAR_MANIFEST).read_bytes()
    first.conn.close()
    second.conn.close()


def test_closing_a_run_rewrites_only_the_run_table_and_its_line_of_the_manifest(evaluated, workbook, quick_cfg, tmp_path):
    star = export_world(evaluated.root, workbook, quick_cfg, tmp_path)
    before = {p.name: p.read_bytes() for p in star.out.glob("*.parquet")}
    star.conn.execute("UPDATE pipeline_runs SET status = 'ok', finished_at = '2011-04-23 09:00:00' WHERE run_key = 'run-4'")
    path = export_run_table(star.conn, star.out, MODEL, reporting.RunMeta("run-4", datetime(2011, 4, 23, 9)), star.view)
    assert path == star.out / "dim_pipeline_run.parquet" and verify_star_schema(star.out) == []
    after = {p.name: p.read_bytes() for p in star.out.glob("*.parquet")}
    assert [n for n in after if after[n] != before[n]] == ["dim_pipeline_run.parquet"]
    runs = frame(star.out, "dim_pipeline_run").set_index("run_key")
    assert runs.loc["run-4", "status"] == "ok" and str(runs.loc["run-4", "finished_at"]) == "2011-04-23 09:00:00"
    (star.out / "dim_group.parquet").write_bytes(b"changed")
    assert export_run_table(star.conn, star.out, MODEL, RUN, star.view) is None and (star.out / "dim_group.parquet").read_bytes() == b"changed", "a set that does not verify is left as it is"
    (star.out / STAR_MANIFEST).unlink()
    assert export_run_table(star.conn, star.out, MODEL, RUN, star.view) is None
    star.conn.close()


def test_a_shown_cell_exists_in_the_files_with_the_minimum_of_the_configuration_and_a_lower_one_shows_more(evaluated, workbook, quick_cfg, tmp_path):
    default = export_world(evaluated.root, workbook, quick_cfg, tmp_path / "d")
    lower = export_world(evaluated.root, workbook, quick_cfg, tmp_path / "l", minimum=3)
    assert with_minimum(default.view, 3).privacy.min_cell_customers == 3
    shown = lambda star, name: int((~frame(star.out, name)["suppressed"]).sum())  # noqa: E731
    assert shown(lower, "fact_round_group") > shown(default, "fact_round_group") and shown(lower, "fact_offer_product") > shown(default, "fact_offer_product")
    assert len(frame(lower.out, "fact_offer_product")) > len(frame(default.out, "fact_offer_product")), "a lower minimum has more products offered to enough customers"
    default.conn.close()
    lower.conn.close()
