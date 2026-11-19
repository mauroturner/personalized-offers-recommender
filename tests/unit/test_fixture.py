"""The synthetic workbook of the tests (U03, D44; base of AC02, AC03 and AC04): it has the real member, sheets and columns, every role, the copies and the repeats
that the rules must find, invented customers and products, the same bytes for the same seed, and one damaged copy for each rule a file can break. The workbook
is read here with openpyxl and its roles are counted again here: nothing of the package under test is used."""

from __future__ import annotations

import hashlib
import io
import re
import zipfile
from collections import Counter
from datetime import date, datetime
from pathlib import Path

import openpyxl
import pytest

from tests.fixtures import make_workbook as mw

PROJECT = Path(__file__).resolve().parents[2]
HEADER = ("Invoice", "StockCode", "Description", "Quantity", "InvoiceDate", "Price", "Customer ID", "Country")
PRODUCT = re.compile(r"\d{5}[A-Za-z]{0,3}")


def read_sheets(zip_path: Path, member: str = "online_retail_II.xlsx") -> dict[str, list[tuple]]:
    with zipfile.ZipFile(zip_path) as archive:
        data = archive.read(member)
    book = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    try:
        return {name: [tuple(row) for row in book[name].iter_rows(values_only=True)] for name in book.sheetnames}
    finally:
        book.close()


def role(invoice, code, quantity, price, customer) -> str:
    """RF04 again, written differently from the generator's: the first condition that holds."""
    invoice = str(invoice)
    if invoice[:1] == "C":
        return "cancellation"
    if invoice[:1] == "A":
        return "adjustment"
    if not PRODUCT.fullmatch(str(code)):
        return "non_product"
    if min(price, quantity) <= 0:
        return "bad_price"
    return "guest_purchase" if customer is None else "purchase"


@pytest.fixture(scope="module")
def sheets(workbook):
    return read_sheets(workbook.zip_path)


def canonical(sheets: dict[str, list[tuple]]) -> list[tuple]:
    """The first sheet and the rows of the second that are not copies of it: the copies are the rows of the second sheet up to the last day of the first."""
    first, second = (rows[1:] for rows in sheets.values())
    last = max(row[4] for row in first).date()
    return first + [row for row in second if row[4].date() > last]


# --- the workbook ---------------------------------------------------------------------------------------------------------


def test_the_fixture_workbook_has_the_real_sheets_columns_and_every_role(workbook, sheets):
    with zipfile.ZipFile(workbook.zip_path) as archive:
        assert archive.namelist() == ["online_retail_II.xlsx"]
        member = archive.read("online_retail_II.xlsx")
    assert (workbook.zip_bytes, workbook.zip_sha256) == (workbook.zip_path.stat().st_size, hashlib.sha256(workbook.zip_path.read_bytes()).hexdigest())
    assert (workbook.member_bytes, workbook.member_sha256) == (len(member), hashlib.sha256(member).hexdigest())
    assert list(sheets) == ["Year 2009-2010", "Year 2010-2011"]
    for rows in sheets.values():
        assert rows[0] == HEADER
    first, second = (rows[1:] for rows in sheets.values())
    assert 5000 <= len(second) <= 8000 and len(first) < len(second) / 10, "about 6,000 lines, the first sheet only the week it shares"
    # every cell has the type that the real workbook delivers through openpyxl (measured on its first rows)
    for row in first + second:
        invoice, code, description, quantity, stamp, price, customer, country = row
        assert isinstance(invoice, (int, str)) and isinstance(code, (int, str)) and isinstance(quantity, int) and isinstance(price, (int, float))
        assert isinstance(description, str) and isinstance(country, str) and (customer is None or isinstance(customer, int))
        assert isinstance(stamp, datetime) and stamp.second == 0 and date(2010, 12, 6) <= stamp.date() <= date(2011, 4, 22)
    # invented customers and products: nothing that the real file holds
    assert {row[6] for row in second} - {None} <= set(range(90001, 90301)) and len({row[6] for row in second} - {None}) == 300
    products = {int(row[1]) for row in second if str(row[1]).isdigit()}
    assert products and min(products) >= 95000 and max(products) <= 99999 and len(products) <= 400
    described = {row[2] for row in second if str(row[1]).isdigit() and row[3] > 0}
    assert all(re.fullmatch(r"PRODUCTO SINTÉTICO \d+", text) or "<script>" in text or text == "damaged" for text in described)
    assert any("<script>" in text for text in described), "a description with markup, for the escaping of every output"
    # every role of RF04, counted again here, and the counts the fixture says it holds
    rows = canonical(sheets)
    roles = Counter(role(row[0], row[1], row[3], row[5], row[6]) for row in rows)
    assert set(roles) == {"cancellation", "adjustment", "non_product", "bad_price", "guest_purchase", "purchase"}
    assert all(count >= 3 for count in roles.values()) and roles["purchase"] > 3 * sum(count for name, count in roles.items() if name != "purchase")
    truth = workbook.truth
    assert dict(roles) == truth.roles and len(rows) == truth.canonical_lines
    assert {name: len(sheet) - 1 for name, sheet in sheets.items()} == truth.sheet_rows
    assert len({row[6] for row in rows} - {None}) == truth.customers and len({row[0] for row in rows}) == truth.invoices
    assert (truth.first_day, truth.last_day) == (date(2010, 12, 6), date(2011, 4, 22))
    invoices = {row[0]: row[6] is None for row in rows if str(row[0])[0] not in "CA"}
    assert 0.12 < sum(invoices.values()) / len(invoices) < 0.22, "about a sixth of the invoices are guests'"


def test_the_week_in_both_sheets_is_the_same_rows_and_the_repeats_are_inside_the_sheets(workbook, sheets):
    first, second = (rows[1:] for rows in sheets.values())
    assert max(row[4] for row in first).date() <= date(2010, 12, 12)
    assert min(row[4] for row in first).date() >= date(2010, 12, 6)
    copies = [row for row in second if row[4].date() <= date(2010, 12, 12)]
    assert copies == first and len(copies) == workbook.truth.overlap_copies > 100, "the second sheet holds the first one's rows again, in the same order"
    rows = canonical(sheets)
    repeated = sum(count - 1 for count in Counter(rows).values())
    assert repeated == workbook.truth.internal_repeats >= 10
    assert any(count > 1 for row, count in Counter(first).items()), "one repeat is inside the shared week, so both sheets hold it"
    assert len(rows) == workbook.truth.canonical_lines == len(second), "dropping the copies leaves the second sheet's rows"
    # customers buy again what they bought before
    seen: dict[tuple, set] = {}
    for row in rows:
        if role(row[0], row[1], row[3], row[5], row[6]) == "purchase":
            seen.setdefault((row[6], row[1]), set()).add(row[0])
    assert sum(len(invoices) > 1 for invoices in seen.values()) > 100


def test_the_same_seed_gives_the_same_bytes_and_another_seed_other_bytes(workbook, tmp_path):
    small = mw.make_workbook(tmp_path / "small", customers=20)
    again = mw.make_workbook(tmp_path / "again", customers=20)
    assert small.zip_path.read_bytes() == again.zip_path.read_bytes() and small.zip_sha256 == again.zip_sha256 and small.truth == again.truth
    assert small.truth.customers == 20 and small.truth.canonical_lines < workbook.truth.canonical_lines / 5
    other = mw.make_workbook(tmp_path / "other", seed=1, customers=20)
    assert other.zip_sha256 != small.zip_sha256 and other.truth != small.truth
    assert zipfile.ZipFile(workbook.zip_path).infolist()[0].date_time == (2024, 1, 5, 0, 0, 0)
    with zipfile.ZipFile(workbook.zip_path) as archive, zipfile.ZipFile(io.BytesIO(archive.read("online_retail_II.xlsx"))) as xlsx:
        properties = xlsx.read("docProps/core.xml").decode("utf-8")
        assert {info.date_time for info in xlsx.infolist()} == {(2024, 1, 5, 0, 0, 0)}
    assert re.findall(r"<dcterms:(?:created|modified)[^>]*>([^<]*)<", properties) == ["2024-01-05T00:00:00Z", "2024-01-05T00:00:00Z"], "no time of the save in the bytes"


def test_no_invented_code_or_customer_is_in_the_real_range():
    """The real customers go from 12346 to 18287 and the product codes of the part of the file before 2011-08-01 up to 90214 (D44's check, below, with the data)."""
    assert min(mw.CUSTOMERS) == 90001 and max(mw.CUSTOMERS) == 90300 > 18287
    assert min(mw.PRODUCT_CODES) >= 95000 and len(set(mw.PRODUCT_CODES)) == 400 and max(mw.PRODUCT_CODES) <= 99999


@pytest.mark.real_data
def test_no_invented_code_is_a_real_code_before_the_test_window():
    """D44: no code of the real archive, nor its five-digit prefix, is one of the invented ones. The research cache is read with the filter of project 08's
    planner (nothing from 2011-08-01), and the filter is asserted."""
    pq = pytest.importorskip("pyarrow.parquet")
    cache = PROJECT / "data" / "interim" / "analysis.parquet"
    if not cache.exists():
        pytest.skip("the research cache data/interim/analysis.parquet is not there")
    table = pq.read_table(cache, columns=["StockCode", "InvoiceDate"], filters=[("InvoiceDate", "<", datetime(2011, 8, 1))])
    assert max(table["InvoiceDate"].to_pylist()) < datetime(2011, 8, 1)
    prefixes = {match.group(0) for code in set(table["StockCode"].to_pylist()) if (match := re.match(r"\d{5}", str(code)))}
    assert prefixes and not prefixes & {str(code) for code in mw.PRODUCT_CODES}


# --- the damaged copies ----------------------------------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def variants(workbook, tmp_path_factory):
    folder = tmp_path_factory.mktemp("variants")
    return {kind: mw.make_malformed(workbook, kind, folder) for kind in mw.MALFORMED_KINDS}


def inner_names(path: Path, member: str = "online_retail_II.xlsx") -> list[str]:
    with zipfile.ZipFile(path) as archive, zipfile.ZipFile(io.BytesIO(archive.read(member))) as xlsx:
        return xlsx.namelist()


def test_there_is_one_damaged_copy_for_each_rule_a_file_can_break(variants):
    assert set(mw.MALFORMED_KINDS) == set(variants) and len(variants) == 14
    assert {variant.rule for variant in variants.values()} == {"V01", "V02", "V03", "V04", "V05", "V06", "V07"}
    assert {kind: variant.rule for kind, variant in variants.items()} == {
        "wrong_hash": "V01", "extra_member": "V02", "renamed_member": "V02", "macro_part": "V03", "external_link": "V03", "zip_bomb_part": "V03",
        "extra_sheet": "V04", "missing_sheet": "V04", "extra_column": "V05", "missing_column": "V05", "reordered_columns": "V05",
        "wrong_type": "V06", "too_many_rows": "V06", "date_out_of_range": "V07",
    }


def test_each_variant_is_damaged_in_the_documented_way_and_carries_what_the_rule_under_test_needs(workbook, variants):
    base = workbook.zip_path.read_bytes()
    wrong = variants["wrong_hash"]
    data = wrong.workbook.zip_path.read_bytes()
    assert len(data) == len(base) and sum(a != b for a, b in zip(data, base, strict=True)) == 1 and hashlib.sha256(data).hexdigest() != workbook.zip_sha256
    assert (wrong.workbook.zip_bytes, wrong.workbook.zip_sha256) == (workbook.zip_bytes, workbook.zip_sha256), "the base's size and hash are the accepted ones"
    for kind, variant in variants.items():
        if kind == "wrong_hash":
            continue
        file = variant.workbook.zip_path.read_bytes()
        assert (variant.workbook.zip_bytes, variant.workbook.zip_sha256) == (len(file), hashlib.sha256(file).hexdigest()), f"{kind}: V01 must pass"
    assert zipfile.ZipFile(variants["extra_member"].workbook.zip_path).namelist() == ["online_retail_II.xlsx", "notes.txt"]
    assert zipfile.ZipFile(variants["renamed_member"].workbook.zip_path).namelist() == ["retail.xlsx"]
    assert "xl/vbaProject.bin" in inner_names(variants["macro_part"].workbook.zip_path)
    assert "xl/externalLinks/externalLink1.xml" in inner_names(variants["external_link"].workbook.zip_path)
    bomb = variants["zip_bomb_part"]
    with zipfile.ZipFile(bomb.workbook.zip_path) as archive, zipfile.ZipFile(io.BytesIO(archive.read("online_retail_II.xlsx"))) as xlsx:
        info = xlsx.getinfo("xl/media/padding.bin")
    assert info.file_size == 6_000_000 > bomb.overrides["max_part_bytes"] == 4_000_000 and info.file_size / info.compress_size > 500
    assert list(read_sheets(variants["extra_sheet"].workbook.zip_path)) == [*mw.SHEETS, "Notes"]
    assert list(read_sheets(variants["missing_sheet"].workbook.zip_path)) == [mw.SHEETS[0]]
    assert read_sheets(variants["extra_column"].workbook.zip_path)[mw.SHEETS[1]][0] == (*HEADER, "Notes")
    assert read_sheets(variants["missing_column"].workbook.zip_path)[mw.SHEETS[1]][0] == HEADER[:-1]
    swapped = list(HEADER)
    swapped[3], swapped[5] = swapped[5], swapped[3]
    assert read_sheets(variants["reordered_columns"].workbook.zip_path)[mw.SHEETS[1]][0] == tuple(swapped)
    assert len(read_sheets(variants["wrong_type"].workbook.zip_path)[mw.SHEETS[1]]) == 251, "a damaged copy keeps 250 rows of each sheet"
    typed = read_sheets(variants["wrong_type"].workbook.zip_path)[mw.SHEETS[1]]
    assert [row[3] for row in typed if not isinstance(row[3], int) and row[3] != "Quantity"] == ["ten"]
    late = read_sheets(variants["date_out_of_range"].workbook.zip_path)[mw.SHEETS[1]]
    assert [row[4] for row in late[1:] if row[4].date() > date(2011, 4, 22)] == [datetime(2012, 1, 1, 10, 0)]
    rows = {name: len(sheet) - 1 for name, sheet in read_sheets(variants["too_many_rows"].workbook.zip_path).items()}
    assert variants["too_many_rows"].overrides == {"max_rows": max(rows.values()) - 1} and variants["too_many_rows"].workbook.zip_bytes == workbook.zip_bytes
    for kind in ("extra_sheet", "extra_column", "missing_column", "reordered_columns", "wrong_type", "date_out_of_range"):
        assert variants[kind].overrides == {}, kind


def test_an_unknown_kind_is_refused_by_name(workbook, tmp_path):
    with pytest.raises(ValueError, match="no_such_kind"):
        mw.make_malformed(workbook, "no_such_kind", tmp_path)
    assert list(tmp_path.iterdir()) == []
