"""The environment and its dependencies (U01, item 5): every third-party module the code imports is a pinned direct requirement in the
file that corresponds to it (AC38, project 03 B6), every pin is exact (D35, RNF01), `pip check` is judged by its exit code (project 05's
R3-pip-check-stdout-substring) and the generated state stays out of Git."""

from __future__ import annotations

import ast
import functools
import importlib.metadata
import re
import subprocess
import sys
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

import pytest

PROJECT = Path(__file__).resolve().parents[2]
# Top-level names that belong to this project, not to a distribution
LOCAL_TOP_LEVEL = {"personaloffers", "tests"}
# The line that separates the direct pins (above) from the transitive ones (below) in every requirements file
TRANSITIVE_MARKER = "# transitive"
PIN = re.compile(r"([A-Za-z0-9][A-Za-z0-9_.-]*)==([A-Za-z0-9_.+!-]+)")
REQUIREMENT_NAME = re.compile(r"\s*([A-Za-z0-9][A-Za-z0-9._-]*)")
# the runtime flow and services <- the development tools; the second file includes the first
REQUIREMENT_FILES = ("requirements.txt", "requirements-dev.txt")
# The direct pins the landing declares itself (S5): everything else a direct pin needs has a row in LANDING-EXPANSION.md
LANDING_DECLARED = {"pandas", "fastapi"}
# Direct pins with no row in LANDING-EXPANSION.md yet: the rows that add project 08 (implicit, mlxtend) and the 08 in the projects of the existing ones are U22's
# (plan section 27, decision D34), written with the other documents. U22 writes them and empties this set; until then the test says exactly which rows are
# owed, and fails if one is not.
PENDING_LANDING_ROWS = frozenset({"implicit", "mlxtend"})

def normalize(name: str) -> str:
    """PEP 503 normalization: ``scikit_learn``, ``Scikit-Learn`` and ``scikit-learn`` are one distribution."""
    return re.sub(r"[-_.]+", "-", name).lower()


@dataclass
class Pins:
    direct: dict[str, str] = field(default_factory=dict)
    transitive: dict[str, str] = field(default_factory=dict)
    includes: list[str] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)

    @property
    def all(self) -> dict[str, str]:
        return {**self.direct, **self.transitive}


def read_pins(path: Path) -> Pins:
    pins = Pins()
    section = pins.direct
    for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if raw.strip() == TRANSITIVE_MARKER:
            section = pins.transitive
            continue
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        if line.startswith("-r "):
            pins.includes.append(line[3:].strip())
            continue
        match = PIN.fullmatch(line)
        if not match:
            pins.problems.append(f"{path.name}:{number}: {line!r} is not an exact == pin")
            continue
        name = normalize(match.group(1))
        if name in pins.all:
            pins.problems.append(f"{path.name}:{number}: {name} is pinned twice")
            continue
        section[name] = match.group(2)
    return pins


def all_pins(project: Path) -> dict[str, Pins]:
    return {name: read_pins(project / name) for name in REQUIREMENT_FILES}


def with_includes(pins: dict[str, Pins], name: str) -> Pins:
    """The pins a file installs: its own and, recursively, those of the files it includes."""
    merged = Pins(direct=dict(pins[name].direct), transitive=dict(pins[name].transitive), includes=list(pins[name].includes))
    for included in pins[name].includes:
        inner = with_includes(pins, included)
        merged.direct = {**inner.direct, **merged.direct}
        merged.transitive = {**inner.transitive, **merged.transitive}
    return merged


def third_party_imports(root: Path, project: Path, local: frozenset[str]) -> dict[str, set[str]]:
    """Top-level module -> the files (relative to the project) that import it, for every absolute import of a module outside the
    standard library and outside this project."""
    found: dict[str, set[str]] = {}
    for path in sorted(root.rglob("*.py")):
        stat = path.stat()
        for top in _imported_tops(str(path), stat.st_mtime_ns, stat.st_size, local):
            found.setdefault(top, set()).add(path.relative_to(project).as_posix())
    return found


@functools.lru_cache(maxsize=4096)
def _imported_tops(path: str, mtime_ns: int, size: int, local: frozenset[str]) -> frozenset[str]:
    """The third-party top-level modules one file imports, parsed once per version of the file (its time and size are part of the key):
    the project's files are scanned by several tests."""
    del mtime_ns, size
    tree = ast.parse(Path(path).read_text(encoding="utf-8"), filename=path)
    tops = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names = [node.module]
        else:
            continue
        for name in names:
            top = name.split(".", 1)[0]
            if top not in sys.stdlib_module_names and top != "__future__" and top not in LOCAL_TOP_LEVEL and top not in local:
                tops.add(top)
    return frozenset(tops)


@functools.cache
def installed_providers() -> dict[str, list[str]]:
    """``importlib.metadata.packages_distributions()``, read once per session: it scans every installed distribution, and what is
    installed does not change while the suite runs."""
    return importlib.metadata.packages_distributions()


def distribution_of(module: str) -> str:
    """The distribution that provides an importable top-level module (``sklearn`` -> ``scikit-learn``); the module's own name when
    nothing installed provides it, so a missing package is still reported by a recognisable name."""
    providers = installed_providers().get(module)
    return normalize(providers[0] if providers else module)


def dependency_problems(project: Path) -> list[str]:
    """Every third-party import of ``src/`` must be a direct pin of requirements.txt (the service image installs that one); every one of ``tests/`` and
    ``research/`` a direct pin of either file (research/ has requirements-research.txt too, which a test below ties to them). A module pinned only in a
    transitive section is told so, and one that only requirements-dev.txt pins directly is a development tool that runtime code cannot import."""
    files = all_pins(project)
    runtime, dev = (files[name] for name in REQUIREMENT_FILES)
    transitive = runtime.transitive | dev.transitive
    problems: list[str] = []
    for folder in ("src", "research", "tests"):
        root = project / folder
        if not root.is_dir():
            continue
        local = frozenset(path.stem for path in root.rglob("*.py")) if folder == "research" else frozenset()
        allowed = runtime.direct if folder == "src" else runtime.direct | dev.direct
        for module, found_in in sorted(third_party_imports(root, project, local).items()):
            dist = distribution_of(module)
            if dist in allowed:
                continue
            if dist in dev.direct:
                kind = "is a development-only dependency (a direct pin of requirements-dev.txt), which runtime code cannot import"
            elif dist in transitive:
                kind = "is pinned only as a transitive dependency"
            else:
                kind = "is not pinned as a direct requirement"
            problems.append(f"{module} ({dist}) is imported by {', '.join(sorted(found_in))} but {kind}")
    return problems


def never_applies(marker: str) -> bool:
    """A requirement only an extra asks for, or only a Python older than the project's 3.11 (pyproject's requires-python): ``< "3.N"``
    for N up to 11, ``<= "3.N"`` and ``== "3.N"`` for N up to 10 and ``== "2.N"``, in single or double quotes; or only the Pyodide platform
    (``sys_platform == 'emscripten'``). The last two kinds count only in a marker with no ``or``: with one, the other branch may apply."""
    if "extra" in marker:
        return True
    if " or " not in marker:
        if re.search(r"""sys_platform\s*==\s*(['"])emscripten\1""", marker):
            return True
        exact = re.search(r"""python_version\s*==\s*(['"])(\d+)\.(\d+)\1""", marker)
        if exact and (int(exact.group(2)), int(exact.group(3))) < (3, 11):
            return True
    older = re.search(r"""python_version\s*(<=|<)\s*(['"])3\.(\d+)\2""", marker)
    if older is None:
        return False
    minor = int(older.group(3))
    return minor <= 11 if older.group(1) == "<" else minor <= 10


def required_names(dist: str) -> set[str]:
    """The distributions a pinned distribution requires on some supported platform and Python."""
    names = set()
    for requirement in importlib.metadata.requires(dist) or []:
        if ";" in requirement and never_applies(requirement.split(";", 1)[1]):
            continue
        match = REQUIREMENT_NAME.match(requirement)
        if match:
            names.add(normalize(match.group(1)))
    return names


def pip_check_passed(command: list[str]) -> bool:
    """`pip check` is judged by its exit code and nothing it prints (project 05's R3-pip-check-stdout-substring): a pip release that
    words its report differently must not break the check, and a failing one that happens to print the success words must not pass."""
    return subprocess.run(command, capture_output=True, text=True, timeout=120).returncode == 0


def probe_project(tmp_path: Path, files: dict[str, str], drop: tuple[str, ...] = ()) -> Path:
    """A copy of the project's requirements files (without the pins whose names start with one of ``drop``) next to the given source
    files (path relative to the probe -> text)."""
    probe = tmp_path / "probe"
    probe.mkdir()
    for name in REQUIREMENT_FILES:
        lines = (PROJECT / name).read_text(encoding="utf-8").splitlines()
        kept = [line for line in lines if not line.lower().startswith(tuple(f"{pin}==" for pin in drop))]
        (probe / name).write_text("\n".join(kept) + "\n", encoding="utf-8")
    for relative, text in files.items():
        (probe / relative).parent.mkdir(parents=True, exist_ok=True)
        (probe / relative).write_text(text, encoding="utf-8")
    return probe


def require_file(path: Path, needed_by: str) -> Path:
    """`path`, which a rule of this file needs and which is not part of the code under test (the table of the landing's technologies beside the project, the research environment's
    pins, the research scripts): a clear failure that names the file and the rule when it is not there, instead of a ``FileNotFoundError`` that says nothing about either."""
    shown = path.relative_to(PROJECT.parent).as_posix() if PROJECT.parent in path.parents else path.as_posix()
    assert path.exists(), f"{needed_by} needs {shown}, which is not there: restore it (it belongs to the portfolio or to the project's research, not to the code under test)"
    return path


# --- AC38: the imports and the pins ------------------------------------------------------------------------------------


def test_every_direct_import_is_a_pinned_requirement_and_documented(tmp_path):
    # the check itself, on a module that imports pyarrow with its pin removed, and then with pyarrow filed as a transitive pin
    source = {"src/personaloffers/parquet_probe.py": "import numpy as np\nimport pyarrow.parquet as pq\nimport scipy.sparse\n"}
    probe = probe_project(tmp_path, source, drop=("pyarrow",))
    assert dependency_problems(probe) == [
        "pyarrow (pyarrow) is imported by src/personaloffers/parquet_probe.py but is not pinned as a direct requirement"
    ]
    requirements = probe / "requirements.txt"
    requirements.write_text(requirements.read_text(encoding="utf-8") + "pyarrow==26.0.0\n", encoding="utf-8")
    assert dependency_problems(probe) == [
        "pyarrow (pyarrow) is imported by src/personaloffers/parquet_probe.py but is pinned only as a transitive dependency"
    ]
    # and on the project as it is: src/, research/ and tests/ import nothing that is not a direct pin of its file
    for folder in ("src", "research", "tests"):
        require_file(PROJECT / folder, "test_every_direct_import_is_a_pinned_requirement_and_documented (AC38: every folder it checks)")
    assert dependency_problems(PROJECT) == []
    # documented: a direct pin the landing does not declare has a row of the table in LANDING-EXPANSION.md; SQLite is the standard library
    # and the table has its row too. The rows that add project 08 are U22's (PENDING_LANDING_ROWS says which are owed)
    landing = require_file(PROJECT.parent / "LANDING-EXPANSION.md", "test_every_direct_import_is_a_pinned_requirement_and_documented (AC38: every direct pin is documented)")
    table = landing.read_text(encoding="utf-8").splitlines()
    names = [line.split("|")[1].strip().lower() for line in table if line.startswith("| ")]
    pins = all_pins(PROJECT)
    direct = pins["requirements.txt"].direct | pins["requirements-dev.txt"].direct
    undocumented = {name for name in direct if name not in LANDING_DECLARED and not any(name in row for row in names)}
    assert undocumented == PENDING_LANDING_ROWS, (
        f"owed rows differ from PENDING_LANDING_ROWS: undocumented now {sorted(undocumented - PENDING_LANDING_ROWS)}, "
        f"documented already {sorted(PENDING_LANDING_ROWS - undocumented)} (remove them from the set)"
    )


def test_a_development_only_direct_dependency_imported_by_src_is_reported_as_such(tmp_path):
    """pytest is a direct pin of requirements-dev.txt: runtime code that imports it is not wrongly told it is pinned as transitive; the tests and research/
    may import it."""
    probe = probe_project(tmp_path, {"src/personaloffers/uses_pytest.py": "import pytest\nimport numpy\n", "tests/test_uses.py": "import pytest\nimport mlxtend\n"})
    assert dependency_problems(probe) == [
        "pytest (pytest) is imported by src/personaloffers/uses_pytest.py but is a development-only dependency (a direct pin of "
        "requirements-dev.txt), which runtime code cannot import"
    ]


def test_the_scope_of_each_folder_and_the_names_of_the_unknown_modules(tmp_path, monkeypatch):
    """The tests and research/ may import any direct pin and are told the rest by name; research/ modules that import each other are local, not
    dependencies (the fallback of distribution_of for a module no installed distribution provides)."""
    probe = probe_project(tmp_path, {
        "tests/test_probe.py": "import pytest\nimport no_such_module_xyz\nimport colorama\nimport personaloffers\nimport mlxtend\n",
        "research/s99_probe.py": "import numpy\nimport common\nimport pytest\nimport colorama\n",
        "research/common.py": "import pandas\n",
        "src/personaloffers/probe.py": "import colorama\n",
    })
    assert distribution_of("no_such_module_xyz") == "no-such-module-xyz" and distribution_of("sklearn") == "scikit-learn"
    monkeypatch.setattr(sys.modules[__name__], "distribution_of", normalize)
    assert dependency_problems(probe) == [
        "colorama (colorama) is imported by src/personaloffers/probe.py but is pinned only as a transitive dependency",
        "colorama (colorama) is imported by research/s99_probe.py but is pinned only as a transitive dependency",
        "colorama (colorama) is imported by tests/test_probe.py but is pinned only as a transitive dependency",
        "no_such_module_xyz (no-such-module-xyz) is imported by tests/test_probe.py but is not pinned as a direct requirement",
    ]


@pytest.mark.parametrize(("marker", "never"), [
    ('python_version < "3.8"', True), ("python_version < '3.8'", True), ('python_version < "3.11"', True), ('python_version < "3.12"', False),
    ('python_version <= "3.10"', True), ("python_version <= '3.10'", True), ('python_version <= "3.11"', False), ("python_version<='3.12'", False),
    ('extra == "test"', True), ('platform_system == "Windows"', False),
    ('python_version=="2.7"', True), ("python_version == '3.10'", True), ('python_version == "3.11"', False),
    ("sys_platform == 'emscripten' and python_version >= '3.12'", True), ("sys_platform != 'emscripten'", False),
    ('sys_platform == "win32"', False), ('sys_platform == "emscripten" or python_version >= "3.12"', False),
])
def test_a_marker_never_applies_only_to_extras_old_pythons_and_pyodide(marker, never):
    """Single or double quotes and a strict or inclusive bound: ``<= "3.11"`` still applies to 3.11."""
    assert never_applies(marker) is never


def test_a_range_a_bare_name_and_a_repeated_pin_are_reported_and_the_marker_splits_direct_from_transitive(tmp_path):
    """The reader of the requirements files: what is not an exact pin and what is pinned twice are problems, the marker line splits the sections
    and ``-r`` lines are includes, not pins."""
    path = tmp_path / "requirements.txt"
    lines = ["-r requirements-other.txt", "numpy==2.4.6  # a comment", "pandas>=2", "scipy", "numpy==2.4.5", "# transitive", "Six_Pkg==1.0"]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    pins = read_pins(path)
    assert pins.direct == {"numpy": "2.4.6"} and pins.transitive == {"six-pkg": "1.0"} and pins.includes == ["requirements-other.txt"]
    assert pins.problems == [
        "requirements.txt:3: 'pandas>=2' is not an exact == pin",
        "requirements.txt:4: 'scipy' is not an exact == pin",
        "requirements.txt:5: numpy is pinned twice",
    ]


# --- D35, RNF01: the pins ------------------------------------------------------------------------------------------------


def test_every_pin_is_exact_and_the_development_file_includes_the_runtime_one():
    pins = all_pins(PROJECT)
    runtime, dev = (pins[name] for name in REQUIREMENT_FILES)
    assert runtime.problems + dev.problems == []
    assert runtime.includes == [] and dev.includes == ["requirements.txt"]
    assert not set(runtime.all) & set(dev.all), "the development file pins again what requirements.txt already pins"


def test_the_direct_pins_are_the_ones_decision_d35_names():
    """D35: the research environment's versions for the data and the models (numpy 2.4.6 and scipy 1.17.1 are the newest for Python 3.11), project 05's
    and 07's for the services (fastapi, uvicorn, httpx, pytest)."""
    pins = all_pins(PROJECT)
    assert pins["requirements.txt"].direct == {
        "numpy": "2.4.6", "pandas": "3.1.0", "pyarrow": "26.0.0", "openpyxl": "3.1.5", "scipy": "1.17.1", "implicit": "0.7.3",
        "matplotlib": "3.11.1", "fastapi": "0.162.0", "uvicorn": "0.54.0", "httpx": "0.28.1",
    }
    assert pins["requirements-dev.txt"].direct == {"pytest": "9.2.0", "mlxtend": "0.25.0"}


def test_the_research_pins_are_the_runtime_and_development_pins_of_the_same_packages():
    """The research environment (docs/research.md) and the build one are the same versions: nothing new came in with the build."""
    research = read_pins(require_file(PROJECT / "requirements-research.txt", "test_the_research_pins_are_the_runtime_and_development_pins_of_the_same_packages (RNF01)")).all
    built = with_includes(all_pins(PROJECT), "requirements-dev.txt").all
    assert research and {name: (version, built.get(name)) for name, version in research.items() if built.get(name) != version} == {}


def test_a_missing_file_outside_the_code_fails_naming_the_file_and_the_rule(tmp_path, monkeypatch):
    """The three things the checks read that are not the project's own code (the landing's table, the research pins and the research scripts) fail with a message that says which file
    and which rule, not with an exception about a path. The same test functions run on a copy of the project that lacks them, one at a time."""
    (tmp_path / "first").mkdir()
    (tmp_path / "second").mkdir()
    portfolio = tmp_path / "portfolio"
    copy = portfolio / "08-copy"
    for name in REQUIREMENT_FILES:
        (copy / name).parent.mkdir(parents=True, exist_ok=True)
        (copy / name).write_text((PROJECT / name).read_text(encoding="utf-8"), encoding="utf-8")
    for folder in ("src", "tests"):
        (copy / folder).mkdir()
    monkeypatch.setattr(sys.modules[__name__], "PROJECT", copy)
    with pytest.raises(AssertionError, match=r"test_every_direct_import_is_a_pinned_requirement_and_documented.*needs 08-copy/research"):
        test_every_direct_import_is_a_pinned_requirement_and_documented(tmp_path / "first")
    (copy / "research").mkdir()
    with pytest.raises(AssertionError, match=r"test_every_direct_import_is_a_pinned_requirement_and_documented.*needs LANDING-EXPANSION\.md"):
        test_every_direct_import_is_a_pinned_requirement_and_documented(tmp_path / "second")
    with pytest.raises(AssertionError, match=r"test_the_research_pins_are_the_runtime_and_development_pins_of_the_same_packages.*needs 08-copy/requirements-research\.txt"):
        test_the_research_pins_are_the_runtime_and_development_pins_of_the_same_packages()
    # and each of them passes when the files are there
    (portfolio / "LANDING-EXPANSION.md").write_text("| pandas |\n", encoding="utf-8")
    assert require_file(portfolio / "LANDING-EXPANSION.md", "any rule") == portfolio / "LANDING-EXPANSION.md"


def test_every_transitive_pin_is_required_by_another_pin():
    pins = all_pins(PROJECT)
    pinned = set().union(*(set(file.all) for file in pins.values()))
    required = set().union(*(required_names(name) for name in pinned))
    transitive = set().union(*(set(file.transitive) for file in pins.values()))
    orphans = sorted(transitive - required)
    assert orphans == [], f"pinned as transitive but required by no other pin: {orphans}"


def test_each_requirements_file_pins_everything_its_pins_require():
    """requirements.txt alone installs a complete runtime; the development file adds what its own pins need on top of it."""
    pins = all_pins(PROJECT)
    for name in REQUIREMENT_FILES:
        available = set(with_includes(pins, name).all)
        missing = {dist: sorted(required_names(dist) - available) for dist in pins[name].all}
        assert {dist: needs for dist, needs in missing.items() if needs} == {}, name


def test_no_dependency_outside_the_declared_set_is_pinned():
    """D32 (no pytest-xdist), D09 (no RAG, no language model, no vector index), the landing's TensorFlow (nothing here is a neural network) and the earlier
    projects' exclusions."""
    pinned = set().union(*(set(file.all) for file in all_pins(PROJECT).values()))
    assert not ({
        "pytest-xdist", "execnet", "psutil", "requests", "statsmodels", "lightgbm", "xgboost", "shap", "numba", "torch", "tensorflow", "transformers",
        "sentence-transformers", "faiss-cpu", "lifetimes", "sqlalchemy", "pydantic-settings", "lenskit", "surprise", "pyarrow-hotfix",
    } & pinned)


def test_installed_versions_match_the_pins():
    pinned = set()
    wrong = {}
    for file in all_pins(PROJECT).values():
        pinned |= set(file.all.items())
    for name, version in sorted(pinned):
        try:
            installed = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            installed = None
        if installed != version:
            wrong[name] = (version, installed)
    assert not wrong, f"installed versions differ from the pins (pinned, installed): {wrong}"


def test_pip_check_is_judged_by_its_exit_code():
    # the judge, on commands whose words and exit code disagree
    assert pip_check_passed([sys.executable, "-c", "print('No broken requirements found.')"]) is True
    assert pip_check_passed([sys.executable, "-c", "print('No broken requirements found.'); raise SystemExit(1)"]) is False
    assert pip_check_passed([sys.executable, "-c", "print('pip words that changed in a later release')"]) is True
    # and the live environment: the exit code is the contract; the words pip prints are not
    assert pip_check_passed([sys.executable, "-m", "pip", "check", "--disable-pip-version-check"]) is True


# --- the project files ----------------------------------------------------------------------------------------------------


def test_pyproject_declares_the_package_the_pythons_and_the_marks():
    document = tomllib.loads((PROJECT / "pyproject.toml").read_text(encoding="utf-8"))
    assert document["project"]["name"] == "personaloffers"
    assert document["project"]["requires-python"] == ">=3.11,<3.14"
    options = document["tool"]["pytest"]["ini_options"]
    assert "-m 'not real_data and not docker'" in options["addopts"]
    assert "--strict-markers" in options["addopts"]
    assert {mark.split(":", 1)[0] for mark in options["markers"]} == {"real_data", "docker", "slow"}
    assert options["pythonpath"] == ["src", "."]
    assert options["testpaths"] == ["tests"]


@pytest.mark.parametrize("entry", [
    "data/", "outputs/private/", "airflow/.env", "airflow/logs/", "airflow/config/", "airflow/plugins/", "reports/validation/history/",
    ".venv/", "__pycache__/", ".pytest_cache/",
])
def test_gitignore_keeps_generated_state_and_the_environment_out_of_git(entry):
    assert entry in (PROJECT / ".gitignore").read_text(encoding="utf-8").splitlines()


def test_the_seal_the_reports_the_research_and_the_published_outputs_are_not_ignored():
    """The seal, the reports, the Parquet of outputs/powerbi/, the site files, the dashboard and the research scripts with their outputs
    are versioned; only the generated state of the pipeline and the per-customer files are not."""
    ignored = set((PROJECT / ".gitignore").read_text(encoding="utf-8").splitlines())
    assert not ({"reports/", "outputs/", "outputs/powerbi/", "outputs/site/", "reports/model_seal.json", "dashboard/", "docs/", "research/",
                 "research/plan/", "airflow/", "config/", "sql/", "src/", "tests/"} & ignored)


def test_the_docker_build_context_holds_only_the_requirements_the_sources_the_sql_and_the_config():
    lines = [line for line in (PROJECT / ".dockerignore").read_text(encoding="utf-8").splitlines() if line and not line.startswith("#")]
    assert lines == ["*", "!requirements*.txt", "!src/", "!sql/", "!config/", "**/__pycache__/", "**/*.pyc"]


def test_the_package_imports_from_the_source_folder():
    import personaloffers

    assert Path(personaloffers.__file__).resolve().parent == PROJECT / "src" / "personaloffers"
    assert personaloffers.__version__ == "0.1.0"
