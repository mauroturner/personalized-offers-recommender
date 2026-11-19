"""The rounds and their windows (U05; RF05, AC05, AC18; decisions D05, D17, D23, D42): a round is a Monday, its window is the week that follows it, the windows of the rounds
never overlap, and a line of purchase is counted in the window of one round at most."""

from __future__ import annotations

import dataclasses
from datetime import date, datetime, timedelta

import pytest

from personaloffers import calendar as cal
from personaloffers.config import load_config


@pytest.fixture(scope="module")
def real_cfg(project_root):
    return load_config(project_root / "config" / "pipeline.toml")


def midnight(day: date) -> datetime:
    return datetime(day.year, day.month, day.day)


def all_rounds(cfg):
    return [(period, monday) for period in cal.PERIODS for monday in cal.rounds(cfg, period)]


def test_every_purchase_line_counts_in_at_most_one_round_window(fixture_lines, quick_cfg):
    windows = [(monday, *cal.window(monday, quick_cfg)) for _period, monday in all_rounds(quick_cfg)]
    assert len(windows) == 2 + 3 + 1, "two rounds of validation, three of test and the censored one of the close"
    purchases = fixture_lines[fixture_lines["role"] == "purchase"]
    stamps = purchases["invoice_date"]
    counted = sum((stamps >= start) & (stamps < end) for _monday, start, end in windows)
    assert counted.max() == 1, "no line is in two windows"
    assert all(((stamps >= start) & (stamps < end)).sum() > 10 for _monday, start, end in windows), "every window holds purchases of the fixture"
    assert (counted == 0).any(), "the launch history is in no window: it is before the first round"


def test_the_rounds_of_the_real_calendar_are_the_mondays_of_the_plan(real_cfg):
    validation, test, censored = (cal.rounds(real_cfg, period) for period in cal.PERIODS)
    assert len(validation) == 13 and (validation[0], validation[-1]) == (date(2011, 5, 2), date(2011, 7, 25))
    assert len(test) == 18 and (test[0], test[-1]) == (date(2011, 8, 1), date(2011, 11, 28))
    assert censored == [date(2011, 12, 5)]
    for monday in (*validation, *test, *censored):
        assert monday.weekday() == 0
    assert all(b - a == timedelta(days=7) for a, b in zip(validation, validation[1:], strict=False))
    assert all(b - a == timedelta(days=7) for a, b in zip(test, test[1:], strict=False))


def test_the_windows_of_every_round_of_the_real_calendar_are_disjoint_and_in_order(real_cfg):
    windows = [cal.window(monday, real_cfg) for _period, monday in all_rounds(real_cfg)]
    assert len(windows) == 13 + 18 + 1
    for (start, end) in windows:
        assert start < end
    for (_, earlier_end), (later_start, _) in zip(windows, windows[1:], strict=False):
        assert earlier_end <= later_start, "a window ends before the next one starts"
    assert windows[0][0] == datetime(2011, 5, 2)


def test_a_window_is_the_week_after_the_monday_and_the_last_validation_one_ends_before_the_test(real_cfg):
    assert cal.window(date(2011, 8, 1), real_cfg) == (datetime(2011, 8, 1), datetime(2011, 8, 8))
    assert cal.window(date(2011, 7, 25), real_cfg) == (datetime(2011, 7, 25), datetime(2011, 8, 1)), "the last validation week ends at the start of the test"
    assert cal.window(date(2011, 7, 25), real_cfg)[1] <= midnight(real_cfg.calendar.test_first_round)


def test_the_censored_round_stops_at_the_last_day_of_the_archive(real_cfg):
    assert cal.window(date(2011, 12, 5), real_cfg) == (datetime(2011, 12, 5), datetime(2011, 12, 10))
    assert cal.days_observed(date(2011, 12, 5), real_cfg) == 5
    assert cal.days_observed(date(2011, 11, 28), real_cfg) == 7
    assert cal.days_observed(date(2011, 5, 2), real_cfg) == 7


def test_a_shorter_window_days_shortens_every_window(quick_cfg):
    short = dataclasses.replace(quick_cfg, calendar=dataclasses.replace(quick_cfg.calendar, window_days=3))
    assert cal.window(date(2011, 3, 28), short) == (datetime(2011, 3, 28), datetime(2011, 3, 31))
    assert cal.days_observed(date(2011, 3, 28), short) == 3
    assert cal.window(date(2011, 4, 18), short) == (datetime(2011, 4, 18), datetime(2011, 4, 21)), "the censored round takes the shorter of the two ends"


def test_the_quick_calendar_has_the_rounds_of_the_fixture(quick_cfg):
    assert cal.rounds(quick_cfg, "validation") == [date(2011, 3, 14), date(2011, 3, 21)]
    assert cal.rounds(quick_cfg, "test") == [date(2011, 3, 28), date(2011, 4, 4), date(2011, 4, 11)]
    assert cal.rounds(quick_cfg, "censored") == [date(2011, 4, 18)]
    assert cal.window(date(2011, 4, 18), quick_cfg) == (datetime(2011, 4, 18), datetime(2011, 4, 23))


def test_the_period_of_a_round_and_its_identifier(real_cfg):
    assert cal.period_of(date(2011, 5, 2), real_cfg) == "validation"
    assert cal.period_of(date(2011, 8, 1), real_cfg) == "test"
    assert cal.period_of(date(2011, 12, 5), real_cfg) == "censored"
    with pytest.raises(ValueError, match="2011-08-02"):
        cal.period_of(date(2011, 8, 2), real_cfg)
    assert cal.round_id(date(2011, 8, 1)) == "R2011-08-01"
    assert cal.monday_of("R2011-08-01") == date(2011, 8, 1)
    for bad in ("2011-08-01", "R2011-8-1", "R2011-08-01 ", "r2011-08-01", "R2011-13-01", "R2011-08-01\n", ""):
        with pytest.raises(ValueError, match="R"):
            cal.monday_of(bad)


def test_an_unknown_period_or_a_day_that_is_not_a_monday_is_refused(real_cfg):
    with pytest.raises(ValueError, match="validation"):
        cal.rounds(real_cfg, "training")
    with pytest.raises(ValueError, match="lunes"):
        cal.window(date(2011, 8, 2), real_cfg)


def test_the_calendar_reads_the_sealed_view_as_well_as_the_configuration(quick_cfg, quick_view):
    assert [cal.rounds(quick_view, period) for period in cal.PERIODS] == [cal.rounds(quick_cfg, period) for period in cal.PERIODS]
    assert cal.window(date(2011, 3, 28), quick_view) == cal.window(date(2011, 3, 28), quick_cfg)
