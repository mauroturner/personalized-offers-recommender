"""``docs-sync`` (U19; RF26; the deviation of U23 of project 07 that was left open): the results block of the README from the summary and the table of each Parquet file in the data dictionary from the semantic
model; a second use changes nothing and a file without its markers is left as it was."""

from __future__ import annotations

import pytest

from personaloffers import docs_sync
from personaloffers.dashboard.semantic_model import MODEL


def start(name: str) -> str:
    return f"<!-- table:{name}:start -->"


def end(name: str) -> str:
    return f"<!-- table:{name}:end -->"


def dictionary_with(names, body="viejo") -> str:
    return "# Diccionario\n\n" + "".join(f"## {name}\n{start(name)}\n{body}\n{end(name)}\n\n" for name in names) + "fin\n"


def test_a_block_is_the_table_of_the_columns_with_their_type_key_and_description():
    table = MODEL.table("fact_round_ops")
    block = docs_sync.dictionary_block(table)
    lines = block.strip().splitlines()
    assert lines[0].startswith("| Columna | Tipo |") and len(lines) == 2 + len(table.columns)
    for column, line in zip(table.columns, lines[2:], strict=True):
        assert line.startswith(f"| `{column.name}` | {column.dtype} |") and column.description_es.replace("|", "\\|") in line
    assert all(line.count("|") - line.count("\\|") == lines[0].count("|") for line in lines), "every row has the width of its header"
    assert "clave" in block.lower() and "round_key" in block


def test_every_table_of_the_model_has_its_block_filled_and_a_second_use_changes_nothing():
    names = [t.name for t in MODEL.tables]
    text = dictionary_with(names)
    filled = docs_sync.sync_dictionary(text, MODEL)
    assert "viejo" not in filled and filled.endswith("fin\n") and all(f"`{c.name}`" in filled for t in MODEL.tables for c in t.columns)
    assert docs_sync.sync_dictionary(filled, MODEL) == filled


def test_a_table_without_its_markers_leaves_the_text_as_it_was_and_names_the_table():
    names = [t.name for t in MODEL.tables][:-1]
    with pytest.raises(ValueError, match=MODEL.tables[-1].name):
        docs_sync.sync_dictionary(dictionary_with(names), MODEL)
    with pytest.raises(ValueError, match="fact_round_ops"):
        docs_sync.sync_dictionary(dictionary_with([t.name for t in MODEL.tables]).replace(end("fact_round_ops"), "", 1), MODEL)
