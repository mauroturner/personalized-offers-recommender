# Investigación previa: ofertas personalizadas a partir de facturas públicas

Documento de la fase de investigación del proyecto 08 (T9 del plan de portafolio). Describe qué contiene el archivo público Online Retail II, qué tan bien las líneas base predicen qué comprará cada cliente en una ventana posterior, qué puede y qué no puede medir un grupo de control sin ofertas reales, qué se solapa con los proyectos 02 y 04, y qué afirmaciones de la página del sitio no se sostienen. No planifica ni construye el producto. Cada cifra sale de un script de `research/` (sección «Scripts y salidas») o de una fuente citada con su URL. Lo que es supuesto o no verificado se marca como tal.

## Hallazgos principales

1. **El archivo es el que dice el sitio, con más filas de las que se ven.** Son 1.067.371 filas en dos hojas. Las dos hojas se solapan en diciembre de 2010: 22.523 filas aparecen dos veces. Sin esas copias quedan 1.044.848 líneas («un millón», C01). Además hay 11.812 repeticiones dentro del conjunto, que se conservan y se marcan. La licencia es CC BY 4.0, verificada en la página de UCI.
2. **Los clientes compran varias veces y las canastas son grandes.** Mediana de 15 productos distintos por factura (media 25,1). El 72,4 % de los clientes tiene al menos dos facturas de compra. El 25,2 % de los pares cliente-producto se compra en más de una factura, y el 37,2 % de las líneas repite un producto que el mismo cliente ya había comprado. La mediana entre facturas consecutivas de un cliente es de 25 días.
3. **Con un corte en el tiempo, lo que más acierta es repetir lo propio.** En el corte del 2011-06-01 (90 días de prueba, 1.617 clientes evaluados), el hit@10 de «lo que este cliente ya compró» es 83,4 % (IC 95 % de 81,5 a 85,0). Le siguen ALS implícito con 64,4 % (62,2 a 66,8), popularidad reciente con 60,5 %, popularidad global con 58,9 %, reglas de asociación con 58,6 % y, al azar, 6,9 %. Si solo se consideran productos que el cliente nunca compró, las reglas de asociación (30,9 %) y ALS (29,3 %) superan a la popularidad global (26,4 %) en 3 a 5 puntos, y a la popularidad reciente (27,8 %) en 1,5 a 3 puntos, con intervalos que se solapan. En el segundo corte, 2011-09-01, la ventaja frente a la popularidad reciente (28,9 %) es de 6 puntos y los intervalos ya no se solapan; el orden general se repite.
4. **El dato no puede medir el efecto de una oferta.** No hay ofertas enviadas, campañas ni clientes retenidos. Con un grupo de control de 20 % sobre los 1.957 clientes activos en el corte, la diferencia más pequeña que se detecta en la tasa de recompra es 7,85 puntos (14 % de la base de 56,4 %). En un A/A con semilla 0, la prueba marca −5,9 puntos como significativos aunque no hay efecto alguno. En 500 semillas, rechaza el 4,6 % para la recompra (nominal 5 %) y el 10,4 % para el valor del gasto, porque el gasto tiene cola pesada (media 710 £, mediana 159 £).
5. **Hay tres fugas que el diseño debe cerrar.** Una división aleatoria de facturas deja que el 81,4 % de las facturas de prueba tenga, en el entrenamiento, una factura posterior del mismo cliente. Contar la popularidad sobre todo el archivo sube el hit@10 de 56,3 % a 58,9 % en los mismos clientes. Con cortes semanales y ventanas de 90 días, un mismo día cae en 13 ventanas de prueba.
6. **Solapamiento con P2 y P4.** El churn de P4 se reproduce: 34,4 % con su definición (los 2.017 y 1.918 clientes de sus cortes de prueba se reproducen con diferencias de 1 a 5 clientes). El segmento mayorista de P2 no se reproduce exacto (340 clientes frente a 335; 24,4 % del ingreso frente a 26,8 %). P8 no predice la baja ni segmenta: decide qué producto ofrecer a cada cliente, y debe medirlo con líneas base y un corte en el tiempo.
7. **La página del sitio tiene una contradicción clara y varias precisiones.** La principal: «Cliente, vacío en algunas filas» subestima el dato, porque el 22,5 % de las filas (una de cada cinco) no tiene cliente (235.287 filas). El resto está en «Contradicciones con el sitio».

## Objetivo

Responder las preguntas de la investigación del plan (qué contiene el archivo, qué ofrecer después con qué líneas base, qué puede medir un grupo de control, en qué se distingue P8 de P2 y P4, y cómo dividir los datos sin fugas) con evidencia verificable, y dejar lista la base para la fase de requerimientos. Quedan fuera la construcción del flujo semanal, la integración con la herramienta de correo o el CRM, el tablero en Power BI (el `.pbix` requiere Power BI Desktop, y el criterio S4 del plan pide un HTML) y cualquier dato de clientes reales.

## Fuentes

| Fuente | Uso | Licencia / condición | URL |
| --- | --- | --- | --- |
| Online Retail II, Daqing Chen (UCI Machine Learning Repository, doi 10.24432/C5CG6D) | Datos, estructura | CC BY 4.0 (texto de la página: «This dataset is licensed under a (CC BY 4.0) license») | https://archive.ics.uci.edu/dataset/502/online+retail+ii |
| Archivo `online_retail_ii.zip` (45.622.418 bytes, SHA-256 `572e3627…e67bfb`) | Descarga verificada | Mismo que el dataset | https://archive.ics.uci.edu/static/public/502/online+retail+ii.zip |
| Libro `online_retail_II.xlsx` dentro del zip (45.622.278 bytes, SHA-256 `bcbe73b3…2e980`) | Única fuente de filas | Mismo que el dataset | Dentro del zip |
| Página de UCI del dataset | Licencia, autor, conteo de filas (1.067.371) | Pública | https://archive.ics.uci.edu/dataset/502/online+retail+ii |
| mlxtend 0.25.0 (reglas de asociación; referencia para la verificación) | Soporte, confianza y lift | BSD-3-Clause (archivo `LICENSE-BSD3.txt` del repositorio; la API de GitHub no lo clasifica) | https://pypi.org/project/mlxtend/ |
| implicit 0.7.3 (ALS implícito) | Línea base de factorización | MIT (API de GitHub, licencia `MIT`) | https://github.com/benfred/implicit |
| README de P4 (`04-Ecommerce-Churn-Risk/README.md`) | Definiciones de baja, cortes y cifras que se reproducen | Repositorio del portafolio | Repositorio local |
| README de P2 (`02-Ecommerce-Customer-Segmentation/README.md`) | Regla mayorista y cifras que se reproducen | Repositorio del portafolio | Repositorio local |
| Página del sitio `src/i18n/projects/personal-offers.ts` (marca-personal, solo lectura) | Afirmaciones a verificar | Repositorio del sitio | Repositorio local |

Los datos de P2 y P4 se leen solo en sus READMEs. No se abrió ninguna carpeta `data/` de otro proyecto. La bibliografía metodológica está en la sección «Literatura».

## Cómo se verificaron los datos

- **Descarga.** `research/s00_download.py` baja el zip al directorio ignorado `data/raw/`, comprueba su tamaño (45.622.418 bytes) y su SHA-256 (`572e3627…e67bfb`), extrae solo el miembro `online_retail_II.xlsx` por su nombre exacto y guarda su huella. Resultado: **zip verificado; un miembro; licencia CC BY 4.0 confirmada en la página de UCI**. El manifiesto queda en `data/raw/manifest.json`.
- **Entorno.** `requirements-research.txt` fija versiones con al menos dos semanas de antigüedad al 2026-11-19 (nada subido después del 2026-11-05). Como el equipo tiene Python 3.11.1, numpy queda en 2.4.6 y scipy en 1.17.1: las versiones más nuevas exigen Python 3.12 (verificado en el campo `requires_python` de PyPI).
- **Conteos del archivo.** `s01_structure.py` cuenta cada fila; el resultado coincide con las cifras que P4 declara en su README: 22.523 copias del solapamiento, 1.044.848 líneas, 11.812 repeticiones internas, 235.287 líneas sin cliente, 17.641 anulaciones con cliente y código de producto y 713.010 £ anulados (`s06` lo reproduce), y 788.187 líneas de compra con cliente (`s02`).
- **Cifras de P2 y P4 que no coinciden.** P2 dice «5.942 con al menos una compra». El archivo tiene 5.942 identificadores de cliente en total, y 5.852 con al menos una línea de compra. P4 dice «5.852 identificados», que coincide con la segunda cifra. Así que la cifra de P2 usa otra definición.
- **Líneas base.** `s03` calcula las métricas con una prueba propia y comprueba las confianzas de las reglas de asociación contra mlxtend (300 productos más frecuentes, 44.744 pares con al menos 10 facturas; diferencia máxima 1,1 × 10⁻¹⁶).
- **Grupo de control.** `s04` repite la división 500 veces con semillas distintas para medir la tasa de rechazo bajo la hipótesis nula (A/A).
- **Ninguna cifra se escribió a mano.** Cada número de este documento sale de un JSON en `data/interim/` (git-ignorado), escrito por un script.

## Estructura de los datos

| Concepto | Valor | Script |
| --- | ---: | --- |
| Filas en «Year 2009-2010» | 525.461 (2009-12-01 07:45 a 2010-12-09 20:01) | s01 |
| Filas en «Year 2010-2011» | 541.910 (2010-12-01 08:26 a 2011-12-09 12:50) | s01 |
| Filas en total | 1.067.371 | s01 |
| Copias exactas del solapamiento, entre hojas | 22.523 | s01 |
| Repeticiones dentro de cada hoja, antes del solapamiento | 12.133 | s01 |
| Repeticiones internas tras quitar el solapamiento (se conservan y se marcan) | 11.812 | s01 |
| Filas del análisis | 1.044.848 | s01 |
| Líneas sin Customer ID | 235.287 (22,52 % de las filas; 16,42 % del valor absoluto) | s01 |
| Clientes con algún ID | 5.942 | s01 |
| Clientes con al menos una línea de compra | 5.852 | s02 |
| Facturas distintas | 53.628 | s01 |
| Líneas de cancelación (factura que empieza por C) | 19.165 en 8.292 facturas; 18.446 con cliente; 17.641 con cliente y código de producto | s01 |
| Valor absoluto de las anulaciones con cliente y producto | 713.010 £ | s06 |
| Facturas de ajuste (A) | 6 filas | s01 |
| Cantidades negativas (incluye anulaciones) | 22.557 filas | s01 |
| Precio cero / precio negativo | 6.024 / 5 filas | s01 |
| Descripción vacía | 4.275 filas | s01 |
| Códigos de existencia distintos | 5.305 | s01 |
| Códigos de forma producto (cinco dígitos y hasta tres letras) | 1.038.855 filas | s01 |
| Códigos que no son producto | 5.993 filas en 63 códigos | s01 |
| Países distintos / parte de filas del Reino Unido | 43 / 91,88 % | s01 |
| Rango de fechas | 2009-12-01 07:45 a 2011-12-09 12:50 (739 días de calendario) | s01 |

**Códigos que no son producto.** Los más frecuentes son POST (2.086 filas, envío), DOT (1.425, envío a la tienda en línea), M (1.398, «Manual»), C2 (277, transporte), D (173, descuento), S (102, muestras), BANK CHARGES (100), ADJUST (67, ajustes) y AMAZONFEE (36). La regla de forma (cinco dígitos) deja fuera también 124 líneas positivas con códigos del tipo `DCGS…` (productos reales de la tienda, por 1.154,72 £) y los vales de regalo `gift_0001_…`. Esto es una decisión de la investigación, no del archivo, y se recoge en «Riesgos y huecos».

## Canastas y clientes

Las cifras salen de `s02_baskets.py`. Una **línea de compra** es una línea con cantidad y precio positivos, código de forma producto y que no pertenece a una anulación (C) ni a un ajuste (A). Una **factura de compra** tiene al menos una línea de compra. Una **canasta de invitado** es una factura de compra sin Customer ID.

- **Líneas de compra:** 1.014.944 (97,14 % de las filas del análisis), de ellas 788.187 con cliente (la cifra de P4).
- **Facturas de compra:** 39.516. De ellas, 2.922 son de invitados (7,4 %).
- **Productos distintos por factura:** mediana 15; p25 6; p75 28; p90 51; media 25,1. El 8,1 % de las facturas tiene un solo producto.
- **Unidades por factura:** mediana 149; p90 524,5.
- **Canastas de invitado:** mediana 19,5 productos (p25 3, p75 120). Los invitados también compran lotes grandes.
- **Facturas por cliente:** mediana 3; p75 7; p90 13; p99 46; media 6,25. El 27,7 % de los clientes tiene una sola factura; el 72,4 % tiene dos o más; el 36,6 % tiene cinco o más.
- **Productos distintos:** 4.877. Solo 156 (3,2 %) aparecen en una factura. El 1 % de los productos más vendidos concentra el 10,9 % de las líneas, y 1.476 productos (30,3 % del catálogo) explican el 80 % de las líneas. El más vendido, el 85123A, aparece en 5.365 facturas.

## Recompra y tiempo entre compras

- **Pares cliente-producto:** 480.971. El 25,2 % se compra en más de una factura. El 37,2 % de las líneas de compra repite un producto que ese cliente ya había comprado antes.
- **Tiempo entre facturas consecutivas del mismo cliente:** 30.742 pares. Mediana 25,0 días; p25 7,0; p75 62,1; p90 136,0; media 52,1. El 82,8 % de los intervalos es menor o igual a 90 días. Esto importa para la ventana de 90 días: la mayoría de las recompras cae dentro de ella.

## Historia disponible en cada corte

Un corte es el primer día de la ventana de prueba. «Activo» quiere decir que el cliente compró en los 90 días anteriores.

| Corte | Con alguna factura antes | Con 2 o más facturas antes | Activos en 90 días | Activos con 2 o más facturas antes | Con 5 o más productos distintos antes |
| --- | ---: | ---: | ---: | ---: | ---: |
| 2011-06-01 | 4.908 | 3.364 | 1.957 | 1.676 | 4.619 |
| 2011-09-01 | 5.224 | 3.642 | 1.919 | 1.699 | 4.931 |

Al corte del 2011-06-01, 944 clientes con compra no tienen ninguna factura anterior: solo pueden recibir una oferta de popularidad. Entre los activos, 281 de 1.957 (14,4 %) no tienen dos facturas previas, y el sitio menciona justamente esa reserva para cuando falta historia.

## Grupo de control

Las cifras salen de `s04_control.py`. El archivo no tiene ofertas, campañas ni retenciones, así que ningún efecto de una oferta se puede estimar a partir de él. Lo que sí se puede medir es si la técnica de grupo de control funciona y cuánto tamaño tendría que tener una operación real para ver un efecto.

- **Población:** 1.957 clientes activos en los 90 días anteriores al 2011-06-01. Un grupo de control de 20 % (semilla 0) deja 391 clientes fuera de la oferta.
- **Equilibrio** (diferencia estandarizada entre grupos; menos de 0,1 en valor absoluto es lo habitual): facturas previas −0,058; días desde la última compra +0,117; gasto previo −0,008. La recencia queda algo desequilibrada en esta división. Conviene estratificar por recencia (ver «Líneas base» y «Preguntas abiertas»).
- **Resultado en el periodo de 90 días sin intervención:** el 56,4 % compra algo; el gasto por cliente tiene media 710,18 £, mediana 159,20 £ y desviación 3.170,51 £.
- **A/A con semilla 0:** la diferencia en la compra es −5,94 puntos (IC 95 % de −11,47 a −0,41). La diferencia en el valor es −84,90 £ (IC de −352,76 a +182,96). El intervalo de la compra excluye el cero **sin que haya efecto alguno**. Una sola división puede engañar.
- **Calibración del A/A, 500 semillas:** rechaza el 4,6 % (compra; nominal 5 %) y el 10,4 % (valor). La prueba normal sobrerrechaza el valor porque el gasto tiene cola pesada. Para el valor conviene una prueba por remuestreo, transformación logarítmica o un ajuste por la historia previa (CUPED, ver «Literatura»). Este resultado es de las cifras reales del archivo, no de un supuesto.
- **Diferencia mínima detectable (MDE), planificación:** α = 0,05 a dos colas, potencia 0,80, varianza observada.

| Tamaño del grupo de control | Clientes en el grupo | MDE, tasa de compra | MDE, como % de la base | MDE, valor por cliente |
| --- | ---: | ---: | ---: | ---: |
| 10 % | 196 | 10,46 puntos | 19 % | 668,84 £ |
| 20 % | 391 | 7,85 puntos | 14 % | 502,16 £ |
| 30 % | 587 | 6,85 puntos | 12 % | 438,18 £ |

Esto no es un efecto: es el menor efecto que la operación podría ver. Ningún efecto se supone en el cálculo.

**Qué puede y qué no puede medir el grupo de control sin conexión:**
- Puede comprobar el equilibrio del grupo, la tasa de falsos positivos del A/A y el tamaño mínimo de efecto que la operación podría ver.
- Puede medir métricas de la política, como hit@10, cobertura o ingreso esperado de la lista, en una **repetición offline**. Esas métricas describen qué habría ofrecido el modelo, no qué habría pasado.
- No puede medir el efecto causal de una oferta. Para eso hace falta asignación aleatoria real durante la operación, registro de exposición (qué oferta recibió cada cliente y cuándo), y el costo de la oferta y el margen para decidir si el efecto paga.

**Diseño propuesto, sin efectos inventados:**
1. Fijar antes de la operación la métrica principal (compra en 90 días o valor en libras), la regla de decisión y el tamaño del grupo (20 % tiene MDE de 7,85 puntos).
2. Asignar al grupo de control de forma aleatoria y estratificada por recencia y frecuencia, para evitar el desequilibrio de +0,117 que se ve aquí.
3. Correr un A/A previo sobre el histórico con la misma regla, y reportar su tasa de rechazo.
4. Para el valor, usar la prueba por remuestreo o transformada logarítmica, no la normal.
5. En el sitio, sustituir «cualquier efecto que se muestre antes es sintético y está marcado así» por la frase honesta: el A/A y el MDE se muestran, y no se muestra efecto alguno hasta que haya datos reales.

## Solapamiento con P2 y P4

Las cifras salen de `s05_overlap.py`, que usa solo el archivo público y las definiciones de los READMEs.

- **P4 (churn), reproducción:** con la definición «compra neta» (la suma de cantidad × precio de todas las líneas del cliente en la ventana, anulaciones incluidas, mayor que cero), los cortes de prueba dan 2.016 clientes con 36,5 % de bajas (2011-08-01) y 1.913 con 32,2 % (2011-09-01). P4 declara 2.017 y 1.918 clientes, y 34,4 % sobre 3.935 filas. Con la definición «compra positiva» (al menos una línea de compra), la tasa agrupada también es 34,4 %. **Confirmado: la tasa de P4 se reproduce con sus definiciones, con diferencias de 1 a 5 clientes en el conteo.**
- **P2 (mayoristas), reproducción parcial:** la regla de P2 (mediana de unidades por línea de al menos 24 y al menos 3 líneas en los 12 meses anteriores al 2011-05-31) da 340 clientes, frente a 335 declarados. El ingreso de esos clientes en los 192 días siguientes es 24,4 %, frente a 26,8 % declarado. **No reproducido exacto:** la diferencia no se explica con la ventana, y su causa (orden de filas, definición de «línea» o de «ingreso») no quedó verificada.
- **Diferencia entre P2 y P4 en el número de clientes:** ver «Cómo se verificaron los datos».

**Qué debe hacer P8 de forma distinta para ser un proyecto distinto:**
1. **El objetivo no es la baja ni el segmento, sino el producto.** P4 predice si un cliente vuelve; P2 estima cuánto va a comprar y en qué grupo está. P8 ordena productos para cada cliente y decide qué ofrecer.
2. **La evaluación es de ranking con líneas base y corte temporal.** Con hit@10, recall, precisión, NDCG y cobertura, contra popularidad, recompra propia y reglas de asociación. P2 y P4 evalúan probabilidades y valores con calibración y criterios de orden de clientes.
3. **No reutilizar la etiqueta de baja ni los modelos BG/NBD o Gamma-Gamma.** Si P8 usa segmentos de P2 como variable, debe declararlo y no mezclar la evaluación.
4. **Mantener el mismo calendario de división que P4** (lanzamiento al 2011-07-31, cuatro entregas mensuales, cierre con 9 días de diciembre), para que los proyectos sean comparables en el tiempo, pero con la métrica de ranking.
5. **Nuevo en P8:** el catálogo de 4.877 productos, las reglas de canasta (incluidas las facturas de invitados) y la lista de ofertas por cliente. Nada de eso aparece en P2 ni en P4.

## Fugas y división propuesta

Las cifras salen de `s06_split.py`.

**División propuesta** (la de P4, de su README):

| Ventana | Desde | Hasta | Filas | Líneas de compra | Facturas de compra | Clientes con compra |
| --- | --- | --- | ---: | ---: | ---: | ---: |
| Historia (lanzamiento) | 2009-12-01 | 2011-07-31 | 788.359 | 764.377 | 30.787 | 5.117 |
| Entrega 1 | 2011-08-01 | 2011-08-31 | 35.284 | 34.324 | 1.339 | 933 |
| Entrega 2 | 2011-09-01 | 2011-09-30 | 50.226 | 49.055 | 1.818 | 1.259 |
| Entrega 3 | 2011-10-01 | 2011-10-31 | 60.742 | 59.067 | 2.005 | 1.361 |
| Entrega 4 | 2011-11-01 | 2011-11-30 | 84.711 | 83.091 | 2.751 | 1.660 |
| Cierre | 2011-12-01 | 2011-12-09 | 25.526 | 25.030 | 816 | 614 |

**Fugas medidas:**
- **División aleatoria de facturas (80/20, semilla 0):** el 81,4 % de las 7.319 facturas de prueba tiene una factura posterior del mismo cliente dentro del entrenamiento. La división en el tiempo tiene 0 %. Por eso el entrenamiento y la prueba deben cortarse por fecha, nunca al azar.
- **Popularidad calculada sobre el archivo completo:** en los 1.617 clientes evaluados del corte 2011-06-01, el hit@10 es 56,3 % con conteos solo de entrenamiento y 58,9 % con conteos de todo el archivo. Esta última cifra usa las compras de la prueba, así que es una fuga. Nota: la cifra de 56,3 % cuenta solo facturas de clientes, mientras que la de 58,9 % de `s03` incluye las canastas de invitados. Por eso no coinciden; el mismo 58,9 % en `s06` con el archivo completo es una coincidencia numérica.
- **Anulaciones:** 17.641 anulaciones con cliente y producto suman 713.010 £. El 94,0 % del valor encuentra una compra anterior del mismo cliente y producto, con cantidad suficiente, con la regla simple de esta investigación. P4 declara 95,2 % con su regla, que no está en el README. La diferencia se atribuye a la regla de emparejamiento, no verificado.
- **Cortes semanales con ventana de 90 días:** entre el 2011-06-01 y el 2011-09-01 hay 14 cortes semanales, y un mismo día cae en 13 ventanas de prueba. Evaluar cada corte y promediar cuenta el mismo futuro varias veces. Con cortes mensuales la superposición es de dos tercios de cada ventana, y P4 reporta dos cortes de prueba que se solapan.
- **Invitados y clientes vacíos:** 235.287 filas sin cliente. Si se incluyen como un solo «cliente», mezclan a miles de personas distintas y crean una fuga entre entrenamiento y prueba. Deben quedar fuera del ranking por cliente y solo entrar a las reglas de canasta.
- **Copias del solapamiento:** sin quitar las 22.523 copias, la semana de diciembre de 2010 cuenta dos veces en el entrenamiento y en la prueba.

**Propuesta de evaluación:** lanzamiento al 2011-07-31; cuatro entregas mensuales (2011-08 a 2011-11), como P4, para comparar en el mismo calendario; cierre con 2011-12-01 a 2011-12-09. Cada entrega se evalúa una sola vez contra su ventana de 90 días, y los conteos de la ventana posterior nunca entran en el entrenamiento. Si el sitio conserva «cada semana», la evaluación semanal debe usar ventanas de 7 días o hacer la evaluación sobre entregas no solapadas (ver «Preguntas abiertas»).

## Líneas base

Las cifras salen de `s03_baselines.py`. Diseño: entrenamiento con líneas de compra anteriores al corte; prueba con lo que cada cliente compró en los 90 días siguientes; usuarios evaluados, los clientes con al menos una compra en el entrenamiento y otra en la prueba; catálogo, los productos con al menos una compra en el entrenamiento.

**Definiciones.** hit@10: el cliente tiene al menos un producto de la prueba entre sus 10 primeros. recall@10: productos de la prueba recomendados entre todos los de la prueba. precisión@10: aciertos entre 10. NDCG@10: ganancia descontada por posición, con relevancia binaria, frente a su orden ideal. Cobertura: productos distintos recomendados entre los del catálogo. Intervalos: bootstrap sobre clientes (1.000 remuestras, semilla 0, percentiles 2,5 y 97,5), y Wilson para el hit@10.

**Corte principal, 2011-06-01 (prueba de 2011-06-01 a 2011-08-29).** 1.617 clientes evaluados de 1.926 con compra en la prueba (309 sin historia de entrenamiento). Los productos de la prueba son 56.557, de los cuales 9,8 % no están en el catálogo de entrenamiento. En promedio por cliente, el 42,9 % de sus productos de la prueba ya los había comprado antes.

| Método | Variante | hit@10 (IC 95 %) | recall@10 | precisión@10 | NDCG@10 | Cobertura |
| --- | --- | --- | ---: | ---: | ---: | ---: |
| Al azar | sin restricción | 6,9 % (5,8 a 8,2) | 0,002 | 0,008 | 0,008 | 0,978 |
| Popularidad global | sin restricción | 58,9 % (56,6 a 61,2) | 0,045 | 0,117 | 0,132 | 0,002 |
| Popularidad reciente (90 días) | sin restricción | 60,5 % (58,3 a 62,8) | 0,048 | 0,129 | 0,146 | 0,002 |
| Lo propio (recompra) | sin restricción | **83,4 % (81,5 a 85,0)** | 0,166 | 0,322 | 0,379 | 0,374 |
| Reglas de asociación | sin restricción | 58,6 % (56,2 a 61,0) | 0,072 | 0,135 | 0,146 | 0,230 |
| ALS implícito | sin restricción | 64,4 % (62,2 a 66,8) | 0,100 | 0,151 | 0,176 | 0,315 |
| Al azar | solo productos nuevos | 4,1 % (3,2 a 5,1) | 0,001 | 0,004 | 0,004 | 0,976 |
| Popularidad global | solo productos nuevos | 26,4 % (24,3 a 28,5) | 0,013 | 0,036 | 0,038 | 0,019 |
| Popularidad reciente (90 días) | solo productos nuevos | 27,8 % (25,6 a 30,1) | 0,013 | 0,039 | 0,044 | 0,015 |
| Reglas de asociación | solo productos nuevos | **30,9 % (28,6 a 33,3)** | 0,020 | 0,046 | 0,049 | 0,271 |
| ALS implícito | solo productos nuevos | 29,3 % (27,2 a 31,6) | 0,019 | 0,045 | 0,048 | 0,335 |

En «solo productos nuevos», «lo propio» queda sin productos y se rellena con popularidad: sus cifras son las de popularidad.

**Segundo corte, 2011-09-01 (prueba de 2011-09-01 a 2011-11-29), para comprobar la estabilidad.** 2.236 clientes evaluados de 2.833 con compra en la prueba (597 sin historia). Los productos de la prueba son 97.949 (9,7 % fuera del catálogo); repetición 35,0 %.

| Método | hit@10 sin restricción | hit@10 solo nuevos |
| --- | ---: | ---: |
| Al azar | 7,6 % (6,5 a 8,7) | 5,1 % (4,2 a 6,0) |
| Popularidad global | 51,8 % (49,8 a 53,9) | 22,5 % (20,8 a 24,3) |
| Popularidad reciente (90 días) | 49,2 % (47,2 a 51,3) | 28,9 % (27,0 a 30,7) |
| Lo propio (recompra) | 77,8 % (76,0 a 79,5) | (como popularidad) |
| Reglas de asociación | 57,9 % (55,8 a 60,0) | 35,2 % (33,2 a 37,1) |
| ALS implícito | 65,9 % (63,9 a 67,7) | 34,6 % (32,7 a 36,6) |

**Lectura.**
- **Repetir lo propio es la línea base que cualquier modelo debe batir.** Con la lista sin restricción, aciertan 83 de cada 100 clientes con esta regla simple, y ALS queda 19 puntos atrás. Un modelo que no la supere no aporta en la lista sin restricción.
- **Para productos nuevos, las reglas de asociación y ALS aportan poco sobre la popularidad reciente**: entre 1,5 y 6 puntos, y solo en el segundo corte la ventaja se separa del ruido. Entre sí, reglas y ALS no se distinguen en ningún corte (intervalos que se solapan).
- **La cobertura cambia la historia.** La popularidad recomienda casi siempre los mismos 10 productos (cobertura 0,002). Las reglas y ALS llegan a 23–33 % del catálogo, y la recompra, a 37–41 %.
- **Los números son provisionales.** No se hizo búsqueda de hiperparámetros para ALS (64 factores, regularización 0,01, 15 iteraciones, alfa 20, semilla 0, fijados antes de ver la prueba), y las reglas usan soporte mínimo de 10 facturas y lift mayor que 1. Una búsqueda cuidadosa puede cambiar el orden de ALS frente a las reglas.

## Literatura

Cada obra se cita por su título, su revista o congreso y su DOI, verificados en la API de Crossref. No se leyó el texto completo de cada una; las ideas que se usan son las de su título y resumen conocidos.

- Agrawal, R., Imieliński, T., Swami, A. (1993). *Mining association rules between sets of items in large databases*. SIGMOD. https://doi.org/10.1145/170035.170072. Definición de soporte, confianza y lift de las reglas.
- Hu, Y., Koren, Y., Volinsky, C. (2008). *Collaborative Filtering for Implicit Feedback Datasets*. ICDM. https://doi.org/10.1109/ICDM.2008.22. Base de ALS con retroalimentación implícita.
- Järvelin, K., Kekäläinen, J. (2002). *Cumulated gain-based evaluation of IR techniques*. ACM TOIS. https://doi.org/10.1145/582415.582418. Definición de NDCG.
- Jannach, D., Jugovac, M. (2019). *Measuring the Business Value of Recommender Systems*. ACM TMIS. https://doi.org/10.1145/3370082. Por qué una métrica offline no mide el valor de negocio.
- Sun, Z., et al. (2020). *Are We Evaluating Rigorously? Benchmarking Recommendation for Reproducible Evaluation and Fair Comparison*. RecSys. https://doi.org/10.1145/3383313.3412489. Evaluación reproducible y comparaciones justas con líneas base sencillas.
- Ji, Y., et al. (2023). *A Critical Study on Data Leakage in Recommender System Offline Evaluation*. ACM TOIS. https://doi.org/10.1145/3569930. Fugas en la evaluación offline, base de la sección «Fugas».
- Kohavi, R., Longbotham, R., Sommerfield, D., Henne, R. M. (2009). *Controlled experiments on the web: survey and practical guide*. Data Mining and Knowledge Discovery. https://doi.org/10.1007/s10618-008-0114-1. Diseño de grupos de control y su tamaño.
- Deng, A., Xu, Y., Kohavi, R., Walker, T. (2013). *Improving the sensitivity of online controlled experiments by utilizing pre-experiment data* (CUPED). WSDM. https://doi.org/10.1145/2433396.2433413. Reducción de varianza con datos previos al experimento, para el valor del gasto.
- Bibliotecas: implicit (MIT), https://github.com/benfred/implicit; mlxtend (BSD-3), https://pypi.org/project/mlxtend/.

## Contradicciones con el sitio

Las afirmaciones se verifican con `s07_site_claims.py`, que también comprueba que las frases citadas aparecen en el archivo `personal-offers.ts` (14 de 14 frases encontradas en la versión en español; la versión en inglés se revisará al editar el sitio). Solo lectura: no se cambió nada en marca-personal.

| # | Afirmación del sitio | Dato | Veredicto | Propuesta |
| --- | --- | --- | --- | --- |
| 1 | «Cliente, vacío en algunas filas» | 22,5 % de las filas (235.287) | **Contradicción por subestimación**: no son «algunas», es una de cada cinco | «Una de cada cinco filas no tiene cliente» |
| 2 | «0 ofertas al azar para medir su efecto» | Ninguna oferta aleatoria ni campo de campaña. Sí hay 173 líneas de descuento (código D) y 252 descripciones con descuento, oferta o vale | **Cierta, con matiz**: no hay ofertas aleatorias, pero sí descuentos no aleatorios | «0 ofertas al azar» con la nota de los descuentos |
| 3 | «Un minorista del Reino Unido» (lede y resumen) | Vende a minoristas y a mayoristas. Con la regla de P2, 340 clientes son mayoristas al corte de lanzamiento | **Matiz**: el vendedor es minorista, pero parte de los compradores son mayoristas | «Una tienda en línea del Reino Unido que vende también a mayoristas» |
| 4 | «Cada semana un flujo arma las ofertas» | Las marcas del archivo son diarias; P4 usa cortes mensuales | **No es contradicción de datos**: es una decisión de plan | Abierta (ver «Preguntas abiertas») |
| 5 | «Una oferta para cada cliente» (título) | 944 clientes no tienen factura antes del corte del 2011-06-01; el 14,4 % de los activos no tiene dos facturas previas | **Se cumple con la reserva que el sitio menciona**: para esos clientes, solo popularidad | Aclarar que el fallback es popularidad |
| 6 | «Un grupo de control listo… cualquier efecto que se muestre antes es sintético y está marcado así» | El MDE con 20 % es 7,85 puntos; el A/A con semilla 0 marca −5,9 puntos sin efecto | **Riesgo de confusión**: un efecto sintético mostrado puede leerse como resultado | Mostrar A/A y MDE, no efectos (ver «Grupo de control») |
| 7 | «Se evalúa con un corte en el tiempo y precisión@k, contra recomendar lo más vendido» | Así se hizo: popularidad 58,9 % frente a ALS 64,4 % en hit@10 (corte 2011-06-01) | **Confirmada** | Ninguna |
| 8 | «Reglas de asociación… usan también las facturas sin cliente» | 2.922 facturas de invitados (7,4 %) entran en las reglas | **Confirmada** | Ninguna |
| 9 | «1 millón de líneas de factura, aprox.» | 1.044.848 tras quitar copias; 1.067.371 en bruto | **Confirmada** (aproximada) | Ninguna |
| 10 | «8 campos por línea» | Ocho columnas en el libro | **Confirmada** | Ninguna |
| 11 | «Fuente: Daqing Chen, CC BY 4.0» | Página de UCI: CC BY 4.0 y autor Daqing Chen | **Confirmada** | Ninguna |
| 12 | «Completados con las reglas de canasta cuando falta historia» | 281 de 1.957 activos sin dos facturas previas | **Confirmada** | Ninguna |
| 13 | Herramientas: Power BI, n8n | No verificable aquí | **No verificable** | El `.pbix` requiere Power BI Desktop; el criterio S4 pide HTML |

Los puntos 1, 3 y 6 piden cambiar el texto del sitio. Los puntos 2, 4 y 5 son matices o decisiones. El resto está confirmado.

## Riesgos y huecos

- **Sin ofertas no hay efecto medible.** Todo lo que el sitio diga de efectos será simulado. Ver «Grupo de control».
- **El archivo es de 2009–2011 y de un solo minorista.** No refleja el comportamiento actual del mercado ni a otros sectores.
- **Regla de forma de producto.** La regla de cinco dígitos deja fuera 124 líneas `DCGS…` (1.154,72 £) y los vales. Es una decisión de la investigación. El catálogo final debe decidir si se incluyen y documentarlo.
- **Anulaciones sin referencia directa.** El archivo no enlaza una anulación con su factura. El emparejamiento de `s06` (94,0 %) no es el de P4 (95,2 %). Cualquier etiqueta que dependa de anulaciones depende de la regla.
- **Ingreso con cola pesada.** La media del gasto (710 £) es más de cuatro veces la mediana (159 £). Las métricas en libras necesitan transformación o recorte, y la prueba normal sobrerrechaza (10,4 %).
- **Sin búsqueda de hiperparámetros.** ALS y las reglas usan valores fijados de antemano. Un modelo mejor puede existir; no está medido.
- **Una sola semilla para la división de control.** Los resultados del A/A se dan para 500 semillas, pero el resto de las cifras se calcula sobre la división fija del 2011-06-01.
- **Cinco precios negativos y 6.024 precios cero.** No se corrigieron; las líneas de compra los excluyen por precio positivo.
- **Desequilibrio de recencia en el grupo.** Con la división aleatoria simple, la recencia tiene +0,117 de diferencia estandarizada.
- **Cifras de P2 que no se reproducen.** El conteo de mayoristas (340 frente a 335) y su ingreso (24,4 % frente a 26,8 %) no quedaron explicados.
- **Licencias.** mlxtend tiene su licencia en `LICENSE-BSD3.txt`, que la API de GitHub no clasifica; se tomó la del archivo y del PyPI. implicit es MIT según la API de GitHub.
- **Sin datos de correo ni de CRM.** Las tasas de apertura, de respuesta y de costo de una oferta no existen en el archivo; el plan debe tratarlas como supuestos declarados.

## Preguntas abiertas para el plan

1. **Cadencia:** ¿semanal, como dice el sitio, o mensual, como P4? Con semanal, la ventana de 90 días se solapa en 13 cortes; hay que decidir la ventana o evaluar sobre entregas no solapadas.
2. **Métrica principal:** ¿recompra en 90 días (lo propio gana con 83 %), o solo productos nuevos (donde reglas y ALS superan poco a la popularidad)?
3. **Mayoristas:** ¿se excluyen de las ofertas o se tratan aparte, como en P2?
4. **Grupo de control:** ¿20 % (MDE 7,85 puntos), 10 % (10,5) o 30 % (6,9)? ¿Estratificado por recencia?
5. **Métrica de dinero:** ¿valor de la canasta en libras con prueba por remuestreo, o transformación logarítmica?
6. **Clientes sin historia:** ¿reciben solo popularidad, como dice el sitio, o se les deja fuera de la operación?
7. **Búsqueda de hiperparámetros:** ¿se autoriza una búsqueda con validación separada antes de la prueba final?
8. **Texto del sitio:** ¿se aceptan los cambios de la tabla de contradicciones (puntos 1, 3 y 6)?

## Scripts y salidas

Todos corren desde cualquier directorio con `python -I`, usando el entorno de `.venv` dentro de este proyecto.

| Script | Qué hace | Salida (en `data/interim/`, ignorada) |
| --- | --- | --- |
| `research/s00_download.py` | Descarga el zip, verifica tamaño y SHA-256, extrae el libro y comprueba la licencia | `data/raw/manifest.json` |
| `research/s01_structure.py` | Estructura, solapamiento, anulaciones, clientes, códigos, países, fechas | `s01_structure.json`, `lines.parquet`, `analysis.parquet` |
| `research/s02_baskets.py` | Canastas, facturas por cliente, popularidad, recompra, tiempos entre compras, historia por corte | `s02_baskets.json` |
| `research/s03_baselines.py` | Líneas base con corte temporal, métricas y IC; verificación de reglas contra mlxtend | `s03_baselines.json` |
| `research/s04_control.py` | Equilibrio, A/A con 500 semillas, MDE por tamaño de grupo | `s04_control.json` |
| `research/s05_overlap.py` | Reproducción de cifras de P4 (churn) y P2 (mayoristas) desde sus definiciones | `s05_overlap.json` |
| `research/s06_split.py` | División propuesta, fugas medidas, anulaciones, cortes semanales | `s06_split.json` |
| `research/s07_site_claims.py` | Comprobación de cada afirmación del sitio y de sus frases citadas | `s07_site_claims.json` |

**Orden:** `s00` → `s01` → `s02` → `s03` → `s04` → `s05` → `s06` → `s07`. Los scripts de la carpeta `research/` no escriben fuera de `data/`. Las dependencias están en `requirements-research.txt`.
