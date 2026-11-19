"""The HTML design of the report (U16; RF21, AC27; decisions D16, D30, D37; risk items 3 and 6): a self-contained page with every page of the model, every visual with a preview drawn from the exported files, every text
that comes from the data escaped, nothing loaded from outside, the hidden cells shown as hidden, the verdict of each criterion as the summary tells it and the legend that the archive has no offers."""

from __future__ import annotations

import dataclasses
import re
from datetime import datetime
from html import escape

import pandas as pd
import pyarrow.parquet as pq
import pytest

from personaloffers import reporting, texts
from personaloffers.dashboard import render
from personaloffers.dashboard.render import _bare_title, _makers, _preview, render_design
from personaloffers.dashboard.semantic_model import LEGEND, MODEL, NOT_FILTERED, PAGES, Page, Visual
from personaloffers.reporting import RunMeta
from tests.fixtures.published import customer_numbers_in

RUN = RunMeta("run-5", datetime(2011, 4, 23))


def test_html_has_every_page_every_section_and_every_measure_and_table_of_the_model(rendered):
    html = rendered.html
    assert html.startswith("<!doctype html>") and html.count("<html") == 1 and '<html lang="es">' in html and len(html.encode("utf-8")) < 2 * 1024 * 1024
    for key, title in render.SECTIONS:
        assert f'id="{key}"' in html and escape(title) in html
    for number, page in enumerate(MODEL.pages, start=1):
        assert f'id="pagina-{number}"' in html and f"Página {number}: {escape(page.name_es)}" in html
        for v in page.visuals:
            assert f'aria-label="{escape(v.title_es)}"' in html and html.count(f'aria-label="{escape(v.title_es)}"') >= 1, (page.name_es, v.title_es)
    for measure in MODEL.measures:
        assert f"<h3>{escape(measure.name_es)}</h3>" in html and escape(measure.dax) in html
    for table in MODEL.public:
        assert f"<h3>{table.name}</h3>" in html and f"{table.name}.parquet" in html
    assert "fact_offer_customer.parquet" not in html or "no hace falta" in html, "the private table is named only to say that it is not needed"
    for r in MODEL.relationships:
        assert r.rel_id in html
    assert html.count('<section class="visual"') == sum(len(p.visuals) for p in MODEL.pages) == 28


def test_the_page_loads_nothing_from_outside_and_has_no_script(rendered):
    html = rendered.html
    assert "<script" not in html and "<link" not in html and "<img" not in html and "<iframe" not in html and "@import" not in html and "javascript:" not in html
    assert not re.findall(r'(?:src|href)="(?!#)[^"]+"', html) and "http://" not in html.replace("https://doi.org", "").replace("https://creativecommons.org", "").replace("http://www.w3.org", "") or "https://" in html
    assert not re.findall(r"url\((?!#)", html) and "xmlns" not in html, "no namespace address and no resource (the arrow of the diagram points at the page itself)"
    for outside in re.findall(r"https?://[^\s\"'<>)]+", html):
        assert outside.startswith(("https://doi.org/10.24432/C5CG6D", "https://creativecommons.org/licenses/by/4.0/")), outside


def test_every_page_has_the_legend_that_the_archive_has_no_offers_and_the_attribution_is_there(rendered):
    html = rendered.html
    assert html.count(f'<p class="legend">{escape(LEGEND)}</p>') == 1 + len(MODEL.pages), "once at the top and once on each page"
    assert escape(texts.ATTRIBUTION) in html and "doi.org/10.24432/C5CG6D" in html and "CC BY 4.0" in html
    assert f'<div class="warn">{escape(PAGES[3].note_es)}</div>' in html and "Esto no es un efecto" in html
    assert re.sub(r"menor efecto detectable|no es un efecto|permite medir el efecto de una oferta|no es el efecto de nada", "", html.lower()).count("efecto") == 0, "the word is only in the phrases that the decision allows"
    assert "uplift" not in html.lower() and not re.search(r"\blift\b", html.replace("rule_lift", "").lower())


def test_the_previews_are_the_figures_of_the_exported_files(exported, rendered):
    html = rendered.html
    ops = pd.read_parquet(exported.out / "fact_round_ops.parquet")
    assert escape(texts.es(float(ops["base"].sum()), 0)) in html and "en 4 rondas" in html, "the card of the base: the sum of the rounds whose cell is shown"
    totals = pd.read_parquet(exported.out / "fact_method_total.parquet")
    list_hit = totals[(totals["method_key"] == "offer_list") & (totals["variant_key"] == "unrestricted")]["hit_rate"].iloc[0]
    assert escape(texts.es(float(list_hit) * 100, 1)) in html, "the bar of the list is its hit@10 of the file"
    choice = pd.read_parquet(exported.out / "fact_choice.parquet")
    assert escape(choice.sort_values(["chosen", "val_hit_new"], ascending=[False, False]).iloc[0]["candidate"]) in html
    products = pd.read_parquet(exported.out / "dim_product.parquet").set_index("product_key")["description_es"]
    offered = pd.read_parquet(exported.out / "fact_offer_product.parquet").sort_values(["offered_to", "product_key"], ascending=[False, True]).iloc[0]
    assert escape(products[offered["product_key"]]) in html
    runs = pd.read_parquet(exported.out / "dim_pipeline_run.parquet")
    assert escape(runs["run_key"].iloc[0]) in html and render.DASH in html


def test_a_cell_that_was_hidden_is_shown_as_hidden_and_never_as_a_number(exported, rendered):
    ops = pd.read_parquet(exported.out / "fact_round_ops.parquet")
    assert ops["new_assignments"].isna().all() and "oculta" in rendered.html
    group = pd.read_parquet(exported.out / "fact_round_group.parquet")
    assert group["suppressed"].all(), "every cell of the follow-up is hidden in the fixture at the minimum of 10"
    for cell in (render._int(None), render._fmt(None), render._pct(None)):
        assert cell == "oculta"
    assert ">oculta</td>" in rendered.html and '<div class="big">oculta</div>' not in rendered.html, "a hidden cell of a table is told as hidden; no card of the fixture is hidden"
    assert render._int(1234) == "1.234" and render._fmt(0.5) == "0,500" and render._pct(0.1234) == "12,3 %" and render._when(None) == "—"


def test_the_criteria_preview_shows_what_the_threshold_tests_and_the_published_verdict_not_a_value_column(exported, rendered):
    html = rendered.html
    summary = pd.read_parquet(exported.out / "fact_evaluation_summary.parquet")
    criteria = pd.read_parquet(exported.out / "dim_criterion.parquet").set_index("criterion_key")
    assert "Lo que prueba el umbral" in html and "<th>Valor</th>" not in html
    for row in summary.itertuples():
        assert escape(row.verdict_es) in html and escape(row.tested_value_es) in html and escape(criteria.loc[row.criterion_key, "threshold_es"]) in html, row.criterion_key
    point = summary.loc[summary["criterion_key"] == "C01", "point_value"].iloc[0]
    assert summary.loc[summary["criterion_key"] == "C01", "tested_value_es"].iloc[0].endswith("(límite inferior)") and not pd.isna(point)


def test_without_the_exported_files_every_preview_says_there_is_no_data_and_the_criteria_are_pending(tmp_path):
    path = render_design(MODEL, tmp_path / "nothing", tmp_path / "d.html", RUN)
    html = path.read_text(encoding="utf-8")
    assert "La prueba se evalúa con el cierre: los criterios quedan pendientes hasta entonces." in html and "Sin datos" in html and html.count('<section class="visual"') == 28
    assert "Se calcula en Power BI" not in html


def test_an_incoherent_model_writes_nothing_and_the_file_is_written_whole(exported, tmp_path):
    bad = dataclasses.replace(MODEL, relationships=(dataclasses.replace(MODEL.relationships[0], cardinality="many_to_many"), *MODEL.relationships[1:]))
    with pytest.raises(ValueError, match="incoherente"):
        render_design(bad, exported.out, tmp_path / "d.html", RUN)
    assert not (tmp_path / "d.html").exists()
    first = render_design(MODEL, exported.out, tmp_path / "ok" / "d.html", RUN)
    assert first.read_bytes() == render_design(MODEL, exported.out, tmp_path / "ok" / "d.html", RUN).read_bytes() and [p.name for p in first.parent.iterdir()] == ["d.html"], "the same bytes, and no temporary file"


def test_every_visual_of_every_page_gets_its_preview_drawn_from_the_exported_files(exported):
    data = render._Data(exported.out, MODEL)
    for page in MODEL.pages:
        for v in page.visuals:
            body = _preview(data, v)
            assert body and "Se calcula en Power BI" not in body, (page.name_es, v.title_es)


def test_every_maker_key_is_the_bare_title_of_a_visual_and_every_visual_has_a_maker(exported):
    data = render._Data(exported.out, MODEL)
    keys = set(_makers(data, MODEL.pages[0].visuals[0]))
    drawn = {_bare_title(v.title_es) for p in MODEL.pages for v in p.visuals if v.kind not in ("slicer", "card")}
    assert keys == drawn
    cards = set(render._cards(data))
    assert cards == {v.fields[0] for p in MODEL.pages for v in p.visuals if v.kind == "card"}


def test_the_mark_that_cuts_the_not_filtered_note_is_derived_from_the_note_itself():
    assert render.NOT_FILTERED_MARK == " (no lo filtra" and _bare_title("Clientes en la base" + NOT_FILTERED.format(plural="", names="el segmento")) == "Clientes en la base"
    assert _bare_title("Reglas de validación") == "Reglas de validación"


def test_a_row_that_is_not_sealed_is_never_shown_as_a_figure_of_the_test(exported, tmp_path):
    import shutil

    folder = tmp_path / "files"
    shutil.copytree(exported.out, folder)
    totals = pd.read_parquet(folder / "fact_method_total.parquet")
    sealed = totals[totals["seal_state"] == "sealed"].assign(hit_rate=0.5)
    sealed.to_parquet(folder / "fact_method_total.parquet", index=False)

    def page_two() -> str:
        return render_design(MODEL, folder, tmp_path / "d.html", RUN).read_text(encoding="utf-8").split('id="pagina-2"')[1].split('id="pagina-3"')[0]

    before = page_two()
    pd.concat([sealed, sealed.assign(seal_state="post_seal", hit_rate=0.7777)], ignore_index=True).to_parquet(folder / "fact_method_total.parquet", index=False)
    after = page_two()
    assert after == before and ">50</text>" in before and ">78</text>" not in after, "the post-seal rows change nothing of what is drawn: only the sealed ones are"


def test_every_text_that_comes_from_the_data_is_escaped(exported, tmp_path):
    import shutil

    folder = tmp_path / "files"
    shutil.copytree(exported.out, folder)
    products = pd.read_parquet(folder / "dim_product.parquet")
    top = pd.read_parquet(folder / "fact_offer_product.parquet").sort_values(["offered_to", "product_key"], ascending=[False, True]).iloc[0]["product_key"]
    products.loc[products["product_key"] == top, "description_es"] = "<script>alert('x')</script> & \"co\""
    products.to_parquet(folder / "dim_product.parquet", index=False)
    segments = pd.read_parquet(folder / "dim_segment.parquet")
    segments.loc[segments.index[0], "label_es"] = "<b>negrita</b>"
    segments.to_parquet(folder / "dim_segment.parquet", index=False)
    runs = pd.read_parquet(folder / "dim_pipeline_run.parquet")
    runs.loc[runs.index[0], "message"] = "<img src=x onerror=alert(1)>"
    runs.to_parquet(folder / "dim_pipeline_run.parquet", index=False)
    html = render_design(MODEL, folder, tmp_path / "d.html", RUN).read_text(encoding="utf-8")
    assert "<b>negrita" not in html and "&lt;b&gt;negrita&lt;/b&gt;" in html, "the slicers' chips are escaped too"
    assert "<script" not in html and "<img" not in html and "&lt;script&gt;alert(&#x27;x&#x27;)&lt;/script&gt; &amp; &quot;co&quot;" in html and "&lt;img src=x onerror=alert(1)&gt;" in html


def test_the_private_list_is_never_read_even_when_it_is_in_the_same_folder(exported, rendered, tmp_path):
    import shutil

    folder = tmp_path / "both"
    shutil.copytree(exported.out, folder)
    shutil.copy(exported.private / "fact_offer_customer.parquet", folder / "fact_offer_customer.parquet")
    html = render_design(MODEL, folder, tmp_path / "d.html", RUN).read_text(encoding="utf-8")
    assert html == rendered.html and not customer_numbers_in(html), "no number of a customer in the design, with the private file beside the published ones"


def test_the_run_and_the_configuration_of_the_files_are_in_the_page(exported, rendered):
    meta = pq.read_schema(exported.out / "dim_pipeline_run.parquet").metadata
    sha = meta[b"personaloffers.config_sha256"].decode()
    assert f"<code>{sha[:12]}</code>" in rendered.html and "<code>run-5</code>" in rendered.html and "2011-04-23 00:00:00" in rendered.html
    assert isinstance(reporting.RunMeta, type) and Page and Visual
