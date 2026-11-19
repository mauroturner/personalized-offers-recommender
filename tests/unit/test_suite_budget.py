"""The fast suite's time limit and the tree it must leave alone (U03, AC33, AC40; D31): a full default session over the limit fails and says by how much, which
tests were the slowest and how long ``import implicit`` took; a part of the suite never fails for its time; a session that changes a file of the project tree
fails and names it. Both are run in this process with ``pytester`` on a toy suite."""

from __future__ import annotations

import importlib
import re
import shlex
import sys
import tomllib
import types
from pathlib import Path

import pytest

from tests.fixtures import suite_budget, tree_guard

PROJECT = Path(__file__).resolve().parents[2]
TOY_PYPROJECT = """
[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-m 'not real_data and not docker'"
markers = ["real_data: x", "docker: x"]
fast_suite_limit_s = "{limit}"
fast_suite_timed_module = "{module}"
"""
TOY_CONFTEST = """
import pytest
from tests.fixtures import suite_budget, tree_guard

pytest_addoption = suite_budget.pytest_addoption


def pytest_sessionstart(session):
    suite_budget.pytest_sessionstart(session)
    tree_guard.start(session.config)


@pytest.hookimpl(trylast=True)
def pytest_sessionfinish(session, exitstatus):
    tree_guard.finish(session)
    suite_budget.pytest_sessionfinish(session, exitstatus)
"""


def toy_suite(pytester, limit: str, module: str = "implicit") -> None:
    pytester.makepyprojecttoml(TOY_PYPROJECT.format(limit=limit, module=module))
    pytester.makeconftest(TOY_CONFTEST)
    (pytester.path / "tests").mkdir(exist_ok=True)
    (pytester.path / "tests" / "test_toy.py").write_text("def test_one():\n    assert True\n\ndef test_two():\n    assert True\n", encoding="utf-8")


# --- the time limit (AC40, D31) ---------------------------------------------------------------------------------------------


def test_a_full_default_session_over_the_limit_fails_and_says_by_how_much(pytester):
    toy_suite(pytester, "0")
    result = pytester.runpytest_inprocess()
    result.assert_outcomes(passed=2)
    assert result.ret == 1
    result.stdout.re_match_lines([r"La suite rápida tardó \d+\.\d\d s, \d+\.\d\d s por encima del límite de 0 s"])
    # and it prints the slowest tests, slowest first, and what it knows about the heavy import
    result.stdout.re_match_lines([r"Las diez pruebas más lentas .*:", r"\s+\d+\.\d\d s  tests/test_toy\.py::test_(one|two)", r"\s+\d+\.\d\d s  tests/test_toy\.py::test_(one|two)"])
    assert result.stdout.str().count("s  tests/test_toy.py::") == 2
    result.stdout.fnmatch_lines(["*implicit*"])


def test_a_part_of_the_suite_or_a_session_under_the_limit_passes(pytester):
    toy_suite(pytester, "0")
    for args in (["-k", "one"], ["tests/test_toy.py"], ["-m", "not docker"], ["--deselect", "tests/test_toy.py::test_two"]):
        result = pytester.runpytest_inprocess(*args)
        assert result.ret == 0, args
        assert "La suite rápida tardó" not in result.stdout.str(), args
    toy_suite(pytester, "120")
    result = pytester.runpytest_inprocess()
    assert result.ret == 0 and "La suite rápida tardó" not in result.stdout.str()


def test_the_session_hooks_install_the_import_timer_and_remove_it_at_the_end():
    """Called by hand on a stand-in for the config: pytester restores ``sys.meta_path`` after its own sessions, so it cannot show this."""
    config = types.SimpleNamespace(stash=pytest.Stash(), getini=lambda name: "heavy_unused_module", args_source=pytest.Config.ArgsSource.ARGS,
                                   option=types.SimpleNamespace())
    session = types.SimpleNamespace(config=config)
    before = list(sys.meta_path)
    suite_budget.pytest_sessionstart(session)
    installed = [finder for finder in sys.meta_path if finder not in before]
    assert len(installed) == 1 and isinstance(installed[0], suite_budget.ImportTimer) and installed[0].name == "heavy_unused_module"
    suite_budget.pytest_sessionfinish(session, 0)
    assert sys.meta_path == before


def test_the_limit_is_compared_in_seconds_and_the_time_spent_in_setup_and_teardown_counts(pytester):
    toy_suite(pytester, "0.3")
    body = ("import time\nimport pytest\n\n@pytest.fixture\ndef slow_setup():\n    time.sleep(0.4)\n\n"
            "def test_slow_in_its_setup(slow_setup):\n    pass\n\ndef test_quick():\n    pass\n")
    (pytester.path / "tests" / "test_toy.py").write_text(body, encoding="utf-8")
    result = pytester.runpytest_inprocess()
    assert result.ret == 1
    line = next(line for line in result.stdout.lines if line.startswith("La suite rápida tardó"))
    spent, above = (float(part) for part in re.findall(r"(\d+\.\d\d) s", line)[:2])
    assert " 0.3 s" in line and spent >= 0.4 and above == pytest.approx(spent - 0.3, abs=0.011)
    first = next(line for line in result.stdout.lines if "s  tests/test_toy.py::" in line)
    assert "test_slow_in_its_setup" in first and float(first.split(" s ")[0]) >= 0.4, "the setup is part of the test's time"
    toy_suite(pytester, "30")
    assert pytester.runpytest_inprocess().ret == 0


def test_the_ten_slowest_are_ten_and_the_slowest_comes_first(pytester):
    toy_suite(pytester, "0")
    body = "import time\n" + "".join(f"def test_n{n:02d}():\n    time.sleep({0.001 * n})\n\n" for n in range(12))
    (pytester.path / "tests" / "test_toy.py").write_text(body, encoding="utf-8")
    result = pytester.runpytest_inprocess()
    lines = [line for line in result.stdout.lines if "s  tests/test_toy.py::" in line]
    assert len(lines) == 10
    seconds = [float(line.split(" s ")[0]) for line in lines]
    assert seconds == sorted(seconds, reverse=True) and "test_n11" in lines[0] and "test_n00" not in "".join(lines)


def test_a_failing_session_tells_how_long_a_module_took_to_import(pytester):
    """The module is the ini option ``fast_suite_timed_module`` (implicit in the project): here a heavy module of the toy suite."""
    toy_suite(pytester, "0", module="fake_heavy_module")
    (pytester.path / "fake_heavy_module.py").write_text("import time\ntime.sleep(0.2)\n", encoding="utf-8")
    (pytester.path / "tests" / "test_toy.py").write_text("def test_one():\n    import fake_heavy_module\n    assert fake_heavy_module\n", encoding="utf-8")
    sys.modules.pop("fake_heavy_module", None)
    result = pytester.runpytest_inprocess()
    sys.modules.pop("fake_heavy_module", None)
    assert result.ret == 1
    line = next(line for line in result.stdout.lines if line.startswith("Importar fake_heavy_module tardó"))
    assert 0.2 <= float(line.split("tardó ")[1].split(" s")[0]) < 5


def test_the_import_timer_measures_the_first_import_only_and_leaves_the_module_working(tmp_path, monkeypatch):
    (tmp_path / "heavy_probe_module").mkdir()
    (tmp_path / "heavy_probe_module" / "__init__.py").write_text("import time\ntime.sleep(0.15)\nVALUE = 41\n", encoding="utf-8")
    monkeypatch.syspath_prepend(str(tmp_path))
    timer = suite_budget.ImportTimer("heavy_probe_module")
    assert timer.sentence() == "heavy_probe_module no se importó en esta sesión"
    monkeypatch.setattr(sys, "meta_path", [timer, *sys.meta_path])
    monkeypatch.delitem(sys.modules, "heavy_probe_module", raising=False)
    heavy_probe_module = importlib.import_module("heavy_probe_module")

    assert heavy_probe_module.VALUE == 41 and 0.15 <= timer.seconds < 5
    first = timer.seconds
    assert timer.sentence() == f"Importar heavy_probe_module tardó {first:.2f} s"
    monkeypatch.delitem(sys.modules, "heavy_probe_module")
    again = importlib.import_module("heavy_probe_module")

    assert again.VALUE == 41 and timer.seconds == first, "a second import is not timed"
    monkeypatch.delitem(sys.modules, "heavy_probe_module")
    monkeypatch.setattr(sys, "meta_path", [t for t in sys.meta_path if t is not timer])
    assert suite_budget.ImportTimer("os").sentence() == "os ya estaba importado antes de la sesión: su tiempo de importar no se midió"


def test_a_last_failed_session_is_a_part_of_the_suite_and_never_failed_for_its_time(pytester):
    """``--lf`` reruns only a part of the suite: it is not the full default selection, with or without something to rerun."""
    toy_suite(pytester, "0")
    (pytester.path / "tests" / "test_toy.py").write_text("def test_one():\n    assert False\n\ndef test_two():\n    assert True\n", encoding="utf-8")
    assert pytester.runpytest_inprocess().ret == 1  # a failing test is a failure, and the first run is the full selection
    for flag in ("--lf", "--last-failed"):
        result = pytester.runpytest_inprocess(flag)
        assert "La suite rápida tardó" not in result.stdout.str(), flag
        result.assert_outcomes(failed=1)
    (pytester.path / "tests" / "test_toy.py").write_text("def test_one():\n    assert True\n\ndef test_two():\n    assert True\n", encoding="utf-8")
    result = pytester.runpytest_inprocess("--lf")
    assert result.ret == 0 and "La suite rápida tardó" not in result.stdout.str()


def test_the_guards_mark_expression_is_the_default_one_of_pyproject():
    """The guard recognises the default selection by its mark expression, so it must be the one that pyproject.toml passes to every session; if they drifted
    apart, no session would ever be failed for its time."""
    pyproject = tomllib.loads((PROJECT / "pyproject.toml").read_text(encoding="utf-8"))
    tokens = shlex.split(pyproject["tool"]["pytest"]["ini_options"]["addopts"])
    assert tokens.count("-m") == 1 and tokens[tokens.index("-m") + 1] == suite_budget.DEFAULT_MARKEXPR == "not real_data and not docker"


def test_the_project_limit_is_180_seconds_the_working_budget_120_and_the_ten_slowest_are_reported(pytestconfig):
    assert suite_budget.FAST_SUITE_LIMIT_S == 180.0 and float(pytestconfig.getini("fast_suite_limit_s")) == 180.0 and suite_budget.WORKING_BUDGET_S == 120.0
    assert pytestconfig.getini("fast_suite_timed_module") == "implicit"
    addopts = shlex.split(tomllib.loads((PROJECT / "pyproject.toml").read_text(encoding="utf-8"))["tool"]["pytest"]["ini_options"]["addopts"])
    assert "--durations=10" in addopts, "the ten slowest tests of every session are printed for the record (plan, section 24.1)"


# --- the tree the session leaves alone (AC33; project 07's c135752) -----------------------------------------------------------


def test_the_session_leaves_every_tracked_file_unchanged(pytestconfig, pytester):
    # the guard on the real project, at this point of the session: what git lists as tracked or new-and-not-ignored is what the session started with
    before = pytestconfig.stash[tree_guard.SNAPSHOT]
    assert len(before) > 10 and "pyproject.toml" in before and "src/personaloffers/config.py" in before
    assert tree_guard.differences(before, tree_guard.snapshot(PROJECT)) == []
    # and the guard itself, on a toy tree: a file written, one created and one removed fail the session and are named; the ignored state does not
    toy_suite(pytester, "120")
    (pytester.path / "kept.txt").write_text("kept", encoding="utf-8")
    (pytester.path / "gone.txt").write_text("gone", encoding="utf-8")
    body = ("from pathlib import Path\n\ndef test_writes_in_the_tree():\n    root = Path(__file__).resolve().parents[1]\n"
            "    (root / 'kept.txt').write_text('changed')\n    (root / 'new.txt').write_text('new')\n    (root / 'gone.txt').unlink()\n"
            "    (root / 'data').mkdir(exist_ok=True)\n    (root / 'data' / 'state.bin').write_bytes(b'x')\n")
    (pytester.path / "tests" / "test_toy.py").write_text(body, encoding="utf-8")
    result = pytester.runpytest_inprocess()
    assert result.ret == 1
    result.stdout.fnmatch_lines(["*La sesión cambió archivos del árbol del proyecto*"])
    reported = [line.strip() for line in result.stdout.lines if line.strip().startswith(("changed ", "created ", "removed "))]
    assert reported == ["changed kept.txt", "removed gone.txt", "created new.txt"]
    # a session that only reads and writes the ignored state passes
    (pytester.path / "tests" / "test_toy.py").write_text(
        "from pathlib import Path\n\ndef test_writes_the_state():\n    state = Path(__file__).resolve().parents[1] / 'data'\n    state.mkdir(exist_ok=True)\n"
        "    (state / 'state.bin').write_bytes(b'y')\n", encoding="utf-8")
    assert pytester.runpytest_inprocess().ret == 0


def test_the_snapshot_is_taken_by_content_not_by_time_and_follows_git_when_there_is_a_repository(tmp_path):
    (tmp_path / "a.txt").write_text("a", encoding="utf-8")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "b.txt").write_text("b", encoding="utf-8")
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "ignored.txt").write_text("i", encoding="utf-8")
    first = tree_guard.snapshot(tmp_path)
    assert sorted(first) == ["a.txt", "sub/b.txt"], "the walk skips the ignored state (data/) when there is no repository"
    (tmp_path / "a.txt").write_text("a", encoding="utf-8")                    # the same content written again: no difference
    assert tree_guard.differences(first, tree_guard.snapshot(tmp_path)) == []
    (tmp_path / "a.txt").write_text("A", encoding="utf-8")
    (tmp_path / "sub" / "c.txt").write_text("c", encoding="utf-8")
    assert tree_guard.differences(first, tree_guard.snapshot(tmp_path)) == ["changed a.txt", "created sub/c.txt"]
    # the project is in a repository: the files it lists are git's (tracked, or new and not ignored), never the environment or the data
    names = tree_guard.snapshot(PROJECT)
    assert not [name for name in names if name.startswith((".venv/", "data/", "outputs/private/")) or "__pycache__" in name]


def test_the_projects_conftest_wires_the_time_limit_and_the_tree_guard_into_every_session(pytester):
    """The conftest itself, copied into a toy folder: the limit of 0 s and a test that writes a file of the tree fail the session, both said."""
    pytester.makepyprojecttoml(TOY_PYPROJECT.format(limit="0", module="implicit"))
    pytester.makeconftest((PROJECT / "tests" / "conftest.py").read_text(encoding="utf-8"))
    (pytester.path / "tests").mkdir()
    (pytester.path / "tests" / "test_toy.py").write_text(
        "from pathlib import Path\n\ndef test_writes_in_the_tree():\n    (Path(__file__).resolve().parents[1] / 'written.txt').write_text('x')\n", encoding="utf-8")
    result = pytester.runpytest_inprocess()
    assert result.ret == 1
    result.stdout.fnmatch_lines(["*La sesión cambió archivos del árbol del proyecto*", "*created written.txt*", "*La suite rápida tardó*"])
