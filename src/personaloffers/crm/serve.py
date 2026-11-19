"""``serve-crm``: run the CRM stand-in on the local machine (RF23; AC20; plan section 18; decision D27; risk item 2).

``serve_crm(argv)`` is what the command line's ``serve-crm`` calls (U19 wires it; ``python -m personaloffers.crm.serve`` calls it too). It listens on **127.0.0.1 only**, on a port from 1 to 65535, with the
token of the variable ``[crm] token_env`` names; whatever else is exit 2 **before a file is made or a server is started**: another host (``0.0.0.0``, ``localhost`` and an IPv6 address included: the
loopback address is spelled out, nothing is resolved), a port out of range, a configuration that cannot be read, no token. In Docker the same application is served by uvicorn's ``--factory`` on the
internal network of the compose, with no published port (``crm.standin.create_app_from_environment``).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

LOOPBACK_HOST = "127.0.0.1"
DEFAULT_PORT = 8001
EXIT_OK, EXIT_USAGE = 0, 2
NOTHING_WRITTEN = "No se escribió nada."


class _Usage(ValueError):
    """What the command line was given cannot be served."""


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="serve-crm", description=f"Levanta el CRM sustituto en {LOOPBACK_HOST} (PUT y GET de las listas por ronda y GET /health), con token.")
    parser.add_argument("--config", type=Path, metavar="RUTA", help="archivo de configuración (por defecto PERSONALOFFERS_CONFIG o config/pipeline.toml)")
    parser.add_argument("--host", metavar="DIRECCIÓN", default=LOOPBACK_HOST, help=f"interfaz en la que escucha: solo {LOOPBACK_HOST}; otra sale con 2 antes de crear nada")
    parser.add_argument("--port", metavar="N", default=str(DEFAULT_PORT), help=f"puerto, de 1 a 65535 (por defecto {DEFAULT_PORT})")
    parser.add_argument("-v", "--verbose", action="store_true", help="el registro del servidor")
    return parser


def _run_server(app: object, host: str, port: int, verbose: bool) -> None:
    import uvicorn

    uvicorn.run(app, host=host, port=port, log_level="info" if verbose else "warning")


def serve_crm(argv: list[str] | None = None) -> int:
    """Serve the stand-in (see the module); returns the exit code."""
    try:
        args = _parser().parse_args(sys.argv[1:] if argv is None else argv)
    except SystemExit as stop:      # argparse exits on a wrong option (2) and on --help (0)
        return int(stop.code or 0)
    try:
        if args.host != LOOPBACK_HOST:
            raise _Usage(f"--host {args.host!r}: el CRM sustituto solo escucha en {LOOPBACK_HOST} (D27); en Docker lo sirve el servicio crm del compose, en su red interna")
        if not (args.port.isascii() and args.port.isdigit() and 1 <= int(args.port) <= 65535):
            raise _Usage(f"--port {args.port!r}: se esperaba un puerto de 1 a 65535")
        from personaloffers import config as config_module     # the configuration, the application and its libraries are loaded only here
        from personaloffers.crm.standin import create_app

        cfg = config_module.load_config(args.config)
        try:
            app = create_app(cfg)
        except ValueError as error:
            raise _Usage(f"{error}: defina la variable de entorno {cfg.crm.token_env}") from error
    except (_Usage, ValueError, FileNotFoundError) as error:
        print(f"error: {error}. {NOTHING_WRITTEN}", file=sys.stderr)
        return EXIT_USAGE
    _run_server(app, args.host, int(args.port), args.verbose)
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(serve_crm())
