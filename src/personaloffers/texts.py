"""The Spanish texts of the criteria and the way numbers are written in them (RF19; AC23; plan sections 16 and 21; decisions D16, D19, D20): the names, the thresholds, the figure that each threshold tests and
the verdicts of C01-C10.

Each verdict is built from the figures it tells and **names its own comparison** (lo más vendido, la recompra propia, el grupo de control sellado, el CRM) and the unit of what it compares: a difference of
rates is in points, a rate in percent, a coverage, a standardized difference and a p-value as the plain numbers they are. ``tested_value_es`` is the quantity that the threshold compares, written the same way
everywhere (the summary's column «Lo que prueba el umbral», the star schema and the design): never the point value of the same figure. A criterion that cannot be computed says why and is never passed (``cannot``).

Nothing here names an effect of an offer: the archive has no offers (D16).
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any, NamedTuple


class CriterionText(NamedTuple):
    name_es: str
    threshold_es: str          # with the limits of ``[criteria]`` in {braces}
    seen_by_research: str
    seen_by_planner: str


# id: name, threshold, what the research saw, what the planner saw (requirements.md, 8.1; D19)
CRITERIA: dict[str, CriterionText] = {
    "C01": CriterionText("La lista supera a lo más vendido", "límite inferior del intervalo del 95 % de hit@10(lista) − hit@10(B2) > {c01}", "sí", "sí"),
    "C02": CriterionText("La lista no pierde más de 5 puntos frente a la recompra propia", "límite inferior del intervalo del 95 % de hit@10(lista) − hit@10(B3) > {c02}", "en parte", "sí"),
    "C03": CriterionText("La lista supera a la recompra propia", "límite inferior del intervalo del 95 % de hit@10(lista) − hit@10(B3) > {c03}", "en parte", "sí"),
    "C04": CriterionText("El modelo descubre mejor que lo más vendido", "límite inferior del intervalo del 95 % de hit@10 solo nuevos(modelo elegido) − hit@10 solo nuevos(B2) > {c04}", "sí", "sí"),
    "C05": CriterionText("Cada cliente recibe su propia lista", "cobertura media de las listas de la ronda ≥ {c05}", "sí", "sí"),
    "C06": CriterionText("El grupo de control está equilibrado", "mayor diferencia estandarizada absoluta de las cinco covariables ≤ {c06}", "sí", "sí"),
    "C07": CriterionText("La prueba del experimento está calibrada", "tasa de rechazo de la prueba preregistrada, en 500 sorteos nuevos del control, de M1 y de M2: las dos entre {c07_low} y {c07_high}", "sí", "sí"),
    "C08": CriterionText("El A/A no marca una diferencia que no existe", "con el control sellado, la prueba preregistrada de M1 y de M2 da, las dos, p ≥ {c08}", "sí", "sí"),
    "C09": CriterionText("Lo entregado al CRM es lo decidido", "el 100 % de las listas entregadas se lee de vuelta igual, ningún cliente del control llega al CRM ni al CSV y repetir la última ronda no crea ningún registro", "no", "no"),
    "C10": CriterionText("Variantes y seguimiento (informativo)", "sin umbral", "en parte", "en parte"),
}
COVARIATES = {"recency_days": "la recencia", "invoices_365": "las facturas del año", "spend_365": "el gasto del año", "tenure_days": "la antigüedad", "bulk": "la marca mayorista"}


def es(value: float | None, decimals: int = 3, *, percent: bool = False) -> str:
    """A number as the Spanish text shows it: a comma for the decimals, a point for the thousands and «−» for the minus sign; «sin dato» if there is none. With `percent` the number is a fraction
    written as « x %». A number that rounds to zero never carries a minus sign."""
    if value is None or (isinstance(value, float) and not math.isfinite(value)):
        return "sin dato"
    text = f"{(value * 100 if percent else value):,.{decimals}f}"
    if text.startswith("-") and not any(ch in "123456789" for ch in text):
        text = text[1:]
    text = text.replace(",", "§").replace(".", ",").replace("§", ".").replace("-", "−")
    return f"{text} %" if percent else text


def pct(value: float | None) -> str:
    """A fraction as a percentage with the decimals it needs (none when whole, one otherwise, two under 1 %)."""
    if value is None:
        return "sin dato"
    scaled = value * 100
    if abs(scaled - round(scaled)) < 1e-9:
        return es(value, 0, percent=True)
    return es(value, 2 if abs(scaled) < 1 else 1, percent=True)


def points(value: float | None, decimals: int = 1) -> str:
    """A difference of two rates (fractions) in percentage points, «19,5 puntos»."""
    return "sin dato" if value is None else f"{es(value * 100, decimals)} puntos"


def thresholds_from(limits: Mapping[str, Any]) -> dict[str, str]:
    """The threshold of each criterion with its limits from ``[criteria]`` written in."""
    low, high = limits["c07_rejection_band"]
    numbers = {"c01": points(limits["c01_min_diff_low"]), "c02": points(limits["c02_min_diff_low"]), "c03": points(limits["c03_min_diff_low"]), "c04": points(limits["c04_min_diff_low"]),
               "c05": es(limits["c05_min_coverage"], 2), "c06": es(limits["c06_max_abs_smd"], 2), "c07_low": es(low, 1, percent=True), "c07_high": es(high, 1, percent=True), "c08": es(limits["c08_min_p"], 2)}
    return {cid: text.threshold_es.format(**numbers) for cid, text in CRITERIA.items()}


def cannot(why: str) -> str:
    return f"El criterio no se puede calcular: {why}."


def informative_verdict(variants: int) -> str:
    return (f"Informativo: sin umbral. Las líneas base, el modelo elegido y la lista con hit@10, recall@10, precisión@10, NDCG@10 y cobertura, sin restricción y solo nuevos, por ronda y por segmento, "
            f"las pruebas normales sin ajustar del A/A, el menor efecto detectable con 10, 20 y 30 % de control y la ronda censurada están en el resumen ({variants} variantes).")


def tested_value_es(cid: str, **f: Any) -> str:
    """The quantity that the threshold of `cid` compares, with its unit: what the summary's column «Lo que prueba el umbral» shows."""
    if cid in ("C01", "C02", "C03", "C04"):
        return f"{points(f['low'])} (límite inferior)"
    if cid == "C05":
        return f"{es(f['coverage'], 3)} (cobertura media)"
    if cid == "C06":
        return f"{es(f['smd'], 3)} (mayor diferencia estandarizada absoluta)"
    if cid == "C07":
        return f"{es(f['m1'], 1, percent=True)} y {es(f['m2'], 1, percent=True)} (tasas de rechazo de M1 y de M2)"
    if cid == "C08":
        return f"p = {es(f['p1'], 3)} y p = {es(f['p2'], 3)} (M1 y M2)"
    if cid == "C09":
        return (f"{es(f['equal'], 0)} de {es(f['lists'], 0)} listas leídas de vuelta iguales; {es(f['control'], 0)} del control en el CRM o en el CSV; "
                f"{es(f['repeat'], 0)} nuevas al repetir la última ronda")
    if cid == "C10":
        return "sin umbral"
    raise KeyError(cid)


def verdict(cid: str, passed: bool, **f: Any) -> str:
    """The sentence of criterion `cid`, from its figures (see ``evaluation.criteria_of``)."""
    mark = "" if passed else " No se cumple."
    if cid == "C01":
        return (f"En {f['rounds']} rondas semanales, la lista acertó al menos un producto en el {es(f['a'], 1, percent=True)} de los clientes que compraron y lo más vendido (B2) en el {es(f['b'], 1, percent=True)}; "
                f"el límite inferior de la diferencia es {points(f['low'])} y el umbral era {points(f['limit'])}.{mark}")
    if cid in ("C02", "C03"):
        return (f"En {f['rounds']} rondas semanales, la lista acertó al menos un producto en el {es(f['a'], 1, percent=True)} de los clientes que compraron y la recompra propia (B3) en el {es(f['b'], 1, percent=True)}; "
                f"el límite inferior de la diferencia es {points(f['low'])} y debía ser mayor que {points(f['limit'])}.{mark}")
    if cid == "C04":
        return (f"Entre los productos que el cliente nunca había comprado, el modelo elegido acertó en el {es(f['a'], 1, percent=True)} de los clientes que compraron y lo más vendido (B2) en el {es(f['b'], 1, percent=True)}; "
                f"el límite inferior de la diferencia es {points(f['low'])} y debía ser mayor que {points(f['limit'])}.{mark}")
    if cid == "C05":
        return (f"En {f['rounds']} rondas, las listas de cada ronda cubrieron en promedio {es(f['coverage'], 3)} de los productos con alguna compra en los 365 días anteriores; el umbral era {es(f['limit'], 2)}.{mark}")
    if cid == "C06":
        return (f"Entre las cinco covariables de la cohorte del lanzamiento ({es(f['customers'], 0)} clientes), la mayor diferencia estandarizada absoluta entre el grupo de oferta y el de control es {es(f['smd'], 3)} "
                f"({COVARIATES.get(f['covariate'], f['covariate'])}); el máximo era {es(f['limit'], 2)}.{mark}")
    if cid == "C07":
        return (f"En {es(f['seeds'], 0)} sorteos nuevos del grupo de control sobre el período de prueba, la prueba preregistrada rechazó {es(f['m1'], 1, percent=True)} de las veces para las semanas con compra (M1) y {es(f['m2'], 1, percent=True)} para el gasto (M2); "
                f"las dos debían estar entre {es(f['low'], 1, percent=True)} y {es(f['high'], 1, percent=True)}.{mark}")
    if cid == "C08":
        return (f"Con el control sellado y sin ninguna oferta, la prueba preregistrada da p = {es(f['p1'], 3)} para las semanas con compra (M1) y p = {es(f['p2'], 3)} para el gasto (M2) en el período de prueba; "
                f"los dos debían ser al menos {es(f['limit'], 2)}.{mark}")
    if cid == "C09":
        return (f"{es(f['equal'], 0)} de {es(f['lists'], 0)} listas entregadas se leyeron de vuelta del CRM iguales; {es(f['control_crm'], 0)} clientes del control llegaron al CRM y {es(f['control_csv'], 0)} a los archivos de correo; "
                f"repetir la última ronda ({f['round']}, {es(f['contacts'], 0)} contactos) creó {es(f['repeat'], 0)} registros nuevos; debían leerse todas iguales y no llegar ni crearse ninguno.{mark}")
    raise KeyError(cid)


PLAN_VALIDATION_TOLERANCE = 0.01      # two figures of the coverage are told comparable when they differ by at most this much (absolute; the real ones differ by 0.005)
PLAN_VALIDATION_C05 = 0.158      # the plan's validation figure (requirements, section 8.1; research/p01.out, «offer_7_3_blend_als_trend_1 unrestricted»): the lists of the evaluated customers over every product with a basket line before the round


def c05_preregistered_line(c05: Mapping[str, Any]) -> str:
    """C05 as requirements 8.1 define it, from ``evaluation.coverage_definitions`` (D49): one quantity per sentence, each named with its own lines, so the sealed figure is never told with the other's
    denominator."""
    pre, sealed = c05["preregistered"], c05["sealed"]
    mark = " y se cumple" if pre["passed"] else "; no se cumple"
    return (f"C05 como lo fija el preregistro: en {c05['rounds']} rondas, las listas de cada ronda cubrieron en promedio {es(pre['value'], 3)} de los productos con alguna línea de compra "
            f"(`purchase`) en los 365 días anteriores; el umbral era {es(pre['threshold'], 2)}{mark}. La cifra sellada, {es(sealed['value'], 3)}, tiene otro denominador: los productos con alguna de las "
            f"líneas de canasta (las compras de clientes y las de invitados) en esos 365 días.")


def c05_p01_line(c05: Mapping[str, Any]) -> str:
    """Why the test's coverage is not the plan's validation figure (D49), from the computed figures only: the test's figure with ``p01``'s definition is told «comparable» with the plan's 0.158 when it is
    within ``PLAN_VALIDATION_TOLERANCE`` of it, and otherwise both figures are stated; «sobre todo el numerador» (or the denominator) only when the part of the distance it names is the larger one."""
    sealed, whole, definition = (c05[key]["value"] for key in ("sealed", "p01_denominator", "p01_definition"))
    denominator_part, numerator_part = sealed - whole, whole - definition
    head = (f"Con la definición de la validación del plan (`p01`: las listas de los clientes evaluados, los que compraron en la semana, sobre todos los productos con alguna línea de canasta antes de "
            f"la ronda), la prueba da {es(definition, 3)}")
    if round(abs(definition - PLAN_VALIDATION_C05), 9) <= PLAN_VALIDATION_TOLERANCE:
        part = "el numerador" if numerator_part >= denominator_part else "el denominador"
        return (f"{head}, comparable con el {es(PLAN_VALIDATION_C05, 3)} de esa validación. La distancia entre la cifra sellada, "
                f"{es(sealed, 3)}, y ese {es(PLAN_VALIDATION_C05, 3)} es sobre todo {part}: con el denominador de `p01` y las listas de toda la base, la cobertura es "
                f"{es(whole, 3)}; con solo las listas de los clientes evaluados, {es(definition, 3)}.")
    return (f"{head}; la validación del plan dio {es(PLAN_VALIDATION_C05, 3)}, a {es(abs(definition - PLAN_VALIDATION_C05), 3)} de ella, más que la tolerancia de {es(PLAN_VALIDATION_TOLERANCE, 2)} con la que "
            f"se darían por iguales. Entre la cifra sellada, {es(sealed, 3)}, y la de `p01`, {es(definition, 3)}, el denominador explica {es(denominator_part, 3)} y el numerador {es(numerator_part, 3)}: "
            f"con el denominador de `p01` y las listas de toda la base, la cobertura es {es(whole, 3)}.")


# --- the labels of the dimensions of the star schema (plan section 19) ------------------------------------------------------------------------------------------------------

ATTRIBUTION = ("Chen, D. (2012). Online Retail II. UCI Machine Learning Repository. https://doi.org/10.24432/C5CG6D (CC BY 4.0, https://creativecommons.org/licenses/by/4.0/). "
               "Modificado: se quitaron las copias del solapamiento entre hojas, se agrupó por ronda semanal y se resumió en cifras agregadas; no hay números de cliente.")
METHOD_LABELS = {
    "offer_list": ("La lista que se entrega", "La lista: hasta 7 productos de la recompra propia, el resto nuevos del modelo elegido y la reserva de lo más vendido de 28 días"),
    "chosen_discovery": ("Modelo elegido (descubrimiento)", "El modelo de la lista solo, sin la recompra, para medir si descubre productos nuevos"),
    "b0": ("B0 al azar", "Línea base: productos al azar"), "b1": ("B1 popularidad global", "Línea base: lo más comprado de toda la historia"),
    "b2": ("B2 lo más vendido de 28 días", "Línea base: lo más vendido de las últimas cuatro semanas, igual para todos"),
    "b3": ("B3 recompra propia", "Línea base: lo que el cliente ya compró, completado con B2"), "b4": ("B4 reglas de asociación", "Línea base: reglas de pares de productos, sin tendencia"),
    "b5": ("B5 ALS", "Línea base: factorización implícita (ALS), sin tendencia"), "b6": ("B6 coseno entre productos", "Línea base: vecinos por similitud coseno, sin tendencia"),
}
VARIANT_LABELS = {"unrestricted": "Sin restricción: la lista tal cual", "new_only": "Solo productos nuevos: los que el cliente nunca compró"}
SOURCE_LABELS = {"repeat": "Recompra propia", "discovery": "Descubrimiento del modelo", "fallback": "Reserva: lo más vendido de 28 días"}
GROUP_LABELS = {"offer": "Recibe la oferta", "control": "Grupo de control"}
SEGMENT_LABELS = {"bulk|repeat": "Mayorista con compras repetidas", "bulk|one_invoice": "Mayorista con una factura", "retail|repeat": "Minorista con compras repetidas", "retail|one_invoice": "Minorista con una factura"}
COVARIATE_LABELS = {"recency_days": ("Recencia", "días"), "invoices_365": ("Facturas del año", "facturas"), "spend_365": ("Gasto del año", "libras"), "tenure_days": ("Antigüedad", "días"),
                    "bulk": ("Marca mayorista", "0 o 1")}
PERIOD_LABELS = {"history": "Historia", "validation": "Validación", "test": "Prueba", "close": "Cierre", "censored": "Censurada"}
WEEKDAYS_ES = ("lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo")
