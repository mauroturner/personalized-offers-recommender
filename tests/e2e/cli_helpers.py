"""Helpers of the command-line and quick-mode tests (U19): a command of the CLI run in this process and a fingerprint of a folder."""

from __future__ import annotations

import contextlib
import io
import os
from pathlib import Path
from types import SimpleNamespace

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SKIPPED = {".venv", ".git", "__pycache__", ".pytest_cache"}


def cli(*args: str) -> SimpleNamespace:
    """``python -m personaloffers <args>`` in this process (``cli.main``): its exit code and what it wrote to stdout and stderr."""
    from personaloffers.cli import main

    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = main(list(args))
    return SimpleNamespace(code=code, out=out.getvalue(), err=err.getvalue())


def fingerprint(root: Path, skipped: set[str] = SKIPPED) -> dict[str, tuple[int, int]]:
    """Size and modification time of every file under `root` (the environment and the caches left out)."""
    found = {}
    for folder, names, files in os.walk(root):
        names[:] = [n for n in names if n not in skipped]
        for name in files:
            path = Path(folder) / name
            stat = path.stat()
            found[path.relative_to(root).as_posix()] = (stat.st_size, stat.st_mtime_ns)
    return found


def written(root: Path) -> dict[str, tuple[int, int]]:
    """What a command wrote under `root`: every file but the lock, which exists only while a writer holds it."""
    return {k: v for k, v in fingerprint(root).items() if not k.endswith("pipeline.lock")}
