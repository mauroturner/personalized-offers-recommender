"""The evaluation as a task and the summary that tells it (RF18, RF19, AC23, AC24; risk item 1; plan section 16; decisions D16, D19, D21): ``evaluate`` runs at the close and writes the sealed rows and the test part
of the seal once; ``build_summary`` reads what there is, in this order of trust: the sealed rows of the warehouse, else the criteria **rebuilt from the seal** (a warehouse without the sealed rows: a new one, a quick
copy, the site's build), else nothing yet (before the close the summary says when the test is evaluated and shows the validation figures with their rounds).

The summary's table has the column «Lo que prueba el umbral»: the quantity that the criterion's threshold compares (``Criterion.tested_value_es``), never the point value of the same figure (the lesson A1 of
project 07). The star schema, the design and the site tell the same text for each verdict: they read it from here.
"""

from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from personaloffers import evaluation, registry, texts, warehouse
from personaloffers.evaluation import Criterion, CrmEvidence
from personaloffers.files import write_atomic

logger = logging.getLogger(__name__)

CRITERION_COLUMNS = ("criterion_id", "name_es", "tested_value", "tested_value_es", "point_value", "ci_low", "ci_high", "threshold_es", "passed", "seen_by_research", "seen_by_planner", "verdict_es")
RESULTS_START, RESULTS_END = "<!-- results:start -->", "<!-- results:end -->"
TABLES = ("eval_pairs", "eval_methods", "eval_segments", "eval_experiment", "eval_mde", "eval_balance", "eval_criteria", "eval_choice")
POST_SEAL_FILE = "post_seal_analysis.json"


@dataclass(frozen=True)
class RunMeta:
    run_key: str
    as_of: datetime


def criterion_dict(c: Criterion) -> dict[str, Any]:
    return {name: getattr(c, name) for name in CRITERION_COLUMNS}


# --- the rows of the evaluation ----------------------------------------------------------------------------------------------------------------------------------------


def _choice_rows(launch: Mapping[str, Any]) -> list[tuple]:
    """The rows of ``eval_choice`` from the validation part of the launch: each candidate in each round of the validation and in all of them (the figures are the ones that were sealed)."""
    rows = []
    for c in launch["validation"]["candidates"]:
        common = (c["name"], None, c["model"], int(c["size"]), c["regularization"], float(c["weight"]))
        total = [0, 0, 0, 0]
        for round_id, (pairs, hits, distinct, catalogue) in c["per_round"].items():
            total[0] += pairs
            total[1] += hits
            rows.append((common[0], round_id, *common[2:], pairs, hits, distinct, catalogue, hits / pairs if pairs else None, distinct / catalogue if catalogue else None, None, None, len(c["fit_rounds"])))
        for what, summed, sealed in (("pares", total[0], c["pairs"]), ("aciertos", total[1], c["hits"])):
            if summed != sealed:
                raise registry.SealError(f"los {what} por ronda del candidato {c['name']} suman {summed} y el sello dice {sealed} en «todas»: lo sellado no concuerda consigo mismo y no se escribe (runbook R7)")
        rows.append((common[0], "all", *common[2:], c["pairs"], c["hits"], 0, 0, c["hit_new"], c["coverage"], int(c["kept"]), int(c["chosen"]), len(c["fit_rounds"])))
    return rows


def _insert(conn: sqlite3.Connection, sql: str, rows: Sequence[tuple]) -> None:
    for start in range(0, len(rows), evaluation.INSERT_CHUNK):
        conn.executemany(sql, rows[start:start + evaluation.INSERT_CHUNK])


def store_result(conn: sqlite3.Connection, ranking: evaluation.RankingResult, result: evaluation.ExperimentResult, criteria: Sequence[Criterion], launch: Mapping[str, Any], state: str) -> dict[str, int]:
    """Write the rows of the evaluation in one transaction with the seal state of `state` (``first`` and ``repeat`` are the sealed ones, ``post_seal`` the apart one). A repetition finds its sealed rows already there and
    writes none of them: what is sealed is never replaced; a post-seal evaluation replaces the post-seal rows of the one before."""
    seal_state = "post_seal" if state == "post_seal" else "sealed"
    if seal_state == "sealed" and conn.execute("SELECT COUNT(*) FROM eval_criteria WHERE seal_state = 'sealed'").fetchone()[0] > 0:
        return {}
    f = result.figures
    pairs = [(r.round_id, int(r.customer_id), r.method, r.variant, seal_state, r.segment, int(r.hit), float(r.recall), float(r.precision), float(r.ndcg), int(r.test_products))
             for r in ranking.pairs.itertuples(index=False)]
    methods = [(m["method"], m["variant"], m["round_id"], seal_state, m["pairs"], m["hit_rate"], m["ci_low"], m["ci_high"], m["wilson_low"], m["wilson_high"], m["recall"], m["precision"], m["ndcg"], m["coverage"])
               for m in ranking.methods]
    segments = [(s["method"], s["variant"], s["segment"], seal_state, s["pairs"], s["customers"], s["hit_rate"], s["ci_low"], s["ci_high"]) for s in ranking.segments]
    experiment_rows = [(metric, kind, seal_state, t["diff"], t["p"], t["ci_low"], t["ci_high"], f["calibration"]["rejection"][f"{metric}_{kind}"]) for metric, tests in f["aa"].items() for kind, t in tests.items()]
    mde_rows = []
    for row in f["mde"]:
        for metric in ("m1", "m2"):
            mean = f["outcomes"][metric]["mean"]
            mde_rows.append((metric, row["holdout_share"], seal_state, row["holdout_size"], row[f"mde_{metric}"], row[f"mde_{metric}"] / mean if mean else None))
    balance = [(column, seal_state, v["offer_mean"], v["control_mean"], v["smd"]) for column, v in f["balance"]["per_covariate"].items()]
    criteria_rows = [(c.criterion_id, seal_state, c.name_es, c.tested_value, c.tested_value_es, c.point_value, c.ci_low, c.ci_high, c.threshold_es, None if c.passed is None else int(c.passed),
                      c.seen_by_research, c.seen_by_planner, c.verdict_es) for c in criteria]
    choice = [(row[0], row[1], seal_state, *row[2:]) for row in _choice_rows(launch)]
    conn.execute("BEGIN IMMEDIATE")
    try:
        if seal_state == "post_seal":
            for table in TABLES:
                conn.execute(f"DELETE FROM {table} WHERE seal_state = 'post_seal'")
        _insert(conn, "INSERT INTO eval_pairs (round_id, customer_id, method, variant, seal_state, segment, hit, recall, precision, ndcg, test_products) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", pairs)
        _insert(conn, "INSERT INTO eval_methods (method, variant, round_id, seal_state, pairs, hit_rate, ci_low, ci_high, wilson_low, wilson_high, recall, precision, ndcg, coverage) "
                      "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", methods)
        _insert(conn, "INSERT INTO eval_segments (method, variant, segment, seal_state, pairs, customers, hit_rate, ci_low, ci_high) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", segments)
        _insert(conn, "INSERT INTO eval_experiment (metric, kind, seal_state, aa_diff, aa_p, aa_ci_low, aa_ci_high, calibration_rejection) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", experiment_rows)
        _insert(conn, "INSERT INTO eval_mde (metric, holdout_share, seal_state, holdout_size, mde, mde_relative) VALUES (?, ?, ?, ?, ?, ?)", mde_rows)
        _insert(conn, "INSERT INTO eval_balance (covariate, seal_state, offer_mean, control_mean, smd) VALUES (?, ?, ?, ?, ?)", balance)
        _insert(conn, "INSERT INTO eval_criteria (criterion_id, seal_state, name_es, tested_value, tested_value_es, point_value, ci_low, ci_high, threshold_es, passed, seen_by_research, seen_by_planner, verdict_es) "
                      "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", criteria_rows)
        _insert(conn, "INSERT INTO eval_choice (candidate, round_id, seal_state, base_model, size, regularization, trend_weight, pairs, hits, distinct_products, catalogue, hit_new, coverage, kept, chosen, fit_rounds) "
                      "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", choice)
        conn.execute("COMMIT")
    except BaseException:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise
    return {"eval_pairs": len(pairs), "eval_methods": len(methods), "eval_segments": len(segments), "eval_experiment": len(experiment_rows), "eval_mde": len(mde_rows), "eval_balance": len(balance),
            "eval_criteria": len(criteria_rows), "eval_choice": len(choice)}


def evaluate(conn: sqlite3.Connection, view: Any, run: RunMeta, *, seal_path: Path, crm: CrmEvidence) -> dict[str, Any]:
    """The task ``evaluate`` of the close: the test is evaluated **once**. The state of the seal is decided first (``registry.EvaluationRefusedError`` before anything is read or written); then the rankings,
    the A/A and the criteria are computed from what was issued, the rows are stored and the test part of the seal is written (or reproduced, and a repetition that does not reproduce it is a ``SealMismatchError``)."""
    state = registry.check_test_evaluation(seal_path, view)
    lines = warehouse.read_lines(conn)
    ranking = evaluation.evaluate_rankings(conn, view, lines=lines)
    result = evaluation.evaluate_experiment(conn, view, lines=lines)
    figures = evaluation.figures_of(ranking, result, crm)
    criteria = evaluation.evaluate_criteria(figures, view)
    launch = (registry.read_seal(seal_path) or {})["launch"]
    rows = store_result(conn, ranking, result, criteria, launch, state)
    part = {"run_key": run.run_key, "as_of": run.as_of.strftime("%Y-%m-%d %H:%M:%S"), "config_sha256": registry.config_fingerprint(view), "criteria": [c.seal_entry() for c in criteria], "metrics": figures,
            "operation": {"rounds": figures["rounds"], "pairs": figures["pairs"], "customers": figures["customers"]}}
    outcome = registry.write_test_seal(seal_path, part)
    logger.info("evaluate: state %s, seal %s, rows %s", state, outcome, rows)
    return {"state": state, "seal": outcome, "criteria": criteria, "rows": rows, "figures": figures}


# --- the analyses after the seal (D49) -------------------------------------------------------------------------------------------------------------------------------


def post_seal_path(seal_path: Path) -> Path:
    """Where the analyses after the seal live: beside the seal, in a file of their own (never in it: the seal is not rewritten, D21)."""
    return Path(seal_path).with_name(POST_SEAL_FILE)


def write_post_seal_analysis(conn: sqlite3.Connection, view: Any, *, seal_path: Path) -> Path | None:
    """Write ``post_seal_analysis.json`` beside the seal, bound to its bytes (``seal_sha256``), once the seal has its test part; before, nothing (None). C05 with its four definitions
    (``evaluation.coverage_definitions``; B5 of the evaluation): the sealed one must give the seal's ``coverage_list`` to 6 decimals, or nothing is written (``SealError``: the analysis would not be of what was
    sealed). Each has its verdict against the sealed threshold but the plan's, which has none. A repetition writes the same bytes; the seal is never touched."""
    seal_path = Path(seal_path)
    seal = registry.read_seal(seal_path)
    if seal is None or seal.get("test") is None:
        return None
    found = evaluation.coverage_definitions(conn, view)
    sealed = seal["test"]["metrics"]["coverage_list"]
    if round(found["sealed"]["value"], 6) != round(sealed, 6):
        raise registry.SealError(f"la cobertura con la definición sellada da {found['sealed']['value']:.6f} y el sello dice {sealed:.6f}: el análisis no es de lo sellado y no se escribe (runbook R7)")
    limit = seal["launch"]["config"]["criteria"]["c05_min_coverage"]
    c05 = {**found, **{key: {**found[key], "threshold": limit, "passed": bool(found[key]["value"] >= limit)} for key in ("sealed", "preregistered")}}
    document = {"c05": c05, "config_sha256": seal["launch"]["config_sha256"], "seal_sha256": hashlib.sha256(seal_path.read_bytes()).hexdigest(),
                "note_es": "Se calculó después del sello, sobre las mismas listas emitidas y las mismas líneas; no reemplaza ninguna cifra sellada (D49)."}
    return write_atomic(post_seal_path(seal_path), json.dumps(document, indent=1, ensure_ascii=False, sort_keys=True, allow_nan=False) + "\n")


def read_post_seal_analysis(seal_path: Path) -> dict[str, Any] | None:
    """The analyses after the seal, or None when there are none or they were computed beside another seal (a stale file is never published)."""
    path, seal = post_seal_path(seal_path), Path(seal_path)
    if not path.is_file() or not seal.is_file():
        return None
    document = json.loads(path.read_text(encoding="utf-8"))
    if document.get("seal_sha256") != hashlib.sha256(seal.read_bytes()).hexdigest():
        logger.warning("%s was computed beside another seal: it is not published", path.name)
        return None
    return document


# --- the summary -----------------------------------------------------------------------------------------------------------------------------------------------------


def close_day(view: Any) -> str:
    return (view.calendar.close_last_day + timedelta(days=1)).isoformat()


def criteria_rows(conn: sqlite3.Connection, state: str = "sealed") -> list[dict[str, Any]]:
    """The criteria of the warehouse in the state `state`, in order, as dictionaries."""
    cursor = conn.execute(f"SELECT {', '.join(CRITERION_COLUMNS)} FROM eval_criteria WHERE seal_state = ? ORDER BY criterion_id", (state,))
    return [{**dict(zip(CRITERION_COLUMNS, row, strict=True)), "passed": None if row[8] is None else bool(row[8])} for row in cursor]


def pending_criteria(view: Any) -> list[dict[str, Any]]:
    """The ten criteria before the close: the threshold with its sealed limits and no verdict (``passed`` is None: nothing was evaluated)."""
    import dataclasses

    thresholds = texts.thresholds_from(dataclasses.asdict(view.criteria))
    reason = f"La prueba se evalúa con el cierre del {close_day(view)}."
    return [{"criterion_id": cid, "name_es": t.name_es, "tested_value": None, "tested_value_es": "sin dato" if cid != "C10" else "sin umbral", "point_value": None, "ci_low": None, "ci_high": None,
             "threshold_es": thresholds[cid], "passed": None, "seen_by_research": t.seen_by_research, "seen_by_planner": t.seen_by_planner, "verdict_es": reason} for cid, t in texts.CRITERIA.items()]


def _validation(launch: Mapping[str, Any]) -> dict[str, Any]:
    """The validation figures of the launch part, each with the rounds they were measured in: the chosen recipe and the best of each model without the trend (B4 to B6)."""
    part = launch["validation"]
    named = {c["name"]: c for c in part["candidates"]}

    def entry(name: str) -> dict[str, Any]:
        c = named[name]
        return {"name": name, "model": c["model"], "size": c["size"], "weight": c["weight"], "hit_new": c["hit_new"], "coverage": c["coverage"], "pairs": c["pairs"], "fit_rounds": c["fit_rounds"]}

    return {"rounds": part["rounds"], "candidates": len(part["candidates"]), "chosen": entry(part["recipe"]), "baselines": {key: entry(name) for key, name in sorted(part["baselines"].items())}}


def _headline(metrics: Mapping[str, Any]) -> dict[str, Any]:
    """The figures that the README and the site tell, from the seal's metrics (floats to 3 decimals by the writer of the site, not here)."""
    methods, diffs = metrics["methods"], metrics["diffs"]
    twenty = next((row for row in metrics["mde"] if abs(row["holdout_share"] - 0.2) < 1e-9), None)
    return {"rounds": metrics["rounds"], "pairs": metrics["pairs"], "hit_offer_list": methods["offer_list:unrestricted"]["hit_rate"], "hit_b2": methods["b2:unrestricted"]["hit_rate"],
            "hit_b3": methods["b3:unrestricted"]["hit_rate"], "hit_new_chosen": methods["chosen_discovery:new_only"]["hit_rate"], "hit_new_b2": methods["b2:new_only"]["hit_rate"],
            "coverage": metrics["coverage_list"], "max_abs_smd": metrics["balance"]["max_abs_smd"], "aa_p_m1": metrics["aa"]["m1"]["preregistered"]["p"], "aa_p_m2": metrics["aa"]["m2"]["preregistered"]["p"],
            "mde_m1_points_20": None if twenty is None else twenty["mde_m1"] * 100, "mde_m2_gbp_20": None if twenty is None else twenty["mde_m2"], "diff_list_b2_low": diffs["list_vs_b2"]["ci_low"]}


def build_summary(conn: sqlite3.Connection, view: Any, *, seal_path: Path) -> dict[str, Any]:
    """What the README, the model card, the design and the site tell: ``source`` is ``warehouse`` (the sealed rows are there), ``seal`` (C01-C10 rebuilt from the seal, each compared with its own entry to 6 decimals)
    or ``pending`` (the test is not evaluated yet). ``evaluation_status`` is ``pending``, ``sealed`` or ``post_seal`` (the current configuration is not the sealed one: M03). The validation figures come from the launch
    part, each with the rounds they were measured in."""
    document = registry.read_seal(seal_path)
    fingerprint = registry.config_fingerprint(view)
    summary: dict[str, Any] = {"close_day": close_day(view), "config_sha256": fingerprint, "source": "pending", "evaluation_status": "pending", "criteria": [], "validation": {}, "headline": None}
    if document is not None:
        summary["validation"] = _validation(document["launch"])
        summary["config_sha256"] = document["launch"]["config_sha256"]
        if document["launch"]["config_sha256"] != fingerprint:
            summary["evaluation_status"] = "post_seal"
    sealed_rows = criteria_rows(conn) if _has_table(conn, "eval_criteria") else []
    if sealed_rows:
        summary.update(source="warehouse", criteria=sealed_rows)
    elif document is not None and document.get("test") is not None:
        summary.update(source="seal", criteria=[criterion_dict(c) for c in evaluation.criteria_from_seal(document)])
    else:
        summary["criteria"] = pending_criteria(view)
    if summary["source"] != "pending" and document is not None and document.get("test") is not None:
        summary["headline"] = _headline(document["test"]["metrics"])
        if summary["evaluation_status"] == "pending":
            summary["evaluation_status"] = "sealed"
        analysis = read_post_seal_analysis(seal_path) if summary["evaluation_status"] == "sealed" else None
        if analysis is not None:
            summary["post_seal_analysis"] = analysis
    return summary


def _has_table(conn: sqlite3.Connection, name: str) -> bool:
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (name,)).fetchone() is not None


def _cell(text: Any) -> str:
    return str(text).replace("|", "\\|").replace("\n", " ")


def _validation_lines(validation: Mapping[str, Any]) -> list[str]:
    if not validation:
        return []
    rounds = validation["rounds"]
    span = f"{rounds[0]} a {rounds[-1]}" if rounds else "sin rondas"
    out = ["", f"Cifras de la validación (no son la prueba; se midieron en {len(rounds)} rondas, de {span}, con el hit@10 solo nuevos sobre los clientes que compraron):", ""]
    chosen = validation["chosen"]
    out.append(f"- Receta elegida entre {validation['candidates']} candidatas, `{chosen['name']}`: hit@10 solo nuevos {texts.es(chosen['hit_new'], 3)} sobre {texts.es(chosen['pairs'], 0)} pares, cobertura {texts.es(chosen['coverage'], 3)}.")
    for key, c in validation["baselines"].items():
        out.append(f"- Mejor parámetro de {key.upper()} sin tendencia, `{c['name']}`: hit@10 solo nuevos {texts.es(c['hit_new'], 3)}, cobertura {texts.es(c['coverage'], 3)}.")
    return out


def _post_seal_lines(analysis: Mapping[str, Any] | None) -> list[str]:
    if not analysis:
        return []
    c05 = analysis["c05"]
    return ["", "### Análisis posteriores al sello", "", "No reemplazan ninguna cifra sellada: se calcularon después del sello, sobre las mismas listas emitidas y las mismas líneas, y se publican al lado de lo "
            "sellado (D49).", "", f"- {texts.c05_preregistered_line(c05)}", f"- {texts.c05_p01_line(c05)}"]


def summary_markdown(summary: Mapping[str, Any]) -> str:
    """The summary as Markdown: the table of C01-C10 with the threshold, what the threshold tests and each verdict, what does not pass named with its number, the validation figures and, before the close, when the test
    is evaluated."""
    lines = ["## Resumen de la evaluación", ""]
    if summary["source"] == "pending":
        lines += [f"La prueba se evalúa con el cierre del {summary['close_day']}: hasta entonces no hay veredictos.", ""]
    else:
        failing = [c["criterion_id"] for c in summary["criteria"] if c["passed"] is False]
        lines += ["Todos los criterios con umbral se cumplen." if not failing else f"No se cumple: {', '.join(failing)}.", "",
                  "El archivo no tiene ofertas: ninguna cifra es el efecto de una oferta; las listas se miden por lo que anticipan y el grupo de control, por cómo quedó armado y comprobado.", ""]
    lines += ["| ID | Criterio | Umbral | Lo que prueba el umbral | Veredicto |", "| --- | --- | --- | --- | --- |"]
    for c in summary["criteria"]:
        lines.append(f"| {c['criterion_id']} | {_cell(c['name_es'])} | {_cell(c['threshold_es'])} | {_cell(c['tested_value_es'])} | {_cell(c['verdict_es'])} |")
    lines += _post_seal_lines(summary.get("post_seal_analysis"))
    lines += _validation_lines(summary.get("validation") or {})
    return "\n".join(lines) + "\n"


def summary_json(summary: Mapping[str, Any]) -> str:
    return json.dumps(summary, indent=1, ensure_ascii=False, sort_keys=True, allow_nan=False) + "\n"


def write_summary(summary: Mapping[str, Any], reports_dir: Path) -> tuple[Path, Path]:
    """Write ``evaluation_summary.json`` and ``evaluation_summary.md`` into `reports_dir` (each atomically) and return their paths."""
    folder = Path(reports_dir)
    return write_atomic(folder / "evaluation_summary.json", summary_json(summary)), write_atomic(folder / "evaluation_summary.md", summary_markdown(summary))


def replace_block(text: str, name: str, start: str, end: str, content: str) -> str:
    """`text` with what lies between the markers `start` and `end` replaced by `content`: each marker once and in order, or a ``ValueError`` that names the file (`name`). A second use with the same content changes nothing."""
    first, last = text.find(start), text.find(end)
    if text.count(start) != 1 or text.count(end) != 1 or last < first:
        raise ValueError(f"{name} no tiene los marcadores {start} y {end}, una vez cada uno y en ese orden")
    return text[: first + len(start)] + "\n" + content.strip("\n") + "\n" + text[last:]
