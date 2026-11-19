"""Configuration (U02): paths against the project folder, the seal's two lists of keys, the sources' guarantees, the calendar's rules, the grid's axes and every
key refused by name (RNF05, AC16 in part, AC32, AC33; D05, D14, D21, D35)."""

from __future__ import annotations

import dataclasses
import re
from datetime import date
from pathlib import Path

import pytest

from personaloffers.config import (
    DEFAULT_CONFIG,
    ENV_CONFIG,
    ENV_HOME,
    FINGERPRINT_KEYS,
    INFORMATIVE_KEYS,
    LINE_KEY_SHEET_FACTOR,
    UNSEALED_KEYS,
    PipelineConfig,
    SealedConfig,
    config_leaves,
    load_config,
)

PROJECT = Path(__file__).resolve().parents[2]
ZIP_SHA = "572e36277c2390fbfde10664750731e0a86f55e33470d91919085f0408e67bfb"
MEMBER_SHA = "bcbe73b35f5b7babf197fb0cb983a11f5d9ff929078d4aa53d171b1f2df2e980"
LINES_SHA = "0f" * 32
COLUMNS = ("Invoice", "StockCode", "Description", "Quantity", "InvoiceDate", "Price", "Customer ID", "Country")


@pytest.fixture(scope="module")
def cfg() -> PipelineConfig:
    return load_config(DEFAULT_CONFIG)


def variant(tmp_path: Path, snippet: str = "", replace: tuple[str, str] | None = None, name: str = "pipeline.toml") -> Path:
    """A configuration inside `tmp_path/config/`: the real file with one textual replacement, or an ``extends`` of it plus `snippet`."""
    folder = tmp_path / "config"
    folder.mkdir(exist_ok=True)
    target = folder / name
    if replace is not None:
        text = DEFAULT_CONFIG.read_text(encoding="utf-8")
        assert replace[0] in text, f"{replace[0]!r} is not in the default configuration"
        target.write_text(text.replace(*replace, 1), encoding="utf-8")
    else:
        target.write_text(f'extends = "{DEFAULT_CONFIG.as_posix()}"\n{snippet}', encoding="utf-8")
    return target


def refused(tmp_path: Path, match: str, snippet: str = "", replace: tuple[str, str] | None = None) -> None:
    with pytest.raises(ValueError, match=match):
        load_config(variant(tmp_path, snippet, replace))


# --- the default configuration -------------------------------------------------------------------------------------


def test_default_configuration_has_the_values_of_the_plan(cfg):
    assert isinstance(cfg, PipelineConfig) and cfg.project_root == PROJECT
    s = cfg.source
    assert s.zip_path == PROJECT / "data" / "raw" / "online_retail_ii.zip" and (s.zip_bytes, s.zip_sha256) == (45622418, ZIP_SHA)
    assert (s.member, s.member_bytes, s.member_sha256) == ("online_retail_II.xlsx", 45622278, MEMBER_SHA)
    assert (s.max_part_bytes, s.max_rows) == (400_000_000, 1_200_000)
    assert s.sheets == ("Year 2009-2010", "Year 2010-2011") and s.columns == COLUMNS
    assert (s.first_date, s.last_date) == (date(2009, 12, 1), date(2011, 12, 9))
    assert cfg.catalogue.product_code_regex == r"^\d{5}[A-Za-z]{0,3}$"
    c = cfg.calendar
    assert (c.history_start, c.launch_last_day, c.validation_first_round, c.validation_last_round) == (
        date(2009, 12, 1), date(2011, 7, 31), date(2011, 5, 2), date(2011, 7, 25))
    assert (c.test_first_round, c.test_last_round, c.close_first_day, c.close_last_day, c.window_days) == (
        date(2011, 8, 1), date(2011, 11, 28), date(2011, 12, 5), date(2011, 12, 9), 7)
    assert dataclasses.astuple(cfg.base) == (365, 24, 3)
    h = cfg.holdout
    assert (h.share, h.seed, h.salt, h.recency_bands, h.frequency_bands) == (0.20, 20110801, "personal-offers-holdout-v1", 3, 3)
    r = cfg.recommend
    assert (r.k, r.repeat_slots, r.discovery_slots, r.fallback_days, r.repeat_recency_weight, r.repeat_recency_days) == (10, 7, 3, 28, 0.5, 90)
    g = cfg.grid
    assert (g.als_factors, g.als_regularization, g.als_iterations, g.als_alpha) == ((32, 64, 128), (0.01, 0.1), 15, 20.0)
    assert (g.cosine_k, g.rules_min_invoices, g.rules_min_lift) == ((50, 100, 200), (5, 10, 20), 1.0)
    assert (g.blend_trend_weights, g.blend_trend_days, g.choice_tolerance, g.seed) == ((0.0, 0.5, 1.0, 2.0), 28, 0.005, 0)
    assert len(g.als_factors) * len(g.als_regularization) + len(g.cosine_k) + len(g.rules_min_invoices) == 12   # 12 base models x 4 weights = 48 candidates (D12)
    assert (cfg.evaluation.resamples, cfg.evaluation.seed) == (2000, 0)
    x = cfg.experiment
    assert (x.permutations, x.calibration_seeds, x.calibration_permutations, x.cuped_weeks) == (2000, 500, 500, 18)
    assert (x.alpha, x.mde_power, x.mde_shares) == (0.05, 0.80, (0.10, 0.20, 0.30))
    k = cfg.criteria
    assert (k.c01_min_diff_low, k.c02_min_diff_low, k.c03_min_diff_low, k.c04_min_diff_low) == (0.0, -0.05, 0.0, 0.0)
    assert (k.c05_min_coverage, k.c06_max_abs_smd, k.c07_rejection_band, k.c08_min_p) == (0.10, 0.10, (0.031, 0.069), 0.05)
    m = cfg.crm
    assert (m.mode, m.base_url, m.token_env, m.batch_size, m.timeout_s, m.max_body_bytes) == ("standin", "", "PERSONALOFFERS_CRM_TOKEN", 500, 30, 2_000_000)
    assert cfg.privacy.min_cell_customers == 10 and cfg.site.max_total_bytes == 204800


def test_the_configuration_is_immutable(cfg):
    with pytest.raises(dataclasses.FrozenInstanceError):
        cfg.holdout.share = 0.3  # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        cfg.source.sheets = ()  # type: ignore[misc]


# --- paths (RNF05, AC33) ---------------------------------------------------------------------------------------------


def test_relative_paths_resolve_against_project_root_from_another_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv(ENV_HOME, raising=False)
    monkeypatch.delenv(ENV_CONFIG, raising=False)
    for load in (lambda: load_config(PROJECT / "config" / "pipeline.toml"), lambda: load_config(Path("config") / "pipeline.toml"), load_config):
        cfg = load()
        assert cfg.project_root == PROJECT
        for field in dataclasses.fields(cfg.paths):
            path = getattr(cfg.paths, field.name)
            assert path.is_absolute() and PROJECT in path.parents, field.name
        assert cfg.source.zip_path.is_absolute() and PROJECT in cfg.source.zip_path.parents
        assert cfg.paths.warehouse == PROJECT / "data" / "warehouse" / "personaloffers.sqlite"
        assert cfg.paths.crm_db == PROJECT / "data" / "crm" / "standin.sqlite"
        assert cfg.paths.private_dir == PROJECT / "outputs" / "private"
        assert cfg.paths.seal == PROJECT / "reports" / "model_seal.json"
    # the working directory holds another copy's configuration: it is never read in silence
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "pipeline.toml").write_text("this is not the project's configuration", encoding="utf-8")
    assert load_config(Path("config") / "pipeline.toml").project_root == PROJECT


def test_a_relative_personaloffers_config_is_taken_from_the_project_folder(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv(ENV_HOME, raising=False)
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "pipeline.quick.toml").write_text("[evaluation]\nresamples = 999\n", encoding="utf-8")
    monkeypatch.setenv(ENV_CONFIG, "config/pipeline.quick.toml")
    cfg = load_config()
    assert cfg.evaluation.resamples == 200 and cfg.paths.warehouse == PROJECT / "data" / "quick" / "personaloffers.sqlite"


def test_personaloffers_home_moves_the_project_folder_and_must_exist(tmp_path, monkeypatch):
    home = tmp_path / "elsewhere"
    (home / "config").mkdir(parents=True)
    (home / "config" / "pipeline.toml").write_text(DEFAULT_CONFIG.read_text(encoding="utf-8"), encoding="utf-8")
    monkeypatch.setenv(ENV_HOME, str(home))
    assert load_config(DEFAULT_CONFIG).paths.warehouse == home.resolve() / "data" / "warehouse" / "personaloffers.sqlite"
    assert load_config(DEFAULT_CONFIG).source.zip_path == home.resolve() / "data" / "raw" / "online_retail_ii.zip"
    monkeypatch.setenv(ENV_CONFIG, "config/pipeline.toml")
    assert load_config().project_root == home.resolve()
    monkeypatch.setenv(ENV_HOME, str(tmp_path / "does-not-exist"))
    with pytest.raises(ValueError, match=ENV_HOME):
        load_config(DEFAULT_CONFIG)


def test_quick_configuration_keeps_every_path_under_data_quick_and_changes_only_what_the_fixture_needs(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv(ENV_HOME, raising=False)
    monkeypatch.delenv(ENV_CONFIG, raising=False)
    cfg = load_config(PROJECT / "config" / "pipeline.quick.toml")
    default = load_config(DEFAULT_CONFIG)
    quick = PROJECT / "data" / "quick"
    assert cfg.source.zip_path == quick / "online_retail_fixture.zip"
    assert (cfg.source.zip_bytes, cfg.source.zip_sha256, cfg.source.member_bytes, cfg.source.member_sha256) == (0, "", 0, "")
    assert (cfg.source.first_date, cfg.source.last_date) == (date(2010, 12, 6), date(2011, 4, 22))
    assert dataclasses.replace(cfg.source, zip_path=default.source.zip_path, zip_bytes=default.source.zip_bytes, zip_sha256=default.source.zip_sha256,
                               member_bytes=default.source.member_bytes, member_sha256=default.source.member_sha256, first_date=default.source.first_date,
                               last_date=default.source.last_date) == default.source
    for field in dataclasses.fields(cfg.paths):
        assert quick in getattr(cfg.paths, field.name).parents, field.name
    c = cfg.calendar
    assert (c.history_start, c.launch_last_day, c.validation_first_round, c.validation_last_round) == (
        date(2010, 12, 6), date(2011, 3, 27), date(2011, 3, 14), date(2011, 3, 21))
    assert (c.test_first_round, c.test_last_round, c.close_first_day, c.close_last_day) == (date(2011, 3, 28), date(2011, 4, 11), date(2011, 4, 18), date(2011, 4, 22))
    assert c.window_days == 7
    g = cfg.grid
    assert (g.als_factors, g.als_regularization, g.cosine_k, g.rules_min_invoices, g.blend_trend_weights) == ((8,), (0.1,), (20,), (3,), (0.0, 1.0))
    assert dataclasses.replace(g, als_factors=default.grid.als_factors, als_regularization=default.grid.als_regularization, cosine_k=default.grid.cosine_k,
                               rules_min_invoices=default.grid.rules_min_invoices, blend_trend_weights=default.grid.blend_trend_weights) == default.grid
    assert cfg.evaluation.resamples == 200 and cfg.evaluation.seed == default.evaluation.seed
    x = cfg.experiment
    assert (x.permutations, x.calibration_seeds, x.calibration_permutations, x.cuped_weeks) == (200, 40, 100, 3)
    assert dataclasses.replace(x, permutations=2000, calibration_seeds=500, calibration_permutations=500, cuped_weeks=18) == default.experiment
    assert (cfg.catalogue, cfg.base, cfg.holdout, cfg.recommend, cfg.criteria, cfg.crm, cfg.privacy, cfg.site) == (
        default.catalogue, default.base, default.holdout, default.recommend, default.criteria, default.crm, default.privacy, default.site)


def test_the_compose_configuration_only_moves_the_crm_to_http(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    cfg = load_config(PROJECT / "config" / "pipeline.docker.toml")
    default = load_config(DEFAULT_CONFIG)
    assert (cfg.crm.mode, cfg.crm.base_url) == ("http", "http://crm:8001")
    assert dataclasses.replace(cfg, crm=default.crm) == default


def test_a_relative_path_cannot_leave_the_project_folder(tmp_path):
    refused(tmp_path, r"\[paths\] raw_dir.*sale de la carpeta del proyecto", replace=('raw_dir = "data/raw"', 'raw_dir = "../elsewhere"'))
    refused(tmp_path, r"\[paths\] seal.*sale de la carpeta", replace=('seal = "reports/model_seal.json"', 'seal = "data/../../x.json"'))
    refused(tmp_path, r"\[source\] zip_path.*sale de la carpeta", snippet='[source]\nzip_path = "../x.zip"\n')


def test_a_dotdot_that_stays_inside_the_project_is_normalised_and_an_absolute_path_is_kept(tmp_path):
    path = variant(tmp_path, replace=('raw_dir = "data/raw"', 'raw_dir = "data/quick/../raw"'))
    assert load_config(path).paths.raw_dir == tmp_path / "data" / "raw"
    outside = (tmp_path / "outside").as_posix()
    path = variant(tmp_path, replace=('raw_dir = "data/raw"', f'raw_dir = "{outside}"'))
    assert load_config(path).paths.raw_dir == Path(outside)


def test_an_empty_path_is_refused(tmp_path):
    refused(tmp_path, r"\[paths\] figures_dir.*texto vacío", replace=('figures_dir = "docs/figures"', 'figures_dir = ""'))


# --- the seal's keys (D21, AC16) -----------------------------------------------------------------------------------


def test_every_config_key_is_fingerprinted_or_declared_unsealed():
    leaves = [leaf for leaf in config_leaves(PipelineConfig) if leaf != "project_root"]
    assert len(leaves) == len(set(leaves)) and len(leaves) > 80
    fingerprinted, unsealed = set(FINGERPRINT_KEYS), set(UNSEALED_KEYS)
    assert len(FINGERPRINT_KEYS) == len(fingerprinted) and len(UNSEALED_KEYS) == len(unsealed), "a key is listed twice"
    assert fingerprinted & unsealed == set(), "a key is both fingerprinted and declared unsealed"
    assert sorted(set(leaves) - fingerprinted - unsealed) == [], "a key is neither fingerprinted nor declared unsealed"
    assert sorted((fingerprinted | unsealed) - set(leaves)) == [], "a listed key is not in the configuration"
    # the plan, section 4: four keys of [source] enter; every key of the sections that make a sealed value does too
    for section in ("catalogue", "calendar", "base", "holdout", "recommend", "grid", "evaluation", "experiment", "criteria", "privacy"):
        assert {leaf for leaf in leaves if leaf.startswith(f"{section}.")} <= fingerprinted, section
    assert {leaf for leaf in fingerprinted if leaf.startswith("source.")} == {"source.zip_sha256", "source.member_sha256", "source.sheets", "source.columns"}
    assert {leaf for leaf in leaves if leaf.startswith(("crm.", "site.", "paths."))} <= unsealed
    assert {"source.zip_path", "source.zip_bytes", "source.member", "source.member_bytes", "source.max_part_bytes", "source.max_rows", "source.first_date",
            "source.last_date"} <= unsealed
    assert set(INFORMATIVE_KEYS) <= set(leaves), "a key declared informative is not in the configuration"


def test_the_sealed_view_holds_exactly_the_fingerprinted_keys_and_the_observed_hashes(cfg):
    assert set(config_leaves(SealedConfig)) == set(FINGERPRINT_KEYS) | {"zip_sha256_seen", "member_sha256_seen", "lines_sha256_seen"}
    view = SealedConfig.of(cfg, ZIP_SHA, MEMBER_SHA, LINES_SHA)
    for key in FINGERPRINT_KEYS:
        found, original = view, cfg
        for part in key.split("."):
            found, original = getattr(found, part), getattr(original, part)
        assert found == original, key
    assert (view.zip_sha256_seen, view.member_sha256_seen, view.lines_sha256_seen) == (ZIP_SHA, MEMBER_SHA, LINES_SHA)
    assert not any(hasattr(view, name) for name in ("paths", "site", "crm")) and not hasattr(view.source, "zip_path") and not hasattr(view.source, "max_rows")
    for index, name in enumerate(("zip_sha256_seen", "member_sha256_seen", "lines_sha256_seen")):
        for bad in (ZIP_SHA.upper(), ZIP_SHA[:-1], "", " " + ZIP_SHA):
            hashes = [ZIP_SHA, MEMBER_SHA, LINES_SHA]
            hashes[index] = bad
            with pytest.raises(ValueError, match=name):
                SealedConfig.of(cfg, *hashes)


# --- the sources (RF01, V01, V02, V06) -----------------------------------------------------------------------------


@pytest.mark.parametrize(("snippet", "match"), [
    ('[source]\nzip_sha256 = ""\n', r"\[source\] zip_sha256.*data/quick"),
    ('[source]\nzip_bytes = 0\n', r"\[source\] zip_bytes.*mayor que 0"),
    ('[source]\nmember_sha256 = ""\n', r"\[source\] member_sha256.*data/quick"),
    ('[source]\nmember_bytes = 0\n', r"\[source\] member_bytes.*mayor que 0"),
    ('[source]\nzip_bytes = -1\n', r"\[source\] zip_bytes"),
    ('[source]\nzip_sha256 = "' + ZIP_SHA.upper() + '"\n', r"\[source\] zip_sha256.*64 caracteres"),
    ('[source]\nzip_sha256 = "' + ZIP_SHA[:-1] + '"\n', r"\[source\] zip_sha256.*64 caracteres"),
    ('[source]\nmember_sha256 = "' + "z" * 64 + '"\n', r"\[source\] member_sha256.*64 caracteres"),
    ('[source]\nmember = ""\n', r"\[source\] member.*\.xlsx"),
    ('[source]\nmember = "sub/book.xlsx"\n', r"\[source\] member"),
    ('[source]\nmember = "sub\\\\book.xlsx"\n', r"\[source\] member"),
    ('[source]\nmember = ".."\n', r"\[source\] member"),
    ('[source]\nmember = "book.csv"\n', r"\[source\] member.*\.xlsx"),
    ("[source]\nmax_part_bytes = 0\n", r"\[source\] max_part_bytes"),
    ("[source]\nmax_rows = 0\n", r"\[source\] max_rows"),
    (f"[source]\nmax_rows = {LINE_KEY_SHEET_FACTOR}\n", r"\[source\] max_rows.*10000000"),
    ('[source]\nsheets = ["Year 2009-2010"]\n', r"\[source\] sheets.*2 nombres"),
    ('[source]\nsheets = ["Year 2009-2010", "Year 2009-2010"]\n', r"\[source\] sheets.*repetidos"),
    ('[source]\nsheets = ["Year 2009-2010", ""]\n', r"\[source\] sheets"),
    ('[source]\nsheets = ["Year 2009-2010", "Year 2010-2011", "Extra"]\n', r"\[source\] sheets.*2 nombres"),
    ('[source]\ncolumns = ["Invoice"]\n', r"\[source\] columns.*8 nombres"),
    ('[source]\ncolumns = ["Invoice", "Invoice", "Description", "Quantity", "InvoiceDate", "Price", "Customer ID", "Country"]\n', r"\[source\] columns.*repetidos"),
    ('[source]\ncolumns = ["Invoice", " StockCode", "Description", "Quantity", "InvoiceDate", "Price", "Customer ID", "Country"]\n', r"\[source\] columns"),
    ("[source]\nfirst_date = 2011-12-09\n", r"\[source\] last_date.*first_date"),
    ('[source]\nfirst_date = "2009-12-01"\n', r"\[source\] first_date.*una fecha"),
    ("[source]\nlast_date = 2011-12-09T10:00:00\n", r"\[source\] last_date.*una fecha"),
])
def test_the_source_is_checked_key_by_key(tmp_path, snippet, match):
    refused(tmp_path, match, snippet=snippet)


def test_an_empty_accepted_hash_is_allowed_only_for_a_zip_under_data_quick(tmp_path):
    empty = '[source]\nzip_sha256 = ""\nzip_bytes = 0\nmember_sha256 = ""\nmember_bytes = 0\n'
    refused(tmp_path, r"\[source\] zip_sha256.*data/quick", snippet=empty)
    refused(tmp_path, r"\[source\] zip_sha256.*data/quick", snippet=empty + 'zip_path = "data/quick_not/x.zip"\n')
    quick = tmp_path / "data" / "quick" / "x.zip"
    assert load_config(variant(tmp_path, snippet=empty + f'zip_path = "{quick.as_posix()}"\n')).source.zip_sha256 == ""
    assert load_config(variant(tmp_path, snippet=empty + 'zip_path = "data/quick/x.zip"\n')).source.zip_path == quick
    # the other way round: an accepted hash with an empty size, or a size with an empty hash, never goes together; the workbook's pair follows the zip's place
    refused(tmp_path, r"\[source\] zip_bytes.*0", snippet='[source]\nzip_sha256 = ""\nzip_bytes = 5\nzip_path = "data/quick/x.zip"\nmember_sha256 = ""\nmember_bytes = 0\n')
    refused(tmp_path, r"\[source\] member_bytes.*0", snippet='[source]\nzip_sha256 = ""\nzip_bytes = 0\nzip_path = "data/quick/x.zip"\nmember_sha256 = ""\nmember_bytes = 7\n')
    refused(tmp_path, r"\[source\] member_sha256.*data/quick", snippet='[source]\nmember_sha256 = ""\nmember_bytes = 0\n')


# --- the catalogue (D04) ----------------------------------------------------------------------------------------------


@pytest.mark.parametrize(("snippet", "match"), [
    ("[catalogue]\nproduct_code_regex = '('\n", r"\[catalogue\] product_code_regex.*expresión regular"),
    ("[catalogue]\nproduct_code_regex = ''\n", r"\[catalogue\] product_code_regex.*vacío"),
    ("[catalogue]\nproduct_code_regex = '\\d*'\n", r"\[catalogue\] product_code_regex.*vacío"),
    ("[catalogue]\nproduct_code_regex = 5\n", r"\[catalogue\] product_code_regex.*un texto"),
])
def test_the_product_code_regular_expression_is_checked(tmp_path, snippet, match):
    refused(tmp_path, match, snippet=snippet)


# --- the calendar (D05, D23) -------------------------------------------------------------------------------------------


@pytest.mark.parametrize(("snippet", "match"), [
    ("[calendar]\nvalidation_first_round = 2011-05-03\n", r"\[calendar\] validation_first_round.*lunes.*martes"),
    ("[calendar]\nvalidation_last_round = 2011-07-24\n", r"\[calendar\] validation_last_round.*lunes.*domingo"),
    ("[calendar]\ntest_first_round = 2011-08-02\n", r"\[calendar\] test_first_round.*lunes"),
    ("[calendar]\ntest_last_round = 2011-11-29\n", r"\[calendar\] test_last_round.*lunes"),
    ("[calendar]\nclose_first_day = 2011-12-06\n", r"\[calendar\] close_first_day.*lunes"),
    ("[calendar]\nvalidation_last_round = 2011-08-01\n", r"\[calendar\] validation_last_round.*termina después de test_first_round"),
    ("[calendar]\nvalidation_last_round = 2011-08-08\nvalidation_first_round = 2011-08-01\n", r"\[calendar\] validation_last_round.*termina después de test_first_round"),
    ("[calendar]\nvalidation_first_round = 2011-07-25\nvalidation_last_round = 2011-07-18\n", r"\[calendar\] validation_last_round.*validation_first_round"),
    ("[calendar]\nlaunch_last_day = 2011-07-30\n", r"\[calendar\] test_first_round.*día siguiente a launch_last_day"),
    ("[calendar]\nlaunch_last_day = 2011-08-01\n", r"\[calendar\] test_first_round.*día siguiente a launch_last_day"),
    ("[calendar]\ntest_first_round = 2011-12-12\n", r"\[calendar\] test_first_round"),
    ("[calendar]\ntest_last_round = 2011-07-25\n", r"\[calendar\] test_last_round.*test_first_round|\[calendar\] close_first_day"),
    ("[calendar]\nclose_first_day = 2011-12-12\nclose_last_day = 2011-12-16\n", r"\[calendar\] close_first_day.*semana siguiente a test_last_round"),
    ("[calendar]\nclose_last_day = 2011-12-12\n", r"\[calendar\] close_last_day.*semana de close_first_day"),
    ("[calendar]\nclose_last_day = 2011-12-02\n", r"\[calendar\] close_last_day.*semana de close_first_day"),
    ("[calendar]\nwindow_days = 0\n", r"\[calendar\] window_days.*1 a 7"),
    ("[calendar]\nwindow_days = 8\n", r"\[calendar\] window_days.*1 a 7"),
    ("[calendar]\nhistory_start = 2011-05-02\n", r"\[calendar\] validation_first_round.*history_start"),
    ("[calendar]\nhistory_start = 2009-11-30\n", r"\[calendar\] history_start.*first_date"),
    ("[source]\nlast_date = 2011-12-08\n", r"\[calendar\] close_last_day.*last_date"),
    ('[calendar]\nhistory_start = "2009-12-01"\n', r"\[calendar\] history_start.*una fecha"),
    ("[calendar]\nwindow_days = 7.0\n", r"\[calendar\] window_days.*un entero"),
])
def test_the_calendar_is_checked_with_the_name_of_the_boundary(tmp_path, snippet, match):
    refused(tmp_path, match, snippet=snippet)


def test_a_shorter_window_and_a_close_that_is_one_day_are_accepted(tmp_path):
    cfg = load_config(variant(tmp_path, snippet="[calendar]\nwindow_days = 1\nclose_last_day = 2011-12-05\n"))
    assert cfg.calendar.window_days == 1 and cfg.calendar.close_last_day == cfg.calendar.close_first_day


def test_the_validation_may_end_exactly_when_the_test_begins(cfg):
    """R2011-07-25's window [07-25, 08-01) ends the day the first test round starts: the plan's own calendar, and the edge of the rule (D23)."""
    c = cfg.calendar
    assert (c.test_first_round - c.validation_last_round).days == c.window_days


# --- the base, the control group and the list (D06, D07, D10, D14) -----------------------------------------------------


@pytest.mark.parametrize(("snippet", "match"), [
    ("[base]\nlookback_days = 0\n", r"\[base\] lookback_days"),
    ("[base]\nbulk_min_median_qty = 0\n", r"\[base\] bulk_min_median_qty"),
    ("[base]\nbulk_min_lines = 0\n", r"\[base\] bulk_min_lines"),
    ("[holdout]\nshare = 0.0\n", r"\[holdout\] share.*0,5"),
    ("[holdout]\nshare = 0.51\n", r"\[holdout\] share.*0,5"),
    ("[holdout]\nshare = -0.2\n", r"\[holdout\] share"),
    ('[holdout]\nshare = "0.2"\n', r"\[holdout\] share.*un número"),
    ("[holdout]\nseed = -1\n", r"\[holdout\] seed"),
    ("[holdout]\nseed = 4294967296\n", r"\[holdout\] seed"),
    ('[holdout]\nsalt = ""\n', r"\[holdout\] salt"),
    ('[holdout]\nsalt = " x"\n', r"\[holdout\] salt"),
    ("[holdout]\nrecency_bands = 0\n", r"\[holdout\] recency_bands"),
    ("[holdout]\nfrequency_bands = 0\n", r"\[holdout\] frequency_bands"),
    ("[recommend]\nk = 0\n", r"\[recommend\] k"),
    ("[recommend]\nrepeat_slots = 6\n", r"\[recommend\] discovery_slots.*k \(10\).*6 \+ 3"),
    ("[recommend]\ndiscovery_slots = 4\n", r"\[recommend\] discovery_slots.*k \(10\).*7 \+ 4"),
    ("[recommend]\nrepeat_slots = -1\ndiscovery_slots = 11\n", r"\[recommend\] repeat_slots"),
    ("[recommend]\nrepeat_slots = 11\ndiscovery_slots = -1\n", r"\[recommend\] discovery_slots"),
    ("[recommend]\nfallback_days = 0\n", r"\[recommend\] fallback_days"),
    ("[recommend]\nrepeat_recency_days = 0\n", r"\[recommend\] repeat_recency_days"),
    ("[recommend]\nrepeat_recency_weight = -0.1\n", r"\[recommend\] repeat_recency_weight"),
])
def test_the_base_the_control_group_and_the_list_are_checked(tmp_path, snippet, match):
    refused(tmp_path, match, snippet=snippet)


def test_the_edges_of_the_control_group_and_the_list_are_accepted(tmp_path):
    ok = ('[holdout]\nshare = 0.5\nseed = 4294967295\nrecency_bands = 1\nfrequency_bands = 1\n[recommend]\nk = 5\nrepeat_slots = 5\ndiscovery_slots = 0\n'
          'repeat_recency_weight = 0.0\n')
    cfg = load_config(variant(tmp_path, snippet=ok))
    assert cfg.holdout.share == 0.5 and cfg.recommend.discovery_slots == 0 and cfg.recommend.repeat_recency_weight == 0.0


# --- the grid (D12) ---------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(("snippet", "match"), [
    ("[grid]\nals_factors = []\n", r"\[grid\] als_factors.*lista no vacía"),
    ("[grid]\nals_factors = [32, 32]\n", r"\[grid\] als_factors.*repetidos"),
    ("[grid]\nals_factors = [0]\n", r"\[grid\] als_factors"),
    ("[grid]\nals_regularization = []\n", r"\[grid\] als_regularization"),
    ("[grid]\nals_regularization = [0.0]\n", r"\[grid\] als_regularization"),
    ("[grid]\ncosine_k = []\n", r"\[grid\] cosine_k"),
    ("[grid]\ncosine_k = [0, 50]\n", r"\[grid\] cosine_k"),
    ("[grid]\nrules_min_invoices = []\n", r"\[grid\] rules_min_invoices"),
    ("[grid]\nrules_min_invoices = [5, 5]\n", r"\[grid\] rules_min_invoices.*repetidos"),
    ("[grid]\nblend_trend_weights = []\n", r"\[grid\] blend_trend_weights"),
    ("[grid]\nblend_trend_weights = [0.5, 1.0]\n", r"\[grid\] blend_trend_weights.*peso 0"),
    ("[grid]\nblend_trend_weights = [0.0, -1.0]\n", r"\[grid\] blend_trend_weights"),
    ("[grid]\nblend_trend_weights = [0.0, 0.0]\n", r"\[grid\] blend_trend_weights.*repetidos"),
    ("[grid]\nals_iterations = 0\n", r"\[grid\] als_iterations"),
    ("[grid]\nals_alpha = 0.0\n", r"\[grid\] als_alpha"),
    ("[grid]\nrules_min_lift = -1.0\n", r"\[grid\] rules_min_lift"),
    ("[grid]\nblend_trend_days = 0\n", r"\[grid\] blend_trend_days"),
    ("[grid]\nchoice_tolerance = -0.001\n", r"\[grid\] choice_tolerance"),
    ("[grid]\nchoice_tolerance = 1.0\n", r"\[grid\] choice_tolerance"),
    ("[grid]\nseed = -1\n", r"\[grid\] seed"),
    ("[grid]\nals_factors = 32\n", r"\[grid\] als_factors.*una lista"),
    ('[grid]\nals_factors = ["32"]\n', r"\[grid\] als_factors.*un entero"),
    ("[grid]\nals_factors = [32.5]\n", r"\[grid\] als_factors.*un entero"),
])
def test_the_grid_axes_are_checked_with_the_name_of_the_axis(tmp_path, snippet, match):
    refused(tmp_path, match, snippet=snippet)


def test_an_integer_is_accepted_where_the_grid_wants_a_number(tmp_path):
    cfg = load_config(variant(tmp_path, snippet="[grid]\nals_regularization = [1, 0.5]\nblend_trend_weights = [0, 1]\nchoice_tolerance = 0\n"))
    assert cfg.grid.als_regularization == (1.0, 0.5) and cfg.grid.blend_trend_weights == (0.0, 1.0) and cfg.grid.choice_tolerance == 0.0
    assert all(type(value) is float for value in cfg.grid.als_regularization + cfg.grid.blend_trend_weights)


# --- the evaluation, the experiment and the criteria (D15, D19, D20) ----------------------------------------------------


@pytest.mark.parametrize(("snippet", "match"), [
    ("[evaluation]\nresamples = 0\n", r"\[evaluation\] resamples"),
    ("[evaluation]\nseed = -1\n", r"\[evaluation\] seed"),
    ("[experiment]\npermutations = 0\n", r"\[experiment\] permutations"),
    ("[experiment]\ncalibration_seeds = 0\n", r"\[experiment\] calibration_seeds"),
    ("[experiment]\ncalibration_permutations = 0\n", r"\[experiment\] calibration_permutations"),
    ("[experiment]\ncuped_weeks = 0\n", r"\[experiment\] cuped_weeks"),
    ("[experiment]\ncuped_weeks = 17\n", r"\[experiment\] cuped_weeks.*18.*17"),
    ("[experiment]\ncuped_weeks = 19\n", r"\[experiment\] cuped_weeks.*18.*19"),
    ("[experiment]\nalpha = 0.0\n", r"\[experiment\] alpha"),
    ("[experiment]\nalpha = 1.0\n", r"\[experiment\] alpha"),
    ("[experiment]\nmde_power = 1.0\n", r"\[experiment\] mde_power"),
    ("[experiment]\nmde_power = 0.0\n", r"\[experiment\] mde_power"),
    ("[experiment]\nmde_shares = []\n", r"\[experiment\] mde_shares"),
    ("[experiment]\nmde_shares = [0.1, 0.1]\n", r"\[experiment\] mde_shares.*repetidos"),
    ("[experiment]\nmde_shares = [0.1, 1.0]\n", r"\[experiment\] mde_shares"),
    ("[criteria]\nc01_min_diff_low = 1.5\n", r"\[criteria\] c01_min_diff_low"),
    ("[criteria]\nc02_min_diff_low = -1.5\n", r"\[criteria\] c02_min_diff_low"),
    ("[criteria]\nc03_min_diff_low = 2.0\n", r"\[criteria\] c03_min_diff_low"),
    ("[criteria]\nc04_min_diff_low = -2.0\n", r"\[criteria\] c04_min_diff_low"),
    ("[criteria]\nc05_min_coverage = 1.5\n", r"\[criteria\] c05_min_coverage"),
    ("[criteria]\nc05_min_coverage = -0.1\n", r"\[criteria\] c05_min_coverage"),
    ("[criteria]\nc06_max_abs_smd = 0.0\n", r"\[criteria\] c06_max_abs_smd"),
    ("[criteria]\nc07_rejection_band = [0.069, 0.031]\n", r"\[criteria\] c07_rejection_band.*creciente"),
    ("[criteria]\nc07_rejection_band = [0.05, 0.05]\n", r"\[criteria\] c07_rejection_band.*creciente"),
    ("[criteria]\nc07_rejection_band = [0.031]\n", r"\[criteria\] c07_rejection_band.*dos números"),
    ("[criteria]\nc07_rejection_band = [0.0, 0.5, 1.0]\n", r"\[criteria\] c07_rejection_band.*dos números"),
    ("[criteria]\nc07_rejection_band = [-0.1, 0.5]\n", r"\[criteria\] c07_rejection_band"),
    ("[criteria]\nc07_rejection_band = [0.1, 1.5]\n", r"\[criteria\] c07_rejection_band"),
    ("[criteria]\nc08_min_p = 0.0\n", r"\[criteria\] c08_min_p"),
    ("[criteria]\nc08_min_p = 1.0\n", r"\[criteria\] c08_min_p"),
])
def test_the_evaluation_the_experiment_and_the_criteria_are_checked(tmp_path, snippet, match):
    refused(tmp_path, match, snippet=snippet)


def test_the_cuped_period_must_fit_in_the_history(tmp_path):
    shorter = "[calendar]\nhistory_start = 2011-05-01\nvalidation_first_round = 2011-05-02\n[experiment]\ncuped_weeks = 18\n"
    refused(tmp_path, r"\[experiment\] cuped_weeks.*no caben en la historia", snippet=shorter)


def test_the_edges_of_the_experiment_and_the_criteria_are_accepted(tmp_path):
    ok = ('[experiment]\nalpha = 0.999\nmde_power = 0.001\nmde_shares = [0.999]\n[criteria]\nc01_min_diff_low = -1.0\nc02_min_diff_low = 1.0\n'
          'c05_min_coverage = 0.0\nc07_rejection_band = [0.0, 1.0]\nc08_min_p = 0.999\n')
    cfg = load_config(variant(tmp_path, snippet=ok))
    assert cfg.criteria.c07_rejection_band == (0.0, 1.0) and cfg.experiment.mde_shares == (0.999,) and cfg.criteria.c05_min_coverage == 0.0


# --- the CRM, privacy and the site ---------------------------------------------------------------------------------------


@pytest.mark.parametrize(("snippet", "match"), [
    ('[crm]\nmode = "hubspot"\n', r"\[crm\] mode.*hubspot"),
    ('[crm]\nmode = "http"\n', r"\[crm\] base_url.*http"),
    ('[crm]\nmode = "http"\nbase_url = "ftp://crm"\n', r"\[crm\] base_url.*http"),
    ('[crm]\nmode = "http"\nbase_url = "http://"\n', r"\[crm\] base_url.*http"),
    ('[crm]\ntoken_env = "my token"\n', r"\[crm\] token_env"),
    ('[crm]\ntoken_env = ""\n', r"\[crm\] token_env"),
    ("[crm]\nbatch_size = 0\n", r"\[crm\] batch_size"),
    ("[crm]\ntimeout_s = 0\n", r"\[crm\] timeout_s"),
    ("[crm]\nmax_body_bytes = 0\n", r"\[crm\] max_body_bytes"),
    ("[privacy]\nmin_cell_customers = 0\n", r"\[privacy\] min_cell_customers"),
    ("[site]\nmax_total_bytes = 0\n", r"\[site\] max_total_bytes"),
])
def test_the_crm_privacy_and_site_keys_are_checked(tmp_path, snippet, match):
    refused(tmp_path, match, snippet=snippet)


def test_the_http_crm_is_accepted_with_an_address_and_the_standin_without_one(tmp_path):
    cfg = load_config(variant(tmp_path, snippet='[crm]\nmode = "http"\nbase_url = "http://crm.internal:8001/api"\n'))
    assert (cfg.crm.mode, cfg.crm.base_url) == ("http", "http://crm.internal:8001/api")
    assert load_config(variant(tmp_path, snippet='[crm]\nbase_url = "not checked while the stand-in is in process"\n')).crm.mode == "standin"


# --- mistakes in the file are named (AC32) -----------------------------------------------------------------------------


def test_unknown_key_is_rejected_with_its_name(tmp_path):
    refused(tmp_path, r"\[holdout\].*'shares'", snippet="[holdout]\nshares = 0.2\n")
    refused(tmp_path, r"\[evaluation\].*'resample'", snippet="[evaluation]\nresample = 500\n")
    refused(tmp_path, r"\[site\].*'cors'", snippet='[site]\ncors = "*"\n')
    refused(tmp_path, r"\[paths\].*'raw'", snippet='[paths]\nraw = "data/raw"\n')


def test_unknown_section_missing_section_and_missing_key_are_named(tmp_path):
    refused(tmp_path, r"sección desconocida \[extras\]", snippet="[extras]\nx = 1\n")
    text = DEFAULT_CONFIG.read_text(encoding="utf-8")
    without_site = re.sub(r"\[site\].*?(?=\[paths\])", "", text, flags=re.S)
    (tmp_path / "config").mkdir(exist_ok=True)
    (tmp_path / "config" / "a.toml").write_text(without_site, encoding="utf-8")
    with pytest.raises(ValueError, match=r"falta la sección \[site\]"):
        load_config(tmp_path / "config" / "a.toml")
    refused(tmp_path, r"\[evaluation\]: falta la clave 'resamples'", replace=("resamples = 2000", ""))
    refused(tmp_path, r"\[source\]: falta la clave 'member'", replace=('member = "online_retail_II.xlsx"', ""))


@pytest.mark.parametrize(("snippet", "match"), [
    ('[holdout]\nshare = "0.2"\n', r"\[holdout\] share.*un número"),
    ("[holdout]\nseed = 1.5\n", r"\[holdout\] seed.*un entero"),
    ("[holdout]\nseed = true\n", r"\[holdout\] seed.*un entero"),
    ("[holdout]\nsalt = 3\n", r"\[holdout\] salt.*un texto"),
    ("[evaluation]\nresamples = 2000.5\n", r"\[evaluation\] resamples.*un entero"),
    ("[evaluation]\nresamples = true\n", r"\[evaluation\] resamples.*un entero"),
    ("[criteria]\nc07_rejection_band = 0.5\n", r"\[criteria\] c07_rejection_band.*una lista"),
    ('[criteria]\nc07_rejection_band = ["a", "b"]\n', r"\[criteria\] c07_rejection_band.*un número"),
    ("[experiment]\nmde_shares = 0.2\n", r"\[experiment\] mde_shares.*una lista"),
    ("[calendar]\ntest_last_round = 2011-11-28T00:00:00\n", r"\[calendar\] test_last_round.*una fecha"),
    ("[paths]\nraw_dir = 3\n", r"\[paths\] raw_dir.*ruta"),
    ("[source]\nzip_path = 3\n", r"\[source\] zip_path.*ruta"),
    ("[source]\nsheets = 3\n", r"\[source\] sheets.*una lista"),
    ("[source]\nsheets = [3, 4]\n", r"\[source\] sheets.*un texto"),
])
def test_a_value_of_the_wrong_type_is_named(tmp_path, snippet, match):
    refused(tmp_path, match, snippet=snippet)


def test_an_empty_table_over_the_base_changes_nothing(tmp_path):
    assert load_config(variant(tmp_path, snippet="[holdout]\n")) == load_config(variant(tmp_path, snippet=""))


def test_extends_cycle_and_missing_base_are_refused(tmp_path):
    folder = tmp_path / "config"
    folder.mkdir()
    (folder / "a.toml").write_text('extends = "b.toml"\n', encoding="utf-8")
    (folder / "b.toml").write_text('extends = "a.toml"\n', encoding="utf-8")
    with pytest.raises(ValueError, match="ciclo"):
        load_config(folder / "a.toml")
    (folder / "c.toml").write_text('extends = "nothing.toml"\n', encoding="utf-8")
    with pytest.raises(FileNotFoundError):
        load_config(folder / "c.toml")
    with pytest.raises(FileNotFoundError):
        load_config(folder / "absent.toml")
    (folder / "d.toml").write_text("extends = 3\n", encoding="utf-8")
    with pytest.raises(ValueError, match="extends"):
        load_config(folder / "d.toml")
