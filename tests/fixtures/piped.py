"""The folder of a pipeline replay, copied for a test that changes something (U18): the files of the folder and a configuration whose paths are the copy's."""

from __future__ import annotations

import shutil
import types
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[2]
CONFIG_NAME = "test.toml"
PATHS = ("raw_dir", "interim_dir", "warehouse", "models_dir", "crm_db", "outputs_dir", "private_dir", "site_dir", "reports_dir", "figures_dir")


def write_config_file(root: Path, workbook) -> Path:
    """``<root>/config/test.toml``: the quick configuration made to accept the session's workbook with every path under `root`, the same one ``configs.config_for`` builds in memory but as the file that
    ``--config`` takes (the paths are relative to `root`, which is the parent of the folder that holds the file)."""
    folder = Path(root) / "config"
    folder.mkdir(parents=True, exist_ok=True)
    quote = lambda value: '"' + str(value).replace("\\", "/") + '"'   # noqa: E731
    lines = [f"extends = {quote((PROJECT / 'config' / 'pipeline.quick.toml').as_posix())}", "", "[source]", f"zip_path = {quote(Path(workbook.zip_path).as_posix())}", f"zip_bytes = {workbook.zip_bytes}",
             f"zip_sha256 = {quote(workbook.zip_sha256)}", f"member = {quote(workbook.member)}", f"member_bytes = {workbook.member_bytes}", f"member_sha256 = {quote(workbook.member_sha256)}", "", "[paths]",
             *(f"{name} = {quote(name)}" for name in PATHS), 'seal = "reports/model_seal.json"', 'dashboard_html = "dashboard/powerbi-design.html"', 'readme = "README.md"']
    path = folder / CONFIG_NAME
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    return path


QUICK_CONFIG = "pipeline.quick.toml"
LOCK_NAME = "pipeline.lock"


def config_of(state) -> str:
    """The configuration file of a folder (absolute: ``--config`` over a copy of a state): the quick configuration of a clone of the project, or the ``test.toml`` that ``write_config_file`` wrote."""
    config = Path(state.root) / "config"
    return str(config / QUICK_CONFIG) if (config / QUICK_CONFIG).is_file() else str(config / CONFIG_NAME)


def clone_state(root: Path, runs: list) -> types.SimpleNamespace:
    """A clone of the project (``config/``, ``docs/``, the README and ``data/quick/``, what the quick replay of ``quick_clone`` made) as the state of the pipeline tests: the quick configuration read from the
    clone, whose paths are the clone's own, the plan of deliveries and the runs that made it."""
    from personaloffers import deliveries
    from personaloffers.config import load_config
    from tests.fixtures.worlds import sealed_view_of

    cfg = load_config(Path(root) / "config" / QUICK_CONFIG)
    return types.SimpleNamespace(cfg=cfg, runs=runs, plan=deliveries.delivery_plan(sealed_view_of(cfg)), root=Path(root))


def copy_piped(piped, workbook, quick_cfg, destination: Path) -> types.SimpleNamespace:
    """A copy of the replayed clone with its configuration read from the copy (every path under it)."""
    shutil.copytree(piped.root, destination, dirs_exist_ok=True, copy_function=shutil.copyfile, ignore=shutil.ignore_patterns(LOCK_NAME))
    return clone_state(destination, getattr(piped, "runs", []))


def state_of(cfg, run_key: str) -> dict:
    import json

    return json.loads((Path(cfg.paths.interim_dir) / "runs" / f"{run_key}.json").read_text(encoding="utf-8"))


def run_keys(cfg) -> list[str]:
    return sorted(path.stem for path in (Path(cfg.paths.interim_dir) / "runs").glob("*.json"))
