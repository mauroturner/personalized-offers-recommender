"""The seal and the fingerprint of the sealed configuration (U11, risk item 1: the launch is sealed before the first test round and the seal is written once; RF13, AC16; decision D21): every key
that can change a sealed value changes ``config_sha256``, the keys that cannot do not, the seal's launch part is created exclusively and never rewritten, and the state of a seal against a
configuration is none, match or post-seal."""

from __future__ import annotations

import dataclasses
import json
import threading
from datetime import date, timedelta
from typing import Any

import pytest

from personaloffers import config as cfgmod
from personaloffers import registry
from personaloffers.registry import SealError, SealExistsError, SealMismatchError

LAUNCH = {
    "config_sha256": "", "config": {}, "run_key": "run-1", "as_of": "2011-03-28T00:00:00", "validation": {"rounds": ["R2011-03-14"], "candidates": [], "recipe": "als_8_r0.1_w1", "digest": "e" * 64},
    "recipe": {"model": "als", "size": 8, "regularization": 0.1, "weight": 1.0}, "baselines": {}, "holdout": {"fingerprint": "f" * 64, "sizes": {}, "balance": {}, "max_abs_smd": 0.01},
    "lists": {"round_id": "R2011-03-28", "customers": 3, "rows": 30, "fingerprint": "9" * 64},
}


def launch_part(view) -> dict:
    return {**LAUNCH, "config": registry.view_to_dict(view), "config_sha256": registry.config_fingerprint(view)}


def get(view, dotted: str):
    value = view
    for part in dotted.split("."):
        value = getattr(value, part)
    return value


def put(view, dotted: str, value):
    """`view` with the leaf `dotted` replaced (the sections are frozen dataclasses)."""
    head, *rest = dotted.split(".")
    if not rest:
        return dataclasses.replace(view, **{head: value})
    return dataclasses.replace(view, **{head: put(getattr(view, head), ".".join(rest), value)})


def other_value(value: Any):
    """A different value of the same type."""
    if isinstance(value, bool):
        return not value
    if isinstance(value, int):
        return value + 1
    if isinstance(value, float):
        return value + 0.0125
    if isinstance(value, date):
        return value + timedelta(days=7)
    if isinstance(value, str):
        return ("0" if value[:1] != "0" else "1") + value[1:] if len(value) == 64 and set(value) <= set("0123456789abcdef") else value + "x"
    if isinstance(value, tuple):
        return (*value[:-1], other_value(value[-1])) if value else ("x",)
    raise AssertionError(f"no way to change a {type(value).__name__}")


def test_changing_any_fingerprinted_key_changes_config_sha256(quick_view):
    """AC16: every key of FINGERPRINT_KEYS, and the three hashes of what was read, one by one: the fingerprint of the view is another."""
    base = registry.config_fingerprint(quick_view)
    keys = [key for key in cfgmod.FINGERPRINT_KEYS if not key.startswith("source.")] + [f"source.{name}" for name in ("zip_sha256", "member_sha256", "sheets", "columns")]
    keys += ["zip_sha256_seen", "member_sha256_seen", "lines_sha256_seen"]
    assert len(set(keys)) == len(keys) >= 55
    seen = {base}
    for key in keys:
        changed = put(quick_view, key, other_value(get(quick_view, key)))
        found = registry.config_fingerprint(changed)
        assert found != base, key
        seen.add(found)
    assert len(seen) == len(keys) + 1, "and each change gives its own fingerprint"


def flatten(value: Any, prefix: str = "") -> list[str]:
    if isinstance(value, dict):
        return [name for key, inner in value.items() for name in flatten(inner, f"{prefix}{key}.")]
    return [prefix.rstrip(".")]


def test_the_sealed_dictionary_has_exactly_the_fingerprinted_keys_and_the_observed_hashes(quick_view):
    leaves = set(flatten(registry.view_to_dict(quick_view)))
    assert leaves == set(cfgmod.FINGERPRINT_KEYS) | {"zip_sha256_seen", "member_sha256_seen", "lines_sha256_seen"}


def test_a_key_that_cannot_change_a_sealed_value_does_not_change_the_fingerprint(fixture_cfg):
    """The CRM, the site limit, the paths and the file's own sizes are in UNSEALED_KEYS: the sealed view does not carry them."""
    first = registry.sealed_view(fixture_cfg, {"zip": "a" * 64, "member": "b" * 64, "lines": "c" * 64})
    changed = dataclasses.replace(fixture_cfg, crm=dataclasses.replace(fixture_cfg.crm, batch_size=99, timeout_s=5), site=dataclasses.replace(fixture_cfg.site, max_total_bytes=9999),
                                  paths=dataclasses.replace(fixture_cfg.paths, warehouse=fixture_cfg.paths.warehouse.with_name("other")),
                                  source=dataclasses.replace(fixture_cfg.source, max_rows=1_000_000, zip_path=fixture_cfg.paths.warehouse))
    second = registry.sealed_view(changed, {"zip": "a" * 64, "member": "b" * 64, "lines": "c" * 64})
    assert registry.config_fingerprint(first) == registry.config_fingerprint(second)
    third = registry.sealed_view(fixture_cfg, {"zip": "a" * 64, "member": "b" * 64, "lines": "d" * 64})
    assert registry.config_fingerprint(third) != registry.config_fingerprint(first), "but the lines that were read are part of it"


def test_the_sealed_view_is_the_configuration_with_the_hashes_of_what_was_read(fixture_cfg):
    view = registry.sealed_view(fixture_cfg, {"zip": "a" * 64, "member": "b" * 64, "lines": "c" * 64})
    assert (view.zip_sha256_seen, view.member_sha256_seen, view.lines_sha256_seen) == ("a" * 64, "b" * 64, "c" * 64) and view.calendar == fixture_cfg.calendar
    with pytest.raises(ValueError, match="zip"):
        registry.sealed_view(fixture_cfg, {"member": "b" * 64, "lines": "c" * 64})


def test_the_fingerprint_is_a_sha256_of_a_canonical_text_that_does_not_depend_on_the_order_of_keys(quick_view):
    import hashlib

    text = registry.canonical_json(registry.view_to_dict(quick_view))
    assert registry.config_fingerprint(quick_view) == hashlib.sha256(text.encode("utf-8")).hexdigest() and len(registry.config_fingerprint(quick_view)) == 64
    document = json.loads(text)
    assert registry.canonical_json(dict(reversed(list(document.items())))) == text, "the same document with its keys in another order is the same text"
    assert document["calendar"]["test_first_round"] == "2011-03-28" and document["recommend"]["k"] == 10 and isinstance(document["source"]["sheets"], list)


# --- the seal -------------------------------------------------------------------------------------------------------------------------------------


def test_a_seal_that_is_not_there_has_no_state_and_one_with_the_same_fingerprint_matches(tmp_path, quick_view):
    seal = tmp_path / "reports" / "model_seal.json"
    fingerprint = registry.config_fingerprint(quick_view)
    assert registry.seal_state(seal, fingerprint) == "none" and registry.read_seal(seal) is None
    registry.write_launch_seal(seal, launch_part(quick_view))
    assert registry.seal_state(seal, fingerprint) == "match"
    assert registry.seal_state(seal, "0" * 64) == "post_seal", "another configuration: everything it computes is after the seal (M03)"


def test_the_launch_part_is_written_once_and_never_rewritten(tmp_path, quick_view):
    seal = tmp_path / "model_seal.json"
    part = launch_part(quick_view)
    registry.write_launch_seal(seal, part)
    written = seal.read_bytes()
    document = json.loads(written)
    assert set(document) == {"version", "launch"} and document["version"] == 1 and document["launch"] == part
    assert written.endswith(b"\n") and written == (json.dumps(document, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")
    with pytest.raises(SealExistsError, match="sello"):
        registry.write_launch_seal(seal, part)
    with pytest.raises(SealExistsError):
        registry.write_launch_seal(seal, {**part, "run_key": "run-2"})
    assert seal.read_bytes() == written and [p.name for p in tmp_path.iterdir()] == ["model_seal.json"]


def test_two_writers_of_the_launch_part_leave_one_seal_and_one_error(tmp_path, quick_view):
    seal = tmp_path / "model_seal.json"
    outcomes: list[str] = []
    barrier = threading.Barrier(2)

    def write(run_key: str) -> None:
        barrier.wait()
        try:
            registry.write_launch_seal(seal, {**launch_part(quick_view), "run_key": run_key})
            outcomes.append(run_key)
        except SealExistsError:
            outcomes.append("refused")

    threads = [threading.Thread(target=write, args=(key,)) for key in ("run-a", "run-b")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert outcomes.count("refused") == 1 and len(outcomes) == 2 and json.loads(seal.read_text(encoding="utf-8"))["launch"]["run_key"] in ("run-a", "run-b")


def test_a_launch_part_that_is_not_what_the_seal_needs_is_refused_before_anything_is_written(tmp_path, quick_view):
    seal = tmp_path / "model_seal.json"
    part = launch_part(quick_view)
    for broken in ({k: v for k, v in part.items() if k != "recipe"}, {**part, "config_sha256": "1" * 64}, {**part, "config_sha256": "short"}, {**part, "extra": 1}, {**part, "run_key": ""}):
        with pytest.raises(SealError):
            registry.write_launch_seal(seal, broken)
    assert not seal.exists() and list(tmp_path.iterdir()) == []


def test_a_seal_that_cannot_be_read_is_an_error_and_never_a_missing_seal(tmp_path, quick_view):
    seal = tmp_path / "model_seal.json"
    for content in ("not json", "[]", '{"version": 2, "launch": {}}', '{"version": 1}', '{"version": 1, "launch": []}'):
        seal.write_text(content, encoding="utf-8")
        with pytest.raises(SealError):
            registry.read_seal(seal)
        with pytest.raises(SealError):
            registry.seal_state(seal, registry.config_fingerprint(quick_view))


def test_the_state_reads_the_fingerprint_of_the_launch_and_ignores_a_test_part(tmp_path, quick_view):
    seal = tmp_path / "model_seal.json"
    registry.write_launch_seal(seal, launch_part(quick_view))
    document = json.loads(seal.read_text(encoding="utf-8"))
    document["test"] = {"anything": 1}
    seal.write_text(json.dumps(document), encoding="utf-8")
    assert registry.seal_state(seal, registry.config_fingerprint(quick_view)) == "match" and registry.read_seal(seal)["test"] == {"anything": 1}


def test_checking_a_launch_against_what_was_recomputed_names_each_field_that_differs(quick_view):
    sealed = launch_part(quick_view)
    registry.check_launch(sealed, {"validation_digest": "e" * 64, "recipe": "als_8_r0.1_w1", "holdout_fingerprint": "f" * 64, "lists_fingerprint": "9" * 64})
    with pytest.raises(SealMismatchError) as caught:
        registry.check_launch(sealed, {"validation_digest": "0" * 64, "recipe": "cosine_20_w0", "holdout_fingerprint": "f" * 64, "lists_fingerprint": "8" * 64})
    message = str(caught.value)
    assert "validation_digest" in message and "recipe" in message and "lists_fingerprint" in message and "holdout_fingerprint" not in message and "R7" in message
    with pytest.raises(SealMismatchError, match="unknown"):
        registry.check_launch(sealed, {"unknown": "x"})
