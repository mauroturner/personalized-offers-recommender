# Advertencias de las revisiones nativas

Cada hallazgo de las revisiones nativas de Gentle AI que el registro del documento de seguimiento anota para el proyecto 08 (L122, L124, L126, L128, L130 y L134, la revisión de U21): 26 en total, entre advertencias y sugerencias, con su ubicación y su estado. L124 y L132 no anotan ningún hallazgo. Los números y los estados de este archivo son los que cuentan el README, la ficha del modelo y el paso a paso, y `tests/docs/test_docs.py` los compara.

Los hallazgos se numeran dentro de cada tramo (`W` una advertencia, `S` una sugerencia). Las ubicaciones son las que el registro da; los tramos de L126 no dicen de qué unidad sale cada hallazgo y van juntos. Un bullet del registro que reúne varios hallazgos se cuenta uno por uno (por ejemplo, las cuatro sugerencias de `u15b`). Los estados son cuatro: **corregida** (con su commit), **refutada** o **dejada con evidencia** (con el motivo) y **abierta**.

**Estado.** De los 26: 21 **corregidas** (`165f9e1`, `d60db87`, `49e7cce`, `2e74cd4`, `7cb1511`, `55bee6a`, `eae715f`, `8fa0130` y, con las correcciones de la evaluación, `a7a265a`), 2 **dejadas con evidencia**, ninguna **refutada** y 3 **abiertas**, las tres que L131 dejó fuera o que ningún commit toca. La advertencia de U21 sobre las listas de ejemplo de `algorithms.json` se corrigió con D46 (B1 de la evaluación independiente). Las abiertas no cambian ningún veredicto ni lo sellado. Los estados se leyeron de los commits y del registro (L125, L127, L129, L131, L133, L134 y L136); la evaluación independiente los confirma (su A6 y su A7). Las nueve advertencias de la evaluación independiente, que no son de una revisión nativa, están al final, con su estado, y después lo que encontraron las revisiones de las correcciones y la comprobación (L138 y L139), también aparte.

**Lo que no se revisó.** La revisión nativa anota como no revisados, por debajo del presupuesto (`under_budget`, de nivel medio) o por encima de él, estos tramos. Lo que ninguna revisión vio lo sondea la evaluación independiente (plan, sección 28).

| Tramo | Commits | Líneas | Motivo | Registro |
| --- | --- | --- | --- | --- |
| u02 | `92ae779..dbb2bc5` | 1.435 | `under_budget`: queda pendiente en el tramo abierto | L122 |
| u03 | `dbb2bc5..1e646b8` | 1.578 | `under_budget` | L122 |
| u05 | `6b98b3b` | 1.326 | `under_budget` | L124 |
| u07 | `140693a` | 511 | `under_budget` | L124 |
| f1 | `103b7aa..165f9e1` | 103 | `under_budget` (las correcciones de L122) | L126 |
| f2 | `d60db87` | 150 | `under_budget` (las correcciones de L126) | L130 |
| u19 | `59c9a68` | 1.002 | `under_budget` | L130 |
| s3 | `2e74cd4..55bee6a` | no consta | `under_budget` (pruebas y un comentario) | L132 |
| e9ca105 | `e9ca105` | 9.979 | generado y por encima del presupuesto | L133 y L134 |

L124 anota que cada unidad se había evaluado contra su propio padre, así que las de nivel medio que quedaron `under_budget` (U02, U03, U05 y U07) nunca se juntaron en un tramo que llegara al presupuesto; desde U09 el tramo abierto se evalúa antes de cada commit de riesgo alto. Ni L118 ni L120 anotan una revisión nativa de la investigación ni del plan.

Revisadas y aprobadas, con su linaje quemado (el riesgo es el ítem del plan que la revisión escaló): `u01` (ítem 5), `u04` (ítem 2), `u06` y `u08` (ítem 1, sin hallazgos), `u09a` y `u09b` (ítem 6), `u10` (ítem 6, sin hallazgos), `u11a`, `u11b` y `u12` (ítem 1), `u13a` (ítem 2), `u13b` (ítem 3, sin hallazgos), `u14a` y `u14b` (ítem 1), `u15a` (ítem 3), `u15b` (ítem 6), `u16` (ítem 3), `u17` (ítem 3), `u18a` y `u18b` (ítem 4, sin hallazgos), `u20` (ítem 5, sin hallazgos), `s1` (ítem 6, sin hallazgos), `s2` (ítem 1, sin hallazgos) y `u21` (`7238720..f8f80b5`, ítem 2).

## u01 (L122)

Tramo `0677f5b..92ae779` (835 líneas, ítem 5): aprobada con una sugerencia.

- **S1**
  - Hallazgo: Sugerencia: `tests/unit/test_dependencies.py` y otras pruebas por defecto leen archivos fuera del tramo (`LANDING-EXPANSION.md`, `requirements-research.txt`, `research/`), así que un archivo que falta falla en la corrida y no nombra la regla.
  - Ubicación: `tests/unit/test_dependencies.py:215-221`.
  - Estado: **corregida**. `165f9e1`: las pruebas de dependencias que leen archivos de afuera nombran el archivo y la regla cuando falta.

## u04 (L122)

Tramo `1e646b8..555bfec` (1.477 líneas, ítem 2): aprobada con una sugerencia.

- **S1**
  - Hallazgo: Sugerencia: la guarda de DTD y entidades del libro mira solo los primeros 4.096 bytes de cada parte XML, y un comentario o espacios pueden empujar un `<!DOCTYPE` fuera de la ventana.
  - Ubicación: `src/personaloffers/workbook.py:44`.
  - Estado: **corregida**. `165f9e1`: la guarda lee cada parte XML entera, en bloques de 64 KiB que se solapan 4.096 bytes.

## l126 (L126)

Tramos de `103b7aa` a `ef50221`: las correcciones de L122 (`f1`) y U09 a U12, aprobadas con una advertencia y seis sugerencias.

- **W1** (`u12`)
  - Hallazgo: Advertencia: `emit_round` escribe los artefactos de los modelos de la ronda antes de la transacción que inserta las listas y registra los modelos; una interrupción entre las dos deja la carpeta del componente sin nada en la base y `write_component` se niega a sobrescribirla, así que la ronda no se puede emitir de nuevo hasta quitar la carpeta a mano.
  - Ubicación: `src/personaloffers/weekly.py:195-211`.
  - Estado: **corregida**. `d60db87`: la advertencia no se reprodujo como estaba escrita (L129): una ronda interrumpida que se repite adopta las carpetas que quedaron, porque el reajuste es determinista; solo se trababa con una carpeta sin registrar con otro contenido o con un archivo suelto. `emit_round` ahora quita las carpetas de componentes sin registrar antes de escribir y nunca toca una registrada, con una prueba en rojo sobre los dos casos.

- **S1**
  - Hallazgo: Sugerencia: `not self.weight >= 0` es una guarda contra NaN y no tiene comentario.
  - Ubicación: `src/personaloffers/recommend/blend.py:33`.
  - Estado: **corregida**. `d60db87`: un comentario explica que la forma negada es la única que rechaza un peso que no es un número.

- **S2**
  - Hallazgo: Sugerencia: `check_no_leak` corre dos veces por `prepare`.
  - Ubicación: `src/personaloffers/recommend/context.py:56`.
  - Estado: **corregida**. `d60db87`: el corte de la historia se comprueba una vez, con su prueba.

- **S3**
  - Hallazgo: Sugerencia: el tope `RANK_LIMIT` y la guarda de puntajes NaN de las llaves del orden no tienen prueba.
  - Ubicación: `src/personaloffers/offers.py:33-36`.
  - Estado: **corregida**. `d60db87`: pruebas de que 65.535 productos caben, 65.536 no, y de que un puntaje que no es un número no se ordena.

- **S4**
  - Hallazgo: Sugerencia: `discovery_slots` no se lee nunca: la lista concuerda con lo que dice solo si `repeat_slots + discovery_slots == k`.
  - Ubicación: `src/personaloffers/offers.py:64`.
  - Estado: **corregida**. `d60db87`: `build_list` rechaza una vista cuyos lugares no suman `k`, con su prueba.

- **S5**
  - Hallazgo: Sugerencia: el mensaje de falla de una prueba nombra `SOURCE` y `NAME`, que no están definidos.
  - Ubicación: `tests/unit/test_offers.py:220`.
  - Estado: **corregida**. `d60db87`: el mensaje nombra solo lo definido.

- **S6**
  - Hallazgo: Sugerencia: el rechazo a reemplazar un artefacto instalado con otro hash no tiene prueba.
  - Ubicación: `src/personaloffers/launch.py:82-89`.
  - Estado: **corregida**. `d60db87`: una prueba planta una carpeta con otro contenido y comprueba que el lanzamiento se niega, deja el registro vacío, conserva el sello y guarda los candidatos.

## u14a (L128)

Tramo de `f8e3850` (ítem 1): aprobada con dos advertencias y una sugerencia.

- **W1**
  - Hallazgo: Advertencia: dos copias de la regla de seis decimales `_rounded` deciden «sin cambios» y la reconstrucción desde el sello.
  - Ubicación: `src/personaloffers/registry.py:164-172` y `src/personaloffers/evaluation.py`.
  - Estado: **corregida**. `49e7cce`: una sola regla, `registry.rounded`, que usa también la evaluación.

- **W2**
  - Hallazgo: Advertencia: `criteria_from_seal` y sus tres ramas de `SealError` no tienen prueba.
  - Ubicación: `src/personaloffers/evaluation.py:448-454`.
  - Estado: **corregida**. `49e7cce`: pruebas de la reconstrucción de los criterios desde el sello, con la parte del lanzamiento, un criterio de más y el borde de los seis decimales.

- **S1**
  - Hallazgo: Sugerencia: `evaluate_rankings`, `evaluate_experiment`, `run_experiment` y `crm_evidence` no tenían prueba de sus salidas ni de sus caminos de error en ese tramo.
  - Ubicación: `src/personaloffers/evaluation.py` (según el registro).
  - Estado: **corregida**. `55bee6a`: pruebas de los caminos de error de la evaluación y del experimento puro.

## u14b (L128)

Tramo de `bc1932b` (ítem 1): aprobada con una advertencia.

- **W1**
  - Hallazgo: Advertencia: en `_choice_rows` el acumulador `total` no se lee nunca; la fila «todas» usa los `pairs` y `hits` sellados sin comprobar que las sumas por ronda concuerdan.
  - Ubicación: `src/personaloffers/reporting.py:49-54`.
  - Estado: **corregida**. `2e74cd4`: un sello cuyas rondas no suman los `pairs` y `hits` que sella para una candidata se rechaza antes de escribir nada, con su prueba.

## u13a (L128)

Tramo de `24c965a` (ítem 2): aprobada con una sugerencia.

- **S1**
  - Hallazgo: Sugerencia: `synchronous=NORMAL` con un diario de reversa puede corromper el CRM sustituto en un corte de luz (mitigado por la repetición).
  - Ubicación: `src/personaloffers/crm/standin.py:73`.
  - Estado: **dejada con evidencia**. El sustituto se regenera con la repetición y es atómico con el diario de reversa; el código lo dice en el mismo lugar («a stand-in is regenerated by the replay»). El almacén del flujo, que no se regenera, usa `synchronous=FULL`.

## u15a (L128)

Tramo de `a3e995f` (ítem 3): aprobada con una advertencia y dos sugerencias.

- **W1**
  - Hallazgo: Advertencia: el accesorio `exported` y `export_world` no eran consumidos por ninguna prueba en ese commit, así que el camino de exportación (marts, supresión, manifiesto, `verify_star_schema` y los 27 controles del modelo) no se corrió ahí. El commit siguiente agrega las pruebas de contrato; falta ver si pasan por ese camino.
  - Ubicación: `tests/fixtures/stars.py:22-29`.
  - Estado: **corregida**. `7cb1511`: las pruebas de contrato de `tests/contract/test_star_schema.py` consumen `exported`, es decir, el camino de exportación completo.

- **S1**
  - Hallazgo: Sugerencia: el nombre `names` se reutiliza en `export._serialize`.
  - Ubicación: `src/personaloffers/export.py` (`_serialize`).
  - Estado: **corregida**. `eae715f`: `names` pasa a `selected`.

- **S2**
  - Hallazgo: Sugerencia: una sola celda chica en una (ronda, grupo) falla a salvo por `chk_K04` pero no tiene prueba.
  - Ubicación: `sql/checks/model/` (`chk_K04`, según el registro).
  - Estado: **corregida**. `eae715f`: una prueba muestra que una celda chica oculta una segunda, y que sin esa regla `chk_K04` rechaza la exportación.

## u15b (L128)

Tramo de `7cb1511` (ítem 6): aprobada con cuatro sugerencias.

- **S1**
  - Hallazgo: Sugerencia: aserciones encadenadas con `and` en las pruebas del modelo estrella.
  - Ubicación: `tests/contract/test_star_schema.py` (según el registro).
  - Estado: **corregida**. `eae715f`: unas 50 aserciones encadenadas se separan.

- **S2**
  - Hallazgo: Sugerencia: fichas de requerimientos sin explicar en los textos de documentación de las pruebas.
  - Ubicación: docstrings de `tests/` (según el registro).
  - Estado: **abierta**. Ni L129 ni L131 ni ningún commit la tocan; es de legibilidad y no cambia ninguna salida. La evaluación independiente decide si se corrige.

- **S3**
  - Hallazgo: Sugerencia: el rango de clientes sintéticos de las pruebas está escrito de tres formas.
  - Ubicación: `tests/` (según el registro).
  - Estado: **corregida**. `8fa0130`: un solo rango, 90001-90300, y un solo patrón de ruta local, en `tests/fixtures/published.py`.

- **S4**
  - Hallazgo: Sugerencia: la comprobación del orden del manifiesto usa la hora de modificación con 1 ms de holgura.
  - Ubicación: `tests/` (según el registro).
  - Estado: **abierta**. L131 la dejó fuera de la unidad de velocidad y no hay un commit que la cambie.

## u16 (L128)

Tramo de `fe53f04` (ítem 3): aprobada con dos sugerencias.

- **S1**
  - Hallazgo: Sugerencia: `_fmt`, `_int` y `_pct` devuelven «oculta» para cualquier NaN.
  - Ubicación: `src/personaloffers/dashboard/render.py`.
  - Estado: **dejada con evidencia**. Es a propósito: una cifra que falta se muestra oculta antes que como un número inventado; `4362c0d` lo dice en un comentario de `render.py`.

- **S2**
  - Hallazgo: Sugerencia: `svg.py` tiene ayudas y ramas de `line_chart` que el diseño no usa y ninguna prueba ejercita.
  - Ubicación: `src/personaloffers/dashboard/svg.py`.
  - Estado: **abierta**. L131 la dejó fuera de la unidad previa al sello; no cambia ningún byte publicado.

## u17 (L130)

Tramo de `4242f81` (ítem 3): aprobada con dos sugerencias.

- **S1**
  - Hallazgo: Sugerencia: la prueba vuelve a declarar `ENVELOPE` en lugar de importar `site_export.ENVELOPE`.
  - Ubicación: `tests/contract/test_site_export.py:24`.
  - Estado: **corregida**. `8fa0130`: el sobre de la prueba se fija contra el de la exportación.

- **S2**
  - Hallazgo: Sugerencia: la prueba copia la expresión `LOCAL_PATH` de `test_site_export.py:33`.
  - Ubicación: `tests/integration/test_published_bytes.py:124`.
  - Estado: **corregida**. `8fa0130`: el patrón de ruta local se escribe una sola vez, en `tests/fixtures/published.py`.

## u21 (L134)

Tramo `7238720..f8f80b5` (el commit escrito a mano de la corrida real, escalado al ítem 2): aprobado, con el linaje `review-2ad564b917565a2c` reconocido y su autoridad quemada, con una advertencia. El commit generado `e9ca105` (9.979 líneas) está por encima del presupuesto y no se revisó.

- **W1**
  - Hallazgo: Advertencia: la nota de D30 documenta que las tres listas de ejemplo de `algorithms.json` salen de listas de ofertas de clientes reales y acotan la reidentificación a un puñado de clientes. Cada lista completa de 10 es única de un cliente en su ronda y solo 5, 5 y 6 clientes habían comprado antes de la ventana los siete productos de recompra de cada una, menos que el mínimo de 10 clientes de D30. La prueba de privacidad no lo marca porque ninguna lista lleva un número de cliente. El revisor lo considera previo: el código que produce `algorithms.json` no cambió en U21.
  - Ubicación: `docs/decisions.md:351` (la nota de D30 de U21) y `outputs/site/algorithms.json` (`example_lists`).
  - Estado: **corregida**. `a7a265a`: cada lista de ejemplo es el agregado de su perfil, rotulado, con cuántos clientes tienen cada producto (10 o más) y sin rangos, y una prueba con los datos reales cuenta dentro del perfil quién tiene cada producto y quién la lista entera (D46; B1 de la evaluación, que dentro del perfil publicado contó 5, 1 y 2 clientes). El otro hallazgo de L133, C05, no es de una revisión nativa: su denominador sellado cuenta las líneas de canasta y no las de compra, y la distancia con el 0,158 de la validación del plan es sobre todo el numerador; se publica como análisis posterior al sello (D49).

## Las advertencias de la evaluación independiente (L136)

No son de una revisión nativa, y por eso van en una tabla aparte y no se cuentan entre los 26 de arriba. Los bloqueantes B1 a B6 de la misma evaluación están en `docs/evaluation.md`, con su corrección.

| Advertencia | Qué es | Estado | Motivo o commit |
| --- | --- | --- | --- |
| A1 | La cobertura no se calcula como una intersección: de 12 a 41 productos por ronda de las listas no están en el denominador (la cuenta crece con las rondas: 12, 16, 16, 19, 21, 20, 21, 24, 26, 30, 31, 28, 32, 34, 35, 37, 41 y 39), y la de B0 da 1,20 | Dejada, documentada | Calcularla como intersección cambiaría la cifra sellada de C05 y de cada método (`coverage` de `eval_methods`), que el sello y el almacén guardan; no es barato ni deja intacto lo sellado. Un análisis posterior al sello, como el de C05, sí es posible y no se hizo: la cobertura no es una intersección y sigue sellada así. La nota está en D49 (comprobación, N1) |
| A2 | El CRM sustituto aceptaba una lista de 9 productos (200, `created`) | Corregida (la comprobación confirmó el servido y dejó el de en proceso, que se cerró después) | `4d18d86`: el sustituto que sirven `serve-crm` y el compose rechaza con 400 una lista que no tiene `[recommend] k` productos, para todo su lote. `20e0167`: el sustituto en proceso (`mode = standin`, el de siempre) también, porque `make_client` recibe el largo y la tubería le pasa `[recommend] k`; las 82.343 listas reales tienen 10, así que ninguna cifra sellada cambia |
| A3 | El p del A/A sellado (2.000 permutaciones) está a unos 2 errores de Monte Carlo del de 20.000 (0,294 contra 0,315) | Dejada | Es ruido de Monte Carlo y la conclusión de C08 es la misma; más permutaciones cambiarían lo sellado |
| A4 | La semanal crece unos 0,65 s por ronda (de 37 a 48 s) y el pico de memoria, de 1.728 a 2.057 MB de `PeakWorkingSetSize` | Dejada | Sin efecto dentro de las 18 rondas del alcance; los límites de RNF02 y RNF03 se cumplen con margen |
| A5 | Empates de la reserva en `rules_10_w0` y `rules_20_w0`: los aciertos son iguales y difieren en 1 o 2 los productos distintos de tres rondas | Dejada | La elección no cambia (la regla de D12 no elige ninguna de las dos) y cambiar el desempate cambiaría lo sellado de la validación |
| A6 | Las tres sugerencias abiertas de las revisiones nativas (`u15b` S2 y S4, `u16` S2) siguen abiertas | Abiertas, arriba | Sin efecto en ninguna salida; su estado es el de su bloque |
| A7 | Las dos dejadas con evidencia se confirman | Confirmadas | R11 regenera el CRM idéntico y las 9 «ocultas» del diseño son celdas ocultas |
| A8 | Una carpeta que no es componente de la receta (`als/` en una ronda de coseno) quedaba en `models` | Corregida | `4d18d86`: al emitir una ronda se borra una carpeta sin registrar con el nombre de un componente que la receta no usa, y cualquier otra cosa que no es un componente se anota en el registro y se deja |
| A9 | La CLI imprime el aviso de deprecación de Starlette sobre httpx | Dejada | Es del paquete de terceros, no del proyecto, y las versiones están fijadas (D35) |

## Lo que encontraron las revisiones de las correcciones y la comprobación (L138 y L139)

Tampoco cuentan entre los 26 de arriba: los cuatro primeros son de las revisiones nativas de las correcciones (L138) y los cinco últimos, de la comprobación (L139). Ninguno cambia un veredicto ni una cifra sellada.

| Hallazgo | Qué es | Estado | Motivo o commit |
| --- | --- | --- | --- |
| `c6`, advertencia, `reporting.py:151-152` | Cuando la cobertura sellada recalculada no coincide con el `coverage_list` del sello a seis decimales, no se escribe nada y sale `SealError`: un camino de falla nuevo del cierre que ninguna prueba recorría | Corregida | `c0a382c`: una prueba cambia el `coverage_list` de una copia del sello y comprueba el `SealError`, que no se escribe el análisis y que el sello no cambia; quitar la guarda la hace fallar |
| `c2`, sugerencia, `pipeline.py:30-31` | El flujo reemplaza cualquier cantidad de hilos que fije quien lo corre | Dejada, por diseño | D47: es lo que hace que las listas den los mismos bytes en cualquier máquina (RNF01) |
| `c5`, sugerencia, `tests/e2e/test_real.py:357-359` | La prueba tomaba por un estrato cualquier par oferta y control igual al de uno, así que un agregado que coincidiera la haría fallar sin motivo | Corregida | `c0a382c`: la prueba busca los estratos por campo o por llave (un campo que nombra los estratos, un miembro con el número de un estrato y su tamaño, o un contenedor con el par de todos los estratos), no por el valor de un par; una sonda con los archivos reales la vio fallar con una fuga real y pasar con una coincidencia |
| `c6`, sugerencia | Dos docstrings de `evaluation.py` y `reporting.py` dicen «tres definiciones» donde hay cuatro | Corregida | `c0a382c` |
| N1 | El motivo de A1 era en parte falso: de 12 a 41 productos por ronda quedan fuera del denominador, no de 12 a 21, y D49 no nombraba la intersección | Corregida (el texto) | A1 de arriba y la nota de D49 (comprobación, N1) |
| N2 | En el modo rápido, la frase de C05 después del sello decía «comparable con el 0,158» para cualquier cifra | Corregida | `dfd3702`: la frase dice «comparable» solo si la cifra calculada con la definición de `p01` está a 0,01 o menos del 0,158, y si no dice las dos cifras y cuánto explican el denominador y el numerador; con la cifra real (0,153) la frase es la misma y ningún archivo publicado cambió |
| N3 | La frase sellada de C05, «0,559 de los productos con alguna compra», se puede leer como la línea de compra de RF04 | Documentada | La ficha del modelo y el diccionario dicen que son las líneas de canasta (`purchase` y `guest_purchase`) y remiten al análisis posterior al sello; la frase sellada no se reescribe (D21) |
| N4 | En un clon sin el archivo, `run` reescribe `reports/validation/latest.*` con el rechazo V01 | Documentada | R1 del runbook lo dice y da cómo restaurarlos (`git checkout -- reports/validation`) |
| A2, lo que quedaba | El sustituto en proceso no exigía el largo de la lista | Corregida | `20e0167` (ver A2 de arriba) |
| N5 | Una corrida de la suite en reposo tardó 120,87 s contra el presupuesto de 120 s (el límite es 180 s) | Medida de nuevo, y la decisión es del dueño | La suite de la última corrección: 111,33 s y 111,89 s; el margen no es estable, y el presupuesto y el límite son el pendiente 13 del plan |
