# Runbook: qué hacer cuando algo no sale como se esperaba

Todos los comandos son para Windows (PowerShell), dentro de la carpeta `08-Ecommerce-Personal-Offers/` y con el entorno del proyecto. El paquete no está instalado en el entorno: una vez por sesión,

```powershell
$env:PYTHONPATH = "src"
.venv\Scripts\python -m personaloffers --help
```

**Cómo se escribió este documento.** Está escrito desde lo que dicen el código, las pruebas y el registro de decisiones, con los mensajes tal como los emite el código (las rutas y las claves de corrida se abrevian); **no se corrió cada procedimiento** (por ejemplo, no se llenó el disco ni se mató un proceso a mano). Lo que sí se corrió lo dice cada entrada. Donde el código nombra una entrada de este documento (`docs/runbook.md, R5`), es la que sigue. Las rutas en el texto van con barras normales.

Códigos de salida de la CLI (`src/personaloffers/cli.py`): `0` terminó bien (también una corrida sin entrega pendiente y un `replay` sin pendientes), `1` falló una tarea, `2` uso o configuración incorrectos (también una tarea rechazada por el estado de su corrida, un bloqueo tomado, una reconstrucción a medias, R11, y una evaluación con otra configuración que la sellada) y `3` una fuente o una entrega rechazadas. Cada tarea que falla deja su estado en la corrida (`data/interim/runs/<clave>.json`) y su registro.

Tres principios valen para todo el documento:

- **Un rechazo de la fuente o de la entrega no deja nada a medias.** Una fuente que no pasa V01-V07 o una entrega que no pasa V10-V13 escribe su informe de validación (`reports/validation/latest.md` y `latest.json`, con una copia en `history/`) y el estado de la corrida, y nada más: ni almacén, ni Parquet, ni sello, ni cargas al CRM.
- **Una corrida cerrada no se vuelve a abrir.** Cualquier tarea de una corrida cerrada se rechaza con código `2` antes de escribir nada: la entrega siguiente es otra corrida.
- **El sello no se toca.** `reports/model_seal.json` guarda la configuración del lanzamiento y el primer resultado de la prueba; ninguna tarea lo reescribe con otros valores, y la prueba no se evalúa sin él. SHA-256 del sello de la corrida real: `fa393815…5cc36`.

## R1 Falta la fuente, o no tiene el tamaño o la huella fijados

**Síntoma.** Cualquier corrida con la configuración por defecto sale con código `3`: `rechazada: …` con la regla V01 o V02 y el texto «runbook R1: research/s00_download.py». El informe `reports/validation/latest.md` («Validación de la fuente») nombra la regla, con una copia en `history/` (D50). **En un clon nuevo, sin el archivo, `run` reescribe los `reports/validation/latest.md` y `latest.json` que el repositorio versiona** con ese rechazo de V01, y `git status` los muestra modificados. Para volver a lo versionado: `git checkout -- reports/validation`. Después de bajar el archivo (paso 1), la primera corrida los vuelve a escribir con la entrega que pasó.

**Qué significa.** El flujo no descarga nada (D02): exige `online_retail_ii.zip` (45.622.418 bytes) en `data/raw/`, con el SHA-256 `572e36277c2390fbfde10664750731e0a86f55e33470d91919085f0408e67bfb`, y un solo miembro, `online_retail_II.xlsx`, con su tamaño y su huella. El tamaño se compara antes de calcular la huella. En el modo rápido la huella esperada está vacía a propósito y el primer zip que se ve queda registrado en `data/quick/source.lock.json`.

**Qué hacer.**

1. Bajarlo con el script de la investigación, que comprueba el tamaño y el SHA-256 antes de aceptar el archivo y guarda al lado la página de UCI con su licencia:

   ```powershell
   .venv\Scripts\python research\s00_download.py
   ```

2. Si el script dice que la huella no coincide, UCI cambió el archivo o la descarga se cortó: no cambiar `zip_sha256` en `config/pipeline.toml` para que pase, porque esa clave está en la huella del sello (R7). Volver a bajarlo y, si sigue distinto, tratarlo como otra fuente (R12).

## R2 Una regla del libro falló (V03 a V07)

**Síntoma.** Salida `3` con una de V03 a V07 y la hoja, la columna o la fila que no cumple, por ejemplo «la hoja … no tiene exactamente las columnas …» (V05) o «la parte … declara un DTD o una entidad» (V03). El informe `reports/validation/latest.md` la nombra y no se escribió nada más.

**Qué significa.** El zip y el libro se leen como archivos no confiables (RNF11): V03 revisa el paquete (partes, tamaños descomprimidos, razón de compresión de 100 a 1 como tope, macros, vínculos externos, controles ActiveX, partes cifradas, DTD y entidades) antes de que openpyxl lo abra; V04, las dos hojas con sus nombres exactos y ninguna más; V05, las 8 columnas en su orden; V06, el tipo de cada celda y el tope de filas; V07, las fechas entre `first_date` y `last_date`. Con el archivo fijado por V01 y V02 ninguna debería fallar: si falla, el libro no es el que se midió.

**Qué hacer.** Volver a bajar el archivo (R1) y comparar. No subir `max_rows` ni `max_part_bytes`, ni ensanchar las fechas, para que pase: esos valores son parte de la defensa. Si el libro es otro, se trata como otra fuente (R12).

## R3 Una entrega fue rechazada, o `load` se niega a cargarla

**Síntoma.** La corrida termina `rejected` (salida `3`) con una regla bloqueante, V10 a V13, o `load` dice «la validación de la corrida … rechazó su entrega (…): load no carga una entrega rechazada (docs/runbook.md, R3)».

**Qué significa.** Cuatro reglas bloquean (D22): V10, la entrega es la siguiente del plan que no está cargada; V11, el archivo es el que dice su manifiesto (filas y SHA-256); V12, toda línea tiene su fecha dentro del período; V13, ninguna línea ya cargada. Las demás (V14 a V18) cuentan y la entrega sigue: 11.812 repeticiones internas, 5.938 líneas con precio o cantidad no positivos y 4.275 descripciones vacías en la corrida real. El rechazo escribe solo su informe (`latest.md` y `latest.json`, con la copia en `history/<corrida>.json`; D50) y el estado de la corrida.

**Qué hacer.**

1. Leer `reports/validation/latest.md`: dice la regla, cuántas líneas toca y de qué entrega es.
2. V11 dice que el archivo de `data/raw/deliveries/` no es el que el flujo publicó (alguien lo tocó o se cortó una escritura), y V12 y V13 que su contenido no es el de esa entrega: no editar el manifiesto a mano; reconstruir las entregas con R11.
3. Una corrida rechazada no consume la entrega: la siguiente `run` toma la primera que no está cargada (D28).

## R4 Las entregas están fuera de orden o no coinciden con el almacén

**Síntoma.** V10 rechaza («la entrega es la siguiente del plan»), `replay --until <entrega>` sale con `2` porque esa entrega ya está cargada, o `run` y `replay` salen con `2` con «el manifiesto de entregas dice que … entregas están publicadas y el almacén no tiene cargadas …».

**Qué significa.** El plan es un lanzamiento (`L2011-07-31`), 18 semanales (`W2011-08-01` a `W2011-11-28`) y un cierre (`C2011-12-05`), y se cargan en ese orden, una por una (D22). El manifiesto y el almacén dicen cosas distintas cuando alguien movió uno y no el otro, o restauró una copia vieja.

**Qué hacer.** No cargar una entrega a mano ni cambiar la fecha de una línea. Si solo se movió una parte, mover también las demás y reconstruir (R11); si se restauró una copia, restaurar las dos juntas (almacén y entregas con su manifiesto). Cada entrega cargada es una corrida; una cerrada no se reabre.

## R5 La elección no puede correr (M04, memoria)

**Síntoma.** El lanzamiento falla en la tarea `fit_recipe` con «`N` líneas son del 2011-08-01 o posteriores: la elección solo ve lo anterior al primer día de la prueba (M04, runbook R5)» (un `ValidationLeakError`), o con un error de memoria mientras mide las 48 candidatas.

**Qué significa.** M04 es la regla que protege la prueba: ninguna candidata se calcula con una línea desde el primer día de la prueba, y la elección se niega antes de calcular nada. Pasa si la historia del almacén ya tiene líneas de la prueba, es decir, si se intenta elegir de nuevo con un almacén que ya cargó semanas. El otro caso es la memoria: lo que más pesa de la elección es ajustar ALS y el coseno, una vez por ronda de validación y parámetro (D12), y en cada semanal las matrices de puntajes de unos 4.300 clientes por 4.600 productos se calculan y se liberan de a una; con otros programas abiertos y poca memoria libre, el sistema puede negarse.

**Qué hacer.**

1. Para M04: no cambiar la fecha de corte ni las líneas. El lanzamiento se corre sobre un almacén sin entregas de la prueba; si ya se sellaron la receta y las semanas, la receta no se vuelve a elegir (R7, R11) y un análisis con otra grilla es nuevo (R12).
2. Para la memoria: cerrar otros programas y repetir la tarea con `run --run-key <corrida> --from fit_recipe`. El pico medido de la corrida real fue de 2.056,5 MB de `PeakWorkingSetSize`, contra el límite de 6.144 MB de ese contador (RNF03).

## R6 Un artefacto no coincide con su huella, o el registro falló después del sello

**Síntoma.** Una tarea falla con «el artefacto … de la ronda … no es el que se registró: … (runbook R6)», «ya está en su lugar con otro contenido que el candidato: lo registrado no se reemplaza (runbook R6)» o «se registró con otra huella que la que se recalcula».

**Qué significa.** Cada modelo ajustado se guarda en `data/models/<ronda>/<componente>/` como arreglos `.npy` con un `artifact.json` que lleva el tamaño y el SHA-256 de cada archivo; se lee con `allow_pickle=False` y solo si la huella coincide, y un `.pkl`, un `.pickle` o un archivo no listado se rechaza (D13, M02). Lo registrado nunca se reemplaza. Si el sello ya se escribió y el registro del modelo falló, el sello queda, y el siguiente ajuste lo adopta.

**Qué hacer.**

1. No editar ni copiar un artefacto a mano. Si el sello ya está escrito y el registro falló, retomar la corrida desde el ajuste: el lanzamiento no elige de nuevo (la elección está en el sello) y adopta lo sellado:

   ```powershell
   .venv\Scripts\python -m personaloffers run --run-key <corrida> --from fit_recipe
   ```

2. Si una ronda a medias dejó una carpeta de componentes sin registrar, `recommend` la reemplaza antes de escribir. Un artefacto de una ronda semanal que se dañó se rehace porque el reajuste es determinista (D11), con R11; un artefacto del lanzamiento se compara contra el sello y, si se dañó, se restaura de una copia: lo registrado nunca se reemplaza solo.

## R7 El lanzamiento o la evaluación no reproduce el sello

**Síntoma.** «lo que el lanzamiento recalculó no es lo sellado en: …», «la evaluación de la prueba con la configuración sellada no reproduce los valores sellados, redondeados a 6 decimales: …», «no hay sello del lanzamiento: la prueba no empieza antes de sellar el lanzamiento», «el sello … no se puede leer como JSON» o «la prueba no se evalúa con otra configuración que la sellada mientras el sello no tiene su parte de la prueba» (un `SealMismatchError`, `LaunchSealMissingError` o `EvaluationRefusedError`).

**Qué significa.** El sello tiene dos partes que se escriben una sola vez: la del lanzamiento (antes de cargar la primera semanal) y la de la prueba (la primera evaluación). Lo que la corrida recalcula tiene que ser igual a lo sellado a 6 decimales. La huella `config_sha256` cubre cada clave de la configuración que cambia un valor sellado; cambiar una cambia la huella, y una configuración distinta ya no es la sellada. Con la corrida real, la huella de la configuración es `5ef462a014abd8ee63acbeaf830ec49b77fee4ae670cccd9fc462abffe66fcfa`.

**Qué hacer.**

1. Comparar la configuración con la del commit: `git diff config/`. Una clave que cambió es la causa más probable; revertirla.
2. No borrar ni editar `reports/model_seal.json`. Un sello dañado se restaura con `git checkout reports/model_seal.json`.
3. Si la diferencia es real y se quiere conservar (otra mezcla, otra parte de control), es un análisis nuevo: R12. Después del sello, cambiar una clave es un análisis posterior al sello que se escribe al lado de lo sellado, no una evaluación nueva.

## R8 Otro proceso tiene el bloqueo, o quedó un bloqueo

**Síntoma.** Salida `2` (exit 2) con «Otro proceso escribe esta carpeta de datos: …», «El bloqueo … quedó de un proceso que ya no está en marcha: …», «Un proceso de otro equipo o contenedor tiene esta carpeta de datos: …» o «El bloqueo … existe pero no se puede leer quién lo tiene», siempre con «No se escribió nada».

**Qué significa.** Una carpeta de datos tiene un solo escritor (D29): el bloqueo es `data/interim/pipeline.lock`, que dice el proceso, cuándo empezó, la máquina, el comando y la corrida. La CLI, `replay` y el DAG lo toman antes de escribir. Dos contenedores, o un contenedor y la máquina, comparten la carpeta pero no los procesos, así que un proceso no puede saber si el número de proceso del otro está vivo: lo comprueba una persona. La carpeta `PERSONALOFFERS_HOME` (o la del proyecto) es la que se bloquea.

**Qué hacer.**

1. Mirar el archivo y, si el proceso o el contenedor que lo tomó ya no existen (un proceso matado, un corte de luz), borrar `data/interim/pipeline.lock` a mano y repetir.
2. Si el proceso existe, esperar a que termine; con Airflow, detener el planificador antes de usar `airflow dags test`. Entre dos tareas de una corrida de Airflow, que son procesos separados, nadie lo tiene.
3. No sacar el bloqueo con una corrida en marcha: se rompe la garantía de un solo escritor.

## R9 El CRM no responde, rechaza o da conflicto

**Síntoma.** `deliver_offers` falla con `CrmDeliveryError`, con uno de estos textos: «el CRM no acepta el token (estado 401)», «el CRM no respondió» o «el CRM falló (estado 5xx)» (conexión, tiempo o error del servidor), «el CRM rechazó el pedido (estado …)» (409 `list_conflict`, 413 `payload_too_large`, 400 o 404) o «la lectura de vuelta repite o desordena un contacto». Ningún mensaje trae una dirección, una ruta, una traza ni un cuerpo.

**Qué significa.** El CRM sustituto (`serve-crm`, FastAPI y SQLite) escucha solo en `127.0.0.1` o en la red interna del compose, pide `Authorization: Bearer` en cada pedido y contesta con una palabra fija por error. Una lista emitida no cambia: mandar otra para la misma ronda y el mismo contacto es un 409 y no se aplica nada del lote; mandar el mismo lote otra vez da `unchanged`. Una respuesta perdida o un 5xx se reintenta una vez con el mismo lote. Lo entregado se lee de vuelta, página por página, y se compara con lo emitido; lo que se intentó queda en `crm_deliveries`, un registro por intento.

**Qué hacer.**

1. 401: la variable `PERSONALOFFERS_CRM_TOKEN` tiene que ser la del proceso del CRM y la de quien entrega; no escribirla en archivos versionados.
2. No responde: levantar el sustituto (`python -m personaloffers serve-crm`; en Docker, el servicio `crm`) y repetir `run --run-key <corrida> --from deliver_offers`; solo manda lo que falta (C09: repetir una ronda entregada no crea nada).
3. 409: el CRM tiene otra lista para esa clave. Es el CRM el que está distinto de lo emitido: no se corrige mandando la lista de nuevo, se mira qué cambió su base (`data/crm/standin.sqlite`) y se resuelve con R11 sobre una copia.
4. El grupo de control nunca llega al CRM ni al CSV (M05): si una corrida falla antes de mandar porque un cliente del control iba en un lote, es un defecto del flujo y no se fuerza.

## R10 Airflow o Docker no arrancan

**Síntoma.** `docker compose` no levanta, `airflow-init` termina distinto de 0, `import implicit` falla en la imagen o la prueba `-m docker` no encuentra el motor.

**Qué significa.** El DAG `personaloffers_weekly` corre en Docker con LocalExecutor, PostgreSQL y un servicio `crm` aparte (D26). La imagen es `apache/airflow:3.4.0` con su resumen y trae `libgomp1` fijado, que es el OpenMP que carga `implicit`; sin él `import implicit` falla. Cada secreto sale del entorno, sin valor por defecto y con `${VAR:?}`: `PERSONALOFFERS_DB_PASSWORD`, `PERSONALOFFERS_FERNET_KEY`, `PERSONALOFFERS_JWT_SECRET`, `PERSONALOFFERS_ADMIN_PASSWORD` y `PERSONALOFFERS_CRM_TOKEN`. La interfaz solo escucha en `127.0.0.1:8080`.

**Qué hacer.**

1. Docker Desktop tiene que estar corriendo (`docker version`). La prueba lo comprueba y se salta si no.
2. Si el compose dice que falta una variable, definir las cinco en `airflow/.env` (que no se versiona) con valores de usar y tirar; el compose no lee ningún otro archivo de secretos.
3. `airflow/init.sh` se lee en bytes y no puede tener retornos de carro: una línea terminada en CRLF lo rompe en el contenedor. Con `core.autocrlf` activo, volver a bajar el archivo con finales de línea LF.
4. Después de una corrida de prueba, bajar los servicios con `docker compose down --volumes` y comprobar con `docker ps -a` que no queda nada de este proyecto (la prueba lo hace sola).

## R11 Reconstruir desde cero

**Síntoma.** El almacén no tiene las columnas que dice su definición SQL («El almacén lo creó una versión anterior: se reconstruye desde cero (docs/runbook.md, R11)»), se perdió, o un archivo del flujo se perdió o se tocó, y quedan el sello (`reports/model_seal.json`) y los modelos sellados (`data/models/`).

**Qué significa.** Se reconstruye todo lo demás desde el sello, sin elegir otra vez la receta (D28): el lanzamiento encuentra los artefactos sellados sin su fila en `model_registry`, comprueba sus huellas contra el sello y los registra de nuevo (la tarea `fit_recipe` dice `mode=adopt`); las 18 entregas semanales se regeneran con la semilla sellada, y las listas, el seguimiento, el grupo de control, la evaluación sellada y el registro quedan como estaban; y el cierre repite la evaluación de la prueba y tiene que reproducir el sello (`evaluate` dice `state=repeat` y `seal=unchanged`; si no, R7). Un almacén que creó una versión anterior no se migra: se reconstruye.

**Qué hacer.**

1. Mover a otra carpeta, sin borrarlos hasta comprobar la reconstrucción, estos cuatro: `data/warehouse/`, `data/interim/`, `data/raw/deliveries/` (las entregas con su `manifest.json`) y `data/crm/standin.sqlite` (el CRM sustituto). No mover `reports/model_seal.json`, `data/models/` ni `data/raw/online_retail_ii.zip` (con la página de licencia que lo acompaña).

   ```powershell
   $aside = "..\aside-p08"
   New-Item -ItemType Directory -Force $aside
   Move-Item data\warehouse, data\interim, data\raw\deliveries, data\crm\standin.sqlite $aside
   ```

2. Correr `python -m personaloffers replay`: el lanzamiento sin elegir, las 18 semanales, la ronda censurada y el cierre. En la corrida real, la repetición completa que partió de la fuente tardó 1.094 s (L133); esta reconstrucción no repite la elección de las recetas, y la lectura del libro tarda unos 38 s.
3. Comprobar que la tarea `evaluate` del cierre dice `state=repeat` y `seal=unchanged` y que `git status` muestra solo lo que depende de la corrida: las claves y las horas de las corridas, los segundos de cada ronda (`rounds[].seconds` y `fact_round_ops.seconds`), `dim_pipeline_run` y los hashes del manifiesto que dependen de ellos. Correr `python -m personaloffers run` una vez (sin entregas pendientes termina como `no_delivery`, la corrida que la prueba real espera después del replay) y `python -m pytest -m real_data`.

Si se movió solo una parte, `replay` y `run` salen con `2` sin escribir nada y dicen qué falta mover: con el manifiesto de entregas y sin el almacén, «el manifiesto de entregas dice que … entregas están publicadas y el almacén no tiene cargadas … Para reconstruir desde cero, mover también las entregas (raw/deliveries, con su manifiesto), el CRM sustituto y el sello». En este repositorio no se corre sobre `data/`, para no reescribir lo versionado: lo sigue `tests/e2e/test_rebuild.py`, paso por paso, sobre una copia del modo rápido, y comprueba que reproduce las listas, el seguimiento, el control, la evaluación sellada, el registro y los bytes de los modelos. **Con los datos reales se siguió en una copia** en las correcciones de la evaluación, con el código que fija un hilo de BLAS (D47): el paso 2 terminó con 0 en 969 s, con `fit_recipe` en `mode=adopt` y `seal_state=match` y `evaluate` en `state=repeat` y `seal=unchanged`; las 823.430 filas de `offer_lists` son iguales a las selladas en cada columna salvo `run_key`, y también las listas base, el seguimiento, el control, los modelos, el CRM y las tablas de la evaluación; el sello no cambió. En el paso 3, `run` terminó como `no_delivery` y `pytest -m real_data` pasó (7 pruebas; la que lee la caché de la investigación, `data/interim/analysis.parquet`, se salta porque esa carpeta se movió en el paso 1) (D51).

## R12 Empezar un análisis nuevo: otra mezcla, otra parte de control, borrar el sello

**Síntoma.** Se quiere medir otra cosa: 10 de recompra en la lista, otro porcentaje de control, otra grilla de la elección o otra fuente. O una ronda semanal dice «el sello del lanzamiento es de otra configuración que la de esta corrida: … (runbook R12)» o «el sello … ya existe: la parte del lanzamiento se escribe una vez y no se reescribe (runbook R12)».

**Qué significa.** El sello es de una configuración y de una fuente, y es inmutable. Un análisis nuevo con otra configuración (un valor de la huella cambia `config_sha256`) no reemplaza lo sellado: empieza en una carpeta nueva, con su propio lanzamiento, su propio sello y su propia prueba. Cambiar los valores por defecto de los ítems 2 a 7 de los pendientes del dueño (plan, sección 29) después del sello es un análisis posterior al sello, y se escribe al lado de lo sellado y atado a sus bytes.

**Qué hacer.**

1. Copiar el proyecto sin `data/`, sin `reports/model_seal.json` y sin `outputs/` a una carpeta nueva y apuntar `PERSONALOFFERS_HOME` a ella. No borrar el sello de esta carpeta, aunque la evaluación sellada ya esté escrita.
2. Cambiar la clave en la copia, bajar la fuente (R1) y correr `replay`: el lanzamiento sella la receta nueva y la prueba se abre una vez más, en otra carpeta.
3. Publicar el resultado como un análisis aparte, con su huella, y no sobre `README.md` ni `reports/` de esta carpeta, que dicen lo del sello `fa393815…5cc36`.
