"""The pinned source (U04; RF01, V01 and V02; AC01): the zip and its member are the accepted ones by size and SHA-256 or, in quick mode, the ones that the first good
view registered; the size is compared before the hash, the member has its exact bare name, and nothing is written by the check."""

from __future__ import annotations

import hashlib
import json
import zipfile

import pytest

from personaloffers import sources
from personaloffers.sources import SourceError, check_sources
from tests.fixtures import make_workbook as mw
from tests.fixtures.configs import config_for, copy_of, tree_of


@pytest.fixture
def cfg(quick_cfg, workbook, tmp_path):
    return config_for(quick_cfg, workbook, tmp_path / "project")


def damaged(folder, members: dict[str, bytes]):
    """A zip with these members that is accepted by size and hash (so that only the rule under test can fire)."""
    return mw.write_zip(folder / "zip.zip", members)


def test_check_sources_returns_the_hashes_of_the_zip_and_of_the_member_and_writes_nothing(cfg, workbook, tmp_path):
    before = tree_of(tmp_path)
    assert check_sources(cfg) == {"zip": workbook.zip_sha256, "member": workbook.member_sha256}
    assert tree_of(tmp_path) == before and not (tmp_path / "project").exists()


def test_a_missing_zip_is_v01_and_names_the_runbook(cfg, tmp_path):
    missing = config_for(cfg, mw.FixtureWorkbook(tmp_path / "nowhere" / "x.zip", 5, "0" * 64, "online_retail_II.xlsx", 5, "0" * 64), tmp_path / "project")
    with pytest.raises(SourceError) as caught:
        check_sources(missing)
    error = caught.value
    assert error.rule_id == "V01" and error.EXIT_CODE == 3 and "runbook R1" in str(error) and "research/s00_download.py" in str(error)
    assert error.problems == [{"rule_id": "V01", "reason": "missing", "file": "x.zip", "path": str(tmp_path / "nowhere" / "x.zip")}]


def test_another_size_is_refused_before_the_file_is_hashed(cfg, workbook, monkeypatch):
    def never(path, block=0):
        raise AssertionError("a file of another size must not be hashed")

    monkeypatch.setattr(sources, "sha256_file", never)
    import dataclasses

    wrong = dataclasses.replace(cfg, source=dataclasses.replace(cfg.source, zip_bytes=workbook.zip_bytes + 1))
    with pytest.raises(SourceError) as caught:
        check_sources(wrong)
    assert caught.value.rule_id == "V01"
    assert caught.value.problems[0]["reason"] == "size" and caught.value.problems[0]["expected"] == workbook.zip_bytes + 1
    assert caught.value.problems[0]["actual"] == workbook.zip_bytes


def test_the_same_size_with_another_hash_is_v01(cfg, workbook):
    import dataclasses

    wrong = dataclasses.replace(cfg, source=dataclasses.replace(cfg.source, zip_sha256="ab" * 32))
    with pytest.raises(SourceError) as caught:
        check_sources(wrong)
    problem = caught.value.problems[0]
    assert caught.value.rule_id == "V01" and (problem["reason"], problem["expected"], problem["actual"]) == ("sha256", "ab" * 32, workbook.zip_sha256)
    assert "runbook R1" in str(caught.value)


@pytest.mark.parametrize(("name", "members", "reason"), [
    ("extra", lambda xlsx: {"online_retail_II.xlsx": xlsx, "notes.txt": b"x"}, "members"),
    ("renamed", lambda xlsx: {"retail.xlsx": xlsx}, "members"),
    ("in a folder", lambda xlsx: {"sub/online_retail_II.xlsx": xlsx}, "members"),
    ("parent folder", lambda xlsx: {"../online_retail_II.xlsx": xlsx}, "members"),
    ("backslash", lambda xlsx: {"sub\\online_retail_II.xlsx": xlsx}, "members"),
    ("other case", lambda xlsx: {"ONLINE_RETAIL_II.xlsx": xlsx}, "members"),
    ("empty", lambda xlsx: {}, "members"),
])
def test_the_zip_holds_one_member_with_its_exact_bare_name(cfg, workbook, tmp_path, name, members, reason):
    xlsx = zipfile.ZipFile(workbook.zip_path).read("online_retail_II.xlsx")
    written = damaged(tmp_path / "bad", members(xlsx))
    bad = config_for(cfg, mw.FixtureWorkbook(written.zip_path, written.zip_bytes, written.zip_sha256, "online_retail_II.xlsx", workbook.member_bytes,
                                             workbook.member_sha256), tmp_path / "project")
    with pytest.raises(SourceError) as caught:
        check_sources(bad)
    assert caught.value.rule_id == "V02" and caught.value.problems[0]["reason"] == reason and "runbook R1" in str(caught.value), name
    assert caught.value.problems[0]["members"] == zipfile.ZipFile(written.zip_path).namelist()


def test_a_file_that_is_not_a_zip_is_v02_when_the_size_and_hash_are_the_accepted_ones(cfg, tmp_path):
    path = tmp_path / "bad" / "text.zip"
    path.parent.mkdir()
    path.write_bytes(b"this is not a zip file")
    bad = config_for(cfg, mw.FixtureWorkbook(path, path.stat().st_size, hashlib.sha256(path.read_bytes()).hexdigest(), "online_retail_II.xlsx", 5, "0" * 64),
                     tmp_path / "project")
    with pytest.raises(SourceError) as caught:
        check_sources(bad)
    assert caught.value.rule_id == "V02" and caught.value.problems[0]["reason"] == "not_a_zip"


def test_an_encrypted_member_is_v02(cfg, workbook, tmp_path):
    data = bytearray(workbook.zip_path.read_bytes())
    directory = data.rfind(b"PK\x01\x02")
    data[directory + 8] |= 0x01                                   # the central directory says the member is encrypted
    path = tmp_path / "bad" / "encrypted.zip"
    path.parent.mkdir()
    path.write_bytes(bytes(data))
    bad = config_for(cfg, mw.FixtureWorkbook(path, len(data), hashlib.sha256(bytes(data)).hexdigest(), workbook.member, workbook.member_bytes, workbook.member_sha256),
                     tmp_path / "project")
    with pytest.raises(SourceError) as caught:
        check_sources(bad)
    assert caught.value.rule_id == "V02" and caught.value.problems[0]["reason"] == "encrypted"


def test_the_member_has_the_accepted_size_and_the_accepted_hash(cfg, workbook, tmp_path):
    import dataclasses

    wrong_size = dataclasses.replace(cfg, source=dataclasses.replace(cfg.source, member_bytes=workbook.member_bytes + 1))
    with pytest.raises(SourceError) as caught:
        check_sources(wrong_size)
    problem = caught.value.problems[0]
    assert caught.value.rule_id == "V02" and (problem["reason"], problem["expected"], problem["actual"]) == ("size", workbook.member_bytes + 1, workbook.member_bytes)
    wrong_hash = dataclasses.replace(cfg, source=dataclasses.replace(cfg.source, member_sha256="cd" * 32))
    with pytest.raises(SourceError) as caught:
        check_sources(wrong_hash)
    problem = caught.value.problems[0]
    assert caught.value.rule_id == "V02" and (problem["reason"], problem["expected"], problem["actual"]) == ("sha256", "cd" * 32, workbook.member_sha256)


def test_a_member_that_differs_by_one_byte_is_v02_even_when_its_zip_is_the_accepted_one(cfg, workbook, tmp_path):
    xlsx = bytearray(zipfile.ZipFile(workbook.zip_path).read("online_retail_II.xlsx"))
    xlsx[len(xlsx) // 2] ^= 0x01
    written = damaged(tmp_path / "bad", {"online_retail_II.xlsx": bytes(xlsx)})
    bad = config_for(cfg, mw.FixtureWorkbook(written.zip_path, written.zip_bytes, written.zip_sha256, "online_retail_II.xlsx", workbook.member_bytes,
                                             workbook.member_sha256), tmp_path / "project")
    with pytest.raises(SourceError) as caught:
        check_sources(bad)
    assert caught.value.rule_id == "V02" and caught.value.problems[0]["reason"] == "sha256"


# --- quick mode: the first view is registered and then held (D02, D44) ------------------------------------------------------------


def quick_config(quick_cfg, fixture, tmp_path):
    """The quick configuration's own source: empty accepted sizes and hashes, a zip in a folder of the test."""
    import dataclasses

    copy = copy_of(fixture, tmp_path / "quick")
    base = config_for(quick_cfg, copy, tmp_path / "project")
    return dataclasses.replace(base, source=dataclasses.replace(base.source, zip_bytes=0, zip_sha256="", member_bytes=0, member_sha256=""))


def test_without_a_registry_the_quick_mode_accepts_the_first_view_and_the_check_writes_nothing(quick_cfg, workbook, tmp_path):
    cfg = quick_config(quick_cfg, workbook, tmp_path)
    before = tree_of(tmp_path)
    assert check_sources(cfg) == {"zip": workbook.zip_sha256, "member": workbook.member_sha256}
    assert tree_of(tmp_path) == before and sources.read_source_lock(sources.lock_path(cfg)) is None


def test_the_registry_holds_the_quick_mode_to_its_first_view(quick_cfg, workbook, tmp_path):
    cfg = quick_config(quick_cfg, workbook, tmp_path)
    lock = sources.lock_path(cfg)
    assert lock == cfg.source.zip_path.parent / "source.lock.json"
    sources.write_source_lock(lock, {"sha256": workbook.zip_sha256, "size": workbook.zip_bytes}, {"sha256": workbook.member_sha256, "size": workbook.member_bytes})
    document = json.loads(lock.read_text(encoding="utf-8"))
    assert document == {"version": 1, "zip": {"sha256": workbook.zip_sha256, "size": workbook.zip_bytes},
                        "member": {"sha256": workbook.member_sha256, "size": workbook.member_bytes}}
    assert sources.read_source_lock(lock) == document
    assert check_sources(cfg) == {"zip": workbook.zip_sha256, "member": workbook.member_sha256}
    # another zip in the same place: another size is refused by size, the same size with another hash by hash
    other = mw.make_workbook(tmp_path / "other", seed=1, customers=20)
    cfg.source.zip_path.write_bytes(other.zip_path.read_bytes())
    with pytest.raises(SourceError) as caught:
        check_sources(cfg)
    assert caught.value.rule_id == "V01" and caught.value.problems[0]["reason"] == "size" and caught.value.problems[0]["expected"] == workbook.zip_bytes
    data = bytearray(workbook.zip_path.read_bytes())
    data[len(data) // 2] ^= 0x01
    cfg.source.zip_path.write_bytes(bytes(data))
    with pytest.raises(SourceError) as caught:
        check_sources(cfg)
    assert caught.value.rule_id == "V01" and caught.value.problems[0]["reason"] == "sha256" and "registrada" in str(caught.value)


@pytest.mark.parametrize("text", [
    "not json", "[]", '{"version": 2, "zip": {"sha256": "' + "a" * 64 + '", "size": 1}, "member": {"sha256": "' + "a" * 64 + '", "size": 1}}',
    '{"version": 1, "zip": {"sha256": "A", "size": 1}, "member": {"sha256": "' + "a" * 64 + '", "size": 1}}',
    '{"version": 1, "zip": {"sha256": "' + "a" * 64 + '", "size": 0}, "member": {"sha256": "' + "a" * 64 + '", "size": 1}}',
    '{"version": 1, "zip": {"sha256": "' + "a" * 64 + '", "size": true}, "member": {"sha256": "' + "a" * 64 + '", "size": 1}}',
    '{"version": 1, "zip": {"sha256": "' + "a" * 64 + '", "size": 1}}',
    '{"version": 1, "zip": {"sha256": "' + "a" * 64 + '", "size": 1}, "member": {"sha256": "' + "a" * 64 + '", "size": 1}, "extra": 1}',
])
def test_a_registry_in_another_format_is_v01(quick_cfg, workbook, tmp_path, text):
    cfg = quick_config(quick_cfg, workbook, tmp_path)
    sources.lock_path(cfg).write_text(text, encoding="utf-8")
    with pytest.raises(SourceError) as caught:
        check_sources(cfg)
    assert caught.value.rule_id == "V01" and caught.value.problems[0]["reason"] == "lock" and "runbook R1" in str(caught.value)


def test_a_first_view_of_a_member_over_the_part_cap_is_refused_and_a_registered_size_replaces_the_cap(quick_cfg, workbook, tmp_path):
    import dataclasses

    cfg = quick_config(quick_cfg, workbook, tmp_path)
    capped = dataclasses.replace(cfg, source=dataclasses.replace(cfg.source, max_part_bytes=workbook.member_bytes - 1))
    with pytest.raises(SourceError) as caught:
        check_sources(capped)
    problem = caught.value.problems[0]
    assert caught.value.rule_id == "V02" and (problem["reason"], problem["expected"], problem["actual"]) == ("size", workbook.member_bytes - 1, workbook.member_bytes)
    assert check_sources(dataclasses.replace(cfg, source=dataclasses.replace(cfg.source, max_part_bytes=workbook.member_bytes))) == {
        "zip": workbook.zip_sha256, "member": workbook.member_sha256}


def test_the_extraction_writes_the_member_under_a_new_name_and_leaves_nothing_when_it_refuses(cfg, workbook, tmp_path):
    import dataclasses

    out = tmp_path / "scratch"
    path = sources.extract_workbook(cfg, out)
    assert path.parent == out and path.name != "online_retail_II.xlsx" and path.suffix == ".xlsx"
    assert path.read_bytes() == zipfile.ZipFile(workbook.zip_path).read("online_retail_II.xlsx")
    assert sources.extract_workbook(cfg, out) != path and len(list(out.iterdir())) == 2, "a name is never reused"
    refused = tmp_path / "refused"
    wrong = dataclasses.replace(cfg, source=dataclasses.replace(cfg.source, member_sha256="cd" * 32))
    with pytest.raises(SourceError) as caught:
        sources.extract_workbook(wrong, refused)
    assert caught.value.rule_id == "V02" and caught.value.problems[0]["reason"] == "sha256" and list(refused.iterdir()) == []
    # a member whose bytes are damaged inside the zip is corrupt, whatever the header says
    data = bytearray(workbook.zip_path.read_bytes())
    data[len(data) // 2] ^= 0xFF
    broken = tmp_path / "broken" / "fixture.zip"
    broken.parent.mkdir()
    broken.write_bytes(bytes(data))
    damaged_cfg = dataclasses.replace(cfg, source=dataclasses.replace(cfg.source, zip_path=broken, zip_bytes=len(data), zip_sha256=hashlib.sha256(bytes(data)).hexdigest()))
    for action in (lambda: check_sources(damaged_cfg), lambda: sources.extract_workbook(damaged_cfg, refused)):
        with pytest.raises(SourceError) as caught:
            action()
        assert caught.value.rule_id == "V02" and caught.value.problems[0]["reason"] == "corrupt"
    assert list(refused.iterdir()) == []
