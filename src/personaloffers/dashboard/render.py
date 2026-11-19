"""The HTML design of the Power BI report, generated from the semantic model and the exported Parquet (RF21, AC27; risk items 3 and 6; plan section 20; decisions D16, D30, D37). Adapted from project 07's
``dashboard/render.py``; it is not imported from it.

One self-contained page (inline CSS, inline SVG, no scripts, no fonts or images from the network) with the steps to build the report in Power BI Desktop, the diagram of the model, the relationships, the Power Query code
of each table, the DAX measures and the five pages placed on a 12 x 9 grid, each visual with a preview drawn from the exported tables. Nothing here is typed by hand twice: change ``semantic_model.py`` and render again.

Rules for what a preview shows. Every text that comes from the data goes through ``html.escape``. The previews are the figures of the exported tables with no slicer applied: the document says that no measure was run
(there is no Power BI here), so a card is what the table says, not what the DAX would give. The test shows its **sealed** rows and, when there are none, says that it is pending; the verdict of each criterion is the
text of the exported table, which is the summary's. A cell that was hidden for having fewer customers than the minimum (D30) is shown as «oculta», never as a number. Every page carries the legend that the archive has no
offers, and nothing in the page shows an effect of an offer. The file is written through ``files.write_atomic``.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from html import escape
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq

from personaloffers import texts
from personaloffers.dashboard import svg
from personaloffers.dashboard.semantic_model import LEGEND, NOT_FILTERED, PAGE_COLUMNS, PAGE_ROWS, Page, SemanticModel, Visual, dax_measure_refs, validate_model
from personaloffers.files import write_atomic
from personaloffers.reporting import RunMeta

logger = logging.getLogger(__name__)

PAGE_WIDTH_PX, PAGE_HEIGHT_PX = 1280, 720
CELL_W, CELL_H = PAGE_WIDTH_PX / PAGE_COLUMNS, PAGE_HEIGHT_PX / PAGE_ROWS
HEADER_PX = 26
TABLE_ROWS = 9              # the most rows a table preview shows
TITLE = "Diseño del tablero de Power BI: una oferta para cada cliente, con un grupo de control listo para medir"
SECTIONS = (
    ("armado", "Cómo armarlo en Power BI Desktop"), ("modelo", "El modelo en estrella"), ("relaciones", "Relaciones"), ("consultas", "Power Query: una consulta por tabla"),
    ("medidas", "Medidas DAX"), ("paginas", "Las cinco páginas"), ("fuente", "Fuente y licencia"),
)
KIND_ES = {"slicer": "Segmentador", "card": "Tarjeta", "lineChart": "Gráfico de líneas", "barChart": "Gráfico de barras", "table": "Tabla"}
DASH = "—"
HIDDEN = "oculta"
CSS = """
:root{color-scheme:light;--surface:#fcfcfb;--panel:#f3f2ef;--text:#0b0b0b;--text-2:#52514e;--muted:#6f6e69;--line:#d9d8d3;--accent:#256abf;
--series-1:#2a78d6;--series-2:#eb6834;--series-3:#1baf7a;--series-4:#eda100;--series-5:#e87ba4;--series-6:#008300;--series-7:#6250d6;--series-8:#e34948}
@media (prefers-color-scheme:dark){:root:where(:not([data-theme="light"])){color-scheme:dark;--surface:#1a1a19;--panel:#242422;--text:#f0efec;--text-2:#c3c2b7;--muted:#a3a299;--line:#3a3a37;--accent:#6da7ec;
--series-1:#3987e5;--series-2:#d95926;--series-3:#199e70;--series-4:#c98500;--series-5:#d55181;--series-6:#008300;--series-7:#9085e9;--series-8:#e66767}}
:root[data-theme="dark"]{color-scheme:dark;--surface:#1a1a19;--panel:#242422;--text:#f0efec;--text-2:#c3c2b7;--muted:#a3a299;--line:#3a3a37;--accent:#6da7ec;
--series-1:#3987e5;--series-2:#d95926;--series-3:#199e70;--series-4:#c98500;--series-5:#d55181;--series-6:#008300;--series-7:#9085e9;--series-8:#e66767}
*{box-sizing:border-box}
body{margin:0;background:var(--surface);color:var(--text);font:16px/1.55 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
main{max-width:1180px;margin:0 auto;padding:24px 16px 64px}
h1{font-size:1.6rem;line-height:1.25;margin:0 0 4px}h2{font-size:1.3rem;margin:48px 0 8px;padding-top:8px;border-top:1px solid var(--line)}
h3{font-size:1.05rem;margin:28px 0 8px}p,li{max-width:78ch}a{color:var(--accent)}
.lead{color:var(--text-2);margin:0 0 16px}.meta{display:flex;flex-wrap:wrap;gap:8px 24px;color:var(--text-2);font-size:.9rem;margin:12px 0}
nav ul{display:flex;flex-wrap:wrap;gap:4px 16px;padding:0;list-style:none;margin:16px 0}
code,pre{font-family:ui-monospace,SFMono-Regular,Consolas,monospace;font-size:.85rem}
pre{background:var(--panel);border:1px solid var(--line);border-radius:6px;padding:10px 12px;overflow-x:auto;margin:6px 0;white-space:pre}
table{border-collapse:collapse;width:100%;font-size:.88rem}th,td{border-bottom:1px solid var(--line);padding:5px 8px;text-align:left;vertical-align:top}
th{color:var(--text-2);font-weight:600;background:var(--surface)}td.num,th.num{text-align:right;font-variant-numeric:tabular-nums}
.scroll{overflow-x:auto}.warn{border-left:3px solid var(--series-4);padding:4px 12px;background:var(--panel);margin:12px 0}
.legend{border:1px solid var(--line);border-radius:6px;padding:4px 10px;background:var(--panel);font-size:.85rem;color:var(--text-2);margin:6px 0}
.model-svg{width:100%;height:auto;display:block}.model-svg .box{fill:var(--panel);stroke:var(--line)}.model-svg .dim{stroke:var(--series-1)}
.model-svg .fact{stroke:var(--series-2)}.model-svg text{fill:var(--text);font-size:12px}.model-svg .small{fill:var(--text-2);font-size:10px}
.model-svg .rel{stroke:var(--muted);stroke-width:1;fill:none;opacity:.55}.model-svg .card{font-weight:700;fill:var(--accent)}
.canvas-wrap{overflow-x:auto;border:1px solid var(--line);border-radius:8px;background:var(--panel);padding:8px}
.canvas{display:grid;grid-template-columns:repeat(12,1fr);grid-template-rows:repeat(9,1fr);gap:6px;aspect-ratio:16/9;min-width:960px;max-width:1280px}
.visual{background:var(--surface);border:1px solid var(--line);border-radius:6px;overflow:hidden;display:flex;flex-direction:column;min-width:0;min-height:0}
.visual header{display:flex;justify-content:space-between;gap:6px;padding:2px 8px;font-size:.75rem;color:var(--text-2);height:26px;align-items:center}
.visual header b{color:var(--text);font-weight:600;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.visual header span{white-space:nowrap;color:var(--muted)}
.visual .body{flex:1;min-height:0;padding:0 8px 3px;overflow:hidden;font-size:.75rem}.visual .body svg{max-width:100%;height:auto;display:block}
.big{font-size:1.2rem;font-weight:700;line-height:1.15;font-variant-numeric:tabular-nums;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.sub{color:var(--muted);font-size:.65rem;line-height:1.1}
.chips{display:flex;flex-wrap:nowrap;gap:3px;overflow:hidden}.chip{white-space:nowrap;border:1px solid var(--line);border-radius:10px;padding:0 6px;font-size:.7rem;color:var(--text-2)}
.visual table{font-size:.7rem}.visual th,.visual td{padding:1px 5px}.rows p{margin:1px 0;font-size:.75rem}
svg .svg-grid{stroke:var(--line);stroke-width:1}svg .svg-axis{stroke:var(--muted);stroke-width:1}
svg .svg-tick,svg .svg-legend,svg .svg-note,svg .svg-value{fill:var(--text-2);font-size:10px}svg .svg-value{fill:var(--text)}
svg .svg-hit{fill:transparent}svg .svg-hit:hover{fill:var(--text);fill-opacity:.15}
.placement td:first-child{white-space:nowrap}
@media print{.canvas-wrap{break-inside:avoid}body{font-size:12px}}
"""


# --- data ---------------------------------------------------------------------------------------------------------------------


class _Data:
    """The exported tables the previews are drawn from (a missing file is an empty table with its columns) and the run they were made by."""

    def __init__(self, parquet_dir: Path, model: SemanticModel) -> None:
        self.t: dict[str, pd.DataFrame] = {}
        for table in model.public:
            path = Path(parquet_dir) / f"{table.name}.parquet"
            self.t[table.name] = pd.read_parquet(path) if path.is_file() else pd.DataFrame(columns=list(table.column_names))
        path = Path(parquet_dir) / "dim_pipeline_run.parquet"
        metadata = pq.read_schema(path).metadata or {} if path.is_file() else {}
        self.config_sha256 = metadata.get(b"personaloffers.config_sha256", b"").decode("utf-8", "replace") or DASH
        self.method_es = dict(zip(self.t["dim_method"]["method_key"], self.t["dim_method"]["label_es"], strict=True))
        self.variant_es = dict(zip(self.t["dim_variant"]["variant_key"], self.t["dim_variant"]["label_es"], strict=True))
        self.source_es = dict(zip(self.t["dim_source"]["source_key"], self.t["dim_source"]["label_es"], strict=True))
        self.segment_es = dict(zip(self.t["dim_segment"]["segment_key"], self.t["dim_segment"]["label_es"], strict=True))
        self.covariate_es = dict(zip(self.t["dim_covariate"]["covariate_key"], self.t["dim_covariate"]["label_es"], strict=True))
        self.product_es = dict(zip(self.t["dim_product"]["product_key"], self.t["dim_product"]["description_es"], strict=True))

    def sealed(self, name: str) -> pd.DataFrame:
        """The sealed rows of a fact. A row that is not sealed is never a figure of the test."""
        frame = self.t[name]
        return frame[frame["seal_state"] == "sealed"] if "seal_state" in frame.columns else frame


def _missing(value) -> bool:
    return value is None or bool(pd.isna(value))


def _fmt(value, digits: int = 3) -> str:
    return HIDDEN if _missing(value) else texts.es(float(value), digits)


def _int(value) -> str:
    return HIDDEN if _missing(value) else texts.es(float(value), 0)


def _pct(value, digits: int = 1) -> str:
    return HIDDEN if _missing(value) else texts.es(float(value), digits, percent=True)


def _when(value) -> str:
    return DASH if _missing(value) else pd.Timestamp(value).strftime("%Y-%m-%d %H:%M")


def _table_html(headers: list[str], rows: list[list[str]], numeric: set[int] = frozenset()) -> str:
    """A table; every cell is escaped."""
    head = "".join(f'<th{" class=num" if i in numeric else ""}>{escape(h)}</th>' for i, h in enumerate(headers))
    body = "".join("<tr>" + "".join(f'<td{" class=num" if i in numeric else ""}>{escape(str(c))}</td>' for i, c in enumerate(row)) + "</tr>" for row in rows)
    return f"<table><thead><tr>{head}</tr></thead><tbody>{body or '<tr><td>Sin datos</td></tr>'}</tbody></table>"


def _size(v: Visual) -> tuple[int, int]:
    return max(int(v.w * CELL_W - 22), 60), max(int(v.h * CELL_H - HEADER_PX - 12), 40)


def _card(big: str, sub: str = "") -> str:
    return f'<div class="big">{escape(big)}</div><div class="sub">{escape(sub)}</div>'


def _note(text: str) -> str:
    return f'<div class="rows"><p>{escape(text)}</p></div>'


def _caption(text: str) -> str:
    return f'<div class="sub">{escape(text)}</div>'


# --- previews ---------------------------------------------------------------------------------------------------------------------


def _slicer(data: _Data, field: str) -> str:
    table, column = field.split("[")[0], field.split("[")[1].rstrip("]")
    values = data.t[table][column].dropna() if column in data.t[table].columns else pd.Series(dtype=object)
    shown = sorted({str(x) for x in values})
    chips = "".join(f'<span class="chip">{escape(x)}</span>' for x in shown[:3])
    more = f'<span class="chip">+{len(shown) - 3}</span>' if len(shown) > 3 else ""
    return f'<div class="chips">{chips or "Sin datos"}{more}</div>'


def _total(frame: pd.DataFrame, column: str):
    """The sum of a column of a table where some cells are hidden: None when every cell is."""
    values = frame[column].dropna()
    return None if values.empty else values.sum()


def _cards(data: _Data) -> dict:
    ops, rules, runs = data.t["fact_round_ops"], data.t["fact_validation"], data.t["dim_pipeline_run"]
    ok = runs[runs["status"] == "ok"]
    balance = data.sealed("fact_balance")
    blocking = rules[(rules["severity"] == "bloqueante") & (rules["status"] == "falla")]
    rounds = f"en {len(ops)} rondas"
    return {
        "[Clientes en la base]": lambda: _card(_int(_total(ops, "base")), rounds), "[Reciben oferta]": lambda: _card(_int(_total(ops, "offer")), "reciben la lista de su ronda"),
        "[Grupo de control]": lambda: _card(_int(_total(ops, "control")), "apartados: su lista se arma y no se entrega"), "[Listas entregadas]": lambda: _card(_int(_total(ops, "delivered")), "leídas de vuelta iguales del CRM"),
        "[Parte de reserva]": lambda: _card(_pct(ops["fallback_share"].mean() if len(ops) else None), "de los productos son de lo más vendido de 28 días"),
        "[Mayor diferencia estandarizada]": lambda: _card(_fmt(balance["smd"].abs().max() if len(balance) else None, 3), "entre las cinco covariables (C06)"),
        "[Reglas bloqueantes fallidas]": lambda: _card(_int(len(blocking)), "en las corridas cargadas"),
        "[Última fecha de cálculo]": lambda: _card(_when(ok["as_of"].max()) if len(ok) else DASH, "última corrida terminada bien"),
    }


def _round_bars(data: _Data, v: Visual) -> str:
    ops = data.t["fact_round_ops"].sort_values("round_key")
    groups = [(r.round_key[-5:], {"reciben la lista": float(r.offer), "control": float(r.control)}) for r in ops.itertuples() if not _missing(r.offer)]
    width, height = _size(v)
    return svg.grouped_bar_chart(groups, width, height - 14, v.title_es) + _caption("Clientes de cada ronda; una ronda con una parte oculta no se dibuja.")


def _offered(data: _Data) -> str:
    frame = data.t["fact_offer_product"].sort_values(["offered_to", "product_key"], ascending=[False, True]).head(TABLE_ROWS)
    rows = [[data.product_es.get(r.product_key, r.product_key), data.source_es.get(r.source_key, r.source_key), _int(r.offered_to), _int(r.bought_by)] for r in frame.itertuples()]
    return _table_html(["Producto", "Origen", "Ofrecido a", "Comprado por"], rows, {2, 3}) + _caption("Los más ofrecidos de todas las rondas; una compra con pocos clientes está oculta.")


def _hit_bars(data: _Data, v: Visual) -> str:
    totals = data.sealed("fact_method_total")
    totals = totals[totals["variant_key"] == "unrestricted"].dropna(subset=["hit_rate"])
    width, height = _size(v)
    return svg.bar_chart([(data.method_es.get(r.method_key, r.method_key), float(r.hit_rate) * 100) for r in totals.itertuples()], width, height - 14, v.title_es, unit="%") + _caption(
        "hit@10 de la prueba, sin restricción, sobre los clientes que compraron (el intervalo de cada uno está en la tabla de criterios).")


def _hit_lines(data: _Data, v: Visual) -> str:
    rounds = data.sealed("fact_method_round")
    rounds = rounds[(rounds["variant_key"] == "unrestricted") & rounds["method_key"].isin(["offer_list", "b2", "b3"])].sort_values("round_key")
    order = sorted(rounds["round_key"].unique())
    series = {data.method_es.get(m, m): [(float(order.index(r.round_key)), float(r.hit_rate) * 100) for r in part.itertuples() if not _missing(r.hit_rate)] for m, part in rounds.groupby("method_key")}
    width, height = _size(v)
    return svg.line_chart(series, width, height - 14, v.title_es, unit="%") + _caption("hit@10 por ronda de la lista, de lo más vendido (B2) y de la recompra propia (B3).")


def _metrics_table(data: _Data) -> str:
    totals = data.sealed("fact_method_total")
    totals = totals[totals["variant_key"] == "unrestricted"].sort_values("method_key")
    rows = [[data.method_es.get(r.method_key, r.method_key), _pct(r.recall), _pct(r.precision), _pct(r.ndcg)] for r in totals.itertuples()]
    return _table_html(["Método", "recall@10", "precisión@10", "NDCG@10"], rows, {1, 2, 3}) + _caption("Sin restricción, sobre la prueba.")


def _segment_bars(data: _Data, v: Visual) -> str:
    segments = data.sealed("fact_segment")
    segments = segments[(segments["variant_key"] == "unrestricted") & segments["method_key"].isin(["offer_list", "b2", "b3"])]
    groups = []
    for segment, part in segments.groupby("segment_key"):
        groups.append((data.segment_es.get(segment, segment)[:24], {data.method_es.get(r.method_key, r.method_key): float(r.hit_rate) * 100 for r in part.itertuples() if not _missing(r.hit_rate)}))
    width, height = _size(v)
    return svg.grouped_bar_chart(groups, width, height - 14, v.title_es) + _caption("hit@10 (%) por segmento; un segmento con pocos clientes está oculto.")


def _new_bars(data: _Data, v: Visual) -> str:
    totals = data.sealed("fact_method_total")
    totals = totals[totals["variant_key"] == "new_only"].dropna(subset=["hit_rate"])
    width, height = _size(v)
    return svg.bar_chart([(data.method_es.get(r.method_key, r.method_key), float(r.hit_rate) * 100) for r in totals.itertuples()], width, height - 14, v.title_es, unit="%") + _caption(
        "hit@10 con la lista armada solo con productos que el cliente nunca compró.")


def _coverage_bars(data: _Data, v: Visual) -> str:
    totals = data.sealed("fact_method_total")
    totals = totals[totals["variant_key"] == "unrestricted"].dropna(subset=["coverage"])
    width, height = _size(v)
    return svg.bar_chart([(data.method_es.get(r.method_key, r.method_key), float(r.coverage)) for r in totals.itertuples()], width, height - 14, v.title_es) + _caption(
        "Productos distintos de las listas sobre los comprados en el último año, media de la prueba.")


def _choice_table(data: _Data) -> str:
    choice = data.t["fact_choice"].sort_values(["chosen", "val_hit_new"], ascending=[False, False]).head(TABLE_ROWS)
    rows = [[r.candidate, _fmt(r.val_hit_new, 3), _fmt(r.val_coverage, 3), "sí" if r.kept else "no", "sí" if r.chosen else "no", _int(r.fit_rounds)] for r in choice.itertuples()]
    return _table_html(["Receta", "hit@10 solo nuevos", "Cobertura", "Conserva", "Elegida", "Rondas"], rows, {1, 2, 5}) + _caption(f"Las {len(data.t['fact_choice'])} recetas de la validación; se muestran las mejores.")


def _rules_table(data: _Data) -> str:
    rules = data.t["fact_rule"].sort_values(["rule_lift", "support"], ascending=[False, False]).head(TABLE_ROWS)
    rows = [[r.antecedent_es, r.consequent_es, _int(r.support), _fmt(r.confidence, 2), _fmt(r.rule_lift, 2)] for r in rules.itertuples()]
    return _table_html(["Producto de partida", "Producto que anticipa", "Facturas", "Confianza", "rule_lift"], rows, {2, 3, 4})


def _balance_table(data: _Data) -> str:
    balance = data.sealed("fact_balance").sort_values("covariate_key")
    covariates = data.t["dim_covariate"].set_index("covariate_key")
    rows = [[data.covariate_es.get(r.covariate_key, r.covariate_key), covariates.loc[r.covariate_key, "unit_es"], _fmt(r.offer_mean, 2), _fmt(r.control_mean, 2), _fmt(r.smd, 3)] for r in balance.itertuples()]
    return _table_html(["Covariable", "Unidad", "Media del grupo de oferta", "Media del control", "Diferencia estandarizada"], rows, {2, 3, 4}) + _caption("En la cohorte del lanzamiento; el criterio C06 pide que ninguna pase de 0,10.")


def _aa_table(data: _Data) -> str:
    experiment = data.sealed("fact_experiment")
    experiment = experiment[experiment["test"] == "preregistered"].sort_values("metric")
    rows = [[{"m1": "M1: semanas con compra", "m2": "M2: gasto en libras"}.get(r.metric, r.metric), _fmt(r.aa_p, 3), _pct(r.calibration_rejection)] for r in experiment.itertuples()]
    return _table_html(["Resultado", "p del A/A sellado", "Rechazo en los sorteos nuevos"], rows, {1, 2}) + _caption("Sin ofertas, la diferencia entre los grupos es ruido: el p debe ser 0,05 o más y el rechazo, de 3,1 % a 6,9 %.")


def _mde_table(data: _Data) -> str:
    mde = data.sealed("fact_mde").sort_values(["metric", "holdout_share"])
    rows = [[{"m1": "M1 (puntos de semanas con compra)", "m2": "M2 (libras)"}.get(r.metric, r.metric), _pct(r.holdout_share, 0), _int(r.holdout_size),
             _fmt(float(r.mde) * 100 if r.metric == "m1" and not _missing(r.mde) else r.mde, 2)] for r in mde.itertuples()]
    return _table_html(["Resultado", "Control", "Clientes", "Menor efecto detectable"], rows, {1, 2, 3}) + _caption("Lo que una operación de este tamaño podría ver: no es un resultado.")


def _criteria(data: _Data) -> str:
    summary = data.sealed("fact_evaluation_summary").sort_values("criterion_key")
    if summary.empty:
        return _note("La prueba se evalúa con el cierre: los criterios quedan pendientes hasta entonces.")
    criteria = data.t["dim_criterion"].set_index("criterion_key")
    rows = [[r.criterion_key, criteria.loc[r.criterion_key, "name_es"], criteria.loc[r.criterion_key, "threshold_es"], r.tested_value_es, r.seen_by_research, r.seen_by_planner,
             "informativo" if _missing(r.passed) else ("sí" if r.passed else "no"), r.verdict_es] for r in summary.itertuples()]
    return _table_html(["Criterio", "Nombre", "Umbral", "Lo que prueba el umbral", "Investigación", "Plan", "Cumple", "Veredicto"], rows)


def _rules(data: _Data) -> str:
    rules = data.t["fact_validation"].sort_values(["run_key", "rule_id"])
    return _table_html(["Corrida", "Regla", "Nombre", "Severidad", "Filas", "Estado"], [[r.run_key, r.rule_id, r.name_es, r.severity, _int(r.rows_affected), r.status] for r in rules.head(TABLE_ROWS).itertuples()], {4})


def _runs(data: _Data) -> str:
    runs = data.t["dim_pipeline_run"].sort_values("as_of", ascending=False)
    return _table_html(["Corrida", "Entrega", "Instante de cálculo", "Estado", "Mensaje"], [[r.run_key, r.delivery_id or DASH, _when(r.as_of), r.status, r.message or ""] for r in runs.head(TABLE_ROWS).itertuples()])


NOT_FILTERED_MARK = NOT_FILTERED[:NOT_FILTERED.index("{")]   # " (no lo filtra": what every note starts with, before its fields


def _bare_title(title: str) -> str:
    """A visual's title without the note that says what its slicers do not filter (``semantic_model.NOT_FILTERED``): the key of its preview."""
    return title.split(NOT_FILTERED_MARK, 1)[0]


def _makers(data: _Data, v: Visual) -> dict[str, Callable[[], str]]:
    """The drawing of each visual that is not a slicer or a card, by its title without the not-filtered note."""
    return {
        "Clientes que reciben la lista y clientes de control, por ronda": lambda: _round_bars(data, v), "Los productos más ofrecidos, por origen": lambda: _offered(data),
        "Acierto de cada método, con su intervalo": lambda: _hit_bars(data, v), "Acierto por ronda de cada método": lambda: _hit_lines(data, v), "Recall, precisión y NDCG de cada método": lambda: _metrics_table(data),
        "Acierto por segmento": lambda: _segment_bars(data, v), "Acierto solo con productos nuevos, de cada método": lambda: _new_bars(data, v),
        "Cobertura de las listas de cada método": lambda: _coverage_bars(data, v), "La elección de la receta en la validación": lambda: _choice_table(data),
        "Las reglas de pares con mayor rule_lift": lambda: _rules_table(data), "El equilibrio del control, covariable por covariable": lambda: _balance_table(data),
        "El A/A del control sellado: p y rechazo de la calibración": lambda: _aa_table(data), "Lo que una operación de este tamaño podría ver": lambda: _mde_table(data),
        "Criterios C01-C10": lambda: _criteria(data), "Reglas de validación": lambda: _rules(data), "Corridas": lambda: _runs(data),
    }


def _preview(data: _Data, v: Visual) -> str:
    """The body of a visual: its drawing or figure from the exported tables."""
    if v.kind == "slicer":
        return _slicer(data, v.fields[0])
    if v.kind == "card":
        maker = _cards(data).get(v.fields[0])
        return maker() if maker else _note("Se calcula en Power BI.")
    maker = _makers(data, v).get(_bare_title(v.title_es))
    return maker() if maker else _note("Se calcula en Power BI.")


# --- sections -----------------------------------------------------------------------------------------------------------------


def _steps(model: SemanticModel) -> str:
    steps = [
        "Instale Power BI Desktop (gratuito, solo para Windows) y abra un informe en blanco.",
        "Cree un parámetro de texto llamado <code>CarpetaSalidas</code> con la ruta de <code>outputs\\powerbi</code>.",
        f"Cree una consulta por tabla publicada ({len(model.public)}) con el código de la sección «Power Query»; deje el nombre de la consulta igual al de la tabla. "
        "La tabla <code>fact_offer_customer</code> tiene números de cliente: está en <code>outputs\\private</code>, no se versiona y no hace falta para este diseño.",
        f"En la vista de modelo, cree las {len(model.relationships)} relaciones de la tabla «Relaciones»: uno a varios (1:*), filtro único de la dimensión al hecho, todas activas. "
        "Los hechos sin clave compartida (<code>fact_choice</code>, <code>fact_experiment</code>, <code>fact_mde</code>, <code>fact_rule</code>) no tienen relación: alimentan sus propios visuales; "
        "<code>dim_date</code> es un calendario sin relaciones.",
        "Marque <code>dim_date</code> como tabla de fechas con la columna <code>date</code>.",
        "Cree una tabla vacía llamada <code>_Medidas</code> y agregue en ella las medidas de la sección «Medidas DAX», con su formato.",
        f"Cree las {len(model.pages)} páginas a 1280 × 720 px y ubique cada visual según la grilla de {PAGE_COLUMNS} columnas por {PAGE_ROWS} filas; ponga en cada una la leyenda «{LEGEND}».",
        "Guarde el informe como <code>.pbix</code>. Cuando corra el flujo, «Actualizar» vuelve a leer los mismos archivos.",
    ]
    return "<ol>" + "".join(f"<li>{s}</li>" for s in steps) + "</ol>"


def _diagram(model: SemanticModel) -> str:
    """Related dimensions above, the facts with relationships in the middle, the run table below, and the tables without relationships last (the private one is not drawn)."""
    width, height = 1500, 700
    public = [t for t in model.tables if not t.private]
    related = {r.dim_table for r in model.relationships} | {r.fact_table for r in model.relationships if not model.table(r.fact_table).private}
    top = [t.name for t in public if t.kind == "dimension" and t.name in related and t.name != "dim_pipeline_run"]
    bottom = [t.name for t in public if t.name == "dim_pipeline_run" and t.name in related]
    facts = [t.name for t in public if t.kind == "fact" and t.name in related]
    alone = [t.name for t in public if t.name not in related]
    boxes: dict[str, tuple[float, float, float, float]] = {}
    for names, y, w, h in ((top, 24, 150, 46), (facts, 250, 150, 56), (bottom, 420, 170, 46), (alone, 590, 150, 46)):
        w = min(w, (width - 16 * (len(names) + 1)) / max(len(names), 1))
        gap = (width - w * len(names)) / (len(names) + 1) if names else 0
        for i, name in enumerate(names):
            boxes[name] = (gap + i * (w + gap), y, w, h)
    dims = sum(1 for t in public if t.kind == "dimension")
    nfacts = sum(1 for t in public if t.kind == "fact")
    out = [f'<svg class="model-svg" viewBox="0 0 {width} {height}" role="img" aria-label="Diagrama del modelo en estrella: {dims} dimensiones y {nfacts} hechos publicados">',
           '<defs><marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto"><path d="M0,0 L10,5 L0,10 z" fill="var(--muted)"/></marker></defs>']
    for r in model.relationships:
        if r.fact_table not in boxes:
            continue
        dx, dy, dw, dh = boxes[r.dim_table]
        fx, fy, fw, fh = boxes[r.fact_table]
        up = r.dim_table in top
        x1, y1 = dx + dw / 2, (dy + dh if up else dy)
        x2, y2 = fx + fw / 2, (fy if up else fy + fh)
        out.append(f'<line class="rel" x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" marker-end="url(#arrow)">'
                   f'<title>{escape(r.rel_id)}: {escape(r.dim_table)}[{escape(r.dim_column)}] 1 → * {escape(r.fact_table)}[{escape(r.fact_column)}]</title></line>')
        sign = 1 if up else -1
        out.append(f'<text class="card" x="{x1 + 3:.1f}" y="{y1 + sign * 13:.1f}">1</text><text class="card" x="{x2 + 3:.1f}" y="{y2 - sign * 6:.1f}">*</text>')
    for name, (x, y, w, h) in boxes.items():
        table = model.table(name)
        size = ' font-size="9"' if len(name) > 15 else ""
        key = ", ".join(table.key) if table.kind == "dimension" else f"{len(table.columns)} columnas"
        out.append(f'<rect class="box {"dim" if table.kind == "dimension" else "fact"}" x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h}" rx="6"/>'
                   f'<text x="{x + w / 2:.1f}" y="{y + h / 2 - 2:.1f}" text-anchor="middle"{size}>{escape(name)}</text>'
                   f'<text class="small" x="{x + w / 2:.1f}" y="{y + h / 2 + 12:.1f}" text-anchor="middle">{escape(key)}</text>')
    out.append('<text class="small" x="8" y="570">Sin relaciones: alimentan sus propios visuales.</text>')
    out.append(f'<text class="small" x="8" y="{height - 6}">Cada línea va de la dimensión («1») al hecho («*»); la flecha es la dirección del filtro, única y activa.</text></svg>')
    return "".join(out)


def _relationships(model: SemanticModel) -> str:
    rows = [[r.rel_id, f"{r.dim_table}[{r.dim_column}]", "1", f"{r.fact_table}[{r.fact_column}]", "*", "Uno a varios (1:*)",
             "Única: de la dimensión al hecho" if r.cross_filter == "single" else r.cross_filter, "Sí" if r.active else "No"] for r in model.relationships]
    return _table_html(["ID", "Dimensión", "", "Hecho", "", "Cardinalidad", "Dirección del filtro", "Activa"], rows)


def _queries(model: SemanticModel) -> str:
    parts = []
    for t in model.public:
        steps = f'    Origen = Parquet.Document(File.Contents(CarpetaSalidas & "\\{t.name}.parquet"))'
        last = "Origen"
        dates = [c.name for c in t.columns if c.dtype == "date"]
        if dates:
            casts = ", ".join(f'{{"{d}", type date}}' for d in dates)
            steps += f",\n    Tipos = Table.TransformColumnTypes(Origen, {{{casts}}})"
            last = "Tipos"
        parts.append(f"<h3>{escape(t.name)}</h3><p>{escape(t.description_es)}</p><pre><code>{escape(f'let{chr(10)}{steps}{chr(10)}in{chr(10)}    {last}')}</code></pre>")
    return "".join(parts)


def _measures(model: SemanticModel) -> str:
    parts = []
    for m in model.measures:
        uses = sorted(dax_measure_refs(m.dax))
        used = f" Usa: {', '.join('[' + u + ']' for u in uses)}." if uses else ""
        parts.append(f"<h3>{escape(m.name_es)}</h3><p>{escape(m.description_es)}{escape(used)} Formato: <code>{escape(m.format_string)}</code>.</p>"
                     f"<pre><code>{escape(m.name_es)} =\n{escape(m.dax)}</code></pre>")
    return "".join(parts)


def _page_section(data: _Data, page: Page, number: int) -> str:
    visuals = []
    for v in page.visuals:
        style = f"grid-column:{v.x + 1} / span {v.w};grid-row:{v.y + 1} / span {v.h}"
        visuals.append(f'<section class="visual" style="{style}" aria-label="{escape(v.title_es)}"><header><b>{escape(v.title_es)}</b>'
                       f'<span>{escape(KIND_ES.get(v.kind, v.kind))}</span></header><div class="body">{_preview(data, v)}</div></section>')
    rows = [[KIND_ES.get(v.kind, v.kind), v.title_es, ", ".join(v.fields), f"x {v.x}, y {v.y}, ancho {v.w}, alto {v.h}"] for v in page.visuals]
    note = f'<div class="warn">{escape(page.note_es)}</div>' if page.note_es else ""
    return (f'<h3 id="pagina-{number}">Página {number}: {escape(page.name_es)}</h3><p class="legend">{escape(LEGEND)}</p>{note}'
            f'<div class="canvas-wrap"><div class="canvas" role="group" aria-label="Página {escape(page.name_es)}">{"".join(visuals)}</div></div>'
            f'<details><summary>Posición, tipo y campos de cada visual</summary><div class="scroll placement">'
            f'{_table_html(["Visual", "Título", "Campos", "Posición (celdas)"], rows)}</div></details>')


def _page_html(model: SemanticModel, data: _Data, run: RunMeta) -> str:
    nav = "".join(f'<li><a href="#{key}">{escape(title)}</a></li>' for key, title in SECTIONS)
    pages = "".join(_page_section(data, p, i) for i, p in enumerate(model.pages, start=1))
    dims = sum(1 for t in model.public if t.kind == "dimension")
    facts = sum(1 for t in model.public if t.kind == "fact")
    return f"""<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{escape(TITLE)}</title>
<style>{CSS}</style>
</head>
<body>
<main>
<h1>{escape(TITLE)}</h1>
<p class="lead">Guía para armar el informe en Power BI Desktop a partir de los archivos Parquet de <code>outputs/powerbi</code>: modelo, relaciones, consultas, medidas y las cinco páginas con una vista previa de cada visual dibujada con los números de esos archivos.</p>
<p class="legend">{escape(LEGEND)}</p>
<div class="meta"><span>Fecha de cálculo <b>{escape(run.as_of.isoformat(sep=" "))}</b></span><span>Corrida <code>{escape(run.run_key)}</code></span><span>SHA-256 de la configuración sellada <code>{escape(data.config_sha256[:12])}</code></span></div>
<nav aria-label="Secciones"><ul>{nav}</ul></nav>
<h2 id="armado">{escape(SECTIONS[0][1])}</h2>
{_steps(model)}
<div class="warn"><b>Qué se probó y qué no.</b> Las pruebas del proyecto comprueban que los archivos cumplen el modelo (claves únicas, claves foráneas en su dimensión, relaciones de uno a varios con filtro único) y que cada referencia de cada medida existe; no corren ninguna medida, porque no hay Power BI aquí. Las vistas previas son las cifras de los archivos sin ningún segmentador, no lo que daría el DAX.</div>
<div class="warn"><b>Una celda con pocos clientes está oculta.</b> Toda celda que cuenta clientes tiene {escape(texts.es(10, 0))} o más; una más chica aparece como «{HIDDEN}», y donde un total se publica, un grupo nunca oculta una sola celda, porque el total la daría de vuelta por resta (D30). Ningún archivo tiene números de cliente.</div>
<h2 id="modelo">{escape(SECTIONS[1][1])}</h2>
<p>{dims} dimensiones y {facts} hechos publicados. Los hechos de la elección, del A/A, del menor efecto detectable y de las reglas no comparten claves con las dimensiones y alimentan sus propios visuales.</p>
{_diagram(model)}
<h2 id="relaciones">{escape(SECTIONS[2][1])}</h2>
<div class="scroll">{_relationships(model)}</div>
<h2 id="consultas">{escape(SECTIONS[3][1])}</h2>
{_queries(model)}
<h2 id="medidas">{escape(SECTIONS[4][1])}</h2>
<p>Todas van en la tabla <code>_Medidas</code>. Los nombres de las medidas y los textos están en español; las tablas y las columnas, en inglés. Las medidas que leen una tabla con <code>seal_state</code> piden solo las filas selladas.</p>
{_measures(model)}
<h2 id="paginas">{escape(SECTIONS[5][1])}</h2>
<p>Cada página es un lienzo de 1280 × 720 px (16:9) sobre una grilla de {PAGE_COLUMNS} columnas por {PAGE_ROWS} filas; la posición de cada visual está en celdas. Las vistas previas de la evaluación muestran las filas selladas; hasta el cierre dicen que la prueba está pendiente.</p>
{pages}
<h2 id="fuente">{escape(SECTIONS[6][1])}</h2>
<p>{escape(texts.ATTRIBUTION)}</p>
<p>Datos de la corrida <code>{escape(run.run_key)}</code>, con fecha de cálculo {escape(run.as_of.isoformat(sep=" "))}. Este documento se genera desde <code>dashboard/semantic_model.py</code>; no se edita a mano.</p>
</main>
</body>
</html>
"""


def render_design(model: SemanticModel, parquet_dir: Path, html_path: Path, run_meta: RunMeta) -> Path:
    """Write the HTML design of the report to `html_path` (atomically, through ``files.write_atomic``) from the Parquet files of `parquet_dir` and return the path. The model is checked first: an incoherent one writes
    nothing."""
    problems = validate_model(model)
    if problems:
        raise ValueError(f"el modelo semántico es incoherente: {problems[0]}")
    html = _page_html(model, _Data(Path(parquet_dir), model), run_meta)
    path = write_atomic(Path(html_path), html)
    logger.info("dashboard design written to %s (%d bytes)", path.name, len(html.encode("utf-8")))
    return path
