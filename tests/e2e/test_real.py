"""What the complete real replay left (U21; AC03, AC04, AC37, AC40; RNF02, RNF03, RNF12; plan sections 13, 14, 16, 21 and 27; decisions D21, D30, D31).

Marks ``real_data``: not in the default suite. The tests read outputs and start no run: the first and only evaluation of the test window (lines dated 2011-08-01 or later) is the replay itself
(``python -m personaloffers replay``, in the real ``data/``), made once. Without its outputs these tests fail (they do not skip) and say which file is missing.

The criteria are never read here against their thresholds: whether C03 passed is the summary's to say. What is checked is that the seal, the warehouse, the summary and the site tell the same ten verdicts,
that the counts are the plan's, that every run closed in order, the limits of RNF02 and RNF03 with the name of the counter, and that nothing published or versioned carries a real customer number or a
cell of fewer customers than the minimum (D30).
"""

from __future__ import annotations

import json
import re
import sqlite3
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd
import pytest

from personaloffers import registry
from personaloffers.dashboard.semantic_model import CUSTOMER_COUNT_COLUMNS, MODEL
from personaloffers.evaluation import criteria_from_seal
from personaloffers.export import verify_star_schema
from personaloffers.site_export import read_site, verify_site
from personaloffers.sysinfo import POSIX_COUNTER, WINDOWS_COUNTER
from tests.fixtures.published import LOCAL_PATH, example_list_problems

pytestmark = pytest.mark.real_data

WEEKLY_RUNS, REPLAY_RUNS = 18, 20                       # one launch, 18 weekly deliveries and the close (D22)
SEALED_LAUNCH_RUN, SEALED_CLOSE_RUN = "20261119T234941422797Z", "20261120T000628680396Z"     # the runs that wrote the seal (L133); a rebuild (runbook R11) runs under other keys
# AC03 and AC04: what the real workbook holds (research.md; the counts of the whole file are U21's)
SHEET_ROWS, COPIES, LINES, INTERNAL_REPEATS = {"Year 2009-2010": 525_461, "Year 2010-2011": 541_910}, 22_523, 1_044_848, 11_812
GUEST_LINES, NON_PRODUCT_CODE_LINES = 235_287, 5_993
# RNF02 (seconds) and RNF03 (megabytes), AC37
MAX_READ_S, MAX_LAUNCH_S, MAX_WEEKLY_S, MAX_CLOSE_S, MAX_REPLAY_S = 5 * 60, 20 * 60, 60, 5 * 60, 45 * 60
MAX_PEAK_WORKING_SET_MB = 6 * 1024
MAX_PARQUET_BYTES = 25 * 1024 * 1024
MIN_CELL_CUSTOMERS = 10
# The real customer numbers that the hand-written files hold today, by file and number of tokens (they are not published, but D30 says none in anything versioned): the two ends of the real range in
# comments and checks of the fixture (its first and last number), the example cell of a reader test, a block of consecutive numbers that the newcomer-assignment tests feed to the assignment with the quick
# configuration's salt (not the sealed one), and a P4 line count in a research script. Reported to the evaluation (L133); not changed after the seal.
HAND_WRITTEN_WITH_REAL_NUMBERS = {"research/s06_split.py": 1, "src/personaloffers/workbook.py": 2, "tests/contract/test_workbook.py": 5, "tests/fixtures/make_workbook.py": 2,
                                  "tests/integration/test_holdout.py": 1, "tests/unit/test_fixture.py": 4, "tests/unit/test_holdout.py": 34}
HIDDEN_WHOLE = ("fact_round_group", "fact_method_round", "fact_method_total", "fact_segment", "fact_mde")
PRIVATE_TABLE = "fact_offer_customer"          # the one table with a customer: it is written to outputs/private/, which the repository ignores (D30)
PRODUCT_CODE_FIELDS = {"stock_code", "code", "product_code", "product_key"}      # a product code of five digits can equal a customer number: in these fields it is not one
IDENTITY_FIELDS = re.compile(r"(customer|contact|client|cliente)(_id|_number|_no)?|email|customer_id|contact_id", re.IGNORECASE)      # the names of K07, plus the ones a reader would give it
FIVE_DIGITS = re.compile(r"(?<![\w.,])\d{5}(?![\w])")
HASH = re.compile(r"[0-9a-f]{32,}")
TEXT_SUFFIXES = {".md", ".json", ".html", ".svg", ".toml", ".txt", ".sql", ".py", ".yaml", ".yml", ".csv", ".sh", ".cfg", ".ini"}
GENERATED_FOLDERS = ("outputs/powerbi", "outputs/site", "reports", "dashboard", "docs/figures")
GENERATED_PREFIXES = tuple(f"{folder}/" for folder in GENERATED_FOLDERS)
NOT_VERSIONED = ("outputs/private/", "data/", "reports/validation/history/")


def require(path: Path) -> Path:
    assert path.is_file(), f"falta {path.name}: la repetición real completa no corrió (python -m personaloffers replay)"
    return path


def seconds(started: str, finished: str) -> float:
    return (datetime.fromisoformat(finished) - datetime.fromisoformat(started)).total_seconds()


@pytest.fixture(scope="module")
def outputs(cfg):
    paths = cfg.paths
    seal_path, summary_path = require(Path(paths.seal)), require(Path(paths.reports_dir) / "evaluation_summary.json")
    warehouse = require(Path(paths.warehouse))
    read = {"seal": json.loads(seal_path.read_text(encoding="utf-8")), "summary": json.loads(summary_path.read_text(encoding="utf-8")), "site": read_site(Path(paths.site_dir)),
            "seal_path": seal_path, "powerbi": Path(paths.outputs_dir), "interim": Path(paths.interim_dir)}
    conn = sqlite3.connect(f"{warehouse.as_uri()}?mode=ro", uri=True)
    try:
        yield {"conn": conn, **read}
    finally:
        conn.close()


def _runs(conn):
    """The runs in the order they started, each a row read by its column's name."""
    cursor = conn.cursor()
    cursor.row_factory = sqlite3.Row
    return cursor.execute("SELECT p.run_key, p.started_at, p.finished_at, p.status, p.peak_working_set_mb, p.memory_counter, d.kind, p.delivery_id "
                          "FROM pipeline_runs p LEFT JOIN deliveries d ON d.delivery_id = p.delivery_id ORDER BY p.started_at").fetchall()


def _state(outputs, run_key: str) -> dict:
    return json.loads(require(outputs["interim"] / "runs" / f"{run_key}.json").read_text(encoding="utf-8"))


def test_real_counts_seal_and_summary_consistency(cfg, outputs):
    conn, seal, summary, site = outputs["conn"], outputs["seal"], outputs["summary"], outputs["site"]

    # AC03: the rows of both sheets, the copies removed, the canonical lines and the internal repeats marked
    counts = json.loads(require(outputs["interim"] / "source_counts.json").read_text(encoding="utf-8"))
    assert counts["rows_by_sheet"] == SHEET_ROWS and sum(SHEET_ROWS.values()) == 1_067_371
    assert counts["copies_removed"] == COPIES and counts["internal_repeats"] == INTERNAL_REPEATS
    assert conn.execute("SELECT COUNT(*), SUM(internal_repeat) FROM lines").fetchone() == (LINES, INTERNAL_REPEATS)
    assert sum(SHEET_ROWS.values()) - COPIES == LINES

    # AC04: the lines without a customer and the lines whose code is not a product (the roles keep their order of RF04, so a code outside the rule can sit in another role)
    assert conn.execute("SELECT COUNT(*) FROM lines WHERE customer_id IS NULL").fetchone()[0] == GUEST_LINES
    rule = re.compile(cfg.catalogue.product_code_regex)
    non_product = sum(count for code, count in conn.execute("SELECT stock_code, COUNT(*) FROM lines GROUP BY stock_code") if not rule.match(code))
    assert non_product == NON_PRODUCT_CODE_LINES
    assert dict(conn.execute("SELECT role, COUNT(*) FROM lines GROUP BY role")).keys() == {"purchase", "guest_purchase", "cancellation", "adjustment", "non_product", "bad_price"}

    # AC05: one launch, 18 weekly deliveries and the close, every one loaded
    deliveries = conn.execute("SELECT delivery_id, kind, status FROM deliveries ORDER BY CASE kind WHEN 'launch' THEN 0 WHEN 'weekly' THEN 1 ELSE 2 END, delivery_id").fetchall()
    assert [d[1] for d in deliveries] == ["launch"] + ["weekly"] * WEEKLY_RUNS + ["close"] and {d[2] for d in deliveries} == {"loaded"}
    assert deliveries[1][0] == "W2011-08-01" and deliveries[WEEKLY_RUNS][0] == "W2011-11-28" and deliveries[-1][0] == "C2011-12-05"
    assert conn.execute("SELECT COUNT(*) FROM eval_criteria WHERE seal_state != 'sealed'").fetchone()[0] == 0, "the test is evaluated once: no post-seal rows"

    # The seal: both parts, one configuration, and the criteria told the same in the seal, the warehouse, the summary and the site (D21)
    assert set(seal) == {"version", "launch", "test"} and seal["test"] is not None
    launch, test = seal["launch"], seal["test"]
    assert registry.read_seal(outputs["seal_path"]) == seal, "the seal is read back with the shape the code checks"
    runs = _runs(conn)
    observed = _state(outputs, runs[0]["run_key"])["tasks"]["fetch_source"]["source_sha256"]
    fingerprint = registry.config_fingerprint(registry.sealed_view(cfg, observed))
    assert launch["config_sha256"] == test["config_sha256"] == fingerprint == summary["config_sha256"] == site.summary["seal"]["launch"]["config_sha256"]
    assert registry.seal_state(outputs["seal_path"], fingerprint) == "match"
    sealed = criteria_from_seal(seal)
    assert [c.criterion_id for c in sealed] == [f"C{n:02d}" for n in range(1, 11)] == [c["id"] for c in test["criteria"]]
    assert summary["source"] == "warehouse" and site.summary["evaluation_status"] == "sealed" and site.summary["sealed_from"] == "warehouse"
    assert [c["criterion_id"] for c in summary["criteria"]] == [c["criterion_id"] for c in site.summary["criteria"]] == [c.criterion_id for c in sealed]
    own = {r[0]: r[1:] for r in conn.execute("SELECT criterion_id, passed, verdict_es FROM eval_criteria WHERE seal_state = 'sealed'")}
    assert sorted(own) == [c.criterion_id for c in sealed]
    for criterion, in_summary, on_site, in_seal in zip(sealed, summary["criteria"], site.summary["criteria"], test["criteria"], strict=True):
        assert in_summary["verdict_es"] == on_site["verdict_es"] == in_seal["verdict_es"] == own[criterion.criterion_id][1] == criterion.verdict_es, criterion.criterion_id
        assert in_summary["passed"] == on_site["passed"] == in_seal["passed"] == criterion.passed, criterion.criterion_id
        assert own[criterion.criterion_id][0] == (None if criterion.passed is None else int(criterion.passed)), criterion.criterion_id
    assert site.summary["seal"]["test"]["run_key"] == test["run_key"]

    # The runs: the launch, the 18 weekly deliveries and the close, each ok and in order. The seal keeps the keys of the runs that wrote it (L133); this warehouse's runs are those, or a rebuild
    # (runbook R11) whose launch adopted the sealed models without choosing again and whose close reproduced the seal without writing it
    assert [r["kind"] for r in runs[:REPLAY_RUNS]] == ["launch"] + ["weekly"] * WEEKLY_RUNS + ["close"] and {r["status"] for r in runs[:REPLAY_RUNS]} == {"ok"}
    assert len(runs) == REPLAY_RUNS or {r["status"] for r in runs[REPLAY_RUNS:]} == {"no_delivery"}
    assert (launch["run_key"], test["run_key"]) == (SEALED_LAUNCH_RUN, SEALED_CLOSE_RUN)
    chose, evaluated = _state(outputs, runs[0]["run_key"])["tasks"]["fit_recipe"], _state(outputs, runs[REPLAY_RUNS - 1]["run_key"])["tasks"]["evaluate"]
    if (runs[0]["run_key"], runs[REPLAY_RUNS - 1]["run_key"]) == (SEALED_LAUNCH_RUN, SEALED_CLOSE_RUN):
        assert (chose["mode"], chose["sealed"], evaluated["state"], evaluated["seal"]) == ("fresh", True, "first", "written"), "the sealed runs chose, sealed and wrote the test part"
    else:
        assert (chose["mode"], chose["seal_state"], evaluated["state"], evaluated["seal"]) == ("adopt", "match", "repeat", "unchanged"), "a rebuild adopts the sealed models and reproduces the seal (R11)"
    assert conn.execute("SELECT COUNT(*) FROM deliveries WHERE status != 'loaded'").fetchone()[0] == 0

    # AC37 (RNF03): the peak of the working set with the counter named, the files that were written and their size
    assert not verify_site(Path(cfg.paths.site_dir)) and not verify_star_schema(outputs["powerbi"])
    counter = WINDOWS_COUNTER if sys.platform == "win32" else POSIX_COUNTER
    assert {r["memory_counter"] for r in runs[:REPLAY_RUNS]} == {counter}
    assert max(r["peak_working_set_mb"] for r in runs[:REPLAY_RUNS]) <= MAX_PEAK_WORKING_SET_MB, f"el pico de {counter} pasa de 6 GB (RNF03)"
    parquets = sorted(outputs["powerbi"].glob("*.parquet"))
    assert {p.stem for p in parquets} == {t.name for t in MODEL.tables} - {PRIVATE_TABLE} and max(p.stat().st_size for p in parquets) <= MAX_PARQUET_BYTES


def test_no_example_list_of_the_site_can_single_out_a_customer_of_its_profile(outputs):
    """B1 of the evaluation (D30, D46): the three example lists of ``algorithms.json`` were one customer's list each, and within the published profile only 5, 1 and 2 customers had bought their seven
    repeat products. Counted within the profile and its round from the issued lists, no published list may be held whole by fewer than 10 customers, carry a customer's ranks or show a product held by
    fewer than 10."""
    examples = outputs["site"].algorithms["example_lists"]
    assert example_list_problems(outputs["conn"], examples, MIN_CELL_CUSTOMERS) == []
    assert len(examples) == 3 and all(e["kind"] == "aggregate" for e in examples)


def test_every_weekly_run_and_the_close_take_at_most_the_required_seconds(outputs):
    """RNF02 and AC37: reading the workbook, the launch with the choice, each weekly run, the close with the A/A and its calibration and the whole replay stay inside their limits. Every miss is
    listed in one message, so a miss of one limit does not hide another."""
    runs = _runs(outputs["conn"])[:REPLAY_RUNS]
    assert [r["kind"] for r in runs] == ["launch"] + ["weekly"] * WEEKLY_RUNS + ["close"]
    wall = [seconds(r["started_at"], r["finished_at"]) for r in runs]
    tasks = [_state(outputs, r["run_key"])["tasks"] for r in runs]
    worked = [sum(t["seconds"] for t in task.values()) for task in tasks]
    misses = []
    if tasks[0]["fetch_source"]["seconds"] > MAX_READ_S:
        misses.append(f"leer el libro y escribir las líneas: {tasks[0]['fetch_source']['seconds']} s (límite {MAX_READ_S})")
    if max(wall[0], worked[0]) > MAX_LAUNCH_S:
        misses.append(f"lanzamiento con la elección: {max(wall[0], worked[0]):.0f} s (límite {MAX_LAUNCH_S})")
    misses += [f"{r['delivery_id']}: {max(w, k):.0f} s (límite {MAX_WEEKLY_S})" for r, w, k in zip(runs[1:-1], wall[1:-1], worked[1:-1], strict=True) if max(w, k) > MAX_WEEKLY_S]
    if max(wall[-1], worked[-1]) > MAX_CLOSE_S:
        misses.append(f"cierre con el A/A y su calibración: {max(wall[-1], worked[-1]):.0f} s (límite {MAX_CLOSE_S})")
    whole = seconds(runs[0]["started_at"], runs[-1]["finished_at"])
    if whole > MAX_REPLAY_S:
        misses.append(f"repetición completa: {whole:.0f} s (límite {MAX_REPLAY_S})")
    assert misses == [], "; ".join(misses)


# --- privacy (D30): the real customer numbers of the archive -----------------------------------------------------------------


def _project_files(root: Path) -> list[Path]:
    """Everything that is, or would be, versioned (tracked and not ignored) plus every file of the generated folders on disk, without what the project keeps out on purpose (D30)."""
    listed = subprocess.run(["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z", "--", "."], cwd=root, capture_output=True, check=True).stdout.decode("utf-8")
    files = {root / name for name in listed.split("\0") if name}
    for folder in GENERATED_FOLDERS:
        files |= {p for p in (root / folder).rglob("*") if p.is_file()}
    return sorted(p for p in files if p.is_file() and not any(p.relative_to(root).as_posix().startswith(prefix) for prefix in NOT_VERSIONED) and ".venv" not in p.parts
                  and "__pycache__" not in p.parts)


def _tokens(text: str, customers: set[int]) -> list[str]:
    """The five-digit tokens of `text` that are a real customer number (a hash is read out first: its digits are not a number)."""
    return [token for token in FIVE_DIGITS.findall(HASH.sub(" ", text)) if int(token) in customers]


def _json_hits(node, customers: set[int], descriptions: set[str], path: str = "") -> tuple[list[str], list[str]]:
    """(leaks, coincidences) of a parsed JSON. A value that equals a customer number is a coincidence when it is a number under a key (a count or a size), a product code under a product-code field
    or a token inside a description that the source gives a product; it is a leak anywhere else (another text, a key, a bare value in a list, a field that is an identifier of a customer)."""
    leaks: list[str] = []
    coincidences: list[str] = []
    if isinstance(node, dict):
        for key, value in node.items():
            here = f"{path}/{key}"
            if FIVE_DIGITS.fullmatch(str(key)) and int(key) in customers:
                leaks.append(f"{here} (a key)")
            if IDENTITY_FIELDS.fullmatch(str(key)) and not isinstance(value, (dict, list)):
                leaks.append(f"{here} (a field that identifies a customer)")
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                if float(value).is_integer() and int(value) in customers:
                    coincidences.append(f"{here}={int(value)} (a number under a key)")
            elif isinstance(value, str) and FIVE_DIGITS.fullmatch(value) and int(value) in customers:
                (coincidences if str(key) in PRODUCT_CODE_FIELDS else leaks).append(f"{here}={value}")
            else:
                sub_leaks, sub_coincidences = _json_hits(value, customers, descriptions, here)
                leaks += sub_leaks
                coincidences += sub_coincidences
    elif isinstance(node, list):
        for index, value in enumerate(node):
            if isinstance(value, (str, int)) and not isinstance(value, bool) and FIVE_DIGITS.fullmatch(str(value)) and int(value) in customers:
                leaks.append(f"{path}[{index}]={value} (a bare value in a list)")
            else:
                sub_leaks, sub_coincidences = _json_hits(value, customers, descriptions, f"{path}[{index}]")
                leaks += sub_leaks
                coincidences += sub_coincidences
    elif isinstance(node, str):
        (coincidences if node in descriptions else leaks).extend(f"{path}: {token} inside a text" for token in _tokens(node, customers))
    return leaks, coincidences


def _parquet_hits(path: Path, customers: set[int], descriptions: set[str]) -> tuple[list[str], list[str]]:
    """(leaks, coincidences) of a Parquet file, by the same rule as ``_json_hits``, column by column (a numeric column is a count, a size or a key)."""
    table = pd.read_parquet(path)
    leaks: list[str] = []
    coincidences: list[str] = []
    for column in table.columns:
        if IDENTITY_FIELDS.fullmatch(column):
            leaks.append(f"{path.name}[{column}] (a column that identifies a customer)")
        series = table[column].dropna()
        if series.empty:
            continue
        if pd.api.types.is_numeric_dtype(series) and not pd.api.types.is_bool_dtype(series):
            numbers = series[series % 1 == 0].astype("int64")
            found = int(numbers.isin(customers).sum())
            if found:
                coincidences.append(f"{path.name}[{column}]: {found} numbers in a numeric column")
            continue
        for text in (str(v) for v in series):
            if re.fullmatch(r"\d{5}", text):
                if int(text) in customers:
                    (coincidences if column in PRODUCT_CODE_FIELDS else leaks).append(f"{path.name}[{column}]={text}")
            else:
                (coincidences if text in descriptions else leaks).extend(f"{path.name}[{column}]: {token} inside a text" for token in _tokens(text, customers))
    return leaks, coincidences


def test_no_real_customer_number_in_anything_versioned_or_published_and_no_cell_under_the_minimum(cfg, outputs):
    """RNF12 and D30, with the real archive (the check of the synthetic range of ``tests/fixtures/published.py`` does not cover these numbers).

    No customer number of the archive is in a published file (the Parquet files, the six site files and the seal, the summary, the design and the figures): a five-digit number that equals one is a
    coincidence only as a count under a key, a product code in a product-code field or a token inside a description that the source gives a product (63 customer numbers are also codes of the
    catalogue, and some descriptions end in one), and a leak in a key, a list, any other text or a field that identifies a customer. In the hand-written files (code, tests, notes) the numbers that
    are there today are pinned by file and count in ``HAND_WRITTEN_WITH_REAL_NUMBERS``: a number in another file, or one more, fails. And no published cell counts fewer customers than the minimum."""
    root = Path(__file__).resolve().parents[2]
    customers = {int(c) for (c,) in outputs["conn"].execute("SELECT DISTINCT customer_id FROM lines WHERE customer_id IS NOT NULL")}
    descriptions = {d for (d,) in outputs["conn"].execute("SELECT DISTINCT description FROM lines WHERE description IS NOT NULL")} | \
                   {d for (d,) in outputs["conn"].execute("SELECT DISTINCT description_es FROM products WHERE description_es IS NOT NULL")}
    assert len(customers) == 5_942 and min(customers) >= 10_000 and max(customers) <= 99_999
    leaks: list[str] = []
    coincidences: list[str] = []
    hand_written: dict[str, int] = {}
    for path in _project_files(root):
        name = path.relative_to(root).as_posix()
        generated = name.startswith(GENERATED_PREFIXES)
        if path.suffix == ".parquet":
            found = _parquet_hits(path, customers, descriptions)
        elif path.suffix == ".json" and generated:
            found = _json_hits(json.loads(path.read_text(encoding="utf-8")), customers, descriptions, name)
        elif path.suffix in TEXT_SUFFIXES:
            tokens = _tokens(path.read_text(encoding="utf-8", errors="replace"), customers)
            if generated:
                found = ([f"{name}: {token}" for token in tokens], [])
            else:
                hand_written.update({name: len(tokens)} if tokens else {})
                continue
        else:
            continue
        leaks += [f"{name}: {item}" for item in found[0]]
        coincidences += found[1]
    assert leaks == [], f"números de cliente del archivo real en lo publicado: {leaks[:10]}"
    assert hand_written == HAND_WRITTEN_WITH_REAL_NUMBERS, "the real customer numbers of the hand-written files are not the pinned ones (a file, or one more)"
    assert not any(LOCAL_PATH.search(p.read_text(encoding="utf-8", errors="replace")) for p in _project_files(root) if p.suffix in {".json", ".md", ".html", ".svg"}), "a path of this machine"
    assert subprocess.run(["git", "check-ignore", "-q", f"outputs/private/{PRIVATE_TABLE}.parquet"], cwd=root).returncode == 0, "the private list must stay out of the repository"
    assert not (outputs["powerbi"] / f"{PRIVATE_TABLE}.parquet").exists()

    # no published cell counts fewer customers than the minimum: what is shown has at least ten, and a hidden cell is empty (a zero is also under the minimum)
    for table, columns in CUSTOMER_COUNT_COLUMNS.items():
        frame = pd.read_parquet(outputs["powerbi"] / f"{table}.parquet")
        for column in columns:
            shown = frame[column].dropna()
            assert (shown >= MIN_CELL_CUSTOMERS).all(), f"{table}[{column}] shows a cell under {MIN_CELL_CUSTOMERS}: {sorted(shown[shown < MIN_CELL_CUSTOMERS])[:3]}"
        if table in HIDDEN_WHOLE:          # the round's operation and the product's purchases hide a column at a time (K02): a shown number of theirs is checked above
            assert frame.loc[frame["suppressed"], list(columns)].isna().all().all(), f"{table}: a hidden cell holds a number"
    assert len(coincidences) < 200, "a count equal to a customer number is a coincidence; this many would deserve a look"
