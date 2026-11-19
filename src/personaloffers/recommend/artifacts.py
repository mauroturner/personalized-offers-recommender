"""The fitted models as flat arrays with their hashes (AC15, M02; decision D13; plan section 9.7; runbook R6).

Each component of a round (``als``, ``cosine``, ``rules``, ``popularity``) is a folder ``<models>/<round>/<component>/`` with its arrays as ``.npy`` files and ``artifact.json``: the version, the
parameters and the size and SHA-256 of each file. The files are written first and the manifest last, every one with ``write_atomic``, so a folder without a manifest is an interrupted write and
no manifest ever describes a file that is not there. The SHA-256 of the manifest is what ``model_registry`` keeps (``artifact_sha256``).

Reading is the part that matters (nothing here runs code from a file): the registered hash is compared with the manifest's first, and nothing is deserialized if it differs; the names the manifest
lists must be plain ``.npy`` names (a ``.pkl``, a ``.npz`` or a path that leaves the folder is refused by its name); a file in the folder that the manifest does not list is refused; each listed
file must have its size and hash; and then ``numpy.load(allow_pickle=False)``, so an array of objects cannot be read even if everything before it were forged consistently.
"""

from __future__ import annotations

import io
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from personaloffers.calendar import monday_of
from personaloffers.files import sha256_file, write_atomic

COMPONENTS = ("als", "cosine", "rules", "popularity")
MANIFEST = "artifact.json"
MANIFEST_VERSION = 1
_ARRAY_NAME = re.compile(r"[A-Za-z0-9_]+")
_FILE_NAME = re.compile(r"[A-Za-z0-9_]+\.npy")


class ArtifactError(RuntimeError):
    """An artifact is not what was registered, or it holds something that is not read (M02)."""


@dataclass(frozen=True)
class Artifact:
    path: Path
    sha256: str          # of the manifest: what ``model_registry`` keeps


def artifact_sha256(folder: Path) -> str:
    """The SHA-256 of the manifest of the artifact in `folder`."""
    manifest = Path(folder) / MANIFEST
    if not manifest.is_file():
        raise ArtifactError(f"la carpeta {Path(folder).name} no tiene {MANIFEST}: la escritura no terminó o no es un artefacto")
    return sha256_file(manifest)


def _serialized(name: str, array: np.ndarray) -> bytes:
    if not _ARRAY_NAME.fullmatch(name):
        raise ArtifactError(f"el nombre «{name}» de un arreglo debe ser letras, números y guiones bajos")
    array = np.asarray(array)
    if array.dtype.hasobject:
        raise ArtifactError(f"el arreglo «{name}» es de objetos: solo se escriben arreglos planos que se leen sin pickle")
    buffer = io.BytesIO()
    np.save(buffer, array, allow_pickle=False)
    return buffer.getvalue()


def write_component(models_dir: Path, round_id: str, component: str, arrays: dict[str, np.ndarray], params: dict[str, Any]) -> Artifact:
    """Write the arrays of a component of a round and then its manifest; the folder is created. Writing the same content again changes nothing; other content for a folder that already has its
    manifest is an ``ArtifactError`` (what was registered is not rewritten)."""
    try:
        monday_of(round_id)
    except ValueError as error:
        raise ArtifactError(f"{round_id!r} no es el identificador de una ronda") from error
    if component not in COMPONENTS:
        raise ArtifactError(f"el componente {component!r} no es uno de {', '.join(COMPONENTS)}")
    payloads = {f"{name}.npy": _serialized(name, array) for name, array in sorted(arrays.items())}
    manifest = {"version": MANIFEST_VERSION, "params": params,
                "files": {name: {"bytes": len(data), "sha256": _sha256(data)} for name, data in payloads.items()}}
    text = json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    folder = Path(models_dir) / round_id / component
    if (folder / MANIFEST).is_file():
        if (folder / MANIFEST).read_text(encoding="utf-8") == text:
            return Artifact(folder, sha256_file(folder / MANIFEST))
        raise ArtifactError(f"el artefacto {round_id}/{component} ya existe con otro contenido: lo registrado no se reescribe")
    for name, data in payloads.items():
        write_atomic(folder / name, data)
    write_atomic(folder / MANIFEST, text)
    return Artifact(folder, sha256_file(folder / MANIFEST))


def _sha256(data: bytes) -> str:
    import hashlib

    return hashlib.sha256(data).hexdigest()


def verify_component(folder: Path, expected_sha256: str) -> dict[str, Any]:
    """The manifest of the artifact in `folder`, only if it has the registered hash and every file is the one it lists (names, sizes, hashes, and nothing else in the folder); ``ArtifactError``
    otherwise. Nothing is deserialized."""
    folder = Path(folder)
    if artifact_sha256(folder) != expected_sha256:
        raise ArtifactError(f"la huella del artefacto {folder.name} no es la registrada: no se lee")
    try:
        manifest = json.loads((folder / MANIFEST).read_text(encoding="utf-8"))
        listed, params = manifest["files"], manifest["params"]
        valid = manifest["version"] == MANIFEST_VERSION and isinstance(listed, dict) and isinstance(params, dict) and set(manifest) == {"version", "params", "files"}
    except (ValueError, KeyError, TypeError) as error:
        raise ArtifactError(f"el manifiesto de {folder.name} no se puede leer") from error
    if not valid:
        raise ArtifactError(f"el manifiesto de {folder.name} no tiene la forma esperada")
    for name in listed:
        if not isinstance(name, str) or not _FILE_NAME.fullmatch(name):
            raise ArtifactError(f"el nombre «{name}» del manifiesto no es el de un arreglo .npy de la carpeta: solo se leen arreglos .npy sin pickle")
    present = {path.name for path in folder.iterdir()} - {MANIFEST}
    for name in sorted(present - set(listed)):
        raise ArtifactError(f"el archivo «{name}» de la carpeta no está en el manifiesto: no se lee ({folder.name})")
    for name, entry in listed.items():
        path = folder / name
        if not path.is_file():
            raise ArtifactError(f"falta el archivo «{name}» que lista el manifiesto de {folder.name}")
        if path.stat().st_size != entry.get("bytes") or sha256_file(path) != entry.get("sha256"):
            raise ArtifactError(f"el archivo «{name}» no es el que lista el manifiesto de {folder.name} (tamaño o huella)")
    return manifest


def read_component(folder: Path, expected_sha256: str) -> tuple[dict[str, np.ndarray], dict[str, Any]]:
    """The arrays and the parameters of the artifact in `folder`, only if ``verify_component`` accepts it; ``ArtifactError`` otherwise, before any file is deserialized."""
    folder = Path(folder)
    manifest = verify_component(folder, expected_sha256)
    listed, params = manifest["files"], manifest["params"]
    arrays: dict[str, np.ndarray] = {}
    for name in sorted(listed):
        try:
            array = np.load(folder / name, allow_pickle=False)
        except ValueError as error:
            raise ArtifactError(f"el archivo «{name}» contiene objetos de Python (pickle), que no se leen") from error
        if array.dtype.hasobject:
            raise ArtifactError(f"el archivo «{name}» contiene objetos de Python (pickle), que no se leen")
        arrays[name[: -len(".npy")]] = array
    return arrays, params
