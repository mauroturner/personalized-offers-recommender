"""The semantic model of the Power BI report: the single source of its tables and relationships (RF20, RF21, AC26, AC27; D30, D37; plan sections 19 and 20). Adapted from project 07's
``dashboard/semantic_model.py``.

Tables with their columns (type, description, unit) and relationships (all one to many, single direction, active) live here; the Arrow schema of every Parquet file, the data dictionary and the HTML
design come from this module. Names of tables, columns and files are in English; descriptions and labels in Spanish (RNF13). The measures (DAX) and the five pages of the report live here too: ``validate_model`` checks the tables and the
relationships and, for the measures and the pages, that every DAX reference and every field of a visual is a column or a measure of the model, because no measure runs anywhere in the project (risk item 6).

**Privacy (D30).** No table has a column of customer, but the private one: ``fact_offer_customer`` (``private = True``) is written to ``outputs/private/`` and never versioned. A column that counts customers
is in ``CUSTOMER_COUNT_COLUMNS``: a published cell of it has ``[privacy] min_cell_customers`` or more, and a hidden cell has a ``suppressed`` mark and an empty value.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

import pyarrow as pa

ARROW_TYPES = {"int8": pa.int8(), "int16": pa.int16(), "int32": pa.int32(), "int64": pa.int64(), "float64": pa.float64(), "string": pa.string(), "bool": pa.bool_(),
               "date": pa.date32(), "datetime": pa.timestamp("us")}


@dataclass(frozen=True)
class Column:
    name: str
    dtype: str    # a key of ARROW_TYPES
    description_es: str
    unit: str | None = None


@dataclass(frozen=True)
class Table:
    name: str
    kind: Literal["dimension", "fact"]
    key: tuple[str, ...]          # a dimension's unique key or a fact's grain
    columns: tuple[Column, ...]
    description_es: str = ""
    private: bool = False         # written to ``outputs/private/``, never versioned

    @property
    def column_names(self) -> tuple[str, ...]:
        return tuple(c.name for c in self.columns)


@dataclass(frozen=True)
class Relationship:
    rel_id: str
    dim_table: str
    dim_column: str
    fact_table: str
    fact_column: str
    cardinality: str = "one_to_many"
    cross_filter: str = "single"
    active: bool = True


@dataclass(frozen=True)
class Measure:
    name_es: str
    dax: str
    format_string: str
    description_es: str


@dataclass(frozen=True)
class Visual:
    kind: str                     # slicer, card, table, barChart, lineChart
    title_es: str
    fields: tuple[str, ...]       # "table[column]" or "[Measure]"
    x: int
    y: int
    w: int
    h: int


@dataclass(frozen=True)
class Page:
    name_es: str
    visuals: tuple[Visual, ...]
    note_es: str = ""


@dataclass(frozen=True)
class SemanticModel:
    tables: tuple[Table, ...]
    relationships: tuple[Relationship, ...]
    measures: tuple[Measure, ...] = ()
    pages: tuple[Page, ...] = ()

    def table(self, name: str) -> Table:
        return next(t for t in self.tables if t.name == name)

    def measure(self, name: str) -> Measure:
        return next(m for m in self.measures if m.name_es == name)

    @property
    def public(self) -> tuple[Table, ...]:
        return tuple(t for t in self.tables if not t.private)

    @property
    def private(self) -> tuple[Table, ...]:
        return tuple(t for t in self.tables if t.private)


def arrow_schema(table: Table) -> pa.Schema:
    """The Arrow schema of a table's Parquet file: the columns in order, every key not null."""
    return pa.schema([pa.field(c.name, ARROW_TYPES[c.dtype], nullable=c.name not in table.key) for c in table.columns])


def _c(name: str, dtype: str, description_es: str, unit: str | None = None) -> Column:
    return Column(name, dtype, description_es, unit)


ROUND_KEY = _c("round_key", "string", "Ronda: R seguida del lunes que la abre, AAAA-MM-DD.")
PRODUCT_KEY = _c("product_key", "string", "Producto: su código del archivo.")
METHOD_KEY = _c("method_key", "string", "Método: offer_list (la lista), chosen_discovery (el modelo elegido) o b0 a b6 (las líneas base).")
VARIANT_KEY = _c("variant_key", "string", "Variante: unrestricted (la lista tal cual) o new_only (solo productos que el cliente nunca compró).")
SOURCE_KEY = _c("source_key", "string", "Origen del producto en la lista: repeat, discovery o fallback.")
GROUP_KEY = _c("group_key", "string", "Grupo del cliente: offer (recibe la lista) o control (la lista se arma y no se entrega).")
SEGMENT_KEY = _c("segment_key", "string", "Segmento: mayorista o minorista, con una factura previa o varias.")
COVARIATE_KEY = _c("covariate_key", "string", "Covariable del equilibrio: recency_days, invoices_365, spend_365, tenure_days o bulk.")
CRITERION_KEY = _c("criterion_key", "string", "Criterio, de C01 a C10.")
RUN_KEY = _c("run_key", "string", "Corrida que lo escribió.")
SEAL_STATE = _c("seal_state", "string", "sealed (la configuración sellada) o post_seal (otra, posterior al sello).")
SUPPRESSED = _c("suppressed", "bool", "Celda oculta: tiene menos clientes que el mínimo, o es la más chica de un grupo que mostraría a otra por resta.")

DIM_DATE = Table("dim_date", "dimension", ("date_key",), (
    _c("date_key", "int32", "Fecha, como AAAAMMDD."), _c("date", "date", "Fecha."), _c("week_monday", "date", "Lunes de su semana."),
    _c("period", "string", "history (antes de la validación), validation (las 13 rondas de elección), test (las rondas de la prueba) o close (la semana del cierre)."),
), "Los días del calendario del proyecto, del primer día del archivo al último del cierre. Es una tabla de calendario sin relaciones: las rondas se identifican por su lunes.")
DIM_ROUND = Table("dim_round", "dimension", ("round_key",), (
    ROUND_KEY, _c("monday", "date", "Lunes que abre la ronda."), _c("period", "string", "test (una de las 18 rondas semanales) o censored (la del cierre, con cinco días)."),
    _c("days_observed", "int8", "Días de su semana de seguimiento: 7, o 5 en la ronda censurada.", "días"),
), "Las rondas que se armaron y entregaron.")
DIM_PRODUCT = Table("dim_product", "dimension", ("product_key",), (
    PRODUCT_KEY, _c("description_es", "string", "Descripción más frecuente del producto en el archivo."), _c("first_seen", "date", "Primer día con una línea del producto."),
    _c("popularity_band", "int8", "Decil de facturas en la historia del lanzamiento, de 1 (el menos pedido) a 10; 0 si no tiene facturas en esa historia."),
), "Los productos del archivo.")
DIM_METHOD = Table("dim_method", "dimension", ("method_key",), (METHOD_KEY, _c("label_es", "string", "Método, en español."), _c("role_es", "string", "Qué es.")), "La lista, el modelo elegido y las siete líneas base.")
DIM_VARIANT = Table("dim_variant", "dimension", ("variant_key",), (VARIANT_KEY, _c("label_es", "string", "Variante, en español.")), "Las dos variantes de cada método.")
DIM_SOURCE = Table("dim_source", "dimension", ("source_key",), (SOURCE_KEY, _c("label_es", "string", "Origen, en español.")), "De dónde viene cada producto de una lista.")
DIM_GROUP = Table("dim_group", "dimension", ("group_key",), (GROUP_KEY, _c("label_es", "string", "Grupo, en español.")), "El grupo que recibe la lista y el de control.")
DIM_SEGMENT = Table("dim_segment", "dimension", ("segment_key",), (SEGMENT_KEY, _c("label_es", "string", "Segmento, en español.")), "Los cuatro segmentos: mayorista o no, una factura previa o más.")
DIM_COVARIATE = Table("dim_covariate", "dimension", ("covariate_key",), (
    COVARIATE_KEY, _c("label_es", "string", "Covariable, en español."), _c("unit_es", "string", "Unidad."),
), "Las cinco covariables con que se compara el grupo de oferta y el de control.")
DIM_CRITERION = Table("dim_criterion", "dimension", ("criterion_key",), (
    CRITERION_KEY, _c("name_es", "string", "Nombre del criterio."), _c("threshold_es", "string", "Su umbral, con los límites sellados."),
), "Los diez criterios fijados antes de construir.")
DIM_PIPELINE_RUN = Table("dim_pipeline_run", "dimension", ("run_key",), (
    RUN_KEY, _c("started_at", "datetime", "Inicio."), _c("finished_at", "datetime", "Fin."), _c("status", "string", "Estado: running, ok, failed, rejected o no_delivery."),
    _c("delivery_id", "string", "Entrega que cargó."), _c("as_of", "datetime", "Instante de cálculo de la corrida."), _c("config_sha256", "string", "Huella de la configuración sellada."),
    _c("round_id", "string", "Ronda que armó la corrida."), _c("peak_working_set_mb", "float64", "Pico del conjunto de trabajo.", "MB"), _c("memory_counter", "string", "Contador de memoria que dio las cifras."),
    _c("message", "string", "Mensaje de la corrida."),
), "Las corridas del flujo.")

FACT_ROUND_OPS = Table("fact_round_ops", "fact", ("round_key",), (
    ROUND_KEY, _c("base", "int64", "Clientes de la base de la ronda.", "clientes"), _c("offer", "int64", "De ellos, los que reciben la lista.", "clientes"), _c("control", "int64", "Los del grupo de control.", "clientes"),
    _c("new_assignments", "int64", "Clientes que entraron a la base esta ronda y se asignaron por la función hash.", "clientes"), _c("delivered", "int64", "Listas entregadas al CRM y leídas de vuelta iguales.", "listas"),
    _c("fallback_share", "float64", "Parte de los productos de las listas que son de la reserva."), _c("buyers_outside_base", "int64", "Clientes que compraron en la semana sin estar en la base de la ronda.", "clientes"),
    _c("seconds", "float64", "Segundos que tardó armar y entregar la ronda.", "s"), SUPPRESSED,
), "Qué se armó y se entregó cada semana. Una celda con menos clientes que el mínimo está vacía.")
FACT_ROUND_GROUP = Table("fact_round_group", "fact", ("round_key", "group_key", "segment_key"), (
    ROUND_KEY, GROUP_KEY, SEGMENT_KEY, _c("customers", "int64", "Clientes de la base en el grupo y el segmento.", "clientes"), _c("buyers", "int64", "De ellos, los que compraron en la semana.", "clientes"),
    _c("buyers_of_listed", "int64", "De ellos, los que compraron un producto de su lista.", "clientes"), _c("spend", "float64", "Gasto de los que compraron, en libras.", "libras"), SUPPRESSED,
), "Seguimiento por ronda, grupo y segmento. Lo del grupo de control es lo que habría pasado sin entregarle la lista: sin ofertas en el archivo, no es el efecto de nada.")
FACT_OFFER_PRODUCT = Table("fact_offer_product", "fact", ("round_key", "product_key", "source_key"), (
    ROUND_KEY, PRODUCT_KEY, SOURCE_KEY, _c("offered_to", "int64", "Clientes del grupo de oferta a los que la lista les puso el producto con ese origen.", "clientes"),
    _c("bought_by", "int64", "De ellos, los que lo compraron en la semana.", "clientes"), SUPPRESSED,
), "Qué productos se ofrecieron, con qué origen y cuántos se compraron. Solo hay filas con el mínimo de clientes ofrecidos; la compra por debajo del mínimo está vacía.")
FACT_METHOD_ROUND = Table("fact_method_round", "fact", ("method_key", "variant_key", "round_key", "seal_state"), (
    METHOD_KEY, VARIANT_KEY, ROUND_KEY, _c("pairs", "int64", "Pares (ronda, cliente) evaluados: clientes de la base que compraron en la semana.", "pares"),
    _c("hit_rate", "float64", "hit@10: parte de los pares con al menos un producto de la lista comprado en la semana."), _c("recall", "float64", "recall@10: productos de la lista comprados sobre productos distintos comprados."),
    _c("precision", "float64", "precisión@10: productos de la lista comprados sobre 10."), _c("ndcg", "float64", "NDCG@10: acierto con descuento por lugar."),
    _c("coverage", "float64", "Productos distintos de las listas de la ronda sobre los comprados en los 365 días anteriores."), SEAL_STATE, SUPPRESSED,
), "Cada método y variante en cada ronda.")
FACT_METHOD_TOTAL = Table("fact_method_total", "fact", ("method_key", "variant_key", "seal_state"), (
    METHOD_KEY, VARIANT_KEY, _c("pairs", "int64", "Pares evaluados en las rondas de la prueba.", "pares"), _c("hit_rate", "float64", "hit@10 de la prueba."),
    _c("ci_low", "float64", "Límite inferior del intervalo del 95 % (remuestreo por cliente)."), _c("ci_high", "float64", "Límite superior del intervalo del 95 %."),
    _c("wilson_low", "float64", "Límite inferior del intervalo de Wilson (informativo)."), _c("wilson_high", "float64", "Límite superior del intervalo de Wilson (informativo)."),
    _c("recall", "float64", "recall@10 de la prueba."), _c("precision", "float64", "precisión@10 de la prueba."), _c("ndcg", "float64", "NDCG@10 de la prueba."),
    _c("coverage", "float64", "Cobertura media de las rondas de la prueba."), SEAL_STATE, SUPPRESSED,
), "Cada método y variante en toda la prueba.")
FACT_SEGMENT = Table("fact_segment", "fact", ("method_key", "variant_key", "segment_key", "seal_state"), (
    METHOD_KEY, VARIANT_KEY, SEGMENT_KEY, _c("pairs", "int64", "Pares evaluados del segmento.", "pares"), _c("hit_rate", "float64", "hit@10 del segmento."),
    _c("ci_low", "float64", "Límite inferior del intervalo del 95 %."), _c("ci_high", "float64", "Límite superior del intervalo del 95 %."), SEAL_STATE, SUPPRESSED,
), "Cada método y variante por segmento. Una celda con menos clientes que el mínimo está vacía.")
FACT_CHOICE = Table("fact_choice", "fact", ("candidate",), (
    _c("candidate", "string", "Receta candidata: modelo, tamaño, regularización y peso de la tendencia."), _c("base_model", "string", "als, cosine o rules."),
    _c("params", "string", "Parámetros del modelo base."), _c("trend_weight", "float64", "Peso de la tendencia en la mezcla."), _c("val_hit_new", "float64", "hit@10 solo nuevos en las rondas de validación."),
    _c("val_coverage", "float64", "Cobertura media en esas rondas."), _c("kept", "bool", "Quedó a menos de la tolerancia de la mejor."), _c("chosen", "bool", "Es la receta elegida y sellada."),
    _c("fit_rounds", "int8", "Rondas de validación con que se midió.", "rondas"),
), "Las 48 recetas medidas en la validación, con la elegida.")
FACT_BALANCE = Table("fact_balance", "fact", ("covariate_key", "seal_state"), (
    COVARIATE_KEY, _c("offer_mean", "float64", "Media en el grupo de oferta."), _c("control_mean", "float64", "Media en el grupo de control."), _c("smd", "float64", "Diferencia estandarizada."), SEAL_STATE,
), "El equilibrio del grupo de control en la cohorte del lanzamiento.")
FACT_EXPERIMENT = Table("fact_experiment", "fact", ("metric", "test", "seal_state"), (
    _c("metric", "string", "m1 (parte de las semanas con compra) o m2 (gasto en libras)."), _c("test", "string", "preregistered (CUPED y permutación estratificada), normal_raw o normal_cuped (informativas)."),
    _c("aa_diff", "float64", "Diferencia entre los grupos del A/A (nadie recibió una oferta: no es el efecto de nada)."), _c("aa_p", "float64", "p de dos colas."),
    _c("aa_ci_low", "float64", "Límite inferior del intervalo del 95 %."), _c("aa_ci_high", "float64", "Límite superior del intervalo del 95 %."),
    _c("calibration_rejection", "float64", "Parte de los sorteos nuevos del control que esta prueba rechazó con p < 0,05."), SEAL_STATE,
), "El A/A del control sellado y la calibración de cada prueba.")
FACT_MDE = Table("fact_mde", "fact", ("metric", "holdout_share", "seal_state"), (
    _c("metric", "string", "m1 o m2."), _c("holdout_share", "float64", "Parte de la cohorte que se deja como control."), _c("holdout_size", "int64", "Clientes en ese control.", "clientes"),
    _c("mde", "float64", "Menor diferencia que la prueba vería (M1 en parte de las semanas, M2 en libras)."), _c("mde_relative", "float64", "El mismo número sobre la media del resultado."), SEAL_STATE, SUPPRESSED,
), "Lo que una operación de este tamaño podría ver con 10, 20 y 30 % de control.")
FACT_RULE = Table("fact_rule", "fact", ("antecedent_key", "consequent_key"), (
    _c("antecedent_key", "string", "Producto de partida de la regla."), _c("consequent_key", "string", "Producto que la regla anticipa."), _c("antecedent_es", "string", "Descripción del producto de partida."),
    _c("consequent_es", "string", "Descripción del producto que anticipa."), _c("support", "int64", "Facturas de la historia del lanzamiento con los dos productos.", "facturas"),
    _c("confidence", "float64", "Facturas con los dos sobre facturas con el primero."), _c("rule_lift", "float64", "Confianza sobre la parte de facturas con el segundo."),
), "Las reglas de pares de mayor rule_lift con soporte suficiente. Sin relaciones: lleva dos claves de producto y se muestra como tabla.")
FACT_EVALUATION_SUMMARY = Table("fact_evaluation_summary", "fact", ("criterion_key", "seal_state"), (
    CRITERION_KEY, _c("tested_value_es", "string", "La cantidad que el umbral compara, con su unidad."), _c("point_value", "float64", "Valor puntual de la misma cifra."),
    _c("ci_low", "float64", "Límite inferior del intervalo."), _c("ci_high", "float64", "Límite superior del intervalo."), _c("passed", "bool", "Se cumple; vacío si no hay umbral."),
    _c("seen_by_research", "string", "Si la investigación vio esta cifra antes de fijar el criterio."), _c("seen_by_planner", "string", "Si el planificador la vio."), _c("verdict_es", "string", "Veredicto, el mismo del resumen."), SEAL_STATE,
), "Los diez criterios con su veredicto.")
FACT_VALIDATION = Table("fact_validation", "fact", ("run_key", "rule_id"), (
    RUN_KEY, _c("rule_id", "string", "Regla de validación: V10 a V18."), _c("name_es", "string", "Regla, en español."), _c("severity", "string", "bloqueante, advertencia o informativa."),
    _c("scope", "string", "Alcance de la regla."), _c("aggregation", "string", "source, per_run o latest."), _c("status", "string", "pasa o falla."), _c("rows_affected", "int64", "Filas afectadas.", "filas"),
), "Qué dijo cada regla de validación en cada corrida.")
FACT_OFFER_CUSTOMER = Table("fact_offer_customer", "fact", ("round_key", "customer_id", "rank"), (
    ROUND_KEY, _c("customer_id", "int64", "Número de cliente del archivo (solo en outputs/private, nunca versionado)."), _c("rank", "int8", "Lugar en la lista, de 1 a 10."), PRODUCT_KEY, SOURCE_KEY, GROUP_KEY,
    _c("bought", "bool", "El cliente compró ese producto en la semana de la ronda; vacío si la semana no llegó."),
), "La lista de cada cliente. Tiene números de cliente: vive solo en outputs/private y nunca se versiona (D30, D45).", private=True)

DIMENSIONS = (DIM_DATE, DIM_ROUND, DIM_PRODUCT, DIM_METHOD, DIM_VARIANT, DIM_SOURCE, DIM_GROUP, DIM_SEGMENT, DIM_COVARIATE, DIM_CRITERION, DIM_PIPELINE_RUN)
FACTS = (FACT_ROUND_OPS, FACT_ROUND_GROUP, FACT_OFFER_PRODUCT, FACT_METHOD_ROUND, FACT_METHOD_TOTAL, FACT_SEGMENT, FACT_CHOICE, FACT_BALANCE, FACT_EXPERIMENT, FACT_MDE, FACT_RULE,
         FACT_EVALUATION_SUMMARY, FACT_VALIDATION, FACT_OFFER_CUSTOMER)

# plan, section 19: relationship id -> (dimension, fact, fact column)
RELATIONSHIP_SPEC = {
    "R01": ("dim_round", "fact_round_ops", "round_key"), "R02": ("dim_round", "fact_round_group", "round_key"), "R03": ("dim_round", "fact_offer_product", "round_key"),
    "R04": ("dim_round", "fact_method_round", "round_key"), "R05": ("dim_round", "fact_offer_customer", "round_key"), "R06": ("dim_product", "fact_offer_product", "product_key"),
    "R07": ("dim_product", "fact_offer_customer", "product_key"), "R08": ("dim_method", "fact_method_round", "method_key"), "R09": ("dim_method", "fact_method_total", "method_key"),
    "R10": ("dim_method", "fact_segment", "method_key"), "R11": ("dim_variant", "fact_method_round", "variant_key"), "R12": ("dim_variant", "fact_method_total", "variant_key"),
    "R13": ("dim_variant", "fact_segment", "variant_key"), "R14": ("dim_source", "fact_offer_product", "source_key"), "R15": ("dim_group", "fact_round_group", "group_key"),
    "R16": ("dim_segment", "fact_round_group", "segment_key"), "R17": ("dim_segment", "fact_segment", "segment_key"), "R18": ("dim_covariate", "fact_balance", "covariate_key"),
    "R19": ("dim_criterion", "fact_evaluation_summary", "criterion_key"), "R20": ("dim_pipeline_run", "fact_validation", "run_key"),
}
RELATIONSHIPS = tuple(Relationship(rel_id, dim, next(t for t in DIMENSIONS if t.name == dim).key[0], fact, column) for rel_id, (dim, fact, column) in RELATIONSHIP_SPEC.items())
PAGE_COLUMNS, PAGE_ROWS = 12, 9

# --- the measures and the pages (plan section 20; U16) --------------------------------------------------------------------------------------------------------------

INTEGER, PERCENT, DECIMAL_3, DATETIME_FORMAT, TEXT_FORMAT = "#,0", "0.0%", "0.000", "yyyy-mm-dd hh:mm", "@"
_S = 'seal_state] = "sealed"'
LEGEND = "Sin ofertas reales: el archivo no permite medir el efecto de una oferta"


def _sealed(table: str) -> str:
    return f'{table}[{_S}'


MEASURES: tuple[Measure, ...] = (
    Measure("Clientes en la base", "SUM ( fact_round_ops[base] )", INTEGER, "Clientes de la base de las rondas elegidas; una celda con menos clientes que el mínimo está vacía y no suma."),
    Measure("Reciben oferta", "SUM ( fact_round_ops[offer] )", INTEGER, "De ellos, los que reciben la lista."),
    Measure("Grupo de control", "SUM ( fact_round_ops[control] )", INTEGER, "Los que quedaron apartados: su lista se arma y no se entrega."),
    Measure("Listas entregadas", "SUM ( fact_round_ops[delivered] )", INTEGER, "Listas que llegaron al CRM y se leyeron de vuelta iguales."),
    Measure("Parte de reserva", "AVERAGE ( fact_round_ops[fallback_share] )", PERCENT, "Parte de los productos de las listas que son de la reserva (lo más vendido de 28 días)."),
    Measure("Acierto (hit@10)", f"CALCULATE ( SELECTEDVALUE ( fact_method_total[hit_rate] ), {_sealed('fact_method_total')} )", PERCENT,
            "hit@10 de la prueba de un método y una variante: la parte de los clientes que compraron con al menos un producto de la lista comprado en la semana."),
    Measure("Acierto por ronda", f"CALCULATE ( AVERAGE ( fact_method_round[hit_rate] ), {_sealed('fact_method_round')} )", PERCENT, "hit@10 de cada ronda: la media de las rondas elegidas, con la configuración sellada."),
    Measure("Límite inferior", f"CALCULATE ( SELECTEDVALUE ( fact_method_total[ci_low] ), {_sealed('fact_method_total')} )", PERCENT, "Límite inferior del intervalo del 95 % del hit@10 (remuestreo por cliente)."),
    Measure("Límite superior", f"CALCULATE ( SELECTEDVALUE ( fact_method_total[ci_high] ), {_sealed('fact_method_total')} )", PERCENT, "Límite superior del intervalo del 95 % del hit@10."),
    Measure("Recall (recall@10)", f"CALCULATE ( SELECTEDVALUE ( fact_method_total[recall] ), {_sealed('fact_method_total')} )", PERCENT, "Productos de la lista comprados sobre productos distintos comprados."),
    Measure("Precisión (precisión@10)", f"CALCULATE ( SELECTEDVALUE ( fact_method_total[precision] ), {_sealed('fact_method_total')} )", PERCENT, "Productos de la lista comprados sobre diez."),
    Measure("NDCG (NDCG@10)", f"CALCULATE ( SELECTEDVALUE ( fact_method_total[ndcg] ), {_sealed('fact_method_total')} )", PERCENT, "Acierto con descuento por el lugar de la lista."),
    Measure("Cobertura", f"CALCULATE ( AVERAGE ( fact_method_round[coverage] ), {_sealed('fact_method_round')} )", DECIMAL_3,
            "Productos distintos de las listas de la ronda sobre los comprados en los 365 días anteriores, media de las rondas elegidas."),
    Measure("Acierto solo nuevos", f'CALCULATE ( SELECTEDVALUE ( fact_method_total[hit_rate] ), {_sealed("fact_method_total")}, fact_method_total[variant_key] = "new_only" )', PERCENT,
            "hit@10 de la prueba con la lista armada solo con productos que el cliente nunca compró."),
    Measure("Acierto por segmento", f"CALCULATE ( SELECTEDVALUE ( fact_segment[hit_rate] ), {_sealed('fact_segment')} )", PERCENT, "hit@10 de la prueba de un método y una variante en un segmento; una celda con pocos clientes está vacía."),
    Measure("Ofrecido a", "SUM ( fact_offer_product[offered_to] )", INTEGER, "Clientes del grupo de oferta a los que la lista les puso el producto."),
    Measure("Comprado por", "SUM ( fact_offer_product[bought_by] )", INTEGER, "De ellos, los que lo compraron en la semana; una celda con menos clientes que el mínimo está vacía."),
    Measure("Diferencia estandarizada", f"CALCULATE ( SELECTEDVALUE ( fact_balance[smd] ), {_sealed('fact_balance')} )", DECIMAL_3, "Diferencia estandarizada de una covariable entre el grupo de oferta y el de control."),
    Measure("Mayor diferencia estandarizada", f"CALCULATE ( MAXX ( fact_balance, ABS ( fact_balance[smd] ) ), {_sealed('fact_balance')} )", DECIMAL_3,
            "La mayor diferencia estandarizada absoluta de las cinco covariables: lo que mira el criterio C06."),
    Measure("Rechazo del A/A", f'CALCULATE ( SELECTEDVALUE ( fact_experiment[calibration_rejection] ), fact_experiment[test] = "preregistered", {_sealed("fact_experiment")} )', PERCENT,
            "Parte de los sorteos nuevos del control que la prueba preregistrada rechazó con p menor que 0,05 (debe estar entre 3,1 % y 6,9 %)."),
    Measure("p del A/A", f'CALCULATE ( SELECTEDVALUE ( fact_experiment[aa_p] ), fact_experiment[test] = "preregistered", {_sealed("fact_experiment")} )', DECIMAL_3,
            "p de la prueba preregistrada con el control sellado, sin ninguna oferta."),
    Measure("Menor efecto detectable", f"CALCULATE ( SELECTEDVALUE ( fact_mde[mde] ), {_sealed('fact_mde')} )", DECIMAL_3,
            "Menor diferencia que una operación de este tamaño podría ver: en M1, parte de las semanas con compra; en M2, libras. No es un resultado."),
    Measure("Veredicto", f"CALCULATE ( SELECTEDVALUE ( fact_evaluation_summary[verdict_es] ), {_sealed('fact_evaluation_summary')} )", TEXT_FORMAT, "Veredicto de un criterio con la configuración sellada."),
    Measure("Última fecha de cálculo", 'CALCULATE ( MAX ( dim_pipeline_run[as_of] ), dim_pipeline_run[status] = "ok" )', DATETIME_FORMAT, "Instante de cálculo de la última corrida terminada bien."),
    Measure("Reglas bloqueantes fallidas", 'CALCULATE ( COUNTROWS ( fact_validation ), fact_validation[severity] = "bloqueante", fact_validation[status] = "falla" )', INTEGER,
            "Resultados de reglas bloqueantes que fallaron, en las corridas cargadas."),
)

NOT_FILTERED = " (no lo filtra{plural} {names})"
SEGMENT_NOTE = NOT_FILTERED.format(plural="", names="el segmento")
PAGES: tuple[Page, ...] = (
    Page("Las ofertas de la semana", (
        Visual("slicer", "Ronda", ("dim_round[round_key]",), 0, 0, 6, 1),
        Visual("slicer", "Segmento", ("dim_segment[label_es]",), 6, 0, 6, 1),
        Visual("card", "Clientes en la base" + SEGMENT_NOTE, ("[Clientes en la base]",), 0, 1, 2, 1),
        Visual("card", "Reciben oferta" + SEGMENT_NOTE, ("[Reciben oferta]",), 2, 1, 2, 1),
        Visual("card", "Grupo de control" + SEGMENT_NOTE, ("[Grupo de control]",), 4, 1, 2, 1),
        Visual("card", "Listas entregadas" + SEGMENT_NOTE, ("[Listas entregadas]",), 6, 1, 3, 1),
        Visual("card", "Parte de reserva" + SEGMENT_NOTE, ("[Parte de reserva]",), 9, 1, 3, 1),
        Visual("barChart", "Clientes que reciben la lista y clientes de control, por ronda" + SEGMENT_NOTE, ("dim_round[round_key]", "[Reciben oferta]", "[Grupo de control]"), 0, 2, 6, 7),
        Visual("table", "Los productos más ofrecidos, por origen" + SEGMENT_NOTE, ("dim_product[description_es]", "dim_source[label_es]", "[Ofrecido a]", "[Comprado por]"), 6, 2, 6, 7),
    )),
    Page("La lista contra las líneas base", (
        Visual("slicer", "Variante", ("dim_variant[label_es]",), 0, 0, 6, 1),
        Visual("slicer", "Segmento", ("dim_segment[label_es]",), 6, 0, 6, 1),
        Visual("barChart", "Acierto de cada método, con su intervalo" + SEGMENT_NOTE, ("dim_method[label_es]", "[Acierto (hit@10)]", "[Límite inferior]", "[Límite superior]"), 0, 1, 6, 4),
        Visual("lineChart", "Acierto por ronda de cada método" + SEGMENT_NOTE, ("dim_round[round_key]", "dim_method[label_es]", "[Acierto por ronda]"), 6, 1, 6, 4),
        Visual("table", "Recall, precisión y NDCG de cada método" + SEGMENT_NOTE, ("dim_method[label_es]", "[Recall (recall@10)]", "[Precisión (precisión@10)]", "[NDCG (NDCG@10)]"), 0, 5, 6, 4),
        Visual("barChart", "Acierto por segmento", ("dim_segment[label_es]", "dim_method[label_es]", "[Acierto por segmento]"), 6, 5, 6, 4),
    )),
    Page("Productos nuevos y cobertura", (
        Visual("barChart", "Acierto solo con productos nuevos, de cada método", ("dim_method[label_es]", "[Acierto solo nuevos]"), 0, 0, 6, 4),
        Visual("barChart", "Cobertura de las listas de cada método", ("dim_method[label_es]", "[Cobertura]"), 6, 0, 6, 4),
        Visual("table", "La elección de la receta en la validación", ("fact_choice[candidate]", "fact_choice[val_hit_new]", "fact_choice[val_coverage]", "fact_choice[kept]", "fact_choice[chosen]",
                                                                     "fact_choice[fit_rounds]"), 0, 4, 6, 5),
        Visual("table", "Las reglas de pares con mayor rule_lift", ("fact_rule[antecedent_es]", "fact_rule[consequent_es]", "fact_rule[support]", "fact_rule[confidence]", "fact_rule[rule_lift]"), 6, 4, 6, 5),
    )),
    Page("El grupo de control, listo para medir", (
        Visual("card", "Mayor diferencia estandarizada", ("[Mayor diferencia estandarizada]",), 0, 0, 4, 1),
        Visual("table", "El equilibrio del control, covariable por covariable", ("dim_covariate[label_es]", "dim_covariate[unit_es]", "fact_balance[offer_mean]", "fact_balance[control_mean]", "[Diferencia estandarizada]"), 0, 1, 12, 3),
        Visual("table", "El A/A del control sellado: p y rechazo de la calibración", ("fact_experiment[metric]", "[p del A/A]", "[Rechazo del A/A]"), 0, 4, 6, 5),
        Visual("table", "Lo que una operación de este tamaño podría ver", ("fact_mde[metric]", "fact_mde[holdout_share]", "[Menor efecto detectable]"), 6, 4, 6, 5),
    ), "Esto no es un efecto: sin ofertas en el archivo, la diferencia entre los dos grupos es ruido. Las cifras dicen cómo quedó armado el control y qué tamaño de diferencia podría verse con una operación real."),
    Page("La prueba y la calidad de datos", (
        Visual("table", "Criterios C01-C10", ("dim_criterion[criterion_key]", "dim_criterion[name_es]", "dim_criterion[threshold_es]", "fact_evaluation_summary[tested_value_es]",
                                               "fact_evaluation_summary[seen_by_research]", "fact_evaluation_summary[seen_by_planner]", "[Veredicto]"), 0, 0, 12, 4),
        Visual("card", "Reglas bloqueantes fallidas", ("[Reglas bloqueantes fallidas]",), 0, 4, 6, 1),
        Visual("card", "Última fecha de cálculo", ("[Última fecha de cálculo]",), 6, 4, 6, 1),
        Visual("table", "Reglas de validación", ("fact_validation[rule_id]", "fact_validation[name_es]", "fact_validation[severity]", "fact_validation[rows_affected]", "fact_validation[status]"), 0, 5, 6, 4),
        Visual("table", "Corridas", ("dim_pipeline_run[run_key]", "dim_pipeline_run[delivery_id]", "dim_pipeline_run[as_of]", "dim_pipeline_run[status]", "dim_pipeline_run[message]"), 6, 5, 6, 4),
    )),
)
MODEL = SemanticModel(tables=(*DIMENSIONS, *FACTS), relationships=RELATIONSHIPS, measures=MEASURES, pages=PAGES)

# the columns that count customers: a published cell of them has ``[privacy] min_cell_customers`` or more (D30); the first of each table decides whether the cell is hidden
CUSTOMER_COUNT_COLUMNS = {
    "fact_round_ops": ("base", "offer", "control", "new_assignments", "buyers_outside_base"), "fact_round_group": ("customers", "buyers", "buyers_of_listed"),
    "fact_offer_product": ("offered_to", "bought_by"), "fact_method_round": ("pairs",), "fact_method_total": ("pairs",), "fact_segment": ("pairs",), "fact_mde": ("holdout_size",),
}


def validate_model(model: SemanticModel) -> list[str]:
    """What is incoherent in the tables and the relationships of `model` (empty when it is coherent): a duplicate table or column, a key that is not a column, a dimension whose key is not one column, a
    relationship that is not one to many, single and active, or that points to a column that does not exist or has another type, and a column of customer in a table that is not private (D30)."""
    problems: list[str] = []
    names = [t.name for t in model.tables]
    problems += [f"tabla repetida: {n}" for n in sorted({n for n in names if names.count(n) > 1})]
    tables = {t.name: t for t in model.tables}
    for t in model.tables:
        columns = t.column_names
        problems += [f"{t.name}: columna repetida {c}" for c in sorted({c for c in columns if columns.count(c) > 1})]
        problems += [f"{t.name}: la clave {k} no es una columna" for k in t.key if k not in columns]
        problems += [f"{t.name}: tipo desconocido {c.dtype}" for c in t.columns if c.dtype not in ARROW_TYPES]
        if t.kind == "dimension" and len(t.key) != 1:
            problems.append(f"{t.name}: una dimensión tiene una sola columna de clave")
        if not t.private and any("customer" in c for c in columns if c != "customers" and c != "customer_count"):
            problems.append(f"{t.name}: una tabla que se versiona no tiene columna de cliente (D30)")
    for r in model.relationships:
        dim, fact = tables.get(r.dim_table), tables.get(r.fact_table)
        if dim is None or fact is None:
            problems.append(f"{r.rel_id}: tabla inexistente")
            continue
        if (r.cardinality, r.cross_filter, r.active) != ("one_to_many", "single", True):
            problems.append(f"{r.rel_id}: debe ser de uno a varios, de un solo sentido y activa")
        if dim.kind != "dimension" or fact.kind != "fact" or dim.key != (r.dim_column,):
            problems.append(f"{r.rel_id}: va de la clave de una dimensión a un hecho")
        dim_type = next((c.dtype for c in dim.columns if c.name == r.dim_column), None)
        fact_type = next((c.dtype for c in fact.columns if c.name == r.fact_column), None)
        if fact_type is None or dim_type != fact_type:
            problems.append(f"{r.rel_id}: {r.fact_table}[{r.fact_column}] no existe o no es del tipo de {r.dim_table}[{r.dim_column}]")
    for name, columns in CUSTOMER_COUNT_COLUMNS.items():
        problems += [f"{name}: la columna {c} que cuenta clientes no existe" for c in columns if name not in tables or c not in tables[name].column_names]
        if name in tables and "suppressed" not in tables[name].column_names:
            problems.append(f"{name}: cuenta clientes y no tiene la marca suppressed")
    return problems + _measure_problems(model) + _page_problems(model)


# --- the static checks that stand in for running the measures (risk item 6: no DAX runs anywhere in the project) --------------------------------------------------------------------------

_COLUMN_REF = re.compile(r"(?<![\w'])([A-Za-z_]\w*)\[(\w+)\]")
_MEASURE_REF = re.compile(r"(?<![\w\]'])\[([^\[\]]+)\]")
_FUNCTION_CALL = re.compile(r"\b([A-Z][A-Z0-9.]*)(?=\s*\()")
_LITERAL_COMPARISON = re.compile(r'\b([a-z_]\w*)\[(\w+)\]\s*=\s*"([^"]*)"')
_REMOVES_FILTERS = re.compile(r"\b(ALL|ALLEXCEPT|ALLSELECTED|REMOVEFILTERS|CROSSFILTER|USERELATIONSHIP|KEEPFILTERS)\b")
DAX_FUNCTIONS = frozenset({"CALCULATE", "COUNTROWS", "DISTINCTCOUNT", "DIVIDE", "MAX", "MAXX", "ABS", "SELECTEDVALUE", "SUM", "SUMX", "NOT", "ISBLANK", "TRUE", "AVERAGE"})


def dax_column_refs(dax: str) -> set[tuple[str, str]]:
    """The ``table[column]`` references of a DAX expression."""
    return set(_COLUMN_REF.findall(dax))


def dax_measure_refs(dax: str) -> set[str]:
    """The ``[Measure]`` references of a DAX expression: a bracket not attached to a table."""
    return set(_MEASURE_REF.findall(dax))


def visual_tables(model: SemanticModel, visual: Visual) -> set[str]:
    """The tables a visual reads: those of its columns and, through the DAX of its measures and of the measures they name, those the measures name by a column or whole."""
    found: set[str] = set()
    pending, seen = list(visual.fields), set()
    while pending:
        field = pending.pop()
        if field.startswith("["):
            name = field[1:-1]
            measure = next((m for m in model.measures if m.name_es == name), None)
            if measure is not None and name not in seen:
                seen.add(name)
                found |= {t.name for t in model.tables if re.search(rf"\b{t.name}\b", measure.dax)}
                pending += [f"[{n}]" for n in dax_measure_refs(measure.dax)]
        else:
            found.add(field.split("[")[0])
    return {t for t in found if any(table.name == t for table in model.tables)}


def _field_problem(model: SemanticModel, field: str) -> str | None:
    """Why the field of a visual does not resolve, or None."""
    if field.startswith("["):
        return None if any(f"[{m.name_es}]" == field for m in model.measures) else f"la medida {field} no existe"
    match = re.fullmatch(r"([A-Za-z_]\w*)\[(\w+)\]", field)
    if match is None:
        return f"el campo {field!r} no es una columna ni una medida"
    table, column = match.groups()
    return None if any(t.name == table and column in t.column_names for t in model.tables) else f"la columna {field} no existe"


def _measure_problems(model: SemanticModel) -> list[str]:
    problems: list[str] = []
    names = [m.name_es for m in model.measures]
    problems += [f"la medida [{n}] está repetida" for n in sorted({n for n in names if names.count(n) > 1})]
    columns = {t.name: {c.name: c for c in t.columns} for t in model.tables}
    uses: dict[str, set[str]] = {}
    for m in model.measures:
        label = f"[{m.name_es}]"
        if m.dax.count("(") != m.dax.count(")"):
            problems.append(f"{label}: paréntesis sin cerrar en el DAX")
        if m.dax.count('"') % 2:
            problems.append(f"{label}: comillas sin cerrar en el DAX")
        problems += [f"{label}: {t}[{c}] no existe" for t, c in sorted(dax_column_refs(m.dax)) if c not in columns.get(t, {})]
        problems += [f"{label}: {w} no es una tabla" for w in sorted(set(re.findall(r"\b(?:dim|fact)_\w+", m.dax)) - set(columns))]
        problems += [f"{label}: la función {f} no es de las que usa el plan" for f in sorted(set(_FUNCTION_CALL.findall(m.dax)) - DAX_FUNCTIONS)]
        uses[m.name_es] = dax_measure_refs(m.dax)
        problems += [f"{label}: la medida [{r}] no existe o es ella misma" for r in sorted(uses[m.name_es]) if r not in names or r == m.name_es]
        for table, column, literal in _LITERAL_COMPARISON.findall(m.dax):
            if column in columns.get(table, {}) and literal not in columns[table][column].description_es:
                problems.append(f"{label}: compara {table}[{column}] con '{literal}', que la columna no toma")
        problems += [f"{label}: {w} quita los filtros de los segmentadores" for w in sorted(set(_REMOVES_FILTERS.findall(m.dax)))]
        if not m.format_string or not m.description_es:
            problems.append(f"{label}: necesita un formato y una descripción")

    def circle(name: str, path: tuple[str, ...]) -> bool:
        return name in path or any(circle(n, (*path, name)) for n in uses.get(name, ()) if n in uses and n != name)

    problems += [f"las medidas [{n}] se llaman en círculo" for n in sorted(uses) if any(circle(r, (n,)) for r in uses[n] if r in uses and r != n)]
    return problems


def _page_problems(model: SemanticModel) -> list[str]:
    problems: list[str] = []
    titles = [p.name_es for p in model.pages]
    problems += [f"página repetida: {t}" for t in sorted({t for t in titles if titles.count(t) > 1})]
    related = {(r.dim_table, r.fact_table) for r in model.relationships}
    kinds = {t.name: t.kind for t in model.tables}
    for page in model.pages:
        if not page.visuals:
            problems.append(f"{page.name_es}: sin visuales")
        taken: dict[tuple[int, int], str] = {}
        for v in page.visuals:
            label = f"{page.name_es}: {v.title_es}"
            problems += [f"{label}: {why}" for field in v.fields if (why := _field_problem(model, field)) is not None]
            if v.kind == "slicer" and (len(v.fields) != 1 or v.fields[0].startswith("[")):
                problems.append(f"{label}: un segmentador usa una sola columna")
            tables = visual_tables(model, v)
            dims, facts = sorted(t for t in tables if kinds[t] == "dimension"), sorted(t for t in tables if kinds[t] == "fact")
            if len(facts) >= 2 and not dims:
                problems.append(f"{label}: dos hechos sin una dimensión que los una")
            if len(dims) >= 2 and not facts:
                problems.append(f"{label}: dos dimensiones sin un hecho que las una")
            problems += [f"{label}: {d} y {f} no se unen por ninguna relación" for d in dims for f in facts if (d, f) not in related]
            if v.w < 1 or v.h < 1 or v.x < 0 or v.y < 0 or v.x + v.w > PAGE_COLUMNS or v.y + v.h > PAGE_ROWS:
                problems.append(f"{label}: sale de la grilla de {PAGE_COLUMNS} x {PAGE_ROWS}")
                continue
            cells = [(cx, cy) for cx in range(v.x, v.x + v.w) for cy in range(v.y, v.y + v.h)]
            clash = next((taken[c] for c in cells if c in taken), None)
            if clash is not None:
                problems.append(f"{label}: se superpone con {clash}")
            taken.update({c: v.title_es for c in cells})
    return problems
