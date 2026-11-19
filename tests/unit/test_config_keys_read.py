"""A key that is validated and fingerprinted but that no module reads (U19; lesson B2 of project 06, L85): ``config._check`` accepts it, ``FINGERPRINT_KEYS`` hashes it, and changing it changes ``config_sha256``
and nothing else, so a run under another value is called ``post_seal`` for no reason and the seal says a knob exists that turns nothing. This walks the keys of the configuration and fails on any that no module
outside ``config.py`` reads, by attribute name and section, in the abstract syntax tree of the sources.

What it accepts as a read: an attribute access ``.name`` in a module (not ``config.py``), or the text ``"name"`` where the module reads by name, that also names the key's section, as an attribute (``view.grid``)
or as a name (``grid``). A key inside a table counts as read when its table is. The generic serializers (``registry``) walk every field and read none by name, so they never count.
"""

from __future__ import annotations

import ast
from pathlib import Path

from personaloffers.config import FINGERPRINT_KEYS, INFORMATIVE_KEYS, UNSEALED_KEYS

SRC = Path(__file__).resolve().parents[2] / "src" / "personaloffers"
GENERIC = {"config.py"}
# keys whose only reader is a library or a service by name, not an attribute of the configuration object (each one with its reader)
READ_ELSEWHERE: dict[str, str] = {}


def module_names() -> dict[str, tuple[set[str], set[str]]]:
    """module path -> (the attribute names and strings it uses, the attribute and plain names it uses)."""
    out = {}
    for path in sorted(SRC.rglob("*.py")):
        relative = path.relative_to(SRC).as_posix()
        if relative in GENERIC:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        attributes = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
        constants = {n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)}
        names = attributes | {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} | {n.arg for n in ast.walk(tree) if isinstance(n, ast.arg)}
        out[relative] = (attributes | constants, names)
    return out


def readers_of(key: str, modules) -> list[str]:
    *path, leaf = key.split(".")
    section = path[0]
    return [name for name, (attributes, names) in modules.items() if leaf in attributes and section in names]


def test_every_fingerprinted_key_is_read_by_a_module_that_it_names():
    modules = module_names()
    unread = [key for key in (*FINGERPRINT_KEYS, *UNSEALED_KEYS) if key not in INFORMATIVE_KEYS and key not in READ_ELSEWHERE and not readers_of(key, modules)]
    assert unread == [], f"keys that are validated (and fingerprinted or declared unsealed) and that no module reads: {unread}; read them, or take them out of the configuration"


def test_the_walk_finds_a_key_that_nobody_reads_and_names_the_reader_of_one_that_is_read():
    modules = module_names()
    assert "metrics.py" in readers_of("evaluation.resamples", modules) and "holdout.py" in readers_of("holdout.share", modules)
    assert not readers_of("grid.not_a_key_at_all", modules) and not readers_of("nosuchsection.resamples", modules)


def test_a_key_read_elsewhere_names_its_reader():
    assert all(isinstance(reader, str) and reader for reader in READ_ELSEWHERE.values())
