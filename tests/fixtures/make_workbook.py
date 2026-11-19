"""The synthetic workbook of the tests and of the quick mode (U03; plan section 24; decision D44): a zip with the two-sheet workbook of UCI Online Retail II,
built from invented customers and products, with every special row of the real file.

``make_workbook`` writes ``online_retail_fixture.zip`` holding ``online_retail_II.xlsx`` (the real member name, the two real sheet names and the eight real
columns). It is deterministic for a seed, down to the bytes of the zip: the workbook's properties carry a fixed date and the parts are repacked with a fixed
time. Nothing here imports the package under test: the truth it reports is worked out from the generated rows with its own rules.

* Customers are ``90001`` to ``90300`` and products ``95000``, ``95012`` ... ``99788`` (400 codes), described as «PRODUCTO SINTÉTICO n», all outside the real
  ranges (customers 12346 to 18287; product codes up to 90214, plus their letters, in the part of the real file before 2011-08-01), so a byte search finds any
  of them in an output. D44 asked for the range 90000-99999 if no real code fell in it, and four real codes do (90050, 90075, 90100, 90150): this range does
  not. The last product's description carries markup, to test that every output escapes it.
* The calendar is the quick mode's: the first sheet holds the week of 2010-12-06 and the second holds every day from 2010-12-06 to 2011-04-22, so that week is in
  both sheets, as December 2010 is in the real ones (the copies of the second sheet are the ones to drop). Some rows are repeated inside a sheet.
* Every role of requirements RF04 is there: cancellations («C» invoices), adjustments («A» invoices with a service code), service codes inside invoices, zero
  prices and negative quantities outside a cancellation, lines without a customer (about a sixth of the invoices) and the purchases, in which each customer
  buys again what they bought before.

``make_malformed`` damages a valid fixture in one documented way for each rule of the source that a file can break (``MALFORMED_KINDS``); the variant it returns
carries the accepted size and hash of what it wrote (so the rule under test is the one that fires, not V01) and the settings of ``[source]`` it needs.
"""

from __future__ import annotations

import hashlib
import io
import re
import zipfile
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np
import openpyxl

ZIP_NAME = "online_retail_fixture.zip"
MEMBER = "online_retail_II.xlsx"
SHEETS = ("Year 2009-2010", "Year 2010-2011")
COLUMNS = ("Invoice", "StockCode", "Description", "Quantity", "InvoiceDate", "Price", "Customer ID", "Country")
FIRST_DAY = date(2010, 12, 6)
LAST_DAY = date(2011, 4, 22)
OVERLAP_END = date(2010, 12, 12)      # the first sheet holds the week FIRST_DAY .. OVERLAP_END, and the second sheet holds it again
CUSTOMER_FIRST, CUSTOMER_LAST = 90_001, 90_300      # the invented customers; what no published file may hold is a number in this range (``tests.fixtures.published``)
CUSTOMERS = tuple(range(CUSTOMER_FIRST, CUSTOMER_LAST + 1))
PRODUCT_CODES = tuple(95000 + 12 * n for n in range(400))   # the real archive has codes up to 90214: nothing from 91000 on
FIRST_INVOICE = 590000
CATALOGUE_REGEX = re.compile(r"\d{5}[A-Za-z]{0,3}")
FIXED_TIME = datetime(2024, 1, 5, 0, 0, 0)
ZIP_TIME = (2024, 1, 5, 0, 0, 0)
SERVICE_LINES = (("POST", "POSTAGE", 18.0), ("DOT", "DOTCOM POSTAGE", 35.5), ("M", "Manual", 12.75), ("BANK CHARGES", "Bank Charges", 15.0),
                 ("PADS", "PADS TO MATCH ALL CUSHIONS", 0.001), ("D", "Discount", 8.5))
QUANTITIES = (1, 2, 3, 4, 6, 12, 24)
QUANTITY_WEIGHTS = (0.25, 0.15, 0.10, 0.10, 0.15, 0.17, 0.08)
PRICES = (0.42, 0.85, 1.25, 1.65, 2.1, 2.95, 3.75, 4.95, 6.35, 8.5, 12.75, 16.95)
OTHER_COUNTRIES = ("France", "Germany", "EIRE")
MALFORMED_KINDS = (
    "wrong_hash", "extra_member", "renamed_member", "macro_part", "external_link", "zip_bomb_part", "extra_sheet", "missing_sheet",
    "extra_column", "missing_column", "reordered_columns", "wrong_type", "date_out_of_range", "too_many_rows",
)
# The rule of the plan's section 6 that each variant must fail
EXPECTED_RULE = {
    "wrong_hash": "V01", "extra_member": "V02", "renamed_member": "V02", "macro_part": "V03", "external_link": "V03", "zip_bomb_part": "V03",
    "extra_sheet": "V04", "missing_sheet": "V04", "extra_column": "V05", "missing_column": "V05", "reordered_columns": "V05",
    "wrong_type": "V06", "too_many_rows": "V06", "date_out_of_range": "V07",
}

Row = tuple   # (invoice, stock code, description, quantity, timestamp, price, customer or None, country)


@dataclass(frozen=True)
class FixtureTruth:
    """What every rule must count on the valid fixture, worked out from the generated rows (never read back from the workbook)."""

    sheet_rows: dict[str, int]
    overlap_copies: int                 # rows of the second sheet that the first sheet holds too: all the rows of the first sheet
    canonical_lines: int                # the rows that are left after dropping those copies
    internal_repeats: int               # canonical lines equal to an earlier one of their own sheet
    roles: dict[str, int]               # cancellation, adjustment, non_product, bad_price, guest_purchase, purchase (RF04's order)
    customers: int                      # distinct customers with a line
    invoices: int
    first_day: date
    last_day: date


@dataclass(frozen=True)
class FixtureWorkbook:
    zip_path: Path
    zip_bytes: int
    zip_sha256: str
    member: str
    member_bytes: int
    member_sha256: str
    truth: FixtureTruth | None = None


@dataclass(frozen=True)
class Variant:
    """A damaged copy: the file, the accepted size and hash of what was written, and the keys of ``[source]`` that the variant needs to reach its rule."""

    kind: str
    rule: str
    workbook: FixtureWorkbook
    overrides: dict = field(default_factory=dict)


# --- the rows ------------------------------------------------------------------------------------------------------------


def role_of(invoice: object, code: object, quantity: int, price: float, customer: int | None) -> str:
    """RF04, in its order."""
    text = str(invoice)
    if text.startswith("C"):
        return "cancellation"
    if text.startswith("A"):
        return "adjustment"
    if CATALOGUE_REGEX.fullmatch(str(code)) is None:
        return "non_product"
    if price <= 0 or quantity <= 0:
        return "bad_price"
    if customer is None:
        return "guest_purchase"
    return "purchase"


def _stamp(rng: np.random.Generator, day: date) -> datetime:
    return datetime(day.year, day.month, day.day, int(rng.integers(8, 20)), int(rng.integers(0, 60)))


def generate_rows(seed: int = 0, customers: int = len(CUSTOMERS)) -> list[Row]:
    """Every row of the fixture in time order (the duplicates of the internal repeats included), before it is split into sheets. `customers` fewer than the 300
    make a smaller fixture with the same rules (the tests that only need the same bytes twice use one)."""
    rng = np.random.default_rng(seed)
    days = (LAST_DAY - FIRST_DAY).days + 1
    weights = 1.0 / (np.arange(1, len(PRODUCT_CODES) + 1) ** 0.8)
    popularity = rng.permutation(weights / weights.sum())
    price_of = {code: PRICES[(n * 7) % len(PRICES)] for n, code in enumerate(PRODUCT_CODES)}
    description_of = {code: f"PRODUCTO SINTÉTICO {n + 1}" for n, code in enumerate(PRODUCT_CODES)}
    description_of[PRODUCT_CODES[-1]] = '<script>alert("x")</script> PRODUCTO SINTÉTICO 400'
    # an invoice before numbering: (timestamp, kind, customer, country, [(code, description, quantity, price)])
    invoices: list[tuple] = []
    for customer in CUSTOMERS[:customers]:
        favourites = rng.choice(len(PRODUCT_CODES), size=12, replace=False, p=popularity)
        country = "United Kingdom" if rng.random() < 0.9 else OTHER_COUNTRIES[int(rng.integers(0, len(OTHER_COUNTRIES)))]
        day = float(rng.uniform(0, 30))
        while day < days:
            lines, chosen = [], set()
            for _ in range(int(rng.integers(2, 9))):
                index = int(rng.choice(favourites)) if rng.random() < 0.65 else int(rng.choice(len(PRODUCT_CODES), p=popularity))
                if index in chosen:
                    continue
                chosen.add(index)
                code = PRODUCT_CODES[index]
                quantity = int(rng.choice(QUANTITIES, p=QUANTITY_WEIGHTS))
                lines.append((code, description_of[code], quantity, price_of[code]))
            if rng.random() < 0.08:
                code, description, price = SERVICE_LINES[int(rng.integers(0, len(SERVICE_LINES)))]
                lines.append((code, description, 1, price))
            if rng.random() < 0.02:
                code = PRODUCT_CODES[int(rng.integers(0, len(PRODUCT_CODES)))]
                lines.append((code, description_of[code], int(rng.integers(1, 5)), 0.0))          # a zero price
            stamp = _stamp(rng, FIRST_DAY + timedelta(days=int(day)))
            invoices.append((stamp, "purchase", customer, country, lines))
            if rng.random() < 0.06 and int(day) + 1 < days:     # a cancellation of some of its lines, one to ten days later
                later = min(days - 1, int(day) + int(rng.integers(1, 11)))
                kept = [line for line in lines if rng.random() < 0.6] or lines[:1]
                invoices.append((_stamp(rng, FIRST_DAY + timedelta(days=later)), "cancellation", customer, country,
                                 [(c, d, -q, p) for c, d, q, p in kept if q > 0]))
            day += max(2.0, float(rng.exponential(42.0)))
    for _ in range(round(250 * customers / len(CUSTOMERS))):      # guests: invoices without a customer
        lines = []
        for index in {int(i) for i in rng.choice(len(PRODUCT_CODES), size=int(rng.integers(1, 7)), p=popularity)}:
            code = PRODUCT_CODES[index]
            lines.append((code, description_of[code], int(rng.choice(QUANTITIES, p=QUANTITY_WEIGHTS)), price_of[code]))
        invoices.append((_stamp(rng, FIRST_DAY + timedelta(days=int(rng.integers(0, days)))), "purchase", None, "United Kingdom", lines))
    for _ in range(4):                                           # damaged goods: a negative quantity and a zero price outside a cancellation
        code = PRODUCT_CODES[int(rng.integers(0, len(PRODUCT_CODES)))]
        invoices.append((_stamp(rng, FIRST_DAY + timedelta(days=int(rng.integers(0, days)))), "purchase", None, "United Kingdom",
                         [(code, "damaged", -int(rng.integers(1, 4)), 0.0)]))
    for _ in range(3):                                           # adjustments: an «A» invoice with a service code and no customer
        invoices.append((_stamp(rng, FIRST_DAY + timedelta(days=int(rng.integers(0, days)))), "adjustment", None, "United Kingdom",
                         [("B", "Adjust bad debt", 1, float(rng.integers(100, 900)))]))
    invoices = [invoice for invoice in invoices if invoice[0].date() <= LAST_DAY]
    invoices.sort(key=lambda invoice: (invoice[0], str(invoice[1]), invoice[2] or 0))
    rows: list[Row] = []
    for number, (stamp, kind, customer, country, lines) in enumerate(invoices):
        invoice: object = FIRST_INVOICE + number
        if kind == "cancellation":
            invoice = f"C{invoice}"
        elif kind == "adjustment":
            invoice = f"A{invoice}"
        for code, description, quantity, price in lines:
            stock_code: object = code if isinstance(code, str) else int(code)   # the real file stores a code of digits only as a number
            rows.append((invoice, stock_code, description, quantity, stamp, price, customer, country))
    # internal repeats: a line written twice in a row, one of them inside the week that both sheets hold
    inside = [i for i, row in enumerate(rows) if row[4].date() <= OVERLAP_END]
    chosen = {inside[len(inside) // 2]} | {int(i) for i in rng.choice(len(rows), size=40, replace=False)}
    repeated: list[Row] = []
    for index, row in enumerate(rows):
        repeated.append(row)
        if index in chosen:
            repeated.append(row)
    return repeated


def split_sheets(rows: list[Row]) -> dict[str, list[Row]]:
    """The first sheet holds the week of FIRST_DAY and the second holds everything."""
    return {SHEETS[0]: [row for row in rows if row[4].date() <= OVERLAP_END], SHEETS[1]: list(rows)}


def worked_out_truth(rows: list[Row]) -> FixtureTruth:
    """The counts every rule must find, from the rows and by the rules of RF03 and RF04 written again here."""
    sheets = split_sheets(rows)
    canonical = sheets[SHEETS[0]] + [row for row in sheets[SHEETS[1]] if row[4].date() > OVERLAP_END]
    seen: set[tuple] = set()
    repeats = 0
    for row in canonical:
        repeats += row in seen
        seen.add(row)
    roles = dict.fromkeys(("cancellation", "adjustment", "non_product", "bad_price", "guest_purchase", "purchase"), 0)
    for invoice, code, _description, quantity, _stamp_, price, customer, _country in canonical:
        roles[role_of(invoice, code, quantity, price, customer)] += 1
    return FixtureTruth(
        sheet_rows={name: len(sheet) for name, sheet in sheets.items()}, overlap_copies=len(sheets[SHEETS[0]]), canonical_lines=len(canonical),
        internal_repeats=repeats, roles=roles, customers=len({row[6] for row in canonical if row[6] is not None}),
        invoices=len({row[0] for row in canonical}), first_day=min(row[4].date() for row in rows), last_day=max(row[4].date() for row in rows),
    )


# --- the files ------------------------------------------------------------------------------------------------------------


def build_xlsx(sheets: dict[str, list[tuple]], header: tuple[str, ...] = COLUMNS, extra_parts: dict[str, bytes] | None = None) -> bytes:
    """A workbook with these sheets (the header, then the rows) as the bytes of a zip with fixed times; `extra_parts` are added to the package."""
    book = openpyxl.Workbook(write_only=True)
    book.properties.created = book.properties.modified = FIXED_TIME
    book.properties.creator = "personaloffers fixture"
    for name, rows in sheets.items():
        sheet = book.create_sheet(name)
        sheet.append(list(header))
        for row in rows:
            sheet.append(list(row))
    raw = io.BytesIO()
    book.save(raw)
    with zipfile.ZipFile(raw) as source:
        parts = {info.filename: source.read(info.filename) for info in source.infolist()}
    # openpyxl stamps the time of the save in the properties, whatever they were set to: put the fixed one back
    parts["docProps/core.xml"] = re.sub(rb"(<dcterms:modified[^>]*>)[^<]*(</dcterms:modified>)", rb"\g<1>2024-01-05T00:00:00Z\g<2>", parts["docProps/core.xml"])
    parts.update(extra_parts or {})
    return repack(parts)


def repack(parts: dict[str, bytes]) -> bytes:
    """The parts as a zip with a fixed time and compression, in the order given."""
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in parts.items():
            info = zipfile.ZipInfo(name, ZIP_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, data)
    return out.getvalue()


def write_zip(path: Path, members: dict[str, bytes], truth: FixtureTruth | None = None, member: str = MEMBER) -> FixtureWorkbook:
    """Write a zip with these members and return its accepted size and hash and those of `member` (empty when it is not there)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = repack(members)
    path.write_bytes(data)
    inner = members.get(member, b"")
    return FixtureWorkbook(zip_path=path, zip_bytes=len(data), zip_sha256=hashlib.sha256(data).hexdigest(), member=member, member_bytes=len(inner),
                           member_sha256=hashlib.sha256(inner).hexdigest() if inner else "", truth=truth)


def make_workbook(out_dir: Path, seed: int = 0, customers: int = len(CUSTOMERS)) -> FixtureWorkbook:
    """Write ``online_retail_fixture.zip`` in `out_dir` (created if needed) and return it with the truth of its rows."""
    rows = generate_rows(seed, customers)
    xlsx = build_xlsx(split_sheets(rows))
    return write_zip(Path(out_dir) / ZIP_NAME, {MEMBER: xlsx}, worked_out_truth(rows))


# --- the damaged copies ------------------------------------------------------------------------------------------------------


def _member_of(fixture: FixtureWorkbook) -> bytes:
    with zipfile.ZipFile(fixture.zip_path) as archive:
        return archive.read(fixture.member)


def _parts_of(fixture: FixtureWorkbook) -> dict[str, bytes]:
    with zipfile.ZipFile(io.BytesIO(_member_of(fixture))) as xlsx:
        return {info.filename: xlsx.read(info.filename) for info in xlsx.infolist()}


SMALL_SHEET = 250   # rows of each sheet that a damaged copy keeps: a rule needs one defect, not six thousand lines (and writing them costs a second)


_ROWS_CACHE: dict[tuple, dict[str, list[tuple]]] = {}   # keyed by the path, the hash and the limit: a path written again with other bytes is read again


def _rows_of(fixture: FixtureWorkbook, limit: int = SMALL_SHEET) -> dict[str, list[tuple]]:
    """The first `limit` rows of each sheet of the fixture, read back with openpyxl (once for each file and limit)."""
    key = (str(fixture.zip_path), fixture.zip_sha256, limit)
    if key not in _ROWS_CACHE:
        book = openpyxl.load_workbook(io.BytesIO(_member_of(fixture)), read_only=True, data_only=True)
        try:
            _ROWS_CACHE[key] = {name: [tuple(row) for row in book[name].iter_rows(min_row=2, max_row=limit + 1, values_only=True)] for name in book.sheetnames}
        finally:
            book.close()
    return {name: list(rows) for name, rows in _ROWS_CACHE[key].items()}


def make_malformed(base: FixtureWorkbook, kind: str, out_dir: Path) -> Variant:
    """The fixture damaged in one documented way (`kind` in ``MALFORMED_KINDS``), written to ``<out_dir>/<kind>.zip``.

    wrong_hash: the same size with one byte changed in the middle, so the zip is not the accepted one (V01, with the base's size and hash accepted).
    extra_member / renamed_member: a second file in the zip, or the workbook under another name (V02).
    macro_part / external_link: the package holds ``xl/vbaProject.bin`` or an external link (V03).
    zip_bomb_part: a part of six million zero bytes, over the cap of four million that the variant asks for and at a ratio of about a thousand (V03).
    extra_sheet / missing_sheet: a third sheet, or only the first one (V04).
    extra_column / missing_column / reordered_columns: a ninth column, no ``Country``, or ``Quantity`` and ``Price`` swapped in the header (V05).
    wrong_type: ``Quantity`` of one line is the text «ten» (V06).
    too_many_rows: the valid workbook with a limit of one row fewer than its sheets have (V06): the first sheet is the one that goes over.
    Every damaged copy keeps the first 250 rows of each sheet.
    date_out_of_range: one line dated 2012-01-01, after the last day of the source (V07).
    """
    if kind not in MALFORMED_KINDS:
        raise ValueError(f"unknown kind {kind!r}; the kinds are {MALFORMED_KINDS}")
    out_dir = Path(out_dir)
    path = out_dir / f"{kind}.zip"
    overrides: dict = {}
    members: dict[str, bytes]
    if kind == "wrong_hash":
        data = bytearray(base.zip_path.read_bytes())
        data[len(data) // 2] ^= 0x01
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(bytes(data))
        accepted = FixtureWorkbook(path, base.zip_bytes, base.zip_sha256, base.member, base.member_bytes, base.member_sha256)
        return Variant(kind, EXPECTED_RULE[kind], accepted, overrides)
    xlsx = _member_of(base)
    members = {MEMBER: xlsx}
    parts = _parts_of(base)
    sheets = _rows_of(base)
    if kind == "extra_member":
        members = {MEMBER: xlsx, "notes.txt": b"not a workbook"}
    elif kind == "renamed_member":
        members = {"retail.xlsx": xlsx}
    elif kind == "macro_part":
        members = {MEMBER: repack({**parts, "xl/vbaProject.bin": b"\xd0\xcf\x11\xe0 macros"})}
    elif kind == "external_link":
        members = {MEMBER: repack({**parts, "xl/externalLinks/externalLink1.xml": b"<externalLink/>"})}
    elif kind == "zip_bomb_part":
        members = {MEMBER: repack({**parts, "xl/media/padding.bin": bytes(6_000_000)})}
        overrides = {"max_part_bytes": 4_000_000}
    elif kind == "extra_sheet":
        members = {MEMBER: build_xlsx({**sheets, "Notes": [("a", "b")]})}
    elif kind == "missing_sheet":
        members = {MEMBER: build_xlsx({SHEETS[0]: sheets[SHEETS[0]]})}
    elif kind == "extra_column":
        members = {MEMBER: build_xlsx(sheets, header=(*COLUMNS, "Notes"))}
    elif kind == "missing_column":
        members = {MEMBER: build_xlsx({name: [row[:-1] for row in rows] for name, rows in sheets.items()}, header=COLUMNS[:-1])}
    elif kind == "reordered_columns":
        swapped = list(COLUMNS)
        swapped[3], swapped[5] = swapped[5], swapped[3]
        members = {MEMBER: build_xlsx(sheets, header=tuple(swapped))}
    elif kind == "wrong_type":
        broken = [list(row) for row in sheets[SHEETS[1]]]
        broken[len(broken) // 2][3] = "ten"
        members = {MEMBER: build_xlsx({**sheets, SHEETS[1]: [tuple(row) for row in broken]})}
    elif kind == "date_out_of_range":
        broken = [list(row) for row in sheets[SHEETS[1]]]
        broken[len(broken) // 2][4] = datetime(2012, 1, 1, 10, 0)
        members = {MEMBER: build_xlsx({**sheets, SHEETS[1]: [tuple(row) for row in broken]})}
    elif kind == "too_many_rows":
        members = {MEMBER: build_xlsx(sheets)}
        overrides = {"max_rows": SMALL_SHEET - 1}
    written = write_zip(path, members)
    return Variant(kind, EXPECTED_RULE[kind], written, overrides)
