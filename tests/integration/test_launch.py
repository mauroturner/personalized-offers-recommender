"""The launch (U11, risk item 1: the choice is made on validation rounds only, the seal is written once and before anything is registered, and what was registered is not redone; RF12, RF13,
AC14, AC16, AC36; M04; decisions D11, D12, D21, D23): what a launch seals, stores and registers, that it reproduces from the seal, and what it leaves when something fails after the seal."""

from __future__ import annotations

import dataclasses
import hashlib
import json
from pathlib import Path

import numpy as np
import pytest

from personaloffers import choose, holdout, launch, offers, registry, warehouse
from personaloffers import calendar as cal
from personaloffers import deliveries as dv
from personaloffers import validate as val
from personaloffers.recommend import artifacts, blend, context
from personaloffers.registry import SealError, SealMismatchError
from tests.fixtures.worlds import CONFIG_SHA, RUN_KEY, STARTED, copy_world


@pytest.fixture
def world(launch_template, workbook, quick_cfg, tmp_path):
    """The launch delivery loaded and nothing else (a copy of the template)."""
    made = copy_world(launch_template, workbook, quick_cfg, tmp_path / "world")
    yield made
    made.conn.close()


@pytest.fixture
def after(launched, workbook, quick_cfg, tmp_path):
    """A copy of the folder in which the launch ran."""
    made = copy_world(launched.root, workbook, quick_cfg, tmp_path / "after")
    yield made
    made.conn.close()


def go(world):
    return launch.run_launch(world.conn, world.view, world.run_key, models_dir=world.models_dir, seal_path=world.seal_path)


def tree(path: Path) -> dict[str, bytes]:
    return {p.relative_to(path).as_posix(): p.read_bytes() for p in sorted(Path(path).rglob("*")) if p.is_file()} if Path(path).exists() else {}


def state_of(world) -> tuple:
    """Everything a launch writes: the file of the warehouse, the seal, the folder of the models."""
    seal = world.seal_path.read_bytes() if world.seal_path.exists() else b""
    return (hashlib.sha256(Path(world.warehouse_path).read_bytes()).hexdigest(), seal, tree(world.models_dir))


# --- what a launch does ----------------------------------------------------------------------------------------------------------------------------


def test_a_launch_chooses_seals_stores_and_registers(launched, workbook, quick_cfg, tmp_path):
    world = copy_world(launched.root, workbook, quick_cfg, tmp_path / "w")
    try:
        result, seal = launched.result, launched.seal
        round_id = cal.round_id(quick_cfg.calendar.test_first_round)
        assert (result.mode, result.seal_state, result.sealed, result.registered, result.round_id) == ("fresh", "none", True, True, round_id)
        part = seal["launch"]
        assert set(part) == registry.LAUNCH_KEYS and part["config_sha256"] == registry.config_fingerprint(world.view) == result.config_sha256 and part["run_key"] == RUN_KEY
        assert part["validation"]["recipe"] == result.recipe.name == result.choice.chosen.name and part["recipe"]["name"] == result.recipe.name and sorted(part["baselines"]) == ["b4", "b5", "b6"]
        # the base and the draw of the first round
        assert world.conn.execute("SELECT round_id, period, built_by_run FROM rounds").fetchall() == [(round_id, "test", RUN_KEY)]
        stored = holdout.read_assignments(world.conn)
        assert holdout.fingerprint(stored) == part["holdout"]["fingerprint"] == result.holdout_fingerprint and set(stored["assigned_round"]) == {round_id} and set(stored["method"]) == {"stratified"}
        assert world.conn.execute("SELECT COUNT(*) FROM contact_base").fetchone()[0] == len(stored) == world.conn.execute("SELECT base_size FROM rounds").fetchone()[0]
        assert part["holdout"]["max_abs_smd"] == max(abs(v) for v in part["holdout"]["balance"].values()) and part["holdout"]["sizes"]["groups"]["control"] == int((stored["grp"] == "control").sum())
        # the models: the popularity of the round and the chosen model, registered with the hash of their manifests
        models = warehouse.registered_models(world.conn, round_id)
        assert sorted(models) == sorted(["popularity", result.recipe.model])
        for component, (path, digest, params) in models.items():
            assert path == f"{round_id}/{component}" and artifacts.artifact_sha256(world.models_dir / path) == digest and len(digest) == 64
            assert artifacts.read_component(world.models_dir / path, digest)[1] == params
        assert sorted(p.name for p in world.models_dir.iterdir()) == [round_id], "the folder of the candidates is gone"
        assert world.conn.execute("SELECT MIN(fit_lines) FROM model_registry").fetchone()[0] == len(warehouse.read_lines(world.conn))
    finally:
        world.conn.close()


def test_the_lists_of_the_first_round_can_be_rebuilt_from_the_registered_artifacts_alone(after, quick_cfg):
    """The arrays are for the independent evaluation: the sealed fingerprint of the lists is reproduced from the popularity and the model that were registered, without fitting anything."""
    world = after
    seal = registry.read_seal(world.seal_path)["launch"]
    round_id = seal["lists"]["round_id"]
    models = warehouse.registered_models(world.conn, round_id)
    arrays = {component: artifacts.read_component(world.models_dir / path, digest)[0] for component, (path, digest, _p) in models.items()}
    recipe = blend.Recipe(seal["recipe"]["model"], seal["recipe"]["size"], seal["recipe"]["weight"], regularization=seal["recipe"]["regularization"])
    monday = quick_cfg.calendar.test_first_round
    from personaloffers import base

    history = base.history_before(warehouse.read_lines(world.conn), monday)
    data = context.prepare(history, monday, base.contact_base(history, monday, world.view)["customer_id"].to_numpy(), world.view)
    popularity = arrays["popularity"]
    assert np.array_equal(popularity["codes"], data.codes) and np.array_equal(popularity["fallback"], data.fallback) and np.array_equal(popularity["tie_rank"], data.tie_rank)
    from personaloffers.recommend import factor, rules

    if recipe.model == "als":
        model = factor.AlsModel.from_arrays(arrays["als"])
    elif recipe.model == "cosine":
        model = factor.CosineModel.from_arrays(arrays["cosine"])
    else:
        model = rules.from_arrays(arrays["rules"])
    discovery = blend.blend(blend.model_scores(data, recipe, model), popularity["trend"], recipe.weight)
    products, sources = offers.build_list(data.repeat, discovery, data.seen, popularity["fallback"], world.view, tie_rank=popularity["tie_rank"])
    lists = offers.RoundLists(data.customers, products, sources, np.zeros(products.shape))
    assert offers.lists_fingerprint(lists, popularity["codes"]) == seal["lists"]["fingerprint"]


def test_the_seal_is_written_before_the_base_the_models_or_the_registry_are(world, monkeypatch):
    order: list[str] = []
    for module, name in ((registry, "write_launch_seal"), (warehouse, "store_round_base"), (warehouse, "register_models"), (choose, "choose")):
        original = getattr(module, name)
        monkeypatch.setattr(module, name, lambda *a, _o=original, _n=name, **k: order.append(_n) or _o(*a, **k))
    go(world)
    assert order == ["choose", "write_launch_seal", "store_round_base", "register_models"]


def test_every_candidate_names_its_fit_rounds(launched, quick_view):
    rounds = [cal.round_id(m) for m in cal.rounds(quick_view, "validation")]
    part = launched.seal["launch"]["validation"]
    assert part["rounds"] == rounds and len(part["candidates"]) == 6
    for candidate in part["candidates"]:
        assert candidate["fit_rounds"] == rounds and sorted(candidate["per_round"]) == sorted(rounds), candidate["name"]
    assert choose.from_dict(part).chosen.name == launched.result.recipe.name and part["digest"] == choose.digest(launched.result.choice)


def test_no_validation_figure_reads_a_line_from_the_first_test_day(world, quick_cfg):
    """M04: the warehouse of the launch holds no line of the test, and the figures of the seal are those of a direct choice on its lines (nothing else can have been in them)."""
    lines = warehouse.read_lines(world.conn)
    assert lines["invoice_date"].max() < np.datetime64(quick_cfg.calendar.test_first_round)
    result = go(world)
    assert choose.digest(result.choice) == choose.digest(choose.choose(lines, world.view)) == registry.read_seal(world.seal_path)["launch"]["validation"]["digest"]


def test_a_warehouse_with_a_line_of_the_test_is_refused_and_nothing_is_written(launch_template, workbook, quick_cfg, tmp_path):
    made = copy_world(launch_template, workbook, quick_cfg, tmp_path / "w")
    try:
        spec = made.plan[1]
        path = dv.delivery_path(made.cfg, spec)
        report = val.validate_delivery(spec, path, made.conn, made.view, run_key="run-2")
        warehouse.load_delivery(made.conn, spec, dv.read_delivery(path), report, "run-2", started_at=STARTED, config_sha256=CONFIG_SHA)
        before = state_of(made)
        with pytest.raises(choose.ValidationLeakError, match="R5"):
            go(made)
        assert state_of(made) == before and not made.seal_path.exists() and not made.models_dir.exists()
    finally:
        made.conn.close()


# --- a launch that is repeated, adopted and reproduced -----------------------------------------------------------------------------------------------


def test_launching_again_writes_nothing_and_checks_what_is_stored_against_the_seal(after):
    before = state_of(after)
    again = go(after)
    assert (again.mode, again.seal_state, again.sealed, again.registered) == ("done", "match", False, False)
    assert state_of(after) == before and again.recipe.name == registry.read_seal(after.seal_path)["launch"]["recipe"]["name"]


def test_a_failure_after_the_seal_leaves_no_orphan_and_the_next_fit_adopts(world, monkeypatch):
    """AC36: the registry fails after the seal was written. Nothing is registered (no row without its artifact), the candidates are kept, and the next launch adopts the seal: it does not choose again."""
    original = warehouse.register_models

    def fail(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(warehouse, "register_models", fail)
    with pytest.raises(OSError, match="disk full"):
        go(world)
    assert world.seal_path.exists() and warehouse.registered_models(world.conn, "R2011-03-28") == {}
    assert world.conn.execute("SELECT COUNT(*) FROM model_registry").fetchone()[0] == 0, "no orphan row"
    kept = launch.candidates_folder(world.models_dir, RUN_KEY)
    assert kept.exists() and len(list((world.models_dir / "R2011-03-28").iterdir())) == 2, "the artifacts are in place and the candidates folder was not cleared"
    sealed = world.seal_path.read_bytes()
    monkeypatch.setattr(warehouse, "register_models", original)
    monkeypatch.setattr(choose, "choose", lambda *a, **k: pytest.fail("the next fit does not choose again"))
    adopted = go(world)
    assert (adopted.mode, adopted.seal_state, adopted.sealed, adopted.registered) == ("adopt", "match", False, True)
    assert world.seal_path.read_bytes() == sealed, "the seal was not touched"
    assert sorted(warehouse.registered_models(world.conn, "R2011-03-28")) == sorted(["popularity", adopted.recipe.model]) and not kept.exists()


def test_candidate_artifacts_are_kept_when_the_choice_fails(world, monkeypatch):
    """The fit and its artifacts are written under the candidates folder first: if the seal cannot be written they stay there for the next attempt, and nothing is sealed, stored or registered."""
    original = registry.write_launch_seal
    monkeypatch.setattr(registry, "write_launch_seal", lambda *a, **k: (_ for _ in ()).throw(OSError("cannot write")))
    with pytest.raises(OSError, match="cannot write"):
        go(world)
    kept = launch.candidates_folder(world.models_dir, RUN_KEY)
    assert len(list((kept / "R2011-03-28").iterdir())) == 2 and not world.models_dir.joinpath("R2011-03-28").exists()
    assert not world.seal_path.exists() and world.conn.execute("SELECT COUNT(*) FROM rounds").fetchone()[0] == 0 and world.conn.execute("SELECT COUNT(*) FROM model_registry").fetchone()[0] == 0
    monkeypatch.setattr(registry, "write_launch_seal", original)
    retried = go(world)
    assert (retried.mode, retried.sealed, retried.registered) == ("fresh", True, True) and not kept.exists(), "the retry finishes and clears the candidates"


def test_a_choice_that_fails_writes_nothing_at_all(world, monkeypatch):
    monkeypatch.setattr(choose, "choose", lambda *a, **k: (_ for _ in ()).throw(choose.ChoiceError("sin pares")))
    before = state_of(world)
    with pytest.raises(choose.ChoiceError):
        go(world)
    assert state_of(world) == before and not world.models_dir.exists()


def test_the_launch_is_reproduced_from_the_seal_in_a_new_folder_bit_for_bit(launched, launch_template, workbook, quick_cfg, tmp_path):
    """R11 in miniature: a folder in which only the launch is loaded, with the seal copied in, adopts it and registers the same artifacts (the same hashes) and the same draw."""
    fresh = copy_world(launch_template, workbook, quick_cfg, tmp_path / "rebuild")
    try:
        fresh.seal_path.parent.mkdir(parents=True, exist_ok=True)
        fresh.seal_path.write_bytes((launched.root / "reports" / "model_seal.json").read_bytes())
        result = go(fresh)
        assert (result.mode, result.sealed, result.registered) == ("adopt", False, True)
        original = copy_world(launched.root, workbook, quick_cfg, tmp_path / "original")
        try:
            assert warehouse.registered_models(fresh.conn, "R2011-03-28") == warehouse.registered_models(original.conn, "R2011-03-28")
            assert holdout.read_assignments(fresh.conn).equals(holdout.read_assignments(original.conn))
            assert fresh.conn.execute("SELECT * FROM contact_base ORDER BY customer_id").fetchall() == original.conn.execute("SELECT * FROM contact_base ORDER BY customer_id").fetchall()
        finally:
            original.conn.close()
    finally:
        fresh.conn.close()


@pytest.mark.parametrize("field", ["lists_fingerprint", "holdout_fingerprint", "validation_digest"])
def test_a_launch_that_does_not_reproduce_the_seal_names_what_differs_and_writes_nothing(field, launched, launch_template, workbook, quick_cfg, tmp_path):
    fresh = copy_world(launch_template, workbook, quick_cfg, tmp_path / "rebuild")
    try:
        document = json.loads((launched.root / "reports" / "model_seal.json").read_text(encoding="utf-8"))
        place = registry.COMPARED[field]
        document["launch"][place[0]][place[1]] = "0" * 64
        fresh.seal_path.parent.mkdir(parents=True, exist_ok=True)
        tampered = (json.dumps(document, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")
        fresh.seal_path.write_bytes(tampered)
        before = (hashlib.sha256(Path(fresh.warehouse_path).read_bytes()).hexdigest(), tree(fresh.models_dir))
        with pytest.raises(SealMismatchError, match=field):
            go(fresh)
        assert (hashlib.sha256(Path(fresh.warehouse_path).read_bytes()).hexdigest(), tree(fresh.models_dir)) == before and fresh.seal_path.read_bytes() == tampered
    finally:
        fresh.conn.close()


def test_another_configuration_with_a_seal_is_post_seal_and_the_seal_is_left_alone(launched, launch_template, workbook, quick_cfg, tmp_path):
    """M03: the seal of another configuration is never replaced; what is computed under the new one is post-seal. A warehouse that already holds the sealed round refuses (runbook R12)."""
    after_launch = copy_world(launched.root, workbook, quick_cfg, tmp_path / "after")
    fresh = copy_world(launch_template, workbook, quick_cfg, tmp_path / "fresh")
    try:
        changed = dataclasses.replace(after_launch.view, grid=dataclasses.replace(after_launch.view.grid, blend_trend_weights=(0.0, 0.5)))
        assert registry.seal_state(after_launch.seal_path, registry.config_fingerprint(changed)) == "post_seal"
        before = state_of(after_launch)
        with pytest.raises(SealMismatchError, match="R12"):
            launch.run_launch(after_launch.conn, changed, RUN_KEY, models_dir=after_launch.models_dir, seal_path=after_launch.seal_path)
        assert state_of(after_launch) == before
        fresh.seal_path.parent.mkdir(parents=True, exist_ok=True)
        fresh.seal_path.write_bytes((launched.root / "reports" / "model_seal.json").read_bytes())
        sealed = fresh.seal_path.read_bytes()
        result = launch.run_launch(fresh.conn, changed, RUN_KEY, models_dir=fresh.models_dir, seal_path=fresh.seal_path)
        assert (result.mode, result.seal_state, result.sealed, result.registered) == ("fresh", "post_seal", False, True) and fresh.seal_path.read_bytes() == sealed
        assert {c.recipe.weight for c in result.choice.candidates} == {0.0, 0.5}
    finally:
        after_launch.conn.close()
        fresh.conn.close()


def test_a_seal_that_cannot_be_read_stops_the_launch_before_anything_is_written(world):
    world.seal_path.parent.mkdir(parents=True, exist_ok=True)
    world.seal_path.write_text("{ not json", encoding="utf-8")
    before = state_of(world)
    with pytest.raises(SealError, match="R7"):
        go(world)
    assert state_of(world) == before


def test_an_artifact_that_changed_after_it_was_registered_is_found_by_the_next_launch(after):
    path = next((after.models_dir / "R2011-03-28" / "popularity").glob("fallback.npy"))
    data = path.read_bytes()
    path.write_bytes(data[:-1] + bytes([data[-1] ^ 1]))
    with pytest.raises(artifacts.ArtifactError, match="huella"):
        go(after)


def test_an_adopted_launch_refuses_a_warehouse_with_a_line_of_the_test_too(launched, launch_template, workbook, quick_cfg, tmp_path):
    made = copy_world(launch_template, workbook, quick_cfg, tmp_path / "w")
    try:
        made.seal_path.parent.mkdir(parents=True, exist_ok=True)
        made.seal_path.write_bytes((launched.root / "reports" / "model_seal.json").read_bytes())
        spec = made.plan[1]
        path = dv.delivery_path(made.cfg, spec)
        report = val.validate_delivery(spec, path, made.conn, made.view, run_key="run-2")
        warehouse.load_delivery(made.conn, spec, dv.read_delivery(path), report, "run-2", started_at=STARTED, config_sha256=CONFIG_SHA)
        before = state_of(made)
        with pytest.raises(choose.ValidationLeakError, match="R5"):
            go(made)
        assert state_of(made) == before
    finally:
        made.conn.close()


def test_an_artifact_that_is_installed_with_another_hash_is_not_replaced_by_the_launch(world):
    """The refusal of ``_install`` (runbook R6): a folder in the final place with other content than the candidate is what a registered round would have, so it is kept, the registry gets no row, and the launch
    says so. The seal that was written before stays, so the next fit adopts it once the folder is dealt with."""
    planted = artifacts.write_component(world.models_dir, "R2011-03-28", "popularity", {"codes": np.arange(3)}, {"planted": True})
    before = tree(world.models_dir / "R2011-03-28")
    with pytest.raises(artifacts.ArtifactError, match="ya está en su lugar"):
        go(world)
    assert tree(world.models_dir / "R2011-03-28") == before and artifacts.artifact_sha256(planted.path) == planted.sha256, "the folder that was there is as it was"
    assert world.conn.execute("SELECT COUNT(*) FROM model_registry").fetchone()[0] == 0 and world.seal_path.exists()
    assert launch.candidates_folder(world.models_dir, RUN_KEY).exists(), "the candidates are kept for the next attempt"
