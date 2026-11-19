"""Command line of the pipeline: ``python -m personaloffers <command>`` (RF24, RF25, RNF05; AC30, AC31, AC32; plan section 22; D26, D29). Adapted from project 07's ``cli.py``.

``run``, ``task`` and ``replay`` call ``pipeline.run_all``, ``pipeline.run_task`` and ``pipeline.replay``: the same task list, order and functions as the Airflow DAG, so the whole flow runs on Windows without
Airflow. ``make-fixture`` writes the synthetic workbook of the quick mode, ``serve-crm`` is ``crm.serve.serve_crm`` (the stand-in on 127.0.0.1 only), ``figures`` calls ``figures.write_figures`` and ``docs-sync`` fills the
results block of the README and the tables of the data dictionary: no step is written here.

Exit codes: 0 ok (also a run with no delivery left and a replay with nothing pending), 1 a task failed, 2 wrong usage or configuration (also a task refused by the state of its run, because another writer holds the data
folder, a rebuild followed only in part or the test asked for with another configuration), 3 the delivery or the source was rejected. A combination that cannot do what it says is refused with 2 before anything is
written: no option is ignored in silence (AC32). Every relative path of ``--config`` and of ``make-fixture`` is taken from ``$PERSONALOFFERS_HOME`` or the project folder, never from the working directory (RNF05).
``main(argv)`` is the entry the tests use, in the same process.

The top-level help imports only the configuration: the pipeline is imported by the commands that run tasks. A new command is a ``commands.add_parser`` in ``build_parser`` and a branch of ``_execute``.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import traceback
from pathlib import Path

from personaloffers.config import DEFAULT_PROJECT_ROOT, ENV_CONFIG, ENV_HOME, load_config

EXIT_OK, EXIT_FAILED, EXIT_USAGE, EXIT_REJECTED = 0, 1, 2, 3
TASK_COMMANDS = ("run", "task")          # the commands whose options name tasks: only they need the pipeline's list to build the parser
SUMMARY_MD = "evaluation_summary.md"
DICTIONARY = Path("docs") / "data-dictionary.md"
NOTHING_WRITTEN = "No se escribió nada."
QUIET_KEYS = ("seconds", "sha256", "peak_working_set_mb", "peak_commit_mb", "memory_counter", "message")     # what a line of a task leaves out: it is in the state of the run
LOOPBACK_HOST = "127.0.0.1"


class _UsageError(ValueError):
    """A combination of options that cannot do what it says (before anything is written)."""


def _home() -> Path:
    home = os.environ.get(ENV_HOME)
    return Path(home).resolve() if home else DEFAULT_PROJECT_ROOT


def _common() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--config", type=Path, metavar="RUTA",
                        help=f"archivo de configuración (por defecto ${ENV_CONFIG} o config/pipeline.toml); una ruta relativa se toma desde ${ENV_HOME} o la carpeta del proyecto")
    common.add_argument("-v", "--verbose", action="store_true", help="muestra el detalle de cada paso y la traza de la tarea que falla")
    return common


def build_parser(task_ids: tuple[str, ...] | None = None) -> argparse.ArgumentParser:
    """The parser. `task_ids` are the choices of ``--only``, ``--from`` and ``task`` (``pipeline.TASK_IDS``); without them those options take any name and the pipeline refuses an unknown one (the top-level help
    does not import the pipeline)."""
    parser = argparse.ArgumentParser(prog="python -m personaloffers", description="Una oferta para cada cliente, armada sola: una lista por cliente cada semana, con un grupo de control listo y su evaluación.")
    commands = parser.add_subparsers(dest="command", required=True, metavar="COMANDO")
    common = _common()
    tasks = f" ({', '.join(task_ids)})" if task_ids else ""

    run = commands.add_parser("run", parents=[common], help="una corrida: la siguiente entrega, con las trece tareas en orden", description=f"Una corrida con las tareas de pipeline.TASKS{tasks}.")
    run.add_argument("--only", nargs="+", choices=task_ids, metavar="TAREA", help="corre solo estas tareas de la corrida, en su orden")
    run.add_argument("--from", dest="start", choices=task_ids, metavar="TAREA", help="sigue la corrida desde esta tarea")
    run.add_argument("--run-key", metavar="CLAVE", help="la corrida que se continúa (con --only o --from)")

    replay = commands.add_parser("replay", parents=[common], help="corridas seguidas, una por entrega pendiente, hasta agotarlas o hasta una entrega")
    replay.add_argument("--until", metavar="ENTREGA", help="la última entrega que se corre, por su identificador (por ejemplo W2011-08-08; por defecto, todas las pendientes; una anterior a la siguiente "
                                                           "pendiente, o cualquiera si no queda ninguna, sale con 2)")

    task = commands.add_parser("task", parents=[common], help="una tarea de una corrida", description=f"Una tarea de una corrida{tasks}.")
    task.add_argument("task", choices=task_ids, metavar="TAREA")
    task.add_argument("--run-key", metavar="CLAVE", help="la corrida a la que pertenece (una nueva si se omite; una tarea desde load necesita la de una corrida que tiene su entrega: sin ella sale con 2)")

    fixture = commands.add_parser("make-fixture", help="escribe el libro sintético del modo rápido (unas 6.000 líneas de 300 clientes inventados) como un zip",
                                  description="Escribe el zip con el libro sintético que usa el modo rápido (data/quick/online_retail_fixture.zip), el mismo que usan las pruebas; con la misma semilla, los mismos bytes.")
    fixture.add_argument("output", type=Path, metavar="SALIDA_ZIP", help="el zip que se escribe; una ruta relativa se toma desde $PERSONALOFFERS_HOME o, sin él, desde la carpeta del proyecto")
    fixture.add_argument("--seed", type=int, default=0, metavar="N", help="la semilla del generador, desde 0 (por defecto 0)")

    serve = commands.add_parser("serve-crm", help=f"levanta el CRM sustituto en {LOOPBACK_HOST} (PUT y GET de las listas por ronda y GET /health), con token",
                                description="Sirve el CRM sustituto con FastAPI y uvicorn, solo en la interfaz local, con el token de la variable de entorno que dice [crm] token_env. No escribe nada más que su propia base.")
    serve.add_argument("--config", type=Path, metavar="RUTA", help="archivo de configuración")
    serve.add_argument("--host", metavar="DIRECCIÓN", help=f"interfaz en la que escucha: solo {LOOPBACK_HOST}; otra sale con 2 antes de crear nada")
    serve.add_argument("--port", metavar="N", help="puerto, de 1 a 65535 (por defecto 8001)")
    serve.add_argument("-v", "--verbose", action="store_true", help="el registro del servidor")

    commands.add_parser("figures", parents=[common], help="dibuja las figuras de la documentación desde los archivos del sitio verificados de la última corrida")
    docs_sync = f"copia el resumen de resultados (reports/{SUMMARY_MD}) en el bloque de resultados del README y la tabla de cada Parquet en el diccionario de datos"
    commands.add_parser("docs-sync", parents=[common], help=docs_sync, description=docs_sync[0].upper() + docs_sync[1:] + ". Un segundo uso no cambia nada; si el README o el diccionario no tienen sus marcadores no se escribe nada.")
    return parser


def _say(text: str) -> None:
    sys.stdout.write(text + "\n")


def _fail(text: str) -> None:
    sys.stderr.write(text + "\n")


class _LineFormatter(logging.Formatter):
    """One line per record: the traceback of a failed task is printed once, by ``main`` with ``-v``."""

    def formatException(self, ei) -> str:
        return ""


def _configure_logging(verbose: bool) -> None:
    """Log to the standard error from the package's own logger, one line per record, replacing the handler of an earlier call in this process (the tests make several): information with ``-v``, warnings and
    errors without it."""
    package = logging.getLogger("personaloffers")
    for handler in [h for h in package.handlers if getattr(h, "_personaloffers_cli", False)]:
        package.removeHandler(handler)
    handler = logging.StreamHandler(sys.stderr)
    handler._personaloffers_cli = True   # type: ignore[attr-defined]
    handler.setFormatter(_LineFormatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    package.addHandler(handler)
    package.setLevel(logging.INFO if verbose else logging.WARNING)


def _check_run(args: argparse.Namespace, task_ids: tuple[str, ...]) -> None:
    """The combinations of ``run`` that cannot do what they say, refused before a state file is created (plan section 22)."""
    if args.only and args.start is not None:
        raise _UsageError("--only y --from no se combinan: una elige las tareas y la otra desde cuál se sigue. " + NOTHING_WRITTEN)
    if args.run_key and not args.only and args.start is None:
        raise _UsageError("--run-key continúa una corrida y necesita --only o --from para decir qué tareas corren; una corrida nueva no lleva clave. " + NOTHING_WRITTEN)
    first = next(t for t in task_ids if t in args.only) if args.only else (args.start or task_ids[0])
    if args.run_key is None and first != task_ids[0]:
        raise _UsageError(f"una corrida nueva empieza por {task_ids[0]} y esta empezaría por {first}: para seguir una corrida que ya empezó, dé su clave con --run-key. " + NOTHING_WRITTEN)


def _brief(result: dict) -> str:
    return ", ".join(f"{k}={v}" for k, v in result.items() if k not in QUIET_KEYS and v is not None and not isinstance(v, (dict, list)))


def _show_run(outcome: list[dict]) -> None:
    for step in outcome:
        result = step["result"]
        if step["task"] == "deliver" and result.get("delivered"):
            _say(f"entrega {result['delivery_id']} (cálculo al {result['as_of']})")
        _say(f"{step['task']:<18} {result.get('seconds', 0):>8.1f} s  {_brief(result)}")
    if outcome and not outcome[-1]["result"].get("delivered", True):
        _say(outcome[-1]["result"]["message"])


def _output_file(path: Path) -> Path:
    home = _home()
    output = path if path.is_absolute() else Path(os.path.normpath(home / path))   # like the paths of the configuration: never the working directory
    if not path.is_absolute() and home not in output.parents:
        raise _UsageError(f"{path} sale de la carpeta del proyecto ({home}): dé una ruta absoluta si el destino está fuera a propósito. {NOTHING_WRITTEN}")
    return output


def _make_fixture(args: argparse.Namespace) -> int:
    root = DEFAULT_PROJECT_ROOT
    if args.seed < 0:
        raise _UsageError(f"--seed {args.seed}: la semilla es un entero desde 0. {NOTHING_WRITTEN}")
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))   # the generator lives with the tests, next to src/
    try:
        from tests.fixtures import make_workbook as generator
    except ModuleNotFoundError as error:
        if error.name not in ("tests", "tests.fixtures", "tests.fixtures.make_workbook"):
            raise   # a module the generator itself needs is missing: a real error, not an absent tests tree
        raise _UsageError(f"el generador del libro sintético vive en tests/fixtures/ de la carpeta del proyecto ({root}) y no está: make-fixture solo corre desde una copia completa. {NOTHING_WRITTEN}") from error
    output = _output_file(args.output)
    rows = generator.generate_rows(args.seed, len(generator.CUSTOMERS))
    written = generator.write_zip(output, {generator.MEMBER: generator.build_xlsx(generator.split_sheets(rows))}, generator.worked_out_truth(rows))
    _say(f"escribí {output.name} en {output.parent} ({written.zip_bytes} bytes, semilla {args.seed})")
    return EXIT_OK


def _docs_sync(cfg) -> int:
    """The results block of the README from the summary and the table of each Parquet in the data dictionary: everything is checked first and then written (a file without its markers is left as it was, exit 2)."""
    from personaloffers.dashboard.semantic_model import MODEL
    from personaloffers.docs_sync import sync_dictionary
    from personaloffers.files import write_atomic
    from personaloffers.reporting import RESULTS_END, RESULTS_START, replace_block

    summary, readme = Path(cfg.paths.reports_dir) / SUMMARY_MD, Path(cfg.paths.readme)
    dictionary = readme.parent / DICTIONARY
    if not readme.is_file():   # the quick mode has no README of its own
        raise _UsageError(f"la configuración no tiene un README que sincronizar: {readme.name} no existe (el modo rápido no lo tiene). {NOTHING_WRITTEN}")
    if not summary.is_file():
        raise _UsageError(f"falta el resumen de resultados {summary.name}: lo escribe la tarea report. {NOTHING_WRITTEN}")
    text = readme.read_text(encoding="utf-8")
    try:
        new = replace_block(text, readme.name, RESULTS_START, RESULTS_END, summary.read_text(encoding="utf-8"))
        old_dictionary = dictionary.read_text(encoding="utf-8") if dictionary.is_file() else None
        new_dictionary = None if old_dictionary is None else sync_dictionary(old_dictionary, MODEL)
    except ValueError as error:
        raise _UsageError(f"{error}. {NOTHING_WRITTEN}") from error
    if new != text:
        write_atomic(readme, new)
    _say(f"{readme.name} actualizado" if new != text else f"{readme.name} ya estaba al día")
    if new_dictionary is None:
        _say(f"{dictionary.name} no existe: no se sincronizó")
    else:
        if new_dictionary != old_dictionary:
            write_atomic(dictionary, new_dictionary)
        _say(f"{dictionary.name} actualizado" if new_dictionary != old_dictionary else f"{dictionary.name} ya estaba al día")
    return EXIT_OK


def _figures(cfg) -> int:
    from personaloffers.figures import write_figures   # matplotlib: only the command that draws pays for it

    try:
        paths = write_figures(cfg.paths.site_dir, cfg.paths.figures_dir)
    except FileNotFoundError as error:   # no site files, or a folder that is not one export (SiteSetError): nothing was written
        raise _UsageError(f"las figuras se dibujan solo desde los archivos del sitio de una misma exportación: {error}. {NOTHING_WRITTEN}") from error
    for path in paths:
        _say(f"escribí {path.name}")
    return EXIT_OK


def _execute(args: argparse.Namespace, cfg, pipeline) -> int:
    if args.command == "docs-sync":
        return _docs_sync(cfg)
    if args.command == "figures":
        return _figures(cfg)
    if args.command == "task":
        result = pipeline.run_task(args.task, args.run_key, cfg)
        _say(f"{args.task}: {_brief(result)}")
        return EXIT_OK
    if args.command == "replay":
        runs = pipeline.replay(cfg, args.until)
        for outcome in runs:
            _show_run(outcome)
        _say(f"{len(runs)} corrida" + ("" if len(runs) == 1 else "s") if runs else "no hay entregas pendientes: las del plan ya están cargadas")
        return EXIT_OK
    _show_run(pipeline.run_all(cfg, only=args.only, start=args.start, run_key=args.run_key))
    return EXIT_OK


def _command_of(argv: list[str]) -> str | None:
    return next((a for a in argv if not a.startswith("-")), None)


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:1] == ["serve-crm"]:      # its own parser reads its options: the stand-in is a module of its own that Docker runs too
        from personaloffers.crm.serve import serve_crm

        return serve_crm(argv[1:])
    task_ids = None
    if _command_of(argv) in TASK_COMMANDS:
        from personaloffers.pipeline import TASK_IDS

        task_ids = TASK_IDS
    try:
        args = build_parser(task_ids).parse_args(argv)
    except SystemExit as stop:   # argparse exits on a wrong option (2) and on --help (0)
        return int(stop.code or 0)
    _configure_logging(getattr(args, "verbose", False))
    if args.command == "make-fixture":
        try:
            return _make_fixture(args)
        except (_UsageError, ValueError, OSError) as error:   # a path that cannot be written, or the generator absent
            _fail(f"error: {error}")
            return EXIT_USAGE
    try:
        if args.command == "run":
            _check_run(args, task_ids)
        cfg = load_config(args.config)
    except (ValueError, FileNotFoundError) as error:   # a wrong option or configuration: nothing has been written
        _fail(f"error: {error}")
        return EXIT_USAGE
    from personaloffers import pipeline
    from personaloffers.sources import SourceError
    from personaloffers.validate import ValidationError

    try:
        return _execute(args, cfg, pipeline)
    except (ValidationError, SourceError) as error:
        _fail(f"rechazada: {error}")
        return EXIT_REJECTED
    except (_UsageError, pipeline.UsageError, pipeline.RunRefusedError) as error:   # refused before anything ran or was written
        _fail(f"error: {error}")
        return getattr(error, "exit_code", EXIT_USAGE)
    except Exception as error:   # a task failed: its record is in the state of the run
        _fail(f"falló: {type(error).__name__}: {error}")
        if getattr(args, "verbose", False):
            _fail("".join(traceback.format_exception(error)).rstrip())
        return EXIT_FAILED


__all__ = ["EXIT_FAILED", "EXIT_OK", "EXIT_REJECTED", "EXIT_USAGE", "build_parser", "main"]
