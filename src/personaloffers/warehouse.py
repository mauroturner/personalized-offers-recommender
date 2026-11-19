"""The SQLite warehouse: connection, SQL runner, schema, the load of a delivery and the controls (RF14, AC17 in part; plan section 5; decisions D24, D29); adapted from project 07.

Rules of the runner, the same as in projects 01 to 07:

- autocommit connection (``isolation_level=None``); transactions are explicit ``BEGIN IMMEDIATE``;
- ``journal_mode=DELETE`` (WAL does not behave on Docker Desktop mounts), ``synchronous=FULL``, ``foreign_keys=ON``;
- never ``executescript()``: it commits the open transaction first. SQL files are split into statements with ``sqlite3.complete_statement`` and run one by one with named parameters,
  so a failure can roll the whole load back; the schema is created inside the transaction too, so a first load that fails leaves no table behind;
- a failure never commits: the transaction is rolled back with ``ROLLBACK`` and the error that made it necessary is the one that reaches the caller.

A load is all or nothing: the delivery's row, the run's row (``running``: ``report`` closes it), the validation's rows, the lines of the delivery, the products seen for the first time and
the controls of ``sql/checks/load/`` are one transaction. It is refused, writing nothing, without a validation of this run that passed the four blocking rules and that is the one of the
file whose lines are given, and a delivery already loaded or a run already recorded leaves the warehouse byte for byte as it was. The tables of ``sql/schema/002_flow.sql`` (and the lines, the
products and the validation) are insert-only in the database itself: three triggers each. A delivery that was rejected or only published before is loaded over its row.
"""

from __future__ import annotations

import functools
import json
import logging
import re
import sqlite3
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Literal

import pandas as pd
import pyarrow as pa

from personaloffers import holdout
from personaloffers import workbook as wb
from personaloffers.deliveries import DeliverySpec
from personaloffers.lines import PRODUCT_ROLES
from personaloffers.validate import BLOCKING, ValidationReport

logger = logging.getLogger(__name__)

SQL_DIR = Path(__file__).resolve().parents[2] / "sql"
CHECK_GROUPS = ("load", "model")
MART_GROUPS = ("powerbi",)
SAMPLE_LIMIT = 5
BUSY_TIMEOUT_MS = 30_000       # an overlapping writer waits this long for the write lock before failing (runbook R8)
CACHE_KIB = 65_536             # the page cache of a connection (negative ``cache_size`` is in KiB), in memory only
BLOCKING_RULES = ("V10", "V11", "V12", "V13")
_HEX64 = re.compile(r"[0-9a-f]{64}")


@dataclass(frozen=True)
class CheckResult:
    check_id: str
    violations: int
    sample: list[tuple]


@dataclass(frozen=True)
class LoadResult:
    delivery_id: str
    run_key: str
    lines: int
    products: int
    checks: list[CheckResult]


class LoadRefusedError(RuntimeError):
    """The load was refused before anything was written: there is no validation of this run that passed (``load`` never runs without one), or the lines are not the validated file's."""


class DeliveryAlreadyLoadedError(RuntimeError):
    """The delivery is already in the warehouse: loading it again would duplicate its lines."""

    def __init__(self, delivery_id: str) -> None:
        super().__init__(f"La entrega {delivery_id} ya está cargada en el almacén; no se carga de nuevo")


class CheckFailedError(RuntimeError):
    """A control returned rows: the transaction was rolled back."""

    def __init__(self, checks: list[CheckResult], step: str = "La carga") -> None:
        self.checks, self.step = checks, step
        failing = [c for c in checks if c.violations]
        detail = "; ".join(f"{c.check_id}: {c.violations} filas, por ejemplo {c.sample[:2]}" for c in failing)
        super().__init__(f"{step} se deshizo; controles con filas que los violan: {detail}")


class SchemaDriftError(RuntimeError):
    """A table of the warehouse does not have the columns its SQL definition declares (runbook R11)."""

    def __init__(self, table: str, source: str, missing: tuple[str, ...], unexpected: tuple[str, ...], retyped: tuple[str, ...]) -> None:
        self.table, self.missing, self.unexpected, self.retyped = table, missing, unexpected, retyped
        parts = [text for text, columns in ((f"faltan las columnas {list(missing)}", missing), (f"sobran las columnas {list(unexpected)}", unexpected),
                                            (f"tienen otro tipo las columnas {list(retyped)}", retyped)) if columns]
        super().__init__(f"La tabla {table} no coincide con su definición en sql/schema/{source}: {'; '.join(parts)}. "
                         "El almacén lo creó una versión anterior: se reconstruye desde cero (docs/runbook.md, R11).")


# --- connection and SQL files -------------------------------------------------------------------------------------------


def connect(path: Path) -> sqlite3.Connection:
    """Open (creating the folder and the file) the warehouse in autocommit mode with the project's pragmas."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, isolation_level=None)
    conn.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}")
    conn.execute("PRAGMA journal_mode=DELETE")
    conn.execute("PRAGMA synchronous=FULL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute(f"PRAGMA cache_size=-{CACHE_KIB}")   # memory only: nothing in the file or in a result depends on it
    return conn


def _has_sql(text: str) -> bool:
    """True if `text` has anything besides whitespace, semicolons and comments."""
    i, n = 0, len(text)
    while i < n:
        if text.startswith("--", i):
            end = text.find("\n", i)
            i = n if end == -1 else end + 1
        elif text.startswith("/*", i):
            end = text.find("*/", i + 2)
            i = n if end == -1 else end + 2
        elif text[i].isspace() or text[i] == ";":
            i += 1
        else:
            return True
    return False


def split_statements(sql_text: str) -> list[str]:
    """Split a SQL file into statements, keeping semicolons inside strings, comments and triggers (a new list: the split is cached by text)."""
    return list(_split_statements(sql_text))


@functools.lru_cache(maxsize=256)
def _split_statements(sql_text: str) -> tuple[str, ...]:
    statements: list[str] = []
    start = 0
    for position, character in enumerate(sql_text):
        if character == ";" and sqlite3.complete_statement(sql_text[start : position + 1]):
            chunk = sql_text[start : position + 1]
            if _has_sql(chunk):
                statements.append(chunk.strip())
            start = position + 1
    if _has_sql(sql_text[start:]):   # a last statement without its semicolon
        statements.append(sql_text[start:].strip())
    return tuple(statements)


def run_sql_file(conn: sqlite3.Connection, path: Path, params: Mapping[str, object] | None = None) -> None:
    """Execute the statements of a SQL file one by one, binding the named parameters each uses."""
    for statement in split_statements(Path(path).read_text(encoding="utf-8")):
        conn.execute(statement, dict(params or {}))


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (name,)).fetchone() is not None


def _declared_tables(path: Path) -> dict[str, dict[str, str]]:
    """``{table: {column: declared type}}`` of a schema file, read by creating its tables in memory (cached by the file's size and time)."""
    stat = Path(path).stat()
    return _declared_tables_cached(str(path), stat.st_size, stat.st_mtime_ns)


@functools.lru_cache(maxsize=16)
def _declared_tables_cached(path: str, size: int, mtime_ns: int) -> dict[str, dict[str, str]]:
    del size, mtime_ns   # only part of the cache key
    scratch = sqlite3.connect(":memory:")
    try:
        scratch.execute("PRAGMA foreign_keys=OFF")
        for statement in split_statements(Path(path).read_text(encoding="utf-8")):
            scratch.execute(statement)
        names = [r[0] for r in scratch.execute("SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'")]
        return {t: {r[1]: (r[2] or "").upper() for r in scratch.execute(f'PRAGMA table_info("{t}")')} for t in names}
    finally:
        scratch.close()


def _check_no_drift(conn: sqlite3.Connection, path: Path) -> None:
    for table, declared in _declared_tables(path).items():
        if not _table_exists(conn, table):
            continue
        actual = {r[1]: (r[2] or "").upper() for r in conn.execute(f'PRAGMA table_info("{table}")')}
        missing = tuple(c for c in declared if c not in actual)
        unexpected = tuple(c for c in actual if c not in declared)
        retyped = tuple(c for c in declared if c in actual and declared[c] != actual[c])
        if missing or unexpected or retyped:
            raise SchemaDriftError(table, Path(path).name, missing, unexpected, retyped)


def apply_schema(conn: sqlite3.Connection) -> None:
    """Create the tables of ``sql/schema`` that do not exist yet (idempotent; keeps the data). A table that exists with other columns than its file declares is not migrated:
    ``SchemaDriftError`` names it and its columns.

    Called in autocommit mode, the statements run in one transaction of their own, which is committed whatever happens (what an error leaves is what each statement before it did, as in
    autocommit), because a statement outside a transaction takes and gives back the file's lock by itself, which is most of the cost of a no-op ``CREATE ... IF NOT EXISTS`` when everything
    exists. Called inside the caller's transaction, it joins it."""
    own = not conn.in_transaction
    if own:
        conn.execute("BEGIN")
    try:
        for path in sorted((SQL_DIR / "schema").glob("*.sql")):
            _check_no_drift(conn, path)
            run_sql_file(conn, path)
    finally:
        if own and conn.in_transaction:
            conn.execute("COMMIT")


def rebuild_marts(conn: sqlite3.Connection, group: Literal["powerbi"], params: Mapping[str, object] | None = None) -> list[str]:
    """Rebuild the marts of a group (``sql/marts/<group>/mart_*.sql``, in file-name order) inside the caller's transaction: each file drops its table and creates it again from the tables it reads, so a
    rollback undoes it too. Returns the names of the files that ran (project 07's runner)."""
    if group not in MART_GROUPS:
        raise ValueError(f"grupo de marts desconocido: {group!r}; se esperaba uno de {', '.join(MART_GROUPS)}")
    if not conn.in_transaction:
        raise RuntimeError("los marts se reconstruyen dentro de una transacción abierta, para que una falla los deshaga")
    paths = sorted((SQL_DIR / "marts" / group).glob("mart_*.sql"))
    for path in paths:
        run_sql_file(conn, path, params)
    return [path.stem for path in paths]


# --- controls --------------------------------------------------------------------------------------------------------------


def run_checks(conn: sqlite3.Connection, group: Literal["load", "model"], params: Mapping[str, object] | None = None, *, only: Iterable[str] | None = None) -> list[CheckResult]:
    """Run the controls of a group, in file-name order (or only those named in `only`); each file selects the rows that break its rule (none: it passes). A group without a folder
    has no controls: the ones of the star schema come with it (U15)."""
    if group not in CHECK_GROUPS:
        raise ValueError(f"grupo de controles desconocido: {group!r}; se esperaba uno de {', '.join(CHECK_GROUPS)}")
    bound = dict(params or {})
    paths = sorted((SQL_DIR / "checks" / group).glob("chk_*.sql"))
    if only is not None:
        wanted = list(only)
        unknown = [name for name in wanted if name not in {p.stem for p in paths}]
        if unknown:
            raise ValueError(f"no hay un control {', '.join(unknown)} en el grupo {group}")
        paths = [p for p in paths if p.stem in wanted]
    results = []
    for path in paths:
        statements = split_statements(path.read_text(encoding="utf-8"))
        if len(statements) != 1:
            raise ValueError(f"{path.name} debe tener exactamente un SELECT y tiene {len(statements)} sentencias")
        select = statements[0].rstrip().rstrip(";")
        violations = conn.execute(f"SELECT COUNT(*) FROM ({select})", bound).fetchone()[0]
        sample = conn.execute(f"SELECT * FROM ({select}) LIMIT {SAMPLE_LIMIT}", bound).fetchall() if violations else []
        results.append(CheckResult(path.stem, int(violations), sample))
    return results


def _fail_on(checks: list[CheckResult], what: str, step: str = "La carga") -> None:
    """``CheckFailedError`` if a control has rows. It is raised inside the caller's open transaction, so the log says which control failed."""
    failing = [c for c in checks if c.violations]
    for c in failing:
        logger.error("%s: control %s failed, violations=%d sample=%s", what, c.check_id, c.violations, c.sample)
    if failing:
        raise CheckFailedError(checks, step)


# --- load ------------------------------------------------------------------------------------------------------------------


def _stamp(value: datetime) -> str:
    """An instant as the warehouse stores it: ``YYYY-MM-DD HH:MM:SS``."""
    return value.strftime("%Y-%m-%d %H:%M:%S")


def _require_a_passed_validation(spec: DeliverySpec, lines: pd.DataFrame, report: ValidationReport, run_key: str) -> None:
    if report.run_key != run_key:
        raise LoadRefusedError(f"La carga {run_key} se rechazó: la validación que se le pasó es de la corrida {report.run_key}, no de esta")
    if report.delivery_id != spec.delivery_id:
        raise LoadRefusedError(f"La carga {run_key} se rechazó: la validación es de la entrega {report.delivery_id} y se carga {spec.delivery_id}")
    present = {result.rule_id for result in report.results}
    if not set(BLOCKING_RULES) <= present:
        raise LoadRefusedError(f"La carga {run_key} se rechazó: la validación no tiene las reglas bloqueantes {', '.join(BLOCKING_RULES)} (tiene {sorted(present)})")
    failed = [result.rule_id for result in report.results if result.severity == BLOCKING and not result.passed]
    if failed:
        raise LoadRefusedError(f"La carga {run_key} se rechazó: la validación no pasó {', '.join(failed)}")
    if report.rows is None or report.sha256 is None:
        raise LoadRefusedError(f"La carga {run_key} se rechazó: la validación no dice qué archivo validó (filas y SHA-256)")
    if len(lines) != report.rows:
        raise LoadRefusedError(f"La carga {run_key} se rechazó: las líneas que se pasan son {len(lines)} filas y el archivo que se validó tiene {report.rows}")


def _line_rows(spec: DeliverySpec, lines: pd.DataFrame) -> list[tuple]:
    """The lines as the rows of the ``lines`` table: the price as the shortest decimal text that is the same number, the date as text and a guest's customer as NULL."""
    prices = [format(Decimal(repr(price)), "f") for price in lines["price"].tolist()]
    dates = lines["invoice_date"].dt.strftime("%Y-%m-%d %H:%M:%S").tolist()
    customers = [None if pd.isna(customer) else int(customer) for customer in lines["customer_id"]]
    descriptions = [None if pd.isna(text) else str(text) for text in lines["description"]]
    return list(zip(
        lines["line_key"].astype("int64").tolist(), [spec.delivery_id] * len(lines), lines["invoice"].astype(str).tolist(), lines["stock_code"].astype(str).tolist(), descriptions,
        lines["quantity"].astype("int64").tolist(), dates, prices, customers, lines["country"].astype(str).tolist(), lines["internal_repeat"].astype(int).tolist(),
        lines["role"].astype(str).tolist(), strict=True))


def _new_products(conn: sqlite3.Connection, spec: DeliverySpec, lines: pd.DataFrame) -> list[tuple]:
    """The products that this delivery shows for the first time: a code with a line of a basket (a purchase or a guest's) that ``products`` does not have yet, with its commonest
    non-blank description (the first in order on a tie), the day of its first line and, in the launch, the invoices that hold it."""
    basket = lines[lines["role"].isin(PRODUCT_ROLES)]
    known = {row[0] for row in conn.execute("SELECT stock_code FROM products")}
    fresh = basket[~basket["stock_code"].astype(str).isin(known)]
    if fresh.empty:
        return []
    described = fresh[fresh["description"].notna() & (fresh["description"].fillna("").str.strip() != "")]
    counts = described.groupby(["stock_code", "description"]).size().reset_index(name="n").sort_values(["stock_code", "n", "description"], ascending=[True, False, True])
    best = counts.drop_duplicates("stock_code").set_index("stock_code")["description"]
    first_seen = fresh.groupby("stock_code")["invoice_date"].min().dt.strftime("%Y-%m-%d")
    invoices = fresh.groupby("stock_code")["invoice"].nunique() if spec.kind == "launch" else fresh.groupby("stock_code")["invoice"].nunique() * 0
    return [(str(code), str(best[code]) if code in best.index else None, first_seen[code], int(invoices[code])) for code in sorted(first_seen.index)]


def load_delivery(conn: sqlite3.Connection, spec: DeliverySpec, lines: pd.DataFrame, report: ValidationReport, run_key: str, *, started_at: datetime,
                  config_sha256: str) -> LoadResult:
    """Record the delivery `spec` (with the rows and the SHA-256 of the file that `report` validated), the run (``running``), the validation `report`, the `lines` of the delivery and the
    products it shows for the first time, in one transaction with the controls of ``sql/checks/load/``. `config_sha256` is the sealed configuration's.

    Refused before writing (``LoadRefusedError``) when `report` is not this run's, this delivery's and a validation that passed every blocking rule, or when `lines` are not as many as the
    file it validated. A delivery already loaded (``DeliveryAlreadyLoadedError``), a run already recorded or a control with rows rolls everything back, apply_schema included, and the
    warehouse keeps exactly what it had."""
    if not _HEX64.fullmatch(config_sha256):
        raise ValueError("config_sha256 de la carga debe ser 64 caracteres hexadecimales en minúscula")
    _require_a_passed_validation(spec, lines, report, run_key)
    conn.execute("BEGIN IMMEDIATE")
    try:
        apply_schema(conn)
        row = conn.execute("SELECT status FROM deliveries WHERE delivery_id = ?", (spec.delivery_id,)).fetchone()
        if row is not None and row[0] == "loaded":
            raise DeliveryAlreadyLoadedError(spec.delivery_id)
        values = (spec.kind, spec.first_day.isoformat(), spec.last_day.isoformat(), _stamp(spec.as_of), report.rows, report.sha256, run_key)
        if row is None:
            conn.execute("INSERT INTO deliveries (kind, first_day, last_day, as_of, rows, sha256, status, run_key, delivery_id) VALUES (?, ?, ?, ?, ?, ?, 'loaded', ?, ?)", (*values, spec.delivery_id))
        else:   # a delivery that was rejected or only published before: the same delivery, now loaded by this run
            conn.execute("UPDATE deliveries SET kind = ?, first_day = ?, last_day = ?, as_of = ?, rows = ?, sha256 = ?, status = 'loaded', run_key = ? WHERE delivery_id = ?", (*values, spec.delivery_id))
        conn.execute("INSERT INTO pipeline_runs (run_key, started_at, status, delivery_id, as_of, config_sha256) VALUES (?, ?, 'running', ?, ?, ?)",
                     (run_key, _stamp(started_at), spec.delivery_id, _stamp(spec.as_of), config_sha256))
        conn.executemany("INSERT INTO validation_results (run_key, rule_id, name_es, severity, scope, aggregation, passed, rows_affected, examples_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                         [(run_key, r.rule_id, r.name_es, r.severity, r.scope, r.aggregation, int(r.passed), r.rows_affected, json.dumps(list(r.examples))) for r in report.results])
        conn.executemany("INSERT INTO lines (line_key, delivery_id, invoice, stock_code, description, quantity, invoice_date, price, customer_id, country, internal_repeat, role) "
                         "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", _line_rows(spec, lines))
        products = _new_products(conn, spec, lines)
        conn.executemany("INSERT INTO products (stock_code, description_es, first_seen, launch_invoices) VALUES (?, ?, ?, ?)", products)
        checks = run_checks(conn, "load")
        _fail_on(checks, f"load {run_key}")
        conn.execute("COMMIT")
    except BaseException:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        logger.warning("load %s rolled back: the warehouse keeps what it had", run_key)
        raise
    logger.info("load %s: delivery=%s lines=%d products=%d controls=%d", run_key, spec.delivery_id, len(lines), len(products), len(checks))
    return LoadResult(spec.delivery_id, run_key, len(lines), len(products), checks)



# --- what the launch and the weekly rounds read and write (U11) --------------------------------------------------------------------------------


class RoundConflictError(RuntimeError):
    """A round is already stored with another base than the one offered: what was issued for a round is not redone (D14, D24)."""


def _text_columns_as_string(frame: pd.DataFrame) -> pd.DataFrame:
    """The text columns with the ``string`` type that a delivery file gives them (its pandas metadata says so; a table made here has none)."""
    return frame.astype({column: "string" for column in ("invoice", "stock_code", "description", "country", "role")})


def read_lines(conn: sqlite3.Connection) -> pd.DataFrame:
    """Every line the warehouse holds, as the canonical frame of ``personaloffers.workbook`` (the columns, the types and the order of the line key), which is what a task cuts a round's history
    from: the warehouse has only the deliveries that were loaded, so nothing of the future can be in it. A warehouse without lines gives an empty frame with the columns."""
    columns = ["line_key", "invoice", "stock_code", "description", "quantity", "invoice_date", "price", "customer_id", "country", "internal_repeat", "role"]
    rows = conn.execute(f"SELECT {', '.join(columns)} FROM lines ORDER BY line_key").fetchall() if _table_exists(conn, "lines") else []
    if not rows:
        return _text_columns_as_string(wb.frame_of(wb.LINES_SCHEMA.empty_table()))
    stored = list(zip(*rows, strict=True))
    by_name = dict(zip(columns, stored, strict=True))
    typed = {
        "line_key": pa.array(by_name["line_key"], pa.int64()), "invoice": pa.array(by_name["invoice"], pa.string()), "stock_code": pa.array(by_name["stock_code"], pa.string()),
        "description": pa.array(by_name["description"], pa.string()), "quantity": pa.array(by_name["quantity"], pa.int64()),
        "invoice_date": pa.array(pd.to_datetime(list(by_name["invoice_date"]), format="%Y-%m-%d %H:%M:%S").to_numpy("datetime64[us]"), pa.timestamp("us")),
        "price": pa.array([float(text) for text in by_name["price"]], pa.float64()), "customer_id": pa.array(by_name["customer_id"], pa.int64()),
        "country": pa.array(by_name["country"], pa.string()), "internal_repeat": pa.array([bool(flag) for flag in by_name["internal_repeat"]], pa.bool_()),
        "role": pa.array(by_name["role"], pa.string()),
    }
    return _text_columns_as_string(wb.frame_of(pa.table(typed, schema=wb.LINES_SCHEMA)))


def _insert_base_rows(conn: sqlite3.Connection, rows: list[tuple]) -> None:
    conn.executemany("INSERT INTO contact_base (round_id, customer_id, recency_days, invoices_365, spend_365, tenure_days, bulk, invoices_before, segment) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", rows)


def store_round_base(conn: sqlite3.Connection, round_id: str, monday: date, period: str, run_key: str, table: pd.DataFrame, new_assignments: pd.DataFrame) -> bool:
    """Store the base of a round in one transaction: its row in ``rounds`` (with the size of the base and of each group), the assignments of the customers that have none yet
    (`new_assignments`: those of the launch, or the hash assignments of the ones that enter) and the ``contact_base`` rows of `table` (``personaloffers.base.base_table``). Every customer of the base
    must have a group, stored before or in `new_assignments`, or it is a ``ValueError`` that writes nothing. Returns True if it wrote, and False, writing nothing, if the round is stored with this
    same base; another base for a stored round is a ``RoundConflictError``. Joins the transaction of the caller if there is one."""
    own = not conn.in_transaction
    if own:
        conn.execute("BEGIN IMMEDIATE")
    try:
        stored_round = conn.execute("SELECT base_size FROM rounds WHERE round_id = ?", (round_id,)).fetchone()
        if stored_round is not None:
            in_base = conn.execute("SELECT COUNT(*) FROM contact_base WHERE round_id = ?", (round_id,)).fetchone()[0]
            if stored_round[0] != len(table) or in_base != len(table):
                raise RoundConflictError(f"la ronda {round_id} ya está guardada con otra base ({stored_round[0]} clientes, no {len(table)}): una ronda armada no se rehace")
            if not holdout.stored_assignments_agree(conn, new_assignments):
                raise RoundConflictError(f"la ronda {round_id} ya está guardada y las asignaciones que se ofrecen no son las que tiene: una asignación no se rehace (D14)")
            if own:
                conn.execute("ROLLBACK")
            return False
        customers = table["customer_id"].astype("int64").tolist()
        groups = {int(c): g for c, g in zip(new_assignments["customer_id"], new_assignments["grp"], strict=True)}
        for start in range(0, len(customers), 500):
            chunk = [c for c in customers[start:start + 500] if c not in groups]
            marks = ", ".join("?" * len(chunk))
            groups.update(dict(conn.execute(f"SELECT customer_id, grp FROM holdout_assignments WHERE customer_id IN ({marks})", chunk)) if chunk else {})
        without = sum(1 for c in customers if c not in groups)
        if without:
            raise ValueError(f"{without} clientes de la base de {round_id} no tienen un grupo: sin asignación no se arma la ronda")
        control = sum(1 for c in customers if groups[c] == "control")
        conn.execute("INSERT INTO rounds (round_id, monday, period, built_by_run, base_size, offer_size, control_size) VALUES (?, ?, ?, ?, ?, ?, ?)",
                     (round_id, monday.isoformat(), period, run_key, len(customers), len(customers) - control, control))
        holdout.store_assignments(conn, new_assignments, run_key)
        rows = [(round_id, int(r.customer_id), float(r.recency_days), int(r.invoices_365), float(r.spend_365), float(r.tenure_days), int(r.bulk), int(r.invoices_before), str(r.segment))
                for r in table.itertuples(index=False)]
        _insert_base_rows(conn, rows)
        if own:
            conn.execute("COMMIT")
        return True
    except BaseException:
        if own and conn.in_transaction:
            conn.execute("ROLLBACK")
        raise


def insert_model(conn: sqlite3.Connection, round_id: str, component: str, params: dict, artifact_path: str, artifact_sha256: str, fit_lines: int, seconds: float) -> None:
    """Register one fitted component of a round (``model_registry``, insert-only). Joins the transaction of the caller if there is one."""
    own = not conn.in_transaction
    if own:
        conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute("INSERT INTO model_registry (round_id, component, params_json, artifact_path, artifact_sha256, fit_lines, seconds) VALUES (?, ?, ?, ?, ?, ?, ?)",
                     (round_id, component, json.dumps(params, sort_keys=True), artifact_path, artifact_sha256, fit_lines, seconds))
        if own:
            conn.execute("COMMIT")
    except BaseException:
        if own and conn.in_transaction:
            conn.execute("ROLLBACK")
        raise


def register_models(conn: sqlite3.Connection, round_id: str, models: Iterable[tuple[str, dict, str, str, int, float]]) -> None:
    """Register every ``(component, params, artifact_path, artifact_sha256, fit_lines, seconds)`` of `models` for the round, all or none."""
    own = not conn.in_transaction
    if own:
        conn.execute("BEGIN IMMEDIATE")
    try:
        for component, params, path, digest, fit_lines, seconds in models:
            insert_model(conn, round_id, component, params, path, digest, fit_lines, seconds)
        if own:
            conn.execute("COMMIT")
    except BaseException:
        if own and conn.in_transaction:
            conn.execute("ROLLBACK")
        raise


def registered_models(conn: sqlite3.Connection, round_id: str) -> dict[str, tuple[str, str, dict]]:
    """``{component: (artifact_path, artifact_sha256, params)}`` of the models registered for the round."""
    rows = conn.execute("SELECT component, artifact_path, artifact_sha256, params_json FROM model_registry WHERE round_id = ? ORDER BY component", (round_id,)).fetchall()
    return {component: (path, digest, json.loads(params)) for component, path, digest, params in rows}
