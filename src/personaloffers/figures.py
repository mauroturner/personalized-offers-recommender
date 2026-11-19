"""The figures of the documentation, drawn only from the verified files of the site (RF26; plan sections 21 and 25).

``write_figures`` reads the six JSON files through ``site_export.read_site``, which refuses a folder that is not one export (``SiteSetError``): nothing is drawn from a warehouse, a Parquet file or a number typed
here, so a figure in the README can only say what the site says. ``figure_data`` returns, for each figure, the numbers it plots; the drawing functions take nothing else. Every figure says what it shows in Spanish and,
while the test is not sealed, that the test is evaluated at the close; none of them shows an effect of an offer (the archive has none: the figures show what a list anticipates, how the control group was drawn and how the
test is calibrated). Each PNG is written atomically and is the same bytes every time (no date or version is written in it).
"""

from __future__ import annotations

import io
import logging
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from personaloffers.files import write_atomic  # noqa: E402
from personaloffers.site_export import SiteFiles, read_site  # noqa: E402

logger = logging.getLogger(__name__)

FIGURES = ("hit_by_method", "round_operation", "balance", "calibration", "choice", "new_products")
DPI = 110
COLORS = ("#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#6250d6", "#e34948")
PENDING = "La prueba se evalúa con el cierre"
NAN = float("nan")


def _nan(values: list) -> list[float]:
    return [NAN if v is None else float(v) for v in values]


def figure_data(site: SiteFiles) -> dict[str, dict[str, Any]]:
    """The numbers each figure plots, taken from the verified files and from nothing else."""
    sealed = site.summary["evaluation_status"] == "sealed"
    methods = site.algorithms["methods"]
    unrestricted = [m for m in methods if m["variant_key"] == "unrestricted"]
    new_only = [m for m in methods if m["variant_key"] == "new_only"]
    rounds = site.operation["rounds"]
    calibration = site.control["calibration"]
    choice = site.algorithms["choice"]
    return {
        "hit_by_method": {"scope": "test" if sealed and unrestricted else "pending", "method": [m["label_es"] for m in unrestricted], "hit_rate": [m["hit_rate"] for m in unrestricted],
                          "ci_low": [m["ci_low"] for m in unrestricted], "ci_high": [m["ci_high"] for m in unrestricted]},
        "round_operation": {"round": [r["round_key"][1:] for r in rounds], "offer": [r["offer"] for r in rounds], "control": [r["control"] for r in rounds]},
        "balance": {"covariate": [b["label_es"] for b in site.control["balance"]], "smd": [b["smd"] for b in site.control["balance"]]},
        "calibration": {"scope": "test" if calibration is not None else "pending", "m1": None if calibration is None else calibration["rejection"]["m1"],
                        "m2": None if calibration is None else calibration["rejection"]["m2"], "m1_normal": None if calibration is None else calibration["rejection_normal_raw"]["m1"],
                        "m2_normal": None if calibration is None else calibration["rejection_normal_raw"]["m2"], "band": None if calibration is None else calibration["band"]},
        "choice": {"candidate": [c["candidate"] for c in choice], "val_hit_new": [c["val_hit_new"] for c in choice], "val_coverage": [c["val_coverage"] for c in choice], "chosen": [c["chosen"] for c in choice]},
        "new_products": {"scope": "test" if sealed and new_only else "pending", "method": [m["label_es"] for m in new_only], "hit_rate": [m["hit_rate"] for m in new_only], "coverage": [m["coverage"] for m in new_only]},
    }


def _png(fig: plt.Figure) -> bytes:
    buffer = io.BytesIO()
    fig.savefig(buffer, format="png", dpi=DPI, bbox_inches="tight", metadata={"Software": None})
    plt.close(fig)
    return buffer.getvalue()


def _empty(ax: plt.Axes, text: str) -> None:
    ax.text(0.5, 0.5, text, ha="center", va="center", transform=ax.transAxes)
    ax.set_xticks([])
    ax.set_yticks([])


def _hit_by_method(d: dict) -> bytes:
    fig, ax = plt.subplots(figsize=(7, 4.2))
    if d["scope"] == "pending":
        _empty(ax, PENDING)
    else:
        rates = [v * 100 for v in _nan(d["hit_rate"])]
        low = [r - v * 100 for r, v in zip(rates, _nan(d["ci_low"]), strict=True)]
        high = [v * 100 - r for r, v in zip(rates, _nan(d["ci_high"]), strict=True)]
        ax.barh(d["method"], rates, xerr=[low, high], color=COLORS[0], ecolor="#444444", capsize=3)
        ax.invert_yaxis()
        ax.set_xlabel("Clientes que compraron y acertaron al menos un producto de la lista (%)")
        ax.set_title("La lista frente a las líneas base, con su intervalo del 95 %", fontsize=10)
    return _png(fig)


def _round_operation(d: dict) -> bytes:
    fig, ax = plt.subplots(figsize=(7, 3.8))
    if not d["round"]:
        _empty(ax, "Sin rondas")
    else:
        offer, control = [0 if v is None else v for v in d["offer"]], [0 if v is None else v for v in d["control"]]
        ax.bar(d["round"], offer, color=COLORS[0], label="reciben la lista")
        ax.bar(d["round"], control, bottom=offer, color=COLORS[1], label="grupo de control")
        ax.set_ylabel("Clientes de la base")
        ax.tick_params(axis="x", labelrotation=60, labelsize=7)
        ax.legend(frameon=False)
        ax.set_title("Cada semana: quién recibe la lista y quién queda en el grupo de control", fontsize=10)
    return _png(fig)


def _balance(d: dict) -> bytes:
    fig, ax = plt.subplots(figsize=(6.5, 3.4))
    if not d["covariate"]:
        _empty(ax, "Sin covariables")
    else:
        ax.barh(d["covariate"], d["smd"], color=COLORS[2])
        ax.axvline(0.1, color="#888888", linestyle="--")
        ax.axvline(-0.1, color="#888888", linestyle="--")
        ax.invert_yaxis()
        ax.set_xlabel("Diferencia estandarizada entre oferta y control (límite ±0,10)")
        ax.set_title("El grupo de control quedó parecido al de oferta, antes de cualquier lista", fontsize=10)
    return _png(fig)


def _calibration(d: dict) -> bytes:
    fig, ax = plt.subplots(figsize=(6.5, 3.6))
    if d["scope"] == "pending":
        _empty(ax, PENDING)
    else:
        names = ["M1 preregistrada", "M1 normal", "M2 preregistrada", "M2 normal"]
        rates = [d["m1"], d["m1_normal"], d["m2"], d["m2_normal"]]
        ax.bar(names, [v * 100 for v in _nan(rates)], color=[COLORS[0], COLORS[3], COLORS[0], COLORS[3]])
        low, high = d["band"]
        ax.axhspan(low * 100, high * 100, color="#bbbbbb", alpha=0.5, label="banda aceptada")
        ax.set_ylabel("Veces que rechaza, en 500 sorteos sin oferta (%)")
        ax.tick_params(axis="x", labelsize=8)
        ax.legend(frameon=False)
        ax.set_title("La prueba preregistrada rechaza lo que debe; la normal, no siempre", fontsize=10)
    return _png(fig)


def _choice(d: dict) -> bytes:
    fig, ax = plt.subplots(figsize=(7, max(3.0, 0.32 * len(d["candidate"]) + 1.4)))
    if not d["candidate"]:
        _empty(ax, "Sin candidatas")
    else:
        colors = [COLORS[1] if chosen else COLORS[0] for chosen in d["chosen"]]
        ax.barh(d["candidate"], [v * 100 for v in _nan(d["val_hit_new"])], color=colors)
        ax.invert_yaxis()
        ax.set_xlabel("Acierto de productos nuevos en las rondas de validación (%)")
        ax.set_title("La elección se hizo solo con las rondas de validación (en naranja, la elegida)", fontsize=9)
    return _png(fig)


def _new_products(d: dict) -> bytes:
    fig, ax = plt.subplots(figsize=(7, 3.8))
    if d["scope"] == "pending":
        _empty(ax, PENDING)
    else:
        ax.barh(d["method"], [v * 100 for v in _nan(d["hit_rate"])], color=COLORS[5])
        ax.invert_yaxis()
        ax.set_xlabel("Clientes que compraron un producto nuevo de la lista (%)")
        ax.set_title("Productos que el cliente nunca había comprado: el modelo frente a las líneas base", fontsize=9)
    return _png(fig)


_DRAW = {"hit_by_method": _hit_by_method, "round_operation": _round_operation, "balance": _balance, "calibration": _calibration, "choice": _choice, "new_products": _new_products}


def figure_pngs(data: dict[str, dict[str, Any]]) -> dict[str, bytes]:
    """The PNG of each figure from its numbers."""
    return {name: _DRAW[name](data[name]) for name in FIGURES}


def write_figures(site_dir: Path, out_dir: Path) -> list[Path]:
    """Draw the figures from the verified files of `site_dir` into `out_dir` (``<name>.png``, each atomic) and return their paths. A folder that is not one export is a ``SiteSetError`` and nothing is drawn or
    written."""
    pictures = figure_pngs(figure_data(read_site(site_dir)))
    paths = [write_atomic(Path(out_dir) / f"{name}.png", pictures[name]) for name in FIGURES]
    logger.info("figures: %d drawn from %s into %s", len(paths), Path(site_dir).name, Path(out_dir).name)
    return paths
