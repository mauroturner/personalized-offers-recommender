"""The folder of a pipeline replay, copied for a test that changes something (U18): the files of the folder and a configuration whose paths are the copy's."""

from __future__ import annotations

import shutil
import types
from pathlib import Path

from tests.fixtures.configs import config_for


def copy_piped(piped, workbook, quick_cfg, destination: Path) -> types.SimpleNamespace:
    """A copy of the replayed folder with its configuration (every path under the copy)."""
    shutil.copytree(piped.root, destination, dirs_exist_ok=True)
    return types.SimpleNamespace(cfg=config_for(quick_cfg, workbook, destination), root=destination)


def state_of(cfg, run_key: str) -> dict:
    import json

    return json.loads((Path(cfg.paths.interim_dir) / "runs" / f"{run_key}.json").read_text(encoding="utf-8"))


def run_keys(cfg) -> list[str]:
    return sorted(path.stem for path in (Path(cfg.paths.interim_dir) / "runs").glob("*.json"))
