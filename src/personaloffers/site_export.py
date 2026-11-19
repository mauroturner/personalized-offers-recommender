"""The six small JSON files that the personal site copies (RF22, AC28; risk item 3: another repository consumes their shape; decisions D16, D30, D38; plan section 21). Adapted from project 07's ``site_export.py``.

``export_site`` writes ``summary.json``, ``data.json``, ``algorithms.json``, ``operation.json``, ``control.json`` and ``validation_rules.json`` and, last, ``manifest.json``. The figures of the test come from the star
model (the ``star_*`` tables that ``export.build_powerbi_marts`` built, the very rows the Parquet files hold, with their small cells already hidden), the criteria and the headline from the summary of the run
(``reporting.build_summary``), the seal says what was frozen, and the facts of the archive come from the lines the warehouse holds. **Until the test is sealed with this configuration every result of the test is empty
or ``null``** (the criteria are the ten thresholds with no verdict, ``methods``, ``by_round``, ``aa``, ``calibration`` and ``mde`` are empty): the rounds that already ran are follow-up, and the validation of the choice
and the balance of the draw were sealed at the launch, so they are not the test. A configuration that is not the sealed one (``post_seal``) publishes none of it either.

**No effect is published** (D16): the archive has no offers, so no field is named after an effect, an increase or a lift (the ``rule_lift`` of the association rules is another thing) and every text that says
«efecto» says «menor efecto detectable» or that something is not one; ``tests/contract/test_site_export.py`` walks every key and string. **Nothing identifies a customer**: no number of a customer is written, a count
of customers under ``[privacy] min_cell_customers`` is ``null``, a total over cells is ``null`` as soon as one of its cells is hidden, and the three example lists carry no customer, come from a profile with at least
that many customers and say so (the plan's assumption: if the evaluation judges that a list could identify someone, it is replaced by one for a made-up profile).

The files are a contract that another repository consumes: a change of shape is a change of ``tests/contract/test_site_export.py``. Floats are rounded to what the site shows; every file is
``json.dumps(obj, ensure_ascii=False, sort_keys=True, indent=1)`` with a final newline and the six together stay under ``max_total_bytes`` (``[site]``). They are one export: each is replaced atomically and
``manifest.json``, written last, names each with its size and SHA-256. The old manifest is removed before the first file is replaced, so a failure between two replacements leaves a folder with no manifest, which
``verify_site`` refuses; a reader takes the files through ``read_site``. A rule that counts something cumulative (``source`` and ``latest``) is read once, from the latest loaded run that recorded it, and never summed
over the runs (project 03, D94). ``export_summary`` rewrites only ``summary.json`` and the manifest (what closing a run changes: its status).
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import sqlite3
import statistics
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from personaloffers import calendar as cal
from personaloffers import registry, reporting, texts
from personaloffers.files import write_atomic
from personaloffers.validate import RULES

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 1
SITE_FILES = ("summary.json", "data.json", "algorithms.json", "operation.json", "control.json", "validation_rules.json")
MANIFEST_FILE = "manifest.json"
ENVELOPE = ("schema_version", "run_key", "as_of", "config_sha256", "source_sha256", "attribution", "no_effect_note_es")
REQUIRED_STAR = ("star_dim_round", "star_fact_round_ops", "star_fact_round_group", "star_fact_method_total", "star_fact_method_round", "star_fact_choice", "star_fact_balance", "star_fact_experiment",
                 "star_fact_mde", "star_fact_rule")
NO_EFFECT_NOTE_ES = "El archivo no tiene ofertas: estas cifras dicen qué anticipa cada lista, no cuánto vende una oferta"
CANNOT_MEASURE_ES = [
    "No se puede medir cuánto vende una oferta: el archivo no tiene ninguna oferta enviada.",
    "No se puede medir qué hace un grupo de control sin oferta: nadie quedó fuera de una campaña.",
    "El A/A compara dos grupos que no recibieron nada: lo que muestra es cómo quedó armado el control y qué tan calibrada está la prueba.",
    "El menor efecto detectable dice qué tamaño de diferencia podría verse con una operación real de este tamaño; no es un resultado.",
]
PENDING_ES = "La prueba se evalúa con el cierre del {close}."
POST_SEAL_ES = "La configuración no es la sellada: la prueba no se publica."
STATUS_WORST_FIRST = ("falla", "advertencia", "pasa")
LIST_METHODS = ("offer_list", "chosen_discovery", "b2", "b3")
TOP_COUNTRIES = 10
EXAMPLE_LISTS = 3
RULES_EXAMPLE = 10
RULES_EXAMPLE_MIN_SUPPORT = 50
CRITERION_FIELDS = ("criterion_id", "name_es", "threshold_es", "tested_value_es", "point_value", "ci_low", "ci_high", "passed", "verdict_es")


class SiteExportError(RuntimeError):
    """The site files cannot be written from this warehouse; nothing was replaced."""


class SiteSetError(FileNotFoundError):
    """The files of a site folder are not one export: one is missing or is not the file ``manifest.json`` names, or the manifest is."""


@dataclass(frozen=True)
class SiteFiles:
    """The six documents of a verified site folder and its manifest, parsed from the bytes that were checked against it."""

    summary: dict[str, Any]
    data: dict[str, Any]
    algorithms: dict[str, Any]
    operation: dict[str, Any]
    control: dict[str, Any]
    validation_rules: dict[str, Any]
    manifest: dict[str, Any]


# --- values -------------------------------------------------------------------------------------------------------------------------


def _num(value: Any, decimals: int = 3) -> float | None:
    if value is None or pd.isna(value) or (isinstance(value, float) and not math.isfinite(value)):
        return None
    return round(float(value), decimals)


def _int(value: Any) -> int | None:
    return None if value is None or pd.isna(value) else int(value)


def _cell(value: Any, minimum: int) -> int | None:
    """A count of customers as the site shows it: nothing when it is under the minimum of a cell (D30)."""
    return None if value is None or pd.isna(value) or int(value) < minimum else int(value)


def _query(conn: sqlite3.Connection, sql: str, params: tuple | dict = ()) -> pd.DataFrame:
    return pd.read_sql_query(sql, conn, params=params)


def _require_star(conn: sqlite3.Connection) -> None:
    present = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    missing = [t for t in REQUIRED_STAR if t not in present]
    if missing:
        raise SiteExportError(f"faltan las tablas del modelo estrella {missing}: la tarea export las construye antes de escribir el sitio")


def _header(run: reporting.RunMeta, view: Any) -> dict[str, Any]:
    return {"schema_version": SCHEMA_VERSION, "run_key": run.run_key, "as_of": run.as_of.strftime("%Y-%m-%d %H:%M:%S"), "config_sha256": registry.config_fingerprint(view),
            "source_sha256": view.zip_sha256_seen, "attribution": texts.ATTRIBUTION, "no_effect_note_es": NO_EFFECT_NOTE_ES}


def _records(frame: pd.DataFrame, decimals: Mapping[str, int] | None = None) -> list[dict[str, Any]]:
    """The rows of `frame` as dictionaries of plain values: ``None`` for a missing one, a float rounded to its decimals (3 by default) and an integer column left whole."""
    out = []
    for row in frame.to_dict("records"):
        item = {}
        for key, value in row.items():
            if isinstance(value, float) or (not isinstance(value, (str, bool, int)) and value is not None and not pd.isna(value) and hasattr(value, "item") and isinstance(value.item(), float)):
                item[key] = _num(value, (decimals or {}).get(key, 3))
            elif value is None or (not isinstance(value, str) and pd.isna(value)):
                item[key] = None
            else:
                item[key] = value.item() if hasattr(value, "item") else value
        out.append(item)
    return out


# --- summary.json ---------------------------------------------------------------------------------------------------------------------------


def _pending(view: Any, status: str) -> list[dict[str, Any]]:
    reason = POST_SEAL_ES if status == "post_seal" else PENDING_ES.format(close=reporting.close_day(view))
    return [{**{key: c[key] for key in CRITERION_FIELDS}, "tested_value_es": None, "verdict_es": reason} for c in reporting.pending_criteria(view)]


def _summary(conn: sqlite3.Connection, run: reporting.RunMeta, view: Any, summary: dict[str, Any], seal: dict[str, Any] | None, status: str) -> dict[str, Any]:
    sealed = status == "sealed"
    if sealed:
        criteria = [{key: (_num(c[key], 4) if key in ("point_value", "ci_low", "ci_high") else c[key]) for key in CRITERION_FIELDS} for c in summary["criteria"]]
    else:
        criteria = _pending(view, status)
    headline = None
    if sealed and summary["headline"] is not None:
        raw = summary["headline"]
        ops = _query(conn, "SELECT o.base, o.offer, o.control FROM star_fact_round_ops o JOIN star_dim_round d ON d.round_key = o.round_key WHERE d.period = 'test' ORDER BY o.round_key")
        mean = lambda column: None if ops.empty or ops[column].isna().any() else _num(ops[column].mean())   # noqa: E731
        headline = {"rounds": raw["rounds"], "base_mean": mean("base"), "offer_mean": mean("offer"), "control_mean": mean("control"), **{key: _num(raw[key]) for key in (
            "hit_offer_list", "hit_b2", "hit_b3", "hit_new_chosen", "hit_new_b2", "coverage", "max_abs_smd", "aa_p_m1", "aa_p_m2", "mde_m1_points_20", "mde_m2_gbp_20")}}
    row = conn.execute("SELECT status FROM pipeline_runs WHERE run_key = ?", (run.run_key,)).fetchone()
    launch, test = (seal or {}).get("launch"), (seal or {}).get("test")
    sealed_part = None if launch is None else {
        "launch": {"config_sha256": launch["config_sha256"], "as_of": launch["as_of"], "recipe": launch["recipe"]["name"]},
        "test": {"run_key": test["run_key"], "as_of": test["as_of"]} if sealed and test is not None else None}
    return {"status": row[0] if row else "running", "evaluation_status": status, "headline": headline, "criteria": criteria, "seal": sealed_part, "sealed_from": summary["source"] if sealed else None}


# --- data.json ------------------------------------------------------------------------------------------------------------------------------


def _data(conn: sqlite3.Connection, view: Any, source_counts: Mapping[str, Any] | None) -> dict[str, Any]:
    minimum = view.privacy.min_cell_customers
    rows, guests, repeats = conn.execute("SELECT COUNT(*), COALESCE(SUM(customer_id IS NULL), 0), COALESCE(SUM(internal_repeat), 0) FROM lines").fetchone()
    counts = source_counts or {}
    source = {"rows_loaded": rows, "rows_without_customer": int(guests), "share_without_customer": _num(guests / rows) if rows else None, "internal_repeats": int(repeats),
              "copies_removed": counts.get("copies_removed"), "rows_by_sheet": counts.get("rows_by_sheet")}
    roles = dict(conn.execute("SELECT role, COUNT(*) FROM lines GROUP BY role ORDER BY role").fetchall())
    countries = [{"country": c, "lines": n} for c, n in conn.execute("SELECT country, COUNT(*) AS n FROM lines WHERE role IN ('purchase', 'guest_purchase') GROUP BY country ORDER BY n DESC, country LIMIT ?", (TOP_COUNTRIES,))]
    sizes = _query(conn, "SELECT invoice, COUNT(DISTINCT stock_code) AS n FROM lines WHERE role IN ('purchase', 'guest_purchase') GROUP BY invoice")
    guest_invoices = conn.execute("SELECT COUNT(DISTINCT invoice) FROM lines WHERE role = 'guest_purchase'").fetchone()[0]
    customers, repeating = conn.execute("SELECT COUNT(*), COALESCE(SUM(n >= 2), 0) FROM (SELECT COUNT(DISTINCT invoice) AS n FROM lines WHERE role = 'purchase' GROUP BY customer_id)").fetchone()
    pairs, repeated = conn.execute("SELECT COUNT(*), COALESCE(SUM(n >= 2), 0) FROM (SELECT COUNT(DISTINCT invoice) AS n FROM lines WHERE role = 'purchase' GROUP BY customer_id, stock_code)").fetchone()
    visits = _query(conn, "SELECT customer_id, MIN(invoice_date) AS day FROM lines WHERE role = 'purchase' GROUP BY customer_id, invoice")
    visits["day"] = pd.to_datetime(visits["day"]).dt.normalize()
    gaps = visits.sort_values(["customer_id", "day"]).groupby("customer_id")["day"].diff().dropna().dt.days
    first = cal.round_id(view.calendar.test_first_round)
    base_size, bulk = conn.execute("SELECT COUNT(*), COALESCE(SUM(bulk), 0) FROM contact_base WHERE round_id = ?", (first,)).fetchone()
    c = view.calendar
    return {"source": source, "roles": roles, "countries": countries,
            "products": {"distinct": conn.execute("SELECT COUNT(DISTINCT stock_code) FROM lines WHERE role IN ('purchase', 'guest_purchase')").fetchone()[0]},
            "baskets": {"median_products": _num(statistics.median(sizes["n"]), 1) if len(sizes) else None, "invoices": len(sizes), "guest_invoices": int(guest_invoices)},
            "customers": {"with_a_purchase": _cell(customers, minimum), "with_two_or_more_invoices": _cell(repeating, minimum)},
            "repurchase": {"pairs": int(pairs), "share_of_pairs": _num(repeated / pairs) if pairs else None, "median_days_between_purchases": _num(gaps.median(), 1) if len(gaps) else None},
            "bulk": {"rule": "mediana de la cantidad por línea y líneas mínimas de [base]; la regla del proyecto 02", "customers_in_the_launch_base": _cell(base_size, minimum), "bulk": _cell(bulk, minimum)},
            "discount_lines": conn.execute("SELECT COUNT(*) FROM lines WHERE stock_code = 'D'").fetchone()[0],
            "calendar": {"history_start": c.history_start.isoformat(), "launch_last_day": c.launch_last_day.isoformat(), "validation_rounds": [cal.round_id(m) for m in cal.rounds(view, "validation")],
                         "rounds": [cal.round_id(m) for m in cal.rounds(view, "test")], "censored_round": next((cal.round_id(m) for m in cal.rounds(view, "censored")), None),
                         "close_first_day": c.close_first_day.isoformat(), "close_last_day": c.close_last_day.isoformat()}}


# --- algorithms.json ------------------------------------------------------------------------------------------------------------------------


def _methods(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    frame = _query(conn, "SELECT method_key, variant_key, pairs, hit_rate, ci_low, ci_high, wilson_low, wilson_high, recall, precision, ndcg, coverage, suppressed FROM star_fact_method_total "
                         "WHERE seal_state = 'sealed' ORDER BY method_key, variant_key")
    frame.insert(1, "label_es", [texts.METHOD_LABELS[m][0] for m in frame["method_key"]])
    frame["suppressed"] = frame["suppressed"].astype(bool)
    return _records(frame)


def _by_round(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    marks = ", ".join("?" for _ in LIST_METHODS)
    frame = _query(conn, "SELECT m.method_key, m.variant_key, m.round_key, d.period, m.pairs, m.hit_rate FROM star_fact_method_round m JOIN star_dim_round d ON d.round_key = m.round_key "
                         f"WHERE m.seal_state = 'sealed' AND m.method_key IN ({marks}) ORDER BY m.method_key, m.variant_key, m.round_key", LIST_METHODS)
    return _records(frame)


def _choice(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    frame = _query(conn, "SELECT candidate, base_model, params, trend_weight, val_hit_new, val_coverage, kept, chosen, fit_rounds FROM star_fact_choice ORDER BY candidate")
    out = _records(frame.drop(columns=["params", "kept", "chosen"]))
    for item, params, kept, chosen in zip(out, frame["params"], frame["kept"], frame["chosen"], strict=True):
        item.update(params=json.loads(params), kept=bool(kept), chosen=bool(chosen))
    return out


def _rules_example(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    frame = _query(conn, "SELECT antecedent_es, consequent_es, support, confidence, rule_lift FROM star_fact_rule WHERE support >= ? ORDER BY rule_lift DESC, support DESC, antecedent_key, consequent_key LIMIT ?",
                   (RULES_EXAMPLE_MIN_SUPPORT, RULES_EXAMPLE))
    return _records(frame)


def _example_lists(conn: sqlite3.Connection, view: Any) -> list[dict[str, Any]]:
    """Three lists of the first round, for the three biggest profiles that have at least the minimum of customers: the offer-group customer in the middle of the profile's customers by number; no customer is named."""
    round_id, minimum = cal.round_id(view.calendar.test_first_round), view.privacy.min_cell_customers
    profiles = conn.execute("SELECT segment, COUNT(*) AS n FROM contact_base WHERE round_id = ? GROUP BY segment HAVING COUNT(*) >= ? ORDER BY n DESC, segment LIMIT ?", (round_id, minimum, EXAMPLE_LISTS)).fetchall()
    out = []
    for segment, size in profiles:
        ids = [r[0] for r in conn.execute("SELECT c.customer_id FROM contact_base c JOIN holdout_assignments h ON h.customer_id = c.customer_id WHERE c.round_id = ? AND c.segment = ? AND h.grp = 'offer' "
                                          "ORDER BY c.customer_id", (round_id, segment))]
        if not ids:
            continue
        products = [{"rank": r, "stock_code": code, "description_es": text or "", "source_key": source} for r, code, text, source in conn.execute(
            "SELECT o.rank, o.stock_code, p.description_es, o.source FROM offer_lists o LEFT JOIN products p ON p.stock_code = o.stock_code WHERE o.round_id = ? AND o.customer_id = ? ORDER BY o.rank",
            (round_id, ids[len(ids) // 2]))]
        out.append({"profile_es": texts.SEGMENT_LABELS.get(segment, segment), "segment_key": segment, "round_key": round_id, "customers_in_segment": int(size), "products": products})
    return out


def _algorithms(conn: sqlite3.Connection, view: Any, status: str) -> dict[str, Any]:
    sealed = status == "sealed"
    return {"methods": _methods(conn) if sealed else [], "by_round": _by_round(conn) if sealed else [], "choice": _choice(conn), "rules_example": _rules_example(conn), "example_lists": _example_lists(conn, view)}


# --- operation.json -------------------------------------------------------------------------------------------------------------------------


def _count_email(private_dir: Path) -> dict[str, int]:
    """The e-mail files and their rows (without the header), counted; their content is never read into the site."""
    folder = Path(private_dir) / "email"
    names = sorted(folder.glob("*.csv")) if folder.is_dir() else []
    return {"files": len(names), "rows": sum(max(0, len(p.read_text(encoding="utf-8").splitlines()) - 1) for p in names)}


def _operation(conn: sqlite3.Connection, view: Any, private_dir: Path) -> dict[str, Any]:
    ops = _query(conn, "SELECT o.round_key, d.monday, d.period, o.base, o.offer, o.control, o.delivered, o.fallback_share, o.seconds FROM star_fact_round_ops o JOIN star_dim_round d ON d.round_key = o.round_key "
                       "ORDER BY o.round_key")
    groups = _query(conn, "SELECT round_key, group_key, COUNT(*) AS cells, SUM(suppressed) AS hidden, SUM(buyers) AS buyers, SUM(buyers_of_listed) AS listed FROM star_fact_round_group GROUP BY round_key, group_key")
    rounds = []
    for row in _records(ops, {"seconds": 1}):
        mine = groups[groups["round_key"] == row["round_key"]]
        whole = lambda frame, column: None if frame.empty or frame["hidden"].gt(0).any() or frame[column].isna().any() else _int(frame[column].sum())   # noqa: E731
        by_group = {g: mine[mine["group_key"] == g] for g in ("offer", "control")}
        row["buyers"] = whole(mine, "buyers")
        row["buyers_of_listed"] = {g: whole(frame, "listed") for g, frame in by_group.items()}
        rounds.append(row)
    minimum = view.privacy.min_cell_customers
    lists, created, unchanged, conflicts, equal, batches = conn.execute("SELECT COALESCE(SUM(contacts), 0), COALESCE(SUM(created), 0), COALESCE(SUM(unchanged), 0), COALESCE(SUM(conflicts), 0), "
                                                                         "COALESCE(SUM(readback_equal), 0), COUNT(*) FROM crm_deliveries WHERE status = 'ok'").fetchone()
    return {"rounds": rounds, "crm": {"lists": lists, "created": created, "unchanged": unchanged, "conflicts": conflicts, "batches": batches, "batches_read_back_equal": equal, "minimum_cell": minimum},
            "email": _count_email(private_dir)}


# --- control.json ---------------------------------------------------------------------------------------------------------------------------


def _control(conn: sqlite3.Connection, view: Any, seal: dict[str, Any] | None, status: str) -> dict[str, Any]:
    minimum, h = view.privacy.min_cell_customers, view.holdout
    launch = (seal or {}).get("launch") or {}
    sizes = (launch.get("holdout") or {}).get("sizes", {}).get("groups", {})
    holdout = {"share": h.share, "method": "estratificado por recencia, frecuencia y la marca mayorista; una sola vez, con la semilla sellada", "strata": h.recency_bands * h.frequency_bands * 2,
               "groups": {g: _cell(sizes.get(g), minimum) for g in ("offer", "control")}}
    sealed = status == "sealed"
    means = _query(conn, "SELECT covariate_key, offer_mean, control_mean FROM star_fact_balance WHERE seal_state = 'sealed'").set_index("covariate_key") if sealed else pd.DataFrame()
    smd = (launch.get("holdout") or {}).get("balance", {})
    balance = [{"covariate_key": key, "label_es": texts.COVARIATE_LABELS[key][0], "offer_mean": _num(means.loc[key, "offer_mean"]) if key in means.index else None,
                "control_mean": _num(means.loc[key, "control_mean"]) if key in means.index else None, "smd": _num(smd[key])} for key in texts.COVARIATE_LABELS if key in smd]
    aa = calibration = None
    mde: list[dict[str, Any]] = []
    if sealed:
        experiment = _query(conn, "SELECT metric, test, aa_diff, aa_p, aa_ci_low, aa_ci_high, calibration_rejection FROM star_fact_experiment WHERE seal_state = 'sealed' ORDER BY metric, test")
        aa, rejection, raw = {}, {}, {}
        for r in experiment.itertuples(index=False):
            aa.setdefault(r.metric, {})[r.test] = {"diff": _num(r.aa_diff, 4), "p": _num(r.aa_p), "ci_low": _num(r.aa_ci_low, 4), "ci_high": _num(r.aa_ci_high, 4)}
            if r.test == "preregistered":
                rejection[r.metric] = _num(r.calibration_rejection)
            elif r.test == "normal_raw":
                raw[r.metric] = _num(r.calibration_rejection)
        x = view.experiment
        calibration = {"alpha": x.alpha, "seeds": x.calibration_seeds, "permutations": x.calibration_permutations, "band": list(view.criteria.c07_rejection_band), "rejection": rejection,
                       "rejection_normal_raw": raw}
        mde = _records(_query(conn, "SELECT metric, holdout_share, holdout_size, mde, mde_relative FROM star_fact_mde WHERE seal_state = 'sealed' ORDER BY metric, holdout_share"), {"mde": 4, "mde_relative": 3})
    return {"holdout": holdout, "balance": balance, "aa": aa, "calibration": calibration, "mde": mde, "what_it_cannot_measure_es": CANNOT_MEASURE_ES}


# --- validation_rules.json ------------------------------------------------------------------------------------------------------------------


def _aggregated(rows: pd.DataFrame, rule_id: str) -> pd.DataFrame:
    """The rows of `rule_id` that its aggregation counts (plan section 6): ``source`` and ``latest`` read once, from the latest loaded run that recorded the rule (a cumulative count summed over the runs would
    count the earlier files again; project 03, D94), ``per_run`` every loaded run."""
    mine = rows[rows["rule_id"] == rule_id]
    if len(mine) and mine["aggregation"].iloc[0] in ("source", "latest"):
        mine = mine[mine["as_of"] == mine["as_of"].max()]
    return mine


def _rule_order(rule_id: str) -> tuple[str, int]:
    return rule_id[0], int(rule_id[1:])


def _validation(conn: sqlite3.Connection) -> dict[str, Any]:
    rows = _query(conn, "SELECT v.rule_id, v.name_es, v.severity, v.scope, v.aggregation, v.passed, v.rows_affected, d.as_of FROM validation_results v "
                        "JOIN deliveries d ON d.run_key = v.run_key AND d.status = 'loaded' ORDER BY d.as_of, v.rule_id")
    known = dict(RULES)
    for r in rows.drop_duplicates("rule_id").itertuples():
        known.setdefault(r.rule_id, (r.name_es, r.severity, r.scope, r.aggregation))
    rules = []
    for rule_id in sorted(known, key=_rule_order):
        name, severity, scope, aggregation = known[rule_id]
        mine = _aggregated(rows, rule_id)
        found = ["pasa" if bool(p) else ("falla" if s == "bloqueante" else "advertencia") for p, s in zip(mine["passed"], mine["severity"], strict=True)]
        status = "sin evaluar" if mine.empty else next(s for s in STATUS_WORST_FIRST if s in found)
        rules.append({"rule_id": rule_id, "name_es": name, "severity": severity, "scope": scope, "aggregation": aggregation, "status": status, "rows_affected": int(mine["rows_affected"].sum())})
    loaded, rejected = conn.execute("SELECT COALESCE(SUM(status = 'loaded'), 0), COALESCE(SUM(status = 'rejected'), 0) FROM deliveries").fetchone()
    return {"rules": rules, "totals": {"lines": int(conn.execute("SELECT COUNT(*) FROM lines").fetchone()[0]), "deliveries_loaded": int(loaded), "deliveries_rejected": int(rejected)}}


# --- reading, verifying and writing the set -------------------------------------------------------------------------------------------------


def _text(document: dict) -> str:
    return json.dumps(document, ensure_ascii=False, sort_keys=True, indent=1, allow_nan=False) + "\n"


def _read_checked(out_dir: Path) -> tuple[dict[str, bytes], dict[str, Any], list[str]]:
    out_dir = Path(out_dir)
    try:
        manifest = json.loads((out_dir / MANIFEST_FILE).read_text(encoding="utf-8"))
        files = manifest["files"]
        if not isinstance(files, dict) or not all(isinstance(e, dict) for e in files.values()):
            raise TypeError(MANIFEST_FILE)
    except FileNotFoundError:
        return {}, {}, [f"falta {MANIFEST_FILE} en la carpeta del sitio: el conjunto no es una exportación completa"]
    except (ValueError, KeyError, TypeError):
        return {}, {}, [f"{MANIFEST_FILE} de la carpeta del sitio no se puede leer"]
    problems = [] if sorted(files) == sorted(SITE_FILES) else [f"{MANIFEST_FILE} nombra {sorted(files)} y no los seis archivos del sitio"]
    out: dict[str, bytes] = {}
    for name in SITE_FILES:
        path = out_dir / name
        if not path.is_file():
            problems.append(f"falta {name} en la carpeta del sitio")
            continue
        data = path.read_bytes()
        entry = files.get(name, {})
        if len(data) != entry.get("bytes") or hashlib.sha256(data).hexdigest() != entry.get("sha256"):
            problems.append(f"{name} no es el que nombra {MANIFEST_FILE} (otro tamaño o SHA-256): los archivos no son de una misma exportación")
            continue
        try:
            document = json.loads(data.decode("utf-8"))
        except ValueError:
            problems.append(f"{name} no es un JSON legible")
            continue
        if any(document.get(key) != manifest.get(key) for key in ENVELOPE):
            problems.append(f"{name} no lleva el envoltorio de {MANIFEST_FILE} (la corrida, el instante o la fuente son otros)")
        out[name] = data
    return out, manifest, problems


def read_site(out_dir: Path) -> SiteFiles:
    """The six documents of `out_dir`, each read once and checked against ``manifest.json``; ``SiteSetError`` if they are not one export."""
    data, manifest, problems = _read_checked(out_dir)
    if problems:
        raise SiteSetError("; ".join(problems))
    documents = {name.removesuffix(".json"): json.loads(data[name].decode("utf-8")) for name in SITE_FILES}
    return SiteFiles(**documents, manifest=manifest)


def verify_site(out_dir: Path) -> list[str]:
    """What keeps the files of `out_dir` from being one export (``[]`` when the manifest names the six with their size and SHA-256 and each carries its envelope)."""
    return _read_checked(out_dir)[2]


def _manifest(header: dict[str, Any], payloads: Mapping[str, bytes]) -> str:
    return _text({**header, "files": {n: {"bytes": len(p), "sha256": hashlib.sha256(p).hexdigest()} for n, p in payloads.items()}})


def _write(documents: dict[str, dict[str, Any]], out_dir: Path, cap: int, header: dict[str, Any]) -> list[Path]:
    out_dir = Path(out_dir)
    payloads = {name: _text({**header, **documents[name]}).encode("utf-8") for name in SITE_FILES}
    total = sum(len(p) for p in payloads.values())
    if total > cap:
        raise SiteExportError(f"los archivos del sitio pesan {total} bytes y el tope es {cap}: no se escribió ninguno")
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / MANIFEST_FILE).unlink(missing_ok=True)         # a set being rewritten has no manifest until its last file is written
    paths = [write_atomic(out_dir / name, payloads[name]) for name in SITE_FILES]
    write_atomic(out_dir / MANIFEST_FILE, _manifest(header, payloads))
    logger.info("site export %s: %d files, %d bytes", header["run_key"], len(paths), total)
    return paths


def _context(conn: sqlite3.Connection, view: Any, seal_path: Path) -> tuple[dict[str, Any], dict[str, Any] | None, str]:
    summary, seal = reporting.build_summary(conn, view, seal_path=Path(seal_path)), registry.read_seal(Path(seal_path))
    return summary, seal, summary["evaluation_status"]


def export_site(conn: sqlite3.Connection, out_dir: Path, run: reporting.RunMeta, view: Any, *, seal_path: Path, private_dir: Path, max_total_bytes: int,
                source_counts: Mapping[str, Any] | None = None) -> list[Path]:
    """Write the six site files from the star model of `conn`, then ``manifest.json``; returns the six paths (``SITE_FILES`` order). Every document is built before the first file is replaced, and nothing is
    written if together they would pass `max_total_bytes` (``[site]``). `view` is the sealed view, as for ``export_star_schema``; `private_dir` is where the e-mail files are (only counted); `source_counts` are
    what the first build of the lines found in the source (``copies_removed`` and ``rows_by_sheet``), which the warehouse does not hold: without them those two figures are ``None``."""
    _require_star(conn)
    summary, seal, status = _context(conn, view, seal_path)
    documents = {"summary.json": _summary(conn, run, view, summary, seal, status), "data.json": _data(conn, view, source_counts), "algorithms.json": _algorithms(conn, view, status),
                 "operation.json": _operation(conn, view, Path(private_dir)), "control.json": _control(conn, view, seal, status), "validation_rules.json": _validation(conn)}
    return _write(documents, out_dir, max_total_bytes, _header(run, view))


def export_summary(conn: sqlite3.Connection, out_dir: Path, run: reporting.RunMeta, view: Any, *, seal_path: Path, max_total_bytes: int) -> Path:
    """Rewrite only ``summary.json`` (what closing a run changes: its status) and the manifest with it, the manifest removed before and written again last. The other five must be one export of this same run: over a
    folder that is not one, or is of another run, nothing is written (``SiteExportError``)."""
    _require_star(conn)
    header = _header(run, view)
    out_dir = Path(out_dir)
    problems = verify_site(out_dir)
    if not problems and json.loads((out_dir / MANIFEST_FILE).read_text(encoding="utf-8"))["run_key"] != header["run_key"]:
        problems = ["el conjunto es de otra corrida"]
    if problems:
        raise SiteExportError(f"no se reescribe el resumen: {'; '.join(problems)}; la tarea export escribe los seis archivos de nuevo")
    summary, seal, status = _context(conn, view, seal_path)
    payloads = {name: (out_dir / name).read_bytes() for name in SITE_FILES if name != "summary.json"}
    payloads["summary.json"] = _text({**header, **_summary(conn, run, view, summary, seal, status)}).encode("utf-8")
    ordered = {name: payloads[name] for name in SITE_FILES}
    total = sum(len(p) for p in ordered.values())
    if total > max_total_bytes:
        raise SiteExportError(f"los archivos del sitio pesan {total} bytes y el tope es {max_total_bytes}: no se escribió ninguno")
    (out_dir / MANIFEST_FILE).unlink(missing_ok=True)
    path = write_atomic(out_dir / "summary.json", payloads["summary.json"])
    write_atomic(out_dir / MANIFEST_FILE, _manifest(header, ordered))
    logger.info("site summary %s rewritten: %d bytes", header["run_key"], len(payloads["summary.json"]))
    return path


__all__ = ["MANIFEST_FILE", "SITE_FILES", "SiteExportError", "SiteFiles", "SiteSetError", "export_site", "export_summary", "read_site", "verify_site"]
