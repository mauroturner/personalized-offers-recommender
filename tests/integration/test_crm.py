"""The delivery to the CRM (U13; RF15, RF16, AC10, AC19, AC20, C09; M05; plan section 12; decisions D14, D25, D45; risk items 3 and 2): the lists of the offer group, never the control group's, go in
batches that can be repeated, read back page by page and compared with what was issued, and what was tried is written once for each try."""

from __future__ import annotations

import dataclasses
import json
import sqlite3

import httpx
import pytest

from personaloffers import holdout
from personaloffers.crm import client as crm_client
from personaloffers.crm.client import (
    CrmAuthError,
    CrmClient,
    CrmDeliveryError,
    CrmRejected,
    CrmUnreachable,
    ContactOffers,
    Offer,
    deliver_round,
    make_client,
    repeat_round,
)
from personaloffers.email_export import email_path, write_email_csv
from personaloffers.holdout import ControlLeakError
from tests.fixtures.tiny_flow import tiny_warehouse
from tests.fixtures.worlds import copy_world

TOKEN = "integration-token"
ROUNDS = ["R2011-03-28", "R2011-04-04", "R2011-04-11", "R2011-04-18"]
SOURCES = ("repeat", "discovery", "fallback")


class Spy:
    """The HTTP client of the stand-in with a log of the requests and a script of what goes wrong, in order: ``lose`` (the server does it and the answer never comes), ``fail`` (a 500 without doing it),
    ``refuse`` (a 400), ``garbage`` (an answer that is not JSON) or None (as it is). Each scripted action is used by one request that matches `only` (a method and a part of the path)."""

    def __init__(self, http):
        self.http, self.calls, self.script, self.bodies = http, [], [], []

    def script_for(self, *actions, only=("PUT", "/offers")):
        self.script = [(only, action) for action in actions]

    def request(self, method, url, **kwargs):
        self.calls.append((method, url))
        if method == "PUT":
            self.bodies.append(json.loads(kwargs["content"]))
        for index, (only, action) in enumerate(self.script):
            if method == only[0] and only[1] in url:
                del self.script[index]
                if action == "lose":
                    self.http.request(method, url, **kwargs)
                    raise httpx.ReadTimeout("the answer was lost")
                if action == "fail":
                    return httpx.Response(500, json={"code": "internal_error"})
                if action == "refuse":
                    return httpx.Response(400, json={"code": "bad_request"})
                if action == "garbage":
                    return httpx.Response(200, content=b"<html>not what the plan says</html>")
                break
        return self.http.request(method, url, **kwargs)

    def count(self, method, part="/offers"):
        return sum(1 for m, u in self.calls if m == method and part in u)


@pytest.fixture
def world(replayed, workbook, quick_cfg, tmp_path):
    """A copy of the folder in which the launch, the three weekly deliveries and the close ran, with a CRM stand-in of its own (a file in the copy) and a client that logs what it sends."""
    made = copy_world(replayed.root, workbook, quick_cfg, tmp_path / "replayed")
    made.crm = make_client(made.cfg.crm, made.cfg.paths, env={made.cfg.crm.token_env: TOKEN})
    made.spy = Spy(made.crm._http)
    made.client = CrmClient(made.spy, TOKEN, page_size=made.cfg.crm.batch_size)
    yield made
    made.conn.close()


def offer_group(world, round_id):
    return [r[0] for r in world.conn.execute("SELECT customer_id FROM offer_lists WHERE round_id = ? AND grp = 'offer' GROUP BY customer_id ORDER BY customer_id", (round_id,))]


def control_group(world, round_id):
    return [r[0] for r in world.conn.execute("SELECT customer_id FROM offer_lists WHERE round_id = ? AND grp = 'control' GROUP BY customer_id ORDER BY customer_id", (round_id,))]


def emitted(world, round_id):
    return {c: tuple(Offer(r, s, o) for r, s, o in world.conn.execute("SELECT rank, stock_code, source FROM offer_lists WHERE round_id = ? AND customer_id = ? ORDER BY rank", (round_id, c)))
            for c in offer_group(world, round_id)}


def rows(world, round_id):
    return world.conn.execute("SELECT batch, attempt, status, contacts, created, unchanged, conflicts, sends, readback_equal FROM crm_deliveries WHERE round_id = ? ORDER BY batch, attempt", (round_id,)).fetchall()


def deliver(world, round_id="R2011-03-28", run_key="run-4", batch_size=None, client=None):
    return deliver_round(world.conn, client or world.client, round_id, run_key=run_key, batch_size=batch_size or world.cfg.crm.batch_size)


# --- the control group never gets anything (AC10, M05) -----------------------------------------------------------------------------------------


def test_no_control_customer_reaches_the_crm_or_the_email_csv(world):
    """AC10, C09: in every round of the replay the CRM holds exactly the lists of the offer group, as emitted, and the e-mail file has the same customers; the control group has its lists in the warehouse and
    nowhere else."""
    saw_control = 0
    for round_id in ROUNDS:
        result = deliver(world, round_id)
        mine, held = emitted(world, round_id), control_group(world, round_id)
        saw_control += len(held)
        in_crm = {c.contact_id: c.offers for c in world.client.read_round(round_id)}
        assert in_crm == mine and result.delivered == len(mine) and not set(held) & set(in_crm), round_id
        path = write_email_csv(world.conn, round_id, email_path(world.cfg.paths.private_dir, round_id), world.view)
        in_file = {int(line.split(",")[0]) for line in path.read_text(encoding="utf-8").splitlines()[1:]}
        assert in_file == set(mine) and not set(held) & in_file, round_id
    assert saw_control > 0, "the replay has a control group to leave out"


def test_a_control_customer_in_what_is_to_be_delivered_stops_everything_before_a_request_or_a_row(quick_cfg, quick_view, tmp_path):
    """M05: a list that says ``offer`` for a customer the assignments put in the control group, or for one that has no assignment, is refused before any request, any row and any file."""
    cases = (("control", "offer", "grupo de control"), (None, "offer", "no tienen asignación"), ("offer", "control", "dicen un grupo"))
    for assigned, listed, expected in cases:
        conn = tiny_warehouse(tmp_path / f"{assigned}.sqlite", {1: "offer", 2: listed}, {1: "offer", 2: assigned})
        paths = dataclasses.replace(quick_cfg.paths, crm_db=tmp_path / f"crm-{assigned}" / "standin.sqlite")
        spy = Spy(make_client(quick_cfg.crm, paths, env={quick_cfg.crm.token_env: TOKEN})._http)
        with pytest.raises(ControlLeakError, match=expected):
            deliver_round(conn, CrmClient(spy, TOKEN), "R2011-03-28", run_key="run-1", batch_size=500)
        assert spy.calls == [] and conn.execute("SELECT COUNT(*) FROM crm_deliveries").fetchone()[0] == 0, "nothing was sent and nothing was written"
        with pytest.raises(ControlLeakError, match=expected):
            repeat_round(conn, CrmClient(spy, TOKEN), "R2011-03-28", batch_size=500)
        assert spy.calls == []
        with pytest.raises(ControlLeakError, match=expected):
            write_email_csv(conn, "R2011-03-28", tmp_path / f"{assigned}.csv", quick_view)
        assert not (tmp_path / f"{assigned}.csv").exists()
        conn.close()


def test_the_control_group_has_its_lists_in_the_warehouse_and_none_of_them_is_ever_sent(world):
    deliver(world, "R2011-03-28")
    control = control_group(world, "R2011-03-28")
    assert control and world.conn.execute("SELECT COUNT(*) FROM offer_lists WHERE round_id = 'R2011-03-28' AND grp = 'control'").fetchone()[0] == 10 * len(control)
    assert all(world.client.read_contact(c, "R2011-03-28") is None for c in control)


# --- delivering a round ------------------------------------------------------------------------------------------------------


def test_a_round_is_sent_in_batches_in_the_order_of_the_contact_and_each_is_written_as_what_it_was(world):
    result = deliver(world, "R2011-03-28", batch_size=100)
    mine = emitted(world, "R2011-03-28")
    expected = [min(100, len(mine) - 100 * n) for n in range(-(-len(mine) // 100))]
    assert len(expected) >= 2 and result.batches == len(expected) and result.contacts == len(mine)
    assert rows(world, "R2011-03-28") == [(n, 1, "ok", size, size, 0, 0, 1, 1) for n, size in enumerate(expected, start=1)]
    assert (result.created, result.unchanged, result.conflicts, result.skipped, result.failed, result.unexpected) == (len(mine), 0, 0, 0, (), 0)
    assert result.readback_equal and result.delivered == len(mine) and result.seconds >= 0
    assert world.spy.count("PUT") == len(expected)


def test_the_batches_hold_the_contacts_in_the_order_of_their_number_and_each_contact_once(world):
    deliver(world, "R2011-03-28", batch_size=100)
    sent = [[c["contact_id"] for c in body["contacts"]] for body in world.spy.bodies]
    flat = [c for batch in sent for c in batch]
    assert flat == sorted(emitted(world, "R2011-03-28")) and [len(batch) for batch in sent][:-1] == [100] * (len(sent) - 1) and len(sent) >= 3


def test_delivering_a_round_again_sends_nothing_and_writes_nothing_and_reads_back_what_is_there(world):
    first = deliver(world, "R2011-04-04", batch_size=100)
    stored, puts = rows(world, "R2011-04-04"), world.spy.count("PUT")
    again = deliver(world, "R2011-04-04", batch_size=100)
    assert rows(world, "R2011-04-04") == stored and world.spy.count("PUT") == puts, "the batches that are delivered are not sent again"
    assert (again.skipped, again.created, again.unchanged) == (first.batches, 0, 0) and again.readback_equal and again.delivered == first.delivered
    assert world.spy.count("GET") >= 2, "but it reads the round back and compares it"


def test_a_batch_retried_after_a_lost_response_creates_nothing_new(world):
    """AC19, the lesson A4 of project 07: the CRM kept the batch and the answer never came; the same batch is sent again once and answers ``unchanged``, and the CRM has each list once."""
    world.spy.script_for("lose")
    result = deliver(world, "R2011-03-28")
    mine = emitted(world, "R2011-03-28")
    assert world.spy.count("PUT") == 2
    assert rows(world, "R2011-03-28") == [(1, 1, "ok", len(mine), 0, len(mine), 0, 2, 1)], "created 0: the first send did it, the second found it done"
    assert (result.created, result.unchanged, result.readback_equal) == (0, len(mine), True)
    assert {c.contact_id: c.offers for c in world.client.read_round("R2011-03-28")} == mine and sum(1 for _ in world.client.read_round("R2011-03-28")) == len(mine)
    assert repeat_round(world.conn, world.client, "R2011-03-28", batch_size=500).created == 0


def test_a_batch_whose_answer_is_lost_twice_or_that_fails_is_a_failed_attempt_and_the_other_batches_are_still_tried(world):
    mine = emitted(world, "R2011-03-28")
    world.spy.script_for("lose", "lose")                       # the first batch: both sends are lost
    with pytest.raises(CrmDeliveryError, match="lote") as error:
        deliver(world, "R2011-03-28", batch_size=100)
    result = error.value.result
    batches = -(-len(mine) // 100)
    stored = rows(world, "R2011-03-28")
    assert stored[0] == (1, 1, "failed", 100, 0, 0, 0, 2, 0) and [r[2] for r in stored[1:]] == ["ok"] * (batches - 1) and [r[1] for r in stored] == [1] * batches
    assert result.failed == (1,) and not result.readback_equal and result.delivered == len(mine) - 100
    assert world.spy.count("PUT") == 2 + (batches - 1), "every other batch was tried, once"
    # the next run sends only what is missing, as the second attempt of that batch
    before = world.spy.count("PUT")
    again = deliver(world, "R2011-03-28", batch_size=100)
    assert world.spy.count("PUT") == before + 1 and again.skipped == batches - 1 and again.delivered == len(mine) and again.readback_equal
    assert rows(world, "R2011-03-28")[0:2] == [(1, 1, "failed", 100, 0, 0, 0, 2, 0), (1, 2, "ok", 100, 0, 100, 0, 1, 1)], "the CRM had kept the first batch; the second attempt found it unchanged"


def test_a_server_error_or_a_refusal_is_one_failed_batch_and_a_token_it_does_not_accept_is_not(world):
    world.spy.script_for("fail", "fail")
    with pytest.raises(CrmDeliveryError):
        deliver(world, "R2011-03-28")
    assert [r[2:] for r in rows(world, "R2011-03-28")] == [("failed", len(emitted(world, "R2011-03-28")), 0, 0, 0, 2, 0)]
    world.spy.script_for("refuse")
    with pytest.raises(CrmDeliveryError):
        deliver(world, "R2011-03-28")
    assert [r[1:3] for r in rows(world, "R2011-03-28")] == [(1, "failed"), (2, "failed")] and rows(world, "R2011-03-28")[1][7] == 1, "a 400 is not tried again"
    wrong = CrmClient(world.crm._http, "not-the-token")
    count = len(rows(world, "R2011-03-28"))
    with pytest.raises(CrmAuthError):
        deliver(world, "R2011-03-28", client=wrong)
    assert len(rows(world, "R2011-03-28")) == count, "a token that is not accepted is not a batch's failure: nothing is written"


def test_a_list_the_crm_has_different_is_a_conflict_that_changes_nothing_and_fails_the_batch(world):
    mine = emitted(world, "R2011-03-28")
    customer = next(iter(mine))
    other = tuple(Offer(o.rank, f"{int(o.stock_code[:5]) + 1}", o.source) for o in mine[customer])
    assert world.client.put_offers("R2011-03-28", [ContactOffers(customer, other)]).created == 1
    with pytest.raises(CrmDeliveryError, match="conflicto") as error:
        deliver(world, "R2011-03-28")
    assert rows(world, "R2011-03-28") == [(1, 1, "failed", len(mine), 0, 0, len(mine), 1, 0)]
    assert error.value.result.conflicts == len(mine) and error.value.result.created == 0
    assert [c.contact_id for c in world.client.read_round("R2011-03-28")] == [customer], "no other list of the batch was created"


def test_a_read_back_that_differs_is_written_as_not_equal_and_the_batch_is_tried_again(world, monkeypatch):
    mine = emitted(world, "R2011-03-28")
    real = CrmClient.read_round

    def altered(self, round_id):
        for c in real(self, round_id):
            yield ContactOffers(c.contact_id, tuple(reversed(c.offers))) if c.contact_id == min(mine) else c

    monkeypatch.setattr(CrmClient, "read_round", altered)
    with pytest.raises(CrmDeliveryError, match="lectura de vuelta"):
        deliver(world, "R2011-03-28")
    assert rows(world, "R2011-03-28") == [(1, 1, "ok", len(mine), len(mine), 0, 0, 1, 0)]
    monkeypatch.undo()
    again = deliver(world, "R2011-03-28")
    assert [r[:3] + r[8:] for r in rows(world, "R2011-03-28")] == [(1, 1, "ok", 0), (1, 2, "ok", 1)] and again.readback_equal and again.skipped == 0
    assert rows(world, "R2011-03-28")[1][5] == len(mine), "sent again, unchanged"


def test_a_contact_in_the_crm_that_was_not_emitted_for_the_offer_group_is_unexpected_and_fails_the_round(world):
    mine = emitted(world, "R2011-03-28")
    stranger = max(mine) + 1000
    world.client.put_offers("R2011-03-28", [ContactOffers(stranger, next(iter(mine.values())))])
    with pytest.raises(CrmDeliveryError, match="no se emitieron") as error:
        deliver(world, "R2011-03-28")
    assert error.value.result.unexpected == 1 and not error.value.result.readback_equal


def test_a_read_back_that_cannot_be_done_leaves_the_batches_unwritten_so_the_next_run_does_them(world, monkeypatch):
    def broken(self, round_id):
        raise CrmUnreachable("the CRM did not answer")
        yield  # pragma: no cover

    monkeypatch.setattr(CrmClient, "read_round", broken)
    with pytest.raises(CrmUnreachable):
        deliver(world, "R2011-03-28")
    assert rows(world, "R2011-03-28") == [], "what was not read back is not written as delivered"
    monkeypatch.undo()
    assert deliver(world, "R2011-03-28").delivered == len(emitted(world, "R2011-03-28"))
    assert [r[2] for r in rows(world, "R2011-03-28")] == ["ok"]


def test_the_batches_that_failed_are_written_even_when_the_read_back_cannot_be_done_and_the_others_are_not(world, monkeypatch):
    world.spy.script_for("fail", "fail")                       # the first batch fails on both sends

    def broken(self, round_id):
        raise CrmUnreachable("the CRM did not answer")
        yield  # pragma: no cover

    monkeypatch.setattr(CrmClient, "read_round", broken)
    with pytest.raises(CrmUnreachable):
        deliver(world, "R2011-03-28", batch_size=100)
    assert [(r[0], r[2], r[7]) for r in rows(world, "R2011-03-28")] == [(1, "failed", 2)], "the failed batch is the only row: the batches that were sent were not read back, so they are not written"


def test_the_batches_of_another_size_than_the_ones_already_delivered_are_refused_before_a_request(world):
    deliver(world, "R2011-03-28", batch_size=100)
    puts = world.spy.count("PUT")
    with pytest.raises(CrmDeliveryError, match="tamaño"):
        deliver(world, "R2011-03-28", batch_size=50)
    assert world.spy.count("PUT") == puts and len(rows(world, "R2011-03-28")) == -(-len(emitted(world, "R2011-03-28")) // 100)


def test_a_round_that_does_not_exist_or_is_not_a_round_is_refused_before_a_request(world):
    with pytest.raises(CrmDeliveryError, match="no existe"):
        deliver(world, "R2011-09-05")
    with pytest.raises(ValueError, match="ronda"):
        deliver(world, "../escape")
    assert world.spy.calls == []


def test_repeating_the_last_round_creates_no_record_in_the_crm(world):
    """C09: after the round is delivered, sending its batches again changes nothing: every contact is ``unchanged``."""
    deliver(world, "R2011-04-18")
    mine = emitted(world, "R2011-04-18")
    again = repeat_round(world.conn, world.client, "R2011-04-18", batch_size=100)
    assert (again.created, again.unchanged, again.conflicts) == (0, len(mine), 0)
    assert sum(1 for _ in world.client.read_round("R2011-04-18")) == len(mine)
    before = world.conn.execute("SELECT COUNT(*) FROM crm_deliveries").fetchone()[0]
    repeat_round(world.conn, world.client, "R2011-04-18", batch_size=100)
    assert world.conn.execute("SELECT COUNT(*) FROM crm_deliveries").fetchone()[0] == before, "the proof of a repeat writes nothing in the warehouse"


# --- reading back page by page (the lesson 0462f72 of project 07) ---------------------------------------------------------------------------


def test_readback_over_three_pages_has_no_repeat_and_no_gap(world):
    mine = emitted(world, "R2011-03-28")
    assert len(mine) > 2 * 100
    deliver(world, "R2011-03-28", batch_size=100)
    paged = CrmClient(world.spy, TOKEN, page_size=100)
    gets = world.spy.count("GET")
    found = list(paged.read_round("R2011-03-28"))
    pages = -(-len(mine) // 100)
    assert pages >= 3 and world.spy.count("GET") - gets == pages, "it asked page after page until the round was complete"
    assert [c.contact_id for c in found] == sorted(mine), "in the order of the contact, no repeat and no gap"
    assert {c.contact_id: c.offers for c in found} == mine
    tiny = CrmClient(world.spy, TOKEN, page_size=7)
    assert [c.contact_id for c in tiny.read_round("R2011-03-28")] == sorted(mine)


def test_a_page_that_repeats_a_contact_or_stops_short_is_an_error_and_not_a_complete_round(world):
    deliver(world, "R2011-03-28")
    real = world.spy.request

    class Short:
        def __init__(self, mode):
            self.mode = mode

        def request(self, method, url, **kwargs):
            response = real(method, url, **kwargs)
            if method != "GET" or "/offers" not in url or "contacts" in url:
                return response
            body = response.json()
            offset = int(kwargs["params"]["offset"])
            if self.mode == "repeat" and offset > 0:
                body["data"] = [body["data"][0]] + body["data"]
                body["data"] = body["data"][: kwargs["params"]["limit"]]
            if self.mode == "short" and offset > 0:
                body["data"] = []
            return httpx.Response(200, json=body)

    for mode in ("repeat", "short"):
        with pytest.raises(CrmUnreachable, match="lectura de vuelta"):
            list(CrmClient(Short(mode), TOKEN, page_size=100).read_round("R2011-03-28"))


# --- the token and what an error says (AC20) ---------------------------------------------------------------------------------------------------


def test_every_request_without_the_token_is_401_and_no_error_carries_a_path(world):
    """AC20: the client says what happened and never holds the address, the path or the token; the 401 is the same for every route."""
    stranger = CrmClient(world.crm._http, "not-the-token")
    calls = [lambda: stranger.put_offers("R2011-03-28", [ContactOffers(1, (Offer(1, "95000", "repeat"),))]), lambda: list(stranger.read_round("R2011-03-28")),
             lambda: stranger.read_contact(1, "R2011-03-28"), stranger.health]
    for call in calls:
        with pytest.raises(CrmAuthError) as error:
            call()
        for text in ("not-the-token", TOKEN, "/api", "http", "R2011-03-28", "offers", "standin"):
            assert text not in str(error.value), (text, str(error.value))
    assert world.client.health() is True
    raw = world.crm._http.get("/health")
    assert raw.status_code == 401 and raw.json() == {"code": "unauthorized"}


def test_the_token_goes_in_the_header_of_every_request_and_in_no_other_place(world):
    deliver(world, "R2011-03-28")
    seen = []
    real = world.crm._http.request

    def log(method, url, **kwargs):
        seen.append((method, url, kwargs))
        return real(method, url, **kwargs)

    world.crm._http.request = log
    world.client.read_contact(1, "R2011-03-28")
    list(world.client.read_round("R2011-03-28"))
    world.client.health()
    deliver(world, "R2011-03-28")
    assert seen and all(kwargs["headers"]["Authorization"] == f"Bearer {TOKEN}" for _m, _u, kwargs in seen)
    assert all(TOKEN not in url and TOKEN not in json.dumps({k: v for k, v in kwargs.items() if k != "headers"}, default=str) for _m, url, kwargs in seen)


# --- the client ---------------------------------------------------------------------------------------------------------------


def test_a_client_without_a_token_or_with_a_round_that_is_not_one_is_not_made_or_does_not_ask(world):
    for token in ("", " ", None):
        with pytest.raises(crm_client.CrmConfigError, match="token"):
            CrmClient(world.crm._http, token)
    before = len(world.spy.calls)
    for bad in ("x", "R2011-3-28", "R2011-03-28/../x", "R2011-03-28?x=1"):
        with pytest.raises(ValueError, match="ronda"):
            world.client.put_offers(bad, [])
        with pytest.raises(ValueError, match="ronda"):
            list(world.client.read_round(bad))
        with pytest.raises(ValueError, match="ronda"):
            world.client.read_contact(1, bad)
    assert len(world.spy.calls) == before, "no request was made"


def test_an_answer_that_is_not_what_the_plan_says_is_unreachable_and_never_a_crash(world):
    world.spy.script_for("garbage", only=("GET", "/health"))
    with pytest.raises(CrmUnreachable, match="contestó"):
        world.client.health()
    world.spy.script_for("garbage", only=("GET", "/offers"))
    with pytest.raises(CrmUnreachable, match="contestó"):
        list(world.client.read_round("R2011-03-28"))


def test_the_http_mode_needs_an_address_and_a_token_and_the_stand_in_mode_works_without_one(world, tmp_path):
    cfg = world.cfg
    with pytest.raises(crm_client.CrmConfigError, match="base_url"):
        make_client(dataclasses.replace(cfg.crm, mode="http", base_url=""), cfg.paths, env={cfg.crm.token_env: TOKEN})
    with pytest.raises(crm_client.CrmConfigError, match=cfg.crm.token_env):
        make_client(dataclasses.replace(cfg.crm, mode="http", base_url="http://crm:8001"), cfg.paths, env={})
    with pytest.raises(crm_client.CrmConfigError, match="mode"):
        make_client(dataclasses.replace(cfg.crm, mode="ftp"), cfg.paths, env={cfg.crm.token_env: TOKEN})
    http_client = make_client(dataclasses.replace(cfg.crm, mode="http", base_url="http://crm:8001"), cfg.paths, env={cfg.crm.token_env: TOKEN})
    assert str(http_client._http.base_url).startswith("http://crm:8001") and http_client._http.timeout.read == cfg.crm.timeout_s
    alone = make_client(cfg.crm, dataclasses.replace(cfg.paths, crm_db=tmp_path / "alone" / "crm.sqlite"), env={})
    assert alone.health() is True, "in process the token of the process is made when the variable is not set"


def test_a_batch_larger_than_the_configuration_allows_is_refused_by_the_crm_and_not_split_by_the_client(world, tmp_path):
    small = make_client(dataclasses.replace(world.cfg.crm, batch_size=5), dataclasses.replace(world.cfg.paths, crm_db=tmp_path / "small" / "standin.sqlite"), env={world.cfg.crm.token_env: TOKEN})
    spy = Spy(small._http)
    contacts = [ContactOffers(c, offers) for c, offers in list(emitted(world, "R2011-03-28").items())[:6]]
    with pytest.raises(CrmRejected):
        CrmClient(spy, TOKEN, page_size=5).put_offers("R2011-03-28", contacts)
    assert spy.count("PUT") == 1 and list(CrmClient(spy, TOKEN, page_size=5).read_round("R2011-03-28")) == []


# --- the table is the record of what was tried (U06's insert-only rule) -------------------------------------------------------------------


def test_what_was_tried_is_written_once_and_the_table_refuses_a_change(world):
    deliver(world, "R2011-03-28")
    with pytest.raises(sqlite3.DatabaseError, match="solo inserción"):
        world.conn.execute("UPDATE crm_deliveries SET readback_equal = 0")
    with pytest.raises(sqlite3.DatabaseError, match="solo inserción"):
        world.conn.execute("DELETE FROM crm_deliveries")
    assert world.conn.execute("SELECT run_key FROM crm_deliveries").fetchall() == [("run-4",)]
    assert holdout.read_assignments(world.conn)["grp"].isin(["offer", "control"]).all()
