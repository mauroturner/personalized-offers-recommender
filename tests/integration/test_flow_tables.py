"""What the launch and the weekly rounds write and read in the warehouse (U11; D24; risk item 1: what was issued is not redone): the lines as the tasks read them, the base of a round with its
assignments in one transaction that a repeat does not touch, and the registry of the models (the tables are insert-only in the database itself, U06)."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from pandas.testing import assert_frame_equal

from personaloffers import base, holdout
from personaloffers import calendar as cal
from personaloffers import deliveries as dv
from personaloffers import warehouse
from personaloffers.warehouse import RoundConflictError, apply_schema, connect
from tests.fixtures.worlds import RUN_KEY, copy_world

SHA = "a" * 64


@pytest.fixture
def loaded_world(launch_template, workbook, quick_cfg, tmp_path):
    world = copy_world(launch_template, workbook, quick_cfg, tmp_path / "world")
    yield world
    world.conn.close()


def file_digest(conn) -> str:
    return hashlib.sha256(Path(conn.execute("PRAGMA database_list").fetchone()[2]).read_bytes()).hexdigest()


# --- the lines, as the tasks read them -------------------------------------------------------------------------------------------------------------------


def test_the_lines_of_the_warehouse_are_the_canonical_lines_of_what_was_loaded(loaded_world):
    """The same frame, with the same dtypes, in the order of the line key: nothing that a task computes depends on the way the lines were stored (a price as decimal text, a date as text)."""
    expected = dv.read_delivery(dv.delivery_path(loaded_world.cfg, loaded_world.plan[0])).sort_values("line_key").reset_index(drop=True)
    found = warehouse.read_lines(loaded_world.conn)
    assert_frame_equal(found, expected, check_exact=True)
    assert found["customer_id"].isna().any() and found["description"].isna().sum() >= 0 and found["role"].nunique() >= 5


def test_a_warehouse_without_lines_gives_an_empty_frame_with_the_columns(tmp_path):
    conn = connect(tmp_path / "empty.sqlite")
    found = warehouse.read_lines(conn)
    assert found.empty and list(found.columns) == ["line_key", "invoice", "stock_code", "description", "quantity", "invoice_date", "price", "customer_id", "country", "internal_repeat", "role"]
    apply_schema(conn)
    assert warehouse.read_lines(conn).empty
    conn.close()


def test_the_lines_read_are_what_a_round_is_cut_from(loaded_world, quick_view, quick_cfg):
    lines = warehouse.read_lines(loaded_world.conn)
    monday = quick_cfg.calendar.test_first_round
    assert lines["invoice_date"].max() < pd.Timestamp(monday)
    table = base.base_table(base.history_before(lines, monday), monday, quick_view)
    assert len(table) > 100 and table["customer_id"].is_unique


# --- the base of a round ---------------------------------------------------------------------------------------------------------------------------


def launch_base(world, quick_view, quick_cfg):
    monday = quick_cfg.calendar.test_first_round
    lines = warehouse.read_lines(world.conn)
    table = base.base_table(base.history_before(lines, monday), monday, quick_view)
    return monday, table, holdout.assign_cohort(table, quick_view)


def test_the_base_of_a_round_and_its_assignments_are_stored_together_with_the_sizes_of_the_groups(loaded_world, quick_view, quick_cfg):
    monday, table, assignment = launch_base(loaded_world, quick_view, quick_cfg)
    conn = loaded_world.conn
    assert warehouse.store_round_base(conn, cal.round_id(monday), monday, cal.period_of(monday, quick_cfg), RUN_KEY, table, assignment) is True
    control = int((assignment["grp"] == "control").sum())
    assert conn.execute("SELECT * FROM rounds").fetchall() == [(cal.round_id(monday), monday.isoformat(), "test", RUN_KEY, len(table), len(table) - control, control)]
    assert conn.execute("SELECT COUNT(*) FROM contact_base").fetchone()[0] == len(table)
    row = table.iloc[0]
    assert conn.execute("SELECT * FROM contact_base WHERE customer_id = ?", (int(row["customer_id"]),)).fetchone() == (
        cal.round_id(monday), int(row["customer_id"]), float(row["recency_days"]), int(row["invoices_365"]), float(row["spend_365"]), float(row["tenure_days"]), int(row["bulk"]),
        int(row["invoices_before"]), row["segment"])
    stored = holdout.read_assignments(conn)
    assert holdout.fingerprint(stored) == holdout.fingerprint(assignment) and set(stored["assigned_round"]) == {cal.round_id(monday)}
    assert not conn.in_transaction


def test_storing_the_base_of_a_round_again_changes_nothing_and_says_so(loaded_world, quick_view, quick_cfg):
    monday, table, assignment = launch_base(loaded_world, quick_view, quick_cfg)
    args = (cal.round_id(monday), monday, "test", RUN_KEY, table, assignment)
    assert warehouse.store_round_base(loaded_world.conn, *args) is True
    before = file_digest(loaded_world.conn)
    assert warehouse.store_round_base(loaded_world.conn, *args) is False and file_digest(loaded_world.conn) == before


def test_another_base_for_a_round_that_is_stored_is_refused_and_nothing_is_written(loaded_world, quick_view, quick_cfg):
    monday, table, assignment = launch_base(loaded_world, quick_view, quick_cfg)
    args = (cal.round_id(monday), monday, "test", RUN_KEY)
    warehouse.store_round_base(loaded_world.conn, *args, table, assignment)
    before = file_digest(loaded_world.conn)
    with pytest.raises(RoundConflictError, match=cal.round_id(monday)):
        warehouse.store_round_base(loaded_world.conn, *args, table.iloc[:-1], assignment)
    assert file_digest(loaded_world.conn) == before


def test_a_customer_of_the_base_without_a_group_is_refused_before_anything_is_written(loaded_world, quick_view, quick_cfg):
    monday, table, assignment = launch_base(loaded_world, quick_view, quick_cfg)
    before = file_digest(loaded_world.conn)
    with pytest.raises(ValueError, match="sin grupo|asignación"):
        warehouse.store_round_base(loaded_world.conn, cal.round_id(monday), monday, "test", RUN_KEY, table, assignment.iloc[:-3])
    assert file_digest(loaded_world.conn) == before and loaded_world.conn.execute("SELECT COUNT(*) FROM rounds").fetchone()[0] == 0 and not loaded_world.conn.in_transaction


def test_a_failure_while_storing_a_base_rolls_everything_back(loaded_world, quick_view, quick_cfg, monkeypatch):
    monday, table, assignment = launch_base(loaded_world, quick_view, quick_cfg)
    before = file_digest(loaded_world.conn)

    def broken(conn, frame):
        raise sqlite3.OperationalError("disk I/O error")

    monkeypatch.setattr(warehouse, "_insert_base_rows", broken)
    with pytest.raises(sqlite3.OperationalError):
        warehouse.store_round_base(loaded_world.conn, cal.round_id(monday), monday, "test", RUN_KEY, table, assignment)
    assert file_digest(loaded_world.conn) == before and loaded_world.conn.execute("SELECT COUNT(*) FROM holdout_assignments").fetchone()[0] == 0


def test_the_weekly_base_takes_the_group_of_the_stored_customers_and_stores_only_the_new_ones(loaded_world, quick_view, quick_cfg):
    monday, table, assignment = launch_base(loaded_world, quick_view, quick_cfg)
    warehouse.store_round_base(loaded_world.conn, cal.round_id(monday), monday, "test", RUN_KEY, table, assignment)
    later = monday + timedelta(days=7)
    entering = np.array([99001, 99002])
    extra = holdout.assign_newcomers(entering, later, quick_view)
    grown = pd.concat([table.iloc[:50], table.iloc[:2].assign(customer_id=entering)], ignore_index=True)
    assert warehouse.store_round_base(loaded_world.conn, cal.round_id(later), later, "test", RUN_KEY, grown, extra) is True
    sizes = loaded_world.conn.execute("SELECT base_size, offer_size, control_size FROM rounds WHERE round_id = ?", (cal.round_id(later),)).fetchone()
    stored = holdout.read_assignments(loaded_world.conn).set_index("customer_id")["grp"]
    groups = stored.reindex(grown["customer_id"])
    assert sizes == (52, int((groups == "offer").sum()), int((groups == "control").sum())) and sizes[1] + sizes[2] == 52
    assert loaded_world.conn.execute("SELECT COUNT(*) FROM holdout_assignments").fetchone()[0] == len(assignment) + 2


# --- the registry of the models --------------------------------------------------------------------------------------------------------------------


def test_a_model_is_registered_once_with_its_parameters_its_path_and_its_hash(loaded_world, quick_view, quick_cfg):
    monday, table, assignment = launch_base(loaded_world, quick_view, quick_cfg)
    round_id = cal.round_id(monday)
    warehouse.store_round_base(loaded_world.conn, round_id, monday, "test", RUN_KEY, table, assignment)
    warehouse.insert_model(loaded_world.conn, round_id, "als", {"factors": 8, "regularization": 0.1}, f"{round_id}/als", SHA, 4000, 1.25)
    assert loaded_world.conn.execute("SELECT * FROM model_registry").fetchall() == [(round_id, "als", json.dumps({"factors": 8, "regularization": 0.1}, sort_keys=True), f"{round_id}/als", SHA, 4000, 1.25)]
    assert warehouse.registered_models(loaded_world.conn, round_id) == {"als": (f"{round_id}/als", SHA, {"factors": 8, "regularization": 0.1})}
    assert warehouse.registered_models(loaded_world.conn, "R2011-04-04") == {}
    with pytest.raises(sqlite3.DatabaseError, match="solo inserción"):
        warehouse.insert_model(loaded_world.conn, round_id, "als", {}, f"{round_id}/als", SHA, 1, 0.1)
    assert not loaded_world.conn.in_transaction


def test_an_unknown_component_or_a_bad_hash_is_refused_at_the_door(loaded_world, quick_view, quick_cfg):
    monday, table, assignment = launch_base(loaded_world, quick_view, quick_cfg)
    round_id = cal.round_id(monday)
    warehouse.store_round_base(loaded_world.conn, round_id, monday, "test", RUN_KEY, table, assignment)
    for component, digest, fit_lines in (("forest", SHA, 1), ("als", "short", 1), ("als", SHA, 0)):
        with pytest.raises(sqlite3.IntegrityError):
            warehouse.insert_model(loaded_world.conn, round_id, component, {}, "x", digest, fit_lines, 0.1)
    assert loaded_world.conn.execute("SELECT COUNT(*) FROM model_registry").fetchone()[0] == 0 and not loaded_world.conn.in_transaction


def test_two_models_of_one_round_are_registered_in_one_transaction(loaded_world, quick_view, quick_cfg):
    """Both or none: the second one is refused (a bad hash) and the first, written before it, goes with it."""
    monday, table, assignment = launch_base(loaded_world, quick_view, quick_cfg)
    round_id = cal.round_id(monday)
    warehouse.store_round_base(loaded_world.conn, round_id, monday, "test", RUN_KEY, table, assignment)
    models = [("popularity", {}, f"{round_id}/popularity", SHA, 100, 0.1), ("cosine", {"neighbours": 20}, f"{round_id}/cosine", "bad", 100, 0.2)]
    with pytest.raises(sqlite3.IntegrityError):
        warehouse.register_models(loaded_world.conn, round_id, models)
    assert loaded_world.conn.execute("SELECT COUNT(*) FROM model_registry").fetchone()[0] == 0 and not loaded_world.conn.in_transaction
    warehouse.register_models(loaded_world.conn, round_id, [models[0], ("cosine", {"neighbours": 20}, f"{round_id}/cosine", SHA, 100, 0.2)])
    assert sorted(warehouse.registered_models(loaded_world.conn, round_id)) == ["cosine", "popularity"]


def test_a_round_that_is_stored_refuses_other_assignments_for_its_customers(loaded_world, quick_view, quick_cfg):
    """Storing the same round with another draw (here one customer flipped) is a conflict, not a silent repeat: what was assigned is not redone (D14)."""
    monday, table, assignment = launch_base(loaded_world, quick_view, quick_cfg)
    args = (cal.round_id(monday), monday, "test", RUN_KEY, table)
    warehouse.store_round_base(loaded_world.conn, *args, assignment)
    other = assignment.copy()
    other.loc[0, "grp"] = "control" if other.loc[0, "grp"] == "offer" else "offer"
    before = file_digest(loaded_world.conn)
    with pytest.raises(RoundConflictError, match="asignaciones"):
        warehouse.store_round_base(loaded_world.conn, *args, other)
    assert file_digest(loaded_world.conn) == before


def test_the_stored_assignments_agree_only_with_themselves(loaded_world, quick_view, quick_cfg):
    monday, table, assignment = launch_base(loaded_world, quick_view, quick_cfg)
    assert holdout.stored_assignments_agree(loaded_world.conn, assignment) is False, "nothing is stored yet"
    warehouse.store_round_base(loaded_world.conn, cal.round_id(monday), monday, "test", RUN_KEY, table, assignment)
    assert holdout.stored_assignments_agree(loaded_world.conn, assignment) is True and holdout.stored_assignments_agree(loaded_world.conn, assignment.iloc[:5]) is True
    for column, value in (("grp", "control" if assignment.loc[0, "grp"] == "offer" else "offer"), ("method", "hash"), ("assigned_round", "R2011-04-04")):
        changed = assignment.copy()
        changed[column] = changed[column].astype(object)
        changed.loc[0, column] = value
        assert holdout.stored_assignments_agree(loaded_world.conn, changed) is False, column
    unknown = assignment.copy()
    unknown.loc[0, "customer_id"] = 99_999_999
    assert holdout.stored_assignments_agree(loaded_world.conn, unknown) is False
