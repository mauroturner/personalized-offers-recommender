"""The site files of a test world (U17): the six files written from the star model that ``tests.fixtures.stars.export_world`` built, with the counts of the source that the real run reads from the first build of the lines."""

from __future__ import annotations

import types
from pathlib import Path

from personaloffers import site_export
from personaloffers.warehouse import connect
from tests.fixtures.stars import RUN

SOURCE_COUNTS = {"copies_removed": 22523, "rows_by_sheet": {"Year 2009-2010": 525461, "Year 2010-2011": 541910}}
CAP = 204800


def export_site_of(warehouse_path: Path, world, view, folder: Path, *, run=RUN, cap: int = CAP, source_counts=SOURCE_COUNTS, private_dir: Path | None = None):
    """Write the six files of the star model held in `warehouse_path` to ``folder/site`` and return them read back with the arguments that wrote them."""
    conn = connect(warehouse_path)
    out = folder / "site"
    out.mkdir(parents=True, exist_ok=True)
    private = world.cfg.paths.private_dir if private_dir is None else private_dir
    try:
        paths = site_export.export_site(conn, out, run, view, seal_path=world.seal_path, private_dir=private, max_total_bytes=cap, source_counts=source_counts)
        return types.SimpleNamespace(conn=conn, out=out, paths=paths, site=site_export.read_site(out), view=view, run=run, seal_path=world.seal_path, private_dir=private, cap=cap,
                                     source_counts=source_counts)
    except BaseException:
        conn.close()
        raise
