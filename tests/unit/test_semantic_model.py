"""The semantic model of the report (U15, U16; AC26, AC27; decisions D30, D37; risk items 3 and 6): the tables, the keys and the 20 relationships of the plan are the single source of the Parquet schema, the data dictionary
and the design, and ``validate_model`` refuses an incoherent one. The measures and the pages join this file in U16."""

from __future__ import annotations

import dataclasses

import pyarrow as pa
import pytest

from personaloffers.dashboard.semantic_model import (
    ARROW_TYPES,
    CUSTOMER_COUNT_COLUMNS,
    DIMENSIONS,
    FACTS,
    MODEL,
    RELATIONSHIP_SPEC,
    Column,
    SemanticModel,
    arrow_schema,
    validate_model,
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
