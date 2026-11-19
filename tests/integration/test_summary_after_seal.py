"""The summary after the seal (U14; AC23, AC24; decision D21): a warehouse that does not hold the sealed rows (a new one, a quick copy, the site's build) takes C01-C10 from the seal, each one rebuilt from its
figures and compared with its own entry to 6 decimals; a seal the code cannot rebuild is never published. Before the close the summary says when the test is evaluated and shows the validation figures with their
rounds; the table has the column that says what each threshold tests."""

from __future__ import annotations

import copy
import json

import pytest

from personaloffers import evaluation, registry, reporting, warehouse
from personaloffers.registry import SealError
from tests.fixtures.worlds import copy_world


@pytest.fixture
def world(evaluated, workbook, quick_cfg, tmp_path):
    made = copy_world(evaluated.root, workbook, quick_cfg, tmp_path / "evaluated")
    yield made
    made.conn.close()


@pytest.fixture
def empty(tmp_path):
    """A warehouse with the schema and no row: what a new folder has."""
    conn = warehouse.connect(tmp_path / "new" / "w.sqlite")
    warehouse.apply_schema(conn)
    yield conn
    conn.close()


def test_a_warehouse_without_sealed_rows_takes_the_sealed_result_from_the_seal(world, empty, evaluated):
    """AC24: the summary of an empty warehouse and the one of the warehouse that evaluated are the same criteria, rebuilt from the seal and compared with the seal's own entries."""
    assert empty.execute("SELECT COUNT(*) FROM eval_criteria").fetchone()[0] == 0
    from_seal = reporting.build_summary(empty, world.view, seal_path=world.seal_path)
    from_rows = reporting.build_summary(world.conn, world.view, seal_path=world.seal_path)
    assert from_seal["source"] == "seal" and from_rows["source"] == "warehouse" and from_seal["evaluation_status"] == from_rows["evaluation_status"] == "sealed"
    ids = [c["criterion_id"] for c in from_seal["criteria"]]
    assert ids == [f"C{n:02d}" for n in range(1, 11)]
    for a, b in zip(from_seal["criteria"], from_rows["criteria"], strict=True):
        assert a["criterion_id"] == b["criterion_id"] and a["passed"] == b["passed"] and a["verdict_es"] == b["verdict_es"] and a["tested_value_es"] == b["tested_value_es"] and a["threshold_es"] == b["threshold_es"]
        for key in ("tested_value", "point_value", "ci_low", "ci_high"):
            assert (a[key] is None) == (b[key] is None) and (a[key] is None or a[key] == pytest.approx(b[key], abs=1e-6)), (a["criterion_id"], key)
    rebuilt = evaluation.criteria_from_seal(registry.read_seal(world.seal_path))
    assert [c.criterion_id for c in rebuilt] == ids and len(rebuilt) == 10
    assert from_seal["headline"] == from_rows["headline"] and from_seal["headline"]["rounds"] == 3 and from_seal["headline"]["pairs"] == evaluated.seal["test"]["metrics"]["pairs"]
    assert from_seal["validation"]["chosen"]["name"] == evaluated.seal["launch"]["validation"]["recipe"] and from_seal["validation"]["rounds"] == ["R2011-03-14", "R2011-03-21"]


def test_a_seal_that_cannot_be_rebuilt_from_its_own_figures_is_not_taken(world, empty, tmp_path):
    document = json.loads(world.seal_path.read_text(encoding="utf-8"))
    broken = copy.deepcopy(document)
    broken["test"]["metrics"]["diffs"]["list_vs_b2"]["ci_low"] = -0.5
    seal = tmp_path / "broken" / "model_seal.json"
    seal.parent.mkdir()
    seal.write_text(json.dumps(broken), encoding="utf-8")
    with pytest.raises(SealError, match="C01"):
        evaluation.criteria_from_seal(broken)
    with pytest.raises(SealError, match="C01"):
        reporting.build_summary(empty, world.view, seal_path=seal)
    for edit, expected in ((lambda d: d["test"]["criteria"][4].update(passed=not d["test"]["criteria"][4]["passed"]), "C05"), (lambda d: d["test"]["criteria"][8].update(verdict_es="otra cosa"), "C09"),
                           (lambda d: d["test"]["metrics"]["crm"].update(repeat_created=3), "C09"), (lambda d: d["test"]["metrics"]["calibration"]["rejection"].update(m1_preregistered=0.2), "C07")):
        changed = copy.deepcopy(document)
        edit(changed)
        with pytest.raises(SealError, match=expected):
            evaluation.criteria_from_seal(changed)
    with pytest.raises(SealError, match="parte de la prueba"):
        evaluation.criteria_from_seal({"launch": document["launch"]})
    short = copy.deepcopy(document)
    short["test"]["criteria"] = short["test"]["criteria"][:9]
    with pytest.raises(SealError, match="C01 a C10"):
        evaluation.criteria_from_seal(short)


def test_before_the_close_the_summary_says_when_the_test_is_evaluated_and_shows_the_validation_figures_with_their_rounds(launched, workbook, quick_cfg, tmp_path):
    world = copy_world(launched.root, workbook, quick_cfg, tmp_path / "launched")
    try:
        summary = reporting.build_summary(world.conn, world.view, seal_path=world.seal_path)
        assert summary["source"] == "pending" and summary["evaluation_status"] == "pending" and summary["headline"] is None
        assert [c["criterion_id"] for c in summary["criteria"]] == [f"C{n:02d}" for n in range(1, 11)] and all(c["passed"] is None for c in summary["criteria"])
        text = reporting.summary_markdown(summary)
        assert "La prueba se evalúa con el cierre del 2011-04-23: hasta entonces no hay veredictos." in text and "se midieron en 2 rondas, de R2011-03-14 a R2011-03-21" in text
        assert "Receta elegida entre" in text and "B4" in text and "B5" in text and "B6" in text and "hit@10 solo nuevos" in text
        assert "No se cumple" not in text and "Todos los criterios" not in text, "no verdict before the close"
        none = reporting.build_summary(world.conn, world.view, seal_path=world.seal_path.with_name("no_seal.json"))
        assert none["source"] == "pending" and none["validation"] == {} and "se midieron" not in reporting.summary_markdown(none)
    finally:
        world.conn.close()


def test_the_summary_shows_the_quantity_the_threshold_tests(world):
    """AC23, the lesson A1 of project 07: the column is «Lo que prueba el umbral» and not «Valor», and each cell is the text of the criterion's tested quantity: the lower limit for C01-C04, never the point value."""
    summary = reporting.build_summary(world.conn, world.view, seal_path=world.seal_path)
    text = reporting.summary_markdown(summary)
    header = next(line for line in text.splitlines() if line.startswith("| ID"))
    assert header == "| ID | Criterio | Umbral | Lo que prueba el umbral | Veredicto |" and "Valor" not in header
    rows = {line.split(" | ")[0].lstrip("| "): line for line in text.splitlines() if line.startswith("| C")}
    assert list(rows) == [f"C{n:02d}" for n in range(1, 11)]
    for criterion in summary["criteria"]:
        line = rows[criterion["criterion_id"]]
        assert criterion["tested_value_es"].replace("|", "\\|") in line and criterion["threshold_es"] in line and criterion["verdict_es"].replace("|", "\\|") in line
    c01 = next(c for c in summary["criteria"] if c["criterion_id"] == "C01")
    assert c01["tested_value_es"].endswith("(límite inferior)") and c01["tested_value"] == c01["ci_low"] != c01["point_value"]
    assert all(len(line.split(" | ")) == 5 for line in rows.values())


def test_a_criterion_that_is_not_met_is_named_with_its_number_and_the_text_says_the_archive_has_no_offers(world):
    summary = reporting.build_summary(world.conn, world.view, seal_path=world.seal_path)

    def told(failing):
        return reporting.summary_markdown({**summary, "criteria": [{**c, "passed": None if c["criterion_id"] == "C10" else c["criterion_id"] not in failing} for c in summary["criteria"]]})

    assert "No se cumple: C03." in told({"C03"}) and "No se cumple: C03, C05." in told({"C03", "C05"}) and "Todos los criterios con umbral se cumplen." in told(set())
    assert "Todos los criterios" not in told({"C01"}), "C10 has no threshold and is not a failure"
    for text in (told(set()), told({"C03"})):
        assert "El archivo no tiene ofertas" in text and "ninguna cifra es el efecto de una oferta" in text


def test_a_pipe_or_a_line_end_in_a_cell_does_not_break_the_table(world):
    summary = reporting.build_summary(world.conn, world.view, seal_path=world.seal_path)
    nasty = {**summary, "criteria": [{**summary["criteria"][0], "verdict_es": "a | b\nc", "tested_value_es": "x | y"}, *summary["criteria"][1:]]}
    lines = [line for line in reporting.summary_markdown(nasty).splitlines() if line.startswith("| C01")]
    assert lines == [f"| C01 | {summary['criteria'][0]['name_es']} | {summary['criteria'][0]['threshold_es']} | x \\| y | a \\| b c |"]


def test_the_status_is_post_seal_when_the_configuration_is_not_the_sealed_one(world):
    import dataclasses

    other = dataclasses.replace(world.view, criteria=dataclasses.replace(world.view.criteria, c05_min_coverage=0.5))
    summary = reporting.build_summary(world.conn, other, seal_path=world.seal_path)
    assert summary["evaluation_status"] == "post_seal" and summary["config_sha256"] == registry.read_seal(world.seal_path)["launch"]["config_sha256"] != registry.config_fingerprint(other)
    assert summary["source"] == "warehouse", "what was sealed is what is told"


def test_the_summary_is_written_as_json_and_markdown_atomically_and_the_results_block_is_replaced_in_place(world, tmp_path):
    summary = reporting.build_summary(world.conn, world.view, seal_path=world.seal_path)
    json_path, md_path = reporting.write_summary(summary, tmp_path / "reports")
    assert (json_path.name, md_path.name) == ("evaluation_summary.json", "evaluation_summary.md")
    assert json.loads(json_path.read_text(encoding="utf-8")) == json.loads(json.dumps(summary)) and md_path.read_text(encoding="utf-8") == reporting.summary_markdown(summary)
    again = reporting.write_summary(summary, tmp_path / "reports")
    assert (json_path.read_bytes(), md_path.read_bytes()) == (again[0].read_bytes(), again[1].read_bytes()) and sorted(p.name for p in json_path.parent.iterdir()) == ["evaluation_summary.json", "evaluation_summary.md"]
    text = f"# T\n\n{reporting.RESULTS_START}\nold\n{reporting.RESULTS_END}\n\nrest\n"
    new = reporting.replace_block(text, "README.md", reporting.RESULTS_START, reporting.RESULTS_END, "new\n")
    assert new == f"# T\n\n{reporting.RESULTS_START}\nnew\n{reporting.RESULTS_END}\n\nrest\n" and reporting.replace_block(new, "README.md", reporting.RESULTS_START, reporting.RESULTS_END, "new") == new
    for broken in ("no markers", f"{reporting.RESULTS_END}{reporting.RESULTS_START}", f"{reporting.RESULTS_START}{reporting.RESULTS_START}{reporting.RESULTS_END}"):
        with pytest.raises(ValueError, match="README.md"):
            reporting.replace_block(broken, "README.md", reporting.RESULTS_START, reporting.RESULTS_END, "x")


def test_the_headline_is_the_figures_of_the_test_as_the_warehouse_holds_them(world):
    headline = reporting.build_summary(world.conn, world.view, seal_path=world.seal_path)["headline"]

    def rate(method, variant):
        return world.conn.execute("SELECT hit_rate FROM eval_methods WHERE method = ? AND variant = ? AND round_id = 'all' AND seal_state = 'sealed'", (method, variant)).fetchone()[0]

    assert headline["hit_offer_list"] == pytest.approx(rate("offer_list", "unrestricted")) and headline["hit_b2"] == pytest.approx(rate("b2", "unrestricted")) and headline["hit_b3"] == pytest.approx(rate("b3", "unrestricted"))
    assert headline["hit_new_chosen"] == pytest.approx(rate("chosen_discovery", "new_only")) and headline["hit_new_b2"] == pytest.approx(rate("b2", "new_only"))
    assert headline["coverage"] == pytest.approx(world.conn.execute("SELECT coverage FROM eval_methods WHERE method = 'offer_list' AND round_id = 'all'").fetchone()[0])
    assert headline["max_abs_smd"] == pytest.approx(max(abs(r[0]) for r in world.conn.execute("SELECT smd FROM eval_balance")))
    assert headline["aa_p_m1"] == pytest.approx(world.conn.execute("SELECT aa_p FROM eval_experiment WHERE metric = 'm1' AND kind = 'preregistered'").fetchone()[0])
    assert headline["aa_p_m2"] == pytest.approx(world.conn.execute("SELECT aa_p FROM eval_experiment WHERE metric = 'm2' AND kind = 'preregistered'").fetchone()[0])
    assert headline["mde_m1_points_20"] == pytest.approx(100 * world.conn.execute("SELECT mde FROM eval_mde WHERE metric = 'm1' AND holdout_share = 0.2").fetchone()[0])
    assert headline["mde_m2_gbp_20"] == pytest.approx(world.conn.execute("SELECT mde FROM eval_mde WHERE metric = 'm2' AND holdout_share = 0.2").fetchone()[0])
    assert headline["rounds"] == 3 and headline["pairs"] == world.conn.execute("SELECT pairs FROM eval_methods WHERE method = 'offer_list' AND round_id = 'all'").fetchone()[0]
    assert headline["diff_list_b2_low"] == pytest.approx(world.conn.execute("SELECT tested_value FROM eval_criteria WHERE criterion_id = 'C01'").fetchone()[0])


def test_a_seal_without_its_launch_part_or_with_a_criterion_more_is_not_taken_and_the_entries_are_compared_at_six_decimals(evaluated):
    """L128: the happy rebuild and the refusals of ``criteria_from_seal`` that were not run: no launch part, a set of ids that is not C01 to C10, and the edge of the six decimals."""
    document = copy.deepcopy(evaluated.seal)
    assert [c.criterion_id for c in evaluation.criteria_from_seal(document)] == [f"C{n:02d}" for n in range(1, 11)]
    with pytest.raises(SealError, match="parte de la prueba"):
        evaluation.criteria_from_seal({"test": document["test"]})
    with pytest.raises(SealError, match="parte de la prueba"):
        evaluation.criteria_from_seal({})
    extra = copy.deepcopy(document)
    extra["test"]["criteria"].append({**extra["test"]["criteria"][0], "id": "C11"})
    with pytest.raises(SealError, match="C01 a C10"):
        evaluation.criteria_from_seal(extra)
    index = next(i for i, entry in enumerate(document["test"]["criteria"]) if entry["point_value"] is not None)
    near, over = copy.deepcopy(document), copy.deepcopy(document)
    base = round(document["test"]["criteria"][index]["point_value"], 6)
    near["test"]["criteria"][index]["point_value"] = base + 0.0000004      # under half of a millionth: the same sealed number
    over["test"]["criteria"][index]["point_value"] = base + 0.0000006      # over it: another one
    assert [c.criterion_id for c in evaluation.criteria_from_seal(near)] == [f"C{n:02d}" for n in range(1, 11)]
    with pytest.raises(SealError, match=document["test"]["criteria"][index]["id"]):
        evaluation.criteria_from_seal(over)
