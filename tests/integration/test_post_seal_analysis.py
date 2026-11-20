"""C05 as the preregistration defines it, published as an analysis after the seal (B5 of the independent evaluation, D49; plan section 28, item 2; the form of D59 of project 07).

Requirements 8.1 define C05's denominator as the products with a **purchase line** (``purchase``, RF04) in the 365 days before the round; the sealed figure counts the basket lines (``purchase`` and
``guest_purchase``). The seal is never rewritten (D21): the close writes ``reports/post_seal_analysis.json`` beside it and bound to its bytes, with the sealed coverage (which must be the seal's), the
preregistered one with its verdict, and the one with the definition of the plan's validation (``research/p01_weekly_validation.py``: the lists of the evaluated customers over every product with a basket
line before the round). The sealed verdict and its sentence stay; no sentence of the summary tells one quantity with the other's definition."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd
import pytest

from personaloffers import calendar as cal
from personaloffers import evaluation, registry, reporting, texts
from tests.fixtures.sites import export_site_of
from tests.fixtures.stars import export_world
from tests.fixtures.worlds import copy_world


@pytest.fixture
def world(evaluated, workbook, quick_cfg, tmp_path):
    made = copy_world(evaluated.root, workbook, quick_cfg, tmp_path / "evaluated")
    yield made
    made.conn.close()


def _by_hand(world) -> dict[str, float]:
    """The four coverages of the test rounds, mean over the rounds, from the tables with SQL and pandas only."""
    lines = pd.read_sql_query("SELECT customer_id, stock_code, role, invoice_date FROM lines WHERE role IN ('purchase', 'guest_purchase')", world.conn, parse_dates=["invoice_date"])
    shares: dict[str, list[float]] = {"sealed": [], "preregistered": [], "p01_denominator": [], "p01_definition": []}
    for day in cal.rounds(world.view, "test"):
        round_id, monday = cal.round_id(day), pd.Timestamp(day)
        before = lines[lines["invoice_date"] < monday]
        year = before[before["invoice_date"] >= monday - pd.Timedelta(days=365)]
        lists = pd.read_sql_query("SELECT customer_id, stock_code FROM offer_lists WHERE round_id = ?", world.conn, params=(round_id,))
        evaluated = {c for (c,) in world.conn.execute("SELECT c.customer_id FROM contact_base c JOIN round_outcomes o ON o.round_id = c.round_id AND o.customer_id = c.customer_id "
                                                      "WHERE c.round_id = ? AND o.bought = 1", (round_id,))}
        shares["sealed"].append(lists["stock_code"].nunique() / year["stock_code"].nunique())
        shares["preregistered"].append(lists["stock_code"].nunique() / year.loc[year["role"] == "purchase", "stock_code"].nunique())
        shares["p01_denominator"].append(lists["stock_code"].nunique() / before["stock_code"].nunique())
        shares["p01_definition"].append(lists.loc[lists["customer_id"].isin(evaluated), "stock_code"].nunique() / before["stock_code"].nunique())
    assert len(shares["sealed"]) > 1
    return {key: sum(values) / len(values) for key, values in shares.items()}


def test_c05_is_computed_with_each_definition_and_the_sealed_one_is_the_seals(world, evaluated):
    found = evaluation.coverage_definitions(world.conn, world.view)
    hand = _by_hand(world)
    assert found["rounds"] == len(cal.rounds(world.view, "test"))
    for key in ("sealed", "preregistered", "p01_denominator", "p01_definition"):
        assert found[key]["value"] == pytest.approx(hand[key], abs=1e-12), key
    assert found["sealed"]["value"] == pytest.approx(evaluated.seal["test"]["metrics"]["coverage_list"], abs=1e-9), "the sealed definition gives the seal's figure"
    assert found["preregistered"]["value"] > found["sealed"]["value"], "fewer products with a purchase line than with a basket line: a smaller denominator"


def test_the_close_writes_the_analysis_beside_the_seal_bound_to_its_bytes_and_the_seal_is_unchanged(world):
    seal_bytes = Path(world.seal_path).read_bytes()
    path = reporting.write_post_seal_analysis(world.conn, world.view, seal_path=Path(world.seal_path))
    assert path == Path(world.seal_path).with_name("post_seal_analysis.json") and Path(world.seal_path).read_bytes() == seal_bytes
    document = json.loads(path.read_text(encoding="utf-8"))
    assert document["seal_sha256"] == hashlib.sha256(seal_bytes).hexdigest() and document["config_sha256"] == json.loads(seal_bytes)["launch"]["config_sha256"]
    c05 = document["c05"]
    limit = world.view.criteria.c05_min_coverage
    assert c05["preregistered"]["passed"] is (c05["preregistered"]["value"] >= limit) and c05["preregistered"]["threshold"] == limit
    assert c05["sealed"]["passed"] is (c05["sealed"]["value"] >= limit)
    assert set(c05) == {"rounds", "by_round", "sealed", "preregistered", "p01_denominator", "p01_definition"} and all(c05[k]["definition_es"] for k in ("sealed", "preregistered", "p01_denominator", "p01_definition"))
    assert reporting.read_post_seal_analysis(Path(world.seal_path)) == document


def test_an_analysis_computed_beside_another_seal_is_not_published(world):
    reporting.write_post_seal_analysis(world.conn, world.view, seal_path=Path(world.seal_path))
    path = Path(world.seal_path).with_name("post_seal_analysis.json")
    document = json.loads(path.read_text(encoding="utf-8"))
    path.write_text(json.dumps({**document, "seal_sha256": "0" * 64}), encoding="utf-8")
    assert reporting.read_post_seal_analysis(Path(world.seal_path)) is None
    assert "post_seal_analysis" not in reporting.build_summary(world.conn, world.view, seal_path=Path(world.seal_path))


def test_when_the_sealed_coverage_does_not_reproduce_the_seals_nothing_is_written_and_it_is_a_seal_error(world):
    """The guard of ``write_post_seal_analysis`` (L138's warning): the analysis must be of what was sealed. A seal whose ``coverage_list`` is not the recomputed sealed coverage to six decimals refuses it: no
    file is written, and the seal is not touched."""
    seal_path = Path(world.seal_path)
    seal = json.loads(seal_path.read_text(encoding="utf-8"))
    seal["test"]["metrics"]["coverage_list"] = round(seal["test"]["metrics"]["coverage_list"] + 0.001, 6)
    seal_path.write_text(json.dumps(seal, indent=1, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    tampered = seal_path.read_bytes()
    with pytest.raises(registry.SealError, match="el análisis no es de lo sellado"):
        reporting.write_post_seal_analysis(world.conn, world.view, seal_path=seal_path)
    assert not seal_path.with_name("post_seal_analysis.json").exists() and seal_path.read_bytes() == tampered



def test_before_the_test_part_of_the_seal_nothing_is_written(launched, workbook, quick_cfg, tmp_path):
    made = copy_world(launched.root, workbook, quick_cfg, tmp_path / "launched")
    try:
        assert reporting.write_post_seal_analysis(made.conn, made.view, seal_path=Path(made.seal_path)) is None
        assert not Path(made.seal_path).with_name("post_seal_analysis.json").exists()
    finally:
        made.conn.close()


def test_the_summary_and_the_site_tell_the_analysis_beside_the_sealed_c05_without_mixing_the_two(world, workbook, quick_cfg, tmp_path):
    reporting.write_post_seal_analysis(world.conn, world.view, seal_path=Path(world.seal_path))
    summary = reporting.build_summary(world.conn, world.view, seal_path=Path(world.seal_path))
    analysis = summary["post_seal_analysis"]["c05"]
    sealed_c05 = next(c for c in summary["criteria"] if c["criterion_id"] == "C05")
    assert sealed_c05["verdict_es"] == next(c for c in evaluation.criteria_from_seal(json.loads(Path(world.seal_path).read_text(encoding="utf-8"))) if c.criterion_id == "C05").verdict_es, \
        "the sealed sentence stays"
    markdown = reporting.summary_markdown(summary)
    block = markdown.split("### Análisis posteriores al sello", 1)[1].split("\nCifras de la validación", 1)[0]
    preregistered, p01 = texts.c05_preregistered_line(analysis), texts.c05_p01_line(analysis)
    assert preregistered in block and p01 in block
    assert texts.es(analysis["preregistered"]["value"], 3) in preregistered and "línea de compra" in preregistered and texts.es(analysis["sealed"]["value"], 3) in preregistered
    assert "líneas de canasta" in preregistered, "the sealed figure is named with its own definition"
    assert texts.es(analysis["p01_definition"]["value"], 3) in p01 and "clientes evaluados" in p01 and "numerador" in p01
    for sentence in (preregistered, p01):
        assert "alguna compra" not in sentence, "«alguna compra» is the sealed sentence's wording; the analysis names each line role"
    world.conn.close()
    star = export_world(world.root, workbook, quick_cfg, tmp_path / "star")      # the folder now holds the analysis beside its seal
    star.conn.close()
    made = export_site_of(star.world.warehouse_path, star.world, star.view, tmp_path / "site")
    try:
        assert made.site.summary["post_seal_analysis"] == summary["post_seal_analysis"] and made.site.summary["evaluation_status"] == "sealed"
    finally:
        made.conn.close()


def test_the_close_of_the_replay_writes_the_analysis_and_the_summary_and_the_site_carry_it(piped):
    """The task ``report`` of the close writes it before the summary (D49), so the summary, ``evaluation_summary.md`` and the site's ``summary.json`` of the run that closed carry it."""
    reports, seal = Path(piped.cfg.paths.reports_dir), Path(piped.cfg.paths.seal)
    document = json.loads((reports / "post_seal_analysis.json").read_text(encoding="utf-8"))
    assert document["seal_sha256"] == hashlib.sha256(seal.read_bytes()).hexdigest()
    assert json.loads((reports / "evaluation_summary.json").read_text(encoding="utf-8"))["post_seal_analysis"] == document
    assert "### Análisis posteriores al sello" in (reports / "evaluation_summary.md").read_text(encoding="utf-8")
    assert json.loads((Path(piped.cfg.paths.site_dir) / "summary.json").read_text(encoding="utf-8"))["post_seal_analysis"] == document
