"""Pipeline configuration: one TOML file, typed, immutable and checked key by key (plan, section 4).

``config/pipeline.toml`` holds every default. A file may start from another one with a top-level ``extends = "<path>"``
(``config/pipeline.quick.toml`` and ``config/pipeline.docker.toml`` do). Every relative path is resolved against the project folder, never against
the working directory (RNF05): the paths inside the configuration (``[source] zip_path`` and ``[paths]``) against ``$PERSONALOFFERS_HOME`` when it
is set, otherwise the parent of the folder that holds the main configuration file; a relative configuration file (``$PERSONALOFFERS_CONFIG`` or the
``path`` argument, which ``--config`` passes) against ``$PERSONALOFFERS_HOME`` or, without it, the folder of this package's project.

Anything unknown, missing, mistyped or inconsistent is a ``ValueError`` that names the key: an option that is accepted and silently not used is the
defect projects 01 and 02 both had.

Every leaf of the configuration is either in ``FINGERPRINT_KEYS`` (it can change a sealed value, so it enters the seal's ``config_sha256``) or in
``UNSEALED_KEYS`` (it cannot), never both and never neither (decision D21). The sealed calculations receive ``SealedConfig``, which holds only the
fingerprinted keys and the observed hashes of the zip, the workbook and the canonical lines. The hash of the TOML file itself is a different thing
(``config_file_sha256``, project 05's A8) and never appears here. ``INFORMATIVE_KEYS`` names the keys that change nothing a run produces (none yet):
``tests/e2e/test_cli.py`` (U19) walks every key and each must change the result or be listed there.
"""

from __future__ import annotations

import dataclasses
import math
import os
import re
import tomllib
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any, get_args, get_origin, get_type_hints

DEFAULT_PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = DEFAULT_PROJECT_ROOT / "config" / "pipeline.toml"

ENV_CONFIG = "PERSONALOFFERS_CONFIG"
ENV_HOME = "PERSONALOFFERS_HOME"
CRM_MODES = ("standin", "http")
WORKBOOK_COLUMNS = 8          # Invoice, StockCode, Description, Quantity, InvoiceDate, Price, Customer ID, Country
WORKBOOK_SHEETS = 2           # "Year 2009-2010" and "Year 2010-2011"
LINE_KEY_SHEET_FACTOR = 10_000_000   # line_key = sheet number x this + the row of the sheet (from 1), so a sheet holds fewer rows than this (D03)
ROUND_WEEKDAY = 0             # a round is a Monday (D05)
MAX_SEED = 2**32 - 1          # the largest seed that numpy's generators accept

_DAY_NAMES = ("lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo")
_SHA256 = re.compile(r"[0-9a-f]{64}")
_ENV_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_TYPE_NAMES = {
    bool: "verdadero o falso", int: "un entero", float: "un número", str: "un texto", date: "una fecha (AAAA-MM-DD, sin hora)",
    Path: "una ruta",
}


@dataclass(frozen=True)
class SourceConfig:
    zip_path: Path
    zip_bytes: int
    zip_sha256: str
    member: str
    member_bytes: int
    member_sha256: str
    max_part_bytes: int
    max_rows: int
    sheets: tuple[str, ...]
    columns: tuple[str, ...]
    first_date: date
    last_date: date


@dataclass(frozen=True)
class CatalogueConfig:
    product_code_regex: str


@dataclass(frozen=True)
class CalendarConfig:
    history_start: date
    launch_last_day: date
    validation_first_round: date
    validation_last_round: date
    test_first_round: date
    test_last_round: date
    close_first_day: date
    close_last_day: date
    window_days: int


@dataclass(frozen=True)
class BaseConfig:
    lookback_days: int
    bulk_min_median_qty: int
    bulk_min_lines: int


@dataclass(frozen=True)
class HoldoutConfig:
    share: float
    seed: int
    salt: str
    recency_bands: int
    frequency_bands: int


@dataclass(frozen=True)
class RecommendConfig:
    k: int
    repeat_slots: int
    discovery_slots: int
    fallback_days: int
    repeat_recency_weight: float
    repeat_recency_days: int


@dataclass(frozen=True)
class GridConfig:
    als_factors: tuple[int, ...]
    als_regularization: tuple[float, ...]
    als_iterations: int
    als_alpha: float
    cosine_k: tuple[int, ...]
    rules_min_invoices: tuple[int, ...]
    rules_min_lift: float
    blend_trend_weights: tuple[float, ...]
    blend_trend_days: int
    choice_tolerance: float
    seed: int


@dataclass(frozen=True)
class EvaluationConfig:
    resamples: int
    seed: int


@dataclass(frozen=True)
class ExperimentConfig:
    permutations: int
    calibration_seeds: int
    calibration_permutations: int
    cuped_weeks: int
    alpha: float
    mde_power: float
    mde_shares: tuple[float, ...]


@dataclass(frozen=True)
class CriteriaConfig:
    c01_min_diff_low: float
    c02_min_diff_low: float
    c03_min_diff_low: float
    c04_min_diff_low: float
    c05_min_coverage: float
    c06_max_abs_smd: float
    c07_rejection_band: tuple[float, ...]
    c08_min_p: float


@dataclass(frozen=True)
class CrmConfig:
    mode: str
    base_url: str
    token_env: str
    batch_size: int
    timeout_s: int
    max_body_bytes: int


@dataclass(frozen=True)
class PrivacyConfig:
    min_cell_customers: int


@dataclass(frozen=True)
class SiteConfig:
    max_total_bytes: int


@dataclass(frozen=True)
class PathsConfig:
    raw_dir: Path
    interim_dir: Path
    warehouse: Path
    models_dir: Path
    crm_db: Path
    outputs_dir: Path
    private_dir: Path
    site_dir: Path
    reports_dir: Path
    seal: Path
    dashboard_html: Path
    readme: Path
    figures_dir: Path


@dataclass(frozen=True)
class PipelineConfig:
    source: SourceConfig
    catalogue: CatalogueConfig
    calendar: CalendarConfig
    base: BaseConfig
    holdout: HoldoutConfig
    recommend: RecommendConfig
    grid: GridConfig
    evaluation: EvaluationConfig
    experiment: ExperimentConfig
    criteria: CriteriaConfig
    crm: CrmConfig
    privacy: PrivacyConfig
    site: SiteConfig
    paths: PathsConfig
    project_root: Path


# --- the seal's view of the configuration (D21) ------------------------------------------------------------------------


@dataclass(frozen=True)
class SealedSourceConfig:
    """The four keys of ``[source]`` that can change a sealed value: the accepted hashes of the zip and of the workbook, and the sheets and columns that are
    read. The path, the sizes, the limits and the date range cannot (a file over a limit is refused, never read differently); the hashes of the files
    that were actually read enter as ``SealedConfig.zip_sha256_seen``, ``member_sha256_seen`` and ``lines_sha256_seen``."""

    zip_sha256: str
    member_sha256: str
    sheets: tuple[str, ...]
    columns: tuple[str, ...]


@dataclass(frozen=True)
class SealedConfig:
    """What the sealed calculations receive (the base, the control group, the recommenders, the choice and the evaluation): only the keys of
    ``FINGERPRINT_KEYS`` and the observed hashes of the files. A key outside it cannot reach a sealed value."""

    source: SealedSourceConfig
    catalogue: CatalogueConfig
    calendar: CalendarConfig
    base: BaseConfig
    holdout: HoldoutConfig
    recommend: RecommendConfig
    grid: GridConfig
    evaluation: EvaluationConfig
    experiment: ExperimentConfig
    criteria: CriteriaConfig
    privacy: PrivacyConfig
    zip_sha256_seen: str
    member_sha256_seen: str
    lines_sha256_seen: str

    @classmethod
    def of(cls, cfg: PipelineConfig, zip_sha256: str, member_sha256: str, lines_sha256: str) -> SealedConfig:
        """The sealed view of `cfg` for the zip, the workbook and the canonical lines that hashed to these values."""
        for where, value in (("zip_sha256_seen", zip_sha256), ("member_sha256_seen", member_sha256), ("lines_sha256_seen", lines_sha256)):
            _check_hash_seen(value, where)
        skipped = ("source", "zip_sha256_seen", "member_sha256_seen", "lines_sha256_seen")
        sections = {f.name: getattr(cfg, f.name) for f in dataclasses.fields(cls) if f.name not in skipped}
        s = cfg.source
        source = SealedSourceConfig(zip_sha256=s.zip_sha256, member_sha256=s.member_sha256, sheets=s.sheets, columns=s.columns)
        return cls(source=source, **sections, zip_sha256_seen=zip_sha256, member_sha256_seen=member_sha256, lines_sha256_seen=lines_sha256)


def _check_hash_seen(value: str, where: str) -> None:
    if not _SHA256.fullmatch(value):
        raise ValueError(f"{where}: se esperaban 64 caracteres hexadecimales en minúscula, se recibió {value!r}")


def config_leaves(cls: type, prefix: str = "") -> Iterator[str]:
    """The full name of every leaf of a configuration dataclass, ``section.key``, in declaration order."""
    hints = get_type_hints(cls)
    for f in dataclasses.fields(cls):
        name = f"{prefix}{f.name}"
        if dataclasses.is_dataclass(hints[f.name]):
            yield from config_leaves(hints[f.name], f"{name}.")
        else:
            yield name


# Every key that can change a sealed value, named one by one so that a new key fails tests/unit/test_config.py until it is classified.
# Including one too many only turns a cosmetic change into a post_seal run; one too few is project 03's defect B4 (D21). The observed hashes of the zip, the
# workbook and the canonical lines (zip_sha256_seen, member_sha256_seen, lines_sha256_seen) are not configured: SealedConfig adds them.
FINGERPRINT_KEYS: tuple[str, ...] = (
    "source.zip_sha256", "source.member_sha256", "source.sheets", "source.columns",
    "catalogue.product_code_regex",
    "calendar.history_start", "calendar.launch_last_day", "calendar.validation_first_round", "calendar.validation_last_round",
    "calendar.test_first_round", "calendar.test_last_round", "calendar.close_first_day", "calendar.close_last_day", "calendar.window_days",
    "base.lookback_days", "base.bulk_min_median_qty", "base.bulk_min_lines",
    "holdout.share", "holdout.seed", "holdout.salt", "holdout.recency_bands", "holdout.frequency_bands",
    "recommend.k", "recommend.repeat_slots", "recommend.discovery_slots", "recommend.fallback_days",
    "recommend.repeat_recency_weight", "recommend.repeat_recency_days",
    "grid.als_factors", "grid.als_regularization", "grid.als_iterations", "grid.als_alpha", "grid.cosine_k", "grid.rules_min_invoices",
    "grid.rules_min_lift", "grid.blend_trend_weights", "grid.blend_trend_days", "grid.choice_tolerance", "grid.seed",
    "evaluation.resamples", "evaluation.seed",
    "experiment.permutations", "experiment.calibration_seeds", "experiment.calibration_permutations", "experiment.cuped_weeks",
    "experiment.alpha", "experiment.mde_power", "experiment.mde_shares",
    "criteria.c01_min_diff_low", "criteria.c02_min_diff_low", "criteria.c03_min_diff_low", "criteria.c04_min_diff_low",
    "criteria.c05_min_coverage", "criteria.c06_max_abs_smd", "criteria.c07_rejection_band", "criteria.c08_min_p",
    "privacy.min_cell_customers",
)
# Every key that cannot: where the files are, their accepted sizes and limits and the date range that is refused outside (the hashes of what was read
# enter instead), the CRM and how it is reached, the site's limit and where the outputs go.
UNSEALED_KEYS: tuple[str, ...] = (
    "source.zip_path", "source.zip_bytes", "source.member", "source.member_bytes", "source.max_part_bytes", "source.max_rows",
    "source.first_date", "source.last_date",
    "crm.mode", "crm.base_url", "crm.token_env", "crm.batch_size", "crm.timeout_s", "crm.max_body_bytes",
    "site.max_total_bytes",
    "paths.raw_dir", "paths.interim_dir", "paths.warehouse", "paths.models_dir", "paths.crm_db", "paths.outputs_dir", "paths.private_dir",
    "paths.site_dir", "paths.reports_dir", "paths.seal", "paths.dashboard_html", "paths.readme", "paths.figures_dir",
)
# Keys that change nothing a run produces (none yet). A key listed here is declared informative and exempt from the test that each key changes
# the result (plan section 24.2, "Una prueba de clave de configuración que mira el código y no el efecto").
INFORMATIVE_KEYS: tuple[str, ...] = ()


# --- loading --------------------------------------------------------------------------------------------------------


def _resolve(value: str, root: Path, where: str) -> Path:
    if not value.strip():
        raise ValueError(f"{where}: se esperaba una ruta, se recibió un texto vacío")
    path = Path(value)
    if path.is_absolute():
        return path  # an absolute path is explicit: it may point anywhere on purpose
    joined = Path(os.path.normpath(root / path))
    base = Path(os.path.normpath(root))
    if joined != base and base not in joined.parents:
        raise ValueError(
            f"{where}: la ruta relativa {value!r} sale de la carpeta del proyecto ({base}); "
            "use una ruta absoluta si el destino está fuera a propósito"
        )
    return joined


def _coerce(value: Any, annotation: Any, where: str, root: Path, name: str) -> Any:
    """Convert a TOML value to the annotated type or raise ValueError naming `where`; `name` is the dotted name of the section that holds it."""
    origin = get_origin(annotation)
    if origin is tuple:
        (element, _ellipsis) = get_args(annotation)
        if not isinstance(value, list):
            raise ValueError(f"{where}: se esperaba una lista, se recibió {type(value).__name__}")
        return tuple(_coerce(v, element, where, root, name) for v in value)
    if annotation is bool:
        ok = isinstance(value, bool)
    elif annotation is int:
        ok = isinstance(value, int) and not isinstance(value, bool)
    elif annotation is float:
        ok = isinstance(value, (int, float)) and not isinstance(value, bool)
        value = float(value) if ok else value
    elif annotation is str:
        ok = isinstance(value, str)
    elif annotation is date:
        ok = type(value) is date   # a local date: no date-time (a subclass of date), no text
    elif annotation is Path:
        if isinstance(value, str):
            return _resolve(value, root, where)
        ok = False
    else:  # pragma: no cover - only reachable by adding an unsupported annotation
        raise TypeError(f"{where}: unsupported annotation {annotation!r}")
    if not ok:
        raise ValueError(f"{where}: se esperaba {_TYPE_NAMES.get(annotation, annotation)}, se recibió {value!r}")
    return value


def _build_section(cls: type, data: Any, name: str, root: Path) -> Any:
    if not isinstance(data, dict):
        raise ValueError(f"[{name}]: se esperaba una tabla, se recibió {type(data).__name__}")
    hints = get_type_hints(cls)
    fields = [f.name for f in dataclasses.fields(cls)]
    unknown = sorted(set(data) - set(fields))
    if unknown:
        raise ValueError(f"[{name}]: clave desconocida {unknown[0]!r}")
    missing = [f for f in fields if f not in data]
    if missing:
        raise ValueError(f"[{name}]: falta la clave {missing[0]!r}")
    return cls(**{f: _coerce(data[f], hints[f], f"[{name}] {f}", root, name) for f in fields})


# --- consistency checks ---------------------------------------------------------------------------------------------


def _positive(value: float, where: str) -> None:
    if not (math.isfinite(value) and value > 0):
        raise ValueError(f"{where}: se esperaba un valor finito mayor que 0, se recibió {value!r}")


def _non_negative(value: float, where: str) -> None:
    if not (math.isfinite(value) and value >= 0):
        raise ValueError(f"{where}: se esperaba un valor finito desde 0, se recibió {value!r}")


def _at_least(value: int, minimum: int, where: str) -> None:
    if value < minimum:
        raise ValueError(f"{where}: se esperaba {minimum} o más, se recibió {value!r}")


def _between(value: int, low: int, high: int, where: str) -> None:
    if not low <= value <= high:
        raise ValueError(f"{where}: se esperaba un valor de {low} a {high}, se recibió {value!r}")


def _seed(value: int, where: str) -> None:
    if not 0 <= value <= MAX_SEED:
        raise ValueError(f"{where}: se esperaba un entero de 0 a {MAX_SEED}, se recibió {value!r}")


def _open_fraction(value: float, where: str) -> None:
    if not (math.isfinite(value) and 0 < value < 1):
        raise ValueError(f"{where}: se esperaba un valor en (0, 1), se recibió {value!r}")


def _text(value: str, where: str) -> None:
    if not value.strip() or value != value.strip():
        raise ValueError(f"{where}: se esperaba un texto no vacío y sin espacios en los bordes, se recibió {value!r}")


def _unique_texts(values: tuple[str, ...], where: str, *, count: int | None = None) -> None:
    if not values or len(set(values)) != len(values):
        raise ValueError(f"{where}: se esperaba una lista no vacía y sin repetidos, se recibió {list(values)}")
    if count is not None and len(values) != count:
        raise ValueError(f"{where}: se esperaban {count} nombres, se recibieron {len(values)}: {list(values)}")
    for value in values:
        _text(value, where)


def _axis(values: tuple[float, ...] | tuple[int, ...], where: str, check) -> None:
    """One axis of the grid: not empty, no value twice, every value acceptable."""
    if not values or len(set(values)) != len(values):
        raise ValueError(f"{where}: se esperaba una lista no vacía y sin repetidos, se recibió {list(values)}")
    for value in values:
        check(value, where)


def _check_hash(value: str, where: str) -> None:
    if not _SHA256.fullmatch(value):
        raise ValueError(f"{where}: se esperaban 64 caracteres hexadecimales en minúscula, se recibió {value!r}")


def _quick_folder(cfg: PipelineConfig) -> Path:
    return Path(os.path.normpath(cfg.project_root / "data" / "quick"))


def _under(path: Path, folder: Path) -> bool:
    return folder in Path(os.path.normpath(path)).parents


def _check_accepted(under_quick: bool, size: int, digest: str, bytes_where: str, sha_where: str, quick: Path, path: Path) -> None:
    """The accepted size and hash of one source file go together: both set, or both empty and the file under data/quick/ (the first view is recorded there
    by the quick mode)."""
    _at_least(size, 0, bytes_where)
    if digest:
        _check_hash(digest, sha_where)
        if size == 0:
            raise ValueError(f"{bytes_where}: con una huella aceptada se esperaba un tamaño mayor que 0")
    else:
        if not under_quick:
            raise ValueError(
                f"{sha_where}: vacía solo se admite en el modo rápido, con la fuente bajo data/quick/ ({quick}); "
                f"la fuente real exige los 64 caracteres de su huella (se recibió la ruta {path})"
            )
        if size != 0:
            raise ValueError(f"{bytes_where}: con la huella vacía (modo rápido) se esperaba 0, se recibió {size}")


def _check_source(cfg: PipelineConfig) -> None:
    s = cfg.source
    _at_least(s.max_part_bytes, 1, "[source] max_part_bytes")
    _at_least(s.max_rows, 1, "[source] max_rows")
    if s.max_rows >= LINE_KEY_SHEET_FACTOR:
        raise ValueError(f"[source] max_rows: se esperaba menos de {LINE_KEY_SHEET_FACTOR} filas por hoja (la clave de línea es hoja × {LINE_KEY_SHEET_FACTOR} + fila), se recibió {s.max_rows}")
    if not s.member or s.member in (".", "..") or any(char in s.member for char in "/\\\0") or not s.member.lower().endswith(".xlsx"):
        raise ValueError(f"[source] member: se esperaba el nombre de un libro .xlsx sin carpetas, se recibió {s.member!r}")
    _unique_texts(s.sheets, "[source] sheets", count=WORKBOOK_SHEETS)
    _unique_texts(s.columns, "[source] columns", count=WORKBOOK_COLUMNS)
    if not s.first_date < s.last_date:
        raise ValueError(f"[source] last_date: se esperaba una fecha posterior a first_date ({s.first_date}), se recibió {s.last_date}")
    quick = _quick_folder(cfg)
    under_quick = _under(s.zip_path, quick)
    _check_accepted(under_quick, s.zip_bytes, s.zip_sha256, "[source] zip_bytes", "[source] zip_sha256", quick, s.zip_path)
    _check_accepted(under_quick, s.member_bytes, s.member_sha256, "[source] member_bytes", "[source] member_sha256", quick, s.zip_path)


def _check_catalogue(cfg: PipelineConfig) -> None:
    pattern = cfg.catalogue.product_code_regex
    try:
        compiled = re.compile(pattern)
    except re.error as error:
        raise ValueError(f"[catalogue] product_code_regex: no es una expresión regular válida ({error}): {pattern!r}") from error
    if compiled.fullmatch(""):
        raise ValueError(f"[catalogue] product_code_regex: no puede aceptar un código vacío, se recibió {pattern!r}")


def _check_calendar(cfg: PipelineConfig) -> None:
    c, s = cfg.calendar, cfg.source
    rounds = (("validation_first_round", c.validation_first_round), ("validation_last_round", c.validation_last_round),
              ("test_first_round", c.test_first_round), ("test_last_round", c.test_last_round), ("close_first_day", c.close_first_day))
    for key, day in rounds:
        if day.weekday() != ROUND_WEEKDAY:
            raise ValueError(f"[calendar] {key}: se esperaba un lunes (una ronda empieza el lunes), se recibió {day} ({_DAY_NAMES[day.weekday()]})")
    _between(c.window_days, 1, 7, "[calendar] window_days")
    if not c.history_start < c.validation_first_round:
        raise ValueError(f"[calendar] validation_first_round: se esperaba un día posterior a history_start ({c.history_start}), se recibió {c.validation_first_round}")
    if not c.validation_first_round <= c.validation_last_round:
        raise ValueError(f"[calendar] validation_last_round: se esperaba validation_last_round >= validation_first_round ({c.validation_first_round}), se recibió {c.validation_last_round}")
    if c.validation_last_round + timedelta(days=c.window_days) > c.test_first_round:
        raise ValueError(
            f"[calendar] validation_last_round: la ventana de la última ronda de validación ({c.validation_last_round} + {c.window_days} días) "
            f"termina después de test_first_round ({c.test_first_round}); la validación debe terminar antes de la prueba (D23)"
        )
    if c.test_first_round != c.launch_last_day + timedelta(days=1):
        raise ValueError(f"[calendar] test_first_round: se esperaba el día siguiente a launch_last_day ({c.launch_last_day + timedelta(days=1)}), se recibió {c.test_first_round}")
    if not c.test_first_round <= c.test_last_round:
        raise ValueError(f"[calendar] test_last_round: se esperaba test_last_round >= test_first_round ({c.test_first_round}), se recibió {c.test_last_round}")
    if c.close_first_day != c.test_last_round + timedelta(days=7):
        raise ValueError(f"[calendar] close_first_day: se esperaba la semana siguiente a test_last_round ({c.test_last_round + timedelta(days=7)}), se recibió {c.close_first_day}")
    if not c.close_first_day <= c.close_last_day < c.close_first_day + timedelta(days=7):
        raise ValueError(f"[calendar] close_last_day: se esperaba un día de la semana de close_first_day ({c.close_first_day}), se recibió {c.close_last_day}")
    if c.history_start < s.first_date:
        raise ValueError(f"[calendar] history_start: se esperaba una fecha desde source.first_date ({s.first_date}), se recibió {c.history_start}")
    if c.close_last_day > s.last_date:
        raise ValueError(f"[calendar] close_last_day: se esperaba una fecha hasta source.last_date ({s.last_date}), se recibió {c.close_last_day}")


def _check_base_holdout_recommend(cfg: PipelineConfig) -> None:
    b = cfg.base
    for key in ("lookback_days", "bulk_min_median_qty", "bulk_min_lines"):
        _at_least(getattr(b, key), 1, f"[base] {key}")
    h = cfg.holdout
    if not (math.isfinite(h.share) and 0 < h.share <= 0.5):
        raise ValueError(f"[holdout] share: se esperaba un valor en (0, 0,5], se recibió {h.share!r}")
    _seed(h.seed, "[holdout] seed")
    _text(h.salt, "[holdout] salt")
    _at_least(h.recency_bands, 1, "[holdout] recency_bands")
    _at_least(h.frequency_bands, 1, "[holdout] frequency_bands")
    r = cfg.recommend
    for key in ("k", "fallback_days", "repeat_recency_days"):
        _at_least(getattr(r, key), 1, f"[recommend] {key}")
    _at_least(r.repeat_slots, 0, "[recommend] repeat_slots")
    _at_least(r.discovery_slots, 0, "[recommend] discovery_slots")
    if r.repeat_slots + r.discovery_slots != r.k:
        raise ValueError(f"[recommend] discovery_slots: repeat_slots + discovery_slots debe ser k ({r.k}), se recibió {r.repeat_slots} + {r.discovery_slots}")
    _non_negative(r.repeat_recency_weight, "[recommend] repeat_recency_weight")


def _check_grid(cfg: PipelineConfig) -> None:
    g = cfg.grid
    _axis(g.als_factors, "[grid] als_factors", lambda v, w: _at_least(v, 1, w))
    _axis(g.als_regularization, "[grid] als_regularization", _positive)
    _axis(g.cosine_k, "[grid] cosine_k", lambda v, w: _at_least(v, 1, w))
    _axis(g.rules_min_invoices, "[grid] rules_min_invoices", lambda v, w: _at_least(v, 1, w))
    _axis(g.blend_trend_weights, "[grid] blend_trend_weights", _non_negative)
    if 0.0 not in g.blend_trend_weights:
        raise ValueError(f"[grid] blend_trend_weights: se esperaba el peso 0 (el modelo solo, que toman las líneas base B4-B6), se recibió {list(g.blend_trend_weights)}")
    _at_least(g.als_iterations, 1, "[grid] als_iterations")
    _positive(g.als_alpha, "[grid] als_alpha")
    _non_negative(g.rules_min_lift, "[grid] rules_min_lift")
    _at_least(g.blend_trend_days, 1, "[grid] blend_trend_days")
    if not (math.isfinite(g.choice_tolerance) and 0 <= g.choice_tolerance < 1):
        raise ValueError(f"[grid] choice_tolerance: se esperaba un valor en [0, 1), se recibió {g.choice_tolerance!r}")
    _seed(g.seed, "[grid] seed")


def _check_evaluation(cfg: PipelineConfig) -> None:
    _at_least(cfg.evaluation.resamples, 1, "[evaluation] resamples")
    _seed(cfg.evaluation.seed, "[evaluation] seed")
    x, c = cfg.experiment, cfg.calendar
    for key in ("permutations", "calibration_seeds", "calibration_permutations", "cuped_weeks"):
        _at_least(getattr(x, key), 1, f"[experiment] {key}")
    test_rounds = (c.test_last_round - c.test_first_round).days // 7 + 1
    if x.cuped_weeks != test_rounds:
        raise ValueError(
            f"[experiment] cuped_weeks: se esperaba el mismo número de semanas que las rondas de prueba de [calendar] ({test_rounds}: "
            f"el ajuste usa las mismas cantidades del período previo), se recibió {x.cuped_weeks}"
        )
    if (c.launch_last_day - c.history_start).days + 1 < x.cuped_weeks * 7:
        raise ValueError(f"[experiment] cuped_weeks: {x.cuped_weeks} semanas antes del lanzamiento no caben en la historia que empieza el {c.history_start}")
    _open_fraction(x.alpha, "[experiment] alpha")
    _open_fraction(x.mde_power, "[experiment] mde_power")
    _axis(x.mde_shares, "[experiment] mde_shares", _open_fraction)
    k = cfg.criteria
    for key in ("c01_min_diff_low", "c02_min_diff_low", "c03_min_diff_low", "c04_min_diff_low"):
        value = getattr(k, key)
        if not (math.isfinite(value) and -1 <= value <= 1):
            raise ValueError(f"[criteria] {key}: se esperaba un valor de -1 a 1 (una diferencia de tasas), se recibió {value!r}")
    if not (math.isfinite(k.c05_min_coverage) and 0 <= k.c05_min_coverage <= 1):
        raise ValueError(f"[criteria] c05_min_coverage: se esperaba un valor en [0, 1], se recibió {k.c05_min_coverage!r}")
    _positive(k.c06_max_abs_smd, "[criteria] c06_max_abs_smd")
    band = k.c07_rejection_band
    if len(band) != 2 or not all(math.isfinite(v) and 0 <= v <= 1 for v in band) or not band[0] < band[1]:
        raise ValueError(f"[criteria] c07_rejection_band: se esperaban dos números de 0 a 1 en orden creciente (el menor y el mayor), se recibió {list(band)}")
    _open_fraction(k.c08_min_p, "[criteria] c08_min_p")


def _check_crm_privacy_site(cfg: PipelineConfig) -> None:
    m = cfg.crm
    if m.mode not in CRM_MODES:
        raise ValueError(f"[crm] mode: {m.mode!r} no es un valor conocido ({', '.join(CRM_MODES)})")
    if m.mode == "http" and not re.fullmatch(r"https?://[^\s/]+(/\S*)?", m.base_url):
        raise ValueError(f"[crm] base_url: con mode = \"http\" se esperaba una dirección http:// o https://, se recibió {m.base_url!r}")
    if not _ENV_NAME.fullmatch(m.token_env):
        raise ValueError(f"[crm] token_env: se esperaba el nombre de una variable de entorno, se recibió {m.token_env!r}")
    for key in ("batch_size", "timeout_s", "max_body_bytes"):
        _at_least(getattr(m, key), 1, f"[crm] {key}")
    _at_least(cfg.privacy.min_cell_customers, 1, "[privacy] min_cell_customers")
    _positive(cfg.site.max_total_bytes, "[site] max_total_bytes")


def _check(cfg: PipelineConfig) -> None:
    _check_source(cfg)
    _check_catalogue(cfg)
    _check_calendar(cfg)
    _check_base_holdout_recommend(cfg)
    _check_grid(cfg)
    _check_evaluation(cfg)
    _check_crm_privacy_site(cfg)


# --- reading --------------------------------------------------------------------------------------------------------


def _deep_merge(base: dict[str, Any], top: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in top.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value   # a list replaces the whole list
    return merged


def _read_toml(path: Path, _seen: tuple[Path, ...] = ()) -> dict[str, Any]:
    """Read a TOML file, following ``extends`` (relative to the file) and merging over its base."""
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"no se encontró el archivo de configuración: {path}")
    resolved = path.resolve()
    if resolved in _seen:
        raise ValueError(f"los archivos de configuración se extienden entre sí en un ciclo en {path}")
    with path.open("rb") as handle:
        data = tomllib.load(handle)
    parent = data.pop("extends", None)
    if parent is None:
        return data
    if not isinstance(parent, str):
        raise ValueError(f"{path}: extends debe ser una ruta escrita como texto")
    parent_path = Path(parent)
    if not parent_path.is_absolute():
        parent_path = path.parent / parent_path
    return _deep_merge(_read_toml(parent_path, (*_seen, resolved)), data)


def _home() -> Path | None:
    home = os.environ.get(ENV_HOME)
    if not home:
        return None
    root = Path(home).resolve()
    if not root.is_dir():
        raise ValueError(f"{ENV_HOME}: {home!r} no es una carpeta existente")
    return root


def load_config(path: Path | None = None) -> PipelineConfig:
    """Load the configuration.

    `path` is the main file; without it, ``$PERSONALOFFERS_CONFIG`` and then ``config/pipeline.toml`` of the project. A relative `path` or
    ``$PERSONALOFFERS_CONFIG`` is taken from ``$PERSONALOFFERS_HOME`` or, without it, from this package's project: the working directory may be
    another copy's folder, and its configuration is never read in silence. The paths inside are resolved against ``$PERSONALOFFERS_HOME`` or
    the parent of the folder that holds the main file. Anything unknown, missing, mistyped or inconsistent is a ``ValueError`` naming the key.
    """
    home = _home()
    if path is None:
        env = os.environ.get(ENV_CONFIG)
        path = Path(env) if env else DEFAULT_CONFIG
    path = Path(path)
    if not path.is_absolute():
        path = (home or DEFAULT_PROJECT_ROOT) / path
    data = _read_toml(path)
    root = home or path.resolve().parent.parent

    sections = [f.name for f in dataclasses.fields(PipelineConfig) if f.name != "project_root"]
    unknown = sorted(set(data) - set(sections))
    if unknown:
        raise ValueError(f"sección desconocida [{unknown[0]}]")
    missing = [s for s in sections if s not in data]
    if missing:
        raise ValueError(f"falta la sección [{missing[0]}]")
    hints = get_type_hints(PipelineConfig)
    built = {name: _build_section(hints[name], data[name], name, root) for name in sections}
    cfg = PipelineConfig(**built, project_root=root)
    _check(cfg)
    return cfg


__all__ = [
    "DEFAULT_CONFIG", "DEFAULT_PROJECT_ROOT", "ENV_CONFIG", "ENV_HOME", "FINGERPRINT_KEYS", "INFORMATIVE_KEYS", "LINE_KEY_SHEET_FACTOR", "UNSEALED_KEYS",
    "PipelineConfig", "SealedConfig", "config_leaves", "load_config",
]
