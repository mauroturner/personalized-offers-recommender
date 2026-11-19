"""Configurations for the tests that read a file (U04): the quick configuration made to accept exactly one fixture file, with every path under a folder of the test.

``dataclasses.replace`` does not run the checks of ``load_config``, which is what a test of a damaged source needs: the limits of ``[source]`` can be set below what
``load_config`` accepts only through its own file, and the rule under test is the one that must fire."""

from __future__ import annotations

import dataclasses
import io
import shutil
import zipfile
from pathlib import Path

import openpyxl

from personaloffers.config import PipelineConfig
from tests.fixtures.make_workbook import FixtureWorkbook, Variant


def config_for(quick: PipelineConfig, fixture: FixtureWorkbook, root: Path, **source: object) -> PipelineConfig:
    """`quick` with the zip, sizes and hashes of `fixture` accepted (``source`` overrides any key of ``[source]``) and every path under `root`."""
    root = Path(root)
    accepted = dict(zip_path=fixture.zip_path, zip_bytes=fixture.zip_bytes, zip_sha256=fixture.zip_sha256, member=fixture.member,
                    member_bytes=fixture.member_bytes, member_sha256=fixture.member_sha256)
    paths = {field.name: root / field.name for field in dataclasses.fields(quick.paths)}
    paths.update(seal=root / "reports" / "model_seal.json", dashboard_html=root / "dashboard" / "powerbi-design.html", readme=root / "README.md")
    return dataclasses.replace(quick, source=dataclasses.replace(quick.source, **(accepted | source)), paths=dataclasses.replace(quick.paths, **paths),
                               project_root=root)


def config_for_variant(quick: PipelineConfig, variant: Variant, root: Path) -> PipelineConfig:
    return config_for(quick, variant.workbook, root, **variant.overrides)


def copy_of(fixture: FixtureWorkbook, folder: Path) -> FixtureWorkbook:
    """The same fixture in a folder of its own (the quick mode registers its first view next to the zip)."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / fixture.zip_path.name
    shutil.copyfile(fixture.zip_path, target)
    return dataclasses.replace(fixture, zip_path=target)


def tree_of(root: Path) -> dict[str, bytes]:
    """Every file under `root` with its bytes (what 'nothing was written' compares)."""
    root = Path(root)
    return {path.relative_to(root).as_posix(): path.read_bytes() for path in sorted(root.rglob("*")) if path.is_file()} if root.exists() else {}


def read_sheets(zip_path: Path, member: str = "online_retail_II.xlsx") -> dict[str, list[tuple]]:
    """Every row of every sheet of a fixture zip (the header first), read with openpyxl and nothing of the package under test."""
    with zipfile.ZipFile(zip_path) as archive:
        data = archive.read(member)
    book = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    try:
        return {name: [tuple(row) for row in book[name].iter_rows(values_only=True)] for name in book.sheetnames}
    finally:
        book.close()
