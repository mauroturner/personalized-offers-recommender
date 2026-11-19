"""The fast suite's time limit (plan, section 24.1; decision D31): a full default session that takes longer than the limit fails and says by how much,
which ten tests were the slowest and how long ``import implicit`` took.

``tests/conftest.py`` calls the three hooks, so they run in every session. A session is the full default selection when it was started without test paths
(pytest took the ``testpaths`` of pyproject.toml), without ``-k``, ``--deselect`` or ``--lf``, and with the default mark expression; any other selection is a
part of the suite and is never failed for its time. The limit is the ini option ``fast_suite_limit_s`` (180 s by default, the value the owner set for project
06), so a toy suite can set it to 0. The module whose import time is told is the ini option ``fast_suite_timed_module`` (implicit by default, the heaviest
import of the package): its import is timed by a finder that wraps the loader's ``exec_module``, so the figure is the first import of the session, whoever makes
it. ``--durations=10`` in pyproject.toml prints the ten slowest of every session for the record; the failure message repeats them with the figure.
"""

from __future__ import annotations

import importlib.abc
import importlib.machinery
import sys
import time

import pytest

FAST_SUITE_LIMIT_S = 180.0
WORKING_BUDGET_S = 120.0   # what the units add up to before the next one must be a speed unit (plan, section 24.1)
TIMED_MODULE = "implicit"
DEFAULT_MARKEXPR = "not real_data and not docker"
_START = pytest.StashKey[float]()
_TIMER = pytest.StashKey["ImportTimer"]()


class ImportTimer(importlib.abc.MetaPathFinder):
    """Times the first import of one top-level module: the execution of its ``__init__`` (everything it imports included)."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.seconds: float | None = None
        self.was_imported = name in sys.modules
        self._inside = False

    def find_spec(self, fullname, path, target=None):
        if fullname != self.name or self._inside or self.seconds is not None or self.was_imported:
            return None
        self._inside = True
        try:
            spec = importlib.machinery.PathFinder.find_spec(fullname, path)
        finally:
            self._inside = False
        if spec is None or spec.loader is None or not hasattr(spec.loader, "exec_module"):
            return None
        original = spec.loader.exec_module

        def timed(module):
            start = time.perf_counter()
            try:
                original(module)
            finally:
                self.seconds = time.perf_counter() - start

        spec.loader.exec_module = timed
        return spec

    def sentence(self) -> str:
        if self.was_imported:
            return f"{self.name} ya estaba importado antes de la sesión: su tiempo de importar no se midió"
        if self.seconds is None:
            return f"{self.name} no se importó en esta sesión"
        return f"Importar {self.name} tardó {self.seconds:.2f} s"


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addini("fast_suite_limit_s", "time limit of a full default session, in seconds (D31)", default=str(FAST_SUITE_LIMIT_S))
    parser.addini("fast_suite_timed_module", "the module whose import time a failing session tells", default=TIMED_MODULE)


def pytest_sessionstart(session: pytest.Session) -> None:
    config = session.config
    config.stash[_START] = time.perf_counter()
    timer = ImportTimer(config.getini("fast_suite_timed_module"))
    sys.meta_path.insert(0, timer)
    config.stash[_TIMER] = timer


def is_full_default_selection(config: pytest.Config) -> bool:
    """Whether the session runs the whole default suite: no test paths, no -k, no --deselect, no --lf and the default marks."""
    option = config.option
    return (
        config.args_source is not pytest.Config.ArgsSource.ARGS
        and not getattr(option, "keyword", "")
        and not getattr(option, "deselect", None)
        and not getattr(option, "lf", False)
        and getattr(option, "markexpr", "") == DEFAULT_MARKEXPR
    )


def slowest(stats: dict[str, list], count: int = 10) -> list[tuple[float, str]]:
    """The `count` tests that took longest: setup, call and teardown of each added up, slowest first."""
    spent: dict[str, float] = {}
    for reports in stats.values():
        for report in reports:
            if hasattr(report, "when") and hasattr(report, "duration"):
                spent[report.nodeid] = spent.get(report.nodeid, 0.0) + report.duration
    return sorted(((seconds, nodeid) for nodeid, seconds in spent.items()), reverse=True)[:count]


@pytest.hookimpl(trylast=True)
def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    config = session.config
    timer = config.stash.get(_TIMER, None)
    if timer is not None and timer in sys.meta_path:
        sys.meta_path.remove(timer)
    if _START not in config.stash or not is_full_default_selection(config):
        return
    elapsed = time.perf_counter() - config.stash[_START]
    limit = float(config.getini("fast_suite_limit_s"))
    if elapsed <= limit:
        return
    session.exitstatus = pytest.ExitCode.TESTS_FAILED
    reporter = config.pluginmanager.get_plugin("terminalreporter")
    lines = [f"La suite rápida tardó {elapsed:.2f} s, {elapsed - limit:.2f} s por encima del límite de {limit:g} s"]
    if reporter is not None:
        lines.append("Las diez pruebas más lentas (preparación, ejecución y cierre sumados):")
        lines += [f"  {seconds:7.2f} s  {nodeid}" for seconds, nodeid in slowest(reporter.stats)]
    if timer is not None:
        lines.append(timer.sentence())
    if reporter is not None:
        for number, line in enumerate(lines):
            reporter.write_line(line, red=number == 0, bold=number == 0)
    else:  # pragma: no cover - pytest always has its terminal reporter unless -p no:terminal
        print("\n".join(lines))
