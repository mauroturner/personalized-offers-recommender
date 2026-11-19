"""The figures of the documentation (U17, RF26; plan sections 21 and 25): drawn only from the verified files of the site, the same bytes every time, and a set that is not one export draws nothing."""

from __future__ import annotations

import json

import pytest

from personaloffers import figures
from personaloffers.site_export import SiteSetError, read_site
from tests.contract.test_site_export import copy_of  # noqa: F401  (a helper of the contract tests)

PNG = b"\x89PNG\r\n\x1a\n"


def test_each_figure_is_a_png_drawn_from_the_site_and_the_same_twice(sited, tmp_path):
    first = figures.write_figures(sited.out, tmp_path / "a")
    second = figures.write_figures(sited.out, tmp_path / "b")
    assert [p.name for p in first] == [f"{name}.png" for name in figures.FIGURES] and len(figures.FIGURES) == 6
    assert all(p.read_bytes().startswith(PNG) and p.stat().st_size > 2000 for p in first)
    assert [p.read_bytes() for p in first] == [p.read_bytes() for p in second]


def test_the_numbers_of_a_figure_are_the_ones_of_the_site(sited):
    data = figures.figure_data(read_site(sited.out))
    assert set(data) == set(figures.FIGURES)
    site = sited.site
    assert data["hit_by_method"]["hit_rate"] == [m["hit_rate"] for m in site.algorithms["methods"] if m["variant_key"] == "unrestricted"] and data["hit_by_method"]["scope"] == "test"
    assert data["round_operation"]["offer"] == [r["offer"] for r in site.operation["rounds"]] and data["round_operation"]["round"] == [r["round_key"][1:] for r in site.operation["rounds"]]
    assert data["balance"]["smd"] == [b["smd"] for b in site.control["balance"]]
    assert data["calibration"]["m1"] == site.control["calibration"]["rejection"]["m1"] and data["calibration"]["band"] == [0.031, 0.069]
    assert [c["candidate"] for c in site.algorithms["choice"]] == data["choice"]["candidate"]


def test_before_the_seal_the_figures_of_the_test_say_that_it_is_evaluated_at_the_close(sited_pending, tmp_path):
    data = figures.figure_data(sited_pending.site)
    assert data["hit_by_method"]["scope"] == "pending" and data["hit_by_method"]["hit_rate"] == [] and data["calibration"]["scope"] == "pending"
    written = figures.write_figures(sited_pending.out, tmp_path / "figs")
    assert all(p.read_bytes().startswith(PNG) for p in written)


def test_a_folder_that_is_not_one_export_draws_and_writes_nothing(sited, tmp_path):
    out = copy_of(sited, tmp_path)
    (out / "manifest.json").unlink()
    with pytest.raises(SiteSetError):
        figures.write_figures(out, tmp_path / "figs")
    assert not (tmp_path / "figs").exists()
    broken = copy_of(sited, tmp_path / "two")
    document = json.loads((broken / "control.json").read_text(encoding="utf-8"))
    document["balance"] = []
    (broken / "control.json").write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(SiteSetError, match="control.json"):
        figures.write_figures(broken, tmp_path / "figs2")
