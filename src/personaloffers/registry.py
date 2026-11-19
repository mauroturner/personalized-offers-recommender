"""The sealed view of the configuration, its fingerprint and the seal (RF13, AC16; risk item 1; decision D21; plan section 13).

**The view.** ``sealed_view`` is the configuration that the calculations of the seal receive: the keys of ``FINGERPRINT_KEYS`` and the hashes of what was read (the zip, the workbook and the canonical
lines); nothing about where the files are, the CRM or the site's limit can reach a sealed value. ``view_to_dict`` writes it as a plain dictionary (dates as ISO text, tuples as lists) and
``config_fingerprint`` is the SHA-256 of its canonical JSON, the ``config_sha256`` of the seal, of the runs and of every output (the hash of the TOML file is another thing and is not here).

**The seal** is ``reports/model_seal.json``, ``{"version": 1, "launch": {...}}`` and later a ``test`` part. The launch part is created exclusively (``files.write_exclusive``: the name is taken or it is
not, and a file that is there is never touched) before the first weekly delivery is loaded, and no part is ever rewritten. ``seal_state`` says what a seal is to a configuration: ``none`` (no seal or
not a launch part yet), ``match`` (the same fingerprint) or ``post_seal`` (another one: whatever is computed with it is after the seal, M03). A seal that cannot be read is a ``SealError``, never a
missing one: nobody starts over because a file was damaged. ``check_launch`` compares what a launch recomputes with what was sealed and names every field that differs (runbook R7).
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
from collections.abc import Mapping
from datetime import date
from pathlib import Path
from typing import Any, Literal

from personaloffers.config import PipelineConfig, SealedConfig
from personaloffers.files import write_atomic, write_exclusive

SEAL_VERSION = 1
LAUNCH_KEYS = frozenset({"config_sha256", "config", "run_key", "as_of", "validation", "recipe", "baselines", "holdout", "lists"})
_HEX64_LENGTH = 64
# What a launch recomputes, and where the seal keeps it
COMPARED = {
    "validation_digest": ("validation", "digest"), "recipe": ("validation", "recipe"), "holdout_fingerprint": ("holdout", "fingerprint"), "lists_fingerprint": ("lists", "fingerprint"),
}


class SealError(RuntimeError):
    """The seal cannot be read, is not a seal, or was offered something that is not a launch part."""


class SealExistsError(SealError):
    """The launch part of the seal exists: it is written once and never rewritten."""


class LaunchSealMissingError(SealError):
    """The launch part of the seal is not there: the test does not start before it (RNF07e, runbook R7)."""


class SealMismatchError(SealError):
    """What the launch recomputed is not what the seal says (runbook R7)."""


def sealed_view(cfg: PipelineConfig, observed: Mapping[str, str]) -> SealedConfig:
    """The sealed view of `cfg` for what was read: the SHA-256 of the zip (``zip``), of the workbook (``member``) and of the canonical lines (``lines``)."""
    missing = [name for name in ("zip", "member", "lines") if name not in observed]
    if missing:
        raise ValueError(f"faltan las huellas de lo que se leyó: {', '.join(missing)} (zip, member y lines)")
    return SealedConfig.of(cfg, observed["zip"], observed["member"], observed["lines"])


def _plain(value: Any) -> Any:
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {field.name: _plain(getattr(value, field.name)) for field in dataclasses.fields(value)}
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, (tuple, list)):
        return [_plain(item) for item in value]
    if isinstance(value, Path):
        raise TypeError("a path is not part of a sealed view")
    return value


def view_to_dict(view: SealedConfig) -> dict[str, Any]:
    """The sealed view as a plain dictionary: dates as ``AAAA-MM-DD`` text, tuples as lists, the three hashes of what was read at the end."""
    return _plain(view)


def canonical_json(document: Any) -> str:
    """The text that is hashed: sorted keys, no spaces, the characters as they are."""
    return json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def config_fingerprint(view: SealedConfig) -> str:
    """The ``config_sha256``: the SHA-256 of the canonical JSON of the sealed view."""
    return hashlib.sha256(canonical_json(view_to_dict(view)).encode("utf-8")).hexdigest()


def read_seal(seal_path: Path) -> dict[str, Any] | None:
    """The seal, or None when the file is not there. A file that is there and is not a seal (not JSON, another version, no launch part that is an object) is a ``SealError``."""
    path = Path(seal_path)
    if not path.exists():
        return None
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise SealError(f"el sello {path.name} no se puede leer como JSON: no se parte de cero por un archivo dañado (runbook R7)") from error
    if not (isinstance(document, dict) and document.get("version") == SEAL_VERSION and isinstance(document.get("launch"), dict)):
        raise SealError(f"{path.name} no es un sello de la versión {SEAL_VERSION} con su parte del lanzamiento (runbook R7)")
    return document


def seal_state(seal_path: Path, config_sha256: str) -> Literal["none", "match", "post_seal"]:
    """``none`` without a seal, ``match`` when its launch part has this fingerprint and ``post_seal`` when it has another."""
    document = read_seal(seal_path)
    if document is None:
        return "none"
    return "match" if document["launch"].get("config_sha256") == config_sha256 else "post_seal"


def _check_launch_part(launch: Mapping[str, Any]) -> None:
    keys = set(launch)
    if keys != LAUNCH_KEYS:
        raise SealError(f"la parte del lanzamiento debe tener exactamente {sorted(LAUNCH_KEYS)}; le faltan {sorted(LAUNCH_KEYS - keys)} y le sobran {sorted(keys - LAUNCH_KEYS)}")
    digest = launch["config_sha256"]
    if not (isinstance(digest, str) and len(digest) == _HEX64_LENGTH) or digest != hashlib.sha256(canonical_json(launch["config"]).encode("utf-8")).hexdigest():
        raise SealError("config_sha256 de la parte del lanzamiento no es la huella de su configuración")
    if not (isinstance(launch["run_key"], str) and launch["run_key"]):
        raise SealError("la parte del lanzamiento necesita la clave de la corrida que la escribe")


def write_launch_seal(seal_path: Path, launch: Mapping[str, Any]) -> None:
    """Create the seal with its launch part, only if there is no seal: a seal that exists (whatever it holds, the same content included) is a ``SealExistsError`` and is left as it was. The part is
    checked before anything is written."""
    _check_launch_part(launch)
    text = json.dumps({"version": SEAL_VERSION, "launch": launch}, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    try:
        write_exclusive(seal_path, text)
    except FileExistsError as error:
        raise SealExistsError(f"el sello {Path(seal_path).name} ya existe: la parte del lanzamiento se escribe una vez y no se reescribe (runbook R12)") from error


def check_launch(sealed: Mapping[str, Any], recomputed: Mapping[str, str]) -> None:
    """Compare what a launch recomputed (``validation_digest``, ``recipe``, ``holdout_fingerprint`` and ``lists_fingerprint``, any of them) with the launch part: a ``SealMismatchError`` names each
    one that is not the sealed one."""
    different = []
    for name, value in recomputed.items():
        place = COMPARED.get(name)
        if place is None or sealed[place[0]][place[1]] != value:
            different.append(name)
    if different:
        raise SealMismatchError(f"lo que el lanzamiento recalculó no es lo sellado en: {', '.join(different)} (runbook R7)")


def require_launch_seal(seal_path: Path, config_sha256: str) -> dict[str, Any]:
    """The launch part of the seal, for a weekly delivery to go on: a ``LaunchSealMissingError`` without it (the test starts only after the launch is sealed) and a ``SealMismatchError`` when the seal is of
    another configuration (a weekly round is made with the sealed recipe, and an analysis with another configuration starts in a folder of its own, runbook R12)."""
    document = read_seal(seal_path)
    if document is None:
        raise LaunchSealMissingError("no hay sello del lanzamiento: la prueba no empieza antes de sellar el lanzamiento (runbook R7)")
    if document["launch"].get("config_sha256") != config_sha256:
        raise SealMismatchError("el sello del lanzamiento es de otra configuración que la de esta corrida: una ronda semanal se arma con la receta sellada (runbook R12)")
    return document["launch"]


# --- the test part of the seal (U14; RF18, AC16, AC24; risk item 1: the test is evaluated once) ------------------------------------------------------------------------------------------


TEST_KEYS = frozenset({"config_sha256", "run_key", "as_of", "criteria", "metrics", "operation"})
NOT_COMPARED = ("run_key", "as_of")     # what a repetition of the close does not reproduce: the key of its run and the hour of its delivery plan


class EvaluationRefusedError(SealError):
    """The test cannot be evaluated: there is no seal, or the seal has no test part yet and the configuration is not the sealed one (runbook R7)."""


def rounded(value: Any) -> Any:
    """A sealed number to the six decimals that a seal is compared at (a dictionary or a list is rounded inside). The one rule of every comparison with the seal: the repetition of the test and the rebuild of its
    criteria (``evaluation.criteria_from_seal``) decide "the same number" with it."""
    if isinstance(value, float):
        return round(value, 6)
    if isinstance(value, Mapping):
        return {key: rounded(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [rounded(item) for item in value]
    return value


def _flat(document: Any, prefix: str = "") -> dict[str, Any]:
    if isinstance(document, Mapping):
        found: dict[str, Any] = {}
        for key, value in document.items():
            found.update(_flat(value, f"{prefix}{key}."))
        return found
    if isinstance(document, (list, tuple)):
        found = {}
        for index, value in enumerate(document):
            found.update(_flat(value, f"{prefix}{index}."))
        return found
    return {prefix[:-1]: document}


def differing_keys(sealed: Mapping[str, Any], current: Mapping[str, Any]) -> list[str]:
    """The keys (``section.key``) in which two plain configurations differ, sorted: what the refusal of an evaluation names."""
    a, b = _flat(sealed), _flat(current)
    absent = object()
    return sorted(key for key in set(a) | set(b) if a.get(key, absent) != b.get(key, absent))


def check_test_evaluation(seal_path: Path, view: SealedConfig) -> Literal["first", "repeat", "post_seal"]:
    """What evaluating the test with the configuration `view` means, decided **before** anything is read or written (D21).

    ``first``: the seal has the launch part with this configuration and no test part, so this evaluation is the one that is sealed. ``repeat``: the seal has its test part and this is the same configuration:
    the evaluation must reproduce it. ``post_seal``: the test is sealed and this is another configuration: it is computed apart and never replaces the sealed one. With another configuration and **no** test part
    the evaluation is refused (``EvaluationRefusedError`` naming the keys that differ), and so it is without a seal or with a launch part that is not a seal's."""
    document = read_seal(seal_path)
    if document is None:
        raise EvaluationRefusedError("no hay sello: el lanzamiento lo escribe antes de que se evalúe la prueba, y no se evalúa sin él (runbook R7)")
    fingerprint = config_fingerprint(view)
    sealed = document["launch"].get("config_sha256")
    if document.get("test") is not None:
        return "repeat" if sealed == fingerprint else "post_seal"
    if sealed != fingerprint:
        keys = differing_keys(document["launch"].get("config", {}), view_to_dict(view))
        raise EvaluationRefusedError("la prueba no se evalúa con otra configuración que la sellada mientras el sello no tiene su parte de la prueba: la primera evaluación es la que se sella "
                                     f"(D21); las claves que difieren: {', '.join(keys) or '(ninguna que se pueda nombrar)'}. No se escribió nada (runbook R7)")
    return "first"


def _check_test_part(test: Mapping[str, Any]) -> None:
    keys = set(test)
    if keys != TEST_KEYS:
        raise SealError(f"la parte de la prueba debe tener exactamente {sorted(TEST_KEYS)}; le faltan {sorted(TEST_KEYS - keys)} y le sobran {sorted(keys - TEST_KEYS)}")
    digest = test["config_sha256"]
    if not (isinstance(digest, str) and len(digest) == _HEX64_LENGTH and all(ch in "0123456789abcdef" for ch in digest)):
        raise SealError("config_sha256 de la parte de la prueba debe ser un SHA-256 de 64 dígitos hexadecimales")
    if not (isinstance(test["run_key"], str) and test["run_key"]):
        raise SealError("la parte de la prueba necesita la clave de la corrida que la escribe")
    try:
        json.dumps(dict(test), allow_nan=False)
    except (TypeError, ValueError) as error:
        raise SealError(f"la parte de la prueba tiene un valor que no es JSON o no es finito: {error}") from error


def write_test_seal(seal_path: Path, test: Mapping[str, Any]) -> Literal["written", "unchanged", "post_seal"]:
    """Add the test part to the seal once. ``written``: the seal had only its launch part, which is kept exactly as it was, and now has `test` too (the file is read back and must say what was written).
    ``unchanged``: it already has a test part whose values, rounded to 6 decimals, are these. ``post_seal``: `test` was evaluated with another configuration than the sealed one; the seal is left as it is.
    Any other difference is a ``SealMismatchError`` that names the values (runbook R7): every key that can change a sealed value is in ``config_sha256``, so there is no third case."""
    _check_test_part(test)
    path = Path(seal_path)
    document = read_seal(path)
    if document is None:
        raise SealError("no hay sello: la parte de la prueba se escribe después de la del lanzamiento")
    if test["config_sha256"] != document["launch"].get("config_sha256"):
        return "post_seal"
    if document.get("test") is not None:
        then, now = (_flat(rounded({k: v for k, v in part.items() if k not in NOT_COMPARED})) for part in (document["test"], test))
        absent = object()
        differ = sorted(key for key in set(then) | set(now) if then.get(key, absent) != now.get(key, absent))
        if not differ:
            return "unchanged"
        named = "; ".join(f"{key}: {then.get(key)!r} sellado, {now.get(key)!r} en esta corrida" for key in differ[:6])
        raise SealMismatchError(f"la evaluación de la prueba con la configuración sellada no reproduce los valores sellados, redondeados a 6 decimales: {named}{' y otros' if len(differ) > 6 else ''} (runbook R7)")
    text = json.dumps({**document, "test": dict(test)}, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n"
    write_atomic(path, text)
    kept = read_seal(path) or {}
    if kept.get("launch") != document["launch"] or rounded(kept.get("test")) != rounded(dict(test)):
        raise SealMismatchError("lo que consta en el sello no es lo que esta corrida escribió: otra escritura lo cambió (runbook R7)")
    return "written"
