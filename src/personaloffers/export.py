"""The star model for Power BI: the marts in SQLite and one Parquet file per table (RF20, AC26; risk item 3: a contract that others consume; decisions D30, D37; plan section 19). Adapted from project 07's ``export.py``.

``build_powerbi_marts`` loads the reference tables that come from the code, the warehouse and the seal (``ref_*``: the labels in Spanish, the calendar, the rounds with the buyers outside their base, the
products with their popularity band, what each customer bought in each week, the recipes of the validation, the pair rules and the criteria), rebuilds the tables of ``sql/marts/powerbi`` (``star_<name>``) and runs the
controls of ``sql/checks/model``, all in one transaction: a control with rows undoes it (``CheckFailedError``) and the marts keep what they had. The evaluation's tables (``eval_*``) are the only source of the
test's figures and their texts: a verdict is told here exactly as ``reporting`` tells it.

``export_star_schema`` writes every table of the semantic model with its Arrow schema and the run, the instant, the configuration and the attribution as file metadata: the published tables to ``outputs/powerbi/`` and the
one with customer numbers (``private``) to ``outputs/private/``, which git ignores (D30, D45). A file over ``MAX_PARQUET_BYTES`` is an error before anything is written; each file is replaced atomically. The folder's
``manifest.json`` is removed before its first file is written and written again after its last one, with the run and each file's name, bytes and SHA-256 (RNF06): ``verify_star_schema`` checks a folder against it, so a set
left half written by a failure has no manifest and is refused.

**Small cells (D30).** A cell that counts customers is empty (``suppressed``) when it has fewer than ``[privacy] min_cell_customers``, and where a total is published a group never hides just one cell, because the total would
give it back by subtraction (the secondary rule of project 04, in the marts' SQL and checked by ``K03`` and ``K04``).
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import logging
import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from personaloffers import base, texts, warehouse
from personaloffers import calendar as cal
from personaloffers.dashboard.semantic_model import SemanticModel, Table, arrow_schema, validate_model
from personaloffers.files import write_atomic
from personaloffers.recommend import rules
from personaloffers.registry import config_fingerprint, read_seal
from personaloffers.reporting import RunMeta
from personaloffers.warehouse import SQL_DIR, _fail_on, apply_schema, rebuild_marts, run_checks, run_sql_file

logger = logging.getLogger(__name__)

MAX_PARQUET_BYTES = 25 * 1024 * 1024        # a versioned file stays under GitHub's limits (AC37)
STAR_PREFIX = "star_"
METADATA_KEYS = ("personaloffers.run_key", "personaloffers.as_of", "personaloffers.config_sha256", "personaloffers.attribution")
STAR_MANIFEST = "manifest.json"
RUN_TABLE = "dim_pipeline_run"
RUN_TABLE_MART = "mart_11_dim_pipeline_run.sql"
MANIFEST_VERSION = 1
STAMP = "%Y-%m-%d %H:%M:%S"
RULES_MIN_SUPPORT = 20          # the invoices that a pair needs in the launch history to be a rule shown (plan section 19)
RULES_TOP = 200                 # and how many are shown, the ones with the highest rule_lift


def metadata(run: RunMeta, config_sha256: str) -> dict[str, str]:
    """What every Parquet file says about the run that wrote it (RNF08, RNF10): the run, its instant, the sealed configuration and the attribution of the archive."""
    return dict(zip(METADATA_KEYS, (run.run_key, run.as_of.strftime(STAMP), config_sha256, texts.ATTRIBUTION), strict=True))


def _replace(conn: sqlite3.Connection, name: str, columns: str, rows: list[tuple]) -> None:
    conn.execute(f"DROP TABLE IF EXISTS {name}")
    conn.execute(f"CREATE TABLE {name} ({columns})")
    if rows:
        conn.executemany(f"INSERT INTO {name} VALUES ({', '.join('?' for _ in rows[0])})", rows)


def _calendar(view: Any) -> list[tuple[int, str, str, str]]:
    """The days of the project's calendar: ``(date_key, date, week_monday, period)`` from the first day of the archive to the last of the close."""
    c, days, day = view.calendar, [], view.calendar.history_start
    test_end = c.test_last_round + timedelta(days=6)
    while day <= c.close_last_day:
        period = "close" if day >= c.close_first_day else "test" if c.test_first_round <= day <= test_end else "validation" if c.validation_first_round <= day <= c.launch_last_day else "history"
        days.append((int(day.strftime("%Y%m%d")), day.isoformat(), (day - timedelta(days=day.weekday())).isoformat(), period))
        day += timedelta(days=1)
    return days


def _bands(products: list[tuple[str, int]]) -> dict[str, int]:
    """The popularity band of each product: the decile (1 the least asked, 10 the most) of its invoices in the launch history among the products that have any; 0 for the rest."""
    ranked = sorted(((n, code) for code, n in products if n > 0))
    bands = {code: 0 for code, n in products}
    for place, (_n, code) in enumerate(ranked):
        bands[code] = 1 + (10 * place) // len(ranked)
    return bands


def _week_purchases(conn: sqlite3.Connection, view: Any, lines: pd.DataFrame, rounds: list[tuple[str, str]]) -> tuple[list[tuple], dict[str, int], set[str]]:
    """What the customers of each round's base bought in its week (``ref_week_purchase`` rows), the customers that bought without being in the base and the rounds that have a follow-up."""
    followed = {r[0] for r in conn.execute("SELECT DISTINCT round_id FROM round_outcomes")}
    purchases, outside = [], {}
    for round_id, _period in rounds:
        monday = cal.monday_of(round_id)
        members = {r[0] for r in conn.execute("SELECT customer_id FROM contact_base WHERE round_id = ?", (round_id,))}
        start, end = cal.window(monday, view)
        week = lines[(lines["role"] == "purchase") & lines["customer_id"].notna() & (lines["invoice_date"] >= start) & (lines["invoice_date"] < end)]
        outside[round_id] = int(week.loc[~week["customer_id"].isin(members), "customer_id"].nunique()) if round_id in followed else 0
        mine = week[week["customer_id"].isin(members)][["customer_id", "stock_code"]].drop_duplicates()
        purchases += [(round_id, int(c), str(s)) for c, s in zip(mine["customer_id"], mine["stock_code"], strict=True)]
    return purchases, outside, followed


def _rules(lines: pd.DataFrame, view: Any, descriptions: dict[str, str | None]) -> list[tuple]:
    """The ``RULES_TOP`` pair rules of the launch history with the highest rule_lift among those with ``RULES_MIN_SUPPORT`` invoices (ties: more invoices, then the codes)."""
    monday = view.calendar.test_first_round
    history = base.history_before(lines, monday)
    codes = np.array(sorted(history["stock_code"].dropna().astype(str).unique()))
    if not len(codes):
        return []
    found = rules.select(rules.pair_counts(history, monday, codes), RULES_MIN_SUPPORT, view.grid.rules_min_lift)
    order = np.lexsort((found.consequent, found.antecedent, -found.support, -found.rule_lift))[:RULES_TOP]
    return [(str(codes[found.antecedent[i]]), str(codes[found.consequent[i]]), descriptions.get(str(codes[found.antecedent[i]])) or "", descriptions.get(str(codes[found.consequent[i]])) or "",
             int(found.support[i]), float(found.confidence[i]), float(found.rule_lift[i])) for i in order]


def _load_references(conn: sqlite3.Connection, view: Any, seal_path: Path) -> None:
    """The ``ref_*`` tables the marts read."""
    lines = warehouse.read_lines(conn)
    rounds = [(r[0], r[1]) for r in conn.execute("SELECT round_id, period FROM rounds ORDER BY round_id")]
    purchases, outside, followed = _week_purchases(conn, view, lines, rounds)
    products = conn.execute("SELECT stock_code, description_es, first_seen, launch_invoices FROM products ORDER BY stock_code").fetchall()
    bands = _bands([(p[0], p[3]) for p in products])
    _replace(conn, "ref_date", "date_key INTEGER PRIMARY KEY, date TEXT, week_monday TEXT, period TEXT", _calendar(view))
    _replace(conn, "ref_round", "round_key TEXT PRIMARY KEY, monday TEXT, period TEXT, days_observed INTEGER, buyers_outside_base INTEGER, followed INTEGER",
             [(rid, cal.monday_of(rid).isoformat(), period, cal.days_observed(cal.monday_of(rid), view), outside[rid], int(rid in followed)) for rid, period in rounds])
    _replace(conn, "ref_product", "product_key TEXT PRIMARY KEY, description_es TEXT, first_seen TEXT, popularity_band INTEGER", [(code, text or "", first, bands[code]) for code, text, first, _n in products])
    _replace(conn, "ref_week_purchase", "round_id TEXT, customer_id INTEGER, stock_code TEXT, PRIMARY KEY (round_id, customer_id, stock_code)", purchases)
    _replace(conn, "ref_method", "method_key TEXT PRIMARY KEY, label_es TEXT, role_es TEXT", [(key, label, role) for key, (label, role) in texts.METHOD_LABELS.items()])
    _replace(conn, "ref_variant", "variant_key TEXT PRIMARY KEY, label_es TEXT", list(texts.VARIANT_LABELS.items()))
    _replace(conn, "ref_source", "source_key TEXT PRIMARY KEY, label_es TEXT", list(texts.SOURCE_LABELS.items()))
    _replace(conn, "ref_group", "group_key TEXT PRIMARY KEY, label_es TEXT", list(texts.GROUP_LABELS.items()))
    _replace(conn, "ref_segment", "segment_key TEXT PRIMARY KEY, label_es TEXT", list(texts.SEGMENT_LABELS.items()))
    _replace(conn, "ref_covariate", "covariate_key TEXT PRIMARY KEY, label_es TEXT, unit_es TEXT", [(key, label, unit) for key, (label, unit) in texts.COVARIATE_LABELS.items()])
    thresholds = texts.thresholds_from(dataclasses.asdict(view.criteria))
    _replace(conn, "ref_criterion", "criterion_key TEXT PRIMARY KEY, name_es TEXT, threshold_es TEXT", [(cid, t.name_es, thresholds[cid]) for cid, t in texts.CRITERIA.items()])
    document = read_seal(seal_path)
    candidates = [] if document is None else document["launch"]["validation"]["candidates"]
    _replace(conn, "ref_choice", "candidate TEXT PRIMARY KEY, base_model TEXT, params TEXT, trend_weight REAL, val_hit_new REAL, val_coverage REAL, kept INTEGER, chosen INTEGER, fit_rounds INTEGER",
             [(c["name"], c["model"], json.dumps({"size": c["size"], "regularization": c["regularization"]}, sort_keys=True), float(c["weight"]), c["hit_new"], c["coverage"], int(c["kept"]), int(c["chosen"]), len(c["fit_rounds"]))
              for c in candidates])
    _replace(conn, "ref_rule", "antecedent_key TEXT, consequent_key TEXT, antecedent_es TEXT, consequent_es TEXT, support INTEGER, confidence REAL, rule_lift REAL, PRIMARY KEY (antecedent_key, consequent_key)",
             _rules(lines, view, {p[0]: p[1] for p in products}))


def build_powerbi_marts(conn: sqlite3.Connection, run: RunMeta, view: Any, *, seal_path: Path) -> None:
    """Rebuild the reference tables and the star model and run its controls in one transaction; a control with rows undoes it all (``CheckFailedError``) and the marts keep what they had."""
    apply_schema(conn)
    params = {"min_cell_customers": view.privacy.min_cell_customers}
    conn.execute("BEGIN IMMEDIATE")
    try:
        _load_references(conn, view, seal_path)
        rebuild_marts(conn, "powerbi", params)
        _fail_on(run_checks(conn, "model", params), f"star model of run {run.run_key}", "La exportación del modelo estrella")
        conn.execute("COMMIT")
    except BaseException:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        logger.warning("star model of run %s rolled back: the marts keep what they had", run.run_key)
        raise


_CONVERT = {
    "int8": int, "int16": int, "int32": int, "int64": int, "float64": float, "bool": bool, "string": str, "date": lambda v: date.fromisoformat(str(v)[:10]),
    "datetime": lambda v: datetime.fromisoformat(str(v)),
}


def _arrow_table(columns: list[tuple], table: Table) -> pa.Table:
    """The values of the columns (one tuple of values per column) as an Arrow table with the model's schema; a key with a missing value is an error."""
    arrays = []
    for column, values in zip(table.columns, columns, strict=True):
        if column.name in table.key and any(v is None for v in values):
            raise ValueError(f"{table.name}[{column.name}] tiene valores vacíos: una clave no puede")
        convert = _CONVERT[column.dtype]
        arrays.append(pa.array([None if v is None else convert(v) for v in values], type=arrow_schema(table).field(column.name).type))
    return pa.Table.from_arrays(arrays, schema=arrow_schema(table))


def _serialize(conn: sqlite3.Connection, table: Table, meta: dict[str, str]) -> bytes:
    names, order = (", ".join(f'"{name}"' for name in names) for names in (table.column_names, table.key))
    rows = conn.execute(f"SELECT {names} FROM {STAR_PREFIX}{table.name} ORDER BY {order}").fetchall()
    arrow = _arrow_table(list(zip(*rows, strict=True)) if rows else [()] * len(table.columns), table)
    arrow = arrow.replace_schema_metadata({**(arrow.schema.metadata or {}), **{k.encode(): v.encode("utf-8") for k, v in meta.items()}})
    sink = pa.BufferOutputStream()
    pq.write_table(arrow, sink, compression="snappy")
    return sink.getvalue().to_pybytes()


def _manifest_text(meta: dict[str, str], files: list[dict]) -> str:
    document = {"version": MANIFEST_VERSION, **{key.removeprefix("personaloffers."): value for key, value in meta.items()}, "files": files}
    return json.dumps(document, ensure_ascii=False, sort_keys=True, indent=1) + "\n"


def verify_star_schema(folder: Path) -> list[str]:
    """What does not match in `folder` against its ``manifest.json`` (empty when everything does): a missing or unreadable manifest, a listed file that is missing or whose bytes or SHA-256 differ, and a Parquet file
    the manifest does not list."""
    folder = Path(folder)
    try:
        manifest = json.loads((folder / STAR_MANIFEST).read_text(encoding="utf-8"))
        listed = {entry["name"]: entry for entry in manifest["files"]}
    except (OSError, ValueError, KeyError, TypeError) as error:
        return [f"{STAR_MANIFEST}: no hay un manifiesto legible ({type(error).__name__}); el conjunto no se usa"]
    problems = []
    for name, entry in listed.items():
        path = folder / name
        if not path.is_file():
            problems.append(f"{name}: falta el archivo que lista el manifiesto")
            continue
        data = path.read_bytes()
        if len(data) != entry.get("bytes") or hashlib.sha256(data).hexdigest() != entry.get("sha256"):
            problems.append(f"{name}: los bytes no son los del manifiesto")
    problems += [f"{path.name}: el manifiesto no lo lista" for path in sorted(folder.glob("*.parquet")) if path.name not in listed]
    return problems


def export_star_schema(conn: sqlite3.Connection, out_dir: Path, private_dir: Path, model: SemanticModel, run: RunMeta, view: Any, *, seal_path: Path) -> list[Path]:
    """Rebuild the marts and write one Parquet file per table of `model`: the published ones to `out_dir`, with the manifest last, and the private one to `private_dir`. Returns the paths in the model's order. The model is
    checked first and every file is serialized and measured before any is written."""
    problems = validate_model(model)
    if problems:
        raise ValueError(f"el modelo semántico es incoherente: {problems[0]}")
    build_powerbi_marts(conn, run, view, seal_path=seal_path)
    meta = metadata(run, config_fingerprint(view))
    payloads = {}
    for table in model.tables:
        data = _serialize(conn, table, meta)
        if len(data) > MAX_PARQUET_BYTES:
            raise ValueError(f"{table.name}.parquet pesa {len(data)} bytes, más de {MAX_PARQUET_BYTES}: no se escribe nada")
        payloads[table.name] = data
    out_dir, private_dir = Path(out_dir), Path(private_dir)
    (out_dir / STAR_MANIFEST).unlink(missing_ok=True)         # a set being rewritten has no manifest until its last file is written
    paths = [write_atomic((private_dir if table.private else out_dir) / f"{table.name}.parquet", payloads[table.name]) for table in model.tables]
    files = [{"name": f"{t.name}.parquet", "bytes": len(payloads[t.name]), "sha256": hashlib.sha256(payloads[t.name]).hexdigest()} for t in model.public]
    write_atomic(out_dir / STAR_MANIFEST, _manifest_text(meta, files))
    logger.info("star model of run %s: %d files in %s and %d in the private folder", run.run_key, len(model.public), out_dir.name, len(model.private))
    return paths


def export_run_table(conn: sqlite3.Connection, out_dir: Path, model: SemanticModel, run: RunMeta, view: Any) -> Path | None:
    """Rewrite only ``dim_pipeline_run.parquet`` from ``pipeline_runs`` and its line of the folder's manifest: what closing a run, a failure or a run with no delivery changes (plan sections 3 and 22). Nothing is created
    that was not there: without an exported set that verifies against its manifest it logs a warning naming the run and the reason and returns None, and every file keeps its bytes (a set with a file of another export
    would otherwise look whole). The other files, and the manifest's own header, are not touched; the manifest is removed before the file is replaced and written again last, as in ``export_star_schema``."""
    out_dir = Path(out_dir)
    manifest_path = out_dir / STAR_MANIFEST
    problems = ["there is no manifest.json: nothing was exported here"] if not manifest_path.is_file() else verify_star_schema(out_dir)
    if problems:
        logger.warning("run table of run %s not rewritten: the exported set does not match its manifest, so every file is kept as it is: %s", run.run_key, "; ".join(problems))
        return None
    table = model.table(RUN_TABLE)
    conn.execute("BEGIN IMMEDIATE")
    try:
        run_sql_file(conn, SQL_DIR / "marts" / "powerbi" / RUN_TABLE_MART)
        data = _serialize(conn, table, metadata(run, config_fingerprint(view)))
        conn.execute("COMMIT")
    except BaseException:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for entry in manifest["files"]:
        if entry["name"] == f"{RUN_TABLE}.parquet":
            entry.update(bytes=len(data), sha256=hashlib.sha256(data).hexdigest())
    manifest_path.unlink(missing_ok=True)
    path = write_atomic(out_dir / f"{RUN_TABLE}.parquet", data)
    write_atomic(manifest_path, json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=1) + "\n")
    logger.info("run table rewritten: %s (%d bytes)", path.name, len(data))
    return path
