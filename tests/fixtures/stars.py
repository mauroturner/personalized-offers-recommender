"""The star model of the replay written to a folder of a test (U15): the ``evaluated`` replay copied and exported, with the minimum of customers of a cell as the test says (the fixture's cells are small: a test that
needs a shown cell, or exactly one hidden one, sets it)."""

from __future__ import annotations

import dataclasses
import types
from datetime import datetime
from pathlib import Path

from personaloffers import export, reporting
from personaloffers.dashboard.semantic_model import MODEL
from tests.fixtures.worlds import copy_world

RUN = reporting.RunMeta("run-5", datetime(2011, 4, 23))


def with_minimum(view, minimum: int):
    """`view` with ``[privacy] min_cell_customers`` set (the fingerprint changes: only the metadata of the files carries it)."""
    return dataclasses.replace(view, privacy=dataclasses.replace(view.privacy, min_cell_customers=minimum))


def export_world(template: Path, workbook, quick_cfg, folder: Path, *, minimum: int | None = None, run: reporting.RunMeta = RUN):
    """Copy the replay in `template` to `folder`, export its star model and return the world with ``out`` (published files), ``private`` (the private one), ``paths`` and ``view`` (the one that was exported)."""
    world = copy_world(template, workbook, quick_cfg, folder / "world")
    view = world.view if minimum is None else with_minimum(world.view, minimum)
    out, private = folder / "powerbi", folder / "private"
    paths = export.export_star_schema(world.conn, out, private, MODEL, run, view, seal_path=world.seal_path)
    return types.SimpleNamespace(world=world, conn=world.conn, out=out, private=private, paths=paths, view=view, run=run)
