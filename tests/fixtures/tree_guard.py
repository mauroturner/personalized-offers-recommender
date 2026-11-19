"""The tree a session must leave alone (plan, section 24; AC33; project 07's c135752, where a test of ``--config`` ran ``figures`` over the real folder and rewrote
``docs/figures``): the files of the project are fingerprinted when the session starts and again when it ends, and a session that changed one fails and names it.

What counts as the project's files is what git lists as tracked, or new and not ignored (``git ls-files --cached --others --exclude-standard``): the
environment, the data and every other ignored folder are state that a test may write. Without a repository (a toy suite, the image of a service) the folder is walked
and the same state (``.git``, ``.venv``, ``data``, ``__pycache__``, ``.pytest_cache``) is skipped. The fingerprint is the SHA-256 of each file's bytes, never its time,
so a file written again with the same content is not a change.
"""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

import pytest

SNAPSHOT = pytest.StashKey[dict[str, str | None]]()
SKIPPED_FOLDERS = {".git", ".venv", "data", "__pycache__", ".pytest_cache"}


def _walk(root: Path) -> list[str]:
    names = []
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if path.is_file() and not SKIPPED_FOLDERS & set(relative.parts):
            names.append(relative.as_posix())
    return names


def listed_files(root: Path) -> list[str]:
    """The files of the project folder, relative to it and with forward slashes."""
    try:
        done = subprocess.run(["git", "-C", str(root), "ls-files", "--cached", "--others", "--exclude-standard", "-z"], capture_output=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return _walk(root)
    if done.returncode != 0:
        return _walk(root)
    return sorted({name for name in done.stdout.decode("utf-8").split("\0") if name})


def snapshot(root: Path) -> dict[str, str | None]:
    """The SHA-256 of each file of the project (None for one that git lists and is not on disk)."""
    root = Path(root)
    found: dict[str, str | None] = {}
    for name in listed_files(root):
        path = root / name
        found[name] = hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
    return found


def differences(before: dict[str, str | None], after: dict[str, str | None]) -> list[str]:
    """``changed <file>``, then ``removed <file>``, then ``created <file>`` (each sorted)."""
    present = {name for name, digest in after.items() if digest is not None}
    existed = {name for name, digest in before.items() if digest is not None}
    changed = sorted(name for name in present & existed if before[name] != after[name])
    removed = sorted(existed - present)
    created = sorted(present - existed)
    return [f"changed {name}" for name in changed] + [f"removed {name}" for name in removed] + [f"created {name}" for name in created]


def start(config: pytest.Config) -> None:
    config.stash[SNAPSHOT] = snapshot(config.rootpath)


def finish(session: pytest.Session) -> None:
    config = session.config
    if SNAPSHOT not in config.stash:
        return
    changes = differences(config.stash[SNAPSHOT], snapshot(config.rootpath))
    if not changes:
        return
    session.exitstatus = pytest.ExitCode.TESTS_FAILED
    reporter = config.pluginmanager.get_plugin("terminalreporter")
    lines = ["La sesión cambió archivos del árbol del proyecto (ninguna prueba escribe ahí: su estado va en una carpeta temporal o en data/):"]
    lines += [f"  {change}" for change in changes]
    if reporter is not None:
        for number, line in enumerate(lines):
            reporter.write_line(line, red=number == 0, bold=number == 0)
    else:  # pragma: no cover - pytest always has its terminal reporter unless -p no:terminal
        print("\n".join(lines))
