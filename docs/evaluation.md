# La evaluación independiente del proyecto 08

La evaluación independiente (plan, sección 28, ítem 1; registro L136), sus correcciones (ítem 2) y su comprobación (ítem 3). «La evaluación» transcribe el informe del agente evaluador, en un registro neutro y sin las rutas de la máquina; «Las correcciones» cuenta qué se cambió por cada hallazgo, con su commit, su prueba y su impacto medido.

## La evaluación

La evaluación independiente del proyecto 08 (`08-Ecommerce-Personal-Offers`, paquete `personaloffers`) se hizo en solo lectura sobre el repositorio, en el commit `7b7da44`. La corrida sellada es `e9ca105` y el sello mide `fa393815…5cc36`. El núcleo numérico se reproduce exacto con lectores propios: los nueve criterios, las listas, el control, el A/A y la validación. La evaluación encontró seis bloqueantes. Ninguno cambia un veredicto, pero dos son de privacidad en lo publicado y uno es de reproducibilidad (RNF01).

### El entorno

- **Clon:** `git clone --no-hardlinks` en una carpeta temporal fuera del repositorio, en `7b7da44`.
- **Entorno propio:** `.venv` con Python 3.11.1 y `requirements-dev.txt`. `pip check` sale con 0.
- **Archivo:** copiado de `data/raw/` del proyecto.
  - Zip: 45.622.418 bytes, SHA-256 `572e3627…e67bfb`.
  - Libro: 45.622.278 bytes, SHA-256 `bcbe73b3…2e980`.
  - Los dos coinciden con la configuración y con `data/raw/manifest.json`.
- **Estado sellado:** una copia de `data/` completo (2,0 GB: almacén, CRM, modelos, entregas, `interim`) y de `outputs/private/` (los 19 CSV de correo).
- **Copias de trabajo:**
  - `copyR`: R11 tal como está escrito.
  - `copyW`: la semanal real repetida, con un hilo de BLAS.
  - `copyQ`: sondas en modo rápido.
  - `copyT`: el truncamiento de dos rondas.
  - `crmhome`: el CRM sustituto sobre una copia del CRM sellado.
- **El original no se tocó:** `git status` limpio, sigue en `7b7da44` y el sello mide lo mismo.

### Los lectores

Ninguno importa `personaloffers`.

| Lector | Qué hace |
| --- | --- |
| `r01_workbook.py` | Lee el libro con openpyxl en solo lectura. Saca las copias del solapamiento por multiconjunto de los 8 valores, marca las repeticiones internas y asigna los roles en el orden de RF04. |
| `r02_compare_lines.py` | Compara línea por línea con la tabla `lines` y la entrega que le toca a cada fecha. |
| `r03_base_holdout.py` | Arma la base y las covariables de las 19 rondas, los estratos (terciles por rango), el sorteo con la semilla 20110801, el hash de los que entran y el SMD. |
| `r04_metrics.py` | Calcula hit@10, recall, precisión, NDCG y cobertura sobre las listas emitidas y lo comprado en cada semana (leído de sus propias líneas). Hace el remuestreo por cliente (2.000, semilla 0, multinomial). |
| `r05_experiment.py`, `r12_aa_precise.py` | M1 y M2, CUPED, la permutación estratificada, la calibración de 500 × 500, las pruebas normales y el MDE. |
| `r06_validation.py` | Rehace la validación de las 12 candidatas de reglas y de `als_128_r0.1_w0/w1`, leyendo solo líneas anteriores al 2011-08-01. La última línea leída es del 2011-07-31 16:04. |
| `r08_crm.py` | El CRM y los CSV contra las asignaciones y las listas. |
| `r09_examples.py` | El conteo de las listas de ejemplo. |
| `r10_privacy.py` | Revisa los archivos versionados campo por campo, buscando números de cliente y celdas de menos de 10. |
| `r11_diff.py`, `r13_weekly_compare.py` | Comparan una copia reconstruida con lo sellado. |

Algunas sondas usan el código del proyecto a propósito (`probes/p07_truncation.py`, `p_units.py`). La comparación con lo emitido siempre la hace el SQL propio del evaluador.

### Los veredictos, reproducidos o no

| Criterio | Sellado | Cifra de la evaluación | ¿Coincide? |
| --- | --- | --- | --- |
| Lectura (AC03, AC04) | 1.067.371 filas; 22.523 copias; 1.044.848 líneas; 11.812 repeticiones; 235.287 sin cliente; 5.993 fuera de la regla | Lo mismo, y las 1.044.848 líneas son iguales una por una (clave, valores, rol y entrega) | Exacto |
| Base y covariables | 19 rondas | Mismos clientes, diferencia máxima 0 en las seis covariables y el segmento | Exacto |
| Control | 865 en el control y 3.461 en la oferta | El mismo estrato y el mismo grupo para los 4.326; los 812 que entran después, por hash, coinciden todos | Exacto |
| C01 | +25,1 puntos [23,1; 26,9] | 0,251422 [0,231353; 0,269413] | Exacto |
| C02 y C03 | −1,2 puntos [−1,9; −0,4] | −0,011718 [−0,018860; −0,004157] | Exacto: C02 se cumple, C03 no |
| C04 | +5,8 puntos [4,6; 7,0] | 0,057729 [0,046154; 0,069509] | Exacto |
| C05 | 0,559 | Con el denominador del código, 0,558631. Con el que fija el requerimiento, 0,5885 (B5) | Se cumple en las dos variantes |
| C06 | 0,048 | 0,048190615, con la varianza muestral (ddof = 1) | Exacto |
| C07 | 4,8 % y 6,2 % | Con un generador propio de permutaciones, 5,6 % y 6,2 % | Las dos tasas dentro de la banda; ver abajo |
| C08 | p = 0,294 y 0,735 | Con 20.000 permutaciones, 0,315 (error 0,003) y 0,729 | La misma conclusión: ruido de Monte Carlo |
| C09 | 65.959 iguales; 0 del control; 0 nuevas al repetir | 65.959 iguales y 0 del control en el CRM y en los 19 CSV. Un cliente HTTP propio reenvió los 3.433 contactos de R2011-12-05: 0 creados y 3.433 sin cambios | Exacto |
| MDE (C10) | 0,76 puntos y 227,83 £ | 0,0076489 y 227,8253; también con 10 % y 30 % | Exacto |

Detalle de las tasas y las métricas:

- **C07:** los sorteos del evaluador son los mismos que los del proyecto, porque las cuatro tasas de las pruebas normales coinciden exactas (1,4 %, 9,4 %, 4,6 % y 2,4 %). Solo cambia el generador de las permutaciones. La diferencia en M1 es ruido de Monte Carlo cerca del umbral.
- **M1 y M2:** las medias, las desviaciones, las desviaciones ajustadas por CUPED y las θ coinciden a 15 dígitos, igual que las diferencias ajustadas del A/A.
- **Las 17 variantes:** los 105.264 pares del evaluador coinciden con `eval_pairs` (la diferencia máxima de NDCG es 2,2 × 10⁻¹⁶). Las tasas y las coberturas de `eval_methods` también coinciden.
- **Validación:** la regla de D12 elige `als_128_r0.1_w1` entre las 8 candidatas que quedan dentro de 0,005 de la mejor, porque tiene la mayor cobertura, 0,1015. Los cuatro enteros por ronda del evaluador coinciden en `als_128_r0.1_w1` (1.113 aciertos en 3.219 pares), en `als_128_r0.1_w0` y en 10 de las 12 de reglas. En `rules_10_w0` y `rules_20_w0` los aciertos son iguales y difieren en 1 o 2 los productos distintos de tres rondas (advertencia A5).

### Orden y fuga

- **El sello antes de la primera semanal:**
  - El lanzamiento corrió de 23:49:41 a 23:53:56 UTC. Su `fit_recipe` dice `sealed: true`, y los modelos de R2011-08-01 se escribieron a las 23:53:26.
  - La entrega W2011-08-01 se publicó a las 23:53:56,98, en la corrida siguiente, y su carga es posterior.
  - El sello guarda la huella de las listas de R2011-08-01, que es la que dejó la corrida del lanzamiento.
  - Las 20 entregas se cargaron en el orden del plan, cada una por su propia corrida.
- **Ninguna cifra de validación usa el 2011-08-01 o después.** El lector del evaluador leyó solo esas líneas y reprodujo exacto lo sellado de 14 candidatas, la elegida incluida, y los pares y el catálogo de las 48.
- **Truncamiento** (R2011-09-05 y R2011-11-28, en `copyT`, con un hilo de BLAS): las listas de oferta y las de las líneas base son iguales a lo emitido, con todos los decimales del `score`, en los tres casos: con todas las líneas, cortando en el lunes y con las líneas posteriores cambiadas. La base también es la misma.
- **Sin un hilo de BLAS** (el entorno de la CLI), las mismas sondas dan las listas de oferta distintas de lo emitido (B3).

### Privacidad

- **Números de cliente:** ninguno de los 5.942 aparece en un campo de cliente de lo publicado. Lo que coincide son coincidencias:
  - 52 `product_key` que son códigos de producto;
  - un tamaño en bytes en el manifiesto;
  - tres conteos de líneas por país;
  - un conteo de filas en `latest.json`.
- **Archivos escritos a mano:** tienen números reales, que la prueba fija por archivo. `tests/docs/test_docs.py` tiene 4 que nadie fijó (B4).
- **Rutas locales:** ninguna en lo publicado.
- **Celdas de menos de 10 clientes:**
  - Ninguna en los JSON del sitio ni en los Parquet.
  - **Sí en `reports/model_seal.json`** (B2).
  - Las tres listas de ejemplo de `algorithms.json` señalan a un cliente (B1).
- **Efecto:** lo publicado no muestra ningún efecto; las únicas frases con esa palabra son las que permite D16.
- **El CSV:** sin celdas con forma de fórmula.

### Las clases de defecto de la sección 24.2

Las 87 pruebas nombradas, con los 4 nombres de `RENAMED`, salvo las de datos reales y Docker: 115 pasan y 1 se salta (la cuenta de pruebas, que necesita la sesión completa). Además, sondas propias:

| Clase | Veredicto | Sonda propia |
| --- | --- | --- |
| Lista, base o covariable que ve su semana | Cumple | Truncamiento de 2 rondas reales; base de las 19 rondas |
| Popularidad sobre todo el archivo | Cumple | Validación propia con la popularidad de 28 días tomada solo de la historia |
| Invitados como cliente | Cumple | Base solo con `purchase`; reglas con invitados reproducidas exactas |
| Copias contadas dos veces | Cumple | 22.523 y 11.812 propias |
| Ventanas que se pisan | Cumple | Pares por semana reproducidos exactos |
| Cifra de validación con una línea de la prueba | Cumple | Lector que corta en 2011-08-01 |
| Sello escrito después de la primera semanal | Cumple | Orden de las corridas y de las entregas |
| Control sorteado otra vez | Cumple | Sorteo propio; R11 deja `holdout_assignments` idéntico |
| Cliente del control con oferta | Cumple | CRM y 19 CSV: 0. Leer la lista de un cliente del control da 404 |
| Un resultado que no se muestra como ningún efecto | Cumple | Búsqueda de palabras en lo publicado |
| A/A con la prueba normal sobre el gasto | Cumple | La normal sin ajustar rechaza 9,4 % en la calibración, fuera de la banda |
| Permutación que no respeta estratos | Cumple | `draw_assignments` mantiene la cuenta de cada estrato (300 sorteos); p propio comparable |
| Número de cliente o celda < 10 en lo publicado | **No cumple** (B1, B2) | `r09`, `r10` |
| Criterio con otra unidad o denominador | **No cumple** (B5) | C05: líneas de canasta en lugar de líneas de compra |
| Línea base que lee lo que la operación no vería | Cumple | Truncamiento con las líneas base |
| Resumen con otra cifra que la del umbral | Cumple | La columna «Lo que prueba el umbral» = los límites inferiores |
| Tablero o Parquet con otro texto de veredicto | Cumple | Resumen = sitio = Parquet = HTML = README en los 10 |
| Runbook de reconstrucción que no reconstruye | **No cumple en parte** (B3, B4) | R11 reconstruye, pero no da los mismos bytes y su paso de comprobación falla |
| Falla tras el sello: fila huérfana, candidatas borradas | Cumple | R11: `mode=adopt`, `seal_state=match` |
| Reintento que duplica | Cumple | Reenvío propio: 0 creados |
| Lectura de vuelta que repite o saltea | Cumple | Páginas de 333: 3.433 leídos, únicos y en orden |
| Tiempo del cierre descubierto tarde | Cumple | Cierre de 86 s; 71,8 s de `evaluate` en R11 |
| Prueba que escribe en el árbol | Cumple | `git status` limpio tras 2 suites y `-m docker` |
| Archivo versionado sin `write_atomic` | Cumple | Las únicas escrituras de `src` están en `files.py` |
| Byte de control en un Markdown | Cumple | 12 archivos, 0 bytes |
| Métrica que depende del orden | Cumple | Métricas propias con conjuntos, exactas |
| Reajuste no determinista | **No cumple** (B3) | Sin `OPENBLAS_NUM_THREADS=1`, los `score` difieren |
| Modelo con pickle o sin su huella | Cumple | `data/models`: 171 `.npy` y 38 `artifact.json`; R11 adopta con las mismas huellas |
| Reglas con otra confianza | Cumple | Reglas propias, aciertos exactos |
| Prueba de clave que mira el código | Cumple | Cambiar `lookback_days` cambia la huella; `crm.batch_size` no |
| Opción ignorada en silencio | Cumple | `replay --until` inválido o ya cargado sale con 2; `serve-crm --host 0.0.0.0` sale con 2 |
| Tarea desde `load` sin corrida | Cumple | `task load` sin clave sale con 2 y no escribe |
| Ruta relativa contra el directorio de trabajo | Cumple | Configuración leída desde otro directorio |
| Modo rápido que escribe en lo versionado | Cumple | `copyQ`: `git status` solo con archivos de fuera del proyecto |
| Corrida cerrada reanudada | Cumple | `task export` de una corrida `ok` sale con 2 |
| Tareas de una corrida sin su entrega o sin validación | Cumple | V11 sembrada: `validate` sale con 3, `load` con 2, nada escrito |
| Manejador de fallas que tapa el error | Cumple | Prueba nombrada |
| Bloqueo | Cumple | Un bloqueo ilegible sale con 2 y nombra R8; pruebas nombradas |
| Prueba evaluada con otra configuración antes del sello | Cumple | Prueba nombrada; el cierre de R11 da `state=repeat` |
| Huella que no cubre una clave | Cumple | Huella de la configuración del commit = la sellada |
| Resumen tras el sello que dice pendiente | Cumple | Las semanales de R11 dicen `evaluation_source=seal` |
| Servicio afuera o sin token | Cumple | 401 sin token o con otro; `/docs` da 404; sin rutas en los errores |
| Libro malicioso | Cumple | DTD detectado en 0, 5.000, 65.531, 65.533, 65.537 y 196.601 bytes, con espacios y en minúsculas |
| Compose con secreto literal o inicialización que sigue | Cumple | Pruebas nombradas; `${VAR:?}` en el compose |
| Docker que deja su imagen | Cumple | Antes y después, las mismas 218 líneas |
| `pip check` juzgado por texto | Cumple | Código de salida 0 |
| Dependencia sin fijar | Cumple | Prueba nombrada |
| Conjunto mezclado o regla acumulada sumada | Cumple | Huellas de los 7 manifiestos y de los 24 Parquet |
| Segmentador o medida sin sellar | Cumple | Pruebas nombradas |
| Ruta local en lo publicado | Cumple | Búsqueda propia |
| Límite redondeado a mano o documento sin registro | Cumple | Límites del README = intervalos propios |
| Documentación sin sincronizar | Cumple a esta altura | Los documentos decían que esta evaluación faltaba, como correspondía |
| Memoria sin contador | Cumple | `PeakWorkingSetSize` en cada corrida |
| Decisiones sin siete campos | Cumple | Prueba nombrada |
| Tabla de Markdown con otro ancho | Cumple | Prueba nombrada |
| Suite que crece sin aviso | Cumple, con aviso | 109,85 s y 113,72 s: dentro de 120 s y por encima del disparador de 100 s |

### Las corridas

- **`-m docker`:** 2 pasan en 84,0 s (85 s de reloj). El límite es 15 min. Antes y después hay los mismos contenedores, volúmenes, redes e imágenes; solo cambió el orden de una línea `<none>`.
- **La semanal real repetida** (`copyW`): se reconstruyó con `OPENBLAS_NUM_THREADS=1` y `replay --until W2011-11-21` (839 s), y después se corrió `run` sobre W2011-11-28.
  - Tardó 51,5 s de reloj y 50 s en `pipeline_runs`, contra 60 s. La sellada tardó 48 s.
  - El pico fue de 1.732,5 MB de `PeakWorkingSetSize`.
  - Las 823.430 filas de `offer_lists` son idénticas con todos los decimales. También son idénticas las listas base de R2011-11-28 y R2011-12-05, `round_outcomes`, `contact_base`, las asignaciones, `model_registry` y `crm_deliveries`.
- **R11 tal como está escrito** (`copyR`, PowerShell, `$env:PYTHONPATH = "src"` y nada más):
  - El paso 1 movió las cuatro cosas a `..\aside-p08`.
  - El paso 2, `replay`, terminó con 0 en 984,6 s. El lanzamiento dio `mode=adopt` y `seal_state=match`, y el cierre `state=repeat` y `seal=unchanged`. El sello mide lo mismo.
  - El paso 3:
    - `git status` muestra solo los campos de la corrida: el `run_key` de los metadatos, `dim_pipeline_run`, `seconds` y las huellas del manifiesto.
    - `run` termina con 0 y `no_delivery`.
    - **`pytest -m real_data` da 2 fallas** (B4).
  - Las tablas se compararon con SQL propio. Son idénticas las 15 tablas de evaluación, las líneas, las entregas, el control y los modelos, el CRM (65.959 listas) y el CSV de R2011-12-05.
  - **No es idéntica `offer_lists`:** 16.234 de 823.430 `score` difieren en hasta 9,5 × 10⁻⁷ (B3). Productos, rangos, orígenes y grupos son iguales.
  - Cada corrida de la CLI muestra el aviso «OpenBLAS is configured to use 24 threads».

### Las suites

| Suite | Resultado |
| --- | --- |
| Suite por defecto en reposo, dos veces | 1.238 pasan y 1 se salta (1.239 recogidas, 9 sin seleccionar), en 109,85 s y 113,72 s. Límite 180 s, presupuesto 120 s, disparador 100 s. El «unos 108 s» de la documentación era correcto |
| `-m real_data` en `7b7da44` | **Falla** (B4) |
| `-m docker` | 2 pasan |

### Bloqueantes

**B1. Las listas de ejemplo de `algorithms.json` permiten reidentificar a un cliente (D30, RNF12).**
- Lo que dice el registro: L133 contó 5, 5 y 6 clientes que habían comprado antes de la ventana los siete productos de recompra de cada lista.
- El conteo del evaluador (`r09`) confirma eso y lo agrava:
  - Cada lista de 10 es de un solo cliente en R2011-08-01.
  - El archivo publica también el perfil (`segment_key`). Dentro de ese perfil, los clientes que compraron los siete productos de recompra son **5, 1 y 2**.
  - Para «Minorista con una factura», la lista y el perfil más el archivo público de UCI dan un único número de cliente y su lista completa.
- Reproducción: `indep/r09_examples.py own_lines.parquet outputs/site/algorithms.json personaloffers.sqlite`.

**B2. El sello versionado tiene 8 celdas de menos de 10 clientes.**
- Dónde: `reports/model_seal.json`, `launch.holdout.sizes.strata`. El estrato 1 tiene 2 en el control y 8 en la oferta; los estratos 3, 7, 9, 11, 15 y 17 tienen de 3 a 7 en el control.
- La nota de D30 de U21 cuenta el sello entre los archivos publicados y dice «ninguna celda mostrada con menos de 10 clientes»; estas celdas lo contradicen.
- El riesgo práctico es bajo: no dice quién está en el control, pero los estratos se reconstruyen desde el archivo público.
- El sello no se reescribe: la corrección es una decisión (excluir el sello de lo publicado, o anotar una excepción de D30).
- Reproducción: `indep/r10_privacy.py`.

**B3. El flujo no fija `OPENBLAS_NUM_THREADS=1` (RNF01; plan, sección 2).**
- El plan dice que el flujo lo fija en `pipeline.py` y el compose en su entorno. No había ninguna mención en `src/` ni en `airflow/`. Solo `tests/conftest.py` lo fijaba.
- Consecuencias, siguiendo R11 o cualquier corrida de la CLI o del DAG:
  - 16.234 `score` de `offer_lists` salen con otros bytes, y RNF01 pide las mismas listas byte a byte.
  - Recalcular una ronda ya emitida en ese entorno no coincide con lo guardado: `p07` sin la variable da `offer==stored False` en las dos rondas. En `emit_round`, eso es un `ScoringError`.
- Con un hilo, todo coincide exacto (`p07` y `copyW`).

**B4. `pytest -m real_data` falla en `7b7da44`, y con eso el paso 3 de R11.**
- (a) En cualquier estado: `test_no_real_customer_number_in_anything_versioned_or_published_and_no_cell_under_the_minimum` falla porque `tests/docs/test_docs.py`, agregado en U22 (`ea36e58`), tiene 4 números de cliente reales (los dos extremos del rango, dos veces cada uno) que no están en `HAND_WRITTEN_WITH_REAL_NUMBERS`. Pasa en `copyR` y en `copyW`.
- (b) Tras una reconstrucción correcta: `test_real_counts_seal_and_summary_consistency` exige que los `run_key` del sello sean los de las corridas actuales. Ninguna reconstrucción puede cumplirlo, así que la comprobación que pide R11 no puede pasar.
- El README también mandaba correr `-m real_data`.
- Reproducción: el registro `r11_real_data.log` de `copyR`.

**B5. C05 usa otro denominador que el preregistrado.**
- Lo preregistrado (requerimientos, 8.1): «productos con alguna **línea de compra** en los 365 días anteriores». RF04 define una línea de compra como `purchase`.
- El código cuenta las líneas de canasta (`purchase` y `guest_purchase`) y da 0,5586. Con la definición preregistrada da 0,5885. El veredicto no cambia.
- Además, el README, la ficha del modelo y `SITE-UPDATES.md` atribuían la distancia con el 0,158 de la validación solo al denominador. Medido:
  - Cambiar solo el denominador lleva 0,559 a 0,466.
  - La causa principal es el numerador: la validación contó las listas de los unos 250 clientes evaluados, no las de los 4.300 de la base. Con la misma definición que `p01`, la prueba da **0,153**, comparable al 0,158.
- Es la clase de 24.2 «criterio con otro denominador» (la lección B1 del 07).

**B6. El runbook dice que un rechazo escribe su informe en `latest`, y no lo hacía.**
- Lo que dice: el principio 1 del runbook y el paso 1 de R3 dicen que un rechazo escribe `reports/validation/latest.md` y `latest.json` con una copia en `history/`.
- Medido en `copyQ`:
  - Una V11 sembrada (`task validate`, salida 3) escribe solo `history/<corrida>.json`. `latest.md` sigue mostrando la entrega anterior, W2011-03-28, con V11 «pasa».
  - Un zip cambiado (V01, salida 3) no escribe ningún informe.
- Quien siga R3 lee el informe de una entrega que pasó.
- El código escribía `latest` solo en `report`.

### Advertencias

- **A1:** la cobertura no se calcula como intersección. De 12 a 41 productos por ronda de las listas no están en el denominador, y la cuenta crece con las rondas (la comprobación la contó: 12, 16, 16, 19, 21, 20, 21, 24, 26, 30, 31, 28, 32, 34, 35, 37, 41 y 39; la evaluación había escrito de 12 a 21). La B0 de C10 da 1,20.
- **A2:** el CRM sustituto acepta una lista de 9 productos (200, `created`). M06 cuida el flujo.
- **A3:** el p del A/A sellado (2.000 permutaciones) se aparta unos 2 errores de Monte Carlo del cálculo con 20.000 (0,294 contra 0,315).
- **A4:** la semanal crece unos 0,65 s por ronda (de 37 a 48 s) y el pico de `PeakWorkingSetSize` va de 1.728 a 2.057 MB. Sin consecuencias dentro del alcance de 18 rondas.
- **A5:** empates de la reserva en `rules_10_w0` y `rules_20_w0`. Los aciertos son iguales y la elección no cambia.
- **A6:** las advertencias abiertas siguen abiertas, sin consecuencias en ninguna salida:
  - `u15b` S2: claves de requerimientos en las pruebas (90 archivos).
  - `u15b` S4: la holgura de 1 ms del orden por fecha de modificación, en `test_star_schema.py:377`.
  - `u16` S2: `svg.standalone` y `svg.sparkline` no tienen uso ni prueba.
- **A7:** las dos dejadas con evidencia se confirman. R11 regenera el CRM idéntico, y las 9 «oculta» del diseño son celdas ocultas.
- **A8:** una carpeta que no es componente de la receta (`als/` en una ronda de coseno) queda en `models` sin tocar. Sondeado en `copyQ`.
- **A9:** la CLI imprime el aviso de deprecación de Starlette sobre httpx. Es del paquete de terceros, no del proyecto.

**Unidades que no se revisaron, con su sonda:**

| Unidad | Sonda | Resultado |
| --- | --- | --- |
| U02 | 7 configuraciones malas | Cada una da `ValueError` con su clave |
| U03 | El libro de las pruebas | Sus códigos de producto y sus clientes no coinciden con los reales |
| U05 | Roles y entregas | Reproducidos exactos |
| U05 | V11 sembrada | Rechazo sin daño, y la entrega se republica intacta |
| U07 | Base y covariables | Exactas |
| f1 | DTD en el borde de los bloques | Detectado |
| f2 | Carpetas sin registrar | Se reemplazan las de los componentes (A8) |
| U19 | CLI | Códigos 2 y 3 |
| U19 | `docs-sync` | Idempotente |
| U19 | R11 | B3, B4 |
| s3 | Pruebas del tramo | Dentro de la suite, que pasa |
| U22 | Documentación | B4 y B5; la cuenta de 1.239 y los 108 s eran correctos |
| `e9ca105` | Lo generado | Todas sus cifras coinciden con los lectores del evaluador; B1 y B2 están en sus archivos |

### Los dos hallazgos de L133

- **(a) Confirmado y agravado (B1):** 1 cliente por lista. Con el perfil publicado, los que compraron los siete productos de recompra son 5, 1 y 2.
  - Un reemplazo honesto es una lista agregada por perfil, rotulada como tal: los 7 productos de recompra y los 3 de descubrimiento que más aparecen en las listas del segmento en esa ronda, cada uno con la cantidad de clientes que lo tienen (todas de 10 o más), sin rangos de un cliente.
  - Otra opción es la lista de un cliente inventado, que la receta sellada arma desde una historia de productos populares, cada uno comprado por 10 o más clientes, y que diga «ficticio».
- **(b)** El requerimiento fija «líneas de compra» (`purchase`), no las de canasta: 0,5885 en lugar de 0,5586 (B5). El veredicto no cambia con ninguna definición; también se cumple con la de `p01`, 0,153. La distancia con 0,158 es sobre todo el numerador.

### Las carpetas de trabajo

El evaluador dejó sus copias, sus lectores y sus sondas en una carpeta temporal fuera del repositorio (sin borrarlas), con una copia de `indep/` y `probes/` junto al informe.

## Las correcciones

Un agente con Opus corrigió con la prueba primero (plan, sección 28, ítem 2), desde `7b7da44`. El sello no cambió (SHA-256 `fa393815…5cc36`), nada se reajustó ni se eligió de nuevo, y cada corrección que nombra un ítem de riesgo alto va en su propio commit.

| Hallazgo | Qué se hizo | Commit | Prueba en rojo antes del código | Impacto medido |
| --- | --- | --- | --- | --- |
| B1 (ítem 2) | Cada lista de ejemplo es el agregado de su perfil, rotulado: los 7 de recompra y los 3 de descubrimiento que más aparecen en las listas del perfil en R2011-08-01, cada uno con cuántos clientes lo tienen con ese origen, sin rangos (D46) | `a7a265a` | La prueba de datos reales de las listas de ejemplo dio 36 problemas, entre ellos que un solo cliente del perfil tiene cada lista entera; las del contrato fallaron por la forma | Los productos los tienen de 14 a 954 clientes; ningún cliente del perfil tiene la lista entera |
| B2 (ítem 2) | El sello es la excepción con nombre de D30, como registro de auditoría que no se reescribe; la prueba de privacidad la nombra y demuestra que ningún JSON del sitio, Parquet ni el diseño muestra el tamaño de un estrato ni una cuenta de menos de 10 (D48) | `6c07167` | Sin código que cambiar; una sonda vio fallar la prueba con un estrato agregado a `control.json`, una cuenta de 7, una novena celda en el sello y un diseño que nombra un estrato | El sello sigue con sus 8 celdas y ningún otro archivo publicado las muestra |
| B3 (ítem 5) | `pipeline.py` fija `OPENBLAS_NUM_THREADS` y `MKL_NUM_THREADS` en 1 antes de su primer import, y el compose en el entorno de Airflow (D47) | `f1b0a4b` | Las cuatro pruebas de `tests/unit/test_blas_threads.py` | R11 en una copia: `offer_lists` igual a la sellada en todas sus columnas salvo `run_key`, y ningún aviso de OpenBLAS |
| B4 | Sin números de cliente en `tests/docs/test_docs.py`; la prueba compara las claves del sello con las de las corridas que lo escribieron y, en una reconstrucción, pide `adopt` y `repeat` (D51) | `5edb032` | (a) en el repositorio; (b) en la copia reconstruida, con la prueba de `7b7da44` | `-m real_data` pasa en el repositorio y después de R11 |
| B5 (ítem 1) | C05 con cuatro definiciones en `reports/post_seal_analysis.json`, al lado del sello y atado a sus bytes; el resumen y el sitio lo llevan, y cada frase dice una cantidad con su definición (D49) | `d496a88`, `6b7d650` | `tests/integration/test_post_seal_analysis.py` (`AttributeError` antes del código, y la del cierre sin la escritura en `report`) | Sellado 0,559; preregistrado 0,588 (se cumple); con el denominador de `p01`, 0,466; con su definición, 0,153 |
| B6 | Un rechazo de la entrega y uno de la fuente escriben su informe como el último, con la copia en `history/` (D50) | `c6d31e1` | La prueba de la CLI de los dos rechazos | V11 y V01 dejan su propio `latest.md` |
| A2 | El CRM sustituto servido rechaza una lista que no tiene `k` productos | `4d18d86` | La prueba del sustituto con listas de 9 y de 11 | 400 para todo el lote, nada aplicado |
| A8 | Al emitir una ronda se borra una carpeta sin registrar con el nombre de un componente que la receta no usa, y se anota lo que no es un componente | `4d18d86` | La prueba de la ronda con una carpeta ajena | La ronda se emite y la carpeta ya no está |

Las demás advertencias quedan con su motivo en `docs/review-advisories.md`: A1 (calcular la cobertura como intersección cambiaría cifras selladas; un análisis posterior al sello es posible y no se hizo), A3, A4, A5, A6, A7 y A9.

**Las salidas regeneradas** (`324b444`). Desde una copia del estado sellado, con los pasos de exportación y de cierre de la corrida del cierre y nunca con una corrida nueva. Cambiaron por una corrección y se copiaron: `outputs/site/algorithms.json` (B1), `outputs/site/summary.json`, `reports/evaluation_summary.json` y `reports/evaluation_summary.md` (B5), `reports/post_seal_analysis.json` (nuevo, B5) y `outputs/site/manifest.json` (los tamaños y las huellas de los dos JSON del sitio). El bloque de resultados del README lo copió `docs-sync`. Todo lo demás de `outputs/`, `reports/` y `dashboard/`, y las figuras, salió idéntico byte por byte, y el sello no cambió.

**El diferencial.** 39 casos de la CLI en modo rápido (los comandos y las opciones de la sección 22, sus errores, un rechazo V11 y uno V01), en dos copias, una en `7b7da44` y otra en `324b444`, con la salida, los errores, los códigos, los informes de validación y los archivos de `data/quick/` comparados. Los códigos de salida son los mismos en los 39. Las únicas diferencias son las pedidas: ya no sale el aviso de OpenBLAS (B3), los rechazos V11 y V01 dejan su propio informe como el último (B6), las listas de ejemplo son agregados (B1) y el resumen y el sitio llevan el análisis posterior al sello (B5). Lo demás que cambia depende de la corrida: las claves, las horas, los segundos de cada ronda, los picos de memoria y las huellas del manifiesto que dependen de ellos.

**La reconstrucción.** R11 seguido en una copia con los datos reales y el código corregido: el paso 2 terminó con 0 en 969 s (`mode=adopt`, `seal_state=match`; `state=repeat`, `seal=unchanged`), sin el aviso de OpenBLAS. `offer_lists`, las listas base, `round_outcomes`, `holdout_assignments`, `contact_base`, `model_registry`, `crm_deliveries`, `round_ops`, `validation_results`, las líneas y las tablas de la evaluación son iguales a las selladas salvo las columnas de la corrida (`run_key`, `seconds`). El paso 3: `run` terminó como `no_delivery` y `pytest -m real_data` dio 7 pasan y 1 se salta (la caché de la investigación, que el paso 1 movió). Lo que el cierre de la reconstrucción escribió de las correcciones (`post_seal_analysis.json`, el resumen y las listas de ejemplo) es igual a lo versionado.

**Las pruebas.** La suite por defecto en reposo, dos veces: 1.252 pasan y 1 se salta (1.253 recogidas), en 115,73 s y 113,60 s, dentro del presupuesto de 120 s y por encima del disparador de 100 s; las pruebas nuevas sumaron unos 6 s. `pytest -m real_data` en el repositorio: 8 pasan. `pytest -m docker`: 2 pasan en 86,5 s, con Docker igual antes y después. `pytest tests/docs`: 25 pasan y 1 se salta (la cuenta de pruebas, que necesita la sesión completa). El sello mide `fa393815bb5eb6d39a8b29f0167200f0d4f6305da30980b636fee5a9b1c5cc36`.

## Comprobación

Todavía no se hizo. La hace otro agente con Opus (plan, sección 28, ítem 3): rehace los bloqueantes en copias del commit evaluado y del corregido, con un diferencial de la CLI y de la API del CRM, y compara salida, errores y códigos. Una segunda corrección solo si un bloqueante sigue fallando.
