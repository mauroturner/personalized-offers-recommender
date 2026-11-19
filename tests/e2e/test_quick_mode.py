"""The quick mode, isolated (U19; AC33; plan sections 4 and 24.1; D44; lesson B3 of project 01): from a clean clone and from another directory the quick replay ends, and nothing outside ``data/quick/`` changes,
neither in the clone nor in the project folder of the tests. The run is ``make-fixture`` and ``replay`` through the command line, ``$PERSONALOFFERS_HOME`` on the clone and the working directory elsewhere."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from personaloffers import site_export
from personaloffers.config import ENV_CONFIG, ENV_HOME
from tests.e2e.cli_helpers import PROJECT_ROOT, cli, fingerprint


@pytest.mark.slow
def test_quick_replay_from_other_cwd_touches_only_data_quick(tmp_path, monkeypatch):
    clone, elsewhere = tmp_path / "clone", tmp_path / "elsewhere"
    elsewhere.mkdir()
    for name in ("config", "docs"):
        shutil.copytree(PROJECT_ROOT / name, clone / name)
    shutil.copyfile(PROJECT_ROOT / "README.md", clone / "README.md")
    monkeypatch.setenv(ENV_HOME, str(clone))
    monkeypatch.delenv(ENV_CONFIG, raising=False)
    monkeypatch.chdir(elsewhere)
    project_before, clone_before, elsewhere_before = fingerprint(PROJECT_ROOT), fingerprint(clone), fingerprint(elsewhere)
    fixture = cli("make-fixture", "data/quick/online_retail_fixture.zip")
    replay = cli("replay", "--config", "config/pipeline.quick.toml")
    assert fixture.code == 0 and replay.code == 0 and "5 corridas" in replay.out and "L2011-03-27" in replay.out and "C2011-04-18" in replay.out, (fixture.err, replay.err)
    assert fingerprint(PROJECT_ROOT) == project_before, "the project folder of the tests is not touched by a quick run in a clone"
    after = fingerprint(clone)
    assert {k: v for k, v in after.items() if not k.startswith("data/quick/")} == clone_before and {k for k in after if k.startswith("data/quick/")}, "only data/quick/ changed in the clone"
    assert fingerprint(elsewhere) == elsewhere_before == {}, "nothing was written in the working directory the command ran from"
    quick = clone / "data" / "quick"
    assert (quick / "personaloffers.sqlite").is_file() and (quick / "reports" / "model_seal.json").is_file() and (quick / "dashboard" / "powerbi-design.html").is_file()
    assert site_export.verify_site(quick / "outputs" / "site") == [] and site_export.read_site(quick / "outputs" / "site").summary["evaluation_status"] == "sealed"


def test_the_quick_configuration_keeps_every_path_under_data_quick(quick_cfg):
    """No path of the quick mode names a place outside ``data/quick/`` (the configuration refuses an empty accepted hash unless the zip is under it)."""
    quick = PROJECT_ROOT / "data" / "quick"
    for field in ("raw_dir", "interim_dir", "warehouse", "models_dir", "crm_db", "outputs_dir", "private_dir", "site_dir", "reports_dir", "seal", "dashboard_html", "readme", "figures_dir"):
        path = Path(getattr(quick_cfg.paths, field))
        assert quick in path.parents, field
    assert quick in Path(quick_cfg.source.zip_path).parents
