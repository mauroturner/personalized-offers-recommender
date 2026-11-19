"""No information from the future (U07; RF08, AC07; decision D23): the base of a round and its covariates are the same, bit for bit, if every line from its Monday on is removed or
changed; a function that is given one such line refuses; and the modules that compute them have no way to read the lines by themselves. U09 and U12 add the recommenders and the
lists to this file."""

from __future__ import annotations

import ast
import re
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import pytest

from personaloffers import base
from personaloffers import calendar as cal
from personaloffers.base import LeakageError

SRC = Path(__file__).resolve().parents[2] / "src" / "personaloffers"
CALCULATIONS = ("base.py", "holdout.py")      # the modules whose results enter a sealed value; U09 adds the recommenders


def bytes_of(frame: pd.DataFrame) -> bytes:
    """The whole table, every float with all its digits: two tables are the same when these bytes are."""
    return frame.to_csv(index=False, float_format="%.17g", lineterminator="\n").encode("utf-8")


def mondays(cfg) -> list:
    return [monday for period in cal.PERIODS for monday in cal.rounds(cfg, period)]


def table_for(lines: pd.DataFrame, monday, view) -> pd.DataFrame:
    """What a task does: cut the history for the round and compute everything from the cut."""
    return base.base_table(base.history_before(lines, monday), monday, view)


def test_lists_base_and_covariates_are_identical_when_every_line_from_the_monday_is_removed(fixture_lines, quick_view, quick_cfg):
    """AC07, the part of the base: for each round of the calendar, the base and the five covariates (and the invoices before) are the same bytes with the whole file, with every line
    from the Monday on removed, and with every one of those lines changed (their quantities, prices, customers and dates)."""
    checked = 0
    for monday in mondays(quick_cfg):
        midnight = datetime.combine(monday, datetime.min.time())
        everything = table_for(fixture_lines, monday, quick_view)
        truncated = table_for(fixture_lines[fixture_lines["invoice_date"] < midnight], monday, quick_view)
        changed = fixture_lines.copy()
        later = changed["invoice_date"] >= midnight
        assert later.sum() > 30, "there is a future to remove"
        changed.loc[later, "quantity"] = changed.loc[later, "quantity"] * 7 + 1
        changed.loc[later, "price"] = changed.loc[later, "price"] * 3 + 0.5
        changed.loc[later, "customer_id"] = pd.array(changed.loc[later, "customer_id"].astype("Int64") + 1000, dtype="Int64")
        changed.loc[later, "invoice_date"] = changed.loc[later, "invoice_date"] + pd.Timedelta(hours=5)
        assert bytes_of(everything) == bytes_of(truncated) == bytes_of(table_for(changed, monday, quick_view)), monday
        assert len(everything) > 20
        checked += 1
    assert checked == 6


def test_a_base_that_is_not_cut_for_its_round_is_refused(fixture_lines, quick_view, quick_cfg):
    """The guard works on the real table of the fixture: the whole file given to a round that is not the last one is a ``LeakageError``, and the cut history is not."""
    monday = quick_cfg.calendar.test_first_round
    with pytest.raises(LeakageError, match=monday.isoformat()):
        base.base_table(fixture_lines, monday, quick_view)
    with pytest.raises(LeakageError):
        base.contact_base(fixture_lines, monday, quick_view)
    cut = base.history_before(fixture_lines, monday)
    assert len(base.base_table(cut, monday, quick_view)) > 20


def test_the_table_of_a_round_does_not_depend_on_the_order_of_the_lines(fixture_lines, quick_view, quick_cfg):
    """The same lines in another order give the same bytes: a sum of prices is added in the order of the line keys, not in the order the file happens to have."""
    for monday in (quick_cfg.calendar.validation_last_round, quick_cfg.calendar.test_last_round):
        shuffled = fixture_lines.sample(frac=1, random_state=7)
        assert bytes_of(table_for(fixture_lines, monday, quick_view)) == bytes_of(table_for(shuffled, monday, quick_view))


def test_a_later_round_sees_what_an_earlier_one_could_not(fixture_lines, quick_view, quick_cfg):
    first = quick_cfg.calendar.test_first_round
    second = first + timedelta(days=7)
    early, late = table_for(fixture_lines, first, quick_view), table_for(fixture_lines, second, quick_view)
    assert len(late) >= len(early) and set(early["customer_id"]) <= set(late["customer_id"]), "with a year of lookback, nobody leaves the base in a week"
    joined = early.merge(late, on="customer_id", suffixes=("_early", "_late"))
    assert (joined["invoices_before_late"] >= joined["invoices_before_early"]).all() and (joined["tenure_days_late"] > joined["tenure_days_early"]).all()


def test_the_calculation_modules_do_not_read_the_lines_by_themselves():
    """Static (plan section 10): the modules whose results are sealed receive the cut history and never call ``read_lines``, never open the file of the lines and, but for the stored
    assignments of the control group, never touch the warehouse (``holdout.py`` reads ``holdout_assignments`` and nothing of ``lines``)."""
    for name in CALCULATIONS:
        text = (SRC / name).read_text(encoding="utf-8")
        tree = ast.parse(text)
        imported = {alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
        imported |= {node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
        called = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)} | {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
        banned = ["personaloffers.warehouse", "personaloffers.workbook", "personaloffers.sources"] + (["sqlite3"] if name == "base.py" else [])
        assert not {m for m in imported if m.startswith(tuple(banned))}, name
        assert not {"read_lines", "read_parquet", "read_table", "lines_state", "read_delivery"} & called, name
        assert "read_csv" not in called and "open" not in called, name
        assert not re.search(r"(FROM|JOIN)\s+lines", text, re.IGNORECASE), f"{name} reads the lines table"
        if name != "holdout.py":
            assert "connect" not in called, name


def test_the_two_functions_that_read_the_history_call_the_guard_and_the_table_calls_them():
    tree = ast.parse((SRC / "base.py").read_text(encoding="utf-8"))
    functions = {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}
    calls = {name: {n.func.id for n in ast.walk(node) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)} for name, node in functions.items()}
    assert "check_no_leak" in calls["contact_base"] and "check_no_leak" in calls["covariates"]
    assert {"contact_base", "covariates"} <= calls["base_table"]
