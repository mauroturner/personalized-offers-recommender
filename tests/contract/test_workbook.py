"""The untrusted workbook (U04, item 2 of the high-risk list; RF02, RF03, AC01 to AC03 and the base of AC04): every damaged copy of the fixture fails its own rule (V01 to
V07) and writes nothing; the copies of the week that both sheets hold are removed and the lines repeated inside a sheet are flagged; the canonical lines are written with
their manifest last and read only if it matches; and what the reader does with each kind of cell is fixed here."""

from __future__ import annotations

import dataclasses
import datetime as dt
import hashlib
import io
import json
import tempfile
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from personaloffers import sources, workbook as wb
from personaloffers.config import LINE_KEY_SHEET_FACTOR
from personaloffers.sources import SourceError, fetch_source
from tests.fixtures import make_workbook as mw
from tests.fixtures.configs import config_for, config_for_variant, copy_of, read_sheets, tree_of

PROJECT = Path(__file__).resolve().parents[2]
SHEET_1, SHEET_2 = mw.SHEETS
GOOD = (489434, 95000, "PRODUCTO SINTÉTICO 1", 12, dt.datetime(2010, 12, 7, 9, 2), 6.95, 90001, "United Kingdom")


@pytest.fixture
def no_stray_temporary_folder(tmp_path, monkeypatch):
    """Where the extraction goes is a folder of the test, so that what a refused source leaves behind can be listed."""
    folder = tmp_path / "temporary"
    folder.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(folder))
    yield folder
    assert list(folder.iterdir()) == [], "a refused or a finished read leaves no extracted workbook behind"


def hand_workbook(tmp_path: Path, first: list[tuple], second: list[tuple], header: tuple[str, ...] = mw.COLUMNS) -> Path:
    path = tmp_path / "hand.xlsx"
    path.write_bytes(mw.build_xlsx({SHEET_1: first, SHEET_2: second}, header=header))
    return path


# --- AC02: each damaged copy fails its rule and writes nothing ---------------------------------------------------------------------


@pytest.mark.parametrize("kind", mw.MALFORMED_KINDS)
def test_each_malformed_variant_fails_its_rule_and_writes_nothing(kind, variants, quick_cfg, tmp_path, no_stray_temporary_folder):
    variant = variants[kind]
    root = tmp_path / "project"
    before = tree_of(variant.workbook.zip_path.parent)
    with pytest.raises(SourceError) as caught:
        fetch_source(config_for_variant(quick_cfg, variant, root))
    error = caught.value
    assert error.rule_id == variant.rule == mw.EXPECTED_RULE[kind] and error.EXIT_CODE == 3
    assert error.problems and all(problem["rule_id"] == error.rule_id for problem in error.problems)
    assert not root.exists(), "no interim table, no registry of the quick mode, no folder"
    assert tree_of(variant.workbook.zip_path.parent) == before, "the file and the folder it is in are as they were"


EXPECTED_DETAIL = {
    "wrong_hash": {"reason": "sha256"},
    "extra_member": {"reason": "members", "members": ["online_retail_II.xlsx", "notes.txt"]},
    "renamed_member": {"reason": "members", "members": ["retail.xlsx"]},
    "macro_part": {"reason": "forbidden_part", "part": "xl/vbaProject.bin"},
    "external_link": {"reason": "forbidden_part", "part": "xl/externalLinks/externalLink1.xml"},
    "zip_bomb_part": {"reason": "part_size", "part": "xl/media/padding.bin", "size": 6_000_000, "max_part_bytes": 4_000_000},
    "extra_sheet": {"reason": "sheets", "missing": [], "extra": ["Notes"]},
    "missing_sheet": {"reason": "sheets", "missing": [SHEET_2], "extra": []},
    "extra_column": {"sheet": SHEET_1, "extra": ["Notes"], "missing": []},
    "missing_column": {"sheet": SHEET_1, "extra": [], "missing": ["Country"]},
    "reordered_columns": {"sheet": SHEET_1, "extra": [], "missing": []},
    "wrong_type": {"sheet": SHEET_2, "column": "Quantity", "count": 1, "examples": [{"row": 126, "value": "'ten'"}]},
    "date_out_of_range": {"sheet": SHEET_2, "count": 1, "examples": [{"row": 126, "value": "datetime.datetime(2012, 1, 1, 10, 0)"}],
                          "first_date": "2010-12-06", "last_date": "2011-04-22"},
}


@pytest.mark.parametrize("kind", sorted(EXPECTED_DETAIL))
def test_each_rule_names_what_failed_and_where_without_a_customer_or_an_invoice(kind, variants, quick_cfg, tmp_path):
    variant = variants[kind]
    with pytest.raises(SourceError) as caught:
        fetch_source(config_for_variant(quick_cfg, variant, tmp_path / "project"))
    problem = caught.value.problems[0]
    assert {key: problem[key] for key in EXPECTED_DETAIL[kind]} == EXPECTED_DETAIL[kind]
    assert str(caught.value).startswith(f"{variant.rule}: ")
    assert ("runbook R1" in str(caught.value)) == (variant.rule in ("V01", "V02"))


def test_too_many_rows_names_the_sheet_and_the_limit(variants, quick_cfg, tmp_path):
    variant = variants["too_many_rows"]
    with pytest.raises(SourceError) as caught:
        fetch_source(config_for_variant(quick_cfg, variant, tmp_path / "project"))
    limit = variant.overrides["max_rows"]
    assert limit == 249 and caught.value.rule_id == "V06" and caught.value.problems == [{"rule_id": "V06", "reason": "rows", "sheet": SHEET_1, "max_rows": limit}]
    assert f"{limit}" in str(caught.value)
    # the limit itself is accepted: the rows that the sheets have, and nothing is refused
    cfg = config_for_variant(quick_cfg, variant, tmp_path / "again")
    assert fetch_source(dataclasses.replace(cfg, source=dataclasses.replace(cfg.source, max_rows=limit + 1)))["lines"] > 0


def extracted(fixture, folder: Path) -> Path:
    """The workbook of a fixture zip, as a file of its own."""
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "package.xlsx"
    with zipfile.ZipFile(fixture.zip_path) as archive:
        path.write_bytes(archive.read(fixture.member))
    return path


def small_package(parts: dict[str, bytes] | None = None) -> dict[str, bytes]:
    """The parts of a tiny valid workbook (two sheets of one row), plus these."""
    with zipfile.ZipFile(io.BytesIO(mw.build_xlsx({SHEET_1: [GOOD], SHEET_2: [GOOD]}))) as small:
        package = {info.filename: small.read(info.filename) for info in small.infolist()}
    return package | (parts or {})


# --- RF03, AC03: the copies of the shared week and the repeats inside a sheet --------------------------------------------------------


def test_overlap_copies_are_removed_and_internal_repeats_flagged(workbook, quick_cfg, tmp_path, no_stray_temporary_folder):
    cfg = config_for(quick_cfg, workbook, tmp_path / "project")
    result = fetch_source(cfg)
    truth = workbook.truth
    assert result["built"] is True and result["rows_by_sheet"] == truth.sheet_rows
    assert (result["lines"], result["copies"], result["repeats"]) == (truth.canonical_lines, truth.overlap_copies, truth.internal_repeats)
    assert result["zip_sha256"] == workbook.zip_sha256 and result["member_sha256"] == workbook.member_sha256
    lines = wb.read_lines(cfg)
    assert list(lines.columns) == list(wb.LINE_COLUMNS) and len(lines) == truth.canonical_lines
    assert result["lines_sha256"] == hashlib.sha256((cfg.paths.interim_dir / wb.LINES_NAME).read_bytes()).hexdigest()
    # the lines again from the workbook, read here with openpyxl and nothing of the package: the first sheet whole, the second one without the shared week
    sheets = read_sheets(workbook.zip_path)
    first, second = sheets[SHEET_1][1:], sheets[SHEET_2][1:]
    last_shared = max(row[4] for row in first).date()
    expected = [(1, number, row) for number, row in enumerate(first, start=1)]
    expected += [(2, number, row) for number, row in enumerate(second, start=1) if row[4].date() > last_shared]
    assert len(expected) == len(lines) == truth.canonical_lines
    keys = [sheet * LINE_KEY_SHEET_FACTOR + number for sheet, number, _row in expected]
    assert lines["line_key"].tolist() == keys and lines["line_key"].is_unique
    assert lines["invoice"].tolist() == [str(row[0]) for _s, _n, row in expected]
    assert lines["stock_code"].tolist() == [str(row[1]) for _s, _n, row in expected]
    assert lines["quantity"].tolist() == [row[3] for _s, _n, row in expected]
    assert lines["price"].tolist() == [float(row[5]) for _s, _n, row in expected]
    assert lines["invoice_date"].tolist() == [pd.Timestamp(row[4]) for _s, _n, row in expected]
    assert [None if pd.isna(value) else int(value) for value in lines["customer_id"]] == [row[6] for _s, _n, row in expected]
    assert lines["country"].tolist() == [row[7] for _s, _n, row in expected]
    # the copies are the second sheet's: its rows of the shared week are gone, the first sheet's are all there and the line keys say the sheet
    sheet_of = lines["line_key"] // LINE_KEY_SHEET_FACTOR
    assert (sheet_of == 1).sum() == len(first) == truth.overlap_copies and not (lines[sheet_of == 2]["invoice_date"].dt.date <= last_shared).any()
    # a line repeated inside the shared week is kept once as it was in the first sheet and flagged on its second appearance; no other line is flagged
    flagged = lines[lines["internal_repeat"]]
    assert len(flagged) == truth.internal_repeats == int(lines["internal_repeat"].sum())
    assert (sheet_of[flagged.index] == 1).sum() >= 1
    columns = ["invoice", "stock_code", "description", "quantity", "invoice_date", "price", "customer_id", "country"]
    assert lines.duplicated(subset=columns, keep="first").tolist() == lines["internal_repeat"].tolist()
    assert str(lines["customer_id"].dtype) == "Int64" and lines["customer_id"].isna().sum() > 100
    assert set(lines["customer_id"].dropna()) <= set(range(90001, 90301))


def test_the_copies_removed_are_counted_as_a_multiset_and_only_inside_the_shared_days(quick_cfg, tmp_path):
    """Three equal rows in the second sheet against two in the first: two are copies and one is a repeat; an equal row of another day is never a copy."""
    day_one, day_two = dt.datetime(2010, 12, 6, 9, 0), dt.datetime(2010, 12, 6, 10, 0)
    rows = [(1, 95000, "A", 1, day_one, 1.0, 90001, "France"), (1, 95000, "A", 1, day_one, 1.0, 90001, "France"), (2, 95012, None, 2, day_two, 2.5, None, "France")]
    second = [*rows, (1, 95000, "A", 1, day_one, 1.0, 90001, "France"), (3, 95024, "B", 1, dt.datetime(2010, 12, 14, 9, 0), 1.0, 90002, "France")]
    path = hand_workbook(tmp_path, rows, second)
    cfg = config_for(quick_cfg, mw.FixtureWorkbook(path, 1, "a" * 64, "x.xlsx", 1, "a" * 64), tmp_path / "project")
    lines = wb.canonical_lines(wb.read_workbook(path, cfg), cfg)
    assert lines["line_key"].tolist() == [10_000_001, 10_000_002, 10_000_003, 20_000_004, 20_000_005]
    assert lines["internal_repeat"].tolist() == [False, True, False, True, False], "the third equal row stays, as a repeat of the first"
    assert lines["description"].isna().tolist() == [False, False, True, False, False] and lines["customer_id"].isna().tolist() == [False, False, True, False, False]


def test_a_workbook_whose_sheets_share_no_day_keeps_every_row_of_both(quick_cfg, tmp_path):
    first = [(1, 95000, "A", 1, dt.datetime(2010, 12, 6, 9, 0), 1.0, 90001, "France")]
    second = [(1, 95000, "A", 1, dt.datetime(2010, 12, 6, 9, 0), 1.0, 90001, "France")]
    path = hand_workbook(tmp_path, first, second)
    cfg = config_for(quick_cfg, mw.FixtureWorkbook(path, 1, "a" * 64, "x.xlsx", 1, "a" * 64), tmp_path / "project")
    raw = wb.read_workbook(path, cfg)
    assert len(wb.canonical_lines(raw, cfg)) == 1, "the second sheet's day is the first sheet's last one: that day is shared, and the row of the second sheet is a copy"
    later = [(1, 95000, "A", 1, dt.datetime(2010, 12, 8, 9, 0), 1.0, 90001, "France")]
    path = hand_workbook(tmp_path, first, later)
    lines = wb.canonical_lines(wb.read_workbook(path, cfg), cfg)
    assert lines["line_key"].tolist() == [10_000_001, 20_000_001] and lines["internal_repeat"].tolist() == [False, False]


# --- the canonical lines on disk: the manifest is written last, and nothing is read that does not match it ---------------------------------


def built(workbook, quick_cfg, tmp_path):
    cfg = config_for(quick_cfg, workbook, tmp_path / "project")
    return cfg, fetch_source(cfg)


def test_the_lines_are_written_with_their_manifest_last_and_a_second_run_changes_nothing(small_workbook, quick_cfg, tmp_path):
    cfg, result = built(small_workbook, quick_cfg, tmp_path)
    interim = cfg.paths.interim_dir
    assert sorted(path.name for path in interim.iterdir()) == ["lines.parquet", "lines_manifest.json"]
    manifest = json.loads((interim / "lines_manifest.json").read_text(encoding="utf-8"))
    assert manifest == {"version": 2, "zip_sha256": small_workbook.zip_sha256, "member_sha256": small_workbook.member_sha256, "rows": small_workbook.truth.canonical_lines,
                        "files": {"lines.parquet": result["lines_sha256"]}}
    before = tree_of(tmp_path / "project")
    again = fetch_source(cfg)
    assert again["built"] is False and again["lines_sha256"] == result["lines_sha256"] and again["lines"] == result["lines"]
    assert tree_of(tmp_path / "project") == before


def test_the_canonical_lines_keep_their_ten_columns_in_their_order_and_add_the_role_last(fixture_lines, workbook):
    """U05 added ``role``: what was there before is still there, in the same order and with the same values (the counts of the copies and the repeats are the fixture's)."""
    assert tuple(wb.LINE_COLUMNS[:10]) == ("line_key", "invoice", "stock_code", "description", "quantity", "invoice_date", "price", "customer_id", "country", "internal_repeat")
    assert wb.LINE_COLUMNS[10:] == ("role",) and list(fixture_lines.columns) == list(wb.LINE_COLUMNS)
    assert len(fixture_lines) == workbook.truth.canonical_lines and int(fixture_lines["internal_repeat"].sum()) == workbook.truth.internal_repeats
    assert fixture_lines["role"].map(type).eq(str).all() and fixture_lines["role"].notna().all()


def test_lines_written_before_the_roles_existed_are_refused_and_rebuilt_with_them(small_workbook, quick_cfg, tmp_path):
    cfg, result = built(small_workbook, quick_cfg, tmp_path)
    interim = cfg.paths.interim_dir
    old = json.loads((interim / "lines_manifest.json").read_text(encoding="utf-8"))
    old["version"] = 1
    (interim / "lines_manifest.json").write_text(json.dumps(old), encoding="utf-8")
    with pytest.raises(wb.InterimError, match="manifiesto"):
        wb.read_lines(cfg)
    again = fetch_source(cfg)
    assert again["built"] is True and again["lines_sha256"] == result["lines_sha256"]
    assert json.loads((interim / "lines_manifest.json").read_text(encoding="utf-8"))["version"] == 2
    assert "role" in wb.read_lines(cfg).columns


def test_the_task_counts_the_roles_it_wrote_and_the_file_holds_them(small_workbook, quick_cfg, tmp_path):
    cfg, result = built(small_workbook, quick_cfg, tmp_path)
    lines = wb.read_lines(cfg)
    assert result["roles"] == small_workbook.truth.roles == {role: int((lines["role"] == role).sum()) for role in small_workbook.truth.roles}
    assert fetch_source(cfg)["built"] is False


def test_lines_that_do_not_match_their_manifest_are_refused_and_rebuilt_by_the_task(small_workbook, quick_cfg, tmp_path):
    cfg, result = built(small_workbook, quick_cfg, tmp_path)
    interim = cfg.paths.interim_dir
    good = (interim / "lines.parquet").read_bytes()
    manifest_good = (interim / "lines_manifest.json").read_text(encoding="utf-8")
    # a file written again with other content
    data = bytearray(good)
    data[len(data) // 2] ^= 0x01
    (interim / "lines.parquet").write_bytes(bytes(data))
    with pytest.raises(wb.InterimError, match="huella"):
        wb.read_lines(cfg)
    assert fetch_source(cfg)["built"] is True and (interim / "lines.parquet").read_bytes() == good, "the same input gives the same bytes"
    # no manifest, or a manifest that is not one, or one of another source
    (interim / "lines_manifest.json").unlink()
    with pytest.raises(wb.InterimError, match="manifiesto"):
        wb.read_lines(cfg)
    (interim / "lines_manifest.json").write_text("{}", encoding="utf-8")
    with pytest.raises(wb.InterimError, match="manifiesto"):
        wb.read_lines(cfg)
    more = json.loads(manifest_good)
    more["files"]["other.parquet"] = more["files"]["lines.parquet"]
    (interim / "lines_manifest.json").write_text(json.dumps(more), encoding="utf-8")
    with pytest.raises(wb.InterimError, match="manifiesto"):
        wb.read_lines(cfg)
    other = json.loads(manifest_good)
    other["zip_sha256"] = "ee" * 32
    (interim / "lines_manifest.json").write_text(json.dumps(other), encoding="utf-8")
    assert wb.read_lines(cfg) is not None, "the reader trusts the manifest's own hash of the file; whose source it is, is the task's question"
    assert fetch_source(cfg)["built"] is True and (interim / "lines_manifest.json").read_text(encoding="utf-8") == manifest_good
    other["zip_sha256"], other["member_sha256"] = other["zip_sha256"][:0] + small_workbook.zip_sha256, "ee" * 32
    (interim / "lines_manifest.json").write_text(json.dumps(other), encoding="utf-8")
    assert fetch_source(cfg)["built"] is True, "the workbook of the manifest is not this one even if the zip is"
    # the file is gone
    (interim / "lines.parquet").unlink()
    with pytest.raises(wb.InterimError, match="falta"):
        wb.read_lines(cfg)
    assert fetch_source(cfg)["lines_sha256"] == result["lines_sha256"]


def test_the_quick_mode_registers_its_first_view_after_a_good_read_and_holds_it(small_workbook, quick_cfg, tmp_path):
    copy = copy_of(small_workbook, tmp_path / "quick")
    base = config_for(quick_cfg, copy, tmp_path / "project")
    cfg = dataclasses.replace(base, source=dataclasses.replace(base.source, zip_bytes=0, zip_sha256="", member_bytes=0, member_sha256=""))
    lock = sources.lock_path(cfg)
    assert fetch_source(cfg)["lock"] == "registered"
    assert json.loads(lock.read_text(encoding="utf-8")) == {
        "version": 1, "zip": {"sha256": small_workbook.zip_sha256, "size": small_workbook.zip_bytes}, "member": {"sha256": small_workbook.member_sha256, "size": small_workbook.member_bytes}}
    assert fetch_source(cfg)["lock"] == "held"
    pinned = config_for(quick_cfg, small_workbook, tmp_path / "pinned")
    assert fetch_source(pinned)["lock"] == "not needed" and not sources.lock_path(pinned).exists()
    # a refused first view registers nothing
    bad = copy_of(mw.make_malformed(small_workbook, "wrong_type", tmp_path / "damaged").workbook, tmp_path / "quick2")
    unpinned = config_for(quick_cfg, bad, tmp_path / "project2")
    unpinned = dataclasses.replace(unpinned, source=dataclasses.replace(unpinned.source, zip_bytes=0, zip_sha256="", member_bytes=0, member_sha256=""))
    with pytest.raises(SourceError) as caught:
        fetch_source(unpinned)
    assert caught.value.rule_id == "V06" and not sources.lock_path(unpinned).exists() and not (tmp_path / "project2").exists()


# --- the reader: what it makes of each kind of cell (V06) --------------------------------------------------------------------------------


def test_the_reader_converts_what_openpyxl_delivers_and_numbers_the_rows_of_the_sheet(quick_cfg, tmp_path):
    ts = dt.datetime(2010, 12, 7, 9, 2)
    first = [
        (489434, 85048, "A DESCRIPTION", 12, ts, 6.95, 13085.0, "United Kingdom"),     # an invoice and a code as numbers, a customer as an integer-valued float
        (None,) * 8,                                                                   # a blank row: skipped, but the rows after it keep their number
        ("C489449", "79323P", None, -12.0, ts, 2, None, "Germany"),                    # text and number cells, no description, no customer, a quantity as a float and a price as an integer
        ("489436", "22423", 5, 6, ts, 0.001, 99999, ""),                                # text digits, a number as a description (kept as its text), an empty country
    ]
    path = hand_workbook(tmp_path, first, [GOOD])
    cfg = config_for(quick_cfg, mw.FixtureWorkbook(path, 1, "a" * 64, "x.xlsx", 1, "a" * 64), tmp_path / "project")
    raw = wb.read_workbook(path, cfg)
    assert list(raw.columns) == list(wb.RAW_COLUMNS)
    assert raw["sheet"].tolist() == [1, 1, 1, 2] and raw["source_row"].tolist() == [1, 3, 4, 1]
    assert raw["invoice"].tolist() == ["489434", "C489449", "489436", "489434"] and raw["stock_code"].tolist() == ["85048", "79323P", "22423", "95000"]
    assert raw["description"].isna().tolist() == [False, True, False, False] and raw["description"].tolist()[2] == "5"
    assert raw["quantity"].tolist() == [12, -12, 6, 12] and str(raw["quantity"].dtype) == "int64"
    assert raw["price"].tolist() == [6.95, 2.0, 0.001, 6.95] and str(raw["price"].dtype) == "float64"
    assert [None if pd.isna(v) else int(v) for v in raw["customer_id"]] == [13085, None, 99999, 90001] and str(raw["customer_id"].dtype) == "Int64"
    assert raw["country"].tolist() == ["United Kingdom", "Germany", "", "United Kingdom"]
    assert raw["invoice_date"].tolist() == [pd.Timestamp(ts)] * 3 + [pd.Timestamp(GOOD[4])]


@pytest.mark.parametrize(("column", "value"), [
    ("Invoice", None), ("Invoice", "  "), ("Invoice", True), ("Invoice", 1.5), ("StockCode", None), ("StockCode", ""), ("StockCode", 2.5),
    ("Quantity", 1.5), ("Quantity", "5"), ("Quantity", None), ("Quantity", True), ("Quantity", float("nan")),
    ("InvoiceDate", "2011-01-01"), ("InvoiceDate", None), ("InvoiceDate", 40000),
    ("Price", "1.5"), ("Price", None), ("Price", float("inf")), ("Price", float("nan")), ("Price", True),
    ("Customer ID", 1.5), ("Customer ID", "13085"), ("Customer ID", 9999), ("Customer ID", 100000), ("Customer ID", -13085), ("Customer ID", True),
])
def test_a_cell_of_the_wrong_type_is_v06_with_its_column_and_its_row(quick_cfg, tmp_path, column, value):
    row = list(GOOD)
    row[mw.COLUMNS.index(column)] = value
    path = hand_workbook(tmp_path, [GOOD], [GOOD, tuple(row)])
    cfg = config_for(quick_cfg, mw.FixtureWorkbook(path, 1, "a" * 64, "x.xlsx", 1, "a" * 64), tmp_path / "project")
    with pytest.raises(SourceError) as caught:
        wb.read_workbook(path, cfg)
    problem = caught.value.problems[0]
    assert caught.value.rule_id == "V06" and (problem["sheet"], problem["column"], problem["count"]) == (SHEET_2, column, 1)
    assert [example["row"] for example in problem["examples"]] == [2]
    if column in ("Invoice", "Customer ID"):
        assert "13085" not in str(problem["examples"]) and "9999" not in str(problem["examples"]), "an identifier is never shown: its type and its length are"
        assert problem["examples"][0]["value"].startswith("<")


def test_a_value_outside_the_eight_columns_is_v06(quick_cfg, tmp_path):
    path = hand_workbook(tmp_path, [GOOD], [GOOD, (*GOOD, "extra")])
    cfg = config_for(quick_cfg, mw.FixtureWorkbook(path, 1, "a" * 64, "x.xlsx", 1, "a" * 64), tmp_path / "project")
    with pytest.raises(SourceError) as caught:
        wb.read_workbook(path, cfg)
    assert caught.value.rule_id == "V06" and caught.value.problems[0]["reason"] == "outside_columns" and caught.value.problems[0]["row"] == 2


def test_the_counts_and_the_first_five_examples_of_a_column_are_reported(quick_cfg, tmp_path):
    rows = [GOOD] + [(*GOOD[:3], "x", *GOOD[4:]) for _ in range(8)]
    path = hand_workbook(tmp_path, [GOOD], rows)
    cfg = config_for(quick_cfg, mw.FixtureWorkbook(path, 1, "a" * 64, "x.xlsx", 1, "a" * 64), tmp_path / "project")
    with pytest.raises(SourceError) as caught:
        wb.read_workbook(path, cfg)
    problem = caught.value.problems[0]
    assert problem["count"] == 8 and [example["row"] for example in problem["examples"]] == [2, 3, 4, 5, 6]


def test_the_row_limit_and_the_date_limits_include_their_edges(quick_cfg, tmp_path):
    first_day = (GOOD[0], GOOD[1], GOOD[2], GOOD[3], dt.datetime(2010, 12, 6, 0, 0), GOOD[5], GOOD[6], GOOD[7])
    last_day = (GOOD[0], GOOD[1], GOOD[2], GOOD[3], dt.datetime(2011, 4, 22, 23, 59), GOOD[5], GOOD[6], GOOD[7])
    path = hand_workbook(tmp_path, [first_day], [first_day, last_day, GOOD])
    cfg = config_for(quick_cfg, mw.FixtureWorkbook(path, 1, "a" * 64, "x.xlsx", 1, "a" * 64), tmp_path / "project", max_rows=3)
    assert len(wb.read_workbook(path, cfg)) == 4, "three rows in a sheet with a limit of three, and the first and the last minute of the range"
    with pytest.raises(SourceError) as caught:
        wb.read_workbook(path, dataclasses.replace(cfg, source=dataclasses.replace(cfg.source, max_rows=2)))
    assert caught.value.rule_id == "V06" and caught.value.problems[0]["reason"] == "rows"
    for stamp in (dt.datetime(2010, 12, 5, 23, 59), dt.datetime(2011, 4, 23, 0, 0)):
        outside = (*GOOD[:4], stamp, *GOOD[5:])
        path = hand_workbook(tmp_path, [GOOD], [GOOD, outside])
        with pytest.raises(SourceError) as caught:
            wb.read_workbook(path, cfg)
        assert caught.value.rule_id == "V07" and caught.value.problems[0]["count"] == 1


def test_the_two_sheets_are_read_in_the_order_the_configuration_names_them_whatever_the_order_in_the_file(quick_cfg, tmp_path):
    path = tmp_path / "swapped.xlsx"
    path.write_bytes(mw.build_xlsx({SHEET_2: [GOOD, GOOD], SHEET_1: [GOOD]}))
    cfg = config_for(quick_cfg, mw.FixtureWorkbook(path, 1, "a" * 64, "x.xlsx", 1, "a" * 64), tmp_path / "project")
    raw = wb.read_workbook(path, cfg)
    assert raw["sheet"].tolist() == [1, 2, 2] and raw["source_row"].tolist() == [1, 1, 2]


def test_the_header_of_each_sheet_is_the_eight_columns_in_order_and_nothing_else(quick_cfg, tmp_path):
    swapped = list(mw.COLUMNS)
    swapped[0], swapped[1] = swapped[1], swapped[0]
    for header, missing, extra in ((tuple(swapped), [], []), (mw.COLUMNS[:-1], ["Country"], []), ((*mw.COLUMNS, "Notes"), [], ["Notes"]),
                                   (("invoice", *mw.COLUMNS[1:]), ["Invoice"], ["invoice"]), ((), list(mw.COLUMNS), [])):
        path = hand_workbook(tmp_path, [GOOD[: len(header)]] if header else [], [GOOD[: len(header)]] if header else [], header=header)
        cfg = config_for(quick_cfg, mw.FixtureWorkbook(path, 1, "a" * 64, "x.xlsx", 1, "a" * 64), tmp_path / "project")
        with pytest.raises(SourceError) as caught:
            wb.read_workbook(path, cfg)
        problem = caught.value.problems[0]
        assert caught.value.rule_id == "V05" and problem["sheet"] == SHEET_1 and (problem["missing"], problem["extra"]) == (missing, extra), header
        assert problem["columns"] == list(header)


# --- V03: the package, before openpyxl sees it ----------------------------------------------------------------------------------------


def test_the_check_of_the_package_reports_what_it_measured(workbook, quick_cfg, tmp_path):
    cfg = config_for(quick_cfg, workbook, tmp_path / "project")
    check = wb.inspect_workbook(extracted(workbook, tmp_path / "x"), cfg)
    with zipfile.ZipFile(workbook.zip_path) as outer, zipfile.ZipFile(io.BytesIO(outer.read("online_retail_II.xlsx"))) as xlsx:
        infos = xlsx.infolist()
    assert check.parts == len(infos) >= 8
    assert check.largest_part == max(info.file_size for info in infos) and check.uncompressed_bytes == sum(info.file_size for info in infos)
    assert 1.0 < check.max_ratio < wb.MAX_COMPRESSION_RATIO


@pytest.mark.parametrize(("name", "parts", "reason"), [
    ("macros", {"xl/vbaProject.bin": b"x"}, "forbidden_part"), ("macros in any case", {"XL/VBAPROJECT.BIN": b"x"}, "forbidden_part"),
    ("a link", {"xl/externalLinks/externalLink1.xml": b"<x/>"}, "forbidden_part"), ("activeX", {"xl/activeX/activeX1.xml": b"<x/>"}, "forbidden_part"),
    ("a part above the cap", {"xl/big.bin": bytes(300_000)}, "part_size"), ("a ratio", {"xl/zeros.bin": bytes(200_000)}, "ratio"),
    ("an absolute name", {"/xl/evil.xml": b"<x/>"}, "part_name"), ("a parent folder", {"xl/../evil.xml": b"<x/>"}, "part_name"),
    ("a DOCTYPE", {"xl/styles.xml": b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "b">]><styleSheet/>'}, "dtd"),
])
def test_a_package_that_breaks_a_rule_of_v03_is_refused_by_its_reason(workbook, quick_cfg, tmp_path, name, parts, reason):
    package = small_package(parts)
    assert max(len(data) for key, data in package.items() if key not in parts) < 250_000, "the tiny workbook is under the cap that the test sets"
    path = tmp_path / "package.xlsx"
    path.write_bytes(mw.repack(package))
    cfg = config_for(quick_cfg, workbook, tmp_path / "project", max_part_bytes=250_000)
    with pytest.raises(SourceError) as caught:
        wb.inspect_workbook(path, cfg)
    assert caught.value.rule_id == "V03" and caught.value.problems[0]["reason"] == reason, name
    # and the tiny workbook alone is accepted
    path.write_bytes(mw.repack(small_package()))
    assert wb.inspect_workbook(path, cfg).parts == len(small_package())


def test_the_edges_of_the_part_cap_the_ratio_the_parts_count_and_encryption(workbook, quick_cfg, tmp_path, monkeypatch):
    noise = np.random.default_rng(0).bytes(250_000)      # does not compress: its ratio is 1
    cfg = config_for(quick_cfg, workbook, tmp_path / "project", max_part_bytes=250_000)
    path = tmp_path / "edge.xlsx"
    path.write_bytes(mw.repack(small_package({"xl/noise.bin": noise})))
    assert wb.inspect_workbook(path, cfg).largest_part == 250_000, "a part exactly at the cap is inside it"
    path.write_bytes(mw.repack(small_package({"xl/noise.bin": noise + b"x"})))
    with pytest.raises(SourceError) as caught:
        wb.inspect_workbook(path, cfg)
    assert caught.value.problems[0]["reason"] == "part_size" and caught.value.problems[0]["size"] == 250_001
    # a part under 64 KiB is never refused for its ratio, however compressible; one of 64 KiB is
    path.write_bytes(mw.repack(small_package({"xl/zeros.bin": bytes(wb.RATIO_FROM_BYTES - 1)})))
    assert wb.inspect_workbook(path, cfg).max_ratio > wb.MAX_COMPRESSION_RATIO
    path.write_bytes(mw.repack(small_package({"xl/zeros.bin": bytes(wb.RATIO_FROM_BYTES)})))
    with pytest.raises(SourceError) as caught:
        wb.inspect_workbook(path, cfg)
    assert caught.value.problems[0]["reason"] == "ratio"
    # the number of parts
    path.write_bytes(mw.repack(small_package()))
    monkeypatch.setattr(wb, "MAX_PARTS", len(small_package()) - 1)
    with pytest.raises(SourceError) as caught:
        wb.inspect_workbook(path, cfg)
    assert caught.value.problems[0]["reason"] == "parts"
    monkeypatch.undo()
    # an encrypted part: the central directory says so
    data = bytearray(mw.repack(small_package()))
    data[data.rfind(b"PK") + 8] |= 0x01
    path.write_bytes(bytes(data))
    with pytest.raises(SourceError) as caught:
        wb.inspect_workbook(path, cfg)
    assert caught.value.problems[0]["reason"] == "encrypted"


@pytest.mark.parametrize(("name", "data"), [("not a zip", b"this is not a workbook"), ("empty", b""), ("a truncated zip", None)])
def test_a_file_that_is_not_a_workbook_is_v03(workbook, quick_cfg, tmp_path, name, data):
    inner = zipfile.ZipFile(workbook.zip_path).read("online_retail_II.xlsx")
    path = tmp_path / "bad.xlsx"
    path.write_bytes(inner[: len(inner) // 2] if data is None else data)
    cfg = config_for(quick_cfg, workbook, tmp_path / "project")
    with pytest.raises(SourceError) as caught:
        wb.inspect_workbook(path, cfg)
    assert caught.value.rule_id == "V03" and caught.value.problems[0]["reason"] == "unreadable", name


def test_a_zip_without_the_parts_of_a_workbook_is_v03_and_one_that_openpyxl_cannot_open_is_too(workbook, quick_cfg, tmp_path):
    cfg = config_for(quick_cfg, workbook, tmp_path / "project")
    path = tmp_path / "empty.xlsx"
    path.write_bytes(mw.repack({"readme.txt": b"hello"}))
    with pytest.raises(SourceError) as caught:
        wb.inspect_workbook(path, cfg)
    assert caught.value.rule_id == "V03" and caught.value.problems[0]["reason"] == "missing_part"
    package = small_package({"xl/workbook.xml": b"<workbook"})          # the package is what V03 allows, but the workbook part is not XML
    path.write_bytes(mw.repack(package))
    assert wb.inspect_workbook(path, cfg).parts == len(package)
    with pytest.raises(SourceError) as caught:
        wb.read_workbook(path, cfg)
    assert caught.value.rule_id == "V03" and caught.value.problems[0]["reason"] == "unreadable"


# --- the real workbook (marked: it needs data/raw/) ---------------------------------------------------------------------------------------


@pytest.mark.real_data
def test_the_real_zip_and_package_pass_v01_to_v03_with_the_limits_of_the_configuration():
    """V01 and V02 on the 46 MB zip and V03 on its package. The parts' sizes and ratios are the figures that fixed ``max_part_bytes``: the two sheets are 156,346,796
    and 160,448,656 bytes at a ratio of 7.0, under 400,000,000. No row is read."""
    from personaloffers.config import load_config

    cfg = load_config(PROJECT / "config" / "pipeline.toml")
    assert sources.check_sources(cfg) == {"zip": cfg.source.zip_sha256, "member": cfg.source.member_sha256}
    with tempfile.TemporaryDirectory() as folder:
        xlsx = sources.extract_workbook(cfg, Path(folder))
        check = wb.inspect_workbook(xlsx, cfg)
    assert check.parts == 11 and check.largest_part == 160_448_656 and check.largest_part < cfg.source.max_part_bytes / 2
    assert 6.9 < check.max_ratio < 7.1 < wb.MAX_COMPRESSION_RATIO / 10


@pytest.mark.real_data
def test_the_reader_accepts_what_openpyxl_delivers_for_the_first_rows_of_each_real_sheet():
    """The cells of 3,000 rows of each sheet, from December 2009 and December 2010, go through the converter of the reader with no problem: their types are the
    ones it expects (checked with the real file, as the plan asks). The dates are asserted, so no row of the test window is read."""
    import openpyxl

    path = PROJECT / "data" / "raw" / "online_retail_II.xlsx"
    book = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        for name in book.sheetnames:
            for number, row in enumerate(book[name].iter_rows(min_row=2, max_row=3001, values_only=True), start=1):
                converted, bad = wb.convert_row(tuple(row))
                assert not bad, (name, number, bad)
                assert converted[4] < dt.datetime(2011, 8, 1), "the first rows of a sheet are from 2009 and 2010"
    finally:
        book.close()
