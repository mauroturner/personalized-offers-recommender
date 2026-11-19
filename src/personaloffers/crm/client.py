"""The CRM client and the delivery of a round (RF15, AC10, AC19, AC20, C09; M05; plan sections 12 and 18; decisions D14, D25; risk items 3 and 2).

``CrmClient`` speaks the API of ``crm/standin.py`` over an ``httpx.Client``: the real one for a CRM that is reached over HTTP (``[crm] mode = "http"``) or the ``TestClient`` of the stand-in in the same
process (``"standin"``), with ``Authorization: Bearer <token>`` in the header of every request and nowhere else. What the CRM refuses, what it does not answer and what it answers differently are the
errors of this module, whose messages never hold the address, a path, a token or a body.

* ``put_offers`` is idempotent: the same batch again is ``unchanged``, a different list for a key that is there is a 409 and nothing of the batch is applied (``BatchResult.conflicts`` counts the contacts
  of that batch). A send whose answer was lost (no answer, or a 5xx) is **sent again once** with the same batch: the CRM answers ``unchanged`` if it had kept it, so nothing is duplicated (the lesson A4 of
  project 07); ``BatchResult.sends`` says how many sends it took.
* ``read_round`` reads the round back page by page in the order of the contact and checks that no contact repeats and none is skipped (the lesson ``0462f72`` of project 07).

``deliver_round`` sends what was **issued** to the customers of the **offer group** and nothing else. Before any request, ``holdout.check_deliverable`` (M05) refuses the control group and anyone without an
assignment. The contacts, in the order of their number, go in batches of ``batch_size``; a batch that was delivered before (an ``ok`` row of ``crm_deliveries`` that was read back equal) is not sent again,
and one that failed is tried again as its next attempt: **a run sends only what is missing**. Then the whole round is read back and compared with what was issued, contact by contact, and what was tried is
written in one transaction (every try is a row, ``failed`` or ``ok``): a read back that could not be done writes no ``ok`` row, so the next run does that batch again. Anything that is not delivered and read back
equal, a contact in the CRM that was not issued for the offer group included, ends in ``CrmDeliveryError`` after the rows are written. ``repeat_round`` sends a delivered round's batches again and writes nothing
(C09: repeating the last round creates no record).
"""

from __future__ import annotations

import json
import os
import re
import secrets
import sqlite3
import time
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, NamedTuple
from urllib.parse import quote

import httpx

from personaloffers import holdout

ROUND = re.compile(r"R[0-9]{4}-[0-9]{2}-[0-9]{2}")
SOURCES = ("repeat", "discovery", "fallback")


class Offer(NamedTuple):
    rank: int
    stock_code: str
    source: str


class ContactOffers(NamedTuple):
    contact_id: int
    offers: tuple[Offer, ...]


class CrmError(RuntimeError):
    """The CRM did not do what was asked. ``status`` is the HTTP status when there was an answer; the message never holds a body, an address, a path or a token."""

    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status, self.sends = status, 1


class CrmAuthError(CrmError):
    """401 or 403: the token is not accepted."""


class CrmRejected(CrmError):
    """The CRM answered that it will not do it (400, 404, 409, 413...)."""


class CrmUnreachable(CrmError):
    """No answer (a connection that failed or timed out), a 5xx or an answer that is not what the plan says."""


class CrmConfigError(ValueError):
    """``[crm]`` cannot be used as it is (no address, no token, an unknown mode); the command line exits with 2 before writing."""

    EXIT_CODE = 2


class CrmDeliveryError(RuntimeError):
    """A round was not delivered and read back equal; ``result`` is what was done (the rows that say it are already written)."""

    def __init__(self, message: str, result: DeliveryResult | None = None) -> None:
        super().__init__(message)
        self.result = result


@dataclass(frozen=True)
class BatchResult:
    created: int
    unchanged: int
    conflicts: int
    sends: int = 1


@dataclass(frozen=True)
class DeliveryResult:
    round_id: str
    contacts: int                 # the customers of the offer group of the round
    batches: int
    created: int
    unchanged: int
    conflicts: int
    skipped: int                  # batches that an earlier run delivered and read back equal: not sent again
    failed: tuple[int, ...]       # the batches that are not delivered and read back equal after this run
    delivered: int                # the contacts of the batches that are
    readback_equal: bool          # every batch is delivered and the CRM holds nothing that was not issued for the offer group
    unexpected: int               # contacts of the CRM's round that were not issued for the offer group
    seconds: float


def _check_round(round_id: str) -> str:
    if not isinstance(round_id, str) or not ROUND.fullmatch(round_id):
        raise ValueError(f"{round_id!r} no es una ronda (R<año>-<mes>-<día>)")
    return round_id


def _wire(contact: ContactOffers) -> dict[str, Any]:
    return {"contact_id": int(contact.contact_id), "offers": [{"rank": int(o.rank), "stock_code": str(o.stock_code), "source": str(o.source)} for o in contact.offers]}


def _contact_of(item: Any) -> ContactOffers:
    try:
        return ContactOffers(int(item["contact_id"]), tuple(Offer(int(o["rank"]), str(o["stock_code"]), str(o["source"])) for o in item["offers"]))
    except (KeyError, TypeError, ValueError):
        raise CrmUnreachable("el CRM contestó algo que no es lo que dice el plan") from None


class CrmClient:
    def __init__(self, http: Any, token: str, *, page_size: int = 500) -> None:
        if not isinstance(token, str) or not token.strip():
            raise CrmConfigError("el cliente del CRM necesita un token")
        if page_size < 1:
            raise CrmConfigError("el tamaño de página debe ser al menos 1")
        self._http, self._headers, self._page_size = http, {"Authorization": f"Bearer {token}", "Accept": "application/json"}, page_size

    # -- the requests ----------------------------------------------------------------------------------------------------------

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        headers = {**self._headers, **kwargs.pop("headers", {})}
        try:
            response = self._http.request(method, path, headers=headers, **kwargs)
        except httpx.HTTPError as error:
            raise CrmUnreachable(f"el CRM no respondió ({type(error).__name__})") from None
        status = response.status_code
        if status in (401, 403):
            raise CrmAuthError(f"el CRM no acepta el token (estado {status})", status)
        if status >= 500:
            raise CrmUnreachable(f"el CRM falló (estado {status})", status)
        if status >= 400:
            raise CrmRejected(f"el CRM rechazó el pedido (estado {status})", status)
        try:
            body = json.loads(response.text)
        except ValueError:
            raise CrmUnreachable("el CRM contestó algo que no es JSON", status) from None
        if not isinstance(body, dict):
            raise CrmUnreachable("el CRM contestó algo que no es lo que dice el plan", status)
        return body

    def health(self) -> bool:
        """True if the CRM answers ``{"status": "ok"}`` to this token; a token it does not accept is a ``CrmAuthError``."""
        return self._request("GET", "/health").get("status") == "ok"

    def put_offers(self, round_id: str, contacts: Sequence[ContactOffers]) -> BatchResult:
        """Send a batch of lists. 200 is ``created`` and ``unchanged``; a 409 (a list that is there is different) is every contact of the batch in ``conflicts``; a send that got no answer or a 5xx is made
        once more with the same body (``sends`` 2) and then it is a ``CrmUnreachable``; any other refusal is a ``CrmRejected`` and is not sent again."""
        path = f"/api/v1/rounds/{quote(_check_round(round_id), safe='')}/offers"
        content = json.dumps({"contacts": [_wire(c) for c in contacts]}, separators=(",", ":"))
        headers = {"Content-Type": "application/json"}
        sends = 1
        while True:
            try:
                body = self._request("PUT", path, content=content, headers=headers)
                break
            except CrmRejected as error:
                if error.status == 409:
                    return BatchResult(0, 0, len(contacts), sends)
                error.sends = sends
                raise
            except CrmUnreachable as error:
                if sends == 2:
                    error.sends = 2
                    raise
                sends = 2
        try:
            return BatchResult(int(body["created"]), int(body["unchanged"]), 0, sends)
        except (KeyError, TypeError, ValueError):
            raise CrmUnreachable("el CRM contestó algo que no es lo que dice el plan") from None

    def read_round(self, round_id: str) -> Iterator[ContactOffers]:
        """Every list of the round, page by page, in the order of the contact. A page that repeats a contact or goes backwards, one that is longer than asked or one that is empty before the total is
        reached is a ``CrmUnreachable`` (the lectura de vuelta is not complete), never a round that looks complete."""
        path = f"/api/v1/rounds/{quote(_check_round(round_id), safe='')}/offers"
        offset, last = 0, 0
        while True:
            body = self._request("GET", path, params={"offset": offset, "limit": self._page_size})
            data, total = body.get("data"), body.get("total")
            if not isinstance(data, list) or type(total) is not int or total < 0 or len(data) > self._page_size:
                raise CrmUnreachable("el CRM contestó una página que no es lo que dice el plan")
            for item in data:
                contact = _contact_of(item)
                if contact.contact_id <= last:
                    raise CrmUnreachable("la lectura de vuelta repite o desordena un contacto")
                last = contact.contact_id
                yield contact
            offset += len(data)
            if offset >= total:
                return
            if not data:
                raise CrmUnreachable("la lectura de vuelta se cortó antes del total que dijo el CRM")

    def read_contact(self, contact_id: int, round_id: str) -> ContactOffers | None:
        """The list of a contact in a round, or None when the CRM has none."""
        path = f"/api/v1/contacts/{int(contact_id)}/offers"
        try:
            body = self._request("GET", path, params={"round_id": _check_round(round_id)})
        except CrmRejected as error:
            if error.status == 404:
                return None
            raise
        return _contact_of(body)


# --- making a client ---------------------------------------------------------------------------------------------------------------


def make_client(crm: Any, paths: Any, *, env: Mapping[str, str] | None = None) -> CrmClient:
    """The client of ``[crm] mode``: ``standin`` is the stand-in over ``[paths] crm_db`` called in this process (its token from ``[crm] token_env`` or, if the variable is not set, one made for this process:
    nobody else can call it); ``http`` is ``[crm] base_url`` with the token of ``token_env`` (``CrmConfigError`` without it), with ``[crm] timeout_s``."""
    environment = os.environ if env is None else env
    token = environment.get(crm.token_env, "")
    if crm.mode == "http":
        if not crm.base_url:
            raise CrmConfigError("[crm] mode = http necesita [crm] base_url")
        if not token.strip():
            raise CrmConfigError(f"[crm] mode = http necesita el token en la variable de entorno {crm.token_env}")
        return CrmClient(httpx.Client(base_url=crm.base_url, timeout=crm.timeout_s), token, page_size=crm.batch_size)
    if crm.mode != "standin":
        raise CrmConfigError(f"[crm] mode: {crm.mode!r} no es standin ni http")
    from fastapi.testclient import TestClient

    from personaloffers.crm.standin import standin_app

    token = token if token.strip() else f"standin-{secrets.token_hex(16)}"
    app = standin_app(paths.crm_db, token, batch_size=crm.batch_size, max_body_bytes=crm.max_body_bytes)
    return CrmClient(TestClient(app, raise_server_exceptions=False, base_url="http://standin"), token, page_size=crm.batch_size)


# --- delivering a round --------------------------------------------------------------------------------------------------------------


def _issued(conn: sqlite3.Connection, round_id: str) -> dict[int, ContactOffers]:
    """The lists the round issued for the offer group, by contact (``offer_lists``, the order of the rank)."""
    issued: dict[int, list[Offer]] = {}
    for customer, rank, code, source in conn.execute("SELECT customer_id, rank, stock_code, source FROM offer_lists WHERE round_id = ? AND grp = 'offer' ORDER BY customer_id, rank", (round_id,)):
        issued.setdefault(customer, []).append(Offer(rank, code, source))
    return {customer: ContactOffers(customer, tuple(offers)) for customer, offers in issued.items()}


def _chunks(items: Sequence[ContactOffers], size: int) -> list[list[ContactOffers]]:
    return [list(items[start:start + size]) for start in range(0, len(items), size)]


def _stored_attempts(conn: sqlite3.Connection, round_id: str) -> tuple[dict[int, int], dict[int, int]]:
    """``({batch: contacts of the batch that was delivered and read back equal}, {batch: its last attempt})`` of what the warehouse has."""
    delivered = {batch: contacts for batch, contacts in conn.execute("SELECT batch, contacts FROM crm_deliveries WHERE round_id = ? AND status = 'ok' AND readback_equal = 1", (round_id,))}
    last = {batch: attempt for batch, attempt in conn.execute("SELECT batch, MAX(attempt) FROM crm_deliveries WHERE round_id = ? GROUP BY batch", (round_id,))}
    return delivered, last


def deliver_round(conn: sqlite3.Connection, client: CrmClient, round_id: str, *, run_key: str, batch_size: int) -> DeliveryResult:
    """Deliver the round `round_id` to the CRM and read it back (see the module). ``holdout.ControlLeakError`` (M05) before any request or row if the control group, or anyone who is not assigned, is in what is to be
    delivered; ``CrmAuthError`` when the token is not accepted (nothing is written: it is not a batch's failure); ``CrmDeliveryError`` after writing the rows when a batch failed, a list is not the issued one or the
    CRM holds a contact that was not issued; a read back that cannot be done is the ``CrmUnreachable`` it got, with the rows of the batches that failed to be sent written and none of the ``ok`` ones."""
    _check_round(round_id)
    if batch_size < 1:
        raise ValueError("batch_size debe ser al menos 1")
    if conn.execute("SELECT 1 FROM rounds WHERE round_id = ?", (round_id,)).fetchone() is None:
        raise CrmDeliveryError(f"la ronda {round_id} no existe en el almacén: no hay nada que entregar")
    started = time.perf_counter()
    issued = _issued(conn, round_id)
    holdout.check_deliverable(conn, issued)
    holdout.check_round_groups(conn, round_id)
    batches = _chunks([issued[c] for c in sorted(issued)], batch_size)
    delivered, last = _stored_attempts(conn, round_id)
    wrong_size = [n for n, size in delivered.items() if n > len(batches) or size != len(batches[n - 1])]
    if wrong_size:
        raise CrmDeliveryError(f"los lotes {sorted(wrong_size)} de {round_id} se entregaron con otro tamaño de lote que {batch_size}: una ronda entregada no se parte de otra forma")

    outcomes: dict[int, tuple[str, BatchResult | CrmError, float]] = {}
    for number, contacts in enumerate(batches, start=1):
        if number in delivered:
            continue
        began = time.perf_counter()
        try:
            outcomes[number] = ("sent", client.put_offers(round_id, contacts), time.perf_counter() - began)
        except (CrmUnreachable, CrmRejected) as error:
            outcomes[number] = ("failed", error, time.perf_counter() - began)

    def row(number: int, status: str, created: int, unchanged: int, conflicts: int, sends: int, equal: int, seconds: float) -> tuple:
        return (round_id, number, last.get(number, 0) + 1, status, len(batches[number - 1]), created, unchanged, conflicts, sends, equal, round(seconds, 6), run_key)

    refused: dict[int, tuple] = {}
    for number, (status, outcome, seconds) in outcomes.items():
        if status == "failed":
            refused[number] = row(number, "failed", 0, 0, 0, outcome.sends, 0, seconds)
        elif outcome.conflicts:
            refused[number] = row(number, "failed", 0, 0, outcome.conflicts, outcome.sends, 0, seconds)
    try:
        held = {c.contact_id: c.offers for c in client.read_round(round_id)}
    except CrmError:
        _write_attempts(conn, list(refused.values()))     # what was not read back is not written as delivered: the next run does those batches again
        raise
    unexpected = len(held.keys() - issued.keys())
    same = {number: all(held.get(c.contact_id) == c.offers for c in contacts) for number, contacts in enumerate(batches, start=1)}
    rows = list(refused.values()) + [row(number, "ok", out.created, out.unchanged, 0, out.sends, int(same[number]), seconds)
                                     for number, (status, out, seconds) in sorted(outcomes.items()) if number not in refused]
    _write_attempts(conn, sorted(rows, key=lambda r: r[1]))
    failed = tuple(number for number in range(1, len(batches) + 1) if number in refused or not same[number])
    result = DeliveryResult(
        round_id, len(issued), len(batches), sum(r[5] for r in rows), sum(r[6] for r in rows), sum(r[7] for r in rows), len(delivered), failed,
        sum(len(batches[n - 1]) for n in range(1, len(batches) + 1) if n not in failed), not failed and not unexpected, unexpected, round(time.perf_counter() - started, 3))
    if not result.readback_equal:
        reasons = []
        if refused:
            reasons.append(f"los lotes {sorted(refused)} no se entregaron" + (" (conflicto: el CRM tiene otra lista para un contacto)" if any(r[7] for r in refused.values()) else ""))
        if set(failed) - set(refused):
            reasons.append(f"la lectura de vuelta de los lotes {sorted(set(failed) - set(refused))} no es la emitida")
        if unexpected:
            reasons.append(f"{unexpected} contactos del CRM no se emitieron para el grupo de oferta")
        raise CrmDeliveryError(f"la ronda {round_id} no quedó entregada y leída de vuelta igual: {'; '.join(reasons)}", result)
    return result


def _write_attempts(conn: sqlite3.Connection, rows: list[tuple]) -> None:
    """The tries of a run, all in one transaction (``crm_deliveries`` is insert-only)."""
    if not rows:
        return
    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.executemany("INSERT INTO crm_deliveries (round_id, batch, attempt, status, contacts, created, unchanged, conflicts, sends, readback_equal, seconds, run_key) "
                         "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", rows)
        conn.execute("COMMIT")
    except BaseException:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise


def repeat_round(conn: sqlite3.Connection, client: CrmClient, round_id: str, *, batch_size: int) -> BatchResult:
    """Send the lists the round issued for the offer group again, in the batches of ``batch_size``, and add up what the CRM answered: on a round that was delivered, nothing is created (C09). It writes nothing
    in the warehouse and checks M05 first, as a delivery does."""
    _check_round(round_id)
    issued = _issued(conn, round_id)
    holdout.check_deliverable(conn, issued)
    holdout.check_round_groups(conn, round_id)
    totals = [client.put_offers(round_id, contacts) for contacts in _chunks([issued[c] for c in sorted(issued)], batch_size)]
    return BatchResult(sum(r.created for r in totals), sum(r.unchanged for r in totals), sum(r.conflicts for r in totals), max((r.sends for r in totals), default=1))

