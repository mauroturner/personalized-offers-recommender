"""The semantic model of the report (U15, U16; AC26, AC27; decisions D16, D30, D37; risk items 3 and 6): the tables, the keys and the 20 relationships of the plan are the single source of the Parquet schema, the data
dictionary and the design, and ``validate_model`` refuses an incoherent one. No measure runs anywhere in the project, so what stands in for running them is that every table, column, measure and function a DAX expression
names exists, that a measure of the test reads only sealed rows and that each slicer reaches the visuals of its page through a relationship or the title of the visual says it does not filter it (risk item 6)."""

from __future__ import annotations

import dataclasses
import re

import pyarrow as pa
import pytest

from personaloffers.dashboard.semantic_model import (
    ARROW_TYPES,
    CUSTOMER_COUNT_COLUMNS,
    DAX_FUNCTIONS,
    DIMENSIONS,
    FACTS,
    LEGEND,
    MEASURES,
    MODEL,
    PAGE_COLUMNS,
    PAGE_ROWS,
    PAGES,
    RELATIONSHIP_SPEC,
    Column,
    Page,
    SemanticModel,
    Visual,
    arrow_schema,
    dax_column_refs,
    dax_measure_refs,
    validate_model,
    visual_tables,
)

DIM_NAMES = ("dim_date", "dim_round", "dim_product", "dim_method", "dim_variant", "dim_source", "dim_group", "dim_segment", "dim_covariate", "dim_criterion", "dim_pipeline_run")
FACT_NAMES = ("fact_round_ops", "fact_round_group", "fact_offer_product", "fact_method_round", "fact_method_total", "fact_segment", "fact_choice", "fact_balance", "fact_experiment", "fact_mde", "fact_rule",
              "fact_evaluation_summary", "fact_validation", "fact_offer_customer")


def replaced(model: SemanticModel, name: str, **changes) -> SemanticModel:
    return dataclasses.replace(model, tables=tuple(dataclasses.replace(t, **changes) if t.name == name else t for t in model.tables))


def test_the_model_is_the_plans_eleven_dimensions_and_fourteen_facts_with_their_grain_and_it_is_coherent():
    assert [t.name for t in MODEL.tables] == [*DIM_NAMES, *FACT_NAMES] and (len(DIMENSIONS), len(FACTS)) == (11, 14)
    assert validate_model(MODEL) == []
    grain = {t.name: t.key for t in MODEL.tables if t.kind == "fact"}
    assert grain["fact_round_ops"] == ("round_key",) and grain["fact_round_group"] == ("round_key", "group_key", "segment_key") and grain["fact_offer_product"] == ("round_key", "product_key", "source_key")
    assert grain["fact_method_round"] == ("method_key", "variant_key", "round_key", "seal_state") and grain["fact_offer_customer"] == ("round_key", "customer_id", "rank")
    assert [t.name for t in MODEL.private] == ["fact_offer_customer"] and len(MODEL.public) == 24


def test_every_relationship_of_the_plan_is_there_one_to_many_single_and_active():
    assert {r.rel_id: (r.dim_table, r.fact_table, r.fact_column) for r in MODEL.relationships} == RELATIONSHIP_SPEC and len(MODEL.relationships) == 20
    assert all((r.cardinality, r.cross_filter, r.active) == ("one_to_many", "single", True) for r in MODEL.relationships)
    related = {r.fact_table for r in MODEL.relationships}
    assert {t.name for t in MODEL.tables if t.kind == "fact"} - related == {"fact_choice", "fact_experiment", "fact_mde", "fact_rule"}, "what has no dimension to filter it is shown as a table"
    assert {t.name for t in MODEL.tables if t.kind == "dimension"} - {r.dim_table for r in MODEL.relationships} == {"dim_date"}, "the calendar stands alone"


def test_the_arrow_schema_is_the_columns_in_order_with_their_types_and_a_key_that_cannot_be_empty():
    table = MODEL.table("fact_round_group")
    schema = arrow_schema(table)
    assert schema.names == list(table.column_names) and schema.field("customers").type == pa.int64() and schema.field("suppressed").type == pa.bool_() and schema.field("spend").type == pa.float64()
    assert [schema.field(k).nullable for k in table.key] == [False, False, False] and schema.field("customers").nullable
    assert arrow_schema(MODEL.table("dim_pipeline_run")).field("started_at").type == pa.timestamp("us") and set(ARROW_TYPES) >= {c.dtype for t in MODEL.tables for c in t.columns}


def test_a_cell_that_counts_customers_has_its_mark_of_a_hidden_cell_and_no_published_table_has_a_column_of_customer():
    for name, columns in CUSTOMER_COUNT_COLUMNS.items():
        table = MODEL.table(name)
        assert "suppressed" in table.column_names and set(columns) <= set(table.column_names) and name in {t.name for t in MODEL.public}, name
    for table in MODEL.public:
        assert not [c for c in table.column_names if "customer" in c.replace("customers", "")], table.name
    assert "customer_id" in MODEL.table("fact_offer_customer").column_names


@pytest.mark.parametrize("what", ["duplicate table", "duplicate column", "key not a column", "unknown type", "dimension with two keys", "customer column", "no mark", "bad cardinality", "bad filter", "inactive",
                                  "missing fact column", "type mismatch", "unknown table", "not a dimension key"])
def test_an_incoherent_model_is_refused_and_says_what(what):
    model = MODEL
    expected = ""
    if what == "duplicate table":
        model, expected = dataclasses.replace(MODEL, tables=(*MODEL.tables, MODEL.table("dim_group"))), "repetida"
    elif what == "duplicate column":
        t = MODEL.table("dim_group")
        model, expected = replaced(MODEL, "dim_group", columns=(*t.columns, t.columns[0])), "columna repetida"
    elif what == "key not a column":
        model, expected = replaced(MODEL, "dim_group", key=("nothing",)), "no es una columna"
    elif what == "unknown type":
        t = MODEL.table("dim_group")
        model, expected = replaced(MODEL, "dim_group", columns=(*t.columns, Column("x", "decimal", "x"))), "tipo desconocido"
    elif what == "dimension with two keys":
        model, expected = replaced(MODEL, "dim_group", key=("group_key", "label_es")), "una sola columna"
    elif what == "customer column":
        t = MODEL.table("fact_round_ops")
        model, expected = replaced(MODEL, "fact_round_ops", columns=(*t.columns, Column("customer_id", "int64", "x"))), "columna de cliente"
    elif what == "no mark":
        t = MODEL.table("fact_segment")
        model, expected = replaced(MODEL, "fact_segment", columns=tuple(c for c in t.columns if c.name != "suppressed")), "suppressed"
    else:
        first = MODEL.relationships[0]
        change = {"bad cardinality": {"cardinality": "many_to_many"}, "bad filter": {"cross_filter": "both"}, "inactive": {"active": False}, "missing fact column": {"fact_column": "nothing"},
                  "unknown table": {"fact_table": "fact_nothing"}, "not a dimension key": {"dim_column": "monday"}}.get(what)
        if what == "type mismatch":
            t = MODEL.table("fact_round_ops")
            model = replaced(MODEL, "fact_round_ops", columns=tuple(Column("round_key", "int64", "x") if c.name == "round_key" else c for c in t.columns))
            expected = "no existe o no es del tipo"
        else:
            model = dataclasses.replace(MODEL, relationships=(dataclasses.replace(first, **change), *MODEL.relationships[1:]))
            expected = {"bad cardinality": "uno a varios", "bad filter": "uno a varios", "inactive": "uno a varios", "missing fact column": "no existe", "unknown table": "inexistente", "not a dimension key": "clave de una dimensión"}[what]
    problems = validate_model(model)
    assert problems and any(expected in p for p in problems), (what, problems)


# --- the measures and the pages (U16) --------------------------------------------------------------------------------------------------------------------------------------

PAGE_NAMES = ("Las ofertas de la semana", "La lista contra las líneas base", "Productos nuevos y cobertura", "El grupo de control, listo para medir", "La prueba y la calidad de datos")
MEASURE_NAMES = (
    "Clientes en la base", "Reciben oferta", "Grupo de control", "Listas entregadas", "Parte de reserva", "Acierto (hit@10)", "Acierto por ronda", "Límite inferior", "Límite superior", "Recall (recall@10)",
    "Precisión (precisión@10)", "NDCG (NDCG@10)", "Cobertura", "Acierto solo nuevos", "Acierto por segmento", "Ofrecido a", "Comprado por", "Diferencia estandarizada", "Mayor diferencia estandarizada",
    "Rechazo del A/A", "p del A/A", "Menor efecto detectable", "Veredicto", "Última fecha de cálculo", "Reglas bloqueantes fallidas")
SEALED_FACTS = [t.name for t in MODEL.tables if "seal_state" in t.column_names]
PICKS = ("SELECTEDVALUE", "COUNTROWS", "DISTINCTCOUNT", "SUM", "AVERAGE", "SUMX", "MAXX", "MAX")


def test_the_measures_of_the_plan_exist_with_their_names_formats_and_descriptions():
    assert tuple(m.name_es for m in MEASURES) == MEASURE_NAMES and len(MODEL.measures) == 25 and len(set(MEASURE_NAMES)) == 25
    assert all(m.format_string and m.description_es and m.dax.count("(") == m.dax.count(")") for m in MEASURES)
    assert MODEL.measure("Veredicto").format_string == "@" and MODEL.measure("Última fecha de cálculo").format_string == "yyyy-mm-dd hh:mm" and MODEL.measure("Acierto (hit@10)").format_string == "0.0%"
    assert validate_model(MODEL) == []


def test_every_dax_reference_exists():
    columns = {t.name: {c.name: c for c in t.columns} for t in MODEL.tables}
    names = {m.name_es for m in MODEL.measures}
    for m in MODEL.measures:
        for table, column in dax_column_refs(m.dax):
            assert column in columns.get(table, {}), (m.name_es, table, column)
        for ref in dax_measure_refs(m.dax):
            assert ref in names and ref != m.name_es, (m.name_es, ref)
        for table in re.findall(r"\b(?:dim|fact)_\w+", m.dax):
            assert table in columns, (m.name_es, table)
        for function in re.findall(r"\b([A-Z][A-Z0-9.]*)(?=\s*\()", m.dax):
            assert function in DAX_FUNCTIONS, (m.name_es, function)
        for table, column, literal in re.findall(r'\b([a-z_]\w*)\[(\w+)\]\s*=\s*"([^"]*)"', m.dax):
            assert literal in columns[table][column].description_es, (m.name_es, table, column, literal)       # the text a column is compared with is one the column takes
        assert not re.search(r"\b(ALL|ALLEXCEPT|ALLSELECTED|REMOVEFILTERS|CROSSFILTER|USERELATIONSHIP|KEEPFILTERS)\b", m.dax), m.name_es       # no measure removes the slicers' filters
    for page in PAGES:
        for v in page.visuals:
            for field in v.fields:
                if field.startswith("["):
                    assert field[1:-1] in names, (page.name_es, v.title_es, field)
                else:
                    table, column = field.split("[")[0], field.split("[")[1].rstrip("]")
                    assert column in columns[table], (page.name_es, v.title_es, field)


def test_every_test_measure_reads_only_sealed_rows():
    """A measure that picks, sums or counts the rows of a table with a seal state would count a sealed and a post-seal row of the same key twice, or be blank when it picks one (project 04's D71): it asks for
    the sealed rows of every such table it reads. The measures of the follow-up (``fact_round_ops``, ``fact_offer_product``, ``dim_pipeline_run``, ``fact_validation``) have no seal state and are not asked for it."""
    for m in MEASURES:
        tables = {t for t, _ in dax_column_refs(m.dax) if t in SEALED_FACTS} | {t for t in re.findall(r"\b(?:dim|fact)_\w+", m.dax) if t in SEALED_FACTS}
        reads = any(re.search(rf"\b{p}\b", m.dax) for p in PICKS)
        for table in tables:
            if reads:
                assert f'{table}[seal_state] = "sealed"' in m.dax, (m.name_es, table)
    tested = {m.name_es for m in MEASURES if any(t in m.dax for t in SEALED_FACTS)}
    assert tested == set(MEASURE_NAMES) - {"Clientes en la base", "Reciben oferta", "Grupo de control", "Listas entregadas", "Parte de reserva", "Ofrecido a", "Comprado por", "Última fecha de cálculo",
                                           "Reglas bloqueantes fallidas"}, "every measure of the test is one of those"
    for name in ("Clientes en la base", "Ofrecido a", "Reglas bloqueantes fallidas", "Última fecha de cálculo"):
        assert "seal_state" not in MODEL.measure(name).dax, f"{name}: the operation has no sealed rows: it exists before the close"
    assert 'fact_experiment[test] = "preregistered"' in MODEL.measure("p del A/A").dax and 'fact_experiment[test] = "preregistered"' in MODEL.measure("Rechazo del A/A").dax
    assert 'fact_method_total[variant_key] = "new_only"' in MODEL.measure("Acierto solo nuevos").dax
    assert 'fact_validation[severity] = "bloqueante"' in MODEL.measure("Reglas bloqueantes fallidas").dax and 'fact_validation[status] = "falla"' in MODEL.measure("Reglas bloqueantes fallidas").dax
    assert 'dim_pipeline_run[status] = "ok"' in MODEL.measure("Última fecha de cálculo").dax


def test_no_measure_or_title_names_an_effect():
    """D16, AC27: no name of a table, a column, a measure, a page or a visual, and no DAX, says ``effect``, ``uplift`` or ``lift`` (but ``rule_lift``, the lift of an association rule); the Spanish word is only in the three
    phrases that the decision allows: the smallest detectable effect, that a difference is not an effect and that the archive does not let one be measured."""
    allowed = re.compile(r"menor efecto detectable|no es el efecto de nada|no es un efecto|permite medir el efecto de una oferta")
    english = re.compile(r"effect|uplift|\blift", re.I)
    names = [t.name for t in MODEL.tables] + [c.name for t in MODEL.tables for c in t.columns] + [m.name_es for m in MEASURES] + [m.dax for m in MEASURES] + [p.name_es for p in PAGES]
    names += [v.title_es for p in PAGES for v in p.visuals] + [f for p in PAGES for v in p.visuals for f in v.fields]
    for name in names:
        assert not english.search(name.replace("rule_lift", "")), name
    texts_es = [m.description_es for m in MEASURES] + [t.description_es for t in MODEL.tables] + [c.description_es for t in MODEL.tables for c in t.columns] + [p.note_es for p in PAGES] + [LEGEND]
    texts_es += [m.name_es for m in MEASURES] + [v.title_es for p in PAGES for v in p.visuals]
    for text in texts_es:
        rest = allowed.sub("", text.lower())
        assert "efecto" not in rest and "aumento" not in rest and not english.search(rest.replace("rule_lift", "")), text
    assert "Menor efecto detectable" in MEASURE_NAMES and LEGEND == "Sin ofertas reales: el archivo no permite medir el efecto de una oferta"
    assert PAGES[3].note_es.startswith("Esto no es un efecto")


def page(name: str) -> Page:
    return next(p for p in PAGES if p.name_es == name)


def visual(name: str, title: str) -> Visual:
    return next(v for v in page(name).visuals if v.title_es == title)


def test_there_are_five_pages_in_the_order_of_the_plan_inside_the_grid_without_overlaps():
    assert tuple(p.name_es for p in PAGES) == PAGE_NAMES and (PAGE_COLUMNS, PAGE_ROWS) == (12, 9)
    for p in PAGES:
        taken: set[tuple[int, int]] = set()
        for v in p.visuals:
            assert 0 <= v.x and v.x + v.w <= PAGE_COLUMNS and 0 <= v.y and v.y + v.h <= PAGE_ROWS and v.w >= 1 and v.h >= 1, (p.name_es, v.title_es)
            cells = {(x, y) for x in range(v.x, v.x + v.w) for y in range(v.y, v.y + v.h)}
            assert not cells & taken, (p.name_es, v.title_es)
            taken |= cells


def test_each_page_has_the_visuals_of_the_plan():
    first, second, third, fourth, fifth = PAGES
    assert [v.title_es for v in first.visuals if v.kind == "slicer"] == ["Ronda", "Segmento"]
    assert [v.fields[0] for v in first.visuals if v.kind == "card"] == ["[Clientes en la base]", "[Reciben oferta]", "[Grupo de control]", "[Listas entregadas]", "[Parte de reserva]"]
    assert any(v.kind == "barChart" and "por ronda" in v.title_es for v in first.visuals) and any("más ofrecidos" in v.title_es for v in first.visuals)
    assert [v.title_es for v in second.visuals if v.kind == "slicer"] == ["Variante", "Segmento"] and any("intervalo" in v.title_es for v in second.visuals)
    assert any(v.kind == "lineChart" for v in second.visuals) and any("Recall, precisión y NDCG" in v.title_es for v in second.visuals)
    assert any("solo con productos nuevos" in v.title_es for v in third.visuals) and any("Cobertura" in v.title_es for v in third.visuals) and any("elección" in v.title_es for v in third.visuals)
    assert any("rule_lift" in v.title_es for v in third.visuals) and fourth.note_es.startswith("Esto no es un efecto")
    assert any("A/A" in v.title_es for v in fourth.visuals) and any("podría ver" in v.title_es for v in fourth.visuals) and any("equilibrio" in v.title_es for v in fourth.visuals)
    assert [v.title_es for v in fifth.visuals][:1] == ["Criterios C01-C10"] and [v.fields[0] for v in fifth.visuals if v.kind == "card"] == ["[Reglas bloqueantes fallidas]", "[Última fecha de cálculo]"]
    assert {v.title_es for v in fifth.visuals} >= {"Reglas de validación", "Corridas"}


def _filtered_by(table: str) -> set[str]:
    """The tables a slicer on `table` filters: itself and, if it is a dimension, the facts it has a relationship with."""
    return {table} | {r.fact_table for r in MODEL.relationships if r.dim_table == table}


def _says_it_is_not_filtered_by(v: Visual, slicer: Visual) -> bool:
    match = re.search(r"\(no lo filtran? (.*)\)", v.title_es)
    return bool(match) and slicer.title_es.lower() in match.group(1).lower()


def test_every_slicer_reaches_the_visuals_of_its_page_through_a_relationship():
    """A slicer on a table with no path to a visual selects without filtering it, in silence (the correction A10 of project 04). Every slicer of every page reaches every visual of its page through the
    relationships of the model, or the visual's title says that this slicer does not filter it, and a title says so only when it is true."""
    slicers = 0
    for p in PAGES:
        for slicer in (v for v in p.visuals if v.kind == "slicer"):
            slicers += 1
            reached = _filtered_by(slicer.fields[0].split("[")[0])
            assert len(slicer.fields) == 1 and not slicer.fields[0].startswith("["), slicer.title_es
            for v in (v for v in p.visuals if v.kind != "slicer"):
                filtered = bool(reached & visual_tables(MODEL, v))
                assert filtered != _says_it_is_not_filtered_by(v, slicer), (p.name_es, slicer.title_es, v.title_es, filtered)
    assert slicers == 4
    # the two ways it can fail are seen: a slicer that reaches nothing of the page, and a title that says what is not so
    segment = visual(PAGE_NAMES[0], "Segmento")
    cards = next(v for v in page(PAGE_NAMES[0]).visuals if v.title_es.startswith("Clientes en la base"))
    assert not _filtered_by("dim_segment") & visual_tables(MODEL, cards) and _says_it_is_not_filtered_by(cards, segment)
    assert not _says_it_is_not_filtered_by(dataclasses.replace(cards, title_es="Clientes en la base"), segment)
    by_segment = next(v for v in page(PAGE_NAMES[1]).visuals if v.title_es == "Acierto por segmento")
    assert _filtered_by("dim_segment") & visual_tables(MODEL, by_segment), "the segment slicer of page 2 filters the segment bars"


def test_a_visual_reads_only_tables_that_the_relationships_join():
    """A column of a dimension next to a measure of a fact it has no relationship with would show the same number in every row; two facts need a dimension that joins them."""
    kinds = {t.name: t.kind for t in MODEL.tables}
    for p in PAGES:
        for v in p.visuals:
            tables = visual_tables(MODEL, v)
            dims, facts = [t for t in tables if kinds[t] == "dimension"], [t for t in tables if kinds[t] == "fact"]
            assert not (len(facts) >= 2 and not dims) and not (len(dims) >= 2 and not facts), (p.name_es, v.title_es)
            for d in dims:
                for f in facts:
                    assert f in _filtered_by(d), (p.name_es, v.title_es, d, f)


def test_the_model_check_names_every_way_a_measure_or_a_page_can_be_wrong():
    assert validate_model(MODEL) == []
    good = MEASURES[0]

    def with_(**changes) -> SemanticModel:
        return dataclasses.replace(MODEL, **changes)

    def measure(dax: str, **changes) -> SemanticModel:
        return with_(measures=(*MEASURES, dataclasses.replace(good, name_es="Nueva", dax=dax, **changes)))

    first = PAGES[0].visuals[0]
    cases = [
        (measure("SUM ( fact_round_ops[basez] )"), "fact_round_ops[basez]"), (measure("SUM ( fact_round_op[base] )"), "fact_round_op"), (measure("COUNTROWS ( fact_round )"), "fact_round"),
        (measure("[No existe] + 1"), "[No existe]"), (measure("[Nueva] + 1"), "[Nueva]"), (measure("SUM ( fact_round_ops[base] "), "paréntesis"),
        (measure('CALCULATE ( COUNTROWS ( fact_validation ), fact_validation[status] = "falla )'), "comillas"), (measure("MEDIAN ( fact_round_ops[base] )"), "MEDIAN"),
        (measure('CALCULATE ( COUNTROWS ( fact_validation ), fact_validation[status] = "bien" )'), "'bien'"), (measure("CALCULATE ( COUNTROWS ( fact_validation ), ALL ( fact_validation ) )"), "quita los filtros de los segmentadores"),
        (measure("SUM ( fact_round_ops[base] )", format_string=""), "formato"), (measure("SUM ( fact_round_ops[base] )", description_es=""), "descripción"), (with_(measures=(*MEASURES, MEASURES[0])), "repetida"),
        (with_(measures=(dataclasses.replace(MEASURES[0], dax="[Clientes en la base]"), *MEASURES[1:])), "no existe o es ella misma"),
        (with_(measures=(*MEASURES, dataclasses.replace(good, name_es="A", dax="[B] + 1"), dataclasses.replace(good, name_es="B", dax="[A] + 1"))), "en círculo"),
        (with_(pages=(*PAGES, PAGES[0])), "repetida"), (with_(pages=(*PAGES, Page("Vacía", ()))), "sin visuales"),
        (with_(pages=(Page("P", (dataclasses.replace(first, fields=("dim_round[nope]",)),)),)), "dim_round[nope]"),
        (with_(pages=(Page("P", (dataclasses.replace(first, fields=("dim_round[round_key]", "dim_segment[label_es]")),)),)), "un segmentador usa una sola columna"),
        (with_(pages=(Page("P", (dataclasses.replace(first, x=10, w=4),)),)), "sale de la grilla"), (with_(pages=(Page("P", (first, dataclasses.replace(first, title_es="Otro"))),)), "se superpone"),
        (with_(pages=(Page("P", (Visual("table", "Dos hechos", ("fact_round_ops[base]", "fact_balance[smd]"), 0, 0, 4, 2),)),)), "dos hechos sin una dimensión"),
        (with_(pages=(Page("P", (Visual("table", "Dos dimensiones", ("dim_round[round_key]", "dim_group[label_es]"), 0, 0, 4, 2),)),)), "dos dimensiones sin un hecho"),
        (with_(pages=(Page("P", (Visual("table", "Sin relación", ("dim_group[label_es]", "fact_round_ops[base]"), 0, 0, 4, 2),)),)), "no se unen por ninguna relación"),
    ]
    for model, text in cases:
        assert any(text in p for p in validate_model(model)), (text, validate_model(model))
    assert validate_model(dataclasses.replace(MODEL, measures=(), pages=())) == []          # a model without measures or pages is still checked as before


def test_no_text_of_the_report_promises_a_result_or_calls_a_figure_of_an_offer_real():
    forbidden = ("garantiza", "promete", "siempre acierta", "sin errores", "aumento", "ganancia", "retorno")
    texts = [m.description_es for m in MEASURES] + [v.title_es for p in PAGES for v in p.visuals] + [t.description_es for t in MODEL.tables] + [c.description_es for t in MODEL.tables for c in t.columns] + [p.note_es for p in PAGES]
    for text in texts:
        assert not any(word in text.lower() for word in forbidden), text
