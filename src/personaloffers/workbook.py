"""The workbook of Online Retail II as an untrusted file (RF02, RF03; V03 to V07; decisions D02 and D03) and the canonical lines that come out of it.

``inspect_workbook`` is V03 and uses only ``zipfile``: before openpyxl sees a byte, every part of the package is checked by its name (no macros, no external links,
no ActiveX, no path that leaves the archive), its declared size (at most ``[source] max_part_bytes``), its compression ratio (a zero-filled part is a thousand to one;
the real sheets are seven to one), its encryption and its first bytes (no DTD, so no entity can expand). What it cannot see is a lie in a header: ``zipfile`` never
hands out more bytes than the header declares and refuses a part whose CRC does not match, and openpyxl reads in read-only mode, one row at a time.

``read_workbook`` is V04 to V07: the two sheets with their exact names and no other, the eight columns in their order, every cell with its type, at most
``[source] max_rows`` rows in a sheet, every date inside the range of the source. A row that does not convert is reported with its sheet, column and row number and,
for an invoice or a customer, only the type and the length of the value: an identifier is never printed. The cells are converted as openpyxl delivers them in the real
file (an invoice or a code as a number or as text, a quantity as an integer, a price as a float or an integer, a customer as an integer or empty).

``canonical_lines`` drops the copies and flags the repeats (RF03): the days that both sheets hold (from the first day of the second sheet to the last day of the
first) are in both, and the second sheet's copy of each row there is dropped; a row that appears twice inside a sheet is kept and flagged ``internal_repeat``. The
canonical lines are written once, to ``data/interim/lines.parquet``, and their manifest (``lines_manifest.json``) is written last: a reader refuses a file the
manifest does not describe. The roles of the lines (RF04) are the next unit's.
"""

from __future__ import annotations

import json
import math
import re
import zipfile
import zlib
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import openpyxl
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from personaloffers.config import LINE_KEY_SHEET_FACTOR, PipelineConfig
from personaloffers.files import atomic_path, sha256_file, write_atomic
from personaloffers.sources import SourceError, rule

MAX_COMPRESSION_RATIO = 100          # the real sheets are 7 to 1; a part that is mostly one repeated byte is a thousand to one
RATIO_FROM_BYTES = 64 * 1024         # a part under this size cannot hurt, whatever its ratio
MAX_PARTS = 1000
DTD_SCAN_BYTES = 4096
FORBIDDEN_IN_PART_NAMES = ("vbaproject", "externallink", "activex")   # macros, external links and ActiveX controls, whatever the case of the name
REQUIRED_PARTS = ("[Content_Types].xml", "xl/workbook.xml")
CUSTOMER_ID_RANGE = (10_000, 99_999)                  # five digits (V06): the real numbers go from 12346 to 18287, the fixture's from 90001
EXAMPLES = 5                                          # examples kept for each column that does not convert, and for the dates
MASKED_COLUMNS = ("Invoice", "Customer ID")           # identifiers (D30): an example says the type and the length of the value, never the value
COLUMN_ORDER = ("Invoice", "StockCode", "Description", "Quantity", "InvoiceDate", "Price", "Customer ID", "Country")   # the names the problems use
REQUIRED_COLUMNS = ("Invoice", "StockCode", "Quantity", "InvoiceDate", "Price")                                          # a cell that is never empty
RAW_COLUMNS = ("sheet", "source_row", "invoice", "stock_code", "description", "quantity", "invoice_date", "price", "customer_id", "country")
LINE_COLUMNS = ("line_key", "invoice", "stock_code", "description", "quantity", "invoice_date", "price", "customer_id", "country", "internal_repeat")
KEY_COLUMNS = ["invoice", "stock_code", "description", "quantity", "invoice_date", "price", "customer_id", "country"]   # what makes two rows the same row
LINES_NAME = "lines.parquet"
LINES_MANIFEST = "lines_manifest.json"
MANIFEST_VERSION = 1
ATTRIBUTION = "Chen, D. (2012). Online Retail II [Dataset]. UCI Machine Learning Repository. https://doi.org/10.24432/C5CG6D (CC BY 4.0)"
LINES_SCHEMA = pa.schema([
    ("line_key", pa.int64()), ("invoice", pa.string()), ("stock_code", pa.string()), ("description", pa.string()), ("quantity", pa.int64()),
    ("invoice_date", pa.timestamp("us")), ("price", pa.float64()), ("customer_id", pa.int64()), ("country", pa.string()), ("internal_repeat", pa.bool_()),
])
_HEX64 = re.compile(r"[0-9a-f]{64}")


# --- V03: the package ----------------------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class WorkbookCheck:
    """What the check of the package measured: the parts, their total and largest size once inflated, and the highest compression ratio."""

    parts: int
    uncompressed_bytes: int
    largest_part: int
    max_ratio: float


def inspect_workbook(path: Path, cfg: PipelineConfig) -> WorkbookCheck:
    """V03: refuse a package that is not a plain workbook, before openpyxl opens it (see the module). Writes nothing."""
    path = Path(path)
    limit = cfg.source.max_part_bytes
    try:
        archive = zipfile.ZipFile(path)
    except (zipfile.BadZipFile, OSError) as error:
        raise rule("V03", f"el libro no es un archivo zip válido ({type(error).__name__})", reason="unreadable") from error
    with archive:
        infos = archive.infolist()
        if len(infos) > MAX_PARTS:
            raise rule("V03", f"el libro tiene {len(infos)} partes, por encima del límite de {MAX_PARTS}", reason="parts", parts=len(infos), max_parts=MAX_PARTS)
        largest, total, ratio = 0, 0, 0.0
        for info in infos:
            name = info.filename
            lower = name.lower()
            if name.startswith(("/", "\\")) or ".." in name.replace("\\", "/").split("/") or "\\" in name or "\0" in name:
                raise rule("V03", f"la parte «{name}» tiene un nombre que sale del archivo", reason="part_name", part=name)
            if any(word in lower for word in FORBIDDEN_IN_PART_NAMES):
                raise rule("V03", f"la parte «{name}» no se admite en un libro de datos (macros, vínculos externos o controles ActiveX)", reason="forbidden_part", part=name)
            if info.flag_bits & 0x1:
                raise rule("V03", f"la parte «{name}» está cifrada", reason="encrypted", part=name)
            if info.file_size > limit:
                raise rule("V03", f"la parte «{name}» declara {info.file_size} bytes descomprimida, por encima del límite de {limit} ([source] max_part_bytes)", reason="part_size",
                           part=name, size=info.file_size, max_part_bytes=limit)
            part_ratio = info.file_size / max(info.compress_size, 1)
            if info.file_size >= RATIO_FROM_BYTES and part_ratio > MAX_COMPRESSION_RATIO:
                raise rule("V03", f"la parte «{name}» se comprime {part_ratio:.0f} a 1, por encima del límite de {MAX_COMPRESSION_RATIO} a 1", reason="ratio", part=name,
                           ratio=round(part_ratio, 1), max_ratio=MAX_COMPRESSION_RATIO)
            if lower.endswith((".xml", ".rels")):
                try:
                    with archive.open(info) as part:
                        head = part.read(DTD_SCAN_BYTES)
                except (zipfile.BadZipFile, zlib.error, EOFError, NotImplementedError, RuntimeError) as error:
                    raise rule("V03", f"la parte «{name}» está dañada o no se puede descomprimir ({type(error).__name__})", reason="unreadable", part=name) from error
                if re.search(rb"<!\s*(DOCTYPE|ENTITY)", head, re.IGNORECASE):
                    raise rule("V03", f"la parte «{name}» declara un DTD o una entidad, que un libro de datos no necesita", reason="dtd", part=name)
            largest, total, ratio = max(largest, info.file_size), total + info.file_size, max(ratio, part_ratio)
        names = {info.filename for info in infos}
        for required in REQUIRED_PARTS:
            if required not in names:
                raise rule("V03", f"al libro le falta la parte «{required}»", reason="missing_part", part=required)
    return WorkbookCheck(parts=len(infos), uncompressed_bytes=total, largest_part=largest, max_ratio=round(ratio, 2))


# --- V04 to V07: the cells -------------------------------------------------------------------------------------------------------------


_BAD = object()


def _is_blank(value: Any) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def _integer(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and math.isfinite(value) and value == int(value):
        return int(value)
    return None


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if math.isfinite(value) else None


def _identifier(value: Any) -> str | None:
    """An invoice or a product code: a text that is not blank, or a whole number written as its digits."""
    if isinstance(value, str):
        return value if value.strip() else None
    number = _integer(value)
    return None if number is None else str(number)


def _free_text(value: Any) -> Any:
    """A description or a country: blank is None; a text stays; a number is its text (the workbook mixes both); anything else does not convert."""
    if _is_blank(value):
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return str(int(value)) if _integer(value) is not None else repr(value)
    return _BAD


def _customer(value: Any) -> Any:
    """Blank (a guest) is None; otherwise a whole number of five digits."""
    if _is_blank(value):
        return None
    number = _integer(value)
    return number if number is not None and CUSTOMER_ID_RANGE[0] <= number <= CUSTOMER_ID_RANGE[1] else _BAD


def convert_row(values: tuple) -> tuple[tuple, list[str]]:
    """The eight cells of a row as ``(invoice, stock code, description, quantity, timestamp, price, customer or None, country)`` and the names of the columns that do
    not convert, in the order of the workbook (their value in the tuple is None; an empty country is the empty text)."""
    parts = (_identifier(values[0]), _identifier(values[1]), _free_text(values[2]), _integer(values[3]), values[4] if isinstance(values[4], datetime) else None,
             _number(values[5]), _customer(values[6]), _free_text(values[7]))
    bad = [column for column, part in zip(COLUMN_ORDER, parts, strict=True) if part is _BAD or (part is None and column in REQUIRED_COLUMNS)]
    invoice, code, description, quantity, stamp, price, customer, country = (None if part is _BAD else part for part in parts)
    return (invoice, code, description, quantity, stamp, price, customer, "" if country is None else country), bad


def _shown(column: str, value: Any) -> str:
    if column in MASKED_COLUMNS:
        return f"<{type(value).__name__} de {len(str(value))} caracteres>"
    text = repr(value)
    return text[:60] + "..." if len(text) > 60 else text


def _header_problem(name: str, header: list[Any], columns: tuple[str, ...]) -> SourceError | None:
    while header and header[-1] is None:
        header.pop()
    shown = [str(cell) for cell in header]
    if shown == list(columns):
        return None
    missing, extra = [c for c in columns if c not in shown], [c for c in shown if c not in columns]
    order = "" if missing or extra else " pero en otro orden"
    return rule("V05", f"la hoja «{name}» no tiene exactamente las columnas {', '.join(columns)}, en ese orden; tiene {', '.join(shown) or 'ninguna'}{order}",
                sheet=name, columns=shown, missing=missing, extra=extra)


def _read_sheet(sheet: Any, number: int, name: str, cfg: PipelineConfig) -> dict[str, list]:
    """The rows of one sheet, converted; raises V06 for a row over the limit, a value outside the eight columns or a cell that does not convert, and V07 for a date
    outside the range of the source (after the whole sheet was read, so that the count is of the sheet)."""
    source, width = cfg.source, len(cfg.source.columns)
    out: dict[str, list] = {key: [] for key in RAW_COLUMNS}
    problems: dict[str, list[int]] = {}
    shown: dict[str, list[str]] = {}
    out_of_range: list[tuple[int, Any]] = []
    first, last = source.first_date, source.last_date
    rows = sheet.iter_rows(min_row=2, values_only=True)
    try:   # closing the generator releases the sheet's file at once: on Windows an open handle would keep the extracted workbook from being removed
        for row_number, row in enumerate(rows, start=1):
            if row_number > source.max_rows:
                raise rule("V06", f"la hoja «{name}» tiene más de {source.max_rows} filas ([source] max_rows)", reason="rows", sheet=name, max_rows=source.max_rows)
            if len(row) > width and any(value is not None for value in row[width:]):
                raise rule("V06", f"la hoja «{name}» tiene datos fuera de las {width} columnas en la fila {row_number}", reason="outside_columns", sheet=name, row=row_number)
            values = tuple(row[:width]) + (None,) * max(0, width - len(row))
            if all(value is None for value in values):
                continue
            converted, bad = convert_row(values)
            for column in bad:
                bucket = problems.setdefault(column, [])
                bucket.append(row_number)
                if len(bucket) <= EXAMPLES:
                    shown.setdefault(column, []).append(_shown(column, values[COLUMN_ORDER.index(column)]))
            if bad:
                continue
            stamp = converted[4]
            if not first <= stamp.date() <= last:
                out_of_range.append((row_number, stamp))
            out["sheet"].append(number)
            out["source_row"].append(row_number)
            for key, value in zip(RAW_COLUMNS[2:], converted, strict=True):
                out[key].append(value)
    finally:
        rows.close()
    if problems:
        entries = [
            {"rule_id": "V06", "sheet": name, "column": column, "count": len(problems[column]),
             "examples": [{"row": row, "value": value} for row, value in zip(problems[column][:EXAMPLES], shown[column], strict=True)]}
            for column in COLUMN_ORDER if column in problems
        ]
        described = "; ".join(f"hoja «{name}», columna «{entry['column']}»: {entry['count']} valores no cumplen el tipo (primera fila: {entry['examples'][0]['row']})" for entry in entries)
        raise SourceError("V06", described, entries)
    if out_of_range:
        entry = {"rule_id": "V07", "sheet": name, "count": len(out_of_range),
                 "examples": [{"row": row, "value": repr(stamp)} for row, stamp in out_of_range[:EXAMPLES]], "first_date": first.isoformat(), "last_date": last.isoformat()}
        raise SourceError("V07", f"la hoja «{name}» tiene {len(out_of_range)} fechas fuera de {first} a {last} (primera fila: {out_of_range[0][0]})", [entry])
    return out


def read_workbook(path: Path, cfg: PipelineConfig) -> pd.DataFrame:
    """V04 to V07: the rows of the two sheets, converted, as one table in the order of ``[source] sheets`` and of the rows (``RAW_COLUMNS``; ``sheet`` is 1 or 2 and
    ``source_row`` the row of the sheet counted from the first below the header, blank rows included). Blank rows are skipped. Nothing is written."""
    source = cfg.source
    try:
        book = openpyxl.load_workbook(Path(path), read_only=True, data_only=True, keep_links=False)
    except Exception as error:   # an untrusted file: any failure to open it is the rule's failure, with its cause named by type
        raise rule("V03", f"el libro no se puede abrir como .xlsx ({type(error).__name__})", reason="unreadable") from error
    try:
        present = list(book.sheetnames)
        missing, extra = [s for s in source.sheets if s not in present], [s for s in present if s not in source.sheets]
        if missing or extra:
            raise rule("V04", f"el libro debe tener exactamente las hojas {list(source.sheets)}; le faltan {missing} y tiene de más {extra}", reason="sheets",
                       present=present, missing=missing, extra=extra)
        for name in source.sheets:       # every header first: a wrong header is refused before a million rows are read
            rows = book[name].iter_rows(min_row=1, max_row=1, values_only=True)
            try:
                problem = _header_problem(name, list(next(rows, ())), source.columns)
            finally:
                rows.close()
            if problem is not None:
                raise problem
        sheets = [_read_sheet(book[name], number, name, cfg) for number, name in enumerate(source.sheets, start=1)]
    finally:
        book.close()
    joined = {key: [value for sheet in sheets for value in sheet[key]] for key in RAW_COLUMNS}
    frame = pd.DataFrame({
        "sheet": np.asarray(joined["sheet"], dtype="int64"), "source_row": np.asarray(joined["source_row"], dtype="int64"),
        "invoice": pd.array(joined["invoice"], dtype="string"), "stock_code": pd.array(joined["stock_code"], dtype="string"),
        "description": pd.array(joined["description"], dtype="string"), "quantity": np.asarray(joined["quantity"], dtype="int64"),
        "invoice_date": pd.Series(joined["invoice_date"], dtype="datetime64[us]"), "price": np.asarray(joined["price"], dtype="float64"),
        "customer_id": pd.array(joined["customer_id"], dtype="Int64"), "country": pd.array(joined["country"], dtype="string"),
    })
    return frame[list(RAW_COLUMNS)]


# --- RF03: the copies and the repeats ---------------------------------------------------------------------------------------------


def canonical_lines(raw: pd.DataFrame, cfg: PipelineConfig) -> pd.DataFrame:
    """The lines of the workbook without the second sheet's copies of the days that both sheets hold, with ``internal_repeat`` and the ``line_key`` of each line.

    The shared days run from the first day of the second sheet to the last day of the first. Inside them, a row of the second sheet is a copy as many times as the
    first sheet holds the same row (all eight values equal, an empty one equal to an empty one): the first sheet's rows stay, the second's copies go, and a row that the
    second sheet holds more often than the first stays for its extra appearances. Outside the shared days nothing is dropped. A line equal to an earlier line is
    flagged ``internal_repeat`` and kept (D03). ``line_key`` is the sheet times ``LINE_KEY_SHEET_FACTOR`` plus the row of the sheet."""
    last_sheet = len(cfg.source.sheets)
    first, second = raw[raw["sheet"] == 1], raw[raw["sheet"] == last_sheet]
    keep = pd.Series(True, index=raw.index)
    if len(first) and len(second):
        start, end = second["invoice_date"].dt.normalize().min(), first["invoice_date"].dt.normalize().max()
        if start <= end:
            shared_first = first[first["invoice_date"].dt.normalize() >= start]
            shared_second = second[second["invoice_date"].dt.normalize() <= end]
            if len(shared_first) and len(shared_second):
                counts = shared_first.groupby(KEY_COLUMNS, dropna=False, sort=False).size().rename("in_first").reset_index()
                probe = shared_second[KEY_COLUMNS].copy()
                probe["occurrence"] = shared_second.groupby(KEY_COLUMNS, dropna=False, sort=False).cumcount().to_numpy()
                probe["position"] = shared_second.index.to_numpy()
                merged = probe.merge(counts, on=KEY_COLUMNS, how="left")
                copies = merged.loc[merged["occurrence"] < merged["in_first"].fillna(0), "position"]
                keep.loc[copies.to_numpy()] = False
    kept = raw[keep].reset_index(drop=True)
    out = pd.DataFrame({
        "line_key": kept["sheet"].to_numpy(dtype="int64") * LINE_KEY_SHEET_FACTOR + kept["source_row"].to_numpy(dtype="int64"),
        **{column: kept[column] for column in KEY_COLUMNS},
        "internal_repeat": kept.duplicated(subset=KEY_COLUMNS, keep="first").to_numpy(),
    })
    return out[list(LINE_COLUMNS)]


# --- the canonical lines on disk, with their manifest written last -------------------------------------------------------------------


class InterimError(ValueError):
    """The canonical lines are not the file their manifest names: missing, changed, or without a manifest."""


def write_lines(frame: pd.DataFrame, interim_dir: Path, digests: dict[str, str]) -> str:
    """Write ``lines.parquet`` atomically and then ``lines_manifest.json`` with its hash and the zip's and the workbook's: a failure between the two leaves a file that
    does not match its manifest, which every reader refuses and the task rebuilds. Returns the SHA-256 of the Parquet file."""
    interim_dir = Path(interim_dir)
    table = pa.Table.from_pandas(frame[list(LINE_COLUMNS)], schema=LINES_SCHEMA, preserve_index=False)
    metadata = {**(table.schema.metadata or {}), b"personaloffers.zip_sha256": digests["zip"].encode("ascii"), b"personaloffers.attribution": ATTRIBUTION.encode("utf-8")}
    target = interim_dir / LINES_NAME
    with atomic_path(target) as temporary:
        pq.write_table(table.replace_schema_metadata(metadata), temporary)
    digest = sha256_file(target)
    manifest = {"version": MANIFEST_VERSION, "zip_sha256": digests["zip"], "member_sha256": digests["member"], "rows": len(frame), "files": {LINES_NAME: digest}}
    write_atomic(interim_dir / LINES_MANIFEST, json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return digest


def lines_state(interim_dir: Path) -> tuple[str | None, dict]:
    """``(problem, manifest)``: the problem is None when the manifest is valid and the Parquet file is the one it names."""
    folder = Path(interim_dir)
    path = folder / LINES_MANIFEST
    if not path.is_file():
        return f"falta {LINES_MANIFEST} en {folder.name}: las líneas canónicas no tienen su manifiesto", {}
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
        valid = (isinstance(document, dict) and set(document) == {"version", "zip_sha256", "member_sha256", "rows", "files"} and document["version"] == MANIFEST_VERSION
                 and all(isinstance(document[key], str) and _HEX64.fullmatch(document[key]) for key in ("zip_sha256", "member_sha256"))
                 and isinstance(document["rows"], int) and not isinstance(document["rows"], bool) and document["rows"] >= 0
                 and isinstance(document["files"], dict) and set(document["files"]) == {LINES_NAME}
                 and isinstance(document["files"][LINES_NAME], str) and _HEX64.fullmatch(document["files"][LINES_NAME]) is not None)
    except (OSError, ValueError, KeyError, TypeError):
        valid = False
    if not valid:
        return f"{LINES_MANIFEST} no es un manifiesto válido de las líneas canónicas", {}
    target = folder / LINES_NAME
    if not target.is_file():
        return f"falta {LINES_NAME}, que el manifiesto nombra", {}
    if sha256_file(target) != document["files"][LINES_NAME]:
        return f"{LINES_NAME} no coincide con la huella que dice el manifiesto: es de otra escritura", {}
    return None, document


def read_lines(cfg: PipelineConfig) -> pd.DataFrame:
    """The canonical lines (``LINE_COLUMNS``); ``InterimError`` if the file is not the one its manifest names."""
    interim = Path(cfg.paths.interim_dir)
    problem, _manifest = lines_state(interim)
    if problem is not None:
        raise InterimError(problem)
    table = pq.read_table(interim / LINES_NAME)
    frame = table.to_pandas(types_mapper=lambda kind: pd.Int64Dtype() if kind == pa.int64() else None)
    return frame.astype({"line_key": "int64", "quantity": "int64"})[list(LINE_COLUMNS)]
