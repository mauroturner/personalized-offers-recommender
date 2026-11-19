"""The semantic model of the Power BI report: the single source of its tables and relationships (RF20, RF21, AC26, AC27; D30, D37; plan sections 19 and 20). Adapted from project 07's
``dashboard/semantic_model.py``.

Tables with their columns (type, description, unit) and relationships (all one to many, single direction, active) live here; the Arrow schema of every Parquet file, the data dictionary and the HTML
design come from this module. Names of tables, columns and files are in English; descriptions and labels in Spanish (RNF13). The measures (DAX) and the five pages of the report join them in
``U16``.

**Privacy (D30).** No table has a column of customer, but the private one: ``fact_offer_customer`` (``private = True``) is written to ``outputs/private/`` and never versioned. A column that counts customers
is in ``CUSTOMER_COUNT_COLUMNS``: a published cell of it has ``[privacy] min_cell_customers`` or more, and a hidden cell has a ``suppressed`` mark and an empty value.
"""

from __future__ import annotations

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
class SemanticModel:
    tables: tuple[Table, ...]
    relationships: tuple[Relationship, ...]

    def table(self, name: str) -> Table:
        return next(t for t in self.tables if t.name == name)

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
MODEL = SemanticModel(tables=(*DIMENSIONS, *FACTS), relationships=RELATIONSHIPS)

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
    return problems
