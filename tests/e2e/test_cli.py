"""The command line (U19; RF24; AC30, AC32, AC36; plan section 22): its exit codes, an incompatible combination that exits with 2 before writing, every documented option changing the result, every key of the
configuration changing something or being declared informative, and a launch whose registry write failed recovered by the command that the runbook names. The runs are the session's states, copied."""

from __future__ import annotations

import dataclasses
import os
import subprocess
import sys
import threading
import zipfile
from contextlib import contextmanager
from datetime import date, timedelta
from pathlib import Path
from unittest import mock

import pytest

from personaloffers import cli as cli_module
from personaloffers import pipeline, registry, warehouse
from personaloffers.config import ENV_CONFIG, ENV_HOME, FINGERPRINT_KEYS, INFORMATIVE_KEYS, UNSEALED_KEYS
from personaloffers.registry import config_fingerprint
from tests.e2e.cli_helpers import PROJECT_ROOT, cli, written
from tests.fixtures.piped import config_of, copy_piped, run_keys, write_config_file

EXPECTED = ("L2011-03-27", "W2011-04-04", "W2011-04-11", "C2011-04-18")


def runs_of(state) -> list[str]:
    return run_keys(state.cfg)


@pytest.fixture
def before(before_close, workbook, quick_cfg, tmp_path):
    return copy_piped(before_close, workbook, quick_cfg, tmp_path / "before")


@pytest.fixture
def after(piped, workbook, quick_cfg, tmp_path):
    return copy_piped(piped, workbook, quick_cfg, tmp_path / "after")


@pytest.fixture
def fresh(workbook, quick_cfg, tmp_path):
    """An empty folder with its configuration file: nothing has run."""
    import types

    from tests.fixtures.configs import config_for

    write_config_file(tmp_path / "fresh", workbook)
    return types.SimpleNamespace(cfg=config_for(quick_cfg, workbook, tmp_path / "fresh"), root=tmp_path / "fresh")


# --- the documented options: each one has its case ------------------------------------------------------------------------------


def documented_options() -> set[str]:
    """Every option the parsers document, by command (``command option``; a positional by its name), without the help of argparse."""
    parser = cli_module.build_parser(pipeline.TASK_IDS)
    found = set()
    for name, sub in next(a for a in parser._actions if a.dest == "command").choices.items():
        for action in sub._actions:
            if action.option_strings and action.option_strings != ["-h", "--help"]:
                found.add(f"{name} {max(action.option_strings, key=len)}")
            elif not action.option_strings and action.dest not in ("help",):
                found.add(f"{name} {action.dest}")
    return found


def case_config(state, tmp_path):
    """--config: the same command over the folder it points at and over the default one gives other results. The default one is an empty clean folder: once the real run has written the real site files, ``figures``
    over the project's own defaults would succeed too and would write the real figures (U22)."""
    with mock.patch.dict(os.environ, {ENV_HOME: str(tmp_path / "default"), ENV_CONFIG: str(PROJECT_ROOT / "config" / "pipeline.quick.toml")}):
        without = cli("figures")
    with_it = cli("figures", "--config", config_of(state))
    assert without.code == 2 and with_it.code == 0 and with_it.out != without.out


def case_verbose(state, tmp_path):
    quiet = cli("task", "fetch_source", "--config", config_of(state), "--run-key", "v1")
    loud = cli("task", "fetch_source", "--config", config_of(state), "--run-key", "v2", "-v")
    assert quiet.code == loud.code == 0 and "task fetch_source of run v2" in loud.err and "task fetch_source of run v1" not in quiet.err


def case_only(state, tmp_path):
    result = cli("run", "--only", "fetch_source", "deliver", "--config", config_of(state))
    assert result.code == 0 and "fetch_source" in result.out and "deliver" in result.out and "validate" not in result.out and "fit_recipe" not in result.out


def case_from(state, tmp_path):
    pipeline.run_all(state.cfg, only=["fetch_source", "deliver"], run_key="k")
    result = cli("run", "--from", "validate", "--run-key", "k", "--config", config_of(state))
    assert result.code == 0 and "validate" in result.out and "fetch_source" not in result.out and "report" in result.out


def case_run_key(state, tmp_path):
    before = len(runs_of(state))
    pipeline.run_all(state.cfg, only=["fetch_source", "deliver"], run_key="named")
    result = cli("run", "--only", "validate", "--run-key", "named", "--config", config_of(state))
    assert result.code == 0 and "named" in runs_of(state) and len(runs_of(state)) == before + 1, "the named run was continued, not a new one made"


def case_until(state, tmp_path):
    """One run up to the launch instead of the five a replay runs without it."""
    result = cli("replay", "--until", "L2011-03-27", "--config", config_of(state))
    assert result.code == 0 and "1 corrida" in result.out and "1 corridas" not in result.out and "L2011-03-27" in result.out and "W2011-04-04" not in result.out
    assert len(runs_of(state)) == 1


def case_task(state, tmp_path):
    first = cli("task", "fetch_source", "--config", config_of(state), "--run-key", "t")
    second = cli("task", "deliver", "--config", config_of(state), "--run-key", "t")
    assert first.code == second.code == 0 and first.out.startswith("fetch_source:") and "lines=" in first.out and second.out.startswith("deliver:") and "delivered=True" in second.out and "validate" not in second.out


def case_make_fixture(state, tmp_path):
    first, other = tmp_path / "a.zip", tmp_path / "c.zip"
    one, three = cli("make-fixture", str(first)), cli("make-fixture", str(other), "--seed", "1")
    assert one.code == three.code == 0 and zipfile.is_zipfile(first) and zipfile.is_zipfile(other)
    assert first.read_bytes() != other.read_bytes(), "another seed gives another file"
    assert first.read_bytes() == Path(state.cfg.source.zip_path).read_bytes(), "the default seed is the one of the tests: the same bytes as their workbook"
    assert cli("make-fixture", str(tmp_path / "d.zip"), "--seed", "-1").code == 2 and not (tmp_path / "d.zip").exists()


def case_figures(state, tmp_path):
    result = cli("figures", "--config", config_of(state))
    assert result.code == 0 and len(list(Path(state.cfg.paths.figures_dir).glob("*.png"))) == 6


def case_docs_sync(state, tmp_path):
    readme = Path(state.cfg.paths.readme)
    dictionary = readme.parent / "docs" / "data-dictionary.md"      # next to the README, where the command looks for it
    readme.write_text("# Proyecto\n<!-- results:start -->\nviejo\n<!-- results:end -->\nfin\n", encoding="utf-8")
    dictionary.parent.mkdir(parents=True, exist_ok=True)
    from personaloffers.dashboard.semantic_model import MODEL

    dictionary.write_text("# Diccionario\n" + "".join(f"<!-- table:{t.name}:start -->\nviejo\n<!-- table:{t.name}:end -->\n" for t in MODEL.tables) + "fin\n", encoding="utf-8")
    result = cli("docs-sync", "--config", config_of(state))
    text = readme.read_text(encoding="utf-8")
    assert result.code == 0 and "viejo" not in text and "C01" in text and text.endswith("fin\n") and "viejo" not in dictionary.read_text(encoding="utf-8") and "| `base` |" in dictionary.read_text(encoding="utf-8")
    assert cli("docs-sync", "--config", config_of(state)).out.splitlines()[0] == "README.md ya estaba al día"


@contextmanager
def serving(token: str | None = "t0ken"):
    """``uvicorn.run`` replaced by a spy (no socket is opened) and the token of the CRM in the environment (or, with ``token=None``, out of it)."""
    with mock.patch("uvicorn.run") as run, mock.patch.dict(os.environ):
        os.environ.pop("PERSONALOFFERS_CRM_TOKEN", None)
        if token is not None:
            os.environ["PERSONALOFFERS_CRM_TOKEN"] = token
        yield run


def case_serve(state, tmp_path):
    """``serve-crm`` hands uvicorn the application with the host and the port of the options; it listens on 127.0.0.1 only and a wrong host or port is exit 2 before anything is made."""
    config = config_of(state)
    with serving() as run:
        assert cli("serve-crm", "--config", config).code == 0 and run.call_args.kwargs["host"] == "127.0.0.1" and run.call_args.kwargs["port"] == 8001
        assert cli("serve-crm", "--config", config, "--port", "8124", "--host", "127.0.0.1").code == 0 and run.call_args.kwargs["port"] == 8124
        calls = run.call_count
        for host in ("0.0.0.0", "localhost", "::1", ""):
            refused = cli("serve-crm", "--host", host, "--config", config)
            assert refused.code == 2 and "127.0.0.1" in refused.err, host
        for port in ("0", "65536", "x"):
            assert cli("serve-crm", "--port", port, "--config", config).code == 2, port
        assert run.call_count == calls
    with serving() as run:
        assert cli("serve-crm", "--config", config).code == 0 and run.call_args.kwargs["log_level"] == "warning"
        assert cli("serve-crm", "--config", config, "-v").code == 0 and run.call_args.kwargs["log_level"] == "info"


CASES = {
    "run --run-key": case_run_key, "run --only": case_only, "run --from": case_from, "run --verbose": case_verbose, "run --config": case_config,
    "replay --until": case_until, "replay --config": case_config, "replay --verbose": case_verbose,
    "task task": case_task, "task --run-key": case_task, "task --config": case_config, "task --verbose": case_verbose,
    "serve-crm --config": case_serve, "serve-crm --host": case_serve, "serve-crm --port": case_serve, "serve-crm --verbose": case_serve,
    "make-fixture output": case_make_fixture, "make-fixture --seed": case_make_fixture, "figures --config": case_figures, "figures --verbose": case_verbose,
    "docs-sync --config": case_docs_sync, "docs-sync --verbose": case_verbose,
}
# the options that several commands share are the same option: it is shown once, by its case, where it can be seen to change a result


def test_every_option_the_parser_documents_has_its_case():
    assert documented_options() == set(CASES), sorted(documented_options() ^ set(CASES))


@pytest.mark.parametrize("case", sorted(set(CASES.values()), key=lambda f: f.__name__), ids=lambda f: f.__name__)
def test_every_documented_option_changes_the_result(case, request, tmp_path):
    """Each case runs over the copy of the folder it needs and only that one is made (a copy of a replay is 28 MB)."""
    needs = "after" if case in (case_figures, case_docs_sync) else "fresh" if case is case_until else "before"
    case(request.getfixturevalue(needs), tmp_path)


@pytest.mark.parametrize("args, says", [
    (["run", "--only", "fetch_source", "--from", "deliver"], "--only y --from no se combinan"),
    (["run", "--run-key", "x"], "necesita --only o --from"),
    (["run", "--from", "validate"], "una corrida nueva empieza por fetch_source"),
    (["run", "--only", "validate"], "una corrida nueva empieza por fetch_source"),
    (["docs-sync"], "no tiene un README"),
])
def test_incompatible_options_exit_2_before_writing(before, args, says):
    before_state = written(before.root)
    result = cli(*args, "--config", config_of(before))
    assert result.code == 2 and says in result.err and "No se escribió nada" in result.err and written(before.root) == before_state


def test_an_unknown_task_or_option_exits_2_from_the_parser(before):
    assert cli("task", "nope", "--config", config_of(before)).code == 2 and cli("run", "--nope").code == 2 and cli("replay", "--until").code == 2 and cli().code == 2


def test_a_task_from_load_on_of_a_new_run_exits_2_and_writes_nothing(before):
    snapshot = written(before.root)
    for task in pipeline.TASK_IDS[pipeline.TASK_IDS.index("load"):]:
        result = cli("task", task, "--config", config_of(before))
        assert result.code == 2 and "no tiene una entrega" in result.err, task
    assert written(before.root) == snapshot


@pytest.mark.parametrize("kind, until, says", [("after", "C2011-04-18", "no hay entregas pendientes"), ("before", "L2011-03-27", "anterior a la siguiente pendiente"), ("before", "W2001-01-01", "no es una entrega del plan")])
def test_replay_until_a_delivery_already_loaded_exits_2_whether_or_not_one_is_pending(kind, until, says, request):
    state = request.getfixturevalue(kind)
    snapshot = written(state.root)
    result = cli("replay", "--until", until, "--config", config_of(state))
    assert result.code == 2 and says in result.err and written(state.root) == snapshot


def test_a_replay_with_nothing_pending_exits_0_without_the_lock(after):
    snapshot = written(after.root)
    result = cli("replay", "--config", config_of(after))
    assert result.code == 0 and "no hay entregas pendientes" in result.out and written(after.root) == snapshot


def test_a_task_that_fails_exits_1_and_says_why(before, monkeypatch):
    for task in ("fetch_source", "deliver", "validate", "load"):
        assert cli("task", task, "--run-key", "f", "--config", config_of(before)).code == 0
    monkeypatch.setattr(pipeline, "TASKS", tuple(pipeline.TaskSpec(t.task_id, lambda ctx: (_ for _ in ()).throw(ValueError("hubo un problema"))) if t.task_id == "track" else t for t in pipeline.TASKS))
    result = cli("task", "track", "--run-key", "f", "--config", config_of(before), "-v")
    assert result.code == 1 and "falló: ValueError: hubo un problema" in result.err and "Traceback" in result.err


def test_a_rejected_delivery_or_source_exits_3(before, workbook, tmp_path):
    for task in ("fetch_source", "deliver"):
        assert cli("task", task, "--run-key", "r", "--config", config_of(before)).code == 0
    path = Path(before.cfg.paths.raw_dir) / "deliveries" / "C2011-04-18" / "lines.parquet"
    path.write_bytes(path.read_bytes()[:-9] + b"corrupted")
    result = cli("task", "validate", "--run-key", "r", "--config", config_of(before))
    assert result.code == 3 and "rechazada" in result.err
    broken = tmp_path / "broken"
    write_config_file(broken, dataclasses.replace(workbook, zip_sha256="0" * 64))      # the same workbook, with a hash that is not its own
    refused = cli("task", "fetch_source", "--config", config_of(type("S", (), {"root": broken})))
    assert refused.code == 3 and "rechazada" in refused.err


def test_a_rejected_delivery_or_source_writes_its_report_as_the_latest_with_its_copy_in_history(before, workbook, tmp_path):
    """The runbook's first principle and R3, step 1 (B6 of the evaluation, D50): a delivery that V11 rejects and a source that V01 rejects each leave their validation report as
    ``reports/validation/latest.md`` and ``latest.json``, with a copy in ``history/<run>.json``, so whoever follows R3 reads the rejection and not the report of the delivery that passed before it."""
    import json

    reports = Path(before.cfg.paths.reports_dir) / "validation"
    previous = (reports / "latest.json").read_text(encoding="utf-8")
    assert json.loads(previous)["delivery_id"] != "C2011-04-18", "the latest report is the last loaded delivery's, which passed"
    for task in ("fetch_source", "deliver"):
        assert cli("task", task, "--run-key", "r", "--config", config_of(before)).code == 0
    path = Path(before.cfg.paths.raw_dir) / "deliveries" / "C2011-04-18" / "lines.parquet"
    path.write_bytes(path.read_bytes()[:-9] + b"corrupted")
    assert cli("task", "validate", "--run-key", "r", "--config", config_of(before)).code == 3
    latest = json.loads((reports / "latest.json").read_text(encoding="utf-8"))
    assert (latest["delivery_id"], latest["run_key"]) == ("C2011-04-18", "r") and [r["rule_id"] for r in latest["results"] if not r["passed"]] == ["V11"]
    assert (reports / "history" / "r.json").read_text(encoding="utf-8") == (reports / "latest.json").read_text(encoding="utf-8")
    markdown = (reports / "latest.md").read_text(encoding="utf-8")
    assert "Validación de la entrega C2011-04-18" in markdown and "| V11 |" in markdown and "| falla |" in markdown

    broken = tmp_path / "broken"
    write_config_file(broken, dataclasses.replace(workbook, zip_sha256="0" * 64))      # the same workbook, with a hash that is not its own
    assert cli("task", "fetch_source", "--run-key", "s", "--config", str(broken / "config" / "test.toml")).code == 3
    from personaloffers.config import load_config

    folder = Path(load_config(broken / "config" / "test.toml").paths.reports_dir) / "validation"
    source = json.loads((folder / "latest.json").read_text(encoding="utf-8"))
    assert (source["delivery_id"], source["run_key"]) == ("fuente", "s") and [(r["rule_id"], r["passed"], r["severity"]) for r in source["results"]] == [("V01", False, "bloqueante")]
    assert (folder / "history" / "s.json").read_text(encoding="utf-8") == (folder / "latest.json").read_text(encoding="utf-8")
    text = (folder / "latest.md").read_text(encoding="utf-8")
    assert "Validación de la fuente" in text and "| V01 |" in text and "| falla |" in text
    assert str(tmp_path) not in text + json.dumps(source) and tmp_path.as_posix() not in text + json.dumps(source), "a report is versioned: it names no path of this machine"


def test_a_held_lock_exits_2_and_writes_nothing(before):
    from personaloffers.lock import sole_writer

    snapshot = written(before.root)
    answer = {}
    with sole_writer(before.cfg.paths.interim_dir, "someone else", None):
        worker = threading.Thread(target=lambda: answer.update(result=cli("run", "--config", config_of(before))))      # another thread of the process is refused like another process
        worker.start()
        worker.join(timeout=120)
        during = written(before.root)
    result = answer["result"]
    assert result.code == 2 and "otro hilo de este mismo proceso" in result.err.lower() and {k: v for k, v in during.items()} == snapshot


def test_run_from_fit_recipe_recovers_a_launch_whose_registry_write_failed(fresh, monkeypatch):
    """AC36, runbook R6: the registry fails after the seal; the run is left failed with the seal written and no model registered, and ``run --run-key <corrida> --from fit_recipe`` adopts the seal
    without choosing again and finishes the run."""
    config = config_of(fresh)
    first = cli("run", "--only", "fetch_source", "--config", config)      # a new run starts by fetch_source
    assert first.code == 0
    key = runs_of(fresh)[0]
    pipeline.run_all(fresh.cfg, run_key=key, only=["deliver", "validate", "load", "track", "build_base"])
    original = warehouse.register_models
    monkeypatch.setattr(warehouse, "register_models", lambda *a, **k: (_ for _ in ()).throw(OSError("disk full")))
    failed = cli("task", "fit_recipe", "--run-key", key, "--config", config)
    assert failed.code == 1 and "disk full" in failed.err and Path(fresh.cfg.paths.seal).is_file()
    sealed = Path(fresh.cfg.paths.seal).read_bytes()
    monkeypatch.setattr(warehouse, "register_models", original)
    from personaloffers import choose

    monkeypatch.setattr(choose, "choose", lambda *a, **k: pytest.fail("the recovery does not choose again"))
    recovered = cli("run", "--from", "fit_recipe", "--run-key", key, "--config", config)
    assert recovered.code == 0, recovered.err
    assert Path(fresh.cfg.paths.seal).read_bytes() == sealed and "mode=adopt" in recovered.out and "report" in recovered.out
    assert registry.read_seal(Path(fresh.cfg.paths.seal))["launch"]["recipe"]["name"]


def test_module_entry_point_runs_from_another_directory(tmp_path):
    result = subprocess.run([sys.executable, "-m", "personaloffers", "--help"], cwd=tmp_path, capture_output=True, text=True, env={**os.environ, "PYTHONPATH": str(PROJECT_ROOT / "src")}, timeout=120)
    assert result.returncode == 0 and "replay" in result.stdout and "make-fixture" in result.stdout and "serve-crm" in result.stdout and "docs-sync" in result.stdout


# --- every key of the configuration ----------------------------------------------------------------------------------------------


def _changed(value):
    if isinstance(value, date):
        return value + timedelta(days=1)
    if isinstance(value, bool):
        return not value
    if isinstance(value, int):
        return value + 1
    if isinstance(value, float):
        return value * 1.5 if value else 0.25
    if isinstance(value, str):
        return value + "x"
    if isinstance(value, tuple):
        return (*value, value[-1]) if value else (1,)
    return value


def test_every_config_key_changes_the_result_or_is_declared_informative(quick_cfg):
    """AC32, lesson B2 of project 06: a key that is validated and changes nothing is a defect. Here a key is held to what it can show without running the flow (``tests/unit/test_config_keys_read.py``
    shows that a module reads each one): a key that is sealed changes the fingerprint of the sealed view (``config_sha256``), and every key, sealed or not, is either declared informative or read."""
    from personaloffers.config import SealedConfig

    assert set(FINGERPRINT_KEYS).isdisjoint(UNSEALED_KEYS)
    view = SealedConfig.of(quick_cfg, "a" * 64, "b" * 64, "c" * 64)
    base = config_fingerprint(view)
    checked = 0
    for key in FINGERPRINT_KEYS:
        section, *rest = key.split(".")
        if len(rest) != 1 or not hasattr(view, section):
            continue
        node = getattr(view, section)
        if not hasattr(node, rest[0]):      # a key that the sealed view holds in another form (the hashes of what was read)
            continue
        value = getattr(node, rest[0])
        assert _changed(value) != value, key
        changed = dataclasses.replace(view, **{section: dataclasses.replace(node, **{rest[0]: _changed(value)})})
        assert config_fingerprint(changed) != base, key
        checked += 1
    assert checked > 45 and all(k not in FINGERPRINT_KEYS for k in INFORMATIVE_KEYS), "an informative key is not sealed: nothing rests on it"
    assert len(UNSEALED_KEYS) > 0
