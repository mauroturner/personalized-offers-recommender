"""The plan of deliveries, their publication and their manifest (RF05, RF06; plan sections 3 and 6; decisions D05 and D22).

The archive is given to the flow as a simulated operation: a **launch** (``L<last day of the history>``: every line from the first day of the history to
``launch_last_day``), one **weekly** delivery for each test round (``W<Monday>``: the lines of that week, Monday to Sunday) and a **close** (``C<first day of the
close>``: the five days of the censored round). ``delivery_plan`` reads only ``[calendar]``; the deliveries are consecutive, so a line is in the delivery of its date and
in no other, and ``split_lines`` refuses a line that no delivery covers instead of dropping it.

A delivery is published to ``data/raw/deliveries/<id>/lines.parquet`` (the canonical lines of its period, with their role) and the manifest of the folder,
``manifest.json``, is written last, atomically: a failure between the two leaves a file the manifest does not know, which is still pending and is published again with the
same bytes. The manifest holds, for each published delivery, its kind, its days, its ``as_of``, its rows and the SHA-256 of its file; it is read strictly. Whether a
delivery was *loaded* is the warehouse's to say (``deliveries.status``), not the manifest's.
"""

from __future__ import annotations

import json
import re
from collections.abc import Collection
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any

import pandas as pd
import pyarrow.parquet as pq

from personaloffers import workbook as wb
from personaloffers.calendar import rounds
from personaloffers.files import atomic_path, sha256_file, write_atomic

MANIFEST_NAME = "manifest.json"
DELIVERY_FILE = "lines.parquet"
DELIVERIES_FOLDER = "deliveries"
MANIFEST_VERSION = 1
KINDS = ("launch", "weekly", "close")
ENTRY_KEYS = {"kind", "first_day", "last_day", "as_of", "rows", "sha256"}
_HEX64 = re.compile(r"[0-9a-f]{64}")


@dataclass(frozen=True)
class DeliverySpec:
    """One delivery of the plan: its identifier and kind, the days it holds (both included) and the instant from which what it brings is known (``as_of``)."""

    delivery_id: str
    kind: str            # launch, weekly or close
    first_day: date
    last_day: date
    as_of: datetime

    @property
    def start(self) -> datetime:
        return datetime.combine(self.first_day, time.min)

    @property
    def end(self) -> datetime:
        """The midnight after the last day: a line is in the delivery when ``start <= invoice_date < end``."""
        return datetime.combine(self.last_day + timedelta(days=1), time.min)


def delivery_plan(view: Any) -> list[DeliverySpec]:
    """The launch, one weekly delivery for each round of the test and the close, in the order they are made."""
    c = view.calendar
    midnight = lambda day: datetime.combine(day, time.min)   # noqa: E731
    plan = [DeliverySpec(f"L{c.launch_last_day.isoformat()}", "launch", c.history_start, c.launch_last_day, midnight(c.launch_last_day + timedelta(days=1)))]
    for monday in rounds(view, "test"):
        plan.append(DeliverySpec(f"W{monday.isoformat()}", "weekly", monday, monday + timedelta(days=6), midnight(monday + timedelta(days=7))))
    plan.append(DeliverySpec(f"C{c.close_first_day.isoformat()}", "close", c.close_first_day, c.close_last_day, midnight(c.close_last_day + timedelta(days=1))))
    return plan


def lines_of(lines: pd.DataFrame, spec: DeliverySpec) -> pd.DataFrame:
    """The lines of `lines` that are in the delivery `spec` by their date (a new frame; the order is kept)."""
    stamps = lines["invoice_date"]
    return lines[(stamps >= spec.start) & (stamps < spec.end)]


def split_lines(lines: pd.DataFrame, plan: list[DeliverySpec]) -> dict[str, pd.DataFrame]:
    """Every delivery of the plan with its lines. A line that no delivery covers is a ``ValueError`` that says its day: the plan and the source disagree, and a line
    dropped here would be a purchase nobody ever sees."""
    covered = pd.Series(False, index=lines.index)
    parts: dict[str, pd.DataFrame] = {}
    for spec in plan:
        stamps = lines["invoice_date"]
        mask = (stamps >= spec.start) & (stamps < spec.end)
        covered |= mask
        parts[spec.delivery_id] = lines[mask]
    if not covered.all():
        first = lines.loc[~covered, "invoice_date"].min()
        raise ValueError(f"{int((~covered).sum())} líneas no están en ninguna entrega del plan (la primera, del {first.date().isoformat()}): el calendario no cubre el archivo")
    return parts


# --- the manifest -------------------------------------------------------------------------------------------------------------------


def _valid_entry(entry: Any) -> bool:
    try:
        return (isinstance(entry, dict) and set(entry) == ENTRY_KEYS and entry["kind"] in KINDS
                and isinstance(entry["first_day"], str) and date.fromisoformat(entry["first_day"]).isoformat() == entry["first_day"]
                and isinstance(entry["last_day"], str) and date.fromisoformat(entry["last_day"]).isoformat() == entry["last_day"]
                and isinstance(entry["as_of"], str) and datetime.fromisoformat(entry["as_of"]).isoformat() == entry["as_of"]
                and isinstance(entry["rows"], int) and not isinstance(entry["rows"], bool) and entry["rows"] >= 0
                and isinstance(entry["sha256"], str) and _HEX64.fullmatch(entry["sha256"]) is not None)
    except ValueError:
        return False


def _check(manifest: Any, where: str) -> dict[str, Any]:
    if not (isinstance(manifest, dict) and set(manifest) == {"version", "deliveries"} and manifest["version"] == MANIFEST_VERSION and isinstance(manifest["deliveries"], dict)
            and all(isinstance(name, str) and _valid_entry(entry) for name, entry in manifest["deliveries"].items())):
        raise ValueError(f"{where} no es un manifiesto de entregas válido (se esperaba {{version: {MANIFEST_VERSION}, deliveries: {{id: {{{', '.join(sorted(ENTRY_KEYS))}}}}}}})")
    return manifest


def read_manifest(path: Path) -> dict[str, Any]:
    """The manifest at `path`; none yet is ``{version, deliveries: {}}``; anything that is not the exact shape is a ``ValueError``."""
    path = Path(path)
    if not path.exists():
        return {"version": MANIFEST_VERSION, "deliveries": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise ValueError(f"el manifiesto {path.name} no se puede leer como JSON") from error
    return _check(data, f"el manifiesto {path.name}")


def write_manifest(path: Path, manifest: dict[str, Any]) -> None:
    """Write the manifest atomically with sorted keys; one of another shape is refused and the file is left as it was."""
    _check(manifest, "el manifiesto que se iba a escribir")
    write_atomic(Path(path), json.dumps(manifest, indent=2, sort_keys=True) + "\n")


def deliveries_dir(cfg: Any) -> Path:
    """``data/raw/deliveries``: where the deliveries and their manifest are."""
    return Path(cfg.paths.raw_dir) / DELIVERIES_FOLDER


def delivery_path(cfg: Any, spec: DeliverySpec) -> Path:
    return deliveries_dir(cfg) / spec.delivery_id / DELIVERY_FILE


def manifest_path_of(delivery_file: Path) -> Path:
    """The manifest that goes with a delivery file: the one in the folder above its own."""
    return Path(delivery_file).parent.parent / MANIFEST_NAME


# --- publication --------------------------------------------------------------------------------------------------------------------


def publish_frame(cfg: Any, spec: DeliverySpec, frame: pd.DataFrame) -> dict[str, Any]:
    """Write `frame` as the file of the delivery `spec` and then its entry in the manifest (written last, atomically); returns the entry. The same frame gives the same
    bytes, so publishing again changes nothing. ``publish_delivery`` is this with the lines of the delivery; a test that needs a delivery that is wrong calls this one."""
    target = delivery_path(cfg, spec)
    table = wb.table_of(frame)
    metadata = {**(table.schema.metadata or {}), b"personaloffers.delivery_id": spec.delivery_id.encode("ascii"), b"personaloffers.attribution": wb.ATTRIBUTION.encode("utf-8")}
    with atomic_path(target) as temporary:
        pq.write_table(table.replace_schema_metadata(metadata), temporary)
    entry = {"kind": spec.kind, "first_day": spec.first_day.isoformat(), "last_day": spec.last_day.isoformat(), "as_of": spec.as_of.isoformat(), "rows": len(frame),
             "sha256": sha256_file(target)}
    manifest_file = deliveries_dir(cfg) / MANIFEST_NAME
    manifest = read_manifest(manifest_file)
    manifest["deliveries"][spec.delivery_id] = entry
    write_manifest(manifest_file, manifest)
    return entry


def publish_delivery(cfg: Any, lines: pd.DataFrame, spec: DeliverySpec) -> dict[str, Any]:
    """Publish the delivery `spec`: the lines of `lines` that are in its days, in their order."""
    return publish_frame(cfg, spec, lines_of(lines, spec).reset_index(drop=True))


def read_delivery(path: Path) -> pd.DataFrame:
    """The lines of a delivery file (``LINE_COLUMNS``). The file's hash and schema are the validation's to judge (V11), not this function's."""
    return wb.frame_of(pq.read_table(Path(path)))


# --- what is pending ----------------------------------------------------------------------------------------------------------------


def next_pending(manifest: dict[str, Any], plan: list[DeliverySpec]) -> DeliverySpec | None:
    """The first delivery of the plan that was not published (a later one that was does not hide it), or None when all were."""
    done = manifest["deliveries"]
    return next((spec for spec in plan if spec.delivery_id not in done), None)


def next_to_load(plan: list[DeliverySpec], loaded: Collection[str]) -> DeliverySpec | None:
    """The first delivery of the plan that is not loaded in the warehouse, which is the only one that V10 accepts."""
    return next((spec for spec in plan if spec.delivery_id not in loaded), None)
