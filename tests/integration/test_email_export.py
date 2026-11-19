"""The e-mail file of a round (U13; RF16, AC10; M05; plan section 12; decisions D30, D45; risk item 2): one CSV for each round in ``outputs/private/`` with the contact, the rank, the code, the description
and the source of the lists of the customers that receive an offer, written whole or not at all, with a text that a spreadsheet would run as a formula neutralised, and never versioned."""

from __future__ import annotations

import csv
import io
import subprocess
from pathlib import Path

import pytest

from personaloffers import email_export
from personaloffers.email_export import email_path, write_email_csv
from personaloffers.holdout import ControlLeakError
from tests.fixtures.tiny_flow import ROUND, code_of, tiny_warehouse

PROJECT = Path(__file__).resolve().parents[2]
HEADER = ["contact_id", "rank", "stock_code", "description_es", "source"]


def parse(path: Path) -> list[list[str]]:
    return list(csv.reader(io.StringIO(path.read_bytes().decode("utf-8"), newline="")))


@pytest.fixture
def tiny(tmp_path):
    descriptions = {code_of(c, r): f"PRODUCTO SINTÉTICO {code_of(c, r)}" for c in (1, 2, 3, 4) for r in range(1, 11)}
    conn = tiny_warehouse(tmp_path / "w.sqlite", {1: "offer", 2: "control", 3: "offer", 4: "offer"}, {1: "offer", 2: "control", 3: "offer", 4: "offer"}, descriptions=descriptions)
    yield conn, descriptions
    conn.close()


def test_the_file_has_the_columns_of_the_plan_and_ten_rows_for_each_customer_that_receives_an_offer_in_the_order_of_the_contact_and_the_rank(tiny, quick_view, tmp_path):
    conn, descriptions = tiny
    path = write_email_csv(conn, ROUND, tmp_path / "email" / f"{ROUND}.csv", quick_view)
    rows = parse(path)
    assert rows[0] == HEADER and len(rows) == 1 + 3 * 10
    assert [(int(r[0]), int(r[1])) for r in rows[1:]] == [(c, rank) for c in (1, 3, 4) for rank in range(1, 11)], "the control customer is not there; the rest in the order of contact and rank"
    first = rows[1]
    assert first == ["1", "1", code_of(1, 1), descriptions[code_of(1, 1)], "repeat"] and {r[4] for r in rows[1:]} == {"repeat", "discovery", "fallback"}
    assert path.read_bytes().count(b"\r") == 0 and path.read_bytes().endswith(b"\n") and not path.read_bytes().startswith(b"\xef\xbb\xbf"), "newline-terminated UTF-8 without a byte-order mark"


def test_the_same_round_written_again_is_the_same_bytes(tiny, quick_view, tmp_path):
    conn, _ = tiny
    path = write_email_csv(conn, ROUND, tmp_path / "a" / "x.csv", quick_view)
    again = write_email_csv(conn, ROUND, tmp_path / "b" / "x.csv", quick_view)
    assert path.read_bytes() == again.read_bytes()
    assert write_email_csv(conn, ROUND, path, quick_view).read_bytes() == path.read_bytes(), "over its own file too"


def test_a_description_that_a_spreadsheet_would_run_is_neutralised_and_one_with_commas_quotes_or_lines_is_quoted(tmp_path, quick_view):
    nasty = {code_of(1, 1): '=HYPERLINK("http://x","click")', code_of(1, 2): "+SUM(A1)", code_of(1, 3): "-2+3", code_of(1, 4): "@cmd", code_of(1, 5): "\t\tTAB", code_of(1, 6): "\r\nCR",
             code_of(1, 7): 'WITH, COMMA AND "QUOTES"', code_of(1, 8): "TWO\nLINES", code_of(1, 9): None, code_of(1, 10): "  =LEADING SPACES THEN EQUALS"}
    conn = tiny_warehouse(tmp_path / "w.sqlite", {1: "offer"}, {1: "offer"}, descriptions=nasty)
    rows = parse(write_email_csv(conn, ROUND, tmp_path / "x.csv", quick_view))[1:]
    assert [r[3] for r in rows] == ["'" + nasty[code_of(1, 1)], "'+SUM(A1)", "'-2+3", "'@cmd", "TAB", "CR", 'WITH, COMMA AND "QUOTES"', "TWO LINES", "", "'=LEADING SPACES THEN EQUALS"]
    assert [len(r) for r in rows] == [5] * 10, "every row has its five cells whatever the description holds"
    text = (tmp_path / "x.csv").read_bytes().decode("utf-8")
    assert '"WITH, COMMA AND ""QUOTES"""' in text
    assert "\r" not in text and text.count("\n") == 11, "one line for the header and one for each row: no description breaks a row"
    conn.close()


def test_a_product_without_a_row_in_the_catalogue_has_an_empty_description_and_the_list_still_goes(tmp_path, quick_view):
    conn = tiny_warehouse(tmp_path / "w.sqlite", {1: "offer"}, {1: "offer"}, descriptions={})
    rows = parse(write_email_csv(conn, ROUND, tmp_path / "x.csv", quick_view))[1:]
    assert len(rows) == 10 and {r[3] for r in rows} == {""}
    conn.close()


def test_a_list_that_does_not_have_the_ten_products_of_the_plan_is_refused_and_nothing_is_written(tmp_path, quick_view):
    short = tiny_warehouse(tmp_path / "short.sqlite", {1: "offer"}, {1: "offer"}, k=9)
    with pytest.raises(ValueError, match="10"):
        write_email_csv(short, ROUND, tmp_path / "x.csv", quick_view)
    assert not (tmp_path / "x.csv").exists()
    short.close()


def test_a_round_without_lists_for_the_offer_group_is_refused_and_a_round_that_is_not_one_is_refused_before_a_path_is_made(tiny, quick_view, tmp_path):
    conn, _ = tiny
    with pytest.raises(ValueError, match="no existe"):
        write_email_csv(conn, "R2011-09-05", tmp_path / "x.csv", quick_view)
    for bad in ("x", "R2011-3-28", "../R2011-03-28", "R2011-03-28/../../x", "R2011-03-28.csv", "R2011-03-28\n"):
        with pytest.raises(ValueError, match="ronda"):
            email_path(tmp_path, bad)
    assert email_path(tmp_path / "private", ROUND) == tmp_path / "private" / "email" / f"{ROUND}.csv"
    assert not (tmp_path / "private").exists(), "making the name made no folder"


def test_the_file_is_written_whole_through_write_atomic_and_a_failure_leaves_nothing(tiny, quick_view, tmp_path, monkeypatch):
    conn, _ = tiny
    calls = []
    real = email_export.write_atomic
    monkeypatch.setattr(email_export, "write_atomic", lambda path, data: (calls.append((Path(path), type(data))), real(path, data))[1])
    path = write_email_csv(conn, ROUND, tmp_path / "e" / "x.csv", quick_view)
    assert calls == [(path, bytes)] or calls == [(path, str)]
    monkeypatch.setattr(email_export, "write_atomic", lambda path, data: (_ for _ in ()).throw(OSError("disk full")))
    with pytest.raises(OSError, match="disk full"):
        write_email_csv(conn, ROUND, tmp_path / "e" / "y.csv", quick_view)
    assert sorted(p.name for p in (tmp_path / "e").iterdir()) == ["x.csv"]


def test_the_private_folder_is_never_versioned():
    """D30, D45: the file has customer numbers; git must ignore the folder it is written to."""
    found = subprocess.run(["git", "check-ignore", "-q", "outputs/private/email/R2011-03-28.csv"], cwd=PROJECT, check=False)
    assert found.returncode == 0, "outputs/private/ is in .gitignore"
    tracked = subprocess.run(["git", "ls-files", "outputs/private"], cwd=PROJECT, capture_output=True, text=True, check=True).stdout
    assert tracked.strip() == ""


def test_a_replayed_round_gives_a_file_that_is_the_lists_of_the_warehouse(replayed, workbook, quick_cfg, tmp_path):
    from tests.fixtures.worlds import copy_world

    world = copy_world(replayed.root, workbook, quick_cfg, tmp_path / "w")
    try:
        path = write_email_csv(world.conn, "R2011-04-04", email_path(world.cfg.paths.private_dir, "R2011-04-04"), world.view)
        stored = world.conn.execute("SELECT customer_id, rank, stock_code, source FROM offer_lists WHERE round_id = 'R2011-04-04' AND grp = 'offer' ORDER BY customer_id, rank").fetchall()
        assert [(int(r[0]), int(r[1]), r[2], r[4]) for r in parse(path)[1:]] == stored
        assert path == world.cfg.paths.private_dir / "email" / "R2011-04-04.csv"
    finally:
        world.conn.close()
