"""The validation of a delivery (RF06, RF07; V10 to V18; plan section 6; decisions D05, D22 and D30).

Four rules are about the delivery and block the run: **V10** (it is the next delivery of the plan that is not loaded), **V11** (its file is the one its manifest names: it
exists, has the manifest's SHA-256, can be read, has the schema of the canonical lines and the manifest's number of rows), **V12** (every line has its date inside the
days of the delivery) and **V13** (no line is already loaded and none is twice in the delivery). A failing rule raises ``ValidationError`` (exit code 3) after the whole
validation was made, and the run that raised it writes nothing: validating changes no file and no row. When V11 fails the file cannot be trusted and is not read, so the
rules about its lines (V12 to V18) are *skipped* and the report says so. Three never block: **V14** counts the lines that repeat an earlier one of their sheet (they are
kept), **V15** counts the lines of a bad price or quantity (the ``bad_price`` role: they are set apart) and **V16** the empty descriptions (kept). The last two only count:
**V17** the lines of each role and **V18** the customers and the products that the warehouse had not seen.

The report names lines by their ``line_key`` (at most five, in order) and counts customers and products: it never holds a customer number (D30). The warehouse is read
through two tables, ``deliveries`` (``delivery_id``, ``status``) and ``lines`` (``line_key``, ``customer_id``, ``stock_code``, ``role``); without them (``conn`` is None or
the file has no such table yet) nothing is loaded.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from personaloffers import workbook as wb
from personaloffers.deliveries import DeliverySpec, delivery_plan, manifest_path_of, next_to_load, read_manifest
from personaloffers.files import sha256_file
from personaloffers.lines import PRODUCT_ROLES, ROLES

BLOCKING, WARNING, INFORMATIVE = "bloqueante", "advertencia", "informativa"
EXAMPLES = 5
QUERY_CHUNK = 500        # keys per query: far under the limit of variables of SQLite
# rule: (name, severity, scope, aggregation), as in the plan's table
RULES: dict[str, tuple[str, str, str, str]] = {
    "V10": ("La entrega es la siguiente del plan", BLOCKING, "entrega", "per_run"),
    "V11": ("Filas y SHA-256 son los del manifiesto de la entrega", BLOCKING, "entrega", "per_run"),
    "V12": ("Toda línea tiene su fecha dentro del período de la entrega", BLOCKING, "entrega", "per_run"),
    "V13": ("Ninguna línea ya cargada ni repetida dentro de la entrega", BLOCKING, "entrega", "per_run"),
    "V14": ("Repeticiones internas, contadas (se conservan)", WARNING, "línea", "per_run"),
    "V15": ("Precio o cantidad en cero o negativos fuera de las anulaciones (se apartan)", WARNING, "línea", "per_run"),
    "V16": ("Descripción vacía (se conserva)", WARNING, "línea", "per_run"),
    "V17": ("Líneas por rol", INFORMATIVE, "entrega", "per_run"),
    "V18": ("Clientes y productos nuevos de la entrega", INFORMATIVE, "entrega", "per_run"),
}
CONTENT_RULES = ("V12", "V13", "V14", "V15", "V16", "V17", "V18")
# the rules of the source (``sources`` and ``workbook`` raise them as ``SourceError``), as in the plan's table: their report is the source's, not a delivery's
SOURCE_SUBJECT = "fuente"
SOURCE_RULES: dict[str, str] = {
    "V01": "El zip existe con su tamaño y su huella",
    "V02": "Un solo miembro con el nombre exacto, sin rutas, con su tamaño y su huella",
    "V03": "El libro como zip: partes acotadas, sin macros, vínculos externos ni controles",
    "V04": "Las dos hojas con los nombres exactos y ninguna más",
    "V05": "La primera fila de cada hoja tiene las 8 columnas exactas en su orden",
    "V06": "Cada celda con su tipo; filas dentro del tope",
    "V07": "Toda fecha dentro del período del archivo",
}


@dataclass(frozen=True)
class RuleResult:
    rule_id: str
    name_es: str
    severity: str
    scope: str
    aggregation: str
    passed: bool
    rows_affected: int = 0                  # lines that break the rule (an informative rule affects none: it counts in ``detail``)
    examples: tuple[int, ...] = ()          # line keys, in order, at most five: never a customer number
    detail: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ValidationReport:
    delivery_id: str
    run_key: str
    results: tuple[RuleResult, ...]
    skipped: tuple[str, ...] = ()           # the rules that were not evaluated because the file could not be trusted
    rows: int | None = None                 # the rows and the SHA-256 of the file that V11 found to be the manifest's (None when it was not)
    sha256: str | None = None

    @property
    def blocking_failed(self) -> tuple[str, ...]:
        return tuple(r.rule_id for r in self.results if r.severity == BLOCKING and not r.passed)

    @property
    def passed(self) -> bool:
        return not self.blocking_failed

    def to_jsonable(self) -> dict[str, Any]:
        return {
            "delivery_id": self.delivery_id, "run_key": self.run_key, "skipped": list(self.skipped), "rows": self.rows, "sha256": self.sha256,
            "results": [{"rule_id": r.rule_id, "name_es": r.name_es, "severity": r.severity, "scope": r.scope, "aggregation": r.aggregation, "passed": r.passed,
                         "rows_affected": r.rows_affected, "examples": list(r.examples), "detail": r.detail} for r in self.results],
        }

    def to_markdown(self) -> str:
        def cell(text: object) -> str:
            return str(text).replace("|", "\\|")

        title = "# Validación de la fuente" if self.delivery_id == SOURCE_SUBJECT else f"# Validación de la entrega {self.delivery_id}"
        lines = [title, "", f"Corrida: {cell(self.run_key)}", "",
                 "| Regla | Nombre | Severidad | Alcance | Resultado | Líneas |", "| --- | --- | --- | --- | --- | ---: |"]
        for r in self.results:
            lines.append(f"| {r.rule_id} | {cell(r.name_es)} | {r.severity} | {r.scope} | {'pasa' if r.passed else 'falla'} | {r.rows_affected} |")
        if self.skipped:
            lines += ["", f"No se evaluaron, porque el archivo de la entrega no es el del manifiesto: {', '.join(self.skipped)}."]
        return "\n".join(lines) + "\n"


class ValidationError(RuntimeError):
    """A blocking rule of the delivery failed; the command line exits with 3. ``report`` says which."""

    EXIT_CODE = 3

    def __init__(self, report: ValidationReport) -> None:
        super().__init__(f"{report.delivery_id}: falla la regla bloqueante {', '.join(report.blocking_failed)}")
        self.report = report


def source_report(rule_id: str, problems: list[dict[str, Any]], run_key: str) -> ValidationReport:
    """The report of a source that a rule of V01 to V07 rejected (the runbook's first principle; B6 of the evaluation, D50): the failing rule with what it found, item by item, without the path of a
    file (the report is versioned: a path of this machine is never in it) and never a value of a customer; the rules after it were not evaluated."""
    detail = {"problems": [{key: value for key, value in problem.items() if key != "path"} for problem in problems]}
    result = RuleResult(rule_id, SOURCE_RULES.get(rule_id, rule_id), BLOCKING, "fuente", "source", False, 0, (), detail)
    return ValidationReport(SOURCE_SUBJECT, run_key, (result,))


def _result(rule_id: str, passed: bool, keys: list[int] | None = None, rows: int = 0, **detail: Any) -> RuleResult:
    name, severity, scope, aggregation = RULES[rule_id]
    return RuleResult(rule_id, name, severity, scope, aggregation, passed, rows, tuple(sorted(set(keys or []))[:EXAMPLES]), detail)


# --- the warehouse, read ------------------------------------------------------------------------------------------------------------


def _has_table(conn: sqlite3.Connection | None, name: str) -> bool:
    return conn is not None and conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (name,)).fetchone() is not None


def loaded_ids(conn: sqlite3.Connection | None) -> set[str]:
    """The deliveries that the warehouse holds as loaded."""
    if not _has_table(conn, "deliveries"):
        return set()
    return {row[0] for row in conn.execute("SELECT delivery_id FROM deliveries WHERE status = 'loaded'")}


def _loaded_keys(conn: sqlite3.Connection | None, keys: list[int]) -> set[int]:
    if not keys or not _has_table(conn, "lines"):
        return set()
    found: set[int] = set()
    for start in range(0, len(keys), QUERY_CHUNK):
        chunk = keys[start:start + QUERY_CHUNK]
        marks = ", ".join("?" * len(chunk))
        found |= {row[0] for row in conn.execute(f"SELECT line_key FROM lines WHERE line_key IN ({marks})", chunk)}
    return found


def _known(conn: sqlite3.Connection | None) -> tuple[set[int], set[str]]:
    """The customers with a purchase and the products with a basket line that the warehouse already holds."""
    if not _has_table(conn, "lines"):
        return set(), set()
    customers = {row[0] for row in conn.execute("SELECT DISTINCT customer_id FROM lines WHERE role = 'purchase' AND customer_id IS NOT NULL")}
    marks = ", ".join("?" * len(PRODUCT_ROLES))
    products = {row[0] for row in conn.execute(f"SELECT DISTINCT stock_code FROM lines WHERE role IN ({marks})", PRODUCT_ROLES)}
    return customers, products


# --- V11 ----------------------------------------------------------------------------------------------------------------------------


def _v11(spec: DeliverySpec, path: Path) -> tuple[RuleResult, pd.DataFrame | None, dict[str, Any] | None]:
    """The result of V11 and, when the file is the manifest's and can be read, its lines and its manifest entry."""
    def failed(reason: str) -> tuple[RuleResult, None, None]:
        return _result("V11", False, reason=reason), None, None

    try:
        entry = read_manifest(manifest_path_of(path))["deliveries"].get(spec.delivery_id)
    except ValueError:
        return failed("manifest")
    if entry is None:
        return failed("not_in_manifest")
    if not path.is_file():
        return failed("missing_file")
    if sha256_file(path) != entry["sha256"]:
        return failed("sha256")
    try:
        schema = pq.read_schema(path)
    except (pa.ArrowException, OSError):
        return failed("unreadable")
    if not schema.remove_metadata().equals(wb.LINES_SCHEMA):
        return failed("schema")
    try:
        table = pq.read_table(path)
    except (pa.ArrowException, OSError):
        return failed("unreadable")
    if table.num_rows != entry["rows"]:
        return failed("rows")
    return _result("V11", True), wb.frame_of(table), entry


# --- the validation -----------------------------------------------------------------------------------------------------------------


def validate_delivery(spec: DeliverySpec, path: Path, conn: sqlite3.Connection | None, view: Any, *, run_key: str) -> ValidationReport:
    """V10 to V18 for the delivery `spec` whose file is `path` (its manifest is the ``manifest.json`` of the folder above its own). `conn` is the warehouse, read only (None
    or without the tables: nothing is loaded). Raises ``ValidationError`` when a blocking rule fails; writes nothing either way."""
    path = Path(path)
    expected = next_to_load(delivery_plan(view), loaded_ids(conn))
    results = [_result("V10", expected == spec, expected=expected.delivery_id if expected is not None else None)]
    v11, frame, entry = _v11(spec, path)
    results.append(v11)
    skipped: tuple[str, ...] = ()
    if frame is None:
        skipped = CONTENT_RULES
    else:
        keys = frame["line_key"]
        stamps = frame["invoice_date"]
        outside = ~((stamps >= spec.start) & (stamps < spec.end))
        results.append(_result("V12", not outside.any(), keys[outside].tolist(), int(outside.sum())))
        loaded = _loaded_keys(conn, sorted(set(keys.tolist())))
        broken = keys.duplicated(keep="first") | keys.isin(loaded)
        results.append(_result("V13", not broken.any(), keys[broken].tolist(), int(broken.sum())))
        repeats = frame["internal_repeat"].to_numpy(dtype=bool)
        results.append(_result("V14", not repeats.any(), keys[repeats].tolist(), int(repeats.sum())))
        bad = (frame["role"] == "bad_price").to_numpy(dtype=bool)
        results.append(_result("V15", not bad.any(), keys[bad].tolist(), int(bad.sum())))
        empty = (frame["description"].isna() | (frame["description"].fillna("").str.strip() == "")).to_numpy(dtype=bool)
        results.append(_result("V16", not empty.any(), keys[empty].tolist(), int(empty.sum())))
        counts = {role: int((frame["role"] == role).sum()) for role in ROLES}
        if sum(counts.values()) != len(frame):
            counts["unknown"] = len(frame) - sum(counts.values())
        results.append(_result("V17", True, **counts))
        known_customers, known_products = _known(conn)
        purchases = frame[frame["role"] == "purchase"]
        baskets = frame[frame["role"].isin(PRODUCT_ROLES)]
        new_customers = set(purchases["customer_id"].dropna().astype(int)) - known_customers
        new_products = set(baskets["stock_code"].dropna().astype(str)) - known_products
        results.append(_result("V18", True, new_customers=len(new_customers), new_products=len(new_products)))
    report = ValidationReport(spec.delivery_id, run_key, tuple(results), skipped, rows=entry["rows"] if entry else None, sha256=entry["sha256"] if entry else None)
    if not report.passed:
        raise ValidationError(report)
    return report
