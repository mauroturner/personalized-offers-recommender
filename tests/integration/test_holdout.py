"""The control group is persistent (U08, risk item 1; RF09, AC09, AC10; decision D14): the launch writes the assignment of its cohort once, every week writes only those who enter, repeating
any of them changes nothing, nobody is ever assigned again, and nothing of the control group can be delivered."""

from __future__ import annotations

import dataclasses
import hashlib
import sqlite3
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from personaloffers import base, holdout
from personaloffers import calendar as cal
from personaloffers.holdout import AssignmentConflictError, ControlLeakError
from personaloffers.warehouse import apply_schema, connect


@pytest.fixture
def db(tmp_path):
    conn = connect(tmp_path / "wh" / "personaloffers.sqlite")
    apply_schema(conn)
    for number in range(1, 6):
        conn.execute("INSERT INTO pipeline_runs (run_key, started_at, status) VALUES (?, '2011-03-28 06:00:00', 'running')", (f"run-{number}",))
    yield conn
    conn.close()


def file_bytes(conn) -> bytes:
    return Path(conn.execute("PRAGMA database_list").fetchone()[2]).read_bytes()


def digest(conn) -> str:
    return hashlib.sha256(file_bytes(conn)).hexdigest()


def rows(conn) -> list[tuple]:
    return conn.execute("SELECT * FROM holdout_assignments ORDER BY customer_id").fetchall()


def add_round(conn, monday: date, cfg, run_key: str) -> None:
    conn.execute("INSERT INTO rounds VALUES (?, ?, ?, ?, 0, 0, 0)", (cal.round_id(monday), monday.isoformat(), cal.period_of(monday, cfg), run_key))


def launch(conn, lines, view, cfg, run_key="run-1"):
    """What the launch does: the base of the first round of the test, the draw and its storage."""
    monday = cfg.calendar.test_first_round
    cov = base.base_table(base.history_before(lines, monday), monday, view)
    assignment = holdout.assign_cohort(cov, view)
    if conn.execute("SELECT 1 FROM rounds WHERE round_id = ?", (cal.round_id(monday),)).fetchone() is None:
        add_round(conn, monday, cfg, run_key)
    return cov, assignment, holdout.store_assignments(conn, assignment, run_key)


def weekly(conn, lines, view, cfg, monday: date, run_key: str):
    """What a weekly delivery does for the round of `monday`: the base, and the hash assignment of the customers of it that have none."""
    cov = base.base_table(base.history_before(lines, monday), monday, view)
    if conn.execute("SELECT 1 FROM rounds WHERE round_id = ?", (cal.round_id(monday),)).fetchone() is None:
        add_round(conn, monday, cfg, run_key)
    stored = set(holdout.read_assignments(conn)["customer_id"])
    entering = cov.loc[~cov["customer_id"].isin(stored), "customer_id"].to_numpy()
    return cov, entering, holdout.store_assignments(conn, holdout.assign_newcomers(entering, monday, view), run_key)


def rounds_after_the_launch(cfg) -> list[date]:
    return [m for period in ("test", "censored") for m in cal.rounds(cfg, period)][1:]


@pytest.mark.parametrize("lookback", [365, 21])
def test_repeating_the_launch_and_every_weekly_keeps_every_assignment(lookback, db, fixture_lines, quick_view, quick_cfg):
    """With a year of lookback nobody leaves the base; with three weeks many leave and some come back, and the ones that come back keep the group they had."""
    view = dataclasses.replace(quick_view, base=dataclasses.replace(quick_view.base, lookback_days=lookback))
    cov, assignment, inserted = launch(db, fixture_lines, view, quick_cfg)
    assert inserted == len(cov) == len(assignment) > 50
    assert holdout.fingerprint(holdout.read_assignments(db)) == holdout.fingerprint(assignment)
    first = rows(db)
    assert {r[5] for r in first} == {"run-1"} and {r[2] for r in first} == {"stratified"}
    # the launch again: the same draw, nothing written, the file as it was
    before = digest(db)
    assert launch(db, fixture_lines, view, quick_cfg, run_key="run-2")[2] == 0
    assert rows(db) == first and digest(db) == before
    # every weekly delivery after it: those who enter get their hash group, and nobody else moves
    seen = {int(c) for c in cov["customer_id"]}
    entered_at: dict[int, date] = {}
    for number, monday in enumerate(rounds_after_the_launch(quick_cfg), start=2):
        key = f"run-{number + 1}"
        before_rows = rows(db)
        week_cov, entering, written = weekly(db, fixture_lines, view, quick_cfg, monday, key)
        assert written == len(entering) and set(map(int, entering)).isdisjoint(seen), "the ones that enter are the ones that had no assignment"
        after = rows(db)
        assert set(before_rows) <= set(after), "everything that was written is as it was"
        new = [r for r in after if r[0] in set(map(int, entering))]
        assert {r[2] for r in new} <= {"hash"} and {r[3] for r in new} <= {None} and {r[4] for r in new} <= {cal.round_id(monday)} and {r[5] for r in new} <= {key}
        assert all(r[1] == holdout.assign_newcomer(r[0], view) for r in new), "the group of a newcomer is its hash"
        seen |= set(map(int, entering))
        entered_at |= {int(c): monday for c in entering}
        # the same weekly again changes nothing
        snapshot = digest(db)
        week_assignment = holdout.assign_newcomers(entering, monday, view)
        assert holdout.store_assignments(db, week_assignment, key + "b") == 0 and digest(db) == snapshot
        assert set(week_cov["customer_id"]) <= seen, "every customer of a base has an assignment"
    final = holdout.read_assignments(db)
    assert len(final) == len(seen) and final["customer_id"].is_unique and set(final["customer_id"]) == seen
    assert (final.loc[final["method"] == "stratified", "customer_id"].tolist() == sorted(int(c) for c in cov["customer_id"]))
    assert set(entered_at) == seen - {int(c) for c in cov["customer_id"]}
    if lookback == 21:
        assert len(final) > len(cov), "the customers who came into the base later were assigned when they came in"


def test_a_customer_who_leaves_the_base_and_comes_back_keeps_the_assignment_it_had(db, quick_view, quick_cfg):
    """Thirty customers buy on 2011-03-10 (the launch base, with three weeks of lookback); twenty of them buy again on 2011-04-12 and ten new ones on 2011-04-05."""
    from tests.fixtures.hand_lines import hand_frame

    view = dataclasses.replace(quick_view, base=dataclasses.replace(quick_view.base, lookback_days=21),
                               holdout=dataclasses.replace(quick_view.holdout, recency_bands=1, frequency_bands=1))
    stamp = lambda *parts: pd.Timestamp(*parts).to_pydatetime()   # noqa: E731
    lines = hand_frame(*({"customer_id": 90001 + n, "invoice": f"I{n}", "invoice_date": stamp(2011, 3, 10, 10, 0)} for n in range(30)),
                       *({"customer_id": 90031 + n, "invoice": f"N{n}", "invoice_date": stamp(2011, 4, 5, 10, 0)} for n in range(10)),
                       *({"customer_id": 90011 + n, "invoice": f"R{n}", "invoice_date": stamp(2011, 4, 12, 10, 0)} for n in range(20)))
    cov, assignment, inserted = launch(db, lines, view, quick_cfg)
    assert inserted == 30 and (assignment["grp"] == "control").sum() == 6 and set(assignment["stratum"]) == {0}, "one stratum of thirty: round(0.2 * 30) in control"
    at_launch = {r[0]: r[1:] for r in rows(db)}
    presence = {}
    for number, monday in enumerate(rounds_after_the_launch(quick_cfg), start=2):
        week_cov, entering, written = weekly(db, lines, view, quick_cfg, monday, f"run-{number}")
        presence[monday] = set(map(int, week_cov["customer_id"]))
        assert written == len(entering)
    assert presence[date(2011, 4, 4)] == set() and presence[date(2011, 4, 11)] == set(range(90031, 90041)), "everybody left the base, and then ten new customers came in"
    assert presence[date(2011, 4, 18)] == set(range(90011, 90041)), "the twenty that bought again came back, with the ten new ones still in"
    after = {r[0]: r[1:] for r in rows(db)}
    assert len(after) == 40 and all(after[c] == at_launch[c] for c in at_launch), "the thirty of the launch have exactly the assignment they were drawn with, whoever left and came back"
    assert {after[c][1] for c in range(90031, 90041)} == {"hash"} and {after[c][3] for c in range(90031, 90041)} == {"R2011-04-11"}
    assert not [c for c in range(90011, 90031) if after[c][1] != "stratified"], "the ones that came back are not newcomers"


def test_a_different_assignment_for_a_customer_that_has_one_is_a_conflict_that_writes_nothing(db, fixture_lines, quick_view, quick_cfg):
    cov, assignment, _ = launch(db, fixture_lines, quick_view, quick_cfg)
    before = digest(db)
    other = holdout.assign_cohort(cov, dataclasses.replace(quick_view, holdout=dataclasses.replace(quick_view.holdout, seed=quick_view.holdout.seed + 1)))
    assert holdout.fingerprint(other) != holdout.fingerprint(assignment)
    with pytest.raises(AssignmentConflictError, match=r"\d+ clientes") as caught:
        holdout.store_assignments(db, other, "run-2")
    assert not any(str(c) in str(caught.value) for c in cov["customer_id"].head(30)), "the error counts and never names"
    assert digest(db) == before and not db.in_transaction
    extra = pd.concat([assignment, holdout.assign_newcomers(np.array([12346]), cal.monday_of("R2011-04-04"), quick_view)], ignore_index=True)
    tampered = extra.copy()
    tampered.loc[0, "grp"] = "control" if tampered.loc[0, "grp"] == "offer" else "offer"
    add_round(db, cal.monday_of("R2011-04-04"), quick_cfg, "run-1")
    before = digest(db)
    with pytest.raises(AssignmentConflictError):
        holdout.store_assignments(db, tampered, "run-2")
    assert digest(db) == before, "a conflict stops the whole write: not even the new customer of the same call was written"
    retried = assignment.copy()
    retried["stratum"] = retried["stratum"] + 1
    with pytest.raises(AssignmentConflictError):
        holdout.store_assignments(db, retried, "run-2")
    assert digest(db) == before


def test_a_stored_assignment_cannot_be_changed_deleted_or_drawn_again_with_sql(db, fixture_lines, quick_view, quick_cfg):
    launch(db, fixture_lines, quick_view, quick_cfg)
    one = rows(db)[0]
    for statement in ("UPDATE holdout_assignments SET grp = 'offer'", f"DELETE FROM holdout_assignments WHERE customer_id = {one[0]}", "DELETE FROM holdout_assignments",
                      f"INSERT OR REPLACE INTO holdout_assignments VALUES ({one[0]}, 'control', 'hash', NULL, '{one[4]}', 'run-1')"):
        with pytest.raises(sqlite3.DatabaseError, match="solo inserción"):
            db.execute(statement)
    assert rows(db)[0] == one


def test_an_assignment_is_written_all_or_nothing_and_inside_the_callers_transaction_if_there_is_one(db, fixture_lines, quick_view, quick_cfg):
    cov = base.base_table(base.history_before(fixture_lines, quick_cfg.calendar.test_first_round), quick_cfg.calendar.test_first_round, quick_view)
    assignment = holdout.assign_cohort(cov, quick_view)
    with pytest.raises(sqlite3.IntegrityError):         # the round of the launch is not there: the foreign key refuses the first row and none is left
        holdout.store_assignments(db, assignment, "run-1")
    assert rows(db) == [] and not db.in_transaction
    add_round(db, quick_cfg.calendar.test_first_round, quick_cfg, "run-1")
    with pytest.raises(sqlite3.IntegrityError):         # a run that does not exist
        holdout.store_assignments(db, assignment, "no-run")
    assert rows(db) == []
    db.execute("BEGIN IMMEDIATE")
    assert holdout.store_assignments(db, assignment, "run-1") == len(assignment) and db.in_transaction
    db.execute("ROLLBACK")
    assert rows(db) == [], "joined the transaction of the caller, which undid it"
    with pytest.raises(ValueError, match="repetir"):
        holdout.store_assignments(db, pd.concat([assignment, assignment.iloc[:1]]), "run-1")
    assert holdout.store_assignments(db, assignment.iloc[0:0], "run-1") == 0


def test_the_stored_assignments_read_back_as_the_ones_that_were_drawn_with_their_types(db, fixture_lines, quick_view, quick_cfg):
    _, assignment, _ = launch(db, fixture_lines, quick_view, quick_cfg)
    week = rounds_after_the_launch(quick_cfg)[0]
    _, entering, _ = weekly(db, fixture_lines, quick_view, quick_cfg, week, "run-2")
    found = holdout.read_assignments(db)
    assert list(found.columns) == holdout.COLUMNS and found["customer_id"].dtype == np.int64 and found["stratum"].dtype == "Int64"
    pd.testing.assert_frame_equal(found[found["method"] == "stratified"].reset_index(drop=True), assignment.astype({"stratum": "Int64"}), check_dtype=False)
    assert found["customer_id"].is_monotonic_increasing and len(entering) == (found["method"] == "hash").sum()


# --- the control group receives nothing (M05) -------------------------------------------------------------------------------------------------------------


def test_nothing_of_the_control_group_can_be_delivered_and_nobody_without_a_group_either(db, fixture_lines, quick_view, quick_cfg):
    _, assignment, _ = launch(db, fixture_lines, quick_view, quick_cfg)
    offers = assignment.loc[assignment["grp"] == "offer", "customer_id"].tolist()
    controls = assignment.loc[assignment["grp"] == "control", "customer_id"].tolist()
    assert offers and controls
    holdout.check_deliverable(db, offers)
    holdout.check_deliverable(db, [])
    holdout.check_deliverable(db, np.array(offers[:10], dtype="int64"))
    with pytest.raises(ControlLeakError, match="1 clientes del grupo de control") as caught:
        holdout.check_deliverable(db, [*offers, controls[0]])
    assert str(controls[0]) not in str(caught.value)
    with pytest.raises(ControlLeakError, match=f"{len(controls)} clientes del grupo de control"):
        holdout.check_deliverable(db, assignment["customer_id"].tolist())
    with pytest.raises(ControlLeakError, match="1 clientes .* no tienen asignación"):
        holdout.check_deliverable(db, [*offers, 12345678])



def test_the_check_reads_more_customers_than_one_query_holds(db, quick_view, quick_cfg):
    """3,000 customers of the offer group go in one delivery: the check asks in chunks and still finds the one control customer that is at the end."""
    monday = quick_cfg.calendar.test_first_round
    add_round(db, monday, quick_cfg, "run-1")
    ids = np.arange(5000, 8001, dtype="int64")
    assignment = pd.DataFrame({"customer_id": ids, "grp": "offer", "method": "hash", "stratum": pd.array([pd.NA] * len(ids), dtype="Int64"), "assigned_round": cal.round_id(monday)})
    assignment.loc[assignment.index[-1], "grp"] = "control"
    holdout.store_assignments(db, assignment, "run-1")
    holdout.check_deliverable(db, ids[:-1])
    with pytest.raises(ControlLeakError, match="1 clientes del grupo de control"):
        holdout.check_deliverable(db, ids)
