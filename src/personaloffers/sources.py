"""The pinned source (RF01, V01 and V02; decision D02) and the first task, ``fetch_source``.

The zip of UCI and the workbook inside it are untrusted data: the flow never downloads them (``research/s00_download.py`` does, runbook R1), reads local files
only and does not read a byte of one before its size and its SHA-256 are the accepted ones.

* ``check_sources`` is V01 and V02: the zip exists and has the accepted size and hash or, in quick mode (an empty accepted hash), the size and hash registered in
  ``source.lock.json`` by the first good view; the zip holds one member, by the exact bare name that the configuration gives, not encrypted, with the accepted
  (or registered) size and SHA-256. The size is compared before the hash, so a file of another size is never hashed. It writes nothing.
* ``extract_workbook`` writes the member to a file of its own, under a name that is not one read from the archive, holding its bytes to the declared size, and checks
  its hash again while it writes.
* ``fetch_source`` runs both, then reads the workbook as an untrusted file (V03 to V07, ``personaloffers.workbook``) and writes the canonical lines with their
  manifest last, only when they are missing or are not the ones this zip gives; the quick mode's first view is registered only after all of that went without a
  failing rule. A rejected source writes nothing and leaves what was there untouched, the folder of the extraction included.
"""

from __future__ import annotations

import json
import re
import secrets
import tempfile
import zipfile
import zlib
from pathlib import Path
from typing import Any

from personaloffers.config import PipelineConfig
from personaloffers.files import sha256_file, write_atomic
from personaloffers.lines import ROLES

LOCK_NAME = "source.lock.json"
LOCK_VERSION = 1
RUNBOOK_R1 = "runbook R1: research/s00_download.py"
CHUNK = 1 << 20
_HEX64 = re.compile(r"[0-9a-f]{64}")


class SourceError(RuntimeError):
    """A rule of the source (V01 to V07) failed; the exit code of the command line is 3. ``problems`` says what, one dict per failing item (a rule, a file, a sheet,
    a column, a row: never the value of a customer or an invoice)."""

    EXIT_CODE = 3

    def __init__(self, rule_id: str, message: str, problems: list[dict] | None = None) -> None:
        super().__init__(f"{rule_id}: {message}")
        self.rule_id = rule_id
        self.problems = problems if problems is not None else []


def rule(rule_id: str, message: str, runbook: bool | None = None, **problem: Any) -> SourceError:
    """The error of a failing rule: V01 and V02 tell where the runbook R1 is, the others do not."""
    tell = rule_id in ("V01", "V02") if runbook is None else runbook
    return SourceError(rule_id, f"{message} ({RUNBOOK_R1})" if tell else message, [{"rule_id": rule_id, **problem}])


# --- the registry of the quick mode ---------------------------------------------------------------------------------------


def lock_path(cfg: PipelineConfig) -> Path:
    """Next to the zip: ``data/quick/source.lock.json`` in quick mode."""
    return Path(cfg.source.zip_path).parent / LOCK_NAME


def _valid_entry(value: Any) -> bool:
    return (isinstance(value, dict) and set(value) == {"sha256", "size"} and isinstance(value["sha256"], str) and bool(_HEX64.fullmatch(value["sha256"]))
            and isinstance(value["size"], int) and not isinstance(value["size"], bool) and value["size"] > 0)


def read_source_lock(path: Path) -> dict[str, Any] | None:
    """The hashes that quick mode registered, or None if none are. Anything else than the exact format is V01."""
    path = Path(path)
    if not path.exists():
        return None
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
        valid = (isinstance(document, dict) and set(document) == {"version", "zip", "member"} and document["version"] == LOCK_VERSION
                 and _valid_entry(document["zip"]) and _valid_entry(document["member"]))
    except (OSError, ValueError):
        valid = False
    if not valid:
        raise rule("V01", f"{path.name} no es un registro válido de las huellas de la fuente (se esperaba {{version, zip: {{sha256, size}}, member: {{sha256, size}}}})",
                   reason="lock", file=path.name)
    return document


def write_source_lock(path: Path, zip_entry: dict[str, Any], member_entry: dict[str, Any]) -> None:
    """Register the hash and size of the zip and of its member (``{"sha256": ..., "size": ...}`` each)."""
    document = {"version": LOCK_VERSION, "zip": dict(zip_entry), "member": dict(member_entry)}
    write_atomic(Path(path), json.dumps(document, indent=2, sort_keys=True) + "\n")


def _registry(cfg: PipelineConfig) -> dict[str, Any] | None:
    """The registry, only when a hash is left empty (quick mode): a pinned configuration never looks at it."""
    source = cfg.source
    return None if source.zip_sha256 and source.member_sha256 else read_source_lock(lock_path(cfg))


# --- V01 and V02 ----------------------------------------------------------------------------------------------------------------


def _accepted(cfg: PipelineConfig, key: str) -> tuple[int, str, str]:
    """``(size, sha256, which)`` that the zip (or the member) must have: the configured ones, or else the registered ones ('registrada'), or none ('' and 0)."""
    source = cfg.source
    digest, size = (source.zip_sha256, source.zip_bytes) if key == "zip" else (source.member_sha256, source.member_bytes)
    if digest:
        return size, digest, "aceptada"
    registered = _registry(cfg)
    if registered is not None:
        return registered[key]["size"], registered[key]["sha256"], "registrada"
    return 0, "", ""


def _member_digest(archive: zipfile.ZipFile, info: zipfile.ZipInfo, path: Path) -> str:
    """SHA-256 of the member, read in blocks. ``zipfile`` never hands out more bytes than the header declares (and the caller has held that to the limit), and it
    refuses a member whose CRC does not match what was read: a header that lies makes the member corrupt, not larger."""
    import hashlib

    digest = hashlib.sha256()
    try:
        with archive.open(info) as member:
            while chunk := member.read(CHUNK):
                digest.update(chunk)
    except (zipfile.BadZipFile, zlib.error, EOFError, NotImplementedError, RuntimeError) as error:
        raise rule("V02", f"el miembro «{info.filename}» de {path.name} está dañado o no se puede descomprimir ({type(error).__name__})", reason="corrupt",
                   file=path.name) from error
    return digest.hexdigest()


def check_sources(cfg: PipelineConfig) -> dict[str, str]:
    """V01 and V02: the zip and its member exist and are the accepted ones (or the registered ones). Returns ``{"zip": sha256, "member": sha256}``. Writes
    nothing and downloads nothing: a missing or different file is refused with the runbook R1. The size is compared before the file is hashed."""
    source = cfg.source
    path = Path(source.zip_path)
    if not path.is_file():
        raise rule("V01", f"no existe el zip de la fuente {path}: hay que colocarlo ahí", reason="missing", file=path.name, path=str(path))
    size = path.stat().st_size
    want_size, want_sha, which = _accepted(cfg, "zip")
    if which and size != want_size:
        raise rule("V01", f"el zip {path.name} pesa {size} bytes y el tamaño {which} es {want_size}; no se cambió nada", reason="size", file=path.name,
                   expected=want_size, actual=size)
    digest = sha256_file(path)
    if which and digest != want_sha:
        raise rule("V01", f"el zip {path.name} tiene la huella SHA-256 {digest} y la {which} es {want_sha}; no se cambió nada", reason="sha256", file=path.name,
                   expected=want_sha, actual=digest)
    try:
        archive = zipfile.ZipFile(path)
    except (zipfile.BadZipFile, OSError) as error:
        raise rule("V02", f"{path.name} no es un archivo zip válido", reason="not_a_zip", file=path.name) from error
    with archive:
        infos = archive.infolist()
        names = [info.filename for info in infos]
        if names != [source.member]:
            raise rule("V02", f"el zip debe contener solo el miembro «{source.member}», sin ruta, pero contiene {names}", reason="members", file=path.name, members=names)
        info = infos[0]
        if info.flag_bits & 0x1:
            raise rule("V02", f"el miembro «{info.filename}» de {path.name} está cifrado", reason="encrypted", file=path.name)
        want_size, want_sha, which = _accepted(cfg, "member")
        if which and info.file_size != want_size:
            raise rule("V02", f"el miembro «{info.filename}» declara {info.file_size} bytes y el tamaño {which} es {want_size}", reason="size", file=path.name,
                       expected=want_size, actual=info.file_size)
        limit = want_size if which else source.max_part_bytes
        if info.file_size > limit:
            raise rule("V02", f"el miembro «{info.filename}» declara {info.file_size} bytes, por encima del límite de {limit} ([source] max_part_bytes)", reason="size",
                       file=path.name, expected=limit, actual=info.file_size)
        member = _member_digest(archive, info, path)
    if which and member != want_sha:
        raise rule("V02", f"el miembro «{source.member}» tiene la huella SHA-256 {member} y la {which} es {want_sha}", reason="sha256", file=path.name,
                   expected=want_sha, actual=member)
    return {"zip": digest, "member": member}


def extract_workbook(cfg: PipelineConfig, out_dir: Path) -> Path:
    """Write the member of the zip to a new file in `out_dir` and return its path (call it after ``check_sources``). The name on disk is random and never one read
    from the archive; the file is created exclusively, written up to the declared size and hashed while it is written, and a member that is not the accepted
    (or registered) one leaves no file behind."""
    import hashlib

    source = cfg.source
    path = Path(source.zip_path)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    _size, want_sha, which = _accepted(cfg, "member")
    target = out_dir / f"{secrets.token_hex(8)}.xlsx"
    digest = hashlib.sha256()
    try:
        with zipfile.ZipFile(path) as archive:
            with archive.open(archive.getinfo(source.member)) as member, target.open("xb") as handle:
                while chunk := member.read(CHUNK):     # at most the declared size: see ``_member_digest``
                    handle.write(chunk)
                    digest.update(chunk)
    except (zipfile.BadZipFile, zlib.error, EOFError, KeyError, NotImplementedError, RuntimeError) as error:
        target.unlink(missing_ok=True)
        raise rule("V02", f"el miembro «{source.member}» de {path.name} está dañado o no se puede descomprimir ({type(error).__name__})", reason="corrupt",
                   file=path.name) from error
    except BaseException:
        target.unlink(missing_ok=True)
        raise
    if which and digest.hexdigest() != want_sha:
        target.unlink(missing_ok=True)
        raise rule("V02", f"el miembro «{source.member}» tiene la huella SHA-256 {digest.hexdigest()} y la {which} es {want_sha}", reason="sha256", file=path.name,
                   expected=want_sha, actual=digest.hexdigest())
    return target


# --- the first task ------------------------------------------------------------------------------------------------------------


def fetch_source(cfg: PipelineConfig) -> dict[str, Any]:
    """The first task: check the zip and its member (V01, V02), read the workbook as an untrusted file (V03 to V07) and write the canonical lines with their
    manifest last when they are missing or are not the ones these hashes give; register the quick mode's first view after all of that. Returns what the run
    records: the hashes, the rows, whether the lines were written and what the registry did. A rejected source writes nothing."""
    from personaloffers import workbook

    digests = check_sources(cfg)
    interim = Path(cfg.paths.interim_dir)
    problem, manifest = workbook.lines_state(interim)
    result: dict[str, Any] = {"zip_sha256": digests["zip"], "member_sha256": digests["member"]}
    if problem is None and manifest["zip_sha256"] == digests["zip"] and manifest["member_sha256"] == digests["member"]:
        result |= {"built": False, "lines": manifest["rows"], "lines_sha256": manifest["files"][workbook.LINES_NAME]}
    else:
        with tempfile.TemporaryDirectory(prefix="personaloffers-extract-") as folder:
            xlsx = extract_workbook(cfg, Path(folder))
            workbook.inspect_workbook(xlsx, cfg)
            raw = workbook.read_workbook(xlsx, cfg)
        frame = workbook.canonical_lines(raw, cfg)
        lines_sha256 = workbook.write_lines(frame, interim, digests)
        result |= {
            "built": True, "lines": len(frame), "lines_sha256": lines_sha256, "copies": len(raw) - len(frame), "repeats": int(frame["internal_repeat"].sum()),
            "roles": {role: int((frame["role"] == role).sum()) for role in ROLES},
            "rows_by_sheet": {name: int((raw["sheet"] == number).sum()) for number, name in enumerate(cfg.source.sheets, start=1)},
        }
    pinned = bool(cfg.source.zip_sha256 and cfg.source.member_sha256)
    lock = lock_path(cfg)
    if pinned:
        result["lock"] = "not needed"
    elif read_source_lock(lock) is None:
        with zipfile.ZipFile(cfg.source.zip_path) as archive:
            member_size = archive.getinfo(cfg.source.member).file_size
        write_source_lock(lock, {"sha256": digests["zip"], "size": Path(cfg.source.zip_path).stat().st_size}, {"sha256": digests["member"], "size": member_size})
        result["lock"] = "registered"
    else:
        result["lock"] = "held"
    return result


__all__ = ["LOCK_NAME", "RUNBOOK_R1", "SourceError", "check_sources", "extract_workbook", "fetch_source", "lock_path", "read_source_lock", "rule", "write_source_lock"]
