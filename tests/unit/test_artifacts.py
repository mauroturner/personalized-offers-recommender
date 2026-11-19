"""The artifacts of the fitted models (U09; AC15, M02; decision D13): flat ``.npy`` arrays and a manifest of sizes and hashes, written atomically; read only if the hash that was
registered is the hash of what is there, with ``allow_pickle=False``; and nothing else (a pickle, a ``.npz``, an object array, a file the manifest does not list) is ever read."""

from __future__ import annotations

import hashlib
import json
import pickle

import numpy as np
import pytest

from personaloffers import files
from personaloffers.recommend import artifacts
from personaloffers.recommend.artifacts import ArtifactError


def arrays() -> dict[str, np.ndarray]:
    rng = np.random.default_rng(0)
    return {"item_factors": rng.random((5, 3)).astype(np.float32), "user_ids": np.arange(7, dtype=np.int64), "codes": np.array(["85123A", "22423", "x"])}


def written(tmp_path, name="als", round_id="R2011-08-01"):
    return artifacts.write_component(tmp_path / "models", round_id, name, arrays(), {"factors": 3})


def test_a_component_is_written_as_npy_arrays_with_a_manifest_of_sizes_and_hashes(tmp_path):
    artifact = written(tmp_path)
    folder = tmp_path / "models" / "R2011-08-01" / "als"
    assert artifact.path == folder and sorted(p.name for p in folder.iterdir()) == ["artifact.json", "codes.npy", "item_factors.npy", "user_ids.npy"]
    manifest = json.loads((folder / "artifact.json").read_text(encoding="utf-8"))
    assert manifest["version"] == 1 and manifest["params"] == {"factors": 3} and sorted(manifest["files"]) == ["codes.npy", "item_factors.npy", "user_ids.npy"]
    for name, entry in manifest["files"].items():
        assert entry == {"bytes": (folder / name).stat().st_size, "sha256": files.sha256_file(folder / name)}
    assert artifact.sha256 == files.sha256_file(folder / "artifact.json") == artifacts.artifact_sha256(folder)
    assert len(artifact.sha256) == 64


def test_the_same_arrays_give_the_same_bytes_and_the_same_hash(tmp_path):
    first = artifacts.write_component(tmp_path / "a", "R2011-08-01", "als", arrays(), {"factors": 3})
    second = artifacts.write_component(tmp_path / "b", "R2011-08-01", "als", arrays(), {"factors": 3})
    assert first.sha256 == second.sha256
    assert (first.path / "item_factors.npy").read_bytes() == (second.path / "item_factors.npy").read_bytes()
    third = artifacts.write_component(tmp_path / "c", "R2011-08-01", "als", arrays(), {"factors": 4})
    assert third.sha256 != first.sha256, "the parameters are part of what the hash vouches for"


def test_a_component_reads_back_the_arrays_it_was_given_and_its_parameters(tmp_path):
    artifact = written(tmp_path)
    loaded, params = artifacts.read_component(artifact.path, artifact.sha256)
    assert params == {"factors": 3} and set(loaded) == set(arrays())
    for name, expected in arrays().items():
        assert loaded[name].dtype == expected.dtype and np.array_equal(loaded[name], expected), name


def test_an_artifact_with_another_hash_is_refused_before_loading(tmp_path, monkeypatch):
    """M02: the registered hash is checked first; nothing is deserialized when it does not match."""
    artifact = written(tmp_path)
    loaded = []
    monkeypatch.setattr(np, "load", lambda *a, **k: loaded.append(a) or pytest.fail("np.load must not run"))
    with pytest.raises(ArtifactError, match="huella"):
        artifacts.read_component(artifact.path, "0" * 64)
    assert loaded == []


def test_a_changed_array_a_changed_size_or_a_missing_file_is_refused_before_loading(tmp_path, monkeypatch):
    artifact = written(tmp_path)
    target = artifact.path / "item_factors.npy"
    original = target.read_bytes()
    monkeypatch.setattr(np, "load", lambda *a, **k: pytest.fail("np.load must not run"))
    target.write_bytes(original[:-1] + bytes([original[-1] ^ 1]))
    with pytest.raises(ArtifactError, match="item_factors.npy"):
        artifacts.read_component(artifact.path, artifact.sha256)
    target.write_bytes(original + b"\0")
    with pytest.raises(ArtifactError, match="item_factors.npy"):
        artifacts.read_component(artifact.path, artifact.sha256)
    target.unlink()
    with pytest.raises(ArtifactError, match="item_factors.npy"):
        artifacts.read_component(artifact.path, artifact.sha256)


def test_a_file_the_manifest_does_not_list_is_refused_a_pickle_a_npz_or_anything_else(tmp_path, monkeypatch):
    artifact = written(tmp_path)
    monkeypatch.setattr(np, "load", lambda *a, **k: pytest.fail("np.load must not run"))
    for name, data in (("model.pkl", pickle.dumps({"a": 1})), ("model.pickle", b"x"), ("extra.npz", b"PK"), ("notes.txt", b"x"), ("other.npy", b"x")):
        (artifact.path / name).write_bytes(data)
        with pytest.raises(ArtifactError, match=name):
            artifacts.read_component(artifact.path, artifact.sha256)
        (artifact.path / name).unlink()


def test_a_manifest_that_lists_a_pickle_or_a_npz_or_a_path_is_refused_even_with_the_right_hash(tmp_path, monkeypatch):
    """The hash vouches for the manifest, not for what the manifest asks to be read: a listed ``.pkl``, a ``.npz`` and a name that leaves the folder are refused by their names."""
    monkeypatch.setattr(np, "load", lambda *a, **k: pytest.fail("np.load must not run"))
    for name in ("model.pkl", "model.pickle", "factors.npz", "../outside.npy", "sub/inner.npy", "factors.NPY.txt"):
        folder = tmp_path / "evil"
        folder.mkdir(exist_ok=True)
        payload = b"x"
        manifest = {"version": 1, "params": {}, "files": {name: {"bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest()}}}
        (folder / "artifact.json").write_text(json.dumps(manifest), encoding="utf-8")
        with pytest.raises(ArtifactError, match="nombre|npy"):
            artifacts.read_component(folder, files.sha256_file(folder / "artifact.json"))


def test_an_object_array_is_refused_when_written_and_never_loaded_without_pickle(tmp_path):
    with pytest.raises(ArtifactError, match="objeto"):
        artifacts.write_component(tmp_path / "m", "R2011-08-01", "als", {"bad": np.array([{"a": 1}, None], dtype=object)}, {})
    assert not (tmp_path / "m").exists(), "nothing was written"
    # an object array that was written some other way is not read: np.load runs with allow_pickle=False
    artifact = written(tmp_path)
    object_file = artifact.path / "codes.npy"
    with object_file.open("wb") as handle:     # a test writing a hostile file next to the artifact on purpose
        np.save(handle, np.array([{"a": 1}], dtype=object), allow_pickle=True)
    manifest = json.loads((artifact.path / "artifact.json").read_text(encoding="utf-8"))
    manifest["files"]["codes.npy"] = {"bytes": object_file.stat().st_size, "sha256": files.sha256_file(object_file)}
    (artifact.path / "artifact.json").write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ArtifactError, match="pickle|objeto"):
        artifacts.read_component(artifact.path, files.sha256_file(artifact.path / "artifact.json"))


def test_the_arrays_are_read_with_allow_pickle_false(tmp_path, monkeypatch):
    artifact = written(tmp_path)
    seen = []
    original = np.load
    monkeypatch.setattr(np, "load", lambda *a, **k: seen.append(k.get("allow_pickle")) or original(*a, **k))
    artifacts.read_component(artifact.path, artifact.sha256)
    assert seen == [False] * 3


def test_the_names_of_the_round_and_of_the_component_cannot_leave_the_models_folder(tmp_path):
    for round_id, component in (("../R2011-08-01", "als"), ("R2011-08-01", "../als"), ("R2011-08-01", "unknown"), ("2011-08-01", "als"), ("R2011-08-01/x", "als")):
        with pytest.raises(ArtifactError, match="ronda|componente"):
            artifacts.write_component(tmp_path / "models", round_id, component, arrays(), {})
    assert not (tmp_path / "models").exists()


def test_a_failed_write_leaves_no_half_written_artifact(tmp_path, monkeypatch):
    calls = []
    original = files.write_atomic

    def fail_on_the_manifest(path, data):
        calls.append(path.name)
        if path.name == "artifact.json":
            raise OSError("disk full")
        return original(path, data)

    monkeypatch.setattr(artifacts, "write_atomic", fail_on_the_manifest)
    with pytest.raises(OSError, match="disk full"):
        written(tmp_path)
    assert calls[-1] == "artifact.json" and calls.count("artifact.json") == 1, "the manifest is written last"
    with pytest.raises(ArtifactError):
        artifacts.read_component(tmp_path / "models" / "R2011-08-01" / "als", "0" * 64)


def test_a_component_written_again_with_the_same_content_changes_nothing_and_with_other_content_is_refused(tmp_path):
    first = written(tmp_path)
    before = {p.name: p.read_bytes() for p in first.path.iterdir()}
    again = written(tmp_path)
    assert again.sha256 == first.sha256 and {p.name: p.read_bytes() for p in first.path.iterdir()} == before
    other = {**arrays(), "user_ids": np.arange(8, dtype=np.int64)}
    with pytest.raises(ArtifactError, match="ya existe"):
        artifacts.write_component(tmp_path / "models", "R2011-08-01", "als", other, {"factors": 3})
    assert {p.name: p.read_bytes() for p in first.path.iterdir()} == before, "what was registered is not rewritten"
