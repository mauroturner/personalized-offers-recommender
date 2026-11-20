"""The tasks of a run, their state, the ordered close and the refusals (RF24; RNF03, RNF08, RNF16; AC29, AC30, AC31, AC36; risk item 4: order and concurrency; plan sections 3 and 22; D26, D28, D29). Adapted from project 07's
``pipeline.py`` with its corrections.

``TASKS`` is the one list the command line, the entry API and the Airflow DAG run, in this order, with these functions. Every task of a run works on the state file ``<interim>/runs/<run_key>.json`` (the start, the
delivery, the status and the result of each task with its seconds and its memory peaks with their counter, or the whole traceback if it failed) and, from ``load`` on, on the run's row of ``pipeline_runs``. The bodies of
the model's tasks stay where they were written (``launch.run_launch``, ``weekly.track_round`` and ``weekly.emit_round``, ``crm.client.deliver_round``, ``reporting.evaluate``, ``export.export_star_schema``,
``site_export.export_site``): a task here reads what the earlier ones left, builds the ``RunMeta`` and the sealed view they take and calls them.

* **One writer.** ``run_task``, ``run_all`` and ``replay`` hold ``lock.sole_writer`` from before the state file is touched until they return (D29): a second writer is ``RunLockedError`` (exit 2) and writes nothing. A
  ``replay`` with nothing pending returns at once and does not take it.
* **Refusals before writing** (``RunRefusedError``, exit 2, no retry), in this order: any task of a run that ended (``ok`` or ``no_delivery``); ``deliver`` in a run that already holds another delivery; every task after
  ``load`` unless this run loaded its own delivery; ``load`` without this run's validation or with a blocking rule failing in it; the tasks that follow up, issue or deliver (``track`` to ``deliver_offers``) when the run's
  delivery is not the latest loaded one; ``deliver`` of a weekly or the close without the seal of the launch (RNF07e); while the seal has no test part, every task of the run of the close under a configuration that is not the
  sealed one (``registry.EvaluationRefusedError``); and every task from ``load`` on of a run that holds no delivery (``task load`` without ``--run-key``). A new run's state file is written only once its first task passed them
  all. ``run_all`` and ``replay`` also refuse a folder whose state does not agree (``refuse_a_state_that_does_not_agree``, runbook R11).
* **The close.** The run stays ``running`` until ``report`` closes it in this order: SQLite ``ok``, ``dim_pipeline_run.parquet`` alone, ``summary.json`` and the site manifest, and the HTML. Closing never creates a run's
  row: it is ``load``'s.
* **A failure** after ``load`` marks the run ``failed`` in the state file and in SQLite and rewrites the run table, the summary and the HTML if they exist; each of those writes is tried on its own and logged if it fails,
  and the task's error is raised again (AC29). A run with no delivery records ``no_delivery``. The message of a run's row is published in the run table, so it never carries a path of this machine.
* **Which delivery.** ``deliver`` publishes the first delivery of the plan that is not loaded (a delivery that a run published and did not load is published again, the same bytes): a run that failed before ``load`` is
  repeated, not skipped. The checkpoints of the round (``build_base``, ``fit_recipe``, ``recommend``) work on the round the delivery builds: the first test round for the launch, the next Monday for a weekly one and none for the
  close; ``recommend`` is the one transaction of ``weekly.emit_round`` (what is issued is not redone, D14).
"""

from __future__ import annotations

import os

# RNF01 (plan section 2; B3 of the evaluation, D47): one thread of BLAS, set before the first import below loads numpy, scipy or implicit (the library reads it when it is loaded). With more threads the
# refitted scores change in their last bits, so a rebuild would not give the issued lists byte for byte. A value from outside is replaced: the flow is the same bytes on every machine.
os.environ["OPENBLAS_NUM_THREADS"] = "1"
os.environ["MKL_NUM_THREADS"] = "1"

import dataclasses  # noqa: E402  (every import of the module comes after the two variables)
import json
import logging
import re
import sqlite3
import tempfile
import time
import traceback
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from personaloffers import base, evaluation, launch, registry, reporting, validate, warehouse, weekly
from personaloffers import calendar as cal
from personaloffers import deliveries as dv
from personaloffers import sources
from personaloffers import workbook as wb
from personaloffers.config import PipelineConfig, SealedConfig, load_config
from personaloffers.crm.client import deliver_round, make_client
from personaloffers.dashboard.render import render_design
from personaloffers.dashboard.semantic_model import MODEL
from personaloffers.deliveries import DeliverySpec
from personaloffers.email_export import email_path, write_email_csv
from personaloffers.export import export_run_table, export_star_schema
from personaloffers.files import write_atomic
from personaloffers.lock import RunLockedError, RunRefusedError, RunStateError, sole_writer
from personaloffers.registry import EvaluationRefusedError, SealError
from personaloffers.site_export import export_site, export_summary
from personaloffers.sysinfo import MemoryPeaks, peak_memory
from personaloffers.validate import RuleResult, ValidationError, ValidationReport
from personaloffers.warehouse import apply_schema, connect

logger = logging.getLogger(__name__)

CLOSED_STATUSES = ("ok", "no_delivery")
CLOSING_STEPS = ("sqlite", "run_table", "summary", "html")
RUN_COLUMNS = ("run_key", "started_at", "finished_at", "status", "delivery_id", "as_of", "config_sha256", "round_id", "peak_working_set_mb", "memory_counter", "message")
STAMP = "%Y-%m-%d %H:%M:%S"
MESSAGE_LIMIT = 500
SOURCE_COUNTS = "source_counts.json"
NO_HASHES = {"zip": "0" * 64, "member": "0" * 64, "lines": "0" * 64}      # the plan of deliveries needs dates and identifiers only

__all__ = ["TASKS", "TASK_IDS", "RunContext", "RunLockedError", "RunRefusedError", "RunStateError", "TaskSpec", "UsageError", "replay", "run_all", "run_task"]


class UsageError(ValueError):
    """A command asked for something the flow does not do (an unknown task, two selections together): nothing was written."""


@dataclass(frozen=True)
class RunContext:
    cfg: PipelineConfig
    run_key: str
    started_at: datetime
    state_path: Path


@dataclass(frozen=True)
class TaskSpec:
    """One task: its id, its function and the limits the Airflow DAG gives it (retries, minutes between them, timeout in minutes; Airflow enforces them, ``run_task`` runs a task once). ``short_circuit`` marks
    ``deliver``: with no delivery left the run ends there."""

    task_id: str
    func: Callable[[RunContext], dict]
    retries: int = 0
    retry_delay_min: int = 0
    timeout_min: int = 30
    short_circuit: bool = False


# --- state ------------------------------------------------------------------------------------------------------------------


def make_run_key(source: str | datetime) -> str:
    if isinstance(source, datetime):
        return source.astimezone(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    key = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in str(source)).strip("_")
    if not key:
        raise UsageError("una clave de corrida no puede estar vacía")
    return key


def _state_path(cfg: PipelineConfig, run_key: str) -> Path:
    return Path(cfg.paths.interim_dir) / "runs" / f"{run_key}.json"


def _read_state(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def _write_state(path: Path, state: dict) -> None:
    write_atomic(path, json.dumps(state, indent=2, ensure_ascii=False, default=str) + "\n")


def _context(cfg: PipelineConfig, run_id: str | None, when: datetime) -> RunContext:
    """The run `run_id` (a new one at `when` if it has no state file yet). Nothing is written here: a new run's state file is created by its first task once that task passed every refusal (``_open``), so a
    refused run leaves nothing behind."""
    run_key = make_run_key(run_id if run_id is not None else when)
    path = _state_path(cfg, run_key)
    state = _read_state(path)
    started = datetime.fromisoformat(state["started_at"]) if state else when.replace(microsecond=0)
    return RunContext(cfg, run_key, started, path)


def _open(ctx: RunContext) -> None:
    if not ctx.state_path.exists():
        _write_state(ctx.state_path, {"run_key": ctx.run_key, "started_at": ctx.started_at.isoformat(timespec="seconds"), "status": "running", "tasks": {}})


def _task_result(ctx: RunContext, task_id: str) -> dict:
    result = _read_state(ctx.state_path).get("tasks", {}).get(task_id)
    if result is None or result.get("status") in ("failed", "rejected"):
        raise RunStateError(f"la corrida {ctx.run_key} no tiene el resultado de la tarea {task_id}: corra esa tarea antes (python -m personaloffers task {task_id} --run-key {ctx.run_key})")
    return result


def _save_task(ctx: RunContext, task_id: str, result: dict, status: str | None = None) -> None:
    state = _read_state(ctx.state_path)
    state.setdefault("tasks", {})[task_id] = result
    if status:
        state["status"] = status
    _write_state(ctx.state_path, state)


def _mark_rejected(ctx: RunContext, task_id: str, report: ValidationReport) -> None:
    state = _read_state(ctx.state_path)
    state["status"] = "rejected"
    state.setdefault("tasks", {})[task_id] = {"status": "rejected", "rules": list(report.blocking_failed)}
    _write_state(ctx.state_path, state)


def _now_text() -> str:
    return datetime.now(UTC).strftime(STAMP)


def _stamp(value: datetime) -> str:
    return value.strftime(STAMP)


def _peak() -> MemoryPeaks | None:
    """The process's memory peaks, or None: telemetry never discards the result of a task that finished."""
    try:
        return peak_memory()
    except Exception:
        logger.warning("could not measure the peak memory", exc_info=True)
        return None


_FOLDER = "<folder>"
_ABSOLUTE_PATH = re.compile(r"(?:<folder>|(?<![A-Za-z])[A-Za-z]:[\\/]|\\\\|/(?:home|Users|tmp|var|private|mnt|opt|root|usr|etc|srv|run|media)/)[^\s'\"<>|]*")


def _without_paths(text: str, cfg: PipelineConfig) -> str:
    """`text` with every path of this machine taken out: each path that starts at a folder this machine is known by (the project's, the user's, the temporary one: they may hold spaces) or looks absolute becomes
    ``<path>``, whatever follows it. The message of a run's row is published in the run table."""
    known = {str(cfg.project_root), Path(cfg.project_root).as_posix(), str(Path.home()), Path.home().as_posix(), tempfile.gettempdir(), Path(tempfile.gettempdir()).as_posix()}
    for folder in sorted((k for k in known if len(k) > 3), key=len, reverse=True):
        text = text.replace(folder, _FOLDER)
    return _ABSOLUTE_PATH.sub("<path>", text)


# --- the warehouse, as the tasks need it ----------------------------------------------------------------------------------------


def _read_only(cfg: PipelineConfig) -> sqlite3.Connection:
    """The warehouse for reading; before the first load there is none, and asking must not create it."""
    path = Path(cfg.paths.warehouse)
    return sqlite3.connect(":memory:") if not path.exists() else sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)


def _has_table(conn: sqlite3.Connection, name: str) -> bool:
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (name,)).fetchone() is not None


def _loaded(cfg: PipelineConfig) -> set[str]:
    conn = _read_only(cfg)
    try:
        return validate.loaded_ids(conn)
    finally:
        conn.close()


def _plan_of(cfg: PipelineConfig) -> list[DeliverySpec]:
    """The plan of deliveries of the configuration (it needs no hash of a source: dates and identifiers only)."""
    return dv.delivery_plan(registry.sealed_view(cfg, NO_HASHES))


def refuse_a_state_that_does_not_agree(cfg: PipelineConfig) -> None:
    """R11 followed in part, refused before anything is written: the manifest of deliveries names deliveries that the warehouse does not hold as loaded, more than the one that a run in flight may have published
    and not loaded yet (the warehouse was moved aside or is another one: the run would find the deliveries published and load them out of order, or the launch would be refused by V10)."""
    manifest = dv.read_manifest(dv.deliveries_dir(cfg) / dv.MANIFEST_NAME)
    published = set(manifest["deliveries"])
    if len(published) > 1:
        unloaded = sorted(published - _loaded(cfg))
        if len(unloaded) > 1:
            raise RunRefusedError(f"el manifiesto de entregas dice que {len(published)} entregas están publicadas y el almacén no tiene cargadas {len(unloaded)} de ellas ({', '.join(unloaded[:3])}{'…' if len(unloaded) > 3 else ''}): "
                                  "el almacén se movió o es otro. Para reconstruir desde cero, mover también las entregas (raw/deliveries, con su manifiesto), el CRM sustituto y el sello (docs/runbook.md, R11). "
                                  "No se escribió nada.")


def _has_record(ctx: RunContext) -> bool:
    conn = _read_only(ctx.cfg)
    try:
        return _has_table(conn, "pipeline_runs") and conn.execute("SELECT 1 FROM pipeline_runs WHERE run_key = ?", (ctx.run_key,)).fetchone() is not None
    finally:
        conn.close()


def record_run(conn: sqlite3.Connection, fields: dict) -> None:
    """Create or update the run's row of ``pipeline_runs`` with `fields` (only the columns given change)."""
    unknown = set(fields) - set(RUN_COLUMNS)
    if unknown:
        raise ValueError(f"columnas desconocidas de pipeline_runs: {sorted(unknown)}")
    columns = [c for c in fields if c != "run_key"]
    updated = conn.execute(f"UPDATE pipeline_runs SET {', '.join(f'{c} = ?' for c in columns)} WHERE run_key = ?", [*(fields[c] for c in columns), fields["run_key"]]).rowcount if columns else 0
    if not updated:
        names = list(fields)
        conn.execute(f"INSERT INTO pipeline_runs ({', '.join(names)}) VALUES ({', '.join('?' for _ in names)})", [fields[c] for c in names])


def _record(ctx: RunContext, **fields) -> None:
    if "message" in fields:
        fields["message"] = _without_paths(str(fields["message"]), ctx.cfg)[:MESSAGE_LIMIT]
    conn = connect(ctx.cfg.paths.warehouse)
    try:
        apply_schema(conn)
        record_run(conn, {"run_key": ctx.run_key, **fields})
    finally:
        conn.close()


def _latest_loaded(conn: sqlite3.Connection) -> tuple[str, str, datetime] | None:
    if not _has_table(conn, "deliveries"):
        return None
    row = conn.execute("SELECT delivery_id, run_key, as_of FROM deliveries WHERE status = 'loaded' ORDER BY as_of DESC, rowid DESC LIMIT 1").fetchone()
    return None if row is None else (row[0], row[1], datetime.fromisoformat(row[2]))


def _loaded_by(conn: sqlite3.Connection, delivery_id: str) -> str | None:
    if not _has_table(conn, "deliveries"):
        return None
    row = conn.execute("SELECT run_key FROM deliveries WHERE delivery_id = ? AND status = 'loaded'", (delivery_id,)).fetchone()
    return row[0] if row else None


# --- the validation report of a run, between two processes -----------------------------------------------------------------------


def _validation_dir(cfg: PipelineConfig) -> Path:
    return Path(cfg.paths.reports_dir) / "validation"


def _report_path(cfg: PipelineConfig, run_key: str) -> Path:
    return _validation_dir(cfg) / "history" / f"{run_key}.json"


def _report_text(report: ValidationReport) -> str:
    return json.dumps(report.to_jsonable(), indent=1, ensure_ascii=False, sort_keys=True) + "\n"


def _read_report(path: Path) -> ValidationReport:
    document = json.loads(path.read_text(encoding="utf-8"))
    results = tuple(RuleResult(r["rule_id"], r["name_es"], r["severity"], r["scope"], r["aggregation"], r["passed"], r["rows_affected"], tuple(r["examples"]), r["detail"]) for r in document["results"])
    return ValidationReport(document["delivery_id"], document["run_key"], results, tuple(document["skipped"]), document["rows"], document["sha256"])


def _write_report(cfg: PipelineConfig, report: ValidationReport) -> None:
    write_atomic(_report_path(cfg, report.run_key), _report_text(report))


# --- the meta of a run -------------------------------------------------------------------------------------------------------------


def _held_delivery(ctx: RunContext) -> dict:
    return _read_state(ctx.state_path).get("tasks", {}).get("deliver", {})


def _view(ctx: RunContext) -> SealedConfig:
    return registry.sealed_view(ctx.cfg, _task_result(ctx, "fetch_source")["source_sha256"])


def _spec(ctx: RunContext) -> DeliverySpec:
    delivery_id = _held_delivery(ctx)["delivery_id"]
    return next(spec for spec in dv.delivery_plan(_view(ctx)) if spec.delivery_id == delivery_id)


def _meta(ctx: RunContext) -> reporting.RunMeta:
    return reporting.RunMeta(ctx.run_key, _spec(ctx).as_of)


def _round_of(spec: DeliverySpec, view: SealedConfig) -> Any:
    """The Monday of the round that the delivery `spec` builds: the first of the test for the launch, the next one for a weekly delivery, none for the close."""
    if spec.kind == "launch":
        return view.calendar.test_first_round
    return spec.first_day + timedelta(days=cal.DAYS_PER_ROUND) if spec.kind == "weekly" else None


def source_counts(cfg: PipelineConfig) -> dict[str, Any] | None:
    """What the first build of the canonical lines found in the source (the copies it removed and the rows of each sheet), or None: the warehouse does not hold them and the site says so."""
    path = Path(cfg.paths.interim_dir) / SOURCE_COUNTS
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None


# --- the tasks ---------------------------------------------------------------------------------------------------------------------


def fetch_source(ctx: RunContext) -> dict:
    """V01 to V07 over the zip and the workbook and the canonical lines (``sources.fetch_source``); when the lines were built now, what the source held (copies, rows of each sheet) is kept for the site."""
    result = sources.fetch_source(ctx.cfg)
    if result.get("built"):
        write_atomic(Path(ctx.cfg.paths.interim_dir) / SOURCE_COUNTS, json.dumps({"copies_removed": result["copies"], "rows_by_sheet": result["rows_by_sheet"], "internal_repeats": result["repeats"]},
                                                                               indent=1, sort_keys=True) + "\n")
    return {**result, "source_sha256": {"zip": result["zip_sha256"], "member": result["member_sha256"], "lines": result["lines_sha256"]}}


def deliver(ctx: RunContext) -> dict:
    """Publish the first delivery of the plan that is not loaded (D22): the launch, a week, the close; without one left the run ends here as ``no_delivery``."""
    cfg, view = ctx.cfg, _view(ctx)
    spec = dv.next_to_load(dv.delivery_plan(view), _loaded(cfg))
    if spec is None:
        _record(ctx, started_at=_stamp(ctx.started_at.replace(tzinfo=None)), finished_at=_now_text(), status="no_delivery", message="no hay entregas pendientes")
        return {"delivered": False, "run_status": "no_delivery", "message": "no hay entregas pendientes: las del plan ya están cargadas"}
    entry = dv.publish_delivery(cfg, wb.read_lines(cfg), spec)
    return {"delivered": True, "delivery_id": spec.delivery_id, "kind": spec.kind, "first_day": spec.first_day.isoformat(), "as_of": _stamp(spec.as_of), "rows": entry["rows"], "sha256": entry["sha256"]}


def validate_task(ctx: RunContext) -> dict:
    """V10 to V18 over the delivery's file; a blocking rule rejects the delivery (exit 3)."""
    cfg, view = ctx.cfg, _view(ctx)
    spec = _spec(ctx)
    conn = connect(cfg.paths.warehouse) if Path(cfg.paths.warehouse).exists() else None
    try:
        report = validate.validate_delivery(spec, dv.delivery_path(cfg, spec), conn, view, run_key=ctx.run_key)
    except ValidationError as error:
        _write_report(cfg, error.report)
        _mark_rejected(ctx, "validate", error.report)
        raise
    finally:
        if conn is not None:
            conn.close()
    _write_report(cfg, report)
    return {"rows": report.rows, "rules": [r.rule_id for r in report.results], "failed": [r.rule_id for r in report.results if not r.passed]}


def load(ctx: RunContext) -> dict:
    """Load the delivery, the validation of this run and the run itself in one transaction (``warehouse.load_delivery``)."""
    cfg, view = ctx.cfg, _view(ctx)
    spec = _spec(ctx)
    report = _read_report(_report_path(cfg, ctx.run_key))
    lines = dv.read_delivery(dv.delivery_path(cfg, spec))
    conn = connect(cfg.paths.warehouse)
    try:
        result = warehouse.load_delivery(conn, spec, lines, report, ctx.run_key, started_at=ctx.started_at.replace(tzinfo=None), config_sha256=registry.config_fingerprint(view))
    finally:
        conn.close()
    return {"delivery_id": spec.delivery_id, "lines": result.lines, "products": result.products}


def track(ctx: RunContext) -> dict:
    """The follow-up of the round whose week the delivery brings (``weekly.track_round``); the launch brings no week of a round."""
    spec, view = _spec(ctx), _view(ctx)
    if spec.kind == "launch":
        return {"skipped": "launch"}
    conn = connect(ctx.cfg.paths.warehouse)
    try:
        done = weekly.track_round(conn, view, ctx.run_key, spec.first_day)
    finally:
        conn.close()
    return {"round_id": done.round_id, "rows": done.rows, "buyers": done.buyers, "days_observed": done.days_observed}


def build_base(ctx: RunContext) -> dict:
    """The base of the round that the delivery builds, from the history before its Monday (the checkpoint: ``recommend`` stores it with the lists, in one transaction)."""
    spec, view = _spec(ctx), _view(ctx)
    monday = _round_of(spec, view)
    if monday is None:
        return {"skipped": "close"}
    conn = connect(ctx.cfg.paths.warehouse)
    try:
        table = base.base_table(base.history_before(warehouse.read_lines(conn), monday), monday, view)
    finally:
        conn.close()
    return {"round_id": cal.round_id(monday), "base": len(table), "bulk": int(table["bulk"].sum())}


def fit_recipe(ctx: RunContext) -> dict:
    """The launch chooses the recipe in the validation rounds, seals it and registers the first round's models (``launch.run_launch``; the next ``fit_recipe`` of the same run adopts what was sealed, runbook R6);
    a weekly delivery checks the seal and takes the sealed recipe, which ``recommend`` refits on its history."""
    cfg, spec, view = ctx.cfg, _spec(ctx), _view(ctx)
    if spec.kind == "close":
        return {"skipped": "close"}
    if spec.kind != "launch":
        sealed = registry.require_launch_seal(Path(cfg.paths.seal), registry.config_fingerprint(view))
        return {"mode": "sealed", "recipe": sealed["recipe"]["name"]}
    conn = connect(cfg.paths.warehouse)
    try:
        done = launch.run_launch(conn, view, ctx.run_key, models_dir=Path(cfg.paths.models_dir), seal_path=Path(cfg.paths.seal))
    finally:
        conn.close()
    return {"mode": done.mode, "seal_state": done.seal_state, "round_id": done.round_id, "recipe": done.recipe.name, "sealed": done.sealed, "registered": done.registered, "seconds_choice": done.seconds.get("choice")}


def recommend(ctx: RunContext) -> dict:
    """The lists of every customer of the round and of its baselines, refitted with the sealed recipe (``weekly.emit_round``: one transaction, written once)."""
    cfg, spec, view = ctx.cfg, _spec(ctx), _view(ctx)
    monday = _round_of(spec, view)
    if monday is None:
        return {"skipped": "close"}
    conn = connect(cfg.paths.warehouse)
    try:
        done = weekly.emit_round(conn, view, ctx.run_key, monday, models_dir=Path(cfg.paths.models_dir), seal_path=Path(cfg.paths.seal))
    finally:
        conn.close()
    result = dataclasses.asdict(done)
    result["round_seconds"] = result.pop("seconds")      # the seconds of each step of the round; ``seconds`` of a task is its own total, which ``_run_spec`` writes
    return result


def deliver_offers(ctx: RunContext) -> dict:
    """Deliver the lists of the offer group of the round to the CRM and write its e-mail file and the operation of the round (RF15, RF16; the control group reaches neither)."""
    cfg, view = ctx.cfg, _view(ctx)
    issued = _task_result(ctx, "recommend")
    if "skipped" in issued:
        return {"skipped": issued["skipped"]}
    round_id = issued["round_id"]
    started = time.perf_counter()
    conn = connect(cfg.paths.warehouse)
    try:
        done = deliver_round(conn, make_client(cfg.crm, cfg.paths), round_id, run_key=ctx.run_key, batch_size=cfg.crm.batch_size)
        write_email_csv(conn, round_id, email_path(cfg.paths.private_dir, round_id), view)
        if conn.execute("SELECT 1 FROM round_ops WHERE round_id = ?", (round_id,)).fetchone() is None:
            weekly.write_round_ops(conn, round_id, ctx.run_key, delivered=done.delivered, seconds=round(issued["round_seconds"]["total"] + time.perf_counter() - started, 3))
    finally:
        conn.close()
    result = {k: v for k, v in dataclasses.asdict(done).items() if k != "round_id"}
    result["batches_skipped"] = result.pop("skipped")      # ``skipped`` of a task result says that the task did nothing; this is the batches that an earlier run delivered
    return {"round_id": round_id, **result}


def evaluate(ctx: RunContext) -> dict:
    """Only at the close: the test is evaluated once (``reporting.evaluate``) with what the CRM and the e-mail files say (C09)."""
    spec = _spec(ctx)
    if spec.kind != "close":
        return {"skipped": spec.kind}
    cfg, view = ctx.cfg, _view(ctx)
    conn = connect(cfg.paths.warehouse)
    try:
        evidence = evaluation.crm_evidence(conn, make_client(cfg.crm, cfg.paths), private_dir=Path(cfg.paths.private_dir), batch_size=cfg.crm.batch_size)
        try:
            done = reporting.evaluate(conn, view, _meta(ctx), seal_path=Path(cfg.paths.seal), crm=evidence)
        except EvaluationRefusedError as error:
            raise RunRefusedError(str(error)) from error
    finally:
        conn.close()
    return {"state": done["state"], "seal": done["seal"], "rows": done["rows"], "failed": [c.criterion_id for c in done["criteria"] if c.passed is False]}


def export(ctx: RunContext) -> dict:
    """The star model for Power BI and the six files of the site, as of the instant of the run's delivery."""
    cfg, view, run = ctx.cfg, _view(ctx), _meta(ctx)
    conn = connect(cfg.paths.warehouse)
    try:
        parquet = export_star_schema(conn, Path(cfg.paths.outputs_dir), Path(cfg.paths.private_dir), MODEL, run, view, seal_path=Path(cfg.paths.seal))
        site = export_site(conn, Path(cfg.paths.site_dir), run, view, seal_path=Path(cfg.paths.seal), private_dir=Path(cfg.paths.private_dir), max_total_bytes=cfg.site.max_total_bytes,
                           source_counts=source_counts(cfg))
    finally:
        conn.close()
    return {"parquet": len(parquet), "site": len(site)}


def render_dashboard(ctx: RunContext) -> dict:
    """The HTML design of the report, from the specification and the Parquet files just exported."""
    path = render_design(MODEL, Path(ctx.cfg.paths.outputs_dir), Path(ctx.cfg.paths.dashboard_html), _meta(ctx))
    return {"html": path.name, "bytes": path.stat().st_size}


# --- the close ---------------------------------------------------------------------------------------------------------------


def _run_peaks(ctx: RunContext) -> tuple[float | None, str | None]:
    tasks = _read_state(ctx.state_path).get("tasks", {}).values()
    now = _peak()
    working = [p for p in [*(t.get("peak_working_set_mb") for t in tasks), now.working_set_mb if now else None] if p is not None]
    return (max(working) if working else None, now.counter if now else None)


def _close_sqlite(ctx: RunContext) -> None:
    """Close the run's row as ``ok``; the row is ``load``'s, so a run without one is an error and never gets a row here."""
    working, counter = _run_peaks(ctx)
    conn = connect(ctx.cfg.paths.warehouse)
    try:
        apply_schema(conn)
        if conn.execute("SELECT 1 FROM pipeline_runs WHERE run_key = ?", (ctx.run_key,)).fetchone() is None:
            raise RunStateError(f"la corrida {ctx.run_key} no tiene su fila en pipeline_runs: no cargó su entrega, así que no se cierra (python -m personaloffers run --run-key {ctx.run_key} --from validate)")
        record_run(conn, {"run_key": ctx.run_key, "status": "ok", "finished_at": _now_text(), "message": "ok", "peak_working_set_mb": None if working is None else round(working, 1), "memory_counter": counter})
    finally:
        conn.close()


def _close_run_table(ctx: RunContext) -> None:
    conn = connect(ctx.cfg.paths.warehouse)
    try:
        export_run_table(conn, Path(ctx.cfg.paths.outputs_dir), MODEL, _meta(ctx), _view(ctx))
    finally:
        conn.close()


def _close_summary(ctx: RunContext) -> None:
    cfg = ctx.cfg
    conn = connect(cfg.paths.warehouse)
    try:
        export_summary(conn, Path(cfg.paths.site_dir), _meta(ctx), _view(ctx), seal_path=Path(cfg.paths.seal), max_total_bytes=cfg.site.max_total_bytes)
    finally:
        conn.close()


def _close_html(ctx: RunContext) -> None:
    render_dashboard(ctx)


_CLOSERS = {"sqlite": _close_sqlite, "run_table": _close_run_table, "summary": _close_summary, "html": _close_html}


def report(ctx: RunContext) -> dict:
    """Write the evaluation summary and this run's validation report as the latest, and close the run in ``CLOSING_STEPS`` order (plan section 3)."""
    cfg, view = ctx.cfg, _view(ctx)
    conn = connect(cfg.paths.warehouse)
    try:
        summary = reporting.build_summary(conn, view, seal_path=Path(cfg.paths.seal))
    finally:
        conn.close()
    reporting.write_summary(summary, Path(cfg.paths.reports_dir))
    validation = _read_report(_report_path(cfg, ctx.run_key))
    write_atomic(_validation_dir(cfg) / "latest.json", _report_text(validation))
    write_atomic(_validation_dir(cfg) / "latest.md", validation.to_markdown())
    for step in CLOSING_STEPS:
        _CLOSERS[step](ctx)
    return {"summary": "evaluation_summary.json", "evaluation_source": summary["source"], "run_status": "ok"}


def _refresh_exports(ctx: RunContext, *, summary: bool, html: bool, when: str) -> None:
    """Rewrite what was exported before so it says what SQLite says now: the run table, this run's summary and the HTML; nothing is created. Each write is tried on its own and logged if it fails (the caller's
    outcome stands)."""
    cfg = ctx.cfg
    try:
        _meta(ctx), _view(ctx)
    except (RunStateError, KeyError, TypeError, ValueError, StopIteration) as error:
        logger.warning("could not read the metadata of run %s %s, so no exported file was rewritten: %s", ctx.run_key, when, error)
        return
    steps = [("run table", _close_run_table)]
    if summary and (Path(cfg.paths.site_dir) / "summary.json").exists():
        steps.append(("summary", _close_summary))
    if html and Path(cfg.paths.dashboard_html).exists():
        steps.append(("html", _close_html))
    for name, step in steps:
        try:
            step(ctx)
        except Exception as error:
            logger.warning("could not rewrite the %s %s (run %s): %s", name, when, ctx.run_key, error, exc_info=error)


# --- running tasks -----------------------------------------------------------------------------------------------------------------


TASKS: tuple[TaskSpec, ...] = (
    TaskSpec("fetch_source", fetch_source, 0, 0, 20),
    TaskSpec("deliver", deliver, 0, 0, 30, short_circuit=True),
    TaskSpec("validate", validate_task, 0, 0, 10),
    TaskSpec("load", load, 1, 5, 20),
    TaskSpec("track", track, 1, 5, 10),
    TaskSpec("build_base", build_base, 1, 5, 10),
    TaskSpec("fit_recipe", fit_recipe, 1, 5, 60),
    TaskSpec("recommend", recommend, 1, 5, 30),
    TaskSpec("deliver_offers", deliver_offers, 1, 5, 30),
    TaskSpec("evaluate", evaluate, 1, 5, 30),
    TaskSpec("export", export, 1, 5, 10),
    TaskSpec("render_dashboard", render_dashboard, 1, 5, 10),
    TaskSpec("report", report, 1, 5, 5),
)
TASK_IDS = tuple(t.task_id for t in TASKS)
LATEST_ONLY = TASK_IDS[TASK_IDS.index("track"):TASK_IDS.index("evaluate")]      # the tasks that follow up, issue or deliver: they work on the latest delivery that was loaded


def _task_spec(task_id: str) -> TaskSpec:
    for spec in TASKS:
        if spec.task_id == task_id:
            return spec
    raise UsageError(f"tarea desconocida {task_id!r}; las tareas son {', '.join(TASK_IDS)}")


def _refuse_a_closed_run(spec: TaskSpec, ctx: RunContext) -> None:
    status = _read_state(ctx.state_path).get("status")
    if status in CLOSED_STATUSES:
        raise RunRefusedError(f"la corrida {ctx.run_key} está cerrada (estado {status}): no se vuelve a abrir para correr {spec.task_id}; otra entrega es otra corrida (python -m personaloffers run)")


def _refuse_a_second_delivery(spec: TaskSpec, ctx: RunContext) -> None:
    held = _held_delivery(ctx)
    if spec.task_id != "deliver" or not held.get("delivered"):
        return
    pending = dv.next_to_load(dv.delivery_plan(_view(ctx)), _loaded(ctx.cfg))
    if pending is None or pending.delivery_id != held["delivery_id"]:
        raise RunRefusedError(f"la corrida {ctx.run_key} ya tiene la entrega {held['delivery_id']} y la siguiente por cargar es {'ninguna' if pending is None else pending.delivery_id}: "
                              "una corrida no cambia de entrega (python -m personaloffers run)")


def _refuse_a_weekly_without_the_seal(spec: TaskSpec, ctx: RunContext) -> None:
    """RNF07e: no weekly delivery or close is published before the seal of the launch exists for this configuration, so the test never starts unsealed."""
    if spec.task_id != "deliver":
        return
    view = _view(ctx)
    pending = dv.next_to_load(dv.delivery_plan(view), _loaded(ctx.cfg))
    if pending is None or pending.kind == "launch":
        return
    try:
        registry.require_launch_seal(Path(ctx.cfg.paths.seal), registry.config_fingerprint(view))
    except SealError as error:
        raise RunRefusedError(f"la entrega {pending.delivery_id} es {pending.kind} y no hay un sello del lanzamiento de esta configuración: {error}. deliver no corre; el lanzamiento se sella en fit_recipe. No se escribió nada.") from error


def _refuse_a_delivery_this_run_did_not_load(spec: TaskSpec, ctx: RunContext) -> None:
    if TASK_IDS.index(spec.task_id) < TASK_IDS.index("load"):
        return
    held = _held_delivery(ctx)
    if not held.get("delivered"):
        return
    conn = _read_only(ctx.cfg)
    try:
        owner = _loaded_by(conn, held["delivery_id"])
    finally:
        conn.close()
    if owner == ctx.run_key or (owner is None and spec.task_id == "load"):
        return
    if owner is None:
        raise RunRefusedError(f"la corrida {ctx.run_key} tiene la entrega {held['delivery_id']} pero no la cargó: {spec.task_id} trabaja sobre la entrega que cargó su corrida "
                              f"(python -m personaloffers run --run-key {ctx.run_key} --from validate)")
    raise RunRefusedError(f"la entrega {held['delivery_id']} la cargó la corrida {owner}: {spec.task_id} no corre en la corrida {ctx.run_key} (python -m personaloffers run --run-key {owner} --from <tarea>)")


def _refuse_a_load_its_validation_did_not_pass(spec: TaskSpec, ctx: RunContext) -> None:
    if spec.task_id != "load" or not _held_delivery(ctx).get("delivered"):
        return
    path = _report_path(ctx.cfg, ctx.run_key)
    if not path.is_file():
        raise RunRefusedError(f"la corrida {ctx.run_key} no validó su entrega: load carga solo una entrega que la validación de su corrida aprobó (python -m personaloffers run --run-key {ctx.run_key} --from validate)")
    failed = [r["rule_id"] for r in json.loads(path.read_text(encoding="utf-8"))["results"] if not r["passed"] and r["severity"] == "bloqueante"]
    if failed:
        raise RunRefusedError(f"la validación de la corrida {ctx.run_key} rechazó su entrega ({', '.join(failed)}): load no carga una entrega rechazada (docs/runbook.md, R3)")


def _refuse_an_older_delivery(spec: TaskSpec, ctx: RunContext) -> None:
    held = _held_delivery(ctx)
    if spec.task_id not in LATEST_ONLY or not held.get("delivered"):
        return
    conn = _read_only(ctx.cfg)
    try:
        latest = _latest_loaded(conn)
    finally:
        conn.close()
    if latest is not None and latest[0] != held["delivery_id"]:
        raise RunRefusedError(f"la corrida {ctx.run_key} es de la entrega {held['delivery_id']} y la última cargada es la {latest[0]} (al {latest[2].isoformat()}): {spec.task_id} trabaja sobre la última entrega y no corre en esta corrida")


def _refuse_a_test_evaluation_under_another_configuration(spec: TaskSpec, ctx: RunContext) -> None:
    """While the seal has its launch part and no test part, every task of the run of the close is refused when its configuration is not the sealed one, before anything is written: the test is read once, with the
    sealed configuration (``registry.EvaluationRefusedError`` turned into a refused run). After the test part exists, another configuration is post-seal, as before."""
    cfg = ctx.cfg
    try:
        seal = registry.read_seal(Path(cfg.paths.seal))
    except SealError:
        return
    if seal is None or seal.get("test") is not None:
        return
    held = _held_delivery(ctx)
    sealed_config = seal["launch"]["config"]
    observed = (_read_state(ctx.state_path).get("tasks", {}).get("fetch_source") or {}).get("source_sha256") or {
        "zip": sealed_config["zip_sha256_seen"], "member": sealed_config["member_sha256_seen"], "lines": sealed_config["lines_sha256_seen"]}
    view = registry.sealed_view(cfg, observed)
    if held:
        if not held.get("delivered") or held["kind"] != "close":
            return
        delivery_id = held["delivery_id"]
    else:
        pending = dv.next_to_load(dv.delivery_plan(view), _loaded(cfg))
        if pending is None or pending.kind != "close":
            return
        delivery_id = pending.delivery_id
    try:
        registry.check_test_evaluation(Path(cfg.paths.seal), view)
    except EvaluationRefusedError as error:
        raise RunRefusedError(f"la corrida {ctx.run_key} evaluaría la prueba (entrega {delivery_id}) con una configuración que no es la sellada: {error} {spec.task_id} no corre.") from error


def _refuse_a_task_of_a_run_without_a_delivery(spec: TaskSpec, ctx: RunContext) -> None:
    """A task from ``load`` on of a run that holds no delivery (a new run, as ``task <tarea>`` without ``--run-key`` is, or one whose ``deliver`` did not finish) has no delivery of its own to work on: it is refused
    before ``_open`` creates the state file, so nothing is written. It is the last refusal, so every refusal before it keeps its message."""
    if TASK_IDS.index(spec.task_id) < TASK_IDS.index("load") or _held_delivery(ctx).get("delivered"):
        return
    raise RunRefusedError(f"la corrida {ctx.run_key} no tiene una entrega: {spec.task_id} trabaja sobre la entrega que cargó su corrida; una corrida nueva empieza por fetch_source "
                          "(python -m personaloffers run) y una que ya empezó se continúa con su clave (python -m personaloffers run --run-key <clave> --from <tarea>). No se escribió nada.")


def _reopen(ctx: RunContext) -> None:
    state = _read_state(ctx.state_path)
    if state.get("status") != "failed":
        return
    state["status"] = "running"
    _write_state(ctx.state_path, state)
    if _has_record(ctx):
        _record(ctx, status="running", finished_at=None, message="")


def _record_failure(ctx: RunContext, spec: TaskSpec, error: BaseException) -> None:
    """The state file, the run's row and the exported files say the task failed; each write on its own, logged if it fails, so the task's error is what the caller sees (AC29)."""
    message = f"{spec.task_id}: {type(error).__name__}: {error}"
    try:
        state = _read_state(ctx.state_path)
        state["status"] = "failed"
        state.setdefault("tasks", {})[spec.task_id] = {"status": "failed", "error": message[:MESSAGE_LIMIT], "traceback": "".join(traceback.format_exception(error))}
        _write_state(ctx.state_path, state)
    except Exception as failure:
        logger.warning("could not record the failure of %s in the state file of run %s", spec.task_id, ctx.run_key, exc_info=failure)
    try:
        if _has_record(ctx):
            _record(ctx, status="failed", finished_at=_now_text(), message=message)
    except Exception as failure:
        logger.warning("could not record the failure of %s in the warehouse for run %s", spec.task_id, ctx.run_key, exc_info=failure)
    try:
        if _has_record(ctx):
            _refresh_exports(ctx, summary=True, html=True, when=f"after {spec.task_id} failed")
    except Exception as failure:
        logger.warning("could not rewrite the exported files of run %s after %s failed", ctx.run_key, spec.task_id, exc_info=failure)


def _run_spec(spec: TaskSpec, ctx: RunContext) -> dict:
    """The refusals (nothing written), the task, and its result saved with its seconds and its memory peaks; a failure is recorded and raised."""
    _refuse_a_closed_run(spec, ctx)
    _refuse_a_second_delivery(spec, ctx)
    _refuse_a_delivery_this_run_did_not_load(spec, ctx)
    _refuse_a_load_its_validation_did_not_pass(spec, ctx)
    _refuse_an_older_delivery(spec, ctx)
    _refuse_a_test_evaluation_under_another_configuration(spec, ctx)
    _refuse_a_weekly_without_the_seal(spec, ctx)
    _refuse_a_task_of_a_run_without_a_delivery(spec, ctx)
    started = time.perf_counter()
    _open(ctx)
    _reopen(ctx)
    try:
        result = spec.func(ctx)
    except (ValidationError, RunRefusedError):      # the first marked the run rejected itself; the second refused before writing: neither is a failure of the task
        raise
    except BaseException as error:
        _record_failure(ctx, spec, error)
        logger.error("task %s of run %s failed after %.1f s: %s", spec.task_id, ctx.run_key, time.perf_counter() - started, error)
        raise
    peaks = _peak()
    result = {**result, "seconds": round(time.perf_counter() - started, 2), "peak_working_set_mb": None if peaks is None else round(peaks.working_set_mb, 1),
              "peak_commit_mb": None if peaks is None or peaks.commit_mb is None else round(peaks.commit_mb, 1), "memory_counter": None if peaks is None else peaks.counter}
    try:
        _save_task(ctx, spec.task_id, result, status=result.get("run_status"))
    except BaseException as error:
        if result.get("run_status") in CLOSED_STATUSES:
            logger.error("task %s closed run %s as %s but its result could not be saved: run it again", spec.task_id, ctx.run_key, result["run_status"], exc_info=error)
            raise
        _record_failure(ctx, spec, error)
        raise
    logger.info("task %s of run %s: %.1f s", spec.task_id, ctx.run_key, result["seconds"])
    return result


def run_task(task_id: str, run_id: str | None = None, cfg: PipelineConfig | None = None, *, now: datetime | None = None) -> dict:
    """Run one task of the run `run_id` (a new run if None) holding the writer lock: what the Airflow DAG calls."""
    spec = _task_spec(task_id)
    cfg = cfg or load_config()
    when = (now or datetime.now(UTC)).astimezone(UTC)
    with sole_writer(cfg.paths.interim_dir, f"task {task_id}", make_run_key(run_id if run_id is not None else when)):
        return _run_spec(spec, _context(cfg, run_id, when))


def _select(only: list[str] | None, start: str | None) -> list[str]:
    if only is not None and not only:
        raise UsageError("`only` está vacío: indique al menos una tarea")
    if only and start is not None:
        raise UsageError("`only` y `start` no se combinan")
    ids = list(TASK_IDS)
    if start is not None:
        _task_spec(start)
        ids = ids[ids.index(start):]
    if only:
        for task_id in only:
            _task_spec(task_id)
        ids = [i for i in ids if i in only]
    return ids


def run_all(cfg: PipelineConfig, only: list[str] | None = None, start: str | None = None, run_key: str | None = None, *, now: datetime | None = None) -> list[dict]:
    """Run the tasks in order (all, the listed ones or from `start` on) holding the writer lock from before the first to after the last; a run with no delivery stops after ``deliver``."""
    ids = _select(only, start)
    refuse_a_state_that_does_not_agree(cfg)
    when = (now or datetime.now(UTC)).astimezone(UTC)
    outcome = []
    with sole_writer(cfg.paths.interim_dir, "run", make_run_key(run_key if run_key is not None else when)):
        ctx = _context(cfg, run_key, when)
        for task_id in ids:
            spec = _task_spec(task_id)
            result = _run_spec(spec, ctx)
            outcome.append({"task": task_id, "result": result})
            if spec.short_circuit and not result.get("delivered", True):
                break
    return outcome


def replay(cfg: PipelineConfig, until: str | None = None) -> list[list[dict]]:
    """Run the pending deliveries one run after another up to `until`; with nothing pending nothing runs and the lock is not taken."""
    plan = _plan_of(cfg)
    ids = [s.delivery_id for s in plan]
    if until is not None and until not in ids:
        raise UsageError(f"--until {until}: no es una entrega del plan ({', '.join(ids)})")
    last = len(plan) - 1 if until is None else ids.index(until)
    runs: list[list[dict]] = []
    refuse_a_state_that_does_not_agree(cfg)
    pending = dv.next_to_load(plan, _loaded(cfg))
    if pending is None and until is not None:      # every delivery is loaded, `until` too: the same refusal as an `until` before the next pending one
        raise UsageError(f"--until {until}: no hay entregas pendientes (las {len(plan)} del plan ya están cargadas); no hay nada que correr hasta ella. No se escribió nada.")
    if pending is None:
        return runs
    if plan.index(pending) > last:      # nothing up to `until` is pending: the option would be ignored in silence, so it is refused
        raise UsageError(f"--until {until}: es anterior a la siguiente pendiente, {pending.delivery_id}; no hay nada que correr hasta ella. No se escribió nada.")
    with sole_writer(cfg.paths.interim_dir, "replay", None):
        while (pending := dv.next_to_load(plan, _loaded(cfg))) is not None and plan.index(pending) <= last:
            runs.append(run_all(cfg))
            if dv.next_to_load(plan, _loaded(cfg)) == pending:
                raise RunStateError(f"la corrida de {pending.delivery_id} terminó sin cargar la entrega: el replay se detiene")
    return runs
