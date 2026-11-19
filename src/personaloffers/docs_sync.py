"""The data dictionary kept in step with the semantic model (RF26; the deviation of U23 of project 07 that was left open): the table of each Parquet file is written from ``dashboard.semantic_model``, between the
markers ``<!-- table:<name>:start -->`` and ``<!-- table:<name>:end -->`` of ``docs/data-dictionary.md``, so what a file holds and what the documentation says cannot drift apart. ``docs-sync`` (the command) uses
``sync_dictionary``; a table whose markers are missing or repeated is a ``ValueError`` that names it and nothing is written."""

from __future__ import annotations

from personaloffers.dashboard.semantic_model import SemanticModel, Table
from personaloffers.reporting import replace_block

START, END = "<!-- table:{name}:start -->", "<!-- table:{name}:end -->"
HEADER = ("| Columna | Tipo | Clave | Unidad | Descripción |", "| --- | --- | --- | --- | --- |")


def _cell(text: object) -> str:
    return str(text).replace("|", "\|").replace("\n", " ")


def dictionary_block(table: Table) -> str:
    """The Markdown table of the columns of `table`: name, type, whether it is part of the key (the grain of a fact), unit and description."""
    rows = [f"| `{c.name}` | {c.dtype} | {'sí' if c.name in table.key else ''} | {_cell(c.unit or '')} | {_cell(c.description_es)} |" for c in table.columns]
    return "\n".join([*HEADER, *rows]) + "\n"


def sync_dictionary(text: str, model: SemanticModel) -> str:
    """`text` with the table of every table of `model` between its markers; a second use gives the same text."""
    for table in model.tables:
        text = replace_block(text, table.name, START.format(name=table.name), END.format(name=table.name), dictionary_block(table))
    return text
