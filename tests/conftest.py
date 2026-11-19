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
