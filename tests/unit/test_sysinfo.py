"""The peak memory of the process, with the name of its counter (U18; RNF03; D39): every task of every run records its peaks with their counter, and a peak that cannot be measured never discards what a task did."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from personaloffers import sysinfo
from personaloffers.sysinfo import MemoryPeaks, peak_memory
from tests.fixtures.piped import run_keys, state_of


def test_the_peak_is_the_working_set_on_windows_and_ru_maxrss_elsewhere_with_its_counter_named():
    """RNF03, D39: the peak is ``PeakWorkingSetSize`` on Windows and ``ru_maxrss`` elsewhere (``PeakPagefileUsage`` informative, only on Windows)."""
    peaks = peak_memory()
    assert isinstance(peaks, MemoryPeaks) and peaks.working_set_mb > 0
    assert peaks.counter == ("PeakWorkingSetSize" if sys.platform == "win32" else "ru_maxrss")
    assert (peaks.commit_mb is not None and peaks.commit_mb > 0) == (sys.platform == "win32") and not hasattr(peaks, "gpu_mb"), "no GPU (RNF04)"


def test_a_system_that_reports_no_peak_is_an_error(monkeypatch):
    """The counter is read, not assumed: a zero from the system is an ``OSError`` with its reason, and never a peak of 0 MB."""
    monkeypatch.setattr(sysinfo, "_windows_peaks", lambda: (0, 0), raising=False)
    monkeypatch.setattr(sysinfo, "_posix_peak", lambda: 0, raising=False)
    with pytest.raises(OSError, match="no informó el pico de memoria"):
        peak_memory()


def test_a_commit_peak_of_zero_is_none_and_the_megabyte_is_a_mebibyte(monkeypatch):
    monkeypatch.setattr(sysinfo, "_windows_peaks", lambda: (2 * 1024 * 1024, 0), raising=False)
    monkeypatch.setattr(sysinfo, "_posix_peak", lambda: 2 * 1024 * 1024, raising=False)
    peaks = peak_memory()
    assert peaks.working_set_mb == 2.0 and peaks.commit_mb is None


def test_every_task_records_its_peaks_with_their_counters(piped):
    counter = peak_memory().counter
    for key in run_keys(piped.cfg):
        for task_id, result in state_of(piped.cfg, key)["tasks"].items():
            assert result["memory_counter"] == counter and result["peak_working_set_mb"] > 0, (key, task_id)
            assert result["seconds"] >= 0 and "peak_gpu_mb" not in result
    last = state_of(piped.cfg, run_keys(piped.cfg)[-1])["tasks"]
    assert last["report"]["peak_working_set_mb"] >= max(t["peak_working_set_mb"] for t in last.values() if t is not last["report"]) - 0.1, "a peak never falls"


def test_a_peak_that_cannot_be_measured_does_not_discard_the_result_of_a_task(before_close, workbook, quick_cfg, tmp_path, monkeypatch):
    from personaloffers import pipeline
    from tests.fixtures.piped import copy_piped

    made = copy_piped(before_close, workbook, quick_cfg, tmp_path / "w")
    monkeypatch.setattr(pipeline, "peak_memory", lambda: (_ for _ in ()).throw(OSError("no counter")))
    result = pipeline.run_task("fetch_source", "nomem", made.cfg)
    assert result["memory_counter"] is None and result["peak_working_set_mb"] is None and result["lines"] > 0
    assert json.loads((Path(made.cfg.paths.interim_dir) / "runs" / "nomem.json").read_text(encoding="utf-8"))["tasks"]["fetch_source"]["memory_counter"] is None
