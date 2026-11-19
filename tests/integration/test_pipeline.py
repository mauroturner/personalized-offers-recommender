"""The tasks of a run, their state, the ordered close and the refusals (U18, risk item 4: order and concurrency; RF24, AC29, AC30, AC31, AC36; decisions D26, D28, D29; plan sections 3 and 22): the replay of the quick
fixture through the 13 tasks, the run that stays ``running`` until ``report`` closes it in order, a failure that is recorded and does not mask the task's error, and every refusal before anything is written."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from pathlib import Path

import pandas as pd
import pytest

from personaloffers import lock, pipeline, registry, site_export
from personaloffers.pipeline import TASK_IDS, TASKS, RunRefusedError, UsageError
from tests.fixtures.configs import tree_of
from tests.fixtures.piped import copy_piped, run_keys, state_of

EXPECTED_TASKS = ("fetch_source", "deliver", "validate", "load", "track", "build_base", "fit_recipe", "recommend", "deliver_offers", "evaluate", "export", "render_dashboard", "report")


def db(cfg) -> sqlite3.Connection:
    return sqlite3.connect(f"{Path(cfg.paths.warehouse).resolve().as_uri()}?mode=ro", uri=True)


def snapshot(root: Path) -> dict[str, str]:
    """Every file under `root` with its hash, apart from the lock (it is there only while a writer holds it)."""
    return {name: hashlib.sha256(data).hexdigest() for name, data in tree_of(root).items() if not name.endswith("pipeline.lock")}


@pytest.fixture
def before(before_close, workbook, quick_cfg, tmp_path):
    """A copy of the folder in which every delivery but the close was run."""
    return copy_piped(before_close, workbook, quick_cfg, tmp_path / "before")


@pytest.fixture
def after(piped, workbook, quick_cfg, tmp_path):
    """A copy of the folder in which the whole replay ran."""
    return copy_piped(piped, workbook, quick_cfg, tmp_path / "after")


# --- the tasks -----------------------------------------------------------------------------------------------------------------------------------


def test_the_tasks_are_the_thirteen_of_the_plan_in_its_order_and_only_deliver_ends_a_run_that_has_nothing_to_do():
    assert TASK_IDS == EXPECTED_TASKS and [t.task_id for t in TASKS] == list(EXPECTED_TASKS)
    assert [t.task_id for t in TASKS if t.short_circuit] == ["deliver"] and all(callable(t.func) for t in TASKS)
    assert all(t.retries >= 0 and t.timeout_min > 0 for t in TASKS) and TASKS[0].retries == 0, "a source that is refused is not retried"


def test_a_replay_runs_every_delivery_in_its_own_run_and_each_run_the_thirteen_tasks(piped):
    assert len(piped.runs) == 5 and all([step["task"] for step in run] == list(EXPECTED_TASKS) for run in piped.runs)
    keys = run_keys(piped.cfg)
    assert len(keys) == 5
    conn = db(piped.cfg)
    try:
        rows = conn.execute("SELECT run_key, status, delivery_id, peak_working_set_mb, memory_counter, finished_at, message FROM pipeline_runs ORDER BY started_at").fetchall()
        assert [r[1] for r in rows] == ["ok"] * 5 and [r[2] for r in rows] == [spec.delivery_id for spec in piped.plan] and all(r[3] > 0 and r[4] and r[5] and r[6] == "ok" for r in rows)
        assert conn.execute("SELECT COUNT(*) FROM rounds").fetchone()[0] == 4 and conn.execute("SELECT COUNT(*) FROM round_ops").fetchone()[0] == 4
    finally:
        conn.close()
    for key in keys:
        state = state_of(piped.cfg, key)
        assert state["status"] == "ok" and list(state["tasks"]) == list(EXPECTED_TASKS) and all("seconds" in t and "traceback" not in t for t in state["tasks"].values()), key


def test_a_launch_a_weekly_and_a_close_do_what_each_has_to_do_and_skip_the_rest(piped):
    launch, weekly, last, close = (state_of(piped.cfg, key)["tasks"] for key in (run_keys(piped.cfg)[0], run_keys(piped.cfg)[1], run_keys(piped.cfg)[3], run_keys(piped.cfg)[4]))
    assert launch["track"]["skipped"] == "launch" and launch["fit_recipe"]["mode"] == "fresh" and launch["recommend"]["round_id"] == "R2011-03-28" and launch["deliver_offers"]["round_id"] == "R2011-03-28"
    assert launch["evaluate"]["skipped"] == "launch" and weekly["fit_recipe"]["mode"] == "sealed" and weekly["track"]["round_id"] == "R2011-03-28" and weekly["recommend"]["round_id"] == "R2011-04-04"
    assert last["recommend"]["round_id"] == "R2011-04-18" and last["deliver_offers"]["round_id"] == "R2011-04-18" and last["deliver_offers"]["delivered"] == 240 and last["deliver_offers"]["readback_equal"]
    assert close["track"]["round_id"] == "R2011-04-18" and close["recommend"]["skipped"] == "close" and close["deliver_offers"]["skipped"] == "close" and close["evaluate"]["state"] == "first"
    assert close["export"]["site"] == 6 and close["render_dashboard"]["bytes"] > 1000 and close["report"]["run_status"] == "ok"


def test_the_run_of_the_close_leaves_every_output_of_the_flow_and_they_say_the_run_that_made_them(piped):
    cfg, key = piped.cfg, run_keys(piped.cfg)[-1]
    assert site_export.verify_site(cfg.paths.site_dir) == [] and site_export.read_site(cfg.paths.site_dir).summary["run_key"] == key
    assert json.loads((Path(cfg.paths.site_dir) / "manifest.json").read_text(encoding="utf-8"))["run_key"] == key
    summary = json.loads((Path(cfg.paths.reports_dir) / "evaluation_summary.json").read_text(encoding="utf-8"))
    assert summary["source"] == "warehouse" and summary["evaluation_status"] == "sealed" and (Path(cfg.paths.reports_dir) / "evaluation_summary.md").is_file()
    assert registry.read_seal(Path(cfg.paths.seal))["test"]["run_key"] == key
    runs = pd.read_parquet(Path(cfg.paths.outputs_dir) / "dim_pipeline_run.parquet")
    assert sorted(runs["run_key"]) == run_keys(cfg) and set(runs["status"]) == {"ok"}
    assert Path(cfg.paths.dashboard_html).is_file() and (Path(cfg.paths.reports_dir) / "validation" / "latest.json").is_file()
    counts = json.loads((Path(cfg.paths.interim_dir) / "source_counts.json").read_text(encoding="utf-8"))
    assert counts["copies_removed"] > 0 and set(counts["rows_by_sheet"]) == {"Year 2009-2010", "Year 2010-2011"}
    assert site_export.read_site(cfg.paths.site_dir).data["source"]["copies_removed"] == counts["copies_removed"]


def test_the_run_stays_running_until_report_closes_it_in_order(before, monkeypatch):
    cfg = before.cfg
    key = "close-run"
    pipeline.run_all(cfg, run_key=key, only=list(EXPECTED_TASKS[:12]))
    assert state_of(cfg, key)["status"] == "running"
    conn = db(cfg)
    try:
        assert conn.execute("SELECT status FROM pipeline_runs WHERE run_key = ?", (key,)).fetchone() == ("running",)
    finally:
        conn.close()
    order = []
    for step, original in dict(pipeline._CLOSERS).items():
        monkeypatch.setitem(pipeline._CLOSERS, step, lambda ctx, step=step, original=original: (order.append(step), original(ctx))[1])
    result = pipeline.run_task("report", key, cfg)
    assert order == list(pipeline.CLOSING_STEPS) == ["sqlite", "run_table", "summary", "html"] and result["run_status"] == "ok" and state_of(cfg, key)["status"] == "ok"


# --- the refusals, all before anything is written ------------------------------------------------------------------------------------------------------


def test_closed_run_refuses_every_task_and_keeps_its_records(after):
    key = run_keys(after.cfg)[-1]
    before = snapshot(after.root)
    for task_id in TASK_IDS:
        with pytest.raises(RunRefusedError, match="cerrada"):
            pipeline.run_task(task_id, key, after.cfg)
    with pytest.raises(RunRefusedError, match="cerrada"):
        pipeline.run_all(after.cfg, run_key=key)
    assert snapshot(after.root) == before


def test_a_task_of_a_run_that_did_not_load_its_own_delivery_is_refused_and_writes_nothing(after):
    before = snapshot(after.root)
    for task_id in TASK_IDS[3:]:
        with pytest.raises(RunRefusedError, match="no tiene una entrega"):
            pipeline.run_task(task_id, "somebody-else", after.cfg)
    assert snapshot(after.root) == before and not (Path(after.cfg.paths.interim_dir) / "runs" / "somebody-else.json").exists()


def test_a_run_that_holds_a_delivery_it_did_not_load_cannot_work_on_it(before):
    """After ``deliver`` and ``validate`` the run holds a delivery nobody loaded: every task but ``load`` is refused until it does."""
    cfg = before.cfg
    pipeline.run_all(cfg, run_key="first", only=["fetch_source", "deliver", "validate"])
    state = state_of(cfg, "first")
    assert state["tasks"]["deliver"]["delivered"] and state["status"] == "running"
    snap = snapshot(before.root)
    for task_id in TASK_IDS[4:]:
        with pytest.raises(RunRefusedError, match="no la cargó"):
            pipeline.run_task(task_id, "first", cfg)
    assert snapshot(before.root) == snap
    assert pipeline.run_task("load", "first", cfg)["delivery_id"] == state["tasks"]["deliver"]["delivery_id"]


def test_load_is_refused_without_a_passed_validation_of_this_run(before):
    cfg = before.cfg
    pipeline.run_all(cfg, run_key="run-x", only=["fetch_source", "deliver"])
    snap = snapshot(before.root)
    with pytest.raises(RunRefusedError, match="no validó su entrega"):
        pipeline.run_task("load", "run-x", cfg)
    assert snapshot(before.root) == snap
    report = Path(cfg.paths.reports_dir) / "validation" / "history" / "run-x.json"
    pipeline.run_task("validate", "run-x", cfg)
    document = json.loads(report.read_text(encoding="utf-8"))
    document["results"][0]["passed"] = False
    report.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(RunRefusedError, match=document["results"][0]["rule_id"]):
        pipeline.run_task("load", "run-x", cfg)


def test_a_weekly_delivery_is_refused_without_the_seal_of_the_launch(workbook, quick_cfg, tmp_path):
    from tests.fixtures.configs import config_for

    cfg = config_for(quick_cfg, workbook, tmp_path / "unsealed")
    pipeline.run_all(cfg, run_key="launch", only=["fetch_source", "deliver", "validate", "load"])
    manifest = (Path(cfg.paths.raw_dir) / "deliveries" / "manifest.json").read_bytes()
    warehouse = Path(cfg.paths.warehouse).read_bytes()
    pipeline.run_task("fetch_source", "weekly", cfg)
    with pytest.raises(RunRefusedError, match="sello"):
        pipeline.run_task("deliver", "weekly", cfg)
    assert list(state_of(cfg, "weekly")["tasks"]) == ["fetch_source"], "nothing of deliver was recorded"
    assert (Path(cfg.paths.raw_dir) / "deliveries" / "manifest.json").read_bytes() == manifest and Path(cfg.paths.warehouse).read_bytes() == warehouse


def test_the_test_is_not_evaluated_under_another_configuration_while_the_seal_has_no_test(before):
    """Every task of the run of the close is refused before it writes when the configuration is not the sealed one and the seal has no test part (RF18)."""
    import dataclasses

    other = dataclasses.replace(before.cfg, evaluation=dataclasses.replace(before.cfg.evaluation, resamples=before.cfg.evaluation.resamples + 1))
    snap = snapshot(before.root)
    with pytest.raises(RunRefusedError, match="no es la sellada"):
        pipeline.run_all(other, run_key="close-other")
    assert snapshot(before.root) == snap and registry.read_seal(Path(before.cfg.paths.seal)).get("test") is None


def test_a_state_that_does_not_agree_with_the_manifest_is_refused_naming_r11_before_anything_is_written(after):
    Path(after.cfg.paths.warehouse).unlink()
    snap = snapshot(after.root)
    with pytest.raises(RunRefusedError, match="R11"):
        pipeline.run_all(after.cfg)
    with pytest.raises(RunRefusedError, match="R11"):
        pipeline.replay(after.cfg)
    assert snapshot(after.root) == snap


# --- no delivery, failures and the lock --------------------------------------------------------------------------------------------------------------


def test_a_run_of_an_older_delivery_cannot_follow_up_issue_or_deliver_once_a_later_one_is_loaded(after):
    """The tasks from ``track`` to ``deliver_offers`` work on the latest delivery that was loaded: a run of an earlier one that is still open is refused them, and the refusal names the latest."""
    keys = run_keys(after.cfg)
    older = state_of(after.cfg, keys[1])
    older["status"] = "running"
    (Path(after.cfg.paths.interim_dir) / "runs" / f"{keys[1]}.json").write_text(json.dumps(older), encoding="utf-8")
    snap = snapshot(after.root)
    for task_id in TASK_IDS[4:9]:
        with pytest.raises(RunRefusedError, match="la última cargada es la C"):
            pipeline.run_task(task_id, keys[1], after.cfg)
    assert snapshot(after.root) == snap


def test_a_run_with_nothing_to_deliver_ends_after_deliver_as_no_delivery_and_is_closed(after):
    outcome = pipeline.run_all(after.cfg, run_key="idle")
    assert [step["task"] for step in outcome] == ["fetch_source", "deliver"] and outcome[-1]["result"]["delivered"] is False and outcome[-1]["result"]["run_status"] == "no_delivery"
    assert state_of(after.cfg, "idle")["status"] == "no_delivery"
    conn = db(after.cfg)
    try:
        assert conn.execute("SELECT status FROM pipeline_runs WHERE run_key = 'idle'").fetchone() == ("no_delivery",)
    finally:
        conn.close()
    with pytest.raises(RunRefusedError, match="cerrada"):
        pipeline.run_task("track", "idle", after.cfg)
    assert pipeline.replay(after.cfg) == []


def test_a_failure_after_load_marks_the_run_failed_and_rewrites_what_was_exported(before, monkeypatch):
    cfg, key = before.cfg, "failing"
    pipeline.run_all(cfg, run_key=key, only=list(EXPECTED_TASKS[:11]))
    assert json.loads((Path(cfg.paths.site_dir) / "summary.json").read_text(encoding="utf-8"))["status"] == "running"
    monkeypatch.setattr(pipeline, "render_design", lambda *a, **k: (_ for _ in ()).throw(RuntimeError(f"boom at {cfg.paths.dashboard_html}")))
    with pytest.raises(RuntimeError, match="boom"):
        pipeline.run_task("render_dashboard", key, cfg)
    state = state_of(cfg, key)
    assert state["status"] == "failed" and state["tasks"]["render_dashboard"]["status"] == "failed" and "boom" in state["tasks"]["render_dashboard"]["traceback"]
    conn = db(cfg)
    try:
        assert conn.execute("SELECT status, message FROM pipeline_runs WHERE run_key = ?", (key,)).fetchone() == ("failed", "render_dashboard: RuntimeError: boom at <path>"), "the message of a run is published in the run table: no path of this machine"
    finally:
        conn.close()
    assert json.loads((Path(cfg.paths.site_dir) / "summary.json").read_text(encoding="utf-8"))["status"] == "failed"
    assert pd.read_parquet(Path(cfg.paths.outputs_dir) / "dim_pipeline_run.parquet").set_index("run_key").loc[key, "status"] == "failed"
    monkeypatch.undo()
    pipeline.run_task("render_dashboard", key, cfg)
    assert state_of(cfg, key)["status"] == "running", "a failed run is reopened by the task that runs again"
    conn = db(cfg)
    try:
        assert conn.execute("SELECT status, message FROM pipeline_runs WHERE run_key = ?", (key,)).fetchone() == ("running", "")
    finally:
        conn.close()
    result = pipeline.run_all(cfg, run_key=key, start="render_dashboard")
    assert [s["task"] for s in result] == ["render_dashboard", "report"] and state_of(cfg, key)["status"] == "ok", "a failed run is reopened and finished from the task that failed"


def test_failure_handler_write_errors_do_not_mask_the_task_error(before, monkeypatch):
    cfg, key = before.cfg, "masked"
    pipeline.run_all(cfg, run_key=key, only=list(EXPECTED_TASKS[:11]))
    monkeypatch.setattr(pipeline, "render_design", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    original = pipeline._write_state

    def write(path, state):
        if state.get("status") == "failed":
            raise OSError("disk full")
        return original(path, state)

    monkeypatch.setattr(pipeline, "_write_state", write)
    monkeypatch.setattr(pipeline, "_record", lambda *a, **k: (_ for _ in ()).throw(OSError("database is locked")))
    monkeypatch.setattr(pipeline, "export_run_table", lambda *a, **k: (_ for _ in ()).throw(OSError("no space")))
    with pytest.raises(RuntimeError, match="boom"):
        pipeline.run_task("render_dashboard", key, cfg)


def test_a_second_writer_is_refused_before_anything_is_written(after):
    held, release = threading.Event(), threading.Event()

    def hold():
        with lock.sole_writer(after.cfg.paths.interim_dir, "another", None):
            held.set()
            release.wait(10)

    thread = threading.Thread(target=hold)
    thread.start()
    try:
        assert held.wait(10)
        snap = snapshot(after.root)
        for call in (lambda: pipeline.run_task("fetch_source", "x", after.cfg), lambda: pipeline.run_all(after.cfg, run_key="y")):
            with pytest.raises(lock.RunLockedError):
                call()
        assert snapshot(after.root) == snap
    finally:
        release.set()
        thread.join()


# --- the plan of a replay --------------------------------------------------------------------------------------------------------------------------


def test_a_replay_until_a_delivery_that_is_not_in_the_plan_or_is_loaded_already_is_refused_before_it_writes(before, after):
    snap = snapshot(before.root)
    with pytest.raises(UsageError, match="no es una entrega del plan"):
        pipeline.replay(before.cfg, until="W1999-01-04")
    with pytest.raises(UsageError, match="anterior a la siguiente pendiente"):
        pipeline.replay(before.cfg, until="L2011-03-27")
    assert snapshot(before.root) == snap
    with pytest.raises(UsageError, match="no hay entregas pendientes"):
        pipeline.replay(after.cfg, until="L2011-03-27")


def test_a_selection_that_names_an_unknown_task_or_two_selections_is_a_usage_error_and_writes_nothing(after):
    snap = snapshot(after.root)
    for call in (lambda: pipeline.run_all(after.cfg, only=["nope"]), lambda: pipeline.run_all(after.cfg, only=["load"], start="load"), lambda: pipeline.run_all(after.cfg, only=[]),
                 lambda: pipeline.run_task("nope", None, after.cfg), lambda: pipeline.run_all(after.cfg, start="nope")):
        with pytest.raises(UsageError):
            call()
    assert snapshot(after.root) == snap
