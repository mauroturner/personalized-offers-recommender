# Diccionario de datos

Qué tiene cada archivo del proyecto y qué significa cada columna. Los datos son los de Online Retail II (UCI, CC BY 4.0), reales y públicos: el archivo no tiene ofertas, y ninguna columna de este diccionario es el resultado de una. Las tablas de la última sección las escribe `python -m personaloffers docs-sync` desde el modelo semántico (`src/personaloffers/dashboard/semantic_model.py`) entre marcadores `<!-- table:<nombre>:start -->` y `<!-- table:<nombre>:end -->`: no se editan a mano, y `tests/docs/test_docs.py` comprueba que son las que el comando escribe y que cada Parquet versionado tiene exactamente esas columnas.

## Las 8 columnas de la fuente

El libro de UCI tiene dos hojas (`Year 2009-2010` y `Year 2010-2011`) con las mismas 8 columnas, en este orden. El flujo las lee como un archivo no confiable (reglas V03 a V07 del plan) y escribe una vez `data/interim/lines.parquet` con las líneas canónicas.

| Columna | Tipo | Uso |
| --- | --- | --- |
| `Invoice` | texto o entero | La factura. Una letra C al principio es una anulación y una A es un ajuste de deuda; con eso se decide el rol de la línea. Nunca se publica |
| `StockCode` | texto o entero | El producto. Es un producto si son cinco dígitos y hasta tres letras (D04); lo demás son servicios, vales y descuentos |
| `Description` | texto | La descripción del producto, en inglés; puede venir vacía (regla V16, advertencia) |
| `Quantity` | entero | Unidades de la línea; negativa en una anulación |
| `InvoiceDate` | fecha y hora | Decide la entrega y la ronda: cada línea de compra cuenta en la ventana de una sola semana |
| `Price` | número | Precio unitario en libras |
| `Customer ID` | número o vacío | El cliente. Una de cada cinco filas (22,5 %) lo tiene vacío: son compras de invitados. Nunca se publica ni se versiona |
| `Country` | texto | El país de la factura; el Reino Unido concentra 935.026 de las 1.044.848 líneas |

Las 11 columnas de una línea canónica son `line_key`, `invoice`, `stock_code`, `description`, `quantity`, `invoice_date`, `price`, `customer_id`, `country`, `internal_repeat` y `role` (el rol lo agrega la unidad U05). Las 22.523 copias exactas del solapamiento entre hojas se quitan; las 11.812 repeticiones dentro de una hoja se conservan y se marcan en `internal_repeat`.

## Los roles de línea

Cada línea tiene un solo rol, el primero de esta lista que cumple (RF04). Una **línea de compra** es `purchase`; una **canasta** es una factura con líneas `purchase` o `guest_purchase`.

| Orden | Rol | Regla | Líneas en la corrida real |
| --- | --- | --- | --- |
| 1 | `cancellation` | La factura empieza con C | 19.165 |
| 2 | `adjustment` | La factura empieza con A | 6 |
| 3 | `non_product` | El código no es de producto (servicios, vales, las líneas de descuento `D`) | 4.795 |
| 4 | `bad_price` | Precio o cantidad en cero o negativos, fuera de una anulación | 5.938 |
| 5 | `guest_purchase` | Sin cliente: entra en las reglas de canasta y en la popularidad, nunca como un cliente | 226.757 |
| 6 | `purchase` | Todo lo demás: la línea de un cliente | 788.187 |

La suma es 1.044.848. De las 5.993 líneas que quedan fuera de la regla de producto, 4.795 tienen el rol `non_product` y 1.198 son anulaciones o ajustes, que van antes en el orden. Las 173 líneas de descuento no son ofertas al azar (D43).

## La base de contactos y las covariables

La base de una ronda son los clientes con al menos una línea de compra en los 365 días anteriores a su lunes. Las covariables se calculan solo con líneas anteriores a ese lunes (RF08, D06, D23); las cinco primeras son las que compara el equilibrio del grupo de control (C06).

| Columna | Qué es |
| --- | --- |
| `recency_days` | Días desde la última compra, en días fraccionarios |
| `invoices_365` | Facturas del cliente en los 365 días anteriores |
| `spend_365` | Gasto en libras en los 365 días anteriores |
| `tenure_days` | Días desde la primera compra, en días fraccionarios |
| `bulk` | Marca de mayorista, con la regla del proyecto 02 (mediana de unidades por línea de 24 o más con al menos 3 líneas en los 365 días); es un estrato del control y un corte de informe, nunca una variable de un modelo (D07) |
| `invoices_before` | Facturas anteriores al lunes; separa a quien tiene una sola factura de quien tiene más para el corte «una factura previa o más» |

Los cuatro segmentos son la combinación de mayorista o no con una factura previa o más. Quien nunca compró en el último año no está en la base y no recibe lista (D06).

## Los orígenes de cada producto de la lista

Cada lista tiene 10 productos distintos en orden, cada uno con su origen (`offer_lists.source`; la tabla `dim_source`).

| Origen | Qué es |
| --- | --- |
| `repeat` | Un producto que el cliente ya compró, por su puntaje de recompra propia; hasta 7 por lista |
| `discovery` | Un producto que el cliente nunca compró, con el puntaje del modelo elegido (ALS mezclado con la tendencia de 28 días); al menos 3 cuando el modelo tiene candidatos |
| `fallback` | Lo más vendido de los últimos 28 días, sin repetir lo que la lista ya tiene, si el modelo no alcanza para completar 10 |

## Los archivos del sitio

Seis JSON y un manifiesto con el tamaño y el SHA-256 de cada uno, escrito al final (`outputs/site/`, D38). Ningún archivo trae números de cliente ni una celda con menos de 10 clientes, y ninguno trae una ruta de la máquina. Cada uno lleva la fuente y su licencia, la huella de la fuente, la huella de la configuración y la clave de la corrida.

| Archivo | Qué contiene |
| --- | --- |
| `data.json` | El archivo: filas y copias, líneas sin cliente, roles, canastas, mayoristas, el calendario, la recompra y las 173 líneas de descuento |
| `algorithms.json` | Las líneas base y el modelo elegido con su intervalo, por ronda y por variante; las 48 recetas de la elección; las reglas de ejemplo (`rule_lift`) y tres listas de ejemplo, cada una la lista agregada de un perfil (`kind: "aggregate"`, `note_es` y, por producto, `stock_code`, `description_es`, `source_key` y `customers`, sin rango; D46) |
| `operation.json` | Las 19 rondas (clientes de la base, de oferta y de control, lo entregado y los segundos), el CRM (lotes, listas, conflictos) y el correo (archivos y filas) |
| `control.json` | La asignación (865 de control y 3.461 de oferta, 18 estratos), el equilibrio de las cinco covariables, el A/A, la calibración y el menor efecto detectable con 10, 20 y 30 % de control |
| `validation_rules.json` | Las reglas V10 a V18 con su severidad y las filas que tocaron |
| `summary.json` | Los diez criterios con su veredicto, las cifras de cabecera y `post_seal_analysis`: C05 con sus cuatro definiciones, el análisis posterior al sello (D49) |

Una nota corregida: hasta las correcciones de la evaluación, las tres listas de ejemplo de `algorithms.json` salían de la lista de un cliente real de un perfil con 3.029, 958 y 288 clientes, y L133 contó que solo 5, 5 y 6 clientes habían comprado antes de la ventana los siete productos de recompra de cada una, menos que el mínimo de 10 clientes de D30. Ahora son agregados del perfil, y cada producto lo tienen 10 clientes o más (D46).

`reports/post_seal_analysis.json`, al lado del sello: `c05` con `sealed`, `preregistered`, `p01_denominator` y `p01_definition` (cada uno con `value` y `definition_es`; los dos primeros con `threshold` y `passed`), `rounds` y `by_round` (los productos distintos de las listas y de las listas de los clientes evaluados, y los de cada catálogo, por ronda), `config_sha256`, `seal_sha256` (el SHA-256 del sello al lado del que se calculó; con otro sello no se publica) y `note_es`. La frase sellada de C05 (`criteria[].verdict_es` de `C05`, «productos con alguna compra») usa «compra» para la línea de canasta (`purchase` y `guest_purchase`), no para la línea de compra de RF04 (`purchase`): el denominador preregistrado es `c05.preregistered` de este archivo (D49).

## Las tablas del modelo estrella

Veinticinco tablas, 11 dimensiones y 14 hechos, con claves únicas y relaciones de uno a varios de filtro único (D37). Veinticuatro están en `outputs/powerbi/` como Parquet; la lista de cada cliente (`fact_offer_customer`) tiene números de cliente y vive en `outputs/private/`, que no se versiona. Cada Parquet lleva en sus metadatos la clave de la corrida, la huella de la fuente y la de la configuración. Ninguna tabla publicada tiene una columna de cliente, y toda celda que cuenta clientes y tiene menos de 10 está vacía, con una regla secundaria que impide recuperarla por resta.

Cada tabla dice su clave (o el grano, si es un hecho), qué contiene y sus columnas con su tipo, su clave, su unidad y su descripción.

### `dim_date`

Los días del calendario del proyecto, del primer día del archivo al último del cierre. Es una tabla de calendario sin relaciones: las rondas se identifican por su lunes.

Clave: `date_key`. Archivo: `outputs/powerbi/dim_date.parquet`.

<!-- table:dim_date:start -->
| Columna | Tipo | Clave | Unidad | Descripción |
| --- | --- | --- | --- | --- |
| `date_key` | int32 | sí |  | Fecha, como AAAAMMDD. |
| `date` | date |  |  | Fecha. |
| `week_monday` | date |  |  | Lunes de su semana. |
| `period` | string |  |  | history (antes de la validación), validation (las 13 rondas de elección), test (las rondas de la prueba) o close (la semana del cierre). |
<!-- table:dim_date:end -->

### `dim_round`

Las rondas que se armaron y entregaron.

Clave: `round_key`. Archivo: `outputs/powerbi/dim_round.parquet`.

<!-- table:dim_round:start -->
| Columna | Tipo | Clave | Unidad | Descripción |
| --- | --- | --- | --- | --- |
| `round_key` | string | sí |  | Ronda: R seguida del lunes que la abre, AAAA-MM-DD. |
| `monday` | date |  |  | Lunes que abre la ronda. |
| `period` | string |  |  | test (una de las 18 rondas semanales) o censored (la del cierre, con cinco días). |
| `days_observed` | int8 |  | días | Días de su semana de seguimiento: 7, o 5 en la ronda censurada. |
<!-- table:dim_round:end -->

### `dim_product`

Los productos del archivo.

Clave: `product_key`. Archivo: `outputs/powerbi/dim_product.parquet`.

<!-- table:dim_product:start -->
| Columna | Tipo | Clave | Unidad | Descripción |
| --- | --- | --- | --- | --- |
| `product_key` | string | sí |  | Producto: su código del archivo. |
| `description_es` | string |  |  | Descripción más frecuente del producto en el archivo. |
| `first_seen` | date |  |  | Primer día con una línea del producto. |
| `popularity_band` | int8 |  |  | Decil de facturas en la historia del lanzamiento, de 1 (el menos pedido) a 10; 0 si no tiene facturas en esa historia. |
<!-- table:dim_product:end -->

### `dim_method`

La lista, el modelo elegido y las siete líneas base.

Clave: `method_key`. Archivo: `outputs/powerbi/dim_method.parquet`.

<!-- table:dim_method:start -->
| Columna | Tipo | Clave | Unidad | Descripción |
| --- | --- | --- | --- | --- |
| `method_key` | string | sí |  | Método: offer_list (la lista), chosen_discovery (el modelo elegido) o b0 a b6 (las líneas base). |
| `label_es` | string |  |  | Método, en español. |
| `role_es` | string |  |  | Qué es. |
<!-- table:dim_method:end -->

### `dim_variant`

Las dos variantes de cada método.

Clave: `variant_key`. Archivo: `outputs/powerbi/dim_variant.parquet`.

<!-- table:dim_variant:start -->
| Columna | Tipo | Clave | Unidad | Descripción |
| --- | --- | --- | --- | --- |
| `variant_key` | string | sí |  | Variante: unrestricted (la lista tal cual) o new_only (solo productos que el cliente nunca compró). |
| `label_es` | string |  |  | Variante, en español. |
<!-- table:dim_variant:end -->

### `dim_source`

De dónde viene cada producto de una lista.

Clave: `source_key`. Archivo: `outputs/powerbi/dim_source.parquet`.

<!-- table:dim_source:start -->
| Columna | Tipo | Clave | Unidad | Descripción |
| --- | --- | --- | --- | --- |
| `source_key` | string | sí |  | Origen del producto en la lista: repeat, discovery o fallback. |
| `label_es` | string |  |  | Origen, en español. |
<!-- table:dim_source:end -->

### `dim_group`

El grupo que recibe la lista y el de control.

Clave: `group_key`. Archivo: `outputs/powerbi/dim_group.parquet`.

<!-- table:dim_group:start -->
| Columna | Tipo | Clave | Unidad | Descripción |
| --- | --- | --- | --- | --- |
| `group_key` | string | sí |  | Grupo del cliente: offer (recibe la lista) o control (la lista se arma y no se entrega). |
| `label_es` | string |  |  | Grupo, en español. |
<!-- table:dim_group:end -->

### `dim_segment`

Los cuatro segmentos: mayorista o no, una factura previa o más.

Clave: `segment_key`. Archivo: `outputs/powerbi/dim_segment.parquet`.

<!-- table:dim_segment:start -->
| Columna | Tipo | Clave | Unidad | Descripción |
| --- | --- | --- | --- | --- |
| `segment_key` | string | sí |  | Segmento: mayorista o minorista, con una factura previa o varias. |
| `label_es` | string |  |  | Segmento, en español. |
<!-- table:dim_segment:end -->

### `dim_covariate`

Las cinco covariables con que se compara el grupo de oferta y el de control.

Clave: `covariate_key`. Archivo: `outputs/powerbi/dim_covariate.parquet`.

<!-- table:dim_covariate:start -->
| Columna | Tipo | Clave | Unidad | Descripción |
| --- | --- | --- | --- | --- |
| `covariate_key` | string | sí |  | Covariable del equilibrio: recency_days, invoices_365, spend_365, tenure_days o bulk. |
| `label_es` | string |  |  | Covariable, en español. |
| `unit_es` | string |  |  | Unidad. |
<!-- table:dim_covariate:end -->

### `dim_criterion`

Los diez criterios fijados antes de construir.

Clave: `criterion_key`. Archivo: `outputs/powerbi/dim_criterion.parquet`.

<!-- table:dim_criterion:start -->
| Columna | Tipo | Clave | Unidad | Descripción |
| --- | --- | --- | --- | --- |
| `criterion_key` | string | sí |  | Criterio, de C01 a C10. |
| `name_es` | string |  |  | Nombre del criterio. |
| `threshold_es` | string |  |  | Su umbral, con los límites sellados. |
<!-- table:dim_criterion:end -->

### `dim_pipeline_run`

Las corridas del flujo.

Clave: `run_key`. Archivo: `outputs/powerbi/dim_pipeline_run.parquet`.

<!-- table:dim_pipeline_run:start -->
| Columna | Tipo | Clave | Unidad | Descripción |
| --- | --- | --- | --- | --- |
| `run_key` | string | sí |  | Corrida que lo escribió. |
| `started_at` | datetime |  |  | Inicio. |
| `finished_at` | datetime |  |  | Fin. |
| `status` | string |  |  | Estado: running, ok, failed, rejected o no_delivery. |
| `delivery_id` | string |  |  | Entrega que cargó. |
| `as_of` | datetime |  |  | Instante de cálculo de la corrida. |
| `config_sha256` | string |  |  | Huella de la configuración sellada. |
| `round_id` | string |  |  | Ronda que armó la corrida. |
| `peak_working_set_mb` | float64 |  | MB | Pico del conjunto de trabajo. |
| `memory_counter` | string |  |  | Contador de memoria que dio las cifras. |
| `message` | string |  |  | Mensaje de la corrida. |
<!-- table:dim_pipeline_run:end -->

### `fact_round_ops`

Qué se armó y se entregó cada semana. Una celda con menos clientes que el mínimo está vacía.

Clave: `round_key`. Archivo: `outputs/powerbi/fact_round_ops.parquet`.

<!-- table:fact_round_ops:start -->
| Columna | Tipo | Clave | Unidad | Descripción |
| --- | --- | --- | --- | --- |
| `round_key` | string | sí |  | Ronda: R seguida del lunes que la abre, AAAA-MM-DD. |
| `base` | int64 |  | clientes | Clientes de la base de la ronda. |
| `offer` | int64 |  | clientes | De ellos, los que reciben la lista. |
| `control` | int64 |  | clientes | Los del grupo de control. |
| `new_assignments` | int64 |  | clientes | Clientes que entraron a la base esta ronda y se asignaron por la función hash. |
| `delivered` | int64 |  | listas | Listas entregadas al CRM y leídas de vuelta iguales. |
| `fallback_share` | float64 |  |  | Parte de los productos de las listas que son de la reserva. |
| `buyers_outside_base` | int64 |  | clientes | Clientes que compraron en la semana sin estar en la base de la ronda. |
| `seconds` | float64 |  | s | Segundos que tardó armar y entregar la ronda. |
| `suppressed` | bool |  |  | Celda oculta: tiene menos clientes que el mínimo, o es la más chica de un grupo que mostraría a otra por resta. |
<!-- table:fact_round_ops:end -->

### `fact_round_group`

Seguimiento por ronda, grupo y segmento: cuántos clientes compraron y cuántos compraron un producto de su lista. Lo del grupo de control es lo que habría pasado sin entregarle la lista; con el archivo sin ofertas, no se lee como una comparación entre grupos.

Clave: `round_key`, `group_key`, `segment_key`. Archivo: `outputs/powerbi/fact_round_group.parquet`.

<!-- table:fact_round_group:start -->
| Columna | Tipo | Clave | Unidad | Descripción |
| --- | --- | --- | --- | --- |
| `round_key` | string | sí |  | Ronda: R seguida del lunes que la abre, AAAA-MM-DD. |
| `group_key` | string | sí |  | Grupo del cliente: offer (recibe la lista) o control (la lista se arma y no se entrega). |
| `segment_key` | string | sí |  | Segmento: mayorista o minorista, con una factura previa o varias. |
| `customers` | int64 |  | clientes | Clientes de la base en el grupo y el segmento. |
| `buyers` | int64 |  | clientes | De ellos, los que compraron en la semana. |
| `buyers_of_listed` | int64 |  | clientes | De ellos, los que compraron un producto de su lista. |
| `spend` | float64 |  | libras | Gasto de los que compraron, en libras. |
| `suppressed` | bool |  |  | Celda oculta: tiene menos clientes que el mínimo, o es la más chica de un grupo que mostraría a otra por resta. |
<!-- table:fact_round_group:end -->

### `fact_offer_product`

Qué productos se ofrecieron, con qué origen y cuántos se compraron. Solo hay filas con el mínimo de clientes ofrecidos; la compra por debajo del mínimo está vacía.

Clave: `round_key`, `product_key`, `source_key`. Archivo: `outputs/powerbi/fact_offer_product.parquet`.

<!-- table:fact_offer_product:start -->
| Columna | Tipo | Clave | Unidad | Descripción |
| --- | --- | --- | --- | --- |
| `round_key` | string | sí |  | Ronda: R seguida del lunes que la abre, AAAA-MM-DD. |
| `product_key` | string | sí |  | Producto: su código del archivo. |
| `source_key` | string | sí |  | Origen del producto en la lista: repeat, discovery o fallback. |
| `offered_to` | int64 |  | clientes | Clientes del grupo de oferta a los que la lista les puso el producto con ese origen. |
| `bought_by` | int64 |  | clientes | De ellos, los que lo compraron en la semana. |
| `suppressed` | bool |  |  | Celda oculta: tiene menos clientes que el mínimo, o es la más chica de un grupo que mostraría a otra por resta. |
<!-- table:fact_offer_product:end -->

### `fact_method_round`

Cada método y variante en cada ronda.

Clave: `method_key`, `variant_key`, `round_key`, `seal_state`. Archivo: `outputs/powerbi/fact_method_round.parquet`.

<!-- table:fact_method_round:start -->
| Columna | Tipo | Clave | Unidad | Descripción |
| --- | --- | --- | --- | --- |
| `method_key` | string | sí |  | Método: offer_list (la lista), chosen_discovery (el modelo elegido) o b0 a b6 (las líneas base). |
| `variant_key` | string | sí |  | Variante: unrestricted (la lista tal cual) o new_only (solo productos que el cliente nunca compró). |
| `round_key` | string | sí |  | Ronda: R seguida del lunes que la abre, AAAA-MM-DD. |
| `pairs` | int64 |  | pares | Pares (ronda, cliente) evaluados: clientes de la base que compraron en la semana. |
| `hit_rate` | float64 |  |  | hit@10: parte de los pares con al menos un producto de la lista comprado en la semana. |
| `recall` | float64 |  |  | recall@10: productos de la lista comprados sobre productos distintos comprados. |
| `precision` | float64 |  |  | precisión@10: productos de la lista comprados sobre 10. |
| `ndcg` | float64 |  |  | NDCG@10: acierto con descuento por lugar. |
| `coverage` | float64 |  |  | Productos distintos de las listas de la ronda sobre los comprados en los 365 días anteriores. |
| `seal_state` | string | sí |  | sealed (la configuración sellada) o post_seal (otra, posterior al sello). |
| `suppressed` | bool |  |  | Celda oculta: tiene menos clientes que el mínimo, o es la más chica de un grupo que mostraría a otra por resta. |
<!-- table:fact_method_round:end -->

### `fact_method_total`

Cada método y variante en toda la prueba.

Clave: `method_key`, `variant_key`, `seal_state`. Archivo: `outputs/powerbi/fact_method_total.parquet`.

<!-- table:fact_method_total:start -->
| Columna | Tipo | Clave | Unidad | Descripción |
| --- | --- | --- | --- | --- |
| `method_key` | string | sí |  | Método: offer_list (la lista), chosen_discovery (el modelo elegido) o b0 a b6 (las líneas base). |
| `variant_key` | string | sí |  | Variante: unrestricted (la lista tal cual) o new_only (solo productos que el cliente nunca compró). |
| `pairs` | int64 |  | pares | Pares evaluados en las rondas de la prueba. |
| `hit_rate` | float64 |  |  | hit@10 de la prueba. |
| `ci_low` | float64 |  |  | Límite inferior del intervalo del 95 % (remuestreo por cliente). |
| `ci_high` | float64 |  |  | Límite superior del intervalo del 95 %. |
| `wilson_low` | float64 |  |  | Límite inferior del intervalo de Wilson (informativo). |
| `wilson_high` | float64 |  |  | Límite superior del intervalo de Wilson (informativo). |
| `recall` | float64 |  |  | recall@10 de la prueba. |
| `precision` | float64 |  |  | precisión@10 de la prueba. |
| `ndcg` | float64 |  |  | NDCG@10 de la prueba. |
| `coverage` | float64 |  |  | Cobertura media de las rondas de la prueba. |
| `seal_state` | string | sí |  | sealed (la configuración sellada) o post_seal (otra, posterior al sello). |
| `suppressed` | bool |  |  | Celda oculta: tiene menos clientes que el mínimo, o es la más chica de un grupo que mostraría a otra por resta. |
<!-- table:fact_method_total:end -->

### `fact_segment`

Cada método y variante por segmento. Una celda con menos clientes que el mínimo está vacía.

Clave: `method_key`, `variant_key`, `segment_key`, `seal_state`. Archivo: `outputs/powerbi/fact_segment.parquet`.

<!-- table:fact_segment:start -->
| Columna | Tipo | Clave | Unidad | Descripción |
| --- | --- | --- | --- | --- |
| `method_key` | string | sí |  | Método: offer_list (la lista), chosen_discovery (el modelo elegido) o b0 a b6 (las líneas base). |
| `variant_key` | string | sí |  | Variante: unrestricted (la lista tal cual) o new_only (solo productos que el cliente nunca compró). |
| `segment_key` | string | sí |  | Segmento: mayorista o minorista, con una factura previa o varias. |
| `pairs` | int64 |  | pares | Pares evaluados del segmento. |
| `hit_rate` | float64 |  |  | hit@10 del segmento. |
| `ci_low` | float64 |  |  | Límite inferior del intervalo del 95 %. |
| `ci_high` | float64 |  |  | Límite superior del intervalo del 95 %. |
| `seal_state` | string | sí |  | sealed (la configuración sellada) o post_seal (otra, posterior al sello). |
| `suppressed` | bool |  |  | Celda oculta: tiene menos clientes que el mínimo, o es la más chica de un grupo que mostraría a otra por resta. |
<!-- table:fact_segment:end -->

### `fact_choice`

Las 48 recetas medidas en la validación, con la elegida.

Clave: `candidate`. Archivo: `outputs/powerbi/fact_choice.parquet`.

<!-- table:fact_choice:start -->
| Columna | Tipo | Clave | Unidad | Descripción |
| --- | --- | --- | --- | --- |
| `candidate` | string | sí |  | Receta candidata: modelo, tamaño, regularización y peso de la tendencia. |
| `base_model` | string |  |  | als, cosine o rules. |
| `params` | string |  |  | Parámetros del modelo base. |
| `trend_weight` | float64 |  |  | Peso de la tendencia en la mezcla. |
| `val_hit_new` | float64 |  |  | hit@10 solo nuevos en las rondas de validación. |
| `val_coverage` | float64 |  |  | Cobertura media en esas rondas. |
| `kept` | bool |  |  | Quedó a menos de la tolerancia de la mejor. |
| `chosen` | bool |  |  | Es la receta elegida y sellada. |
| `fit_rounds` | int8 |  | rondas | Rondas de validación con que se midió. |
<!-- table:fact_choice:end -->

### `fact_balance`

El equilibrio del grupo de control en la cohorte del lanzamiento.

Clave: `covariate_key`, `seal_state`. Archivo: `outputs/powerbi/fact_balance.parquet`.

<!-- table:fact_balance:start -->
| Columna | Tipo | Clave | Unidad | Descripción |
| --- | --- | --- | --- | --- |
| `covariate_key` | string | sí |  | Covariable del equilibrio: recency_days, invoices_365, spend_365, tenure_days o bulk. |
| `offer_mean` | float64 |  |  | Media en el grupo de oferta. |
| `control_mean` | float64 |  |  | Media en el grupo de control. |
| `smd` | float64 |  |  | Diferencia estandarizada. |
| `seal_state` | string | sí |  | sealed (la configuración sellada) o post_seal (otra, posterior al sello). |
<!-- table:fact_balance:end -->

### `fact_experiment`

El A/A del control sellado y la calibración de cada prueba.

Clave: `metric`, `test`, `seal_state`. Archivo: `outputs/powerbi/fact_experiment.parquet`.

<!-- table:fact_experiment:start -->
| Columna | Tipo | Clave | Unidad | Descripción |
| --- | --- | --- | --- | --- |
| `metric` | string | sí |  | m1 (parte de las semanas con compra) o m2 (gasto en libras). |
| `test` | string | sí |  | preregistered (CUPED y permutación estratificada), normal_raw o normal_cuped (informativas). |
| `aa_diff` | float64 |  |  | Diferencia entre los grupos del A/A (nadie recibió una oferta: no es el efecto de nada). |
| `aa_p` | float64 |  |  | p de dos colas. |
| `aa_ci_low` | float64 |  |  | Límite inferior del intervalo del 95 %. |
| `aa_ci_high` | float64 |  |  | Límite superior del intervalo del 95 %. |
| `calibration_rejection` | float64 |  |  | Parte de los sorteos nuevos del control que esta prueba rechazó con p < 0,05. |
| `seal_state` | string | sí |  | sealed (la configuración sellada) o post_seal (otra, posterior al sello). |
<!-- table:fact_experiment:end -->

### `fact_mde`

Lo que una operación de este tamaño podría ver con 10, 20 y 30 % de control.

Clave: `metric`, `holdout_share`, `seal_state`. Archivo: `outputs/powerbi/fact_mde.parquet`.

<!-- table:fact_mde:start -->
| Columna | Tipo | Clave | Unidad | Descripción |
| --- | --- | --- | --- | --- |
| `metric` | string | sí |  | m1 o m2. |
| `holdout_share` | float64 | sí |  | Parte de la cohorte que se deja como control. |
| `holdout_size` | int64 |  | clientes | Clientes en ese control. |
| `mde` | float64 |  |  | Menor diferencia que la prueba vería (M1 en parte de las semanas, M2 en libras). |
| `mde_relative` | float64 |  |  | El mismo número sobre la media del resultado. |
| `seal_state` | string | sí |  | sealed (la configuración sellada) o post_seal (otra, posterior al sello). |
| `suppressed` | bool |  |  | Celda oculta: tiene menos clientes que el mínimo, o es la más chica de un grupo que mostraría a otra por resta. |
<!-- table:fact_mde:end -->

### `fact_rule`

Las reglas de pares de mayor rule_lift con soporte suficiente. Sin relaciones: lleva dos claves de producto y se muestra como tabla.

Clave: `antecedent_key`, `consequent_key`. Archivo: `outputs/powerbi/fact_rule.parquet`.

<!-- table:fact_rule:start -->
| Columna | Tipo | Clave | Unidad | Descripción |
| --- | --- | --- | --- | --- |
| `antecedent_key` | string | sí |  | Producto de partida de la regla. |
| `consequent_key` | string | sí |  | Producto que la regla anticipa. |
| `antecedent_es` | string |  |  | Descripción del producto de partida. |
| `consequent_es` | string |  |  | Descripción del producto que anticipa. |
| `support` | int64 |  | facturas | Facturas de la historia del lanzamiento con los dos productos. |
| `confidence` | float64 |  |  | Facturas con los dos sobre facturas con el primero. |
| `rule_lift` | float64 |  |  | Confianza sobre la parte de facturas con el segundo. |
<!-- table:fact_rule:end -->

### `fact_evaluation_summary`

Los diez criterios con su veredicto.

Clave: `criterion_key`, `seal_state`. Archivo: `outputs/powerbi/fact_evaluation_summary.parquet`.

<!-- table:fact_evaluation_summary:start -->
| Columna | Tipo | Clave | Unidad | Descripción |
| --- | --- | --- | --- | --- |
| `criterion_key` | string | sí |  | Criterio, de C01 a C10. |
| `tested_value_es` | string |  |  | La cantidad que el umbral compara, con su unidad. |
| `point_value` | float64 |  |  | Valor puntual de la misma cifra. |
| `ci_low` | float64 |  |  | Límite inferior del intervalo. |
| `ci_high` | float64 |  |  | Límite superior del intervalo. |
| `passed` | bool |  |  | Se cumple; vacío si no hay umbral. |
| `seen_by_research` | string |  |  | Si la investigación vio esta cifra antes de fijar el criterio. |
| `seen_by_planner` | string |  |  | Si el planificador la vio. |
| `verdict_es` | string |  |  | Veredicto, el mismo del resumen. |
| `seal_state` | string | sí |  | sealed (la configuración sellada) o post_seal (otra, posterior al sello). |
<!-- table:fact_evaluation_summary:end -->

### `fact_validation`

Qué dijo cada regla de validación en cada corrida.

Clave: `run_key`, `rule_id`. Archivo: `outputs/powerbi/fact_validation.parquet`.

<!-- table:fact_validation:start -->
| Columna | Tipo | Clave | Unidad | Descripción |
| --- | --- | --- | --- | --- |
| `run_key` | string | sí |  | Corrida que lo escribió. |
| `rule_id` | string | sí |  | Regla de validación: V10 a V18. |
| `name_es` | string |  |  | Regla, en español. |
| `severity` | string |  |  | bloqueante, advertencia o informativa. |
| `scope` | string |  |  | Alcance de la regla. |
| `aggregation` | string |  |  | source, per_run o latest. |
| `status` | string |  |  | pasa o falla. |
| `rows_affected` | int64 |  | filas | Filas afectadas. |
<!-- table:fact_validation:end -->

### `fact_offer_customer`

La lista de cada cliente. Tiene números de cliente: vive solo en outputs/private y nunca se versiona (D30, D45).

Clave: `round_key`, `customer_id`, `rank`. Tabla privada: `outputs/private/`, nunca versionada.

<!-- table:fact_offer_customer:start -->
| Columna | Tipo | Clave | Unidad | Descripción |
| --- | --- | --- | --- | --- |
| `round_key` | string | sí |  | Ronda: R seguida del lunes que la abre, AAAA-MM-DD. |
| `customer_id` | int64 | sí |  | Número de cliente del archivo (solo en outputs/private, nunca versionado). |
| `rank` | int8 | sí |  | Lugar en la lista, de 1 a 10. |
| `product_key` | string |  |  | Producto: su código del archivo. |
| `source_key` | string |  |  | Origen del producto en la lista: repeat, discovery o fallback. |
| `group_key` | string |  |  | Grupo del cliente: offer (recibe la lista) o control (la lista se arma y no se entrega). |
| `bought` | bool |  |  | El cliente compró ese producto en la semana de la ronda; vacío si la semana no llegó. |
<!-- table:fact_offer_customer:end -->
