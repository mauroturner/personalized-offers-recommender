"""The weekly round (U12, risk item 1: what was issued is not redone; RF14, RF17, AC13, AC17, M06; decisions D11, D14, D18): the follow-up of the round whose week arrived, the base and the hash
assignment of whoever entered, the refit with the sealed recipe, the lists of every customer (the control group's too) and of the baselines, all in one transaction; repeating a round gives the
same bytes, and a round that was issued is checked and not touched."""

from __future__ import annotations

import hashlib
from decimal import Decimal
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from personaloffers import base, holdout, offers, registry, warehouse, weekly
from personaloffers import calendar as cal
from personaloffers import deliveries as dv
from personaloffers.recommend import artifacts
from personaloffers.weekly import ScoringError
from tests.fixtures.worlds import RUN_KEY, copy_world, load_next_delivery, replay

ROUNDS = ["R2011-03-28", "R2011-04-04", "R2011-04-11", "R2011-04-18"]


@pytest.fixture
def world(replayed, workbook, quick_cfg, tmp_path):
    """A copy of the folder in which the launch, the three weekly deliveries and the close ran."""
    made = copy_world(replayed.root, workbook, quick_cfg, tmp_path / "replayed")
    yield made
    made.conn.close()


def digest(made) -> str:
    return hashlib.sha256(Path(made.warehouse_path).read_bytes()).hexdigest()


# --- what a replay left ------------------------------------------------------------------------------------------------------------------------------


def test_a_replay_issues_the_four_rounds_and_follows_up_the_four_weeks(replayed):
    first, *deliveries = replayed.results
    assert first.round_id == ROUNDS[0] and first.status == "fresh" and first.base == first.offer + first.control == 300
    emitted = [d.emitted for d in deliveries]
    assert [e.round_id for e in emitted if e] == ROUNDS[1:] and emitted[-1] is None, "the close builds no round"
    assert [d.track.round_id for d in deliveries] == ROUNDS and [d.track.days_observed for d in deliveries] == [7, 7, 7, 5], "the censored round has five days"


def test_the_rounds_are_the_three_of_the_test_and_the_censored_one_of_the_close(world):
    assert world.conn.execute("SELECT round_id, period, built_by_run FROM rounds ORDER BY round_id").fetchall() == [
        ("R2011-03-28", "test", "run-1"), ("R2011-04-04", "test", "run-2"), ("R2011-04-11", "test", "run-3"), ("R2011-04-18", "censored", "run-4")]
    assert world.conn.execute("SELECT COUNT(*) FROM round_ops").fetchone()[0] == 0, "the operation of a round is written at the end of its run, by whoever delivers it"


def test_every_round_has_a_list_of_ten_for_every_customer_of_its_base_and_the_control_group_has_its_own(world, quick_view):
    for round_id in ROUNDS:
        customers = [r[0] for r in world.conn.execute("SELECT customer_id FROM contact_base WHERE round_id = ? ORDER BY customer_id", (round_id,))]
        listed = world.conn.execute("SELECT customer_id, COUNT(*), COUNT(DISTINCT stock_code), MIN(rank), MAX(rank), COUNT(DISTINCT grp) FROM offer_lists WHERE round_id = ? GROUP BY customer_id ORDER BY customer_id", (round_id,)).fetchall()
        assert [row[0] for row in listed] == customers and all(row[1:] == (10, 10, 1, 10, 1) for row in listed), round_id
        groups = dict(world.conn.execute("SELECT customer_id, grp FROM holdout_assignments"))
        assert {(c, g) for c, g in world.conn.execute("SELECT DISTINCT customer_id, grp FROM offer_lists WHERE round_id = ?", (round_id,))} == {(c, groups[c]) for c in customers}
        row = world.conn.execute("SELECT base_size, offer_size, control_size FROM rounds WHERE round_id = ?", (round_id,)).fetchone()
        assert row == (len(customers), sum(groups[c] == "offer" for c in customers), sum(groups[c] == "control" for c in customers)) and row[2] > 0
        assert set(r[0] for r in world.conn.execute("SELECT DISTINCT source FROM offer_lists WHERE round_id = ?", (round_id,))) <= set(offers.SOURCES)


def test_every_round_has_the_baselines_of_every_customer_in_both_variants(world):
    for round_id in ROUNDS:
        customers = world.conn.execute("SELECT base_size FROM rounds WHERE round_id = ?", (round_id,)).fetchone()[0]
        counts = world.conn.execute("SELECT method, variant, COUNT(*), COUNT(DISTINCT customer_id) FROM baseline_lists WHERE round_id = ? GROUP BY method, variant", (round_id,)).fetchall()
        assert len(counts) == 16 and all(n == customers * 10 and c == customers for _m, _v, n, c in counts), round_id
        assert {m for m, *_ in counts} == {"b0", "b1", "b2", "b3", "b4", "b5", "b6", "chosen_discovery"}


def test_each_round_is_fitted_with_the_sealed_recipe_and_registered_with_its_artifacts(world):
    launch = registry.read_seal(world.seal_path)["launch"]
    for round_id in ROUNDS:
        models = warehouse.registered_models(world.conn, round_id)
        assert sorted(models) == sorted(["popularity", launch["recipe"]["model"]]), round_id
        for component, (path, digest_, params) in models.items():
            assert path == f"{round_id}/{component}" and artifacts.verify_component(world.models_dir / path, digest_)["params"] == params
        model = models[launch["recipe"]["model"]][2]
        assert (model["model"], model["size"], model["weight"], model["name"]) == (launch["recipe"]["model"], launch["recipe"]["size"], launch["recipe"]["weight"], launch["recipe"]["name"])
    assert warehouse.registered_models(world.conn, ROUNDS[0]) != warehouse.registered_models(world.conn, ROUNDS[1]), "each week refits on its own history"


def test_the_lists_of_a_round_are_what_its_history_gives_and_the_list_of_the_launch_is_the_sealed_one(world, quick_view):
    seal = registry.read_seal(world.seal_path)["launch"]
    lines = warehouse.read_lines(world.conn)
    for round_id in ROUNDS:
        monday = cal.monday_of(round_id)
        history = base.history_before(lines, monday)
        customers = base.contact_base(history, monday, quick_view)["customer_id"].to_numpy()
        from personaloffers.recommend import context

        data = context.prepare(history, monday, customers, quick_view)
        chosen, _ = weekly.sealed_recipes(seal)
        lists = offers.round_lists(data, chosen, quick_view)
        stored = world.conn.execute("SELECT customer_id, rank, stock_code, source FROM offer_lists WHERE round_id = ? ORDER BY customer_id, rank", (round_id,)).fetchall()
        expected = [(int(c), r + 1, str(data.codes[lists.products[i, r]]), offers.SOURCES[int(lists.sources[i, r])]) for i, c in enumerate(lists.customers) for r in range(10)]
        assert stored == expected, round_id
        if round_id == ROUNDS[0]:
            assert offers.lists_fingerprint(lists, data.codes) == seal["lists"]["fingerprint"]


# --- the follow-up ------------------------------------------------------------------------------------------------------------------------------------


def test_the_follow_up_of_a_round_is_what_a_plain_loop_over_the_lines_of_its_week_gives(world, quick_view):
    lines = warehouse.read_lines(world.conn)
    for round_id in ROUNDS:
        monday = cal.monday_of(round_id)
        start, end = cal.window(monday, quick_view)
        listed: dict[int, set[str]] = {}
        for customer, code in world.conn.execute("SELECT customer_id, stock_code FROM offer_lists WHERE round_id = ?", (round_id,)):
            listed.setdefault(customer, set()).add(code)
        bought: dict[int, set[str]] = {}
        spent: dict[int, Decimal] = {}
        for row in lines[(lines["role"] == "purchase") & (lines["invoice_date"] >= start) & (lines["invoice_date"] < end)].itertuples():
            bought.setdefault(int(row.customer_id), set()).add(row.stock_code)
            spent[int(row.customer_id)] = spent.get(int(row.customer_id), Decimal(0)) + Decimal(repr(float(row.price))) * int(row.quantity)
        expected = []
        for customer in [r[0] for r in world.conn.execute("SELECT customer_id FROM contact_base WHERE round_id = ? ORDER BY customer_id", (round_id,))]:
            mine = bought.get(customer, set())
            expected.append((round_id, customer, int(bool(mine)), len(mine), len(mine & listed[customer]), format(spent.get(customer, Decimal(0)), "f"), (end - start).days, None))
        found = world.conn.execute("SELECT round_id, customer_id, bought, products, products_in_offer, spend, days_observed FROM round_outcomes WHERE round_id = ? ORDER BY customer_id", (round_id,)).fetchall()
        assert found == [row[:7] for row in expected], round_id
        assert sum(r[2] for r in found) > 20 and sum(r[4] for r in found) > 0, "some customers bought, and some bought what was on their list"


def test_the_follow_up_counts_the_control_group_too_and_never_a_customer_outside_the_base(world):
    assert world.conn.execute("SELECT COUNT(*) FROM round_outcomes o JOIN holdout_assignments h USING (customer_id) WHERE h.grp = 'control'").fetchone()[0] > 0
    assert world.conn.execute("SELECT COUNT(*) FROM round_outcomes o WHERE NOT EXISTS (SELECT 1 FROM contact_base b WHERE b.round_id = o.round_id AND b.customer_id = o.customer_id)").fetchone()[0] == 0
    assert world.conn.execute("SELECT COUNT(*) FROM round_outcomes WHERE products_in_offer > products").fetchone()[0] == 0


# --- repeating a round ----------------------------------------------------------------------------------------------------------------------------------


def test_repeating_a_round_gives_the_same_lists_byte_for_byte(world, quick_view, workbook, quick_cfg, launched, tmp_path):
    """AC17: a round that was issued, run again, is recomputed, found the same and not written (the file is not touched); and a second replay from the launch, in another folder, issues the same
    lists, baselines, follow-up and artifacts (the same rows and the same hashes, whatever the run keys)."""
    before = digest(world)
    for round_id in ROUNDS:
        again = weekly.emit_round(world.conn, world.view, "run-9", cal.monday_of(round_id), models_dir=world.models_dir, seal_path=world.seal_path)
        assert again.status == "done" and again.lists == 3000
    assert digest(world) == before
    other = copy_world(launched.root, workbook, quick_cfg, tmp_path / "second")
    try:
        replay(other)
        for table, columns in (("offer_lists", "round_id, customer_id, rank, stock_code, source, score, grp"), ("baseline_lists", "round_id, method, variant, customer_id, rank, stock_code"),
                               ("round_outcomes", "round_id, customer_id, bought, products, products_in_offer, spend, days_observed"), ("contact_base", "*"),
                               ("holdout_assignments", "customer_id, grp, method, stratum, assigned_round"),
                               ("model_registry", "round_id, component, params_json, artifact_path, artifact_sha256, fit_lines")):
            query = f"SELECT {columns} FROM {table} ORDER BY 1, 2, 3, 4, 5"
            assert world.conn.execute(query).fetchall() == other.conn.execute(query).fetchall(), table
    finally:
        other.conn.close()


def test_a_round_that_was_issued_is_not_rewritten_when_what_is_recomputed_is_different(world, monkeypatch):
    original = offers.round_lists

    def changed(data, recipe, view, *, cache=None):
        lists = original(data, recipe, view, cache=cache)
        products = lists.products.copy()
        products[0, [0, 1]] = products[0, [1, 0]]
        return offers.RoundLists(lists.customers, products, lists.sources, lists.scores)

    monkeypatch.setattr(offers, "round_lists", changed)
    before = digest(world)
    with pytest.raises(ScoringError, match="R2011-04-04"):
        weekly.emit_round(world.conn, world.view, "run-9", cal.monday_of("R2011-04-04"), models_dir=world.models_dir, seal_path=world.seal_path)
    assert digest(world) == before and not world.conn.in_transaction


def test_a_follow_up_that_was_written_is_checked_and_not_written_again(world):
    before = digest(world)
    again = weekly.track_round(world.conn, world.view, "run-9", cal.monday_of("R2011-04-04"))
    assert again.rows == 0 and again.round_id == "R2011-04-04" and digest(world) == before
    world.conn.execute("DROP TRIGGER round_outcomes_no_delete")
    world.conn.execute("DELETE FROM round_outcomes WHERE round_id = 'R2011-04-04' AND customer_id = (SELECT MIN(customer_id) FROM round_outcomes WHERE round_id = 'R2011-04-04')")
    with pytest.raises(ScoringError, match="seguimiento"):
        weekly.track_round(world.conn, world.view, "run-9", cal.monday_of("R2011-04-04"))


# --- what is not the turn of a delivery ----------------------------------------------------------------------------------------------------------------


def test_a_delivery_that_is_not_the_last_loaded_or_not_a_week_is_refused_before_anything_is_written(world):
    plan = {spec.delivery_id: spec for spec in world.plan}
    before = digest(world)
    with pytest.raises(ScoringError, match="última cargada"):
        weekly.run_round(world.conn, world.view, "run-9", plan["W2011-04-04"], models_dir=world.models_dir, seal_path=world.seal_path)
    with pytest.raises(ScoringError, match="launch"):
        weekly.run_round(world.conn, world.view, "run-9", plan["L2011-03-27"], models_dir=world.models_dir, seal_path=world.seal_path)
    assert digest(world) == before


def test_the_round_of_a_week_that_was_not_built_cannot_be_followed(world):
    with pytest.raises(ScoringError, match="no se armó"):
        weekly.track_round(world.conn, world.view, "run-9", cal.monday_of("R2011-05-02"))


# --- who enters ---------------------------------------------------------------------------------------------------------------------------------------


def test_a_customer_that_enters_the_base_is_assigned_by_the_hash_in_the_round_it_enters(launched, workbook, quick_cfg, tmp_path):
    """Eight customers whose first purchases are in the second week (their lines are renamed to new numbers there): they are in the base of the round after it, with the hash group, and nobody else moves."""
    made = copy_world(launched.root, workbook, quick_cfg, tmp_path / "entering")
    try:
        weekly.emit_round(made.conn, made.view, RUN_KEY, made.view.calendar.test_first_round, models_dir=made.models_dir, seal_path=made.seal_path)
        first = load_next_delivery(made, "run-2")
        weekly.run_round(made.conn, made.view, "run-2", first, models_dir=made.models_dir, seal_path=made.seal_path)
        second = made.plan[2]
        frame = dv.read_delivery(dv.delivery_path(made.cfg, second))
        mine = frame[frame["role"] == "purchase"]
        picked = sorted(mine["customer_id"].dropna().unique())[:8]
        renamed = {int(old): 91001 + n for n, old in enumerate(picked)}
        frame["customer_id"] = frame["customer_id"].map(lambda c: renamed.get(int(c), c) if pd.notna(c) else c).astype("Int64")
        dv.publish_frame(made.cfg, second, frame)
        spec = load_next_delivery(made, "run-3")
        stored_before = holdout.read_assignments(made.conn)
        result = weekly.run_round(made.conn, made.view, "run-3", spec, models_dir=made.models_dir, seal_path=made.seal_path)
        assert result.emitted.new_assignments == 8 and result.emitted.round_id == "R2011-04-11"
        stored = holdout.read_assignments(made.conn).set_index("customer_id")
        entered = stored.loc[sorted(renamed.values())]
        assert set(entered["method"]) == {"hash"} and set(entered["assigned_round"]) == {"R2011-04-11"} and entered["stratum"].isna().all()
        assert all(entered.loc[c, "grp"] == holdout.assign_newcomer(c, made.view) for c in entered.index), "the group of a newcomer is its hash"
        assert holdout.read_assignments(made.conn).iloc[: len(stored_before)].equals(stored_before), "nobody who was assigned moved"
        assert made.conn.execute("SELECT COUNT(*) FROM contact_base WHERE round_id = 'R2011-04-11'").fetchone()[0] == 308
        assert made.conn.execute("SELECT COUNT(*) FROM offer_lists WHERE round_id = 'R2011-04-11' AND customer_id >= 91001 AND customer_id <= 91008").fetchone()[0] == 80
    finally:
        made.conn.close()


# --- the operation of a round ---------------------------------------------------------------------------------------------------------------------------


def test_the_operation_of_a_round_is_written_last_with_what_the_round_and_the_lists_say(world):
    round_id = "R2011-04-04"
    weekly.write_round_ops(world.conn, round_id, "run-3", delivered=190, seconds=2.5)
    row = world.conn.execute("SELECT base, offer, control, new_assignments, lists, delivered, fallback_share, seconds, run_key FROM round_ops WHERE round_id = ?", (round_id,)).fetchone()
    size = world.conn.execute("SELECT base_size, offer_size, control_size FROM rounds WHERE round_id = ?", (round_id,)).fetchone()
    fallback = world.conn.execute("SELECT SUM(source = 'fallback') * 1.0 / COUNT(*) FROM offer_lists WHERE round_id = ?", (round_id,)).fetchone()[0]
    assert row[:3] == size and row[3:6] == (0, size[0], 190) and row[6] == pytest.approx(fallback) and row[7:] == (2.5, "run-3")
    with pytest.raises(Exception, match="solo inserción"):
        weekly.write_round_ops(world.conn, round_id, "run-3", delivered=190, seconds=2.5)
    with pytest.raises(ScoringError):
        weekly.write_round_ops(world.conn, "R2012-01-02", "run-3", delivered=0, seconds=0.1)


def test_the_share_of_the_fallback_is_the_share_of_the_rows_of_the_lists_that_come_from_it(world):
    """The fixture's lists have no fallback (the models always have candidates), so the lists of a made-up round with three of ten products from it for each of two customers prove the share."""
    world.conn.execute("INSERT INTO rounds VALUES ('R2011-05-02', '2011-05-02', 'test', 'run-3', 2, 2, 0)")
    for customer in (91001, 91002):
        for rank in range(1, 11):
            source = "fallback" if rank > 7 else ("discovery" if rank > 5 else "repeat")
            world.conn.execute("INSERT INTO offer_lists VALUES ('R2011-05-02', ?, ?, ?, ?, 1.0, 'offer', 'run-3')", (customer, rank, f"9500{rank}", source))
    weekly.write_round_ops(world.conn, "R2011-05-02", "run-3", delivered=2, seconds=0.5)
    assert world.conn.execute("SELECT lists, fallback_share, delivered FROM round_ops WHERE round_id = 'R2011-05-02'").fetchone() == (2, 0.3, 2)


def test_a_registered_artifact_that_is_not_what_is_recomputed_stops_the_round_before_it_writes(launched, workbook, quick_cfg, tmp_path, monkeypatch):
    """The first round's models were registered by the launch; if they are not what the lists of the round are now made with, nothing is issued (runbook R6)."""
    made = copy_world(launched.root, workbook, quick_cfg, tmp_path / "w")
    try:
        from personaloffers.recommend import blend

        original = blend.model_arrays
        monkeypatch.setattr(blend, "model_arrays", lambda recipe, model: {**original(recipe, model), "extra": np.arange(3)})
        before = digest(made)
        with pytest.raises(artifacts.ArtifactError, match="ya existe"):
            weekly.emit_round(made.conn, made.view, RUN_KEY, made.view.calendar.test_first_round, models_dir=made.models_dir, seal_path=made.seal_path)
        assert digest(made) == before and made.conn.execute("SELECT COUNT(*) FROM offer_lists").fetchone()[0] == 0
        # and with the folders of the registered models gone, what is recomputed is written and found not to be what was registered
        import shutil

        shutil.rmtree(made.models_dir / "R2011-03-28")
        with pytest.raises(ScoringError, match="R6"):
            weekly.emit_round(made.conn, made.view, RUN_KEY, made.view.calendar.test_first_round, models_dir=made.models_dir, seal_path=made.seal_path)
        assert made.conn.execute("SELECT COUNT(*) FROM offer_lists").fetchone()[0] == 0
    finally:
        made.conn.close()
