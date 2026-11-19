"""Folders in which a delivery of the fixture is loaded (U11 on): the deliveries published and the warehouse with the launch loaded by ``run-1``, built once for the session and copied by
each test that changes anything (every load fsyncs, and every test that starts from a loaded launch would pay it again)."""

from __future__ import annotations

import shutil
import types
from datetime import datetime
from pathlib import Path

from personaloffers import deliveries as dv
from personaloffers import validate as val
from personaloffers import warehouse
from personaloffers.config import SealedConfig
from personaloffers.warehouse import connect, load_delivery
from tests.fixtures.configs import config_for

STARTED = datetime(2011, 4, 4, 8, 30, 15)
RUN_KEY = "run-1"
CONFIG_SHA = "d" * 64


def sealed_view_of(cfg) -> SealedConfig:
    return SealedConfig.of(cfg, "a" * 64, "b" * 64, "c" * 64)


def build_launch_template(workbook, quick_cfg, fixture_lines, root: Path) -> Path:
    """`root` with ``project/`` (the deliveries of the fixture published) and a warehouse in which ``run-1`` loaded the launch (the first delivery); closed."""
    cfg = config_for(quick_cfg, workbook, root)
    view = sealed_view_of(cfg)
    plan = dv.delivery_plan(view)
    for spec in plan:
        dv.publish_delivery(cfg, fixture_lines, spec)
    conn = connect(cfg.paths.warehouse)
    spec = plan[0]
    path = dv.delivery_path(cfg, spec)
    report = val.validate_delivery(spec, path, conn, view, run_key=RUN_KEY)
    load_delivery(conn, spec, dv.read_delivery(path), report, RUN_KEY, started_at=STARTED, config_sha256=CONFIG_SHA)
    conn.close()
    return root


def copy_world(template: Path, workbook, quick_cfg, destination: Path, *, open_warehouse: bool = True) -> types.SimpleNamespace:
    """A copy of a template folder as a world: its configuration (every path under the copy), the sealed view, the plan of deliveries and, open, its warehouse."""
    shutil.copytree(template, destination, dirs_exist_ok=True)
    cfg = config_for(quick_cfg, workbook, destination)
    view = sealed_view_of(cfg)
    conn = connect(cfg.paths.warehouse) if open_warehouse else None
    return types.SimpleNamespace(cfg=cfg, view=view, plan=dv.delivery_plan(view), conn=conn, root=destination, seal_path=cfg.paths.seal, models_dir=cfg.paths.models_dir, run_key=RUN_KEY,
                                 warehouse_path=cfg.paths.warehouse)


def lines_of(world) -> object:
    """The lines the warehouse holds, as the tasks read them."""
    return warehouse.read_lines(world.conn)


def load_next_delivery(world, run_key: str):
    """Validate and load the next delivery of the plan that is not loaded (what the tasks ``validate`` and ``load`` do, in this order); returns its spec."""
    spec = dv.next_to_load(world.plan, val.loaded_ids(world.conn))
    path = dv.delivery_path(world.cfg, spec)
    report = val.validate_delivery(spec, path, world.conn, world.view, run_key=run_key)
    load_delivery(world.conn, spec, dv.read_delivery(path), report, run_key, started_at=STARTED, config_sha256=CONFIG_SHA)
    return spec


def replay(world) -> list:
    """From a folder in which the launch ran: the lists of the first round, then each weekly delivery and the close, loaded and run in order (``run-2``, ``run-3``...); returns what each gave."""
    from personaloffers import weekly

    results = [weekly.emit_round(world.conn, world.view, RUN_KEY, world.view.calendar.test_first_round, models_dir=world.models_dir, seal_path=world.seal_path)]
    for number in range(2, len(world.plan) + 1):
        run_key = f"run-{number}"
        spec = load_next_delivery(world, run_key)
        results.append(weekly.run_round(world.conn, world.view, run_key, spec, models_dir=world.models_dir, seal_path=world.seal_path))
    return results
