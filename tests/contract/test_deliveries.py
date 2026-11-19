"""The deliveries and their validation (U05; RF05 to RF07, AC05, AC06; decisions D05, D22, D30): the plan is a launch, one delivery per week of the test and a close; a
delivery is published as a Parquet file with its manifest written last; and V10 to V18 judge it. A blocking rule that fails refuses the delivery and writes nothing."""

from __future__ import annotations

import dataclasses
import hashlib
import json
import sqlite3
import types
from datetime import date, datetime

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from personaloffers import deliveries as dv
from personaloffers import validate as val
from personaloffers import workbook as wb
from personaloffers.config import SealedConfig, load_config
from tests.fixtures.configs import config_for, tree_of
from tests.fixtures.hand_lines import hand_frame

BLOCKING_RULES = ("V10", "V11", "V12", "V13")
EVERY_RULE = ("V10", "V11", "V12", "V13", "V14", "V15", "V16", "V17", "V18")


@pytest.fixture
def world(workbook, quick_cfg, fixture_lines, tmp_path):
    cfg = config_for(quick_cfg, workbook, tmp_path / "project")
    view = SealedConfig.of(cfg, "a" * 64, "b" * 64, "c" * 64)
    return types.SimpleNamespace(cfg=cfg, view=view, lines=fixture_lines, plan=dv.delivery_plan(view), db=tmp_path / "warehouse.sqlite", tmp=tmp_path)


def warehouse_with(path, loaded: list[str] = (), lines: pd.DataFrame | None = None, other: dict[str, str] | None = None):
    """The two tables of the warehouse that a validation reads (U06 creates them for real), holding these loaded deliveries and these lines."""
    conn = sqlite3.connect(path, isolation_level=None)
    conn.execute("CREATE TABLE deliveries (delivery_id TEXT PRIMARY KEY, status TEXT NOT NULL)")
    conn.execute("CREATE TABLE lines (line_key INTEGER PRIMARY KEY, customer_id INTEGER, stock_code TEXT NOT NULL, role TEXT NOT NULL)")
    conn.executemany("INSERT INTO deliveries VALUES (?, 'loaded')", [(name,) for name in loaded])
    conn.executemany("INSERT INTO deliveries VALUES (?, ?)", list((other or {}).items()))
    if lines is not None:
        rows = [(int(r.line_key), None if pd.isna(r.customer_id) else int(r.customer_id), str(r.stock_code), str(r.role)) for r in lines.itertuples()]
        conn.executemany("INSERT INTO lines VALUES (?, ?, ?, ?)", rows)
    return conn


def spec_of(world, delivery_id: str) -> dv.DeliverySpec:
    return next(spec for spec in world.plan if spec.delivery_id == delivery_id)


def publish_all(world, upto: int) -> None:
    for spec in world.plan[:upto]:
        dv.publish_delivery(world.cfg, world.lines, spec)


def folder_of(world):
    return world.tmp / "project"


# --- the plan (RF05, AC05; D05, D22) -------------------------------------------------------------------------------------------------------------------


def test_the_real_plan_is_a_launch_eighteen_weeks_and_a_close(project_root):
    cfg = load_config(project_root / "config" / "pipeline.toml")
    plan = dv.delivery_plan(cfg)
    assert [spec.delivery_id for spec in plan][:3] == ["L2011-07-31", "W2011-08-01", "W2011-08-08"]
    assert [spec.delivery_id for spec in plan][-2:] == ["W2011-11-28", "C2011-12-05"]
    assert [spec.kind for spec in plan] == ["launch"] + ["weekly"] * 18 + ["close"]
    launch, first, last, close = plan[0], plan[1], plan[-2], plan[-1]
    assert (launch.first_day, launch.last_day, launch.as_of) == (date(2009, 12, 1), date(2011, 7, 31), datetime(2011, 8, 1))
    assert (first.first_day, first.last_day, first.as_of) == (date(2011, 8, 1), date(2011, 8, 7), datetime(2011, 8, 8))
    assert (last.first_day, last.last_day, last.as_of) == (date(2011, 11, 28), date(2011, 12, 4), datetime(2011, 12, 5))
    assert (close.first_day, close.last_day, close.as_of) == (date(2011, 12, 5), date(2011, 12, 9), datetime(2011, 12, 10))
    for earlier, later in zip(plan, plan[1:], strict=False):
        assert (later.first_day - earlier.last_day).days == 1, "each delivery starts the day after the last one ends: no day twice, none left out"


def test_the_plan_reads_the_sealed_view_the_same_as_the_configuration(quick_cfg, quick_view):
    assert dv.delivery_plan(quick_view) == dv.delivery_plan(quick_cfg)
    assert [spec.delivery_id for spec in dv.delivery_plan(quick_cfg)] == ["L2011-03-27", "W2011-03-28", "W2011-04-04", "W2011-04-11", "C2011-04-18"]


def test_every_line_goes_in_the_delivery_of_its_date_and_in_only_one(world):
    sizes, seen = [], set()
    for spec in world.plan:
        part = dv.lines_of(world.lines, spec)
        stamps = part["invoice_date"]
        assert (stamps >= datetime.combine(spec.first_day, datetime.min.time())).all() and (stamps < datetime.combine(spec.last_day, datetime.min.time()) + pd.Timedelta(days=1)).all()
        keys = set(part["line_key"])
        assert not keys & seen, "no line in two deliveries"
        seen |= keys
        sizes.append(len(part))
    assert sum(sizes) == len(world.lines) and seen == set(world.lines["line_key"]), "and none in no delivery"
    assert all(size > 0 for size in sizes)
    purchases = world.lines[world.lines["role"] == "purchase"]
    by_date = {spec.delivery_id: set(dv.lines_of(purchases, spec)["line_key"]) for spec in world.plan}
    assert sum(len(keys) for keys in by_date.values()) == len(purchases)


def test_a_line_at_midnight_is_in_the_delivery_that_starts_there_and_not_in_the_one_that_ends(world):
    edges = hand_frame(
        {"invoice_date": datetime(2011, 3, 27, 23, 59, 59, 999999)}, {"invoice_date": datetime(2011, 3, 28, 0, 0, 0)},               # the launch ends and the first week starts
        {"invoice_date": datetime(2011, 4, 3, 23, 59, 59)}, {"invoice_date": datetime(2011, 4, 4, 0, 0, 0)},
        {"invoice_date": datetime(2010, 12, 6, 0, 0, 0)}, {"invoice_date": datetime(2011, 4, 22, 23, 59, 59)},
    )
    parts = dv.split_lines(edges, world.plan)
    keys = edges["line_key"].tolist()
    assert {name: part["line_key"].tolist() for name, part in parts.items()} == {
        "L2011-03-27": [keys[0], keys[4]], "W2011-03-28": [keys[1], keys[2]], "W2011-04-04": [keys[3]], "W2011-04-11": [], "C2011-04-18": [keys[5]]}


def test_a_line_that_no_delivery_covers_is_refused_instead_of_dropped(world):
    early = hand_frame({"invoice_date": datetime(2010, 12, 1, 10, 0)})
    with pytest.raises(ValueError, match="2010-12-01"):
        dv.split_lines(early, world.plan)
    split = dv.split_lines(world.lines, world.plan)
    assert [spec.delivery_id for spec in world.plan] == list(split) and sum(len(part) for part in split.values()) == len(world.lines)


# --- the manifest and the publication -------------------------------------------------------------------------------------------------------------


def test_a_manifest_that_does_not_exist_is_empty_and_one_with_another_shape_is_refused(tmp_path):
    path = tmp_path / "manifest.json"
    assert dv.read_manifest(path) == {"version": 1, "deliveries": {}}
    entry = {"kind": "launch", "first_day": "2011-03-01", "last_day": "2011-03-27", "as_of": "2011-03-28T00:00:00", "rows": 3, "sha256": "a" * 64}
    for bad in ("not json", "[]", "{}", json.dumps({"version": 2, "deliveries": {}}), json.dumps({"version": 1, "deliveries": []}), json.dumps({"version": 1, "deliveries": {"L1": 3}}),
                json.dumps({"version": 1, "deliveries": {"L1": entry | {"extra": 1}}}), json.dumps({"version": 1, "deliveries": {"L1": {k: v for k, v in entry.items() if k != "rows"}}}),
                json.dumps({"version": 1, "deliveries": {"L1": entry | {"rows": -1}}}), json.dumps({"version": 1, "deliveries": {"L1": entry | {"rows": True}}}),
                json.dumps({"version": 1, "deliveries": {"L1": entry | {"sha256": "short"}}}), json.dumps({"version": 1, "deliveries": {"L1": entry | {"kind": "daily"}}})):
        path.write_text(bad, encoding="utf-8")
        with pytest.raises(ValueError, match="manifiesto"):
            dv.read_manifest(path)
    good = {"version": 1, "deliveries": {"L1": entry}}
    dv.write_manifest(path, good)
    assert dv.read_manifest(path) == good and path.read_text(encoding="utf-8") == json.dumps(good, indent=2, sort_keys=True) + "\n"
    before = path.read_bytes()
    with pytest.raises(ValueError, match="manifiesto"):
        dv.write_manifest(path, {"version": 1, "deliveries": {"L1": 3}})
    assert path.read_bytes() == before and [p.name for p in tmp_path.iterdir()] == ["manifest.json"]


def test_a_delivery_is_published_as_its_lines_with_the_manifest_written_last(world):
    spec = world.plan[1]
    entry = dv.publish_delivery(world.cfg, world.lines, spec)
    folder = world.cfg.paths.raw_dir / "deliveries"
    assert sorted(p.relative_to(folder).as_posix() for p in folder.rglob("*") if p.is_file()) == [f"{spec.delivery_id}/lines.parquet", "manifest.json"]
    expected = dv.lines_of(world.lines, spec).reset_index(drop=True)
    published = dv.read_delivery(folder / spec.delivery_id / "lines.parquet")
    pd.testing.assert_frame_equal(published[list(wb.LINE_COLUMNS)], expected[list(wb.LINE_COLUMNS)], check_dtype=False)
    assert list(published.columns) == list(wb.LINE_COLUMNS) and (published["role"] == expected["role"]).all()
    manifest = dv.read_manifest(folder / "manifest.json")
    assert list(manifest["deliveries"]) == [spec.delivery_id] and manifest["deliveries"][spec.delivery_id] == entry
    assert entry == {"kind": "weekly", "first_day": spec.first_day.isoformat(), "last_day": spec.last_day.isoformat(), "as_of": spec.as_of.isoformat(),
                     "rows": len(expected), "sha256": entry["sha256"]}
    assert entry["sha256"] == hashlib.sha256((folder / spec.delivery_id / "lines.parquet").read_bytes()).hexdigest()


def test_publishing_a_delivery_again_changes_nothing_and_adds_the_next_one_beside_it(world):
    first = dv.publish_delivery(world.cfg, world.lines, world.plan[0])
    before = tree_of(world.cfg.paths.raw_dir)
    assert dv.publish_delivery(world.cfg, world.lines, world.plan[0]) == first
    assert tree_of(world.cfg.paths.raw_dir) == before, "the same bytes"
    dv.publish_delivery(world.cfg, world.lines, world.plan[1])
    manifest = dv.read_manifest(world.cfg.paths.raw_dir / "deliveries" / "manifest.json")
    assert sorted(manifest["deliveries"]) == sorted([world.plan[0].delivery_id, world.plan[1].delivery_id])
    kept = f"deliveries/{world.plan[0].delivery_id}/lines.parquet"
    assert tree_of(world.cfg.paths.raw_dir)[kept] == before[kept], "the first delivery's file is as it was"


def test_a_failure_between_the_file_and_the_manifest_leaves_a_delivery_that_is_still_pending_and_publishes_again(world, monkeypatch):
    spec = world.plan[0]

    def broken(path, manifest):
        raise OSError("disk full")

    monkeypatch.setattr(dv, "write_manifest", broken)
    with pytest.raises(OSError, match="disk full"):
        dv.publish_delivery(world.cfg, world.lines, spec)
    folder = world.cfg.paths.raw_dir / "deliveries"
    assert (folder / spec.delivery_id / "lines.parquet").exists() and not (folder / "manifest.json").exists()
    assert dv.next_pending(dv.read_manifest(folder / "manifest.json"), world.plan) == spec
    monkeypatch.undo()
    entry = dv.publish_delivery(world.cfg, world.lines, spec)
    assert dv.read_manifest(folder / "manifest.json")["deliveries"] == {spec.delivery_id: entry}
    assert [p.name for p in (folder / spec.delivery_id).iterdir()] == ["lines.parquet"], "no temporary file left behind"


def test_the_next_pending_delivery_is_the_first_one_that_was_not_published(world):
    manifest = {"version": 1, "deliveries": {}}
    assert dv.next_pending(manifest, world.plan) == world.plan[0]
    for spec in world.plan:
        assert dv.next_pending(manifest, world.plan) == spec
        entry = dv.publish_delivery(world.cfg, world.lines, spec)
        manifest = {"version": 1, "deliveries": {**manifest["deliveries"], spec.delivery_id: entry}}
    assert dv.next_pending(manifest, world.plan) is None
    gap = {"version": 1, "deliveries": {world.plan[2].delivery_id: manifest["deliveries"][world.plan[2].delivery_id]}}
    assert dv.next_pending(gap, world.plan) == world.plan[0], "a later delivery that was published does not hide an earlier one that was not"


def test_the_next_delivery_to_load_is_the_first_one_that_is_not_loaded(world):
    assert dv.next_to_load(world.plan, set()) == world.plan[0]
    assert dv.next_to_load(world.plan, {world.plan[0].delivery_id}) == world.plan[1]
    assert dv.next_to_load(world.plan, {spec.delivery_id for spec in world.plan}) is None
    assert dv.next_to_load(world.plan, {world.plan[1].delivery_id}) == world.plan[0]


# --- V10 to V13: the rules that block, each one refusing without damage (RF07, AC06) ---------------------------------------------------------------------


def sabotage(world, rule: str):
    """A delivery that breaks exactly one blocking rule: ``(spec, path, conn)`` ready to validate. Everything it needs is published first."""
    publish_all(world, 3)
    spec = world.plan[0]
    conn = warehouse_with(world.db)
    folder = world.cfg.paths.raw_dir / "deliveries"
    if rule == "V10":
        spec = world.plan[1]                                              # published and well made, but the launch is not loaded yet
    elif rule == "V11":
        path = folder / spec.delivery_id / "lines.parquet"
        data = bytearray(path.read_bytes())
        data[len(data) // 2] ^= 0x01
        path.write_bytes(bytes(data))                                    # a file that is not the one the manifest names
    elif rule == "V12":
        frame = dv.lines_of(world.lines, spec).reset_index(drop=True)
        frame.loc[3, "invoice_date"] = datetime(2011, 3, 28, 0, 0)       # a day of the next delivery
        dv.publish_frame(world.cfg, spec, frame)
    elif rule == "V13":
        conn.executemany("INSERT INTO lines VALUES (?, ?, ?, ?)", [(int(key), None, "95000", "purchase") for key in dv.lines_of(world.lines, spec)["line_key"].head(4)])
    return spec, folder / spec.delivery_id / "lines.parquet", conn


@pytest.mark.parametrize("rule", BLOCKING_RULES)
def test_each_blocking_rule_rejects_without_damage(rule, world):
    spec, path, conn = sabotage(world, rule)
    before_tree, before_db = tree_of(folder_of(world)), world.db.read_bytes()
    with pytest.raises(val.ValidationError) as caught:
        val.validate_delivery(spec, path, conn, world.view, run_key="run-1")
    error = caught.value
    assert error.EXIT_CODE == 3 and error.report.blocking_failed == (rule,) and error.report.delivery_id == spec.delivery_id and error.report.run_key == "run-1"
    assert not error.report.passed
    assert str(error) == f"{spec.delivery_id}: falla la regla bloqueante {rule}"
    assert tree_of(folder_of(world)) == before_tree, "not a byte of the project changed"
    assert world.db.read_bytes() == before_db, "nor of the warehouse"
    assert not conn.in_transaction


def test_a_delivery_that_fails_v11_is_not_read_and_the_rules_about_its_lines_are_skipped(world):
    spec, path, conn = sabotage(world, "V11")
    with pytest.raises(val.ValidationError) as caught:
        val.validate_delivery(spec, path, conn, world.view, run_key="run-1")
    report = caught.value.report
    assert [r.rule_id for r in report.results] == ["V10", "V11"] and report.skipped == ("V12", "V13", "V14", "V15", "V16", "V17", "V18")
    assert report.results[1].detail["reason"] == "sha256"


def test_v11_names_what_is_wrong_with_the_file(world, tmp_path):
    publish_all(world, 2)
    spec = world.plan[0]
    folder = world.cfg.paths.raw_dir / "deliveries"
    path = folder / spec.delivery_id / "lines.parquet"
    conn = warehouse_with(world.db)

    def reason(**kw) -> str:
        with pytest.raises(val.ValidationError) as caught:
            val.validate_delivery(kw.get("spec", spec), kw.get("path", path), conn, world.view, run_key="run-1")
        assert caught.value.report.blocking_failed == ("V11",)
        return next(r for r in caught.value.report.results if r.rule_id == "V11").detail["reason"]

    good = path.read_bytes()
    manifest_path = folder / "manifest.json"
    manifest = dv.read_manifest(manifest_path)
    # the manifest does not know the delivery
    other = {"version": 1, "deliveries": {k: v for k, v in manifest["deliveries"].items() if k != spec.delivery_id}}
    dv.write_manifest(manifest_path, other)
    assert reason() == "not_in_manifest"
    dv.write_manifest(manifest_path, manifest)
    # the file is gone
    path.unlink()
    assert reason() == "missing_file"
    # the rows are not the manifest's, the hash is
    path.write_bytes(good)
    wrong_rows = {"version": 1, "deliveries": {**manifest["deliveries"], spec.delivery_id: {**manifest["deliveries"][spec.delivery_id], "rows": manifest["deliveries"][spec.delivery_id]["rows"] + 1}}}
    dv.write_manifest(manifest_path, wrong_rows)
    assert reason() == "rows"
    # a file that is not Parquet, with the hash the manifest holds for it
    junk = b"not a parquet file"
    path.write_bytes(junk)
    dv.write_manifest(manifest_path, {"version": 1, "deliveries": {**manifest["deliveries"], spec.delivery_id: {**manifest["deliveries"][spec.delivery_id], "sha256": hashlib.sha256(junk).hexdigest()}}})
    assert reason() == "unreadable"
    # a Parquet file with another schema, with its own hash in the manifest
    table = pa.table({"line_key": pa.array([1], pa.int64())})
    pq.write_table(table, path)
    entry = {**manifest["deliveries"][spec.delivery_id], "rows": 1, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    dv.write_manifest(manifest_path, {"version": 1, "deliveries": {**manifest["deliveries"], spec.delivery_id: entry}})
    assert reason() == "schema"
    # a delivery that is not in the plan at all
    stranger = dataclasses.replace(spec, delivery_id="W2012-01-02")
    dv.write_manifest(manifest_path, manifest)
    path.write_bytes(good)
    with pytest.raises(val.ValidationError) as caught:
        val.validate_delivery(stranger, path, conn, world.view, run_key="run-1")
    assert "V10" in caught.value.report.blocking_failed


def test_v10_accepts_only_the_first_delivery_that_is_not_loaded(world):
    publish_all(world, 3)
    folder = world.cfg.paths.raw_dir / "deliveries"
    first, second = world.plan[0], world.plan[1]
    conn = warehouse_with(world.db, loaded=[first.delivery_id])
    report = val.validate_delivery(second, folder / second.delivery_id / "lines.parquet", conn, world.view, run_key="run-2")
    assert report.passed and next(r for r in report.results if r.rule_id == "V10").passed
    with pytest.raises(val.ValidationError) as caught:   # the first one again: it is loaded, so it is not the next
        val.validate_delivery(first, folder / first.delivery_id / "lines.parquet", conn, world.view, run_key="run-2")
    assert caught.value.report.blocking_failed[0] == "V10"
    detail = next(r for r in caught.value.report.results if r.rule_id == "V10").detail
    assert detail == {"expected": second.delivery_id}


def test_a_delivery_that_is_published_or_rejected_in_the_warehouse_is_not_a_loaded_one(world):
    publish_all(world, 2)
    first = world.plan[0]
    path = world.cfg.paths.raw_dir / "deliveries" / first.delivery_id / "lines.parquet"
    for status in ("published", "rejected"):
        conn = warehouse_with(world.tmp / f"{status}.sqlite", other={first.delivery_id: status})
        assert val.validate_delivery(first, path, conn, world.view, run_key="run-1").passed, f"{status}: the launch is still the next to load"
        assert val.loaded_ids(conn) == set()


def test_v12_and_v13_count_what_breaks_them_and_show_line_keys_never_a_customer(world):
    publish_all(world, 3)
    spec = world.plan[0]
    frame = dv.lines_of(world.lines, spec).reset_index(drop=True)
    frame.loc[[2, 5, 9], "invoice_date"] = datetime(2011, 4, 1, 12, 0)
    frame = pd.concat([frame, frame.iloc[[0]]], ignore_index=True)           # the same line twice
    dv.publish_frame(world.cfg, spec, frame)
    folder = world.cfg.paths.raw_dir / "deliveries"
    conn = warehouse_with(world.db, lines=hand_frame({"line_key": int(frame.loc[11, "line_key"])}))
    with pytest.raises(val.ValidationError) as caught:
        val.validate_delivery(spec, folder / spec.delivery_id / "lines.parquet", conn, world.view, run_key="run-1")
    by_id = {r.rule_id: r for r in caught.value.report.results}
    assert caught.value.report.blocking_failed == ("V12", "V13")
    assert by_id["V12"].rows_affected == 3 and by_id["V12"].examples == tuple(sorted(int(frame.loc[i, "line_key"]) for i in (2, 5, 9)))
    assert by_id["V13"].rows_affected == 2, "one line already loaded and one that is twice in the delivery"
    assert set(by_id["V13"].examples) == {int(frame.loc[0, "line_key"]), int(frame.loc[11, "line_key"])}


def test_the_examples_are_at_most_five_line_keys_in_order(world):
    spec = world.plan[0]
    frame = dv.lines_of(world.lines, spec).reset_index(drop=True)
    frame["invoice_date"] = datetime(2011, 4, 1, 12, 0)
    dv.publish_frame(world.cfg, spec, frame)
    path = world.cfg.paths.raw_dir / "deliveries" / spec.delivery_id / "lines.parquet"
    with pytest.raises(val.ValidationError) as caught:
        val.validate_delivery(spec, path, warehouse_with(world.db), world.view, run_key="run-1")
    v12 = next(r for r in caught.value.report.results if r.rule_id == "V12")
    assert v12.rows_affected == len(frame) and list(v12.examples) == sorted(frame["line_key"].tolist())[:5]


# --- the delivery that passes ------------------------------------------------------------------------------------------------------------------------


def test_a_good_delivery_passes_every_rule_in_order_and_the_validation_writes_nothing(world):
    publish_all(world, 2)
    spec = world.plan[0]
    path = world.cfg.paths.raw_dir / "deliveries" / spec.delivery_id / "lines.parquet"
    before_tree = tree_of(folder_of(world))
    report = val.validate_delivery(spec, path, None, world.view, run_key="run-1")
    assert tuple(r.rule_id for r in report.results) == EVERY_RULE and report.skipped == () and report.passed and report.blocking_failed == ()
    assert tree_of(folder_of(world)) == before_tree
    severities = {r.rule_id: (r.severity, r.scope, r.aggregation) for r in report.results}
    assert [severities[r][0] for r in BLOCKING_RULES] == ["bloqueante"] * 4
    assert [severities[r][0] for r in ("V14", "V15", "V16")] == ["advertencia"] * 3 and [severities[r][0] for r in ("V17", "V18")] == ["informativa"] * 2
    assert {v[2] for v in severities.values()} == {"per_run"}
    assert [r.name_es for r in report.results][0] == "La entrega es la siguiente del plan"
    assert val.validate_delivery(spec, path, warehouse_with(world.db), world.view, run_key="run-1").passed, "an empty warehouse is the same as none"
    assert val.validate_delivery(spec, path, sqlite3.connect(world.tmp / "nothing.sqlite"), world.view, run_key="run-1").passed, "so is a database that has no tables yet"


def test_the_warnings_count_what_they_find_and_do_not_stop_the_delivery(world):
    spec = world.plan[1]
    frame = hand_frame(
        {}, {"internal_repeat": True}, {"internal_repeat": True},                                                       # two repeats
        {"role": "bad_price", "price": 0.0}, {"role": "bad_price", "quantity": -3}, {"role": "bad_price", "price": -1.0, "quantity": 0},   # three bad prices
        {"description": None}, {"description": "   "}, {"description": ""},                                           # three empty descriptions
        {"role": "cancellation", "quantity": -1}, {"role": "adjustment", "customer_id": None}, {"role": "non_product", "stock_code": "POST"},
        {"role": "guest_purchase", "customer_id": None},
    )
    frame["invoice_date"] = datetime(2011, 3, 29, 10, 0)
    dv.publish_frame(world.cfg, spec, frame)
    path = world.cfg.paths.raw_dir / "deliveries" / spec.delivery_id / "lines.parquet"
    conn = warehouse_with(world.db, loaded=[world.plan[0].delivery_id])
    report = val.validate_delivery(spec, path, conn, world.view, run_key="run-2")
    by_id = {r.rule_id: r for r in report.results}
    assert report.passed, "a warning never blocks"
    assert (by_id["V14"].passed, by_id["V14"].rows_affected, list(by_id["V14"].examples)) == (False, 2, [20_000_002, 20_000_003])
    assert (by_id["V15"].passed, by_id["V15"].rows_affected, list(by_id["V15"].examples)) == (False, 3, [20_000_004, 20_000_005, 20_000_006])
    assert (by_id["V16"].passed, by_id["V16"].rows_affected, list(by_id["V16"].examples)) == (False, 3, [20_000_007, 20_000_008, 20_000_009])
    assert by_id["V17"].passed and by_id["V17"].detail == {"cancellation": 1, "adjustment": 1, "non_product": 1, "bad_price": 3, "guest_purchase": 1, "purchase": 6}
    assert by_id["V17"].rows_affected == 0 and by_id["V18"].rows_affected == 0, "an informative rule counts in its detail and affects no line"


def test_a_delivery_with_nothing_to_warn_about_passes_the_warnings(world):
    spec = world.plan[0]
    frame = hand_frame({}, {"line_key": 20_000_002, "stock_code": "95012"})
    frame["invoice_date"] = datetime(2011, 3, 1, 10, 0)
    dv.publish_frame(world.cfg, spec, frame)
    path = world.cfg.paths.raw_dir / "deliveries" / spec.delivery_id / "lines.parquet"
    report = val.validate_delivery(spec, path, None, world.view, run_key="run-1")
    assert all(r.passed for r in report.results) and [r.rows_affected for r in report.results if r.rule_id in ("V14", "V15", "V16")] == [0, 0, 0]
    assert all(r.examples == () for r in report.results)


def test_v18_counts_the_customers_and_the_products_the_warehouse_has_not_seen(world):
    spec = world.plan[1]
    frame = hand_frame(
        {"customer_id": 90001, "stock_code": "95000"}, {"customer_id": 90001, "stock_code": "95012"}, {"customer_id": 90002, "stock_code": "95000"},
        {"customer_id": 90003, "stock_code": "95024", "role": "cancellation", "quantity": -1},       # a cancellation does not make a customer or a product
        {"customer_id": None, "stock_code": "95036", "role": "guest_purchase"},                         # a guest basket brings a product, never a customer
        {"customer_id": 90004, "stock_code": "POST", "role": "non_product"},
    )
    frame["invoice_date"] = datetime(2011, 3, 29, 10, 0)
    dv.publish_frame(world.cfg, spec, frame)
    path = world.cfg.paths.raw_dir / "deliveries" / spec.delivery_id / "lines.parquet"
    nothing = val.validate_delivery(spec, path, warehouse_with(world.tmp / "empty.sqlite", loaded=[world.plan[0].delivery_id]), world.view, run_key="run-2")
    assert next(r for r in nothing.results if r.rule_id == "V18").detail == {"new_customers": 2, "new_products": 3}
    seen = hand_frame({"line_key": 10_000_001, "customer_id": 90001, "stock_code": "95000"}, {"line_key": 10_000_002, "customer_id": 90009, "stock_code": "95036", "role": "guest_purchase"},
                      {"line_key": 10_000_003, "customer_id": 90002, "stock_code": "95012", "role": "cancellation", "quantity": -1})
    conn = warehouse_with(world.db, loaded=[world.plan[0].delivery_id], lines=seen)
    report = val.validate_delivery(spec, path, conn, world.view, run_key="run-2")
    v18 = next(r for r in report.results if r.rule_id == "V18")
    assert v18.detail == {"new_customers": 1, "new_products": 1} and v18.passed and v18.rows_affected == 0, "90002 only cancelled before; 95012 only in a cancellation; 95000 and 95036 are known"


def test_no_customer_number_is_in_the_report(world):
    publish_all(world, 2)
    spec = world.plan[0]
    path = world.cfg.paths.raw_dir / "deliveries" / spec.delivery_id / "lines.parquet"
    report = val.validate_delivery(spec, path, None, world.view, run_key="run-1")
    customers = set(dv.lines_of(world.lines, spec)["customer_id"].dropna().astype(int))
    found = []

    def walk(node):
        if isinstance(node, dict):
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)
        elif isinstance(node, int) and not isinstance(node, bool):
            found.append(node)

    document = report.to_jsonable()
    walk(document)
    assert customers and not customers & set(found)
    text = json.dumps(document) + report.to_markdown()
    assert not any(str(customer) in text for customer in list(customers)[:50])


def test_the_report_is_json_and_a_markdown_table_of_the_same_width(world):
    publish_all(world, 2)
    spec = world.plan[0]
    path = world.cfg.paths.raw_dir / "deliveries" / spec.delivery_id / "lines.parquet"
    report = val.validate_delivery(spec, path, None, world.view, run_key="run|1")
    document = json.loads(json.dumps(report.to_jsonable()))
    assert document["delivery_id"] == spec.delivery_id and document["run_key"] == "run|1" and [r["rule_id"] for r in document["results"]] == list(EVERY_RULE)
    assert set(document["results"][0]) == {"rule_id", "name_es", "severity", "scope", "aggregation", "passed", "rows_affected", "examples", "detail"}
    markdown = report.to_markdown()
    table = [line for line in markdown.splitlines() if line.startswith("|")]
    widths = {len(line.replace("\\|", "").split("|")) for line in table}
    assert len(widths) == 1 and len(table) == 2 + len(EVERY_RULE)
    assert "run\\|1" in markdown and markdown.startswith(f"# Validación de la entrega {spec.delivery_id}")


def test_every_rule_of_the_plan_is_defined_with_its_severity_scope_and_aggregation():
    assert tuple(val.RULES) == EVERY_RULE
    assert {rule_id: val.RULES[rule_id][1] for rule_id in val.RULES} == {"V10": "bloqueante", "V11": "bloqueante", "V12": "bloqueante", "V13": "bloqueante", "V14": "advertencia",
                                                                          "V15": "advertencia", "V16": "advertencia", "V17": "informativa", "V18": "informativa"}
    assert {rule_id: val.RULES[rule_id][1:] for rule_id in ("V12", "V14", "V17")} == {"V12": ("bloqueante", "entrega", "per_run"), "V14": ("advertencia", "línea", "per_run"),
                                                                                   "V17": ("informativa", "entrega", "per_run")}
