"""The test does not start before the launch is sealed (U12; RNF07e, AC16; decision D21): a weekly delivery is refused, writing nothing, when the seal has no launch part and when it is another
configuration's. The refusal of an evaluation under another configuration is U14's and joins this file."""

from __future__ import annotations

import dataclasses
import hashlib
import json
from pathlib import Path

import pytest

from personaloffers import registry, weekly
from personaloffers.registry import LaunchSealMissingError, SealError, SealMismatchError
from tests.fixtures.worlds import RUN_KEY, copy_world, load_next_delivery


@pytest.fixture
def after_launch(launched, workbook, quick_cfg, tmp_path):
    made = copy_world(launched.root, workbook, quick_cfg, tmp_path / "after")
    yield made
    made.conn.close()


def digest(world) -> tuple:
    models = {p.relative_to(world.models_dir).as_posix(): p.read_bytes() for p in sorted(world.models_dir.rglob("*")) if p.is_file()}
    return hashlib.sha256(Path(world.warehouse_path).read_bytes()).hexdigest(), models


def test_a_weekly_delivery_is_refused_without_the_launch_seal(launch_template, workbook, quick_cfg, tmp_path):
    """The folder has the launch loaded and no seal (the launch did not run): the first weekly delivery is loaded and the round is refused before anything is written."""
    world = copy_world(launch_template, workbook, quick_cfg, tmp_path / "no_seal")
    try:
        spec = load_next_delivery(world, "run-2")
        assert spec.kind == "weekly" and not world.seal_path.exists()
        before = digest(world)
        with pytest.raises(LaunchSealMissingError, match="sello"):
            weekly.run_round(world.conn, world.view, "run-2", spec, models_dir=world.models_dir, seal_path=world.seal_path)
        with pytest.raises(LaunchSealMissingError):
            weekly.emit_round(world.conn, world.view, "run-2", spec.first_day, models_dir=world.models_dir, seal_path=world.seal_path)
        assert digest(world) == before and not world.seal_path.exists(), "nothing was written, and no seal was made up"
    finally:
        world.conn.close()


def test_a_seal_with_no_launch_part_is_not_a_seal_of_the_launch(after_launch):
    after_launch.seal_path.write_text(json.dumps({"version": 1, "launch": []}), encoding="utf-8")
    with pytest.raises(SealError):
        registry.require_launch_seal(after_launch.seal_path, registry.config_fingerprint(after_launch.view))


def test_the_seal_of_another_configuration_does_not_let_a_weekly_round_go_on(after_launch):
    changed = dataclasses.replace(after_launch.view, grid=dataclasses.replace(after_launch.view.grid, blend_trend_weights=(0.0, 0.5)))
    spec = load_next_delivery(after_launch, "run-2")
    before = digest(after_launch)
    with pytest.raises(SealMismatchError, match="R12"):
        weekly.run_round(after_launch.conn, changed, "run-2", spec, models_dir=after_launch.models_dir, seal_path=after_launch.seal_path)
    assert digest(after_launch) == before


def test_the_launch_part_of_a_matching_seal_is_what_the_round_receives(after_launch):
    launch = registry.require_launch_seal(after_launch.seal_path, registry.config_fingerprint(after_launch.view))
    assert launch["run_key"] == RUN_KEY and set(launch) == registry.LAUNCH_KEYS
    chosen, recipes = weekly.sealed_recipes(launch)
    assert chosen.name == launch["recipe"]["name"] and sorted(recipes) == ["b4", "b5", "b6"] and all(r.weight == 0.0 for r in recipes.values())
