"""Atomic writes (RNF06): the temporary file is flushed to disk before the rename, a failure leaves the target as it was, and no module of the
package writes a file in another way (plan section 1 and section 24.2)."""

from __future__ import annotations

import ast
import os
from pathlib import Path

import pytest

from personaloffers import files

PROJECT = Path(__file__).resolve().parents[2]


@pytest.fixture
def calls(monkeypatch) -> list[tuple]:
    """The order of ``os.fsync`` and ``os.replace`` in `personaloffers.files`, with the size the synced file had when it was synced."""
    seen: list[tuple] = []
    real_fsync, real_replace = os.fsync, os.replace

    def fsync(fd: int) -> None:
        seen.append(("fsync", os.fstat(fd).st_size))
        real_fsync(fd)

    def replace(source, target) -> None:
        seen.append(("replace", Path(target).name))
        real_replace(source, target)

    monkeypatch.setattr(files.os, "fsync", fsync)
    monkeypatch.setattr(files.os, "replace", replace)
    return seen


def test_write_atomic_flushes_the_whole_payload_to_disk_before_the_rename(tmp_path, calls):
    payload = b"x" * 5000 + "ñ\n".encode()
    target = files.write_atomic(tmp_path / "out" / "data.bin", payload)
    assert target.read_bytes() == payload
    assert calls == [("fsync", len(payload)), ("replace", "data.bin")]
    assert sorted(p.name for p in target.parent.iterdir()) == ["data.bin"]


def test_write_atomic_writes_text_as_utf8_and_leaves_newlines_alone(tmp_path):
    target = files.write_atomic(tmp_path / "text.md", "línea 1\nlínea 2\r\n")
    assert target.read_bytes() == "línea 1\nlínea 2\r\n".encode("utf-8")


def test_write_atomic_replaces_a_previous_content_whole(tmp_path):
    target = tmp_path / "keep.txt"
    target.write_bytes(b"a much longer previous content")
    files.write_atomic(target, b"new")
    assert target.read_bytes() == b"new" and [p.name for p in tmp_path.iterdir()] == ["keep.txt"]


def test_atomic_path_flushes_what_the_caller_wrote_to_the_temporary_name_before_the_rename(tmp_path, calls):
    """A writer that takes a path (Parquet) is synced after it closes the file, whatever it wrote."""
    target = tmp_path / "table.parquet"
    with files.atomic_path(target) as temporary:
        assert temporary != target and temporary.parent == target.parent and not target.exists()
        temporary.write_bytes(b"0123456789")
    assert target.read_bytes() == b"0123456789"
    assert calls == [("fsync", 10), ("replace", "table.parquet")]


def test_a_failed_sync_keeps_the_previous_target_and_leaves_no_temporary_file(tmp_path, monkeypatch):
    target = tmp_path / "keep.txt"
    target.write_bytes(b"old")
    renamed: list[str] = []

    def broken(fd: int) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(files.os, "fsync", broken)
    real_replace = os.replace
    monkeypatch.setattr(files.os, "replace", lambda a, b: (renamed.append(str(b)), real_replace(a, b)))
    with pytest.raises(OSError, match="disk full"):
        files.write_atomic(target, b"new")
    assert target.read_bytes() == b"old" and renamed == [] and [p.name for p in tmp_path.iterdir()] == ["keep.txt"]


def test_a_failed_rename_keeps_the_previous_target_and_leaves_no_temporary_file_and_no_open_descriptor(tmp_path, monkeypatch):
    """``write_atomic`` writes through the descriptor that created the temporary file: when the rename fails the file is closed (it can be removed) and
    the target is as it was."""
    target = tmp_path / "keep.txt"
    target.write_bytes(b"old")

    def broken(source, destination) -> None:
        raise OSError("access denied")

    monkeypatch.setattr(files.os, "replace", broken)
    with pytest.raises(OSError, match="access denied"):
        files.write_atomic(target, "new")
    assert target.read_bytes() == b"old" and [p.name for p in tmp_path.iterdir()] == ["keep.txt"]


def test_a_failure_of_the_writer_keeps_the_previous_target_and_leaves_no_temporary_file(tmp_path):
    """A writer that raises never replaces the target, and a first write that fails leaves no file at all."""
    target = tmp_path / "keep.txt"
    target.write_bytes(b"old")
    with pytest.raises(RuntimeError, match="boom"), files.atomic_path(target) as temporary:
        temporary.write_bytes(b"partial")
        raise RuntimeError("boom")
    assert target.read_bytes() == b"old" and [p.name for p in tmp_path.iterdir()] == ["keep.txt"]
    fresh = tmp_path / "sub" / "fresh.txt"
    with pytest.raises(RuntimeError, match="boom"), files.atomic_path(fresh) as temporary:
        temporary.write_bytes(b"partial")
        raise RuntimeError("boom")
    assert not fresh.exists() and list(fresh.parent.iterdir()) == []


def test_sha256_file_is_the_hash_of_the_bytes_whatever_the_block_size(tmp_path):
    path = tmp_path / "a.bin"
    path.write_bytes(b"abc")
    assert files.sha256_file(path) == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
    big = tmp_path / "big.bin"
    big.write_bytes(b"0123456789" * 1000)
    assert files.sha256_file(big, block=7) == files.sha256_file(big)


# --- the static rule: nothing writes a file but through write_atomic -------------------------------------------------------

WRITER_ATTRIBUTES = {"write_text", "write_bytes", "to_parquet", "to_csv", "to_json", "to_excel", "to_feather", "savefig", "write_table", "touch"}
WRITER_CALLS_OF_MODULES = {("shutil", "copy"), ("shutil", "copy2"), ("shutil", "copyfile"), ("shutil", "move"), ("os", "rename"), ("os", "replace")}
# Modules that may write a file without write_atomic, each with the reason (unversioned state or a file that is not a result): none yet. A unit that adds
# one says why here; ``files.py`` is the one place that renames and syncs.
ALLOWED_RAW_WRITERS: dict[str, str] = {}


def _opens_for_writing(call: ast.Call) -> bool:
    mode = None
    if len(call.args) >= 2 and isinstance(call.args[1], ast.Constant):
        mode = call.args[1].value
    for keyword in call.keywords:
        if keyword.arg == "mode" and isinstance(keyword.value, ast.Constant):
            mode = keyword.value.value
    return isinstance(mode, str) and any(flag in mode for flag in "wax+")


def _method_opens_for_writing(call: ast.Call) -> bool:
    """``path.open("wb")``: the mode is the first argument."""
    mode = None
    if call.args and isinstance(call.args[0], ast.Constant):
        mode = call.args[0].value
    for keyword in call.keywords:
        if keyword.arg == "mode" and isinstance(keyword.value, ast.Constant):
            mode = keyword.value.value
    return isinstance(mode, str) and any(flag in mode for flag in "wax+")


class _RawWriters(ast.NodeVisitor):
    def __init__(self) -> None:
        self.found: list[tuple[int, str]] = []
        self._inside_atomic_path = 0

    def visit_With(self, node: ast.With) -> None:
        guarded = any(
            isinstance(item.context_expr, ast.Call)
            and (getattr(item.context_expr.func, "id", None) == "atomic_path" or getattr(item.context_expr.func, "attr", None) == "atomic_path")
            for item in node.items
        )
        self._inside_atomic_path += guarded
        self.generic_visit(node)
        self._inside_atomic_path -= guarded

    visit_AsyncWith = visit_With  # noqa: N815

    def visit_Call(self, node: ast.Call) -> None:
        func = node.func
        name = None
        if isinstance(func, ast.Name) and func.id == "open" and _opens_for_writing(node):
            name = "open(..., write mode)"
        elif isinstance(func, ast.Attribute):
            if func.attr == "open" and _method_opens_for_writing(node):
                name = f".open({'write mode'})"
            elif func.attr in WRITER_ATTRIBUTES and (node.args or node.keywords or func.attr in {"touch"}):
                name = f".{func.attr}(...)"   # ``frame.to_json()`` with no target returns a text and writes nothing
            elif isinstance(func.value, ast.Name) and (func.value.id, func.attr) in WRITER_CALLS_OF_MODULES:
                name = f"{func.value.id}.{func.attr}(...)"
        if name is not None and not self._inside_atomic_path:
            self.found.append((node.lineno, name))
        self.generic_visit(node)


def raw_writers(root: Path, allowed: dict[str, str]) -> list[str]:
    """Every call that writes a file in a module under `root` that is not ``files.py`` and not in `allowed`, outside a ``with atomic_path(...)`` block:
    ``path:line name``."""
    found: list[str] = []
    for path in sorted(Path(root).rglob("*.py")):
        relative = path.relative_to(root).as_posix()
        if relative == "files.py" or relative in allowed:
            continue
        visitor = _RawWriters()
        visitor.visit(ast.parse(path.read_text(encoding="utf-8"), filename=str(path)))
        found += [f"{relative}:{line} {name}" for line, name in visitor.found]
    return found


def test_every_writer_of_a_versioned_file_uses_write_atomic(tmp_path):
    # the check itself, on a package with each kind of writer, one inside atomic_path and one in an allowed module
    package = tmp_path / "pkg"
    package.mkdir()
    (package / "files.py").write_text("import os\n\ndef write_atomic(path, data):\n    os.replace(path, path)\n", encoding="utf-8")
    (package / "bad.py").write_text(
        "import os\nimport shutil\n\n\ndef run(path, frame, table):\n    path.write_text('x')\n    path.write_bytes(b'x')\n    open(path, 'w')\n"
        "    open(path, mode='ab')\n    path.open('wb')\n    frame.to_parquet(path)\n    frame.to_csv(path)\n    shutil.copy(path, path)\n"
        "    os.rename(path, path)\n    table.savefig(path)\n    pq.write_table(table, path)\n", encoding="utf-8")
    (package / "good.py").write_text(
        "from pkg.files import atomic_path, write_atomic\n\n\ndef run(path, frame):\n    write_atomic(path, 'x')\n    open(path)\n    open(path, 'rb')\n"
        "    path.open('r')\n    path.read_text()\n    with atomic_path(path) as temporary:\n        frame.to_parquet(temporary)\n"
        "    with files.atomic_path(path) as temporary:\n        temporary.write_bytes(b'x')\n", encoding="utf-8")
    (package / "allowed.py").write_text("def run(path):\n    path.write_text('x')\n", encoding="utf-8")
    assert raw_writers(package, {"allowed.py": "test"}) == [
        "bad.py:6 .write_text(...)", "bad.py:7 .write_bytes(...)", "bad.py:8 open(..., write mode)", "bad.py:9 open(..., write mode)",
        "bad.py:10 .open(write mode)", "bad.py:11 .to_parquet(...)", "bad.py:12 .to_csv(...)", "bad.py:13 shutil.copy(...)", "bad.py:14 os.rename(...)",
        "bad.py:15 .savefig(...)", "bad.py:16 .write_table(...)",
    ]
    assert raw_writers(package, {"allowed.py": "test", "bad.py": "test"}) == []
    # and the package as it is: only files.py and the modules named here, each with its reason, write a file without write_atomic
    assert raw_writers(PROJECT / "src" / "personaloffers", ALLOWED_RAW_WRITERS) == []
    assert all(reason.strip() for reason in ALLOWED_RAW_WRITERS.values())
