"""Runbook R11, «Reconstruir desde cero», followed as written on a copy of the quick replay (RF25; AC34; D28; the lesson B3 of project 07): what R11 says to move aside is moved, ``replay`` runs, the launch adopts
the seal without choosing again, and the close reproduces the seal. A rebuild followed only in part never exits 0 having done nothing: it is refused before anything is written, and the refusal names R11."""

from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
from pathlib import Path

import pytest

from personaloffers import choose, registry
from tests.e2e.cli_helpers import cli, written
from tests.fixtures.piped import config_of, copy_piped

# R11, step 1: what is moved aside (never the seal, the models, the source or the reports: they are rewritten or are what is reproduced)
MOVED = ("warehouse", "interim_dir", "deliveries", "crm_db")


def paths_of(state) -> dict[str, Path]:
    p = state.cfg.paths
    return {"warehouse": Path(p.warehouse), "interim_dir": Path(p.interim_dir), "deliveries": Path(p.raw_dir) / "deliveries", "crm_db": Path(p.crm_db)}


def move_aside(state, names, aside: Path) -> None:
    for name in names:
        shutil.move(str(paths_of(state)[name]), str(aside / name))


def digest(root: Path) -> str:
    h = hashlib.sha256()
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        h.update(path.relative_to(root).as_posix().encode() + b"\0" + path.read_bytes())
    return h.hexdigest()


def rows(db: Path, sql: str) -> list:
    conn = sqlite3.connect(f"{db.resolve().as_uri()}?mode=ro", uri=True)
    try:
        return conn.execute(sql).fetchall()
    finally:
        conn.close()


ISSUED = ("SELECT round_id, customer_id, rank, stock_code, source, score, grp FROM offer_lists ORDER BY 1, 2, 3",
          "SELECT round_id, method, variant, customer_id, rank, stock_code FROM baseline_lists ORDER BY 1, 2, 3, 4, 5",
          "SELECT round_id, customer_id, bought, products, products_in_offer, spend, days_observed FROM round_outcomes ORDER BY 1, 2",
          "SELECT customer_id, grp, method, stratum, assigned_round FROM holdout_assignments ORDER BY 1",
          "SELECT criterion_id, tested_value_es, point_value, ci_low, ci_high, passed, verdict_es FROM eval_criteria WHERE seal_state = 'sealed' ORDER BY 1",
          "SELECT method, variant, round_id, pairs, hit_rate FROM eval_methods WHERE seal_state = 'sealed' ORDER BY 1, 2, 3",
          "SELECT round_id, component, artifact_path, artifact_sha256, fit_lines FROM model_registry ORDER BY 1, 2")


@pytest.mark.slow
def test_following_r11_rebuilds_and_reproduces_the_sealed_outputs(piped, workbook, quick_cfg, tmp_path, monkeypatch):
    state = copy_piped(piped, workbook, quick_cfg, tmp_path / "state")
    seal, models = Path(state.cfg.paths.seal), Path(state.cfg.paths.models_dir)
    site = Path(state.cfg.paths.site_dir)
    before = {"seal": seal.read_bytes(), "models": digest(models), "rows": [rows(Path(state.cfg.paths.warehouse), sql) for sql in ISSUED], "algorithms": json.loads((site / "algorithms.json").read_text(encoding="utf-8"))["methods"],
              "criteria": json.loads((site / "summary.json").read_text(encoding="utf-8"))["criteria"], "email": digest(Path(state.cfg.paths.private_dir) / "email")}
    aside = tmp_path / "aside"
    aside.mkdir()
    move_aside(state, MOVED, aside)
    monkeypatch.setattr(choose, "choose", lambda *a, **k: pytest.fail("R11 rebuilds with the seal: the recipe is not chosen again"))
    result = cli("replay", "--config", config_of(state))
    assert result.code == 0, result.err
    assert seal.read_bytes() == before["seal"], "the seal is as it was"
    assert [rows(Path(state.cfg.paths.warehouse), sql) for sql in ISSUED] == before["rows"], "the same lists, follow-up, control group, sealed evaluation and registry"
    assert digest(models) == before["models"], "the models are the same bytes (the ones of the later rounds were written again)"
    assert json.loads((site / "algorithms.json").read_text(encoding="utf-8"))["methods"] == before["algorithms"] and json.loads((site / "summary.json").read_text(encoding="utf-8"))["criteria"] == before["criteria"]
    assert digest(Path(state.cfg.paths.private_dir) / "email") == before["email"]
    states = [json.loads(p.read_text(encoding="utf-8")) for p in sorted((Path(state.cfg.paths.interim_dir) / "runs").glob("*.json"))]
    assert [s["tasks"]["fit_recipe"]["mode"] for s in states if s["tasks"]["fit_recipe"].get("mode") in ("adopt", "fresh")] == ["adopt"], "the launch registered the sealed models again, without a choice"
    assert [(s["tasks"]["evaluate"]["state"], s["tasks"]["evaluate"]["seal"]) for s in states if s["tasks"]["evaluate"].get("state")] == [("repeat", "unchanged")]
    assert registry.read_seal(seal)["test"]["criteria"], "the test part of the seal is the one that was"


@pytest.mark.parametrize("moved", [("warehouse", "interim_dir"), ("warehouse",)])
def test_a_half_done_rebuild_exits_2_and_names_r11(piped, workbook, quick_cfg, tmp_path, moved):
    """With the manifest of deliveries kept the deliveries look published and nothing is loaded: ``replay`` would exit 0 having done nothing, or would load them out of order."""
    state = copy_piped(piped, workbook, quick_cfg, tmp_path / "state")
    aside = tmp_path / "aside"
    aside.mkdir()
    move_aside(state, moved, aside)
    snapshot = written(state.root)
    for args in (("replay",), ("run",)):
        result = cli(*args, "--config", config_of(state))
        assert result.code == 2 and "R11" in result.err and "No se escribió nada" in result.err and "manifiesto de entregas" in result.err, (args, result.err)
    assert written(state.root) == snapshot
