# Registro de decisiones

Una entrada por decisión, con sus siete campos: Contexto, Opciones, Decisión, Motivo, Afecta, Quién y Estado. Donde había un solo camino razonable, «Opciones» lo dice y explica por qué. Las propuestas del agente de planificación (Opus) quedan para revisión del dueño; las del dueño citan el registro del documento de seguimiento (`odd/tasks/portfolio-projects.md`). El dueño pidió autonomía (S12): cada pregunta abierta de research.md tiene aquí un valor por defecto razonable y reversible, y solo las elecciones de producto que le pertenecen van a su lista (plan, sección 29). Las cifras salen de `research.md`, de los documentos del proyecto 07 y de la comprobación del agente de planificación (`requirements.md`, sección 4), que leyó **solo las líneas con fecha anterior al 2011-08-01**. Sus scripts y salidas se versionan en `research/` (`p01_weekly_validation.py`, las 13 rondas semanales de validación con todos los métodos; `p02_control_preperiod.py`, el grupo de control en un período previo; salidas `p01.out` y `p02.out`), y cada uno se corre desde cualquier carpeta con `.venv\Scripts\python -I research/<script>.py` (con `OPENBLAS_NUM_THREADS=1` para `p01`).

**Correspondencia con las preguntas abiertas de research.md**: 1 (cadencia semanal o mensual) → D05; 2 (métrica principal) → D08; 3 (mayoristas) → D07; 4 (tamaño y estratos del grupo de control) → D14; 5 (métrica de dinero) → D15; 6 (clientes sin historia) → D06; 7 (búsqueda de hiperparámetros) → D12; 8 (cambios del texto del sitio) → D33. Lo que el pedido del plan agregó: la orquestación → D26; el grupo de control y qué puede decir el sitio → D14, D15 y D16; la ventana de prueba y lo visto → D17 y D41; el nombre del paquete y el alcance → D40; el sello → D21; las líneas base → D18; el tablero y los archivos del sitio → D37 y D38; la distancia con los proyectos 02 y 04 → D39.

Estados: **vigente**, **pendiente del dueño**, **reemplazada por Dxx**.

---

## D01 Enfoque: un flujo semanal que arma una lista por cliente, aparta un grupo de control y se evalúa una vez en 18 rondas selladas, sin medir ningún efecto

- **Contexto**: el sitio promete una oferta para cada cliente, armada cada semana con lo que se compra junto y lo que compran clientes parecidos, entregada al CRM, con un grupo de control listo (S9). El archivo tiene facturas y ninguna oferta (research.md): no se puede medir el efecto de una oferta. Sí se puede medir qué tan bien una lista anticipa lo que el cliente compra después, con un corte en el tiempo y líneas base.
- **Opciones**: (a) solo un modelo de recomendación medido con un corte, sin flujo; (b) un flujo semanal que arma, entrega y sigue las listas, con un grupo de control sorteado y comprobado, evaluado una vez en rondas que nadie vio al elegir, contra líneas base, con criterios fijados antes; (c) además de (b), un efecto simulado y marcado como sintético.
- **Decisión**: (b), con C01-C10 (`requirements.md`, sección 8.1; D19) y lo esperable escrito: probablemente no se cumpla C03 (superar a la recompra propia) y C04 es incierto.
- **Motivo**: lo que marketing necesita es una lista por cliente que llegue sola al CRM y un grupo de control que permita medir la primera campaña real; (a) no lo entrega; (c) pone en el sitio un número que se lee como resultado (research.md, contradicción 6; D16).
- **Afecta**: todo el proyecto; `requirements.md`; `fact_evaluation_summary`; el README; el sitio.
- **Quién**: agente de planificación.
- **Estado**: vigente.

## D02 Fuente: el zip de UCI y su libro, fijados por tamaño y SHA-256; el flujo solo lee archivos locales y trata el libro como no confiable

- **Contexto**: `research/s00_download.py` baja el zip (45.622.418 bytes, `572e3627…e67bfb`) a `data/raw/`, comprueba su huella, extrae el único miembro por su nombre exacto (45.622.278 bytes, `bcbe73b3…2e980`) y guarda el manifiesto. Un `.xlsx` es un zip con XML: puede traer una bomba de descompresión, macros o vínculos externos.
- **Opciones**: (a) una descarga endurecida dentro del paquete, como el proyecto 04; (b) la descarga queda en el script de la investigación y el flujo comprueba tamaño y huella antes de leer, y abre el libro como zip para inspeccionar cada parte antes de pasarlo a openpyxl.
- **Decisión**: (b). `[source]` con las dos huellas; si una falta o no coincide, `fetch_source` termina con `SourceError` (salida 3) y nombra el runbook R1. V03 recorre las partes del libro (tope descomprimido, razón de compresión, sin `vbaProject`, `externalLink` ni `activeX`); openpyxl abre en `read_only=True`, `data_only=True`. Las líneas canónicas se escriben una vez en `data/interim/lines.parquet` con su manifiesto y se reusan mientras la huella no cambie (leer el libro tarda; P4 midió 36,5 s solo en leerlo).
- **Motivo**: sin red en el flujo desaparece una superficie de ataque y de variación; la huella ya está medida dos veces (P4 y esta investigación, que dieron la misma); inspeccionar el zip antes de openpyxl ataja lo que openpyxl no limita.
- **Afecta**: `sources.py`, `workbook.py`; V01-V07; runbook R1 y R2; README «Cómo correrlo».
- **Quién**: agente de planificación.
- **Estado**: vigente; una descarga en el paquete no se pide.
- **Nota (2026-11-19, U04)**: V03 agrega a lo decidido tres comprobaciones que no cambian el contrato: ninguna parte con nombre que salga del archivo, ninguna parte cifrada y ningún DTD ni entidad en una parte XML (se lee entera, por bloques de 64 KiB que se solapan 4.096 bytes; la primera versión miraba solo los primeros 4.096 bytes y un comentario delante de la declaración la escondía: la revisión de U04 lo encontró y se corrigió antes de U09). Con el archivo real, las dos hojas pesan 156.346.796 y 160.448.656 bytes descomprimidas a razón de 7,0, así que `max_part_bytes = 400.000.000` queda (2,5 veces la mayor) y el tope de razón es 100 a 1 para partes de 64 KiB o más (una parte de ceros se comprime mil a uno). Cada celda se convierte como la entrega openpyxl en el archivo real (verificado en las primeras 3.000 filas de cada hoja, de 2009 y 2010): factura y código como número o texto, descripción y país como texto (un número se guarda como su texto), cantidad entera, precio decimal o entero, cliente entero de cinco dígitos o vacío. `line_key` es hoja por 10.000.000 más la fila de la hoja. El rol de cada línea (RF04) es de U05: `lines.parquet` de U04 trae las líneas sin rol.

## D03 Copias, repeticiones y roles: se quitan las 22.523 copias del solapamiento, se marcan las 11.812 repeticiones internas y las anulaciones no se descuentan de las compras

- **Contexto**: las dos hojas se pisan en diciembre de 2010 (22.523 filas exactas repetidas); hay además 11.812 repeticiones dentro del conjunto, que pueden ser líneas reales (research.md). El proyecto 04 descontó cada anulación de la compra que anula para definir la baja; el emparejamiento depende de la regla (94,0 % del valor con la de la investigación frente a 95,2 % con la del 04, sin verificar).
- **Opciones**: (a) quitar todas las repeticiones; (b) quitar las copias entre hojas y conservar las internas marcadas; para las anulaciones, (c) descontarlas como el 04 o (d) dejarlas con su rol y contar como compra la línea de compra.
- **Decisión**: (b) y (d). Los roles, en el orden de RF04: `cancellation`, `adjustment`, `non_product`, `bad_price`, `guest_purchase`, `purchase`. Lo que un cliente «compró» en una semana son sus líneas `purchase`, aunque después anule alguna; la parte anulada se informa (C10).
- **Motivo**: (a) borraría líneas reales; el interés del cliente en un producto es la compra, y una regla de neteo sin verificar agregaría ruido a la lista y a la métrica sin cambiar qué se le ofrece.
- **Afecta**: `workbook.py`, `lines.py`; AC03, AC04; `data.json`; diccionario.
- **Quién**: agente de planificación.
- **Estado**: vigente.

## D04 Producto: cinco dígitos y hasta tres letras; los `DCGS…` y los vales quedan fuera

- **Contexto**: la regla de la investigación (`^\d{5}[A-Za-z]{0,3}$`) deja fuera los 63 códigos de servicio (POST, DOT, M, C2, D, S, BANK CHARGES…), y también 124 líneas positivas `DCGS…` (1.154,72 £) y los vales `gift_0001_…` (research.md, riesgos).
- **Opciones**: (a) la regla de la investigación; (b) una lista explícita de códigos de servicio y todo lo demás como producto; (c) la regla más una excepción para `DCGS`.
- **Decisión**: (a), en `[catalogue] product_code_regex`, sellada.
- **Motivo**: es la que midió la investigación y la que reproduce las cifras del 04; los `DCGS` son 124 líneas de 1,04 millones, y un vale de regalo no es un producto que ofrecer.
- **Afecta**: `lines.py`; el catálogo; AC04.
- **Quién**: agente de planificación.
- **Estado**: pendiente del dueño (plan, sección 29, ítem 15).

## D05 Calendario y cadencia: semanal, cada lunes, con ventanas de 7 días que no se pisan, dentro del calendario del proyecto 04

- **Contexto**: el sitio dice «cada semana»; el 04 usa entregas mensuales, con lanzamiento al 2011-07-31 y cierre con los 9 días de diciembre (research.md, pregunta 1). Con cortes semanales y ventanas de 90 días, un día cae en 13 ventanas de prueba. La mediana entre compras de un cliente es de 25 días.
- **Opciones**: (a) mensual con ventanas de 30 días, como el 04; (b) semanal con ventanas de 90 días; (c) semanal con ventanas de 7 días.
- **Decisión**: (c). Lanzamiento `L2011-07-31`; 18 entregas semanales de lunes a domingo (`W2011-08-01` a `W2011-11-28`); cierre `C2011-12-05` con el 2011-12-05 al 2011-12-09. Rondas de prueba R2011-08-01 a R2011-11-28; R2011-12-05 queda censurada (D42). Rondas de validación R2011-05-02 a R2011-07-25 (13), todas con su semana antes del 2011-08-01.
- **Motivo**: (c) cumple lo que dice el sitio, cada día de compra cuenta en una sola ronda (sin la fuga de 13 ventanas) y la entrega de cada semana trae a la vez el resultado de la ronda anterior; las fechas del 04 hacen comparables los dos proyectos en el tiempo. (b) cuenta el mismo futuro 13 veces; (a) contradice el sitio. Con 7 días hay menos compradores por ronda (de 204 a 347 en la validación, `p01`), y 18 rondas lo compensan.
- **Afecta**: `calendar.py`, `deliveries.py`; `[calendar]`; RF05; AC05, AC18; el DAG (`0 6 * * 1`).
- **Quién**: agente de planificación.
- **Estado**: pendiente del dueño (plan, sección 29, ítem 1: antes de U05).

## D06 Base de contactos: los clientes con alguna compra en los 365 días anteriores; quien nunca compró no recibe lista

- **Contexto**: research.md, pregunta 6: 944 clientes no tenían factura antes del corte del 2011-06-01, y el sitio habla de completar con las reglas de canasta «cuando falta historia». En la validación, de 20 a 36 compradores por semana no estaban en la base, y de 16 a 33 de ellos hacían su primera compra (`p01`).
- **Opciones**: (a) todos los clientes con alguna compra previa; (b) los activos en 90 días, como el 04; (c) los que compraron en el último año.
- **Decisión**: (c), con `[base] lookback_days = 365`. Un cliente que nunca compró no existe para el CRM hasta su primera compra, así que no recibe lista; uno con una sola factura recibe su recompra, el descubrimiento y la reserva. Los compradores fuera de la base se cuentan (C10).
- **Motivo**: un CRM no manda campañas a quien no conoce; (a) incluye clientes perdidos hace dos años; (b) deja fuera a los que compran cada dos o tres meses (el 17,2 % de los intervalos pasa de 90 días, research.md).
- **Afecta**: `base.py`; RF08; la cohorte del experimento; `fact_round_ops`.
- **Quién**: agente de planificación.
- **Estado**: pendiente del dueño (plan, sección 29, ítem 6).

## D07 Mayoristas: entran en la base y en las ofertas; la regla del proyecto 02 marca un estrato y un corte de informe, nunca una variable del modelo

- **Contexto**: research.md, pregunta 3 y contradicción 3: con la regla del 02, 340 clientes son mayoristas al lanzamiento (el 02 declara 335); en la cohorte del período previo, 362 de 4.320 (`p02`). Compran lotes grandes y muchos productos.
- **Opciones**: (a) excluirlos; (b) tratarlos aparte con otra lista; (c) incluirlos y usar la marca como estrato del control y corte de informe.
- **Decisión**: (c): `bulk` con `[base] bulk_min_median_qty = 24` y `bulk_min_lines = 3` en los 365 días anteriores; estrato del control (D14); corte de C10 y de `fact_segment`.
- **Motivo**: una tienda que vende también a mayoristas les manda ofertas igual; estratificar evita que el sorteo los concentre en un grupo; usar la marca como variable mezclaría la segmentación del 02 con este proyecto (D39).
- **Afecta**: `base.py`, `holdout.py`; `dim_segment`; el sitio (fila 2 de la sección 30 del plan).
- **Quién**: agente de planificación.
- **Estado**: pendiente del dueño (plan, sección 29, ítem 3).

## D08 Métrica principal: hit@10 sobre los pares (ronda, cliente) que compraron en la semana, sin restricción para la lista y solo nuevos para el descubrimiento

- **Contexto**: research.md, pregunta 2: a 90 días, repetir lo propio acierta el 83 %; solo con productos nuevos, reglas y ALS superan apenas a la popularidad. El sitio dice «precisión@k». Con 7 días (`p01`), la recompra propia acierta el 79,1 % y lo más vendido de 28 días el 54,9 %; en nuevos, 17,2 % y 30,9 %.
- **Opciones**: (a) precisión@10; (b) hit@10; (c) NDCG@10; para el universo, (d) todos los clientes de la base, compren o no, o (e) solo los que compraron en la semana.
- **Decisión**: (b) con (e) como criterio; precisión@10, recall@10, NDCG@10 y cobertura en C10. Dos variantes: sin restricción (la lista que se entrega, C01-C03) y solo nuevos (el modelo de descubrimiento, C04).
- **Motivo**: hit@10 dice lo que entiende marketing («en cuántos clientes la lista tenía algo que compraron») y es la de la investigación; (e) es la evaluación de orden habitual, y que un cliente no compre en la semana no depende de la lista (sin ofertas, nadie compra por ella); la precisión con 7 días es muy baja y casi no separa métodos.
- **Afecta**: `metrics.py`, `evaluation.py`; C01-C05, C10; el sitio (fila 8).
- **Quién**: agente de planificación.
- **Estado**: vigente.

## D09 Recomendadores: popularidad, recompra propia, reglas de pares, ALS implícito, similitud coseno y su mezcla con la tendencia; mlxtend solo para comprobar; sin RAG

- **Contexto**: el sitio nombra reglas de asociación con mlxtend y «un filtrado colaborativo por producto o un ALS implícito» con implicit (S9). La investigación calculó las reglas con una matriz dispersa propia y las comprobó contra mlxtend (diferencia máxima 1,1 × 10⁻¹⁶); mlxtend arma tablas de itemsets que con 4.600 productos y 39.000 canastas pesan más que la matriz. En `p01`, ALS, las reglas y la similitud solos pierden contra lo más vendido de 28 días en nuevos; mezclados con la tendencia, ALS gana.
- **Opciones**: (a) solo reglas; (b) solo ALS; (c) los seis recomendadores como candidatas y líneas base, con la mezcla, y la elección en validación; (d) un modelo de lenguaje o RAG sobre las descripciones.
- **Decisión**: (c). Las reglas se calculan con la matriz propia (`recommend/rules.py`) y una prueba las compara con mlxtend en el accesorio (mlxtend queda en `requirements-dev.txt`); ALS y coseno con implicit 0.7.3.
- **Motivo**: (c) mide lo que el sitio promete y deja que la validación elija; (d) no agrega nada para ordenar productos por compras y no se puede auditar contra una línea base.
- **Afecta**: `recommend/*`; `requirements*.txt`; AC11; el sitio (filas 9 y 10).
- **Quién**: agente de planificación.
- **Estado**: vigente.
- **Nota (2026-11-19, U09)**: las reglas se cuentan con una matriz de coocurrencia dispersa (`B.T @ B` de las facturas por los productos), no con una densa de 4.600 por 4.600: la prueba contra mlxtend (`fpgrowth` y `association_rules` con `max_len = 2`) da las mismas parejas y las mismas confianzas y lifts a 1 × 10⁻⁹ en el accesorio. Los modelos de implicit se piden con un hilo, sin GPU y sin el aviso `ParameterWarning` (dice, con la ruta de su propio archivo, que convirtió una matriz a CSR). Los módulos comparten una `RoundData` (`recommend/context.py`, que el plan no nombraba) que arma una vez el catálogo, lo que compró cada cliente, las cuentas de popularidad y el orden de desempate de una ronda, y que guarda sin volver a armarlas la matriz de clientes por productos y las cuentas de pares.

## D10 La lista que se entrega: hasta 7 productos de la propia recompra, el resto nuevos del modelo elegido y la reserva de lo más vendido de 28 días

- **Contexto**: en la validación (`p01`), la recompra propia sola acierta 79,1 %; con 7 de recompra y el resto de la mezcla de ALS con la tendencia, 77,1 % (−1,99 puntos, de −3,01 a −0,88); con 5 y 5, 71,6 %; con 3 y 7, 64,9 %. Un producto que el cliente ya compra cada mes probablemente lo compraría sin oferta (Jannach y Jugovac, 2019, research.md); la página promete «lo que se compra junto y lo que compran clientes parecidos».
- **Opciones**: (a) 10 de recompra; (b) 7 y 3; (c) 5 y 5; (d) elegir la mezcla en la validación.
- **Decisión**: (b), en `[recommend] repeat_slots = 7`, `discovery_slots = 3`, `fallback_days = 28`; cada producto con su origen (`repeat`, `discovery`, `fallback`). El descubrimiento toma los lugares que la recompra deja libres; la reserva, los que el descubrimiento no llena.
- **Motivo**: (a) maximiza el acierto pero no es una oferta nueva; (d) elegiría siempre (a), porque el acierto premia anticipar lo que el cliente compraría igual; (b) cuesta unos 2 puntos en la validación y deja tres productos nuevos por semana para cada cliente, que es lo que el sitio promete. El margen de C02 (5 puntos) es el precio que se acepta.
- **Afecta**: `offers.py`; RF11; AC12; C02, C03; el sitio (fila 7).
- **Quién**: agente de planificación.
- **Estado**: pendiente del dueño (plan, sección 29, ítem 2).

## D11 Reajuste semanal con la receta sellada; desempate fijo

- **Contexto**: los proyectos 03 a 07 entrenan una vez en el lanzamiento y congelan el artefacto. Una lista que no se reajusta no ve los productos nuevos (el 9,8 % de lo comprado en la prueba de la investigación no estaba en el catálogo de entrenamiento) ni lo que el cliente compró la semana anterior. En `p01`, ALS reajustado con un hilo y la misma semilla dio factores idénticos.
- **Opciones**: (a) ajustar una vez y congelar los factores; (b) congelar la receta (modelos, parámetros, pesos, reglas, mezcla) y reajustar cada semana con la historia anterior al lunes.
- **Decisión**: (b). Lo sellado es la receta (D21); los factores de cada ronda se guardan con su huella en `model_registry`. El desempate es puntaje, después popularidad global, después `stock_code`.
- **Motivo**: es lo que haría una operación real cada lunes y no abre ninguna fuga (cada reajuste ve solo el pasado); el determinismo medido hace que repetir una ronda dé las mismas listas byte a byte (RNF01).
- **Afecta**: `launch.py`, `weekly.py`; `model_registry`; AC17.
- **Quién**: agente de planificación.
- **Estado**: vigente.
- **Nota (2026-11-19, U12)**: la ronda semanal (`weekly.py`) hace, para la entrega `W<s>`: comprueba el sello (sin la parte del lanzamiento, o con el de otra configuración, no hace nada y no escribe nada), sigue la ronda `R<s>` (`round_outcomes`: una fila por cliente de su base, por intención de tratar, con las listas del control también) y arma la ronda `R<s + 7>` en una sola transacción: base y covariables de la historia anterior a ese lunes, asignación por la función hash de quien entró, reajuste con la receta sellada, listas de todos los clientes de la base (las del control con su grupo, nunca entregadas) y listas de las líneas base. La última semanal arma la ronda censurada del cierre; el cierre solo sigue (cinco días). Una ronda ya emitida se recalcula y se compara con lo guardado en lugar de escribirse (`status = done`; si difiere, `ScoringError` y nada cambia), y `round_ops` se escribe aparte al final de la corrida (`write_round_ops`), porque `delivered` lo conoce U13. La comprobación del sello de la tarea `deliver` es de U18 (que usa `registry.require_launch_seal`); aquí la aplica `run_round`.
- **Nota (2026-11-19, U09)**: el desempate no suma un número pequeño al puntaje (la investigación sumaba `popularidad / máximo × 10⁻⁶`, que con puntajes de otra escala puede no desempatar o desempatar de más). Cada puntaje `float32` se vuelve un entero que lo ordena exactamente (el `-0,0` es `0,0`, una unidad del último lugar es una diferencia) y debajo va el lugar del producto en el orden fijo: nunca dos claves de una fila son iguales y el orden no depende del orden de las columnas. Un catálogo de 65.535 productos o más no cabe (el real tiene unos 4.600) y es un error.

## D12 La elección: 48 candidatas medidas solo en las 13 rondas de validación, por hit@10 solo nuevos, con una tolerancia de medio punto a favor de la cobertura

- **Contexto**: research.md, pregunta 7: ALS y las reglas usaron valores fijados de antemano. En `p01`, con los valores de la investigación, la mezcla de ALS con la tendencia (peso 1) dio 34,7 % en nuevos y con peso 2 34,9 %, pero su cobertura cae de 0,076 a 0,023.
- **Opciones**: (a) los valores de la investigación, sin búsqueda; (b) una grilla acotada en las rondas de validación; (c) una búsqueda amplia con validación cruzada en el tiempo.
- **Decisión**: (b): ALS con 3 × 2 valores (factores 32, 64 y 128; regularización 0,01 y 0,1; 15 iteraciones; alfa 20), coseno con K 50, 100 y 200, reglas con soporte 5, 10 y 20 facturas; cada uno con el peso de la tendencia 0, 0,5, 1 y 2: 48 candidatas. Se elige la de mayor hit@10 solo nuevos sobre los pares de las 13 rondas de validación (3.219 en `p01`); entre las que quedan a menos de 0,005, la de mayor cobertura; después el menor peso y la más simple. B4-B6 toman su mejor parámetro con peso 0.
- **Motivo**: (a) deja ALS en desventaja injusta (la investigación lo dijo); (c) cuesta más de lo que el lanzamiento permite (unos 5,6 s por ronda y candidata, `p01`) y no cambia lo que se puede afirmar; la tolerancia evita elegir una lista casi igual para todos por medio punto.
- **Afecta**: `choose.py`; `[grid]`; RF12; AC14; `fact_choice`; C04 (la cifra de validación de la elegida es optimista: se eligió en las mismas rondas).
- **Quién**: agente de planificación.
- **Estado**: pendiente del dueño (plan, sección 29, ítem 7).
- **Nota (2026-11-19, U11)**: cada cifra de una candidata en una ronda son cuatro enteros (pares, aciertos, productos distintos en las listas y productos con una línea de canasta en los 365 días anteriores), así que ninguna suma de decimales decide la elección y el sello se reproduce al dígito; la tasa de la candidata es sus aciertos sobre sus pares en todas las rondas y su cobertura, la media de `distintos / catálogo` de las rondas. Solo se puntúan los clientes evaluados de cada ronda (unos 250 de los 4.300 de la base), no la base entera: cada candidata cuesta una mezcla, una selección y una métrica sobre una matriz pequeña, y lo que pesa es ajustar ALS y coseno (una vez por ronda y parámetro, compartido por los cuatro pesos). «A menos de la tolerancia» se juzga con 1 × 10⁻¹² de margen (una diferencia que en decimal es la tolerancia y en binario queda una unidad debajo no entra) y la mejor candidata siempre queda, con tolerancia 0 también; el desempate agrega, después del tamaño, la regularización menor y el nombre. La tasa de la elegida es optimista (se eligió en las mismas rondas): C04 lo dice. Una línea del primer día de la prueba o posterior es un `ValidationLeakError` (M04; runbook R5) antes de calcular nada.

## D13 Artefactos: arreglos `.npy` con su huella, leídos sin pickle

- **Contexto**: implicit guarda sus modelos con `numpy.savez`, que puede llevar objetos; los proyectos 03, 06 y 07 prohibieron pickle (D30 del 03, D20 del 06, D13 del 07).
- **Opciones**: (a) el guardado de implicit; (b) los arreglos de cada componente como `.npy` y un `artifact.json` con tamaño y huella.
- **Decisión**: (b); `numpy.load(allow_pickle=False)` y solo si la huella coincide (M02); se rechaza `.pkl`, `.pickle` y un `.npz` u otro archivo no listado.
- **Motivo**: un arreglo plano no ejecuta código al leerse; la huella hace verificable qué modelo armó cada lista.
- **Afecta**: `recommend/artifacts.py`; AC15; runbook R6.
- **Quién**: agente de planificación.
- **Estado**: vigente.
- **Nota (2026-11-19, U09)**: el manifiesto `artifact.json` lleva la versión, los parámetros y el tamaño y la huella de cada `.npy`, y se escribe al final; la huella que `model_registry` guarda es la del manifiesto. Al leer, se compara esa huella antes de leer nada; un nombre que no sea un `.npy` simple (un `.pkl`, un `.npz`, una ruta) se rechaza por su nombre aunque el manifiesto lo liste; un archivo de la carpeta que el manifiesto no lista también; y `numpy.load` corre con `allow_pickle=False`. Escribir otra vez lo mismo no cambia nada; escribir otro contenido en una carpeta con su manifiesto es un error (lo registrado no se reescribe).

## D14 El grupo de control: 20 % de la cohorte del lanzamiento, estratificado por recencia, frecuencia y la marca mayorista, sorteado una vez; los que entran después por una función hash; persistente; con lista que nunca se entrega

- **Contexto**: research.md, pregunta 4: con 20 % al azar simple, la recencia quedó en +0,117 de diferencia estandarizada. En el período previo (`p02`), con 18 estratos (terciles de recencia × terciles de facturas × la marca), la mayor diferencia de cinco covariables tuvo percentil 95 de 0,073 en 500 sorteos y ninguno pasó 0,10; al azar simple, 0,095 y el 3,6 % pasó 0,10. El MDE con CUPED fue de 0,95, 0,71 y 0,62 puntos de semanas con compra con 10, 20 y 30 %.
- **Opciones**: tamaño (a) 10 %, (b) 20 %, (c) 30 %; procedimiento (d) al azar simple, (e) estratificado; para los que entran después, (f) un sorteo nuevo cada semana o (g) una función hash con sal.
- **Decisión**: (b), (e) y (g). `[holdout] share = 0.20`, `seed = 20110801`, `salt = "personal-offers-holdout-v1"`, terciles por rango. La asignación es de solo inserción. El control tiene su lista (lo que se habría ofrecido) en `offer_lists` y nunca llega al CRM ni al CSV (M05).
- **Motivo**: 20 % equilibra el tamaño de la campaña y el menor efecto visible; estratificar reduce el desequilibrio a la mitad; la función hash no depende de quién más entró ni de un orden; la lista del control permite el análisis por intención de tratar en una operación real.
- **Afecta**: `holdout.py`; RF09; AC09, AC10; C06-C08; `control.json`.
- **Quién**: agente de planificación.
- **Estado**: pendiente del dueño (plan, sección 29, ítem 4).
- **Nota (2026-11-19, U13)**: M05 tiene dos mitades. `check_deliverable` mira a quién se va a entregar (que todos estén asignados a la oferta); `check_round_groups` mira que el grupo que dice cada lista de la ronda sea el de la asignación de su cliente, porque lo que sale se elige por el grupo de la lista: una lista que dice `control` para un cliente que las asignaciones pusieron en la oferta es un cliente al que nunca se le escribe, y es tan defecto como el inverso.

## D15 Las métricas y la prueba del experimento: semanas con compra y gasto en las 18 semanas, con CUPED y permutación estratificada; calibración con 500 sorteos

- **Contexto**: research.md, pregunta 5: el gasto tiene cola pesada (media 710 £, mediana 159 £ a 90 días) y la prueba normal rechazó el 10,4 % de 500 A/A. En `p02`: la normal sin ajustar del gasto rechazó el 7,8 %; con CUPED y permutación estratificada, el 4,2 % (M1) y el 4,4 % (M2); con el sorteo de semilla 0, las normales sin ajustar marcaron +0,71 puntos y +165,65 £ que no existen, y la preregistrada no (p de 0,088 y 0,313). CUPED bajó la desviación un 31 % (M1) y un 35 % (M2).
- **Opciones**: (a) la prueba normal sobre los valores; (b) el logaritmo del gasto; (c) CUPED con permutación estratificada; (d) recortar el gasto en un percentil.
- **Decisión**: (c) para M1 (parte de las 18 semanas con compra) y M2 (gasto en libras), con el período previo de 18 semanas; 2.000 permutaciones para el A/A sellado (C08) y 500 por sorteo en la calibración (C07; con 2.000 el cierre pasaría los 5 minutos). Las normales sin ajustar se informan en C10 para mostrar por qué no se usan.
- **Motivo**: la permutación es exacta bajo la hipótesis nula, y el archivo es justamente esa hipótesis; CUPED usa la historia previa sin sesgo y reduce el MDE; (b) cambia la pregunta (media geométrica) y (d) tira el gasto de los mayoristas.
- **Afecta**: `experiment.py`; `[experiment]`; C07, C08, C10; `fact_experiment`, `control.json`.
- **Quién**: agente de planificación.
- **Estado**: pendiente del dueño (plan, sección 29, ítem 5).
- **Nota (2026-11-19, U10)**: la permutación se hace dentro de cada estrato con el número de controles que tiene (las asignaciones salen de ordenar números al azar, los estratos en orden) y el p a dos colas es `(permutaciones tan lejos de cero como lo observado + 1) / (permutaciones + 1)`; un caso de ocho clientes se enumera entero (`exact_permutation`) y da el p exacto 10/36 que la prueba de Monte Carlo estima. En la calibración, cada sorteo `s` (de 1 a 500) usa `holdout.assign_cohort` con esa semilla y un generador de permutaciones de semilla 100.000 + `s`, compartido por M1 y M2 (la mitad del tiempo de la investigación, que sorteaba aparte): medida con 4.300 clientes sintéticos y las 500 × 500 del plan, tarda unos 38 s en esta máquina. Las dos pruebas normales (sobre el resultado sin ajustar y sobre el ajustado) se calculan en el mismo sorteo para la fila de C10; ninguna es la prueba preregistrada.
- **Nota (2026-11-19, U14)**: el A/A sellado usa la cohorte del lanzamiento (los clientes sorteados con `method = stratified`, con las covariables de su base de la primera ronda), M1 y M2 sobre las semanas de las rondas de prueba y CUPED con las `cuped_weeks` semanas anteriores a la primera ronda. La prueba preregistrada reparte `permutations` asignaciones dentro de los estratos con el generador de semilla 100.000 (`evaluation.AA_SEED`, la base de las semillas de la calibración, que usa 100.000 + 1 a 100.000 + `calibration_seeds`), compartidas por M1 y M2; su intervalo del 95 % es el de la aproximación normal de la diferencia ajustada (`diferencia ± z · error`), porque una permutación no da un intervalo. Las dos pruebas normales (sobre lo observado y sobre lo ajustado) se informan al lado con su p normal. El menor efecto detectable sale de la desviación del resultado ajustado de la cohorte y de `[experiment] mde_shares`. La función `evaluation.run_experiment` es pura (recibe la cohorte, la asignación y las líneas) y es la que corre `research/p04_close_dry_run.py` sobre el período previo del real.

## D16 Qué se puede decir del efecto de una oferta: nada; el sitio muestra el A/A y el menor efecto detectable

- **Contexto**: el sitio dice «cualquier efecto que se muestre antes es sintético y está marcado así»; research.md (contradicción 6) advierte que un efecto sintético al lado de «un grupo de control listo» se lee como resultado. Ninguna oferta se envió en el archivo.
- **Opciones**: (a) simular un efecto y marcarlo «sintético»; (b) no mostrar ningún efecto y mostrar lo que el grupo de control sí permite afirmar: el equilibrio, el A/A con su calibración y el menor efecto detectable.
- **Decisión**: (b). **Lo que el sitio puede afirmar**: (1) que el flujo aparta cada semana un 20 % de los clientes, sorteado una vez y equilibrado (C06, con su cifra); (2) que sin ofertas la diferencia entre los dos grupos es ruido, comprobado con la prueba que se usará (C08, con sus p) y con 500 sorteos que rechazan lo que deben (C07, con sus tasas); (3) que una operación de este tamaño vería un efecto de al menos el MDE (con su cifra y su unidad), y no uno menor; (4) que el efecto de una oferta no se puede medir con este archivo. **Lo que no puede afirmar**: ningún aumento, venta extra, conversión ni retorno de una oferta, ni marcado como sintético. Ningún nombre de campo, medida o figura dice `effect`, `uplift` ni `lift` de una oferta; el de las reglas es `rule_lift`.
- **Motivo**: (a) pone en el sitio un número inventado que alguien citará; (b) es honesto y le dice a un equipo de CRM algo útil: el tamaño que necesita su primera campaña.
- **Afecta**: `experiment.py`, `site_export.py`, `semantic_model.py`, el README, la ficha; AC23, AC27, AC28; el sitio (fila 3).
- **Quién**: agente de planificación.
- **Estado**: vigente.
- **Nota (2026-11-19, U14)**: ningún nombre de campo, de columna, de medida ni de tabla de la evaluación dice `effect`, `uplift` ni `lift`: las columnas del A/A son `aa_diff`, `aa_p`, `aa_ci_low` y `aa_ci_high`, y el menor efecto detectable es `mde`. Los textos de los criterios no dicen «efecto» ni «aumento»; la única frase con «efecto» es «menor efecto detectable», la que este registro permite (el nombre de C08, «El A/A no muestra un efecto que no existe», es el del preregistro y habla del A/A, no de una oferta).

## D17 La ventana de prueba y lo que se vio: las 18 rondas del 2011-08-01 al 2011-11-28; la investigación ya miró parte de ese período a 90 días y el planificador no lo abrió

- **Contexto**: la investigación midió líneas base con cortes del 2011-06-01 (semana de prueba del 2011-06-01 al 2011-08-29) y del 2011-09-01 (2011-09-01 al 2011-11-29), el A/A con resultados hasta el 2011-08-29, los recuentos por mes de las entregas de agosto a diciembre (`s06`), las estadísticas de canastas sobre todo el archivo (`s02`) y la baja del 04 con cortes de agosto y septiembre (`s05`). Toda ventana de fines de 2011 está vista en parte; la única sin mirar sería del 2011-11-30 al 2011-12-09.
- **Opciones**: (a) una prueba de diez días en diciembre; (b) una prueba en 2010, que nadie midió con líneas base; (c) las rondas de agosto a noviembre de 2011, con lo visto dicho en cada criterio.
- **Decisión**: (c). Las columnas «visto por la investigación» y «visto por el planificador» de la sección 8.1 de los requerimientos dicen, criterio por criterio, qué cifra se vio. Lo visto por la investigación es el orden de los métodos a 90 días y con otra población; ninguna cifra de 7 días, ni de la lista, ni de la mezcla, ni del sorteo sellado se calculó sobre la prueba. Los hechos del planificador (D41) leen solo líneas anteriores al 2011-08-01. Ninguna persona ni prueba calcula una métrica de la prueba antes de U21.
- **Motivo**: (a) da muy pocos pares para separar métodos; (b) no tiene historia suficiente (el archivo empieza en diciembre de 2009) y rompe la comparación con el 04; (c) tiene 18 rondas, el calendario del 04 y la honestidad de decir lo visto.
- **Afecta**: `[calendar]`; `requirements.md` 8.1; `seen_by_research`, `seen_by_planner` en `fact_evaluation_summary` y `summary.json`.
- **Quién**: agente de planificación.
- **Estado**: vigente.

## D18 Líneas base: al azar, popularidad global, lo más vendido de 28 días, la recompra propia, reglas, ALS y coseno; la recompra propia es la más fuerte

- **Contexto**: en `p01`, la popularidad de 28 días es la variante más fuerte de «lo más vendido» (30,9 % en nuevos frente a 23,2 % la de 90 días; igual sin restricción); la recompra propia es la base más fuerte sin restricción (79,1 %).
- **Opciones**: B2 con (a) 90 días, como la investigación, o (b) 28 días; (c) comparar la lista solo con lo más vendido, como dice el sitio, o (d) también con la recompra propia.
- **Decisión**: (b) y (d): B0 al azar, B1 popularidad global, B2 popularidad de 28 días, B3 recompra propia completada con B2, B4 reglas, B5 ALS, B6 coseno, todas con la misma reserva y el mismo desempate, emitidas cada ronda (sección 15 del plan).
- **Motivo**: comparar con la variante más débil de lo más vendido exageraría la ventaja; la recompra propia es lo que cualquiera puede hacer sin un modelo, y es la comparación honesta (C02, C03). El plan se prepara para que el modelo no la supere.
- **Afecta**: `baselines.py`; C01-C04, C10; `algorithms.json`.
- **Quién**: agente de planificación.
- **Estado**: vigente.
- **Nota (2026-11-19, U12)**: las ocho listas (B0-B6 y `chosen_discovery`) en las dos variantes salen de los mismos datos de la ronda (la historia anterior al lunes, la misma reserva y el mismo orden de desempate) y se emiten con cada ronda: 16 listas de 10 por cliente de la base, 160 filas de `baseline_lists` por cliente y ronda. B0 usa un generador de semilla `[evaluation] seed` y el día de la ronda (cada ronda sortea el suyo; el plan decía solo la semilla de `[evaluation]`); B1 y B2 sin restricción son la misma lista para todos; B3 son los productos propios por su puntaje y la reserva de B2, y su variante solo nuevos es B2 restringida a lo que el cliente nunca compró (la recompra propia deja solo la reserva, como dice `requirements.md`). Los modelos de B4-B6 usan la receta sellada con peso 0 y comparten el ajuste con el de la lista cuando son del mismo modelo y tamaño.

## D19 Criterios C01-C10, lo esperado y lo que se vio antes de fijarlos

- **Contexto**: los proyectos 01 a 07 fijaron sus criterios antes de construir y dijeron lo esperable; el 04 esperaba que el modelo no superara a las reglas y no las superó. Aquí, `p01` ya muestra que la lista pierde unos 2 puntos frente a la recompra propia y que solo la mezcla con la tendencia supera a lo más vendido en nuevos.
- **Opciones**: (a) solo superioridad frente a lo más vendido, como dice el sitio; (b) superioridad frente a lo más vendido, no inferioridad y superioridad frente a la recompra propia, el descubrimiento frente a lo más vendido, la cobertura y los tres del grupo de control, más la entrega al CRM.
- **Decisión**: (b), en `requirements.md` 8.1: C01 a C09 con umbral y C10 informativo. Esperado: C01, C05, C06, C07 y C09 se cumplen; C02 probablemente sí; **C03 probablemente no**; **C04 incierto**; C08 sí con una probabilidad cercana a 0,90. El margen de C02 (5 puntos) se fijó después de ver la validación (−1,99, de −3,01 a −0,88) y lo dice.
- **Motivo**: (a) se cumple casi seguro y no informa nada; (b) dice si el modelo agrega algo a lo que cualquiera puede hacer y si el control sirve.
- **Afecta**: `[criteria]`; `evaluation.py`, `reporting.py`; el README, la ficha, el tablero, el sitio.
- **Quién**: agente de planificación.
- **Estado**: vigente.
- **Nota (2026-11-19, U14)**: cada criterio prueba **una** cantidad, en su unidad, y la dice igual en todos lados (`Criterion.tested_value_es`, la columna «Lo que prueba el umbral» del resumen): C01-C04, el límite inferior del intervalo de la diferencia, en puntos; C05, la cobertura media; C06, la mayor diferencia estandarizada absoluta; C07, las dos tasas de rechazo de la prueba preregistrada; C08, los dos p de la prueba preregistrada; C09, las tres cuentas. El valor puntual de la misma cifra se muestra al lado (`point_value`) y nunca decide. Un empate no supera (C01-C04 piden mayor que), y un límite que se alcanza pasa donde el criterio dice «al menos» o «como máximo» (C05, C06, C07, C08). Un criterio que no se puede calcular queda `passed = false` con su motivo (C09 también cuando falta el archivo de correo de una ronda: un archivo que no está no es un archivo sin el control). Antes del cierre los diez criterios llevan `passed = null` y la frase «La prueba se evalúa con el cierre del <día>»: no se evaluó, que no es lo mismo que no se cumple. El sello guarda las cifras de las que se reconstruye cada criterio; `criteria_from_seal` las reconstruye y compara cada entrada a 6 decimales o se niega (`SealError`).

## D20 Intervalos: remuestreo por cliente, pareado, 2.000 remuestras; Wilson informativo

- **Contexto**: un cliente aparece en varias rondas (3.219 pares de 1.733 clientes en la validación, `p01`), así que los pares no son independientes.
- **Opciones**: (a) Wilson sobre los pares; (b) remuestreo de pares; (c) remuestreo de clientes con todos sus pares.
- **Decisión**: (c), 2.000 remuestras, semilla 0, percentiles 2,5 y 97,5; las diferencias pareadas usan los mismos clientes remuestreados; Wilson queda en C10.
- **Motivo**: (a) y (b) suponen pares independientes y dan intervalos más estrechos de lo que son.
- **Afecta**: `metrics.py`; C01-C04.
- **Quién**: agente de planificación.
- **Estado**: vigente.
- **Nota (2026-11-19, U10)**: las remuestras de clientes son el sorteo multinomial de `n` clientes con reposición (cuántas veces entra cada uno), y el estadístico de una remuestra es la suma de aciertos de los pares de los clientes sorteados sobre su número de pares; con 2.000 remuestras y unos 2.000 clientes la matriz de repeticiones ocupa unos 30 MB. La diferencia pareada resta los dos estadísticos con las mismas repeticiones. Los percentiles son los de `numpy.percentile` (interpolación lineal) y Wilson es la fórmula del puntaje de Wilson, acotada a [0, 1].
- **Nota (2026-11-19, U14)**: la cobertura de C05 es la de **todas** las listas emitidas de la ronda (las del grupo de oferta y las del control) sobre los productos con una línea de canasta en los 365 días anteriores, promediada sobre las rondas de la prueba; la de la elección en validación (`choose.py`) cuenta las listas de los pares evaluados, que son menos clientes: los dos números no son comparables. Los intervalos de C01-C04 remuestrean clientes (todos los pares de un cliente en todas las rondas se mueven juntos) con las mismas extracciones para las dos listas de una diferencia. La lista (`offer_list`) solo tiene su variante sin restricción (su «solo nuevos» es el descubrimiento, `chosen_discovery`); el resto de los métodos tiene las dos. La ronda censurada tiene sus filas por ronda y sus pares (informativos) y no entra en ningún total.

## D21 El sello: qué se congela antes de abrir la prueba

- **Contexto**: el sello de los proyectos 03 a 07 guarda la configuración del lanzamiento y el primer resultado de la prueba, y no se reescribe; el 07 agregó el orden de escritura y la adopción después de una falla (D62 del 07).
- **Opciones**: (a) sellar los factores del modelo; (b) sellar la receta, el control y las definiciones.
- **Decisión**: (b). La parte `launch`, escrita antes de cargar la primera semanal, guarda: la vista sellada de la configuración (`[catalogue]`, `[calendar]`, `[base]`, `[holdout]`, `[recommend]`, `[grid]`, `[evaluation]`, `[experiment]`, `[criteria]`, `[privacy]` y las huellas de la fuente); la huella de las líneas canónicas; la elección (cada candidata por ronda, con `fit_rounds`); la receta y los parámetros de B4-B6; la huella de la asignación del control, sus tamaños por estrato y su equilibrio; la huella de las listas de R2011-08-01; `validation_digest`. La parte `test` la escribe el cierre una vez.
- **Motivo**: congelar los factores no tiene sentido con un reajuste semanal (D11); lo que no puede cambiar después de ver la prueba es la receta, la mezcla, el control y cómo se mide.
- **Afecta**: `registry.py`, `launch.py`; AC16; runbook R7 y R11.
- **Quién**: agente de planificación.
- **Estado**: vigente.
- **Nota (2026-11-19, U11)**: el sello es `reports/model_seal.json`, `{"version": 1, "launch": {...}}`, y la parte del lanzamiento se crea con `files.write_exclusive` (se escribe y sincroniza un temporal y se le da su nombre con `os.link`, que falla si el nombre existe: dos escritores dejan un sello y un error) y no se reescribe nunca; un sello que no se puede leer es un `SealError` y no un sello ausente. Lleva la vista sellada (`config`), su huella, la elección con las cifras de cada candidata en cada ronda, la receta y los parámetros de B4-B6, el sorteo del control (huella, tamaños, equilibrio), la huella de las listas de R2011-08-01 y el `validation_digest`; no lleva ninguna hora (así se reproduce byte a byte salvo la clave de la corrida). El lanzamiento escribe los artefactos candidatos en `.candidates-<run_key>/`, después el sello y recién entonces guarda la base, mueve los artefactos y registra los modelos (una transacción, de modo que nunca hay una fila de `model_registry` sin su artefacto). Con un sello de la misma configuración y sin modelos registrados el lanzamiento adopta lo sellado (no elige otra vez, recalcula el sorteo y las listas y se niega con `SealMismatchError` si no son las selladas); con todo registrado no escribe nada y comprueba; con un sello de otra configuración todo es posterior al sello (M03) y no se toca el sello, y un almacén que ya tiene la ronda registrada se niega (R12). Cada ronda registra dos componentes (la popularidad de la ronda y el modelo de la receta): los modelos de B4-B6 no se registran, sus listas emitidas son su registro (desviación del plan, que habla de la huella de «los modelos de su ronda»).
- **Nota (2026-11-19, U14)**: la parte `test` del sello (`registry.write_test_seal`) tiene exactamente `config_sha256`, `run_key`, `as_of`, `criteria`, `metrics` y `operation`; se agrega al archivo con la parte del lanzamiento intacta (se relee y se compara) y nunca se reescribe. `check_test_evaluation` decide antes de leer nada: `first` (la evaluación que se sella), `repeat` (debe reproducir lo sellado a 6 decimales; la clave de la corrida y la hora no se comparan), `post_seal` (otra configuración después del sello: sus filas van aparte, `seal_state = post_seal`, y el sello no se toca) o `EvaluationRefusedError` (sin sello, o con otra configuración mientras el sello no tiene la prueba, nombrando las claves que difieren). La evaluación escribe las filas selladas de `003_eval.sql` (de solo inserción; los disparadores miran solo `sealed`) y después el sello; si el sello falla, la repetición recalcula, no repite filas y reproduce. Se agregaron `eval_segments` y `eval_mde` a las tablas del plan (los cortes por segmento y el menor efecto detectable tienen clave propia), y `eval_pairs` guarda también el segmento del par. `eval_pairs` tiene números de cliente: no sale de `data/`.

## D22 Operación simulada: el archivo repartido en un lanzamiento, 18 entregas semanales y un cierre

- **Contexto**: el archivo es histórico; los proyectos 04 a 07 simulan la operación repartiéndolo en entregas.
- **Opciones**: (a) evaluar todo de una vez sobre el archivo; (b) entregas que el flujo recibe una por una, como un sistema de origen.
- **Decisión**: (b): una línea va en la entrega de la fecha de su factura; cada entrega es un Parquet con manifiesto en `data/raw/deliveries/<id>/`. Una corrida sin pendientes es `no_delivery`.
- **Motivo**: prueba el flujo que el sitio promete (validar, cargar, armar, entregar cada semana) y hace natural que lo de la semana sea a la vez el resultado de la ronda anterior.
- **Afecta**: `deliveries.py`; RF05; AC05.
- **Quién**: agente de planificación.
- **Estado**: vigente.
- **Nota (2026-11-19, U12)**: la prueba en seco del plan (sección 14) se corrió con `research/p03_launch_dry_run.py` (salida en `research/p03.out`): el lanzamiento real sobre las 788.359 líneas anteriores al 2011-08-01, en un almacén y una carpeta temporales (nunca una línea de la prueba: el filtro de pyarrow y una parada si una fila lo pasa). Entrega, validación y carga: 8 s; leer las líneas del almacén, 2,4 s; la elección de las 48 candidatas en las 13 rondas de validación, 180 s (de 12,7 a 14,4 s por ronda); el ajuste de la primera ronda, 3,8 s; el lanzamiento entero, 183,5 s (RNF02: 20 minutos). Reprodujo las cifras de `p01`: 3.219 pares, y la receta elegida (`als_128_r0.1_w1`, B4-B6: `rules_5_w0`, `als_128_r0.1_w0` y `cosine_50_w0`) acierta 34,58 % en productos nuevos con cobertura 0,101. La ronda R2011-08-01 (base 4.326, 3.461 con oferta y 865 de control; 43.260 filas de listas y 692.160 de líneas base) tardó 22,9 s con la base (2,7 s), el reajuste de los cuatro modelos (14,7 s) y la escritura (5,4 s): por debajo de los 45 s que fija el plan. El almacén con las líneas del lanzamiento y esa ronda pesa 186 MB (cada ronda agrega unos 40 MB de líneas base: las 19 rondas, unos 0,8 GB, en `data/`, que no se versiona). Nadie pasó del límite: la unidad siguiente no es de velocidad. Medido con el contador de tiempo de pared de Python; la memoria se mide en U21 con su contador.

## D23 Sin fuga: el reloj es la ronda

- **Contexto**: research.md midió tres fugas (la división aleatoria, la popularidad sobre todo el archivo y las ventanas que se pisan) y mostró que los invitados mezclados como un cliente crean otra.
- **Opciones**: (a) que cada función filtre por fecha; (b) una sola función que corta (`history_before`) y que todo lo de una ronda reciba su resultado, con una guarda en ejecución y pruebas de truncamiento.
- **Decisión**: (b), con `LeakageError` (M01), la prueba de truncamiento de AC07 y AC13, la popularidad solo de la historia, los invitados solo en las reglas y la popularidad, una ventana por línea (AC18) y la validación antes del primer día de prueba (M04).
- **Motivo**: un filtro repetido en muchos lugares es el que alguien olvida; la prueba de truncamiento es la que atrapa lo que ninguna otra ve.
- **Afecta**: `base.py`, `recommend/*`, `choose.py`; plan, sección 10.
- **Quién**: agente de planificación.
- **Estado**: vigente.

## D24 Almacenamiento: SQLite para el flujo, otro SQLite para el CRM sustituto y Parquet para las líneas y las entregas

- **Contexto**: como el 07: el flujo relacional en SQLite, el sistema externo con su propia base.
- **Opciones**: (a) todo en una base; (b) el flujo y el CRM separados.
- **Decisión**: (b), con las reglas del runner del 07 y las tablas de solo inserción de la sección 5 del plan.
- **Motivo**: el CRM es otro sistema: si compartiera la base, una prueba no vería lo que se perdió en la entrega.
- **Afecta**: `warehouse.py`, `crm/standin.py`; sección 5 del plan.
- **Quién**: agente de planificación.
- **Estado**: vigente.

## D25 El CRM: un sustituto local con una API REST propia, idempotente por ronda y contacto, con lectura de vuelta

- **Contexto**: el sitio dice que las ofertas llegan «a la herramienta de correo o al CRM» con APIs REST. No hay un CRM del dueño; Mautic (GPL-3) y otros tienen APIs propias que el proyecto no verificó. El 07 usó la forma de ERPNext y una prueba de humo contra ERPNext real.
- **Opciones**: (a) la forma de un CRM concreto (Mautic, HubSpot) con una prueba de humo contra él; (b) una forma propia, simple, documentada, con el sustituto en FastAPI y SQLite.
- **Decisión**: (b) (sección 18 del plan): lotes de a lo sumo 500 contactos, `unchanged` para un lote igual, 409 `list_conflict` para otra lista, lectura de vuelta paginada, token del entorno. La prueba de humo contra un CRM real queda para el dueño.
- **Motivo**: sin un CRM elegido, copiar la forma de uno es una suposición; una forma propia hace probable la idempotencia, la lectura de vuelta y el conflicto, que es lo que importa de una entrega.
- **Afecta**: `crm/*`; RF15, RF23; AC19, AC20; C09; el sitio (fila 6).
- **Quién**: agente de planificación.
- **Estado**: pendiente del dueño (plan, sección 29, ítem 9).
- **Nota (2026-11-19, U13)**: el token va como `Authorization: Bearer <token>` (no `token <clave>:<secreto>` como el ERP del 07), se pide antes de mirar la ruta y se compara con `hmac.compare_digest`; todo error es una palabra fija (`unauthorized`, `not_found`, `bad_request`, `payload_too_large`, `list_conflict`, `internal_error`). Un 409 rechaza el lote entero sin aplicar nada de él, y el cliente cuenta todos los contactos del lote en `conflicts`. Una respuesta perdida (sin respuesta o un 5xx) se reenvía una vez con el mismo cuerpo (`sends` = 2) y el CRM contesta `unchanged`; un 4xx no se reenvía. `crm_deliveries` pasó a una fila por intento: `(round_id, batch, attempt)` con `status` (`ok` o `failed`) y `sends`, porque una tabla de solo inserción no puede reescribir el lote que falló cuando se reintenta; un lote está entregado cuando tiene una fila `ok` con `readback_equal = 1`, y repetir la tarea manda solo los que faltan. Una lectura de vuelta que no se pudo hacer no escribe filas `ok` (solo las de los lotes que fallaron al enviarse), así la siguiente corrida repite esos lotes. `deliver_round` no recibe la vista sellada (el plan la nombraba): `[crm]` no entra en la huella (D21), así que el tamaño del lote es un argumento. `repeat_round` manda otra vez los lotes de una ronda entregada y no escribe nada: es la prueba de la tercera cláusula de C09. `serve-crm` vive en `crm/serve.py` (`serve_crm(argv)`), que U19 enchufa en la línea de comandos; en Docker sirve la misma aplicación `crm.standin.create_app_from_environment` con uvicorn `--factory`.
- **Nota (2026-11-19, U14)**: C09 lee `evaluation.crm_evidence`: las listas emitidas para el grupo de oferta de las rondas entregadas contra los lotes entregados y leídos de vuelta iguales (`crm_deliveries`), los clientes del control que el CRM y los archivos de correo tienen, los archivos que están y lo que crea mandar otra vez los lotes de la última ronda entregada (`crm.client.repeat_round`, que no escribe nada en el almacén). La tarea `evaluate` recibe esa evidencia armada con el cliente de la configuración.

## D26 Orquestación: un DAG de Airflow en Docker que corre la misma tupla de tareas que la CLI, como los proyectos 01 a 07

- **Contexto**: el sitio nombra n8n; para el 07 el dueño eligió Airflow: «2 Airflow (como P1-P6)» (L94 del registro), y quien orquesta lo pide igual para el 08.
- **Opciones**: (a) n8n que llama a un servicio local; (b) Airflow en Docker con la misma tupla `TASKS` que la CLI.
- **Decisión**: (b): `personaloffers_weekly`, `0 6 * * 1`, una tarea por `TaskSpec`, `deliver` con `@task.short_circuit`, sin reintentos, con el servicio `crm` en el compose. Las filas del sitio cambian n8n por Airflow (sección 30 del plan, fila 6).
- **Motivo**: es la decisión del dueño para el 07, aplicada igual; una sola tupla de tareas hace que la CLI y Airflow no diverjan.
- **Afecta**: `pipeline.py`, `airflow/*`; RF24; AC35; el sitio.
- **Quién**: el dueño (L94, para el 07), aplicada por el agente de planificación.
- **Estado**: vigente.

## D27 Servicios: solo el CRM sustituto; sin API de entrada

- **Contexto**: el 07 tuvo una API de entrada (`POST /runs`) para corridas a pedido; su evaluación encontró un 503 después de una corrida confirmada (A4 del 07).
- **Opciones**: (a) una API de entrada como el 07; (b) el disparo manual de Airflow y la CLI como entrada.
- **Decisión**: (b). El único servicio es el CRM sustituto (`serve-crm` en Windows, uvicorn en Docker), en `127.0.0.1` o la red interna, con token.
- **Motivo**: nadie pide aquí una corrida a pedido desde otro programa; una API menos es una superficie menos.
- **Afecta**: `crm/standin.py`, `cli.py`; AC20.
- **Quién**: agente de planificación.
- **Estado**: vigente.

## D28 Estado, cierre y rechazos: el diseño del proyecto 07 con sus correcciones

- **Contexto**: el diseño del 07 (`data/interim/runs/<run_key>.json`, el cierre en orden, el manejador que no tapa el error, los rechazos antes de escribir) pasó su evaluación, con la corrección de la reconstrucción a medias (B3 del 07).
- **Opciones**: un solo camino razonable: copiarlo y adaptarlo.
- **Decisión**: el diseño de la sección 22 del plan, con los rechazos en su orden.
- **Motivo**: es código revisado y evaluado; reescribirlo abriría los defectos que ya se cerraron.
- **Afecta**: `pipeline.py`; AC29, AC30, AC34, AC36.
- **Quién**: agente de planificación.
- **Estado**: vigente.

## D29 Un solo escritor: el bloqueo del proyecto 07

- **Contexto**: los proyectos 05 a 07 comparten un bloqueo por carpeta de datos con sus correcciones (A6 del 06).
- **Opciones**: un solo camino razonable: copiarlo con `PERSONALOFFERS_*`.
- **Decisión**: `lock.py` del 07 tal cual.
- **Motivo**: dos corridas a la vez sobre las mismas tablas de solo inserción romperían la historia.
- **Afecta**: `lock.py`; AC31.
- **Quién**: agente de planificación.
- **Estado**: vigente.

## D30 Privacidad: ningún número de cliente en lo versionado ni en lo publicado; ninguna celda de menos de 10 clientes

- **Contexto**: los identificadores del archivo son números de cliente de una tienda real, aunque sin nombre; el 04 los dejó fuera de todo lo publicado y ocultó las celdas de menos de 10 clientes con una regla secundaria.
- **Opciones**: (a) publicar los números (son públicos en UCI); (b) dejarlos solo en `data/`, el CRM sustituto y `outputs/private/`, y publicar conteos con la regla del 04.
- **Decisión**: (b), con `[privacy] min_cell_customers = 10` y las listas de ejemplo del sitio sin cliente (sección 21 del plan).
- **Motivo**: una lista de productos por número de cliente es un perfil de compras; el portafolio no necesita publicarlo para mostrar el producto.
- **Afecta**: `export.py`, `site_export.py`, `email_export.py`; RNF12; AC26, AC28.
- **Quién**: agente de planificación.
- **Estado**: vigente.

## D31 El tiempo de la suite: 180 s de límite, 120 s de presupuesto, 80 s previstos y una unidad de velocidad a los 100 s

- **Contexto**: el 07 planificó 92 s y terminó en 125 s y 126 s, sobre el presupuesto (N5 del 07, una decisión del dueño); el 06 terminó en 133 s y el dueño subió el límite a 180 s (L79).
- **Opciones**: (a) el plan del 07; (b) menos segundos previstos y un disparador antes del presupuesto.
- **Decisión**: (b): 80 s previstos por unidad (sección 24.1 del plan), 40 s de margen y una unidad de velocidad en cuanto una medición pase de 100 s.
- **Motivo**: las unidades del final (CLI, modo rápido, documentación) siempre suman más de lo previsto; actuar a los 100 s deja lugar para ellas.
- **Afecta**: `tests/conftest.py`, `tests/unit/test_suite_budget.py`; RNF15; AC40.
- **Quién**: agente de planificación.
- **Estado**: pendiente del dueño (plan, sección 29, ítem 13).
- **Nota (2026-11-19, U13 y U14)**: la suite por defecto pasó de unos 37 s (U12) a 44,3 s con U13 (+7,3 s; previstos 5) y a 52,0 s con U14 (+7,7 s; previstos 5). Las dos unidades pasan 1,45 veces lo previsto: lo que suman son los accesorios de sesión nuevos (`delivered`, que entrega las cuatro rondas del repaso al CRM, y `evaluated`, que corre el cierre una vez) y los mundos que copia cada prueba que cambia algo; ninguna prueba sola pasa de 3,4 s. El disparador de 100 s no se alcanzó.

## D32 `pytest-xdist` no se fija

- **Contexto**: como los proyectos 03 a 07: los accesorios de sesión y el bloqueo con procesos aparte no se llevan bien con la ejecución en paralelo.
- **Opciones**: (a) fijarlo y repartir la suite; (b) no fijarlo.
- **Decisión**: (b).
- **Motivo**: el presupuesto se cumple sin él (D31); repartirlo cambiaría qué prueba qué.
- **Afecta**: `requirements-dev.txt`.
- **Quién**: agente de planificación.
- **Estado**: pendiente del dueño (plan, sección 29, ítem 16).

## D33 El texto del sitio: las tres correcciones de hechos que pide research.md y las filas del plan

- **Contexto**: research.md, pregunta 8: «Cliente, vacío en algunas filas» subestima el dato (una de cada cinco); «un minorista del Reino Unido» omite a los mayoristas; un efecto sintético al lado del grupo de control se lee como resultado.
- **Opciones**: (a) proponer solo esas tres; (b) proponer también las que salen del plan (Airflow, la lista, las líneas base, el tablero, los resultados).
- **Decisión**: (b): las 14 filas de la sección 30 del plan, que U22 escribe con las cifras reales en `SITE-UPDATES.md` y la evaluación confirma.
- **Motivo**: S9 pide que el sitio diga lo que el proyecto hizo y encontró; el texto final es del dueño.
- **Afecta**: `SITE-UPDATES.md`; la página `personal-offers` en marca-personal.
- **Quién**: agente de planificación.
- **Estado**: pendiente del dueño (plan, sección 29, ítem 8).

## D34 Tecnologías: las del landing, y las nuevas anotadas en `LANDING-EXPANSION.md`

- **Contexto**: S5 pide las tecnologías del landing y anotar las que no están. implicit y mlxtend están en la página del proyecto pero no en el landing; openpyxl lee el libro.
- **Opciones**: un solo camino razonable: usarlas y anotarlas.
- **Decisión**: implicit, mlxtend, openpyxl y SciPy (si no está ya) van a `LANDING-EXPANSION.md` con el 08 en U22; las que ya están (NumPy, SQLite, pyarrow, matplotlib, pytest, FastAPI, uvicorn, httpx) no se repiten.
- **Motivo**: S5.
- **Afecta**: `LANDING-EXPANSION.md`; `tests/unit/test_dependencies.py`.
- **Quién**: agente de planificación.
- **Estado**: pendiente del dueño (plan, sección 29, ítem 14).

## D35 Versiones fijadas con `==`, con al menos dos semanas, para Python 3.11

- **Contexto**: `requirements-research.txt` fija pandas 3.1.0, numpy 2.4.6, pyarrow 26.0.0, openpyxl 3.1.5, mlxtend 0.25.0, implicit 0.7.3, scipy 1.17.1, scikit-learn 1.9.0 y matplotlib 3.11.1; numpy 2.5 y scipy 1.18 exigen Python 3.12.
- **Opciones**: un solo camino razonable: las mismas versiones, más FastAPI, uvicorn, httpx y pytest con la misma regla de antigüedad.
- **Decisión**: U01 fija esas versiones y las de los servicios (las del 07 si cumplen la regla) **[Verificar en U01 en PyPI la fecha de cada una]**; `pip check` por su código de salida.
- **Motivo**: RNF01; la imagen de Airflow y el `.venv` deben coincidir.
- **Afecta**: `requirements*.txt`; AC38.
- **Quién**: agente de planificación.
- **Estado**: vigente.
- **Nota (2026-11-19, U01)**: `requirements.txt` y `requirements-dev.txt` fijan las versiones de la investigación y las de los proyectos 05 y 07 para los servicios. Seis versiones transitivas de la investigación tenían menos de 14 días y bajaron a la más nueva que cumple la regla: cloudpickle 3.1.3 a 3.1.2, narwhals 2.29.0 a 2.28.0, pydantic 2.14.4 a 2.14.2 (con pydantic-core 2.50.5 a 2.50.2), click 8.5.1 a 8.5.0, annotated-doc 0.0.7 a 0.0.5 y python-dateutil 4.0.0 a 2.9.0.post0 (con six). threadpoolctl 3.8.0 se subió el 2026-11-05, justo 14 días antes. `pydantic` queda transitivo hasta que U13 lo importe.

## D36 Idioma: documentación en español neutro; código, tablas y columnas en inglés; textos visibles en español

- **Contexto**: la suposición del registro para todos los proyectos.
- **Opciones**: un solo camino razonable.
- **Decisión**: como el 07.
- **Motivo**: la regla del portafolio.
- **Afecta**: todo; RNF13.
- **Quién**: agente de planificación.
- **Estado**: vigente.

## D37 El tablero: el modelo estrella en Parquet y el diseño en HTML; el `.pbix` a mano

- **Contexto**: S4: Power BI necesita la interfaz gráfica; los proyectos 01 a 07 entregan las tablas y un HTML con el diseño.
- **Opciones**: un solo camino razonable.
- **Decisión**: las tablas de la sección 19 del plan y las cinco páginas de la sección 20, con la leyenda «Sin ofertas reales: el archivo no permite medir el efecto de una oferta».
- **Motivo**: S4.
- **Afecta**: `export.py`, `dashboard/*`; AC26, AC27; el sitio (fila 11).
- **Quién**: agente de planificación.
- **Estado**: pendiente del dueño (el `.pbix`; plan, sección 29, ítem 12).

## D38 Exportación para el sitio: seis JSON y un manifiesto

- **Contexto**: la página del 01 (S10) tiene Resumen, Datasets, Algoritmos y Producto final; el 08 agrega el grupo de control como parte del producto.
- **Opciones**: (a) los cinco archivos del 07; (b) seis, con `control.json` aparte.
- **Decisión**: (b) (sección 21 del plan): `summary`, `data`, `algorithms`, `operation`, `control` y `validation_rules`, ≤ 200 KB, sin números de cliente ni campos de efecto.
- **Motivo**: el control es lo que el sitio puede afirmar en lugar de un efecto (D16); merece su archivo.
- **Afecta**: `site_export.py`; AC28; la página del sitio.
- **Quién**: agente de planificación.
- **Estado**: vigente.

## D39 Distinto de los proyectos 02 y 04: el producto, no la baja ni el segmento

- **Contexto**: research.md: el 04 predice si un cliente vuelve (34,4 % de bajas, reproducido); el 02 estima cuánto compra y en qué grupo está. Los tres usan el mismo archivo.
- **Opciones**: un solo camino razonable: lo que research.md propone.
- **Decisión**: el 08 ordena productos para cada cliente y se evalúa con métricas de orden, líneas base y rondas semanales; no usa la etiqueta de baja, ni BG/NBD, ni Gamma-Gamma, ni los segmentos del 02 como variable (la marca mayorista es solo un estrato, D07); comparte con el 04 las fechas del lanzamiento y del cierre. Lo nuevo es el catálogo, las reglas de canasta con las facturas de invitados, la lista por cliente, el grupo de control y la entrega al CRM.
- **Motivo**: tres proyectos sobre el mismo archivo solo valen si cada uno responde otra pregunta.
- **Afecta**: todo; el README «En qué consiste».
- **Quién**: agente de planificación.
- **Estado**: vigente.

## D40 El paquete se llama `personaloffers`; el alcance de los commits es `personal-offers`

- **Contexto**: el identificador de la página es `personal-offers`; los paquetes de los proyectos anteriores son una palabra (`churnrisk`, `invoiceflow`).
- **Opciones**: un solo camino razonable.
- **Decisión**: paquete `personaloffers`, entorno `PERSONALOFFERS_*`, DAG `personaloffers_weekly`, compose `personaloffers-airflow`, alcance `personal-offers`; los documentos de planificación con `docs(p08): …`.
- **Motivo**: la regla de los proyectos anteriores.
- **Afecta**: todo.
- **Quién**: agente de planificación.
- **Estado**: vigente.

## D41 Los hechos del planificador: `p01` y `p02`, sin abrir la ventana de prueba

- **Contexto**: el planificador necesitaba saber, antes de fijar los criterios, cómo se comportan los métodos con rondas semanales y cómo se comporta el sorteo estratificado, sin mirar la prueba.
- **Opciones**: (a) fijar los criterios con las cifras de 90 días de la investigación; (b) medir con rondas semanales y un período previo que terminan antes del 2011-08-01.
- **Decisión**: (b). `p01`: las 13 rondas de validación (R2011-05-02 a R2011-07-25) con todos los métodos, la lista y las mezclas; `p02`: un lanzamiento simulado el 2011-04-04 con 17 semanas de resultado (hasta el 2011-07-31). Los dos leen el Parquet de la investigación con un filtro de pyarrow `InvoiceDate < 2011-08-01` y se detienen si una fila lo pasa; la última línea leída es del 2011-07-31 16:04. Sus salidas se versionan sin rutas del equipo (`p01` silencia un aviso de implicit que imprimía la ruta de la biblioteca).
- **Motivo**: con 90 días, la investigación vio que reglas y ALS le ganan a la popularidad en nuevos; con 7 días es al revés, y C04 se habría fijado esperando lo contrario de lo que pasa.
- **Afecta**: `requirements.md` sección 4 y 8.1; D10, D12, D14, D15, D18, D19.
- **Quién**: agente de planificación.
- **Estado**: vigente.

## D42 La ronda censurada: R2011-12-05 se arma y se entrega, y su seguimiento de 5 días es informativo

- **Contexto**: el archivo termina el 2011-12-09 a las 12:50; la ronda del 2011-12-05 solo tiene 5 días de compras.
- **Opciones**: (a) no armarla; (b) armarla, entregarla y seguirla, fuera de los criterios.
- **Decisión**: (b), con `period = "censored"` y `days_observed = 5`, en C10.
- **Motivo**: la operación del lunes 5 de diciembre ocurre igual; medirla con 5 días y mezclarla con las de 7 cambiaría la métrica.
- **Afecta**: `calendar.py`, `evaluation.py`; `dim_round`.
- **Quién**: agente de planificación.
- **Estado**: vigente.

## D43 Las 173 líneas de descuento `D` no son ofertas al azar

- **Contexto**: research.md, contradicción 2: el archivo tiene 173 líneas con el código `D` y 252 descripciones con descuento, oferta o vale, pero ninguna oferta aleatoria ni campo de campaña.
- **Opciones**: (a) usarlas como un experimento natural; (b) contarlas y decir que no son ofertas al azar.
- **Decisión**: (b): rol `non_product`; se cuentan en `data.json` y la página las nombra al lado de «0 ofertas al azar».
- **Motivo**: un descuento no asignado al azar no permite medir un efecto; usarlo así sería la confusión que D16 evita.
- **Afecta**: `lines.py`; `data.json`; el sitio (fila 4).
- **Quién**: agente de planificación.
- **Estado**: vigente.

## D44 El libro sintético de las pruebas

- **Contexto**: la suite no puede leer el libro real (46 MB, decenas de segundos) ni depender de él; el 04 usó un zip sintético con la forma del real.
- **Opciones**: un solo camino razonable: generar un libro con las dos hojas reales, las 8 columnas y cada rol, con clientes y productos ficticios.
- **Decisión**: `tests/fixtures/make_workbook.py` (sección 24 del plan), también expuesto como `make-fixture` para el modo rápido; los códigos ficticios en `90000`-`99999` y las descripciones «PRODUCTO SINTÉTICO n» **[Verificar en U03 que ningún código real del archivo cae en ese rango; si cae, usar otro]**.
- **Motivo**: prueba el lector, los roles y el flujo entero en segundos y sin datos reales.
- **Afecta**: `tests/fixtures/*`, `cli.py`; AC02, AC33.
- **Quién**: agente de planificación.
- **Estado**: vigente.
- **Nota (2026-11-19, U03)**: la verificación que pedía esta decisión dio que cuatro códigos reales del archivo caen en 90000-99999 (90050, 90075, 90100 y 90150; el archivo llega hasta 90214 antes del 2011-08-01). Los productos ficticios son los 400 códigos `95000 + 12 n` (95000 a 99788); los clientes ficticios siguen siendo 90001 a 90300. Una prueba `real_data` lo comprueba contra los prefijos de cinco dígitos del archivo, con el filtro del planificador (nada desde el 2011-08-01).

## D45 El CSV para la herramienta de correo, fuera de lo versionado

- **Contexto**: el sitio dice «a la herramienta de correo o al CRM»; muchas herramientas de correo cargan una lista por archivo.
- **Opciones**: (a) solo el CRM; (b) el CRM y un CSV por ronda.
- **Decisión**: (b): `outputs/private/email/<round_id>.csv` con contacto, rango, código, descripción y origen, solo de quienes reciben oferta.
- **Motivo**: cubre las dos salidas que promete el sitio sin suponer una API de correo; tiene números de cliente, así que no se versiona (D30).
- **Afecta**: `email_export.py`; RF16; AC10.
- **Quién**: agente de planificación.
- **Estado**: vigente.
- **Nota (2026-11-19, U13)**: el archivo se escribe entero con `write_atomic`, en UTF-8 sin marca de orden de bytes y con `
`, y pide `holdout.check_deliverable` (M05) y `holdout.check_round_groups` antes de armar un solo byte. Una descripción que una planilla correría como fórmula (empieza con `=`, `+`, `-` o `@`) lleva un `'` delante, y un carácter de control dentro de una descripción se vuelve un espacio (un retorno de carro suelto parte la fila para algunos lectores y el escritor de CSV de Python no lo entrecomilla). Cada lista debe tener los `k` productos del plan o no se escribe nada.
