"""The warehouse and the load of a delivery (U06; AC17 in part; RF14; plan section 5; decisions D24, D29): a load is one transaction that registers the delivery, the validation,
the run, the lines and the new products, runs the controls and rolls everything back, the schema included, if any of them has a row; the tables of the flow are insert-only in
the database itself; and the runner keeps the rules of projects 01 to 07 (autocommit, explicit transactions, no ``executescript``)."""

from __future__ import annotations

import dataclasses
import hashlib
import shutil
import sqlite3
import types
from datetime import datetime
from decimal import Decimal
from pathlib import Path

import pandas as pd
import pytest

from personaloffers import deliveries as dv
from personaloffers import validate as val
from personaloffers import warehouse
from personaloffers.config import SealedConfig
from personaloffers.lines import PRODUCT_ROLES, ROLES
from personaloffers.warehouse import (
    CheckFailedError,
    DeliveryAlreadyLoadedError,
    LoadRefusedError,
    SchemaDriftError,
    apply_schema,
    connect,
    load_delivery,
    run_checks,
    split_statements,
)
from tests.fixtures.configs import config_for
from tests.fixtures.hand_lines import hand_frame

STARTED = datetime(2011, 4, 4, 8, 30, 15)
SHA = "a" * 64
CONFIG_SHA = "d" * 64
LOAD_CHECKS = ["chk_delivery_rows_match", "chk_guest_is_not_a_customer", "chk_lines_inside_their_delivery", "chk_run_matches_delivery", "chk_validation_complete",
               "chk_validation_passed"]
CORE_INSERT_ONLY = ["validation_results", "lines", "products"]
FLOW_TABLES = ["rounds", "contact_base", "holdout_assignments", "model_registry", "offer_lists", "baseline_lists", "round_outcomes", "crm_deliveries", "round_ops"]


def build(cfg, lines, plan):
    return {spec.delivery_id: dv.publish_delivery(cfg, lines, spec) for spec in plan}


@pytest.fixture(scope="module")
def template(workbook, quick_cfg, fixture_lines, tmp_path_factory):
    """The fixture's deliveries published once and a warehouse with the launch loaded by ``run-1``, built once for the module: a test copies them (each load fsyncs, and every test that
    starts from a loaded launch would pay it again)."""
    root = tmp_path_factory.mktemp("load_template")
    cfg = config_for(quick_cfg, workbook, root / "project")
    view = SealedConfig.of(cfg, "a" * 64, "b" * 64, "c" * 64)
    plan = dv.delivery_plan(view)
    build(cfg, fixture_lines, plan)
    conn = connect(root / "wh" / "personaloffers.sqlite")
    spec = plan[0]
    path = dv.delivery_path(cfg, spec)
    report = val.validate_delivery(spec, path, conn, view, run_key="run-1")
    load_delivery(conn, spec, dv.read_delivery(path), report, "run-1", started_at=STARTED, config_sha256=CONFIG_SHA)
    conn.close()
    return root


def make_world(template, workbook, quick_cfg, fixture_lines, tmp_path, *, launched: bool):
    cfg = config_for(quick_cfg, workbook, tmp_path / "project")
    shutil.copytree(template / "project", cfg.project_root, dirs_exist_ok=True)
    if launched:
        (tmp_path / "wh").mkdir()
        shutil.copyfile(template / "wh" / "personaloffers.sqlite", tmp_path / "wh" / "personaloffers.sqlite")
    view = SealedConfig.of(cfg, "a" * 64, "b" * 64, "c" * 64)
    plan = dv.delivery_plan(view)
    entries = dv.read_manifest(dv.deliveries_dir(cfg) / dv.MANIFEST_NAME)["deliveries"]
    return types.SimpleNamespace(cfg=cfg, view=view, plan=plan, entries=entries, conn=connect(tmp_path / "wh" / "personaloffers.sqlite"), lines=fixture_lines, tmp=tmp_path)


@pytest.fixture
def world(template, workbook, quick_cfg, fixture_lines, tmp_path):
    """The deliveries published and an empty warehouse."""
    made = make_world(template, workbook, quick_cfg, fixture_lines, tmp_path, launched=False)
    yield made
    made.conn.close()


@pytest.fixture
def loaded(template, workbook, quick_cfg, fixture_lines, tmp_path):
    """The deliveries published and a warehouse in which ``run-1`` loaded the launch."""
    made = make_world(template, workbook, quick_cfg, fixture_lines, tmp_path, launched=True)
    yield made
    made.conn.close()


def db_path(conn) -> Path:
    return Path(conn.execute("PRAGMA database_list").fetchone()[2])


def file_hash(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest() if Path(path).exists() else ""


def tables(conn) -> list[str]:
    return [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]


def load_next(world, run_key="run-1"):
    """Validate and load the next delivery of the plan that is not loaded (what the tasks ``validate`` and ``load`` do, in this order)."""
    spec = dv.next_to_load(world.plan, val.loaded_ids(world.conn))
    path = dv.delivery_path(world.cfg, spec)
    report = val.validate_delivery(spec, path, world.conn, world.view, run_key=run_key)
    return spec, load_delivery(world.conn, spec, dv.read_delivery(path), report, run_key, started_at=STARTED, config_sha256=CONFIG_SHA)


def load_frame(world, spec, frame, run_key="run-1"):
    """Publish `frame` as the delivery `spec`, validate it and load it."""
    dv.publish_frame(world.cfg, spec, frame)
    path = dv.delivery_path(world.cfg, spec)
    report = val.validate_delivery(spec, path, world.conn, world.view, run_key=run_key)
    return load_delivery(world.conn, spec, dv.read_delivery(path), report, run_key, started_at=STARTED, config_sha256=CONFIG_SHA)


@pytest.fixture
def broken_check(tmp_path, monkeypatch):
    """The SQL folder copied with one more control of the load that always finds a row."""
    copy = tmp_path / "sql"
    shutil.copytree(warehouse.SQL_DIR, copy)
    (copy / "checks" / "load" / "chk_zz_always_fails.sql").write_text("SELECT 'x' AS broken\n", encoding="utf-8")
    monkeypatch.setattr(warehouse, "SQL_DIR", copy)
    return copy


def test_failed_check_rolls_back_a_first_load(world, broken_check):
    """The first load of a warehouse with a control that finds a row leaves no table behind (the schema is created inside the transaction) and no row."""
    before = file_hash(db_path(world.conn))
    with pytest.raises(CheckFailedError, match="chk_zz_always_fails") as error:
        load_next(world)
    assert [c.check_id for c in error.value.checks if c.violations] == ["chk_zz_always_fails"]
    assert tables(world.conn) == []
    assert file_hash(db_path(world.conn)) == before, "the file is as it was, byte for byte"
    assert not world.conn.in_transaction


# --- the tables of the flow only take rows (D24; risk item 1: what was issued is not redone) ----------------------------------------------------------------


def seed_flow(conn) -> None:
    """One valid row of every table of the flow (the parents they point to first): a round, its base, the assignment, a model, a list, a baseline, an outcome, a delivery to the
    CRM and the operation of the round."""
    conn.execute("INSERT INTO rounds VALUES ('R2011-03-28', '2011-03-28', 'test', 'run-1', 3, 2, 1)")
    conn.execute("INSERT INTO contact_base VALUES ('R2011-03-28', 90001, 12.5, 3, 123.45, 60.25, 0, 3, 'retail|repeat')")
    conn.execute("INSERT INTO holdout_assignments VALUES (90001, 'offer', 'stratified', 4, 'R2011-03-28', 'run-1')")
    conn.execute(f"INSERT INTO model_registry VALUES ('R2011-03-28', 'als', '{{\"factors\": 8}}', 'data/models/R2011-03-28/als', '{SHA}', 5000, 1.5)")
    conn.execute("INSERT INTO offer_lists VALUES ('R2011-03-28', 90001, 1, '95000', 'repeat', 2.5, 'offer', 'run-1')")
    conn.execute("INSERT INTO baseline_lists VALUES ('R2011-03-28', 'b2', 'unrestricted', 90001, 1, '95000', 'run-1')")
    conn.execute("INSERT INTO round_outcomes VALUES ('R2011-03-28', 90001, 1, 2, 1, '12.50', 7, 'run-1')")
    conn.execute("INSERT INTO crm_deliveries (round_id, batch, attempt, status, contacts, created, unchanged, conflicts, sends, readback_equal, seconds, run_key) VALUES ('R2011-03-28', 1, 1, 'ok', 2, 2, 0, 0, 1, 1, 0.5, 'run-1')")
    conn.execute("INSERT INTO round_ops VALUES ('R2011-03-28', 3, 2, 1, 0, 3, 2, 0.1, 4.5, 'run-1')")


# table: (a row's key, an assignment that changes a column, a second row of the same key with other content)
CASES = {
    "rounds": ("round_id = 'R2011-03-28'", "base_size = 9", "INSERT INTO rounds VALUES ('R2011-03-28', '2011-03-28', 'test', 'run-1', 9, 5, 4)"),
    "contact_base": ("customer_id = 90001", "invoices_365 = 99", "INSERT INTO contact_base VALUES ('R2011-03-28', 90001, 1.0, 9, 9.0, 9.0, 1, 9, 'bulk|repeat')"),
    "holdout_assignments": ("customer_id = 90001", "grp = 'control'", "INSERT INTO holdout_assignments VALUES (90001, 'control', 'hash', NULL, 'R2011-03-28', 'run-1')"),
    "model_registry": ("component = 'als'", "seconds = 9.0", f"INSERT INTO model_registry VALUES ('R2011-03-28', 'als', '{{}}', 'x', '{SHA}', 1, 9.0)"),
    "offer_lists": ("customer_id = 90001", "stock_code = '95012'", "INSERT INTO offer_lists VALUES ('R2011-03-28', 90001, 1, '95012', 'discovery', 1.0, 'control', 'run-1')"),
    "baseline_lists": ("customer_id = 90001", "stock_code = '95012'", "INSERT INTO baseline_lists VALUES ('R2011-03-28', 'b2', 'unrestricted', 90001, 1, '95012', 'run-1')"),
    "round_outcomes": ("customer_id = 90001", "bought = 0", "INSERT INTO round_outcomes VALUES ('R2011-03-28', 90001, 0, 0, 0, '0.00', 7, 'run-1')"),
    "crm_deliveries": ("batch = 1", "conflicts = 3", "INSERT INTO crm_deliveries (round_id, batch, attempt, status, contacts, created, unchanged, conflicts, sends, readback_equal, seconds, run_key) VALUES ('R2011-03-28', 1, 1, 'failed', 9, 5, 0, 4, 1, 0, 1.0, 'run-1')"),
    "round_ops": ("round_id = 'R2011-03-28'", "offer = 9", "INSERT INTO round_ops VALUES ('R2011-03-28', 9, 5, 4, 0, 9, 5, 0.9, 9.0, 'run-1')"),
}


def test_flow_tables_reject_update_delete_and_replace(loaded):
    """The triggers say it in the database, whoever writes: an update, a delete, a second insert of a key, INSERT OR REPLACE, REPLACE and an upsert are refused, and the row stays as it was."""
    seed_flow(loaded.conn)
    assert set(CASES) == set(FLOW_TABLES)
    for table, (where, assignment, insert) in CASES.items():
        snapshot = loaded.conn.execute(f"SELECT * FROM {table}").fetchall()
        column = assignment.split(" = ")[0]
        for statement in (f"UPDATE {table} SET {assignment}", f"UPDATE {table} SET {assignment} WHERE {where}", f"DELETE FROM {table}", f"DELETE FROM {table} WHERE {where}", insert,
                          insert.replace("INSERT INTO", "INSERT OR REPLACE INTO"), insert.replace("INSERT INTO", "INSERT OR IGNORE INTO"), insert.replace("INSERT INTO", "REPLACE INTO"),
                          f"{insert} ON CONFLICT DO UPDATE SET {assignment}", f"{insert} ON CONFLICT DO UPDATE SET {column} = {column}"):
            with pytest.raises(sqlite3.DatabaseError, match="solo inserción"):
                loaded.conn.execute(statement)
        assert loaded.conn.execute(f"SELECT * FROM {table}").fetchall() == snapshot, f"{table} is as it was"


def test_the_lines_the_validation_and_the_products_are_insert_only_and_the_deliveries_and_runs_are_not(loaded):
    apply_schema(loaded.conn)
    triggers = {r[0] for r in loaded.conn.execute("SELECT name FROM sqlite_master WHERE type = 'trigger'")}
    for table in (*CORE_INSERT_ONLY, *FLOW_TABLES):
        assert {f"{table}_no_update", f"{table}_no_delete", f"{table}_no_second_insert"} <= triggers, table
    for table in ("deliveries", "pipeline_runs"):
        assert not [t for t in triggers if t.startswith(table)], f"{table} is updated by the flow"
    key = loaded.conn.execute("SELECT line_key FROM lines LIMIT 1").fetchone()[0]
    again = ("INSERT INTO {t} SELECT * FROM {t} LIMIT 1", "INSERT OR REPLACE INTO {t} SELECT * FROM {t} LIMIT 1", "INSERT OR IGNORE INTO {t} SELECT * FROM {t} LIMIT 1")
    statements = [f"UPDATE lines SET quantity = 0 WHERE line_key = {key}", f"DELETE FROM lines WHERE line_key = {key}", "DELETE FROM products", "UPDATE validation_results SET passed = 0"]
    statements += [text.format(t=table) for table in CORE_INSERT_ONLY for text in again]
    for statement in statements:
        with pytest.raises(sqlite3.DatabaseError, match="solo inserción"):
            loaded.conn.execute(statement)
    loaded.conn.execute("UPDATE deliveries SET status = 'rejected'")
    loaded.conn.execute("UPDATE pipeline_runs SET status = 'ok', finished_at = '2011-04-04 09:00:00'")


def test_every_flow_table_takes_its_row_once_and_a_row_with_another_key_is_another_row(loaded):
    seed_flow(loaded.conn)
    loaded.conn.execute("INSERT INTO contact_base VALUES ('R2011-03-28', 90002, 1.0, 1, 1.0, 1.0, 1, 1, 'bulk|one_invoice')")
    loaded.conn.execute("INSERT INTO offer_lists VALUES ('R2011-03-28', 90001, 2, '95012', 'discovery', 1.0, 'offer', 'run-1')")
    loaded.conn.execute("INSERT INTO baseline_lists VALUES ('R2011-03-28', 'b2', 'new_only', 90001, 1, '95012', 'run-1')")
    loaded.conn.execute("INSERT INTO baseline_lists VALUES ('R2011-03-28', 'b3', 'unrestricted', 90001, 1, '95012', 'run-1')")
    loaded.conn.execute("INSERT INTO crm_deliveries (round_id, batch, attempt, status, contacts, created, unchanged, conflicts, sends, readback_equal, seconds, run_key) VALUES ('R2011-03-28', 2, 1, 'ok', 1, 1, 0, 0, 1, 1, 0.1, 'run-1')")
    loaded.conn.execute(f"INSERT INTO model_registry VALUES ('R2011-03-28', 'cosine', '{{}}', 'x', '{SHA}', 1, 0.1)")
    assert [loaded.conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in ("contact_base", "offer_lists", "baseline_lists", "crm_deliveries", "model_registry")] == [2, 2, 3, 2, 2]


def test_a_batch_that_failed_can_be_tried_again_as_another_attempt_and_each_attempt_is_written_once(loaded):
    seed_flow(loaded.conn)
    columns = "(round_id, batch, attempt, status, contacts, created, unchanged, conflicts, sends, readback_equal, seconds, run_key)"
    loaded.conn.execute(f"INSERT INTO crm_deliveries {columns} VALUES ('R2011-03-28', 3, 1, 'failed', 2, 0, 0, 0, 2, 0, 0.5, 'run-1')")
    loaded.conn.execute(f"INSERT INTO crm_deliveries {columns} VALUES ('R2011-03-28', 3, 2, 'ok', 2, 2, 0, 0, 1, 1, 0.5, 'run-1')")
    assert loaded.conn.execute("SELECT batch, attempt, status FROM crm_deliveries WHERE batch = 3 ORDER BY attempt").fetchall() == [(3, 1, "failed"), (3, 2, "ok")]
    with pytest.raises(sqlite3.DatabaseError, match="solo inserción"):
        loaded.conn.execute(f"INSERT INTO crm_deliveries {columns} VALUES ('R2011-03-28', 3, 2, 'ok', 2, 0, 2, 0, 1, 1, 0.5, 'run-1')")


def test_the_schema_constrains_what_it_can_so_a_wrong_row_is_refused_at_the_door(loaded):
    loaded.conn.execute("INSERT INTO rounds VALUES ('R2011-03-28', '2011-03-28', 'test', 'run-1', 3, 2, 1)")
    wrong = [
        "INSERT INTO rounds VALUES ('R2011-04-04', '2011-04-04', 'training', 'run-1', 3, 2, 1)",                                               # a period nobody defined
        "INSERT INTO rounds VALUES ('R2011-04-04', '2011-04-04', 'test', 'no-run', 3, 2, 1)",                                                  # a run that does not exist
        "INSERT INTO rounds VALUES ('R2011-04-04', '2011-04-04', 'test', 'run-1', -1, 2, 1)",
        "INSERT INTO contact_base VALUES ('R2011-09-01', 90001, 1.0, 1, 1.0, 1.0, 0, 1, 'retail|repeat')",                                  # a round that does not exist
        "INSERT INTO contact_base VALUES ('R2011-03-28', 90001, 1.0, 1, 1.0, 1.0, 2, 1, 'retail|repeat')",                                  # bulk is 0 or 1
        "INSERT INTO contact_base VALUES ('R2011-03-28', 90001, 1.0, 1, 1.0, 1.0, 0, 1, 'wholesale')",                                      # a segment nobody defined
        "INSERT INTO contact_base VALUES ('R2011-03-28', 90001, 1.0, 1, 1.0, 1.0, 0, 0, 'retail|repeat')",                                  # a customer with no invoice before
        "INSERT INTO holdout_assignments VALUES (90001, 'maybe', 'stratified', 1, 'R2011-03-28', 'run-1')",
        "INSERT INTO holdout_assignments VALUES (90001, 'offer', 'random', 1, 'R2011-03-28', 'run-1')",
        "INSERT INTO holdout_assignments VALUES (90001, 'offer', 'stratified', NULL, 'R2011-03-28', 'run-1')",                              # a stratified draw has its stratum
        "INSERT INTO holdout_assignments VALUES (90001, 'offer', 'hash', 3, 'R2011-03-28', 'run-1')",                                       # a hash assignment has none
        "INSERT INTO holdout_assignments VALUES (90001, 'offer', 'hash', NULL, 'R2011-09-01', 'run-1')",
        f"INSERT INTO model_registry VALUES ('R2011-03-28', 'forest', '{{}}', 'x', '{SHA}', 1, 0.1)",
        f"INSERT INTO model_registry VALUES ('R2011-03-28', 'als', 'not json', 'x', '{SHA}', 1, 0.1)",
        "INSERT INTO model_registry VALUES ('R2011-03-28', 'als', '{}', 'x', 'short', 1, 0.1)",
        f"INSERT INTO model_registry VALUES ('R2011-03-28', 'als', '{{}}', 'x', '{SHA}', 0, 0.1)",
        "INSERT INTO offer_lists VALUES ('R2011-03-28', 90001, 0, '95000', 'repeat', 1.0, 'offer', 'run-1')",                              # ranks start at 1
        "INSERT INTO offer_lists VALUES ('R2011-03-28', 90001, 1, '95000', 'guess', 1.0, 'offer', 'run-1')",
        "INSERT INTO offer_lists VALUES ('R2011-03-28', 90001, 1, '95000', 'repeat', 1.0, 'both', 'run-1')",
        "INSERT INTO baseline_lists VALUES ('R2011-03-28', 'b9', 'unrestricted', 90001, 1, '95000', 'run-1')",
        "INSERT INTO baseline_lists VALUES ('R2011-03-28', 'b1', 'sometimes', 90001, 1, '95000', 'run-1')",
        "INSERT INTO round_outcomes VALUES ('R2011-03-28', 90001, 2, 1, 1, '1.00', 7, 'run-1')",
        "INSERT INTO round_outcomes VALUES ('R2011-03-28', 90001, 0, 0, 1, '0.00', 7, 'run-1')",                                           # a product of the list that was not bought
        "INSERT INTO round_outcomes VALUES ('R2011-03-28', 90001, 1, 1, 1, '1.00', 8, 'run-1')",                                            # more days than a week
        "INSERT INTO round_outcomes VALUES ('R2011-03-28', 90001, 0, 0, 0, '0.00', 0, 'run-1')",
        "INSERT INTO crm_deliveries (round_id, batch, attempt, status, contacts, created, unchanged, conflicts, sends, readback_equal, seconds, run_key) VALUES ('R2011-03-28', 1, 1, 'ok', 2, 3, 0, 0, 1, 1, 0.5, 'run-1')",                       # more created than contacts
        "INSERT INTO crm_deliveries (round_id, batch, attempt, status, contacts, created, unchanged, conflicts, sends, readback_equal, seconds, run_key) VALUES ('R2011-03-28', 1, 1, 'ok', 2, 2, 0, 0, 1, 2, 0.5, 'run-1')",
        "INSERT INTO crm_deliveries (round_id, batch, attempt, status, contacts, created, unchanged, conflicts, sends, readback_equal, seconds, run_key) VALUES ('R2011-03-28', 1, 0, 'ok', 2, 2, 0, 0, 1, 1, 0.5, 'run-1')",                                                     # attempts start at 1
        "INSERT INTO crm_deliveries (round_id, batch, attempt, status, contacts, created, unchanged, conflicts, sends, readback_equal, seconds, run_key) VALUES ('R2011-03-28', 1, 1, 'sent', 2, 2, 0, 0, 1, 1, 0.5, 'run-1')",                                                   # a status nobody defined
        "INSERT INTO crm_deliveries (round_id, batch, attempt, status, contacts, created, unchanged, conflicts, sends, readback_equal, seconds, run_key) VALUES ('R2011-03-28', 1, 1, 'ok', 2, 2, 0, 0, 3, 1, 0.5, 'run-1')",                                                     # a batch is sent once, or twice when the answer was lost
        "INSERT INTO crm_deliveries (round_id, batch, attempt, status, contacts, created, unchanged, conflicts, sends, readback_equal, seconds, run_key) VALUES ('R2011-03-28', 1, 1, 'ok', 2, 1, 0, 1, 1, 1, 0.5, 'run-1')",                                                     # a delivered batch has no conflict
        "INSERT INTO crm_deliveries (round_id, batch, attempt, status, contacts, created, unchanged, conflicts, sends, readback_equal, seconds, run_key) VALUES ('R2011-03-28', 1, 1, 'failed', 2, 2, 0, 0, 1, 0, 0.5, 'run-1')",                                                 # a failed batch created nothing
        "INSERT INTO crm_deliveries (round_id, batch, attempt, status, contacts, created, unchanged, conflicts, sends, readback_equal, seconds, run_key) VALUES ('R2011-03-28', 1, 1, 'failed', 2, 0, 0, 0, 1, 1, 0.5, 'run-1')",                                                 # and was not read back equal
        "INSERT INTO round_ops VALUES ('R2011-03-28', 3, 2, 1, 0, 3, 2, 1.5, 4.5, 'run-1')",                                                # a share over one
        "INSERT INTO round_ops VALUES ('R2011-03-28', 3, 2, 2, 0, 3, 2, 0.1, 4.5, 'run-1')",                                                # offer + control over the base
    ]
    for statement in wrong:
        with pytest.raises(sqlite3.IntegrityError):
            loaded.conn.execute(statement)
    assert loaded.conn.execute("SELECT COUNT(*) FROM rounds").fetchone()[0] == 1
    for table in ("contact_base", "holdout_assignments", "model_registry", "offer_lists", "baseline_lists", "round_outcomes", "crm_deliveries", "round_ops"):
        assert loaded.conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0, table


# --- the load ----------------------------------------------------------------------------------------------------------------------------------------


def price_text(value: float) -> str:
    return format(Decimal(repr(float(value))), "f")


def test_a_load_registers_the_delivery_the_validation_the_run_and_every_line(world):
    spec, result = load_next(world)
    frame = dv.read_delivery(dv.delivery_path(world.cfg, spec))
    assert (result.delivery_id, result.run_key, result.lines) == (spec.delivery_id, "run-1", len(frame))
    assert [c.check_id for c in result.checks] == LOAD_CHECKS and all(c.violations == 0 for c in result.checks)
    entry = world.entries[spec.delivery_id]
    assert world.conn.execute("SELECT * FROM deliveries").fetchall() == [(spec.delivery_id, "launch", "2010-12-06", "2011-03-27", "2011-03-28 00:00:00", len(frame), entry["sha256"], "loaded", "run-1")]
    run = world.conn.execute("SELECT run_key, started_at, finished_at, status, delivery_id, as_of, config_sha256, round_id, peak_working_set_mb, memory_counter, message FROM pipeline_runs").fetchall()
    assert run == [("run-1", "2011-04-04 08:30:15", None, "running", spec.delivery_id, "2011-03-28 00:00:00", CONFIG_SHA, None, None, None, None)]
    results = world.conn.execute("SELECT rule_id, severity, scope, aggregation, passed FROM validation_results ORDER BY rule_id").fetchall()
    assert [r[0] for r in results] == list(val.RULES) and ("V10", "bloqueante", "entrega", "per_run", 1) in results and ("V14", "advertencia", "línea", "per_run", 0) in results
    assert world.conn.execute("SELECT COUNT(*) FROM lines").fetchone()[0] == len(frame)
    assert not world.conn.in_transaction


def test_a_line_is_stored_with_its_text_price_its_text_date_and_its_role_and_a_guest_has_no_customer(loaded):
    spec = loaded.plan[0]
    frame = dv.read_delivery(dv.delivery_path(loaded.cfg, spec))
    for role in ("purchase", "guest_purchase", "cancellation"):
        row = frame[frame["role"] == role].iloc[0]
        stored = loaded.conn.execute("SELECT * FROM lines WHERE line_key = ?", (int(row["line_key"]),)).fetchone()
        customer = None if pd.isna(row["customer_id"]) else int(row["customer_id"])
        assert stored == (int(row["line_key"]), spec.delivery_id, row["invoice"], row["stock_code"], row["description"], int(row["quantity"]), row["invoice_date"].strftime("%Y-%m-%d %H:%M:%S"),
                          price_text(row["price"]), customer, row["country"], int(row["internal_repeat"]), role)
    assert (loaded.conn.execute("SELECT COUNT(*) FROM lines WHERE role = 'guest_purchase' AND customer_id IS NOT NULL").fetchone()[0],
            loaded.conn.execute("SELECT COUNT(*) FROM lines WHERE role = 'purchase' AND customer_id IS NULL").fetchone()[0]) == (0, 0)
    assert dict(loaded.conn.execute("SELECT role, COUNT(*) FROM lines GROUP BY role")) == {role: n for role, n in frame["role"].value_counts().items()}
    assert loaded.conn.execute("SELECT SUM(internal_repeat) FROM lines").fetchone()[0] == int(frame["internal_repeat"].sum())
    assert set(dict(loaded.conn.execute("SELECT role, 1 FROM lines")).keys()) <= set(ROLES)


def test_the_prices_keep_every_digit_the_source_gave(world):
    spec = world.plan[0]
    frame = hand_frame({"price": 0.001}, {"price": 6.95}, {"price": 2.0}, {"price": 1e-05}, {"price": 1210.5}, {"price": 0.1 + 0.2})
    frame["invoice_date"] = datetime(2011, 3, 1, 10, 0)
    load_frame(world, spec, frame)
    assert [r[0] for r in world.conn.execute("SELECT price FROM lines ORDER BY line_key")] == ["0.001", "6.95", "2.0", "0.00001", "1210.5", "0.30000000000000004"]


def test_the_products_are_the_codes_of_a_basket_with_the_commonest_description_the_first_day_and_the_invoices_of_the_launch(world):
    spec = world.plan[0]
    frame = hand_frame(
        {"invoice": "1", "stock_code": "95000", "description": "ROJO", "invoice_date": datetime(2011, 3, 3, 10, 0)},
        {"invoice": "1", "stock_code": "95000", "description": "ROJO", "invoice_date": datetime(2011, 3, 3, 10, 0)},                       # one invoice: counts once
        {"invoice": "2", "stock_code": "95000", "description": "AZUL", "invoice_date": datetime(2011, 2, 1, 10, 0)},
        {"invoice": "3", "stock_code": "95000", "description": "ROJO", "invoice_date": datetime(2011, 3, 5, 10, 0), "role": "guest_purchase", "customer_id": None},
        {"invoice": "4", "stock_code": "95012", "description": "VERDE", "invoice_date": datetime(2011, 3, 9, 10, 0)},
        {"invoice": "5", "stock_code": "95024", "description": "NEGRO", "invoice_date": datetime(2011, 3, 9, 10, 0), "role": "cancellation", "quantity": -1},   # a cancellation: not a product
        {"invoice": "6", "stock_code": "POST", "description": "POSTAGE", "invoice_date": datetime(2011, 3, 9, 10, 0), "role": "non_product"},
        {"invoice": "7", "stock_code": "95036", "description": None, "invoice_date": datetime(2011, 3, 9, 10, 0)},                              # a product with no description
        {"invoice": "8", "stock_code": "95048", "description": "A", "invoice_date": datetime(2011, 3, 9, 10, 0)}, {"invoice": "9", "stock_code": "95048", "description": "B",
                                                                                                                  "invoice_date": datetime(2011, 3, 9, 10, 0)},      # a tie: the first in order
    )
    load_frame(world, spec, frame)
    assert world.conn.execute("SELECT * FROM products ORDER BY stock_code").fetchall() == [
        ("95000", "ROJO", "2011-02-01", 3), ("95012", "VERDE", "2011-03-09", 1), ("95036", None, "2011-03-09", 1), ("95048", "A", "2011-03-09", 2)]


def test_a_weekly_delivery_adds_only_the_products_it_sees_for_the_first_time_and_counts_no_launch_invoices_for_them(loaded):
    known = {r[0] for r in loaded.conn.execute("SELECT stock_code FROM products")}
    before = loaded.conn.execute("SELECT * FROM products ORDER BY stock_code").fetchall()
    spec, _ = load_next(loaded, run_key="run-2")
    assert spec.kind == "weekly"
    frame = dv.read_delivery(dv.delivery_path(loaded.cfg, spec))
    seen = set(frame.loc[frame["role"].isin(PRODUCT_ROLES), "stock_code"])
    after = loaded.conn.execute("SELECT * FROM products ORDER BY stock_code").fetchall()
    assert {r[0] for r in after} == known | seen and [r for r in after if r[0] in known] == before, "what was there is as it was"
    assert all(r[3] == 0 and r[2] >= "2011-03-28" for r in after if r[0] not in known)


def test_every_delivery_of_the_fixture_validates_and_loads_in_order_and_the_warehouse_holds_every_line_once(world):
    ids = []
    for number in range(len(world.plan)):
        spec, result = load_next(world, run_key=f"run-{number + 1}")
        ids.append(spec.delivery_id)
        assert result.lines > 0 and all(c.violations == 0 for c in result.checks)
    assert ids == [spec.delivery_id for spec in world.plan] and dv.next_to_load(world.plan, val.loaded_ids(world.conn)) is None
    assert world.conn.execute("SELECT COUNT(*), COUNT(DISTINCT line_key) FROM lines").fetchone() == (len(world.lines), len(world.lines))
    assert {r[0] for r in world.conn.execute("SELECT line_key FROM lines")} == set(world.lines["line_key"])
    assert world.conn.execute("SELECT COUNT(*) FROM deliveries WHERE status = 'loaded'").fetchone()[0] == len(world.plan)
    purchases = world.lines[world.lines["role"] == "purchase"]
    assert world.conn.execute("SELECT COUNT(DISTINCT customer_id) FROM lines WHERE role = 'purchase'").fetchone()[0] == purchases["customer_id"].nunique()
    baskets = world.lines[world.lines["role"].isin(PRODUCT_ROLES)]
    assert world.conn.execute("SELECT COUNT(*) FROM products").fetchone()[0] == baskets["stock_code"].nunique()
    assert [r[0] for r in world.conn.execute("SELECT delivery_id FROM deliveries ORDER BY first_day")] == ids
    assert all(c.violations == 0 for c in run_checks(world.conn, "load"))


def test_the_validation_reads_what_the_load_filled_so_a_loaded_delivery_is_refused_again_and_a_repeated_line_too(loaded):
    spec = loaded.plan[0]
    path = dv.delivery_path(loaded.cfg, spec)
    with pytest.raises(val.ValidationError) as caught:
        val.validate_delivery(spec, path, loaded.conn, loaded.view, run_key="run-2")
    assert caught.value.report.blocking_failed == ("V10", "V13"), "it is no longer the next one, and every line of it is loaded"
    second = loaded.plan[1]
    v13 = next(r for r in val.validate_delivery(second, dv.delivery_path(loaded.cfg, second), loaded.conn, loaded.view, run_key="run-2").results if r.rule_id == "V13")
    assert v13.passed
    frame = dv.read_delivery(dv.delivery_path(loaded.cfg, second))
    frame.loc[0, "line_key"] = int(loaded.conn.execute("SELECT line_key FROM lines LIMIT 1").fetchone()[0])
    dv.publish_frame(loaded.cfg, second, frame)
    with pytest.raises(val.ValidationError) as again:
        val.validate_delivery(second, dv.delivery_path(loaded.cfg, second), loaded.conn, loaded.view, run_key="run-2")
    assert again.value.report.blocking_failed == ("V13",)


def test_a_load_without_an_approved_validation_of_this_run_is_refused_before_writing_anything(world):
    spec = world.plan[0]
    path = dv.delivery_path(world.cfg, spec)
    frame = dv.read_delivery(path)
    good = val.validate_delivery(spec, path, None, world.view, run_key="run-1")

    def with_result(rule_id: str, **change):
        return dataclasses.replace(good, results=tuple(dataclasses.replace(r, **change) if r.rule_id == rule_id else r for r in good.results))

    cases = {
        "another run": dataclasses.replace(good, run_key="other-run"),
        "another delivery": dataclasses.replace(good, delivery_id="W2011-03-28"),
        "a blocking rule failed": with_result("V11", passed=False),
        "the first blocking rule failed": with_result("V10", passed=False),
        "the last blocking rule failed": with_result("V13", passed=False),
        "no blocking rule at all": dataclasses.replace(good, results=tuple(r for r in good.results if r.severity != "bloqueante")),
        "one blocking rule missing": dataclasses.replace(good, results=tuple(r for r in good.results if r.rule_id != "V12")),
        "the rules about the lines skipped": dataclasses.replace(good, results=good.results[:2], skipped=val.CONTENT_RULES),
        "no rows said": dataclasses.replace(good, rows=None),
        "no file fingerprint said": dataclasses.replace(good, sha256=None),
    }
    for name, report in cases.items():
        with pytest.raises(LoadRefusedError):
            load_delivery(world.conn, spec, frame, report, "run-1", started_at=STARTED, config_sha256=CONFIG_SHA)
        assert tables(world.conn) == [], f"{name}: not even the schema"
    load_delivery(world.conn, spec, frame, good, "run-1", started_at=STARTED, config_sha256=CONFIG_SHA)   # and a good one still loads after all those refusals
    assert world.conn.execute("SELECT COUNT(*) FROM lines").fetchone()[0] == len(frame)


def test_the_lines_that_are_loaded_are_the_lines_of_the_validated_delivery_and_no_others(world):
    spec = world.plan[0]
    path = dv.delivery_path(world.cfg, spec)
    report = val.validate_delivery(spec, path, None, world.view, run_key="run-1")
    other = dv.read_delivery(dv.delivery_path(world.cfg, world.plan[1]))
    with pytest.raises(LoadRefusedError, match="filas"):
        load_delivery(world.conn, spec, other, report, "run-1", started_at=STARTED, config_sha256=CONFIG_SHA)
    shorter = dv.read_delivery(path).iloc[:-1]
    with pytest.raises(LoadRefusedError, match="filas"):
        load_delivery(world.conn, spec, shorter, report, "run-1", started_at=STARTED, config_sha256=CONFIG_SHA)
    assert tables(world.conn) == []


def test_the_fingerprint_of_the_configuration_is_64_hex_characters_and_the_delivery_has_the_validated_files(world):
    spec = world.plan[0]
    path = dv.delivery_path(world.cfg, spec)
    report = val.validate_delivery(spec, path, None, world.view, run_key="run-1")
    frame = dv.read_delivery(path)
    for digest in ("", "abc", "A" * 64, "a" * 63, "x"):
        with pytest.raises(ValueError, match="64"):
            load_delivery(world.conn, spec, frame, report, "run-1", started_at=STARTED, config_sha256=digest)
    assert tables(world.conn) == []
    load_delivery(world.conn, spec, frame, report, "run-1", started_at=STARTED, config_sha256=CONFIG_SHA)
    assert report.sha256 == world.entries[spec.delivery_id]["sha256"] and report.rows == len(frame)
    assert world.conn.execute("SELECT sha256 FROM deliveries").fetchone() == (report.sha256,), "the delivery holds the fingerprint of the file that was validated"


def test_a_warning_that_failed_does_not_stop_the_load(loaded):
    assert loaded.conn.execute("SELECT passed FROM validation_results WHERE rule_id = 'V14'").fetchone() == (0,), "the fixture's launch has repeated lines, and the load went on"


def test_a_failed_load_leaves_the_file_as_it_was_byte_for_byte(loaded):
    spec = loaded.plan[0]
    before = file_hash(db_path(loaded.conn))
    path = dv.delivery_path(loaded.cfg, spec)
    report = val.validate_delivery(spec, path, None, loaded.view, run_key="run-2")
    with pytest.raises(DeliveryAlreadyLoadedError, match=spec.delivery_id):
        load_delivery(loaded.conn, spec, dv.read_delivery(path), report, "run-2", started_at=STARTED, config_sha256=CONFIG_SHA)
    assert file_hash(db_path(loaded.conn)) == before
    second = loaded.plan[1]
    path2 = dv.delivery_path(loaded.cfg, second)
    report2 = val.validate_delivery(second, path2, loaded.conn, loaded.view, run_key="run-1")
    with pytest.raises(sqlite3.IntegrityError):   # a run that is already recorded
        load_delivery(loaded.conn, second, dv.read_delivery(path2), report2, "run-1", started_at=STARTED, config_sha256=CONFIG_SHA)
    assert file_hash(db_path(loaded.conn)) == before
    assert loaded.conn.execute("SELECT COUNT(*) FROM deliveries").fetchone()[0] == 1 and not loaded.conn.in_transaction


def test_a_delivery_that_was_rejected_or_only_published_before_is_loaded_over_its_row(world):
    spec = world.plan[0]
    apply_schema(world.conn)
    world.conn.execute("INSERT INTO deliveries VALUES (?, 'launch', '2010-12-06', '2011-03-27', '2011-03-28 00:00:00', 1, ?, 'rejected', 'run-0')", (spec.delivery_id, SHA))
    _spec, result = load_next(world)
    assert result.delivery_id == spec.delivery_id
    row = world.conn.execute("SELECT status, run_key, rows, sha256 FROM deliveries").fetchall()
    assert row == [("loaded", "run-1", result.lines, world.entries[spec.delivery_id]["sha256"])]


DAMAGE = [
    ("UPDATE deliveries SET rows = rows + 1", "chk_delivery_rows_match"),
    ("TRIGGER:DELETE FROM lines WHERE line_key = (SELECT MIN(line_key) FROM lines)", "chk_delivery_rows_match"),
    ("TRIGGER:UPDATE lines SET customer_id = 90001 WHERE role = 'guest_purchase'", "chk_guest_is_not_a_customer"),
    ("TRIGGER:UPDATE lines SET customer_id = NULL WHERE role = 'purchase'", "chk_guest_is_not_a_customer"),
    ("TRIGGER:UPDATE lines SET invoice_date = '2012-01-01 10:00:00' WHERE line_key = (SELECT MIN(line_key) FROM lines)", "chk_lines_inside_their_delivery"),
    ("TRIGGER:UPDATE lines SET invoice_date = '2010-12-05 23:59:59' WHERE line_key = (SELECT MIN(line_key) FROM lines)", "chk_lines_inside_their_delivery"),
    ("UPDATE pipeline_runs SET as_of = '2011-01-01 00:00:00'", "chk_run_matches_delivery"),
    ("UPDATE pipeline_runs SET finished_at = '2011-04-04 09:00:00'", "chk_run_matches_delivery"),
    ("TRIGGER:UPDATE validation_results SET passed = 0 WHERE rule_id = 'V10'", "chk_validation_passed"),
    ("TRIGGER:DELETE FROM validation_results WHERE rule_id = 'V11'", "chk_validation_complete"),
]


@pytest.mark.parametrize("damage, control", DAMAGE)
def test_each_control_finds_the_damage_that_it_is_for(loaded, damage, control):
    """Each control of the load, written to find one kind of damage, finds it in a warehouse that was loaded right and made wrong by hand (the insert-only triggers are dropped first for
    the damage that needs an update or a delete)."""
    assert all(c.violations == 0 for c in run_checks(loaded.conn, "load"))
    if damage.startswith("TRIGGER:"):
        for trigger in [r[0] for r in loaded.conn.execute("SELECT name FROM sqlite_master WHERE type = 'trigger' AND (name LIKE '%no_update' OR name LIKE '%no_delete')")]:
            loaded.conn.execute(f"DROP TRIGGER {trigger}")
        damage = damage.removeprefix("TRIGGER:")
    loaded.conn.execute(damage)
    found = {c.check_id: c.violations for c in run_checks(loaded.conn, "load")}
    assert found[control] >= 1, f"{control} found nothing after: {damage}"
    only = run_checks(loaded.conn, "load", only=[control])[0]
    assert only.violations == found[control] and only.sample, "and a sample of the rows"


def test_run_checks_names_its_group_and_its_controls(loaded):
    with pytest.raises(ValueError, match="grupo"):
        run_checks(loaded.conn, "nope")
    with pytest.raises(ValueError, match="chk_nope"):
        run_checks(loaded.conn, "load", only=["chk_nope"])
    assert [c.check_id for c in run_checks(loaded.conn, "load", only=["chk_validation_passed"])] == ["chk_validation_passed"]
    assert run_checks(loaded.conn, "model") == [], "the controls of the star schema came with the star schema (U15)"


def test_a_control_file_must_be_one_select(world, tmp_path, monkeypatch):
    copy = tmp_path / "sql"
    shutil.copytree(warehouse.SQL_DIR, copy)
    (copy / "checks" / "load" / "chk_two.sql").write_text("SELECT 1 WHERE 0;\nSELECT 2 WHERE 0;\n", encoding="utf-8")
    monkeypatch.setattr(warehouse, "SQL_DIR", copy)
    with pytest.raises(ValueError, match="exactamente un SELECT"):
        load_next(world)
    assert tables(world.conn) == []


# --- the runner --------------------------------------------------------------------------------------------------------------------------------------


def test_the_connection_is_autocommit_with_the_projects_pragmas(world):
    conn = world.conn
    assert conn.isolation_level is None
    assert conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "delete"
    assert conn.execute("PRAGMA synchronous").fetchone()[0] == 2, "FULL"
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    assert conn.execute("PRAGMA busy_timeout").fetchone()[0] == warehouse.BUSY_TIMEOUT_MS


def test_connect_creates_the_folder(tmp_path):
    target = tmp_path / "a" / "b" / "wh.sqlite"
    connect(target).close()
    assert target.parent.is_dir()


def test_the_runner_never_calls_executescript():
    source = Path(warehouse.__file__).read_text(encoding="utf-8")
    assert "executescript" not in source.replace("``executescript()``", "")


def test_sql_files_are_split_in_statements_keeping_semicolons_inside_strings_comments_and_triggers():
    text = ("-- a comment; with a semicolon\nCREATE TABLE t (a TEXT DEFAULT 'x;y'); /* block; comment */\n"
            "CREATE TRIGGER g BEFORE INSERT ON t BEGIN SELECT RAISE(ABORT, 'no; way'); END;\nSELECT 1")
    statements = split_statements(text)
    assert len(statements) == 3
    assert statements[0].startswith("-- a comment") and "DEFAULT 'x;y'" in statements[0] and "CREATE TRIGGER g" in statements[1] and statements[1].endswith("END;") and statements[2] == "SELECT 1"
    assert split_statements("-- nothing\n;;\n/* nothing */") == []
    split_statements(text).append("x")
    assert len(split_statements(text)) == 3, "the cached split is a new list each time"


def test_apply_schema_is_idempotent_keeps_the_data_and_refuses_a_table_that_drifted(loaded):
    apply_schema(loaded.conn)
    apply_schema(loaded.conn)
    count = loaded.conn.execute("SELECT COUNT(*) FROM lines").fetchone()[0]
    apply_schema(loaded.conn)
    assert loaded.conn.execute("SELECT COUNT(*) FROM lines").fetchone()[0] == count
    loaded.conn.execute("DROP TABLE round_ops")
    loaded.conn.execute("CREATE TABLE round_ops (round_id TEXT, extra INTEGER)")
    with pytest.raises(SchemaDriftError, match="round_ops") as error:
        apply_schema(loaded.conn)
    assert "extra" in str(error.value) and error.value.table == "round_ops" and "base" in error.value.missing and error.value.unexpected == ("extra",)
    assert not loaded.conn.in_transaction


def test_apply_schema_joins_the_callers_transaction_and_is_undone_with_it(world):
    world.conn.execute("BEGIN IMMEDIATE")
    apply_schema(world.conn)
    assert world.conn.in_transaction
    world.conn.execute("ROLLBACK")
    assert tables(world.conn) == []


def test_a_second_writer_waits_for_the_first_and_then_gets_in(tmp_path):
    first, second = connect(tmp_path / "w.sqlite"), connect(tmp_path / "w.sqlite")
    second.execute("PRAGMA busy_timeout=50")
    first.execute("BEGIN IMMEDIATE")
    with pytest.raises(sqlite3.OperationalError, match="locked"):
        second.execute("BEGIN IMMEDIATE")
    first.execute("ROLLBACK")
    second.execute("BEGIN IMMEDIATE")
    second.execute("ROLLBACK")
    first.close()
    second.close()
