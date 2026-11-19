"""The e-mail file of a round (RF16, AC10; M05; plan section 12; decisions D30, D45; risk item 2).

``write_email_csv`` writes ``outputs/private/email/<round>.csv``: ``contact_id, rank, stock_code, description_es, source`` for the lists of the customers that **receive an offer**, in the order of the
contact and the rank. It is the second way out of the flow (the first is the CRM) and it is held to the same rule: ``holdout.check_deliverable`` (M05) runs before a byte is made, so the control group and
anyone who is not assigned stop it. The file holds customer numbers: it lives in ``outputs/private/``, which git ignores, and is never published (D30).

It is built whole in memory and written with ``files.write_atomic`` (the same bytes for the same round), UTF-8 without a byte-order mark and with ``\\n`` line ends. A description is text of the source and
a spreadsheet runs a cell that starts with ``=``, ``+``, ``-`` or ``@`` as a formula: such a description gets a ``'`` in front, so opening the file in a spreadsheet shows the text and never runs it. A
control character (a tab, a line end) inside a description becomes a space and the ends are trimmed (a bare carriage return is a row break to some readers and the CSV writer does not quote it, and a leading
space or tab would hide a formula from a check that looked at the first character); a comma or a quote is quoted by the CSV writer.
"""

from __future__ import annotations

import csv
import io
import re
import sqlite3
from pathlib import Path
from typing import Any

from personaloffers import holdout
from personaloffers.files import write_atomic

HEADER = ("contact_id", "rank", "stock_code", "description_es", "source")
ROUND = re.compile(r"R[0-9]{4}-[0-9]{2}-[0-9]{2}")
FORMULA_STARTS = ("=", "+", "-", "@")
CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f  ]+")


def _check_round(round_id: str) -> str:
    if not isinstance(round_id, str) or not ROUND.fullmatch(round_id):
        raise ValueError(f"{round_id!r} no es una ronda (R<año>-<mes>-<día>)")
    return round_id


def email_path(private_dir: Path, round_id: str) -> Path:
    """``<private_dir>/email/<round_id>.csv``; the round is checked before the name is made, so it cannot say another folder. Nothing is created."""
    return Path(private_dir) / "email" / f"{_check_round(round_id)}.csv"


def neutralised(text: str | None) -> str:
    """The description as a cell: empty when there is none, free of control characters and with a ``'`` in front when a spreadsheet would read it as a formula."""
    clean = CONTROL.sub(" ", text or "").strip()
    return "'" + clean if clean.startswith(FORMULA_STARTS) else clean


def write_email_csv(conn: sqlite3.Connection, round_id: str, path: Path, view: Any) -> Path:
    """Write the file of `round_id` to `path` and return it. ``ValueError`` when the round has no lists for the offer group, or a list that has not the ``[recommend] k`` products of the plan;
    ``holdout.ControlLeakError`` (M05) when the control group or a customer without an assignment is among them. Nothing is written in any of those cases."""
    _check_round(round_id)
    k = view.recommend.k
    rows = conn.execute(
        "SELECT o.customer_id, o.rank, o.stock_code, p.description_es, o.source FROM offer_lists o LEFT JOIN products p ON p.stock_code = o.stock_code "
        "WHERE o.round_id = ? AND o.grp = 'offer' ORDER BY o.customer_id, o.rank", (round_id,)).fetchall()
    if not rows:
        raise ValueError(f"la ronda {round_id} no existe o no tiene listas para el grupo de oferta: no hay nada que escribir")
    holdout.check_deliverable(conn, {row[0] for row in rows})
    holdout.check_round_groups(conn, round_id)
    sizes: dict[int, int] = {}
    for row in rows:
        sizes[row[0]] = sizes.get(row[0], 0) + 1
    wrong = sum(1 for size in sizes.values() if size != k)
    if wrong:
        raise ValueError(f"{wrong} listas de {round_id} no tienen los {k} productos del plan: no se escribe el archivo")
    text = io.StringIO(newline="")
    writer = csv.writer(text, lineterminator="\n")
    writer.writerow(HEADER)
    for customer, rank, code, description, source in rows:
        writer.writerow((customer, rank, code, neutralised(description), source))
    return write_atomic(Path(path), text.getvalue().encode("utf-8"))
