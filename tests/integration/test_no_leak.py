"""No information from the future (U07 and U09; RF08, RF10, AC07, AC13; decision D23): the base of a round and its covariates, and the recommenders and the lists of the round, are
the same, bit for bit, if every line from its Monday on is removed or changed; a function that is given one such line refuses; and the modules that compute them have no way to read
the lines by themselves. U12 adds the lists the weekly task emits and the baselines to this file."""

from __future__ import annotations

import ast
import re
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import pytest

from personaloffers import base, offers
from personaloffers import calendar as cal
from personaloffers.base import LeakageError
from personaloffers.recommend import blend, context, factor, popularity, repeats, rules

SRC = Path(__file__).resolve().parents[2] / "src" / "personaloffers"
CALCULATIONS = ("base.py", "holdout.py", "offers.py", "recommend/popularity.py", "recommend/repeats.py", "recommend/rules.py", "recommend/factor.py",
                "recommend/blend.py", "recommend/context.py")      # the modules whose results enter a sealed value; the model files (artifacts.py) compute nothing


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


# --- U09: the recommenders and the list --------------------------------------------------------------------------------------------------------------


def lists_for(lines: pd.DataFrame, monday, view) -> bytes:
    """What the tasks of a round do with the cut history: the shared data of the round, the discovery scores of three recipes (one of each model) and the list built from each; every
    array with all its bytes."""
    history = base.history_before(lines, monday)
    customers = base.contact_base(history, monday, view)["customer_id"].to_numpy()
    data = context.prepare(history, monday, customers, view)
    parts = [data.customers.tobytes(), "\n".join(data.codes).encode(), data.seen.tobytes(), data.repeat.tobytes(), data.popularity.tobytes(), data.recent.tobytes(),
             data.trend.tobytes(), data.tie_rank.tobytes(), data.fallback.tobytes()]
    cache: dict = {}
    for recipe in (blend.Recipe("als", 8, 1.0, regularization=0.1), blend.Recipe("cosine", 20, 0.5), blend.Recipe("rules", 3, 1.0)):
        discovery = blend.discovery_scores(data, recipe, view, cache=cache)
        products, origins = offers.build_list(data.repeat, discovery, data.seen, data.fallback, view, tie_rank=data.tie_rank)
        parts += [discovery.tobytes(), products.tobytes(), origins.tobytes()]
    return b"\x00".join(parts)


def test_the_recommenders_and_the_list_are_identical_when_every_line_from_the_monday_is_removed(fixture_lines, quick_view, quick_cfg):
    """AC13: the popularity, the repeats, the three models' scores and the lists of a round are the same bytes with the whole file, with every line from the Monday on removed, and with
    every one of those lines changed (quantity, price, customer and time)."""
    calendar = quick_cfg.calendar
    for monday in (calendar.validation_last_round, calendar.test_first_round, calendar.test_last_round):
        midnight = datetime.combine(monday, datetime.min.time())
        everything = lists_for(fixture_lines, monday, quick_view)
        truncated = lists_for(fixture_lines[fixture_lines["invoice_date"] < midnight], monday, quick_view)
        changed = fixture_lines.copy()
        later = changed["invoice_date"] >= midnight
        assert later.sum() > 30
        changed.loc[later, "quantity"] = changed.loc[later, "quantity"] * 7 + 1
        changed.loc[later, "price"] = changed.loc[later, "price"] * 3 + 0.5
        changed.loc[later, "customer_id"] = pd.array(changed.loc[later, "customer_id"].astype("Int64") + 1000, dtype="Int64")
        changed.loc[later, "invoice_date"] = changed.loc[later, "invoice_date"] + pd.Timedelta(hours=5)
        assert everything == truncated == lists_for(changed, monday, quick_view), monday
        assert len(everything) > 50_000


def test_a_recommender_given_a_line_of_its_round_raises(fixture_lines, quick_view, quick_cfg):
    """M01 (D23): every function of the recommenders that reads the history refuses the whole file given to a round that is not the last one, and accepts the cut."""
    monday = quick_cfg.calendar.test_first_round
    cut = base.history_before(fixture_lines, monday)
    codes = popularity.catalogue(cut, monday)
    customers = base.contact_base(cut, monday, quick_view)["customer_id"].to_numpy()
    calls = {
        "popularity.catalogue": lambda h: popularity.catalogue(h, monday),
        "popularity.counts": lambda h: popularity.counts(h, monday, codes),
        "popularity.counts (28 days)": lambda h: popularity.counts(h, monday, codes, days=28),
        "repeats.score_matrix": lambda h: repeats.score_matrix(h, monday, customers, codes, quick_view),
        "rules.pair_counts": lambda h: rules.pair_counts(h, monday, codes),
        "factor.user_item": lambda h: factor.user_item(h, monday, codes),
        "context.prepare": lambda h: context.prepare(h, monday, customers, quick_view),
    }
    for name, call in calls.items():
        call(cut)
        with pytest.raises(LeakageError, match=monday.isoformat()):
            call(fixture_lines)
        assert name


def test_every_function_of_the_recommenders_that_takes_the_history_calls_the_guard():
    """Static: a public function with a ``history`` parameter calls ``check_no_leak`` itself, so a new one cannot forget it."""
    checked = []
    for name in CALCULATIONS:
        if not name.startswith("recommend/"):
            continue
        tree = ast.parse((SRC / name).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and not node.name.startswith("_") and "history" in {a.arg for a in node.args.args}:
                called = {n.func.id for n in ast.walk(node) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
                assert "check_no_leak" in called, f"{name}:{node.name}"
                checked.append(f"{name}:{node.name}")
    assert len(checked) >= 6 and "recommend/context.py:prepare" in checked
