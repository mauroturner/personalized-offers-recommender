"""The CRM stand-in (U13; AC19, AC20; plan section 18; decisions D25, D27; risk items 2 and 3): FastAPI over SQLite with the API of the plan, the token compared with ``hmac.compare_digest`` and
asked for before the route is looked at, one fixed word for each error and never a path, a trace or what was sent, a list that was issued never changes, and nothing but the routes of the plan."""

from __future__ import annotations

import dataclasses
import inspect
import json
import sqlite3

import pytest
from fastapi.testclient import TestClient

from personaloffers.crm import standin
from personaloffers.crm.standin import create_app, create_app_from_environment, standin_app

TOKEN = "s3cret-token-of-the-tests"
AUTH = {"Authorization": f"Bearer {TOKEN}"}
ROUND = "R2011-03-28"
JSON = {"Content-Type": "application/json"}
SOURCES = ("repeat", "discovery", "fallback")


def offers(seed: int = 0, count: int = 10) -> list[dict]:
    return [{"rank": rank, "stock_code": f"{95000 + 12 * ((seed + rank) % 40)}", "source": SOURCES[min(rank // 4, 2)]} for rank in range(1, count + 1)]


def batch(contacts: range | list[int], seed: int = 0) -> dict:
    return {"contacts": [{"contact_id": c, "offers": offers(seed + c)} for c in contacts]}


@pytest.fixture
def http(tmp_path):
    return TestClient(standin_app(tmp_path / "crm" / "standin.sqlite", TOKEN, batch_size=5, max_body_bytes=20_000), raise_server_exceptions=False)


def put(http, body, round_id=ROUND, headers=AUTH):
    return http.put(f"/api/v1/rounds/{round_id}/offers", content=body if isinstance(body, bytes) else json.dumps(body), headers={**headers, **JSON})


# --- the token ---------------------------------------------------------------------------------------------------------------


def test_every_request_without_the_token_is_401_and_says_nothing_of_the_server(http):
    """AC20: no token, another token, another scheme, an empty or a malformed header: 401 on every route and method, on a route that exists and on one that does not, before the route is looked at."""
    put(http, batch([1]))
    requests = [("GET", "/health"), ("PUT", f"/api/v1/rounds/{ROUND}/offers"), ("GET", f"/api/v1/rounds/{ROUND}/offers"), ("GET", f"/api/v1/contacts/1/offers?round_id={ROUND}"),
                ("GET", "/api/v1/nothing"), ("GET", "/etc/passwd"), ("DELETE", f"/api/v1/rounds/{ROUND}/offers"), ("GET", "/"), ("GET", "/docs"), ("GET", "/openapi.json"),
                ("GET", "/api/v1/rounds/not-a-round/offers")]
    bad = [{}, {"Authorization": ""}, {"Authorization": "Bearer"}, {"Authorization": "Bearer wrong"}, {"Authorization": f"Token {TOKEN}"}, {"Authorization": f"Bearer  {TOKEN}"},
           {"Authorization": f"bearer {TOKEN}"}, {"Authorization": f"Bearer {TOKEN} "}, {"Authorization": f"Bearer {TOKEN}x"}, {"Authorization": f"Bearer {TOKEN[:-1]}"},
           {"Authorization": "Basic czNjcmV0LXRva2Vu"}]
    for method, path in requests:
        for headers in bad:
            response = http.request(method, path, headers=headers)
            assert response.status_code == 401, (method, path, headers)
            assert response.json() == {"code": "unauthorized"} and response.headers["www-authenticate"] == "Bearer"
            assert path.split("?")[0] not in response.text and "Traceback" not in response.text
    assert http.get("/health", headers=AUTH).status_code == 200


def test_the_token_is_compared_in_constant_time_before_anything_else(http, monkeypatch):
    """Every request, with a token and without one, goes through ``hmac.compare_digest`` (spied), and the module never compares the header with ``==``."""
    calls = []
    real = standin.hmac.compare_digest
    monkeypatch.setattr(standin.hmac, "compare_digest", lambda a, b: (calls.append((a, b)), real(a, b))[1])
    http.get("/health", headers=AUTH)
    http.get("/health")
    http.get("/anything-else")
    assert len(calls) == 3 and calls[0][0] == calls[0][1] == f"Bearer {TOKEN}".encode() and calls[1][0] == b"" and calls[2][0] == b""
    source = inspect.getsource(standin)
    assert "supplied ==" not in source and "supplied !=" not in source and "== expected" not in source and "!= expected" not in source


def test_an_app_without_a_token_does_not_start(tmp_path):
    for token in ("", None, " ", "\t"):
        with pytest.raises(ValueError, match="token"):
            standin_app(tmp_path / "x.sqlite", token)
    assert not (tmp_path / "x.sqlite").exists(), "it did not even create its file"


def test_the_token_is_the_one_the_app_was_given_and_not_the_one_of_the_file(tmp_path):
    path = tmp_path / "crm" / "standin.sqlite"
    first = TestClient(standin_app(path, TOKEN))
    assert put(first, batch([1])).status_code == 200
    other = TestClient(standin_app(path, "another-token"))
    assert other.get("/health", headers=AUTH).status_code == 401
    assert other.get("/health", headers={"Authorization": "Bearer another-token"}).status_code == 200


# --- putting and reading lists ------------------------------------------------------------------------------------------------


def test_a_put_creates_the_lists_and_the_same_put_again_changes_nothing(http):
    first = put(http, batch([3, 1, 2]))
    assert first.status_code == 200 and first.json() == {"created": 3, "unchanged": 0}
    second = put(http, batch([1, 2, 3]))
    assert second.status_code == 200 and second.json() == {"created": 0, "unchanged": 3}, "a list that is already there with the same offers is unchanged, whatever the order of the batch"
    mixed = put(http, batch([2, 3, 4, 5]))
    assert mixed.json() == {"created": 2, "unchanged": 2}
    read = http.get(f"/api/v1/rounds/{ROUND}/offers", headers=AUTH)
    assert read.status_code == 200 and read.json()["total"] == 5
    assert [row["contact_id"] for row in read.json()["data"]] == [1, 2, 3, 4, 5], "in the order of the contact"
    assert read.json()["data"][0] == {"contact_id": 1, "offers": offers(1)}


def test_a_different_list_for_a_key_that_is_there_is_409_and_nothing_of_the_batch_changes(http):
    put(http, batch([1, 2]))
    before = http.get(f"/api/v1/rounds/{ROUND}/offers", headers=AUTH).json()
    mixed = {"contacts": [{"contact_id": 3, "offers": offers(3)}, {"contact_id": 2, "offers": offers(99)}, {"contact_id": 4, "offers": offers(4)}]}
    refused = put(http, mixed)
    assert refused.status_code == 409 and refused.json() == {"code": "list_conflict"}
    assert http.get(f"/api/v1/rounds/{ROUND}/offers", headers=AUTH).json() == before, "contacts 3 and 4 were not created either: the batch is applied whole or not at all"
    assert put(http, batch([1, 2])).json() == {"created": 0, "unchanged": 2}
    shorter = offers(2)[:9]
    reordered = [{**o, "rank": rank} for rank, o in enumerate(reversed(offers(2)), start=1)]
    for different in (shorter, reordered):
        assert put(http, {"contacts": [{"contact_id": 2, "offers": different}]}).status_code == 409


def test_the_same_contact_in_another_round_is_another_list(http):
    assert put(http, batch([1], seed=0)).json() == {"created": 1, "unchanged": 0}
    assert put(http, batch([1], seed=7), round_id="R2011-04-04").json() == {"created": 1, "unchanged": 0}
    assert http.get("/api/v1/contacts/1/offers?round_id=R2011-04-04", headers=AUTH).json() == {"contact_id": 1, "offers": offers(8)}
    assert http.get(f"/api/v1/contacts/1/offers?round_id={ROUND}", headers=AUTH).json() == {"contact_id": 1, "offers": offers(1)}


def test_a_page_is_read_by_offset_and_limit_in_the_order_of_the_contact(http):
    for start in (1, 6, 11):
        put(http, batch(range(start, start + 5)))
    pages = [http.get(f"/api/v1/rounds/{ROUND}/offers?offset={offset}&limit=5", headers=AUTH).json() for offset in (0, 5, 10, 15)]
    assert [len(page["data"]) for page in pages] == [5, 5, 5, 0] and {page["total"] for page in pages} == {15}
    assert [row["contact_id"] for page in pages for row in page["data"]] == list(range(1, 16))
    assert [row["contact_id"] for row in http.get(f"/api/v1/rounds/{ROUND}/offers?offset=13&limit=5", headers=AUTH).json()["data"]] == [14, 15]
    default = http.get(f"/api/v1/rounds/{ROUND}/offers", headers=AUTH).json()
    assert len(default["data"]) == 5 and default["total"] == 15, "the default page is the batch size"
    empty = http.get("/api/v1/rounds/R2011-09-05/offers", headers=AUTH)
    assert empty.status_code == 200 and empty.json() == {"data": [], "total": 0}


@pytest.mark.parametrize("query", ["offset=-1", "offset=x", "offset=1.5", "limit=0", "limit=6", "limit=-3", "limit=abc", "offset=", "limit="])
def test_an_offset_or_a_limit_that_is_not_a_whole_number_in_range_is_400(http, query):
    put(http, batch([1]))
    response = http.get(f"/api/v1/rounds/{ROUND}/offers?{query}", headers=AUTH)
    assert response.status_code == 400 and response.json() == {"code": "bad_request"}


def test_the_list_of_one_contact_needs_its_round_and_says_not_found_when_it_has_none(http):
    put(http, batch([1]))
    assert http.get("/api/v1/contacts/1/offers", headers=AUTH).status_code == 400
    assert http.get(f"/api/v1/contacts/2/offers?round_id={ROUND}", headers=AUTH).json() == {"code": "not_found"}
    assert http.get("/api/v1/contacts/1/offers?round_id=R2011-04-04", headers=AUTH).status_code == 404
    for contact in ("x", "-1", "1.5", "0x10", "١", "9" * 30):
        assert http.get(f"/api/v1/contacts/{contact}/offers?round_id={ROUND}", headers=AUTH).status_code == 404, contact


def test_the_health_check_answers_ok_with_the_token(http):
    assert http.get("/health", headers=AUTH).json() == {"status": "ok"}


# --- what is refused ---------------------------------------------------------------------------------------------------------


def contact(contact_id=1, listed=None):
    seed = contact_id if type(contact_id) is int and abs(contact_id) < 10**6 else 1
    return {"contact_id": contact_id, "offers": offers(seed) if listed is None else listed}


BAD_BODIES = {
    "not json": b"{not json", "not an object": b"[]", "no contacts": b"{}", "contacts is not a list": {"contacts": {}}, "empty": {"contacts": []},
    "more than a batch": {"contacts": [contact(i) for i in range(1, 7)]}, "an extra key of the body": {"contacts": [contact()], "round": "R2011-03-28"},
    "an extra key of a contact": {"contacts": [{**contact(), "name": "x"}]}, "contact_id missing": {"contacts": [{"offers": offers()}]},
    "contact_id is a string": {"contacts": [contact("1")]}, "contact_id is a float": {"contacts": [contact(1.0)]}, "contact_id is a bool": {"contacts": [contact(True)]},
    "contact_id is zero": {"contacts": [contact(0)]}, "contact_id is negative": {"contacts": [contact(-4)]}, "contact_id is huge": {"contacts": [contact(10**19)]},
    "the same contact twice": {"contacts": [contact(1), contact(1)]}, "offers missing": {"contacts": [{"contact_id": 1}]}, "offers empty": {"contacts": [contact(1, [])]},
    "offers not a list": {"contacts": [contact(1, {})]}, "too many offers": {"contacts": [contact(1, [{"rank": r, "stock_code": f"A{r}", "source": "repeat"} for r in range(1, 52)])]},
    "a rank that is missing": {"contacts": [contact(1, [{**o, "rank": o["rank"] + 1} for o in offers()])]},
    "a rank twice": {"contacts": [contact(1, [{**o, "rank": 1} for o in offers()])]}, "a rank as text": {"contacts": [contact(1, [{**offers()[0], "rank": "1"}, *offers()[1:]])]},
    "a rank as a bool": {"contacts": [contact(1, [{**offers()[0], "rank": True}, *offers()[1:]])]},
    "a product twice": {"contacts": [contact(1, [offers()[0], {**offers()[1], "stock_code": offers()[0]["stock_code"]}])]},
    "a source nobody defined": {"contacts": [contact(1, [{**offers()[0], "source": "guess"}])]}, "a source missing": {"contacts": [contact(1, [{"rank": 1, "stock_code": "95000"}])]},
    "a code with a space": {"contacts": [contact(1, [{**offers()[0], "stock_code": "95 000"}])]}, "a code with a slash": {"contacts": [contact(1, [{**offers()[0], "stock_code": "../x"}])]},
    "an empty code": {"contacts": [contact(1, [{**offers()[0], "stock_code": ""}])]}, "a code of 13 characters": {"contacts": [contact(1, [{**offers()[0], "stock_code": "A" * 13}])]},
    "a code that is a number": {"contacts": [contact(1, [{**offers()[0], "stock_code": 95000}])]}, "an extra key of an offer": {"contacts": [contact(1, [{**offers()[0], "price": 1}])]},
}


@pytest.mark.parametrize("name", list(BAD_BODIES))
def test_a_body_that_is_not_what_the_plan_says_is_400_and_writes_nothing(http, name):
    response = put(http, BAD_BODIES[name])
    assert response.status_code == 400 and response.json() == {"code": "bad_request"}, name
    assert http.get(f"/api/v1/rounds/{ROUND}/offers", headers=AUTH).json() == {"data": [], "total": 0}


def test_a_list_of_the_largest_size_is_taken_and_one_more_is_not(tmp_path):
    big = TestClient(standin_app(tmp_path / "x.sqlite", TOKEN), raise_server_exceptions=False)
    fifty = [{"rank": r, "stock_code": f"A{r}", "source": "fallback"} for r in range(1, 51)]
    assert put(big, {"contacts": [{"contact_id": 1, "offers": fifty}]}).json() == {"created": 1, "unchanged": 0}
    assert put(big, {"contacts": [{"contact_id": 2, "offers": [*fifty, {"rank": 51, "stock_code": "A51", "source": "fallback"}]}]}).status_code == 400
    assert big.get("/api/v1/contacts/1/offers?round_id=" + ROUND, headers=AUTH).json()["offers"] == fifty


def test_a_body_over_the_limit_is_413_even_when_it_is_valid_and_after_the_token(http):
    big = {"contacts": [{"contact_id": 1, "offers": [{"rank": 1, "stock_code": "95000", "source": "repeat"}], "padding": "a" * 25_000}]}
    response = put(http, big)
    assert response.status_code == 413 and response.json() == {"code": "payload_too_large"}
    assert put(http, big, headers={}).status_code == 401, "the token comes first"
    fits = put(http, batch(range(1, 6)))
    assert fits.status_code == 200 and len(json.dumps(batch(range(1, 6)))) < 20_000


def test_a_body_that_lies_about_its_size_is_cut_at_the_limit(http):
    """The body is read in pieces and counted: a stream that goes on past the limit is refused whatever its Content-Length says."""
    def chunks():
        for _ in range(100):
            yield b" " * 1_000

    response = http.put(f"/api/v1/rounds/{ROUND}/offers", content=chunks(), headers={**AUTH, **JSON})
    assert response.status_code == 413 and response.json() == {"code": "payload_too_large"}


def test_a_round_that_is_not_a_round_is_404_without_touching_the_database(http, monkeypatch):
    def boom(*args, **kwargs):
        raise AssertionError("the database was opened")

    monkeypatch.setattr(standin, "_connect", boom)
    for round_id in ("x", "R2011-3-28", "r2011-03-28", "R2011-03-28x", "R2011-03-28%0A", "R20110328", "R2011-03-28/..", "R٢٠١١-03-28", "%2e%2e", "R2011-03-28%20"):
        for method, suffix in (("PUT", ""), ("GET", ""), ("GET", "?offset=0")):
            response = http.request(method, f"/api/v1/rounds/{round_id}/offers{suffix}", headers=AUTH, content=json.dumps(batch([1])) if method == "PUT" else None)
            assert response.status_code == 404 and response.json() == {"code": "not_found"}, (method, round_id)
    assert http.get("/api/v1/contacts/1/offers?round_id=nope", headers=AUTH).status_code == 404


def test_a_route_or_a_method_that_is_not_in_the_plan_is_404_and_nothing_changes(http):
    put(http, batch([1]))
    before = http.get(f"/api/v1/rounds/{ROUND}/offers", headers=AUTH).json()
    for method, path in (("DELETE", f"/api/v1/rounds/{ROUND}/offers"), ("POST", f"/api/v1/rounds/{ROUND}/offers"), ("PATCH", f"/api/v1/rounds/{ROUND}/offers"),
                         ("PUT", f"/api/v1/contacts/1/offers?round_id={ROUND}"), ("DELETE", f"/api/v1/contacts/1/offers?round_id={ROUND}"), ("POST", "/health"), ("GET", "/api/v1/rounds"),
                         ("GET", f"/api/v1/rounds/{ROUND}"), ("GET", f"/api/v1/rounds/{ROUND}/offers/1"), ("GET", "/docs"), ("GET", "/redoc"), ("GET", "/openapi.json"), ("GET", "/")):
        response = http.request(method, path, headers=AUTH)
        assert response.status_code == 404 and response.json() == {"code": "not_found"}, (method, path)
        assert path.split("?")[0] not in response.text or path == "/"
    assert http.get(f"/api/v1/rounds/{ROUND}/offers", headers=AUTH).json() == before


def test_an_internal_error_is_500_without_a_trace_and_without_a_path(tmp_path, monkeypatch):
    app = TestClient(standin_app(tmp_path / "x.sqlite", TOKEN), raise_server_exceptions=False)

    def boom(*args, **kwargs):
        raise RuntimeError(f"disk exploded at {tmp_path}")

    monkeypatch.setattr(standin, "_page", boom)
    response = app.get(f"/api/v1/rounds/{ROUND}/offers", headers=AUTH)
    assert response.status_code == 500 and response.json() == {"code": "internal_error"}
    assert str(tmp_path) not in response.text and "disk exploded" not in response.text and "Traceback" not in response.text


def test_every_error_is_one_fixed_word_and_never_what_was_sent(http):
    marker = "SECRET-MARKER-9f3c"
    responses = [put(http, {"contacts": [contact(1, [{**offers()[0], "stock_code": marker}])]}), put(http, marker.encode()), http.get(f"/api/v1/contacts/{marker}/offers?round_id={ROUND}", headers=AUTH),
                 http.get(f"/api/v1/rounds/{marker}/offers", headers=AUTH), http.get(f"/api/v1/rounds/{ROUND}/offers?limit={marker}", headers=AUTH), http.get(f"/{marker}", headers=AUTH)]
    for response in responses:
        assert marker not in response.text and set(response.json()) == {"code"} and response.json()["code"] in {"bad_request", "not_found"}
    codes = {"unauthorized", "not_found", "bad_request", "payload_too_large", "list_conflict", "internal_error"}
    assert codes == set(standin.CODES)


# --- what it keeps -----------------------------------------------------------------------------------------------------------


def test_the_lists_survive_the_app_and_the_apps_over_other_files_are_independent(tmp_path):
    path = tmp_path / "crm" / "standin.sqlite"
    assert put(TestClient(standin_app(path, TOKEN)), batch([1, 2])).status_code == 200
    again = TestClient(standin_app(path, TOKEN))
    assert again.get(f"/api/v1/rounds/{ROUND}/offers", headers=AUTH).json()["total"] == 2
    elsewhere = TestClient(standin_app(tmp_path / "other.sqlite", TOKEN))
    assert elsewhere.get(f"/api/v1/rounds/{ROUND}/offers", headers=AUTH).json() == {"data": [], "total": 0}


def test_a_list_that_was_issued_cannot_be_changed_or_deleted_even_with_the_file_in_hand(tmp_path):
    """The database itself refuses (two triggers, as the warehouse's insert-only tables): the lists are what was issued."""
    path = tmp_path / "standin.sqlite"
    put(TestClient(standin_app(path, TOKEN)), batch([1]))
    conn = sqlite3.connect(path)
    try:
        for statement in ("UPDATE lists SET offers = '[]'", "DELETE FROM lists", "INSERT OR REPLACE INTO lists SELECT * FROM lists"):
            with pytest.raises(sqlite3.DatabaseError, match="solo inserción"):
                conn.execute(statement)
        assert conn.execute("SELECT COUNT(*) FROM lists").fetchone()[0] == 1
    finally:
        conn.close()


def test_two_puts_of_one_batch_at_once_create_it_once(tmp_path):
    import threading

    app = TestClient(standin_app(tmp_path / "x.sqlite", TOKEN))
    answers = []

    def send():
        answers.append(put(app, batch(range(1, 6))).json())

    threads = [threading.Thread(target=send) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sorted((a["created"], a["unchanged"]) for a in answers) == [(0, 5), (0, 5), (0, 5), (5, 0)]


# --- starting it ---------------------------------------------------------------------------------------------------------------


def test_the_app_of_the_configuration_reads_its_token_from_the_variable_the_configuration_names_and_its_limits_from_it(quick_cfg, tmp_path):
    cfg = dataclasses.replace(quick_cfg, paths=dataclasses.replace(quick_cfg.paths, crm_db=tmp_path / "crm" / "standin.sqlite"),
                              crm=dataclasses.replace(quick_cfg.crm, batch_size=2, max_body_bytes=3000, token_env="TEST_CRM_TOKEN"))
    app = TestClient(create_app(cfg, {"TEST_CRM_TOKEN": TOKEN, "PERSONALOFFERS_CRM_TOKEN": "not-this-one"}), raise_server_exceptions=False)
    assert cfg.paths.crm_db.is_file()
    assert app.get("/health", headers=AUTH).status_code == 200 and app.get("/health", headers={"Authorization": "Bearer not-this-one"}).status_code == 401
    assert put(app, batch([1, 2, 3])).status_code == 400, "at most batch_size contacts"
    assert put(app, {"contacts": [{"contact_id": 1, "offers": offers(1), "padding": "x" * 4000}]}).status_code == 413, "at most max_body_bytes"
    for env in ({}, {"TEST_CRM_TOKEN": ""}, {"TEST_CRM_TOKEN": "  "}):
        with pytest.raises(ValueError, match="token"):
            create_app(cfg, env)


def test_the_served_stand_in_refuses_a_list_that_is_not_of_the_configured_length_and_applies_nothing_of_its_batch(quick_cfg, tmp_path):
    """A2 of the evaluation: the stand-in that ``serve-crm`` and the compose file serve (``create_app``) took a list of 9 products with 200 ``created``. A list has ``[recommend] k`` products: one of
    another length is 400 for the whole batch, as any other malformed list, and nothing of the batch is applied. ``standin_app`` without a length keeps the old bound (1 to 50)."""
    cfg = dataclasses.replace(quick_cfg, paths=dataclasses.replace(quick_cfg.paths, crm_db=tmp_path / "crm" / "standin.sqlite"), crm=dataclasses.replace(quick_cfg.crm, token_env="TEST_CRM_TOKEN"))
    app = TestClient(create_app(cfg, {"TEST_CRM_TOKEN": TOKEN}), raise_server_exceptions=False)
    k = cfg.recommend.k
    for count in (k - 1, k + 1):
        body = {"contacts": [{"contact_id": 1, "offers": offers(1)}, {"contact_id": 2, "offers": offers(2, count)}]}
        assert put(app, body).status_code == 400 and put(app, body).json() == {"code": "bad_request"}, count
    assert app.get(f"/api/v1/rounds/{ROUND}/offers", headers=AUTH).json()["total"] == 0, "nothing of a refused batch is applied"
    assert put(app, batch([1, 2])).json() == {"created": 2, "unchanged": 0}
    loose = TestClient(standin_app(tmp_path / "loose.sqlite", TOKEN), raise_server_exceptions=False)
    assert put(loose, {"contacts": [{"contact_id": 1, "offers": offers(1, k - 1)}]}).status_code == 200


def test_the_app_of_the_environment_serves_the_file_of_the_configuration_with_the_token_of_the_process(quick_cfg, tmp_path, monkeypatch):
    """U20, D26: in Docker uvicorn calls ``create_app_from_environment`` (``--factory``) in the ``crm`` service; without the token it does not start."""
    from personaloffers import config as config_module

    cfg = dataclasses.replace(quick_cfg, paths=dataclasses.replace(quick_cfg.paths, crm_db=tmp_path / "crm" / "standin.sqlite"))
    monkeypatch.setattr(config_module, "load_config", lambda path=None: cfg)
    monkeypatch.setenv(cfg.crm.token_env, TOKEN)
    app = TestClient(create_app_from_environment(), raise_server_exceptions=False)
    assert app.get("/health").status_code == 401 and app.get("/health", headers=AUTH).json() == {"status": "ok"} and cfg.paths.crm_db.is_file()
    monkeypatch.delenv(cfg.crm.token_env)
    with pytest.raises(ValueError, match="token"):
        create_app_from_environment()
