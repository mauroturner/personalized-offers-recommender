"""Shared fixtures, the automatic skipping of the marks whose requirement is missing, the fast suite's time limit (plan, section 24.1) and the guard of the tree.

The fixtures of the units that come later (the loaded warehouses, the launch and the replayed rounds, the site files and the rendered design) are added by the unit
that writes the code they need.
"""

from __future__ import annotations

import gc
import os
import shutil
from pathlib import Path

# implicit warns, and slows down, with the threads of BLAS: one thread, set before anything imports numpy or implicit (plan, section 2; RNF01)
os.environ["OPENBLAS_NUM_THREADS"] = "1"
os.environ["MKL_NUM_THREADS"] = "1"

import pytest  # noqa: E402

from tests.fixtures import suite_budget, tree_guard  # noqa: E402

pytest_plugins = ["pytester"]
pytest_addoption = suite_budget.pytest_addoption

# The session fixtures keep the fixtures' frames and their warehouses alive for the whole run, and every full collection of the garbage collector walks all of them
# again. The thresholds are raised so that it runs far less often; garbage in cycles is still freed, only later. It changes no value and no test (project 04, D93).
gc.set_threshold(200_000, 100, 100)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
REAL_ZIP = PROJECT_ROOT / "data" / "raw" / "online_retail_ii.zip"


def pytest_sessionstart(session: pytest.Session) -> None:
    suite_budget.pytest_sessionstart(session)
    tree_guard.start(session.config)


@pytest.hookimpl(trylast=True)
def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    tree_guard.finish(session)
    suite_budget.pytest_sessionfinish(session, exitstatus)


@pytest.fixture(scope="session", autouse=True)
def _no_flush_to_the_device():
    """``os.fsync`` makes a file survive a power cut, which no test can cause, and it takes a good part of the time of a suite that writes many small files
    (every atomic write, the registry and the lock call it; project 06's speed unit). The session runs without it; a test that is about the flush replaces
    ``os.fsync`` with its own spy, which wins over this one."""
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(os, "fsync", lambda descriptor: None)
        yield


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Skip, instead of failing, the tests whose external requirement is missing (they are not selected by default either)."""
    needs = {
        "real_data": (lambda: not REAL_ZIP.exists(), "the real UCI zip is not in data/raw/ (research/s00_download.py puts it there)"),
        "docker": (lambda: shutil.which("docker") is None, "docker is not installed"),
    }
    cache: dict[str, bool] = {}
    for item in items:
        for mark, (missing, reason) in needs.items():
            if mark in item.keywords:
                cache.setdefault(mark, missing())
                if cache[mark]:
                    item.add_marker(pytest.mark.skip(reason=reason))


@pytest.fixture(scope="session")
def project_root() -> Path:
    return PROJECT_ROOT


@pytest.fixture(scope="session")
def cfg():
    """The default configuration, loaded once (it is immutable)."""
    from personaloffers.config import load_config

    return load_config(PROJECT_ROOT / "config" / "pipeline.toml")


@pytest.fixture(scope="session")
def quick_cfg():
    """The quick-mode configuration, loaded once."""
    from personaloffers.config import load_config

    return load_config(PROJECT_ROOT / "config" / "pipeline.quick.toml")


@pytest.fixture(scope="session")
def workbook(tmp_path_factory: pytest.TempPathFactory):
    """The synthetic workbook, written once per session outside the working tree: a ``FixtureWorkbook`` (its zip, sizes, hashes and the truth of its rows).
    Tests that change anything copy it (``tests.fixtures.make_workbook.make_malformed`` does)."""
    from tests.fixtures.make_workbook import make_workbook

    return make_workbook(tmp_path_factory.mktemp("workbook"))


@pytest.fixture(scope="session")
def variants(workbook, tmp_path_factory: pytest.TempPathFactory):
    """One damaged copy of the fixture for each rule of the source that a file can break (``make_malformed``), written once per session: kind -> ``Variant``."""
    from tests.fixtures import make_workbook as mw

    folder = tmp_path_factory.mktemp("variants")
    return {kind: mw.make_malformed(workbook, kind, folder) for kind in mw.MALFORMED_KINDS}


@pytest.fixture(scope="session")
def small_workbook(tmp_path_factory: pytest.TempPathFactory):
    """The same generator with twenty customers (about 450 lines, every role): for the tests that need a valid workbook and no more, since reading a
    workbook costs about 60 microseconds a line."""
    from tests.fixtures.make_workbook import make_workbook

    return make_workbook(tmp_path_factory.mktemp("small_workbook"), customers=20)


@pytest.fixture(scope="session")
def fixture_cfg(workbook, quick_cfg, tmp_path_factory: pytest.TempPathFactory):
    """The quick configuration made to accept the session's workbook, every path under a folder of the session (nothing is written in the tree)."""
    from tests.fixtures.configs import config_for

    return config_for(quick_cfg, workbook, tmp_path_factory.mktemp("fixture_cfg"))


@pytest.fixture(scope="session")
def quick_view(fixture_cfg):
    """The sealed view of the quick configuration (what the base, the control group and the recommenders receive), with made-up hashes of what was read."""
    from personaloffers.config import SealedConfig

    return SealedConfig.of(fixture_cfg, "a" * 64, "b" * 64, "c" * 64)


@pytest.fixture(scope="session")
def fixture_lines(workbook, fixture_cfg, tmp_path_factory: pytest.TempPathFactory):
    """The canonical lines of the session's workbook (copies dropped, repeats flagged, roles), read once. Shared by the session: a test that changes it copies it."""
    from personaloffers import sources, workbook as wb

    xlsx = sources.extract_workbook(fixture_cfg, tmp_path_factory.mktemp("fixture_lines"))
    return wb.canonical_lines(wb.read_workbook(xlsx, fixture_cfg), fixture_cfg)


@pytest.fixture(scope="session")
def launch_template(workbook, quick_cfg, fixture_lines, tmp_path_factory: pytest.TempPathFactory):
    """A folder with the deliveries of the fixture published and a warehouse in which ``run-1`` loaded the launch, built once per session (U11 on): a test copies it with
    ``tests.fixtures.worlds.copy_world`` and changes the copy."""
    from tests.fixtures.worlds import build_launch_template

    return build_launch_template(workbook, quick_cfg, fixture_lines, tmp_path_factory.mktemp("launch_template"))


@pytest.fixture(scope="session")
def launched(launch_template, workbook, quick_cfg, tmp_path_factory: pytest.TempPathFactory):
    """The launch run once (U11 on): a folder in which ``run-1`` loaded the launch delivery and ``run_launch`` chose, sealed and registered; ``root`` is the folder (a test copies it with
    ``tests.fixtures.worlds.copy_world``), ``result`` the ``LaunchResult`` and ``seal`` the seal that was written."""
    import types

    from personaloffers import launch, registry
    from tests.fixtures.worlds import copy_world

    world = copy_world(launch_template, workbook, quick_cfg, tmp_path_factory.mktemp("launched"))
    result = launch.run_launch(world.conn, world.view, world.run_key, models_dir=world.models_dir, seal_path=world.seal_path)
    world.conn.close()
    return types.SimpleNamespace(root=world.root, result=result, seal=registry.read_seal(world.seal_path))


@pytest.fixture(scope="session")
def replayed(launched, workbook, quick_cfg, tmp_path_factory: pytest.TempPathFactory):
    """The launch, the first round's lists, the three weekly deliveries and the close run in order, once per session (U12 on): ``root`` is the folder (a test copies it with ``copy_world``) and
    ``results`` what each step gave."""
    import types

    from tests.fixtures.worlds import copy_world, replay

    world = copy_world(launched.root, workbook, quick_cfg, tmp_path_factory.mktemp("replayed"))
    results = replay(world)
    world.conn.close()
    return types.SimpleNamespace(root=world.root, results=results)


@pytest.fixture(scope="session")
def delivered(replayed, workbook, quick_cfg, tmp_path_factory: pytest.TempPathFactory):
    """The replay with every round delivered to the world's CRM stand-in, its e-mail files and the operation of each round written (U14 on): ``root`` is the folder (a test copies it with ``copy_world``)."""
    import types

    from tests.fixtures.worlds import copy_world, deliver_all

    world = copy_world(replayed.root, workbook, quick_cfg, tmp_path_factory.mktemp("delivered"))
    done = deliver_all(world)
    world.conn.close()
    return types.SimpleNamespace(root=world.root, results=done.results)


@pytest.fixture(scope="session")
def evaluated(delivered, workbook, quick_cfg, tmp_path_factory: pytest.TempPathFactory):
    """The closing evaluation run once on the delivered replay (U14 on): ``root`` is the folder, ``outcome`` what ``reporting.evaluate`` returned and ``seal`` the seal with its test part."""
    import types
    from datetime import datetime

    from personaloffers import evaluation, registry, reporting
    from tests.fixtures.worlds import copy_world, crm_client

    world = copy_world(delivered.root, workbook, quick_cfg, tmp_path_factory.mktemp("evaluated"))
    crm = evaluation.crm_evidence(world.conn, crm_client(world), private_dir=world.cfg.paths.private_dir, batch_size=world.cfg.crm.batch_size)
    outcome = reporting.evaluate(world.conn, world.view, reporting.RunMeta("run-5", datetime(2011, 4, 23)), seal_path=world.seal_path, crm=crm)
    world.conn.close()
    return types.SimpleNamespace(root=world.root, outcome=outcome, crm=crm, seal=registry.read_seal(world.seal_path))


@pytest.fixture(scope="session")
def exported(evaluated, workbook, quick_cfg, tmp_path_factory: pytest.TempPathFactory):
    """The star model of the evaluated replay written once with the configured minimum of 10 customers a cell (U15 on): ``out`` is the published folder and ``private`` the private one; a test that changes anything
    exports its own copy (``tests.fixtures.stars.export_world``)."""
    from tests.fixtures.stars import export_world

    star = export_world(evaluated.root, workbook, quick_cfg, tmp_path_factory.mktemp("exported"))
    star.conn.close()
    return star



@pytest.fixture(scope="session")
def rendered(exported, tmp_path_factory: pytest.TempPathFactory):
    """The design of the exported star model written once (U16 on): the ``html`` text and its ``path``."""
    import types

    from personaloffers.dashboard.render import render_design
    from personaloffers.dashboard.semantic_model import MODEL

    path = render_design(MODEL, exported.out, tmp_path_factory.mktemp("design") / "powerbi-design.html", exported.run)
    return types.SimpleNamespace(path=path, html=path.read_text(encoding="utf-8"))


@pytest.fixture(scope="session")
def sited(exported, tmp_path_factory: pytest.TempPathFactory):
    """The six site files of the exported replay, written once (U17 on): ``out`` is the folder, ``site`` what ``read_site`` gives, ``view``/``run``/``seal_path`` what wrote it and ``source_counts`` the counts of the source it was given;
    a test that changes anything exports its own (``tests.fixtures.sites.export_site_of``)."""
    from tests.fixtures.sites import export_site_of

    return export_site_of(exported.world.warehouse_path, exported.world, exported.view, tmp_path_factory.mktemp("sited"))


@pytest.fixture(scope="session")
def before_close(workbook, quick_cfg, tmp_path_factory: pytest.TempPathFactory):
    """The quick replay run by the pipeline itself up to the last weekly delivery, once per session (U18 on): everything but the close. ``cfg`` is its configuration, ``runs`` what each run returned, ``plan`` the plan of
    deliveries and ``root`` the folder: a test that changes anything copies it with ``tests.fixtures.piped.copy_piped``."""
    import types

    from personaloffers import pipeline
    from tests.fixtures.configs import config_for
    from tests.fixtures.worlds import sealed_view_of

    root = tmp_path_factory.mktemp("before_close")
    cfg = config_for(quick_cfg, workbook, root)
    from personaloffers import deliveries

    plan = deliveries.delivery_plan(sealed_view_of(cfg))
    runs = pipeline.replay(cfg, until=plan[-2].delivery_id)
    return types.SimpleNamespace(cfg=cfg, runs=runs, plan=plan, root=root)


@pytest.fixture(scope="session")
def piped(before_close, workbook, quick_cfg, tmp_path_factory: pytest.TempPathFactory):
    """The whole quick replay, every delivery through every task, once per session (U18 on): the folder of ``before_close`` and the close run on top of it."""
    import types

    from personaloffers import pipeline
    from tests.fixtures.piped import copy_piped

    made = copy_piped(before_close, workbook, quick_cfg, tmp_path_factory.mktemp("piped"))
    runs = pipeline.replay(made.cfg)
    return types.SimpleNamespace(cfg=made.cfg, runs=[*before_close.runs, *runs], plan=before_close.plan, root=made.root)
