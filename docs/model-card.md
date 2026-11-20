# Ficha del modelo: una oferta para cada cliente, armada sola

Qué es el flujo, para qué sirve y para qué no, con qué datos, cómo se eligió el modelo, cómo se arma la lista y el grupo de control, cómo se mide y qué no hace. Los datos son reales y públicos (Online Retail II de UCI). El archivo no tiene ofertas: **no se mide el efecto de una oferta** y ninguna cifra de esta ficha lo es. Las cifras son las del resumen sellado de la corrida real del 2026-11-19 al 2026-11-20 (sello de SHA-256 `fa393815…5cc36`, huella de la configuración `5ef462a0…fcfa`); `tests/docs/test_docs.py` comprueba que cada veredicto y cada fila de la tabla de métodos son los del resumen y los de `outputs/site/algorithms.json`. **Ninguna cifra es definitiva hasta la comprobación de las correcciones** (plan, sección 28, ítem 3): la evaluación independiente y sus correcciones están hechas (`docs/evaluation.md`), la comprobación falta.

## Uso previsto y no previsto

**Uso previsto.** Armar cada semana una lista de 10 productos por cliente para una campaña, con un grupo de control listo, y entregarla a un CRM o a una herramienta de correo. Lo que ofrece es una priorización de productos por cliente, con su origen; la decisión de qué campaña mandar y con qué contenido no es del modelo.

**Uso no previsto.**

- Estimar cuánto vende una oferta: no se mide el efecto de una oferta, porque el archivo no tiene ninguna enviada, y ninguna cifra de esta ficha lo es.
- Decidir descuentos: el descuento, su costo y el margen no están en los datos.
- Recomendar a clientes nuevos: quien nunca compró no está en la base y no recibe lista; el flujo no los inventa.
- Leer el A/A como un resultado: compara dos grupos que no recibieron nada, y lo que muestra es cómo quedó armado el control y qué tan calibrada está la prueba.
- Pensar que la lista le gana a repetir lo que el cliente ya compra: C03 no se cumple.

## Datos

- **Fuente**: Chen, D. (2012). Online Retail II. UCI Machine Learning Repository, CC BY 4.0. `online_retail_ii.zip`, 45.622.418 bytes, SHA-256 `572e3627…7bfb`; dos hojas con 525.461 y 541.910 filas, del 2009-12-01 al 2011-12-09.
- **Líneas**: 1.067.371 filas, 22.523 copias del solapamiento entre hojas quitadas, 1.044.848 líneas y 11.812 repeticiones internas marcadas. 235.287 líneas (22,5 %) no tienen cliente: entran en las reglas de canasta y en la popularidad, nunca como un cliente. 5.993 quedan fuera de la regla de producto.
- **Clientes**: 5.852 con alguna compra; la base de la primera ronda tiene 4.326 y las 19 rondas de la prueba entre 4.268 y 4.372. Los mayoristas (339 en la base del lanzamiento, con la regla del proyecto 02) entran en la base y en las ofertas.
- **Calendario**: historia hasta el 2011-07-31; 13 rondas de validación (2011-05-02 a 2011-07-25); 18 rondas de prueba, cada lunes del 2011-08-01 al 2011-11-28, con ventanas de 7 días que no se pisan; una ronda censurada del 2011-12-05 (cinco días), solo informativa; el cierre.
- **Sin fuga**: ninguna base, covariable, recomendador ni asignación lee una línea de su ronda o posterior (RNF07); la elección usa solo las 13 rondas de validación, que terminan antes de la prueba.

## Los recomendadores

Todos reciben la historia anterior al lunes de su ronda y devuelven un puntaje por cliente y producto. Con un orden de desempate fijo (puntaje, popularidad, código) el mismo insumo da las mismas listas byte a byte.

- **Popularidad** (B1 global, B2 de 28 días): facturas distintas con el producto, las de invitados incluidas. B2 es la reserva de la lista y la tendencia de la mezcla.
- **Recompra propia** (B3): las facturas del cliente con el producto más la mitad de la recencia relativa de la última compra.
- **Reglas de pares** (B4): soporte mínimo en facturas y `rule_lift` mayor que 1; el puntaje de un producto es la mayor confianza desde un producto que el cliente compró. Una prueba compara las confianzas con mlxtend a 1 × 10⁻⁹.
- **ALS implícito** (B5) y **similitud coseno entre productos** (B6), con implicit, un hilo y una semilla fija.
- **La mezcla con la tendencia**: el puntaje del modelo dividido por su máximo por cliente, más un peso por lo más vendido de 28 días dividido por su máximo.
- **Los modelos** se guardan como arreglos `.npy` con su SHA-256, sin `pickle`, y se leen solo si la huella coincide.

Cómo les va, con las 18 rondas de la prueba (5.803 pares (ronda, cliente) de clientes que compraron en la semana). «Sin restricción» es la lista tal cual; «solo nuevos» es la lista armada solo con productos que el cliente nunca compró antes de la ronda. La cobertura es la de la definición del plan, los productos distintos de las listas de la ronda sobre los productos con compras en los 365 días anteriores, promediada sobre las 18 rondas, y puede pasar de 1 si una línea base ofrece productos sin compras en ese período.

| Método | hit@10 sin restricción | Intervalo del 95 % | Cobertura | hit@10 solo nuevos | Intervalo del 95 % | Cobertura de solo nuevos |
| --- | --- | --- | --- | --- | --- | --- |
| B0 al azar | 5,6 % | 5,0 % a 6,3 % | 1,200 | 2,9 % | 2,4 % a 3,4 % | 1,200 |
| B1 popularidad global | 43,1 % | 41,4 % a 45,0 % | 0,003 | 13,1 % | 12,2 % a 14,1 % | 0,021 |
| B2 lo más vendido de 28 días | 52,9 % | 51,1 % a 54,8 % | 0,003 | 28,1 % | 26,7 % a 29,6 % | 0,016 |
| B3 recompra propia | 79,2 % | 78,0 % a 80,4 % | 0,652 | 28,1 % | 26,7 % a 29,6 % | 0,016 |
| B4 reglas de asociación | 47,5 % | 45,8 % a 49,3 % | 0,407 | 23,3 % | 22,0 % a 24,6 % | 0,449 |
| B5 ALS | 57,1 % | 55,3 % a 58,8 % | 0,510 | 23,2 % | 21,9 % a 24,5 % | 0,514 |
| B6 coseno entre productos | 61,0 % | 59,3 % a 62,6 % | 0,568 | 22,1 % | 20,8 % a 23,4 % | 0,363 |
| Modelo elegido (descubrimiento) | 74,0 % | 72,6 % a 75,5 % | 0,258 | 33,8 % | 32,4 % a 35,5 % | 0,241 |
| La lista que se entrega | 78,0 % | 76,8 % a 79,3 % | 0,559 | — | — | — |

B3 y B2 tienen el mismo «solo nuevos» porque la recompra propia no tiene productos nuevos y su lista se completa con la reserva de 28 días. Las reglas, ALS y el coseno solos pierden contra B2 en productos nuevos; solo la mezcla con la tendencia lo supera.

## La elección y la lista

**La elección.** En el lanzamiento, 48 recetas (24 de ALS con 3 tamaños, 2 regularizaciones y 4 pesos de la tendencia; 12 de coseno; 12 de reglas) se miden en las 13 rondas de validación por hit@10 solo nuevos; entre las que quedan a medio punto de la mejor se elige la de mayor cobertura (D12). Salió `als_128_r0.1_w1`: 128 factores, regularización 0,1 y la tendencia con peso 1; en la validación acierta al 34,6 % de 3.219 pares con una cobertura de 0,101. Las mejores sin la tendencia quedan en 20,6 % (reglas), 21,3 % (ALS) y 24,2 % (coseno). Se elige antes de abrir la prueba y se sella; como se eligió en las mismas rondas en que se mide, la cifra de validación de la elegida es optimista (D12).

**La lista.** Para cada cliente de la base, 10 productos distintos, 7 de recompra y 3 nuevos como mínimo cuando el modelo tiene candidatos: hasta 7 de la propia recompra, después productos que nunca compró con puntaje del modelo elegido (al menos 3 cuando el modelo tiene candidatos y más si la recompra da menos de 7), y por último lo más vendido de 28 días, sin repetir. Cada producto lleva su origen (`repeat`, `discovery`, `fallback`) y su rango.

**El reajuste semanal.** Cada lunes los modelos se reajustan con la receta sellada y la historia anterior a ese lunes; lo emitido no se rehace.

## El control y el experimento

- **El grupo de control.** El 20 % de la cohorte del lanzamiento (865 de 4.326 clientes; los otros 3.461 reciben lista), estratificado en 18 estratos por recencia, frecuencia y la marca de mayorista, sorteado una sola vez con la semilla sellada. Quien entra a la base después se asigna por una función hash, y nadie se reasigna. El control tiene una lista que nunca se entrega: es lo que se le habría ofrecido.
- **El equilibrio** (C06). Las cinco covariables de la cohorte del lanzamiento quedan con una diferencia estandarizada absoluta de 0,008 (recencia), 0,038 (facturas del año), 0,048 (gasto del año), 0,023 (antigüedad) y 0,004 (marca de mayorista); la mayor es 0,048. En la investigación, un sorteo simple sin estratos había dado +0,117 en la recencia sobre otra población (requirements.md, C06).
- **La prueba preregistrada.** M1 es la parte de las 18 semanas de prueba con alguna compra; M2, el gasto en libras en esas semanas. Se ajustan con CUPED con las mismas cantidades de las 18 semanas anteriores al lanzamiento, y la prueba es una permutación estratificada de 2.000 asignaciones, a dos colas, con α = 0,05.
- **La calibración** (C07). En 500 sorteos nuevos del control, la prueba rechaza 4,8 % (M1) y 6,2 % (M2), dentro de la banda de 3,1 % a 6,9 %. La prueba normal sin ajustar rechaza 1,4 % y 9,4 % en los mismos sorteos, y por eso no se usa.
- **El A/A** (C08). Con el control sellado y sin ninguna oferta, la diferencia de M1 es de 0,27 puntos de semanas con compra (p = 0,294) y la de M2 es de −27,15 £ (p = 0,735): no se distingue de cero, como debe. Es un chequeo de cómo quedó armado el control y de la prueba, no un resultado.
- **El menor efecto detectable.** Con un control del 20 % (865 clientes), una operación de este tamaño vería una diferencia de al menos 0,76 puntos de semanas con compra o de 227,83 £ de gasto, con una potencia de 0,80; con el 10 % son 1,02 puntos y 303,62 £, y con el 30 %, 0,67 puntos y 198,84 £. Dice el tamaño que necesita una primera campaña; no es un resultado.
- **Lo que no se puede medir.** No se puede medir cuánto vende una oferta (no hay ninguna enviada) ni qué haría un grupo sin oferta (nadie quedó fuera de una campaña).

## Criterios y resultados

Criterios fijados antes de construir, con lo esperable escrito (requirements.md, 8.1): C01, C05, C06, C07 y C09 se esperaba que se cumplieran; C02 y C08 probablemente; C03, probablemente no; C04, incierto. De los nueve criterios con umbral **se cumplen ocho (C01, C02, C04, C05, C06, C07, C08 y C09) y no se cumple C03**, como se esperaba. C10 es informativo.

| Criterio | Umbral | Lo que prueba el umbral | Veredicto |
| --- | --- | --- | --- |
| C01 La lista supera a lo más vendido | límite inferior del intervalo del 95 % de hit@10(lista) − hit@10(B2) > 0,0 puntos | 23,1 puntos (límite inferior) | En 18 rondas semanales, la lista acertó al menos un producto en el 78,0 % de los clientes que compraron y lo más vendido (B2) en el 52,9 %; el límite inferior de la diferencia es 23,1 puntos y el umbral era 0,0 puntos. |
| C02 La lista no pierde más de 5 puntos frente a la recompra propia | límite inferior del intervalo del 95 % de hit@10(lista) − hit@10(B3) > −5,0 puntos | −1,9 puntos (límite inferior) | En 18 rondas semanales, la lista acertó al menos un producto en el 78,0 % de los clientes que compraron y la recompra propia (B3) en el 79,2 %; el límite inferior de la diferencia es −1,9 puntos y debía ser mayor que −5,0 puntos. |
| C03 La lista supera a la recompra propia | límite inferior del intervalo del 95 % de hit@10(lista) − hit@10(B3) > 0,0 puntos | −1,9 puntos (límite inferior) | En 18 rondas semanales, la lista acertó al menos un producto en el 78,0 % de los clientes que compraron y la recompra propia (B3) en el 79,2 %; el límite inferior de la diferencia es −1,9 puntos y debía ser mayor que 0,0 puntos. No se cumple. |
| C04 El modelo descubre mejor que lo más vendido | límite inferior del intervalo del 95 % de hit@10 solo nuevos(modelo elegido) − hit@10 solo nuevos(B2) > 0,0 puntos | 4,6 puntos (límite inferior) | Entre los productos que el cliente nunca había comprado, el modelo elegido acertó en el 33,8 % de los clientes que compraron y lo más vendido (B2) en el 28,1 %; el límite inferior de la diferencia es 4,6 puntos y debía ser mayor que 0,0 puntos. |
| C05 Cada cliente recibe su propia lista | cobertura media de las listas de la ronda ≥ 0,10 | 0,559 (cobertura media) | En 18 rondas, las listas de cada ronda cubrieron en promedio 0,559 de los productos con alguna compra en los 365 días anteriores; el umbral era 0,10. |
| C06 El grupo de control está equilibrado | mayor diferencia estandarizada absoluta de las cinco covariables ≤ 0,10 | 0,048 (mayor diferencia estandarizada absoluta) | Entre las cinco covariables de la cohorte del lanzamiento (4.326 clientes), la mayor diferencia estandarizada absoluta entre el grupo de oferta y el de control es 0,048 (el gasto del año); el máximo era 0,10. |
| C07 La prueba del experimento está calibrada | tasa de rechazo de la prueba preregistrada, en 500 sorteos nuevos del control, de M1 y de M2: las dos entre 3,1 % y 6,9 % | 4,8 % y 6,2 % (tasas de rechazo de M1 y de M2) | En 500 sorteos nuevos del grupo de control sobre el período de prueba, la prueba preregistrada rechazó 4,8 % de las veces para las semanas con compra (M1) y 6,2 % para el gasto (M2); las dos debían estar entre 3,1 % y 6,9 %. |
| C08 El A/A no marca una diferencia que no existe | con el control sellado, la prueba preregistrada de M1 y de M2 da, las dos, p ≥ 0,05 | p = 0,294 y p = 0,735 (M1 y M2) | Con el control sellado y sin ninguna oferta, la prueba preregistrada da p = 0,294 para las semanas con compra (M1) y p = 0,735 para el gasto (M2) en el período de prueba; los dos debían ser al menos 0,05. |
| C09 Lo entregado al CRM es lo decidido | el 100 % de las listas entregadas se lee de vuelta igual, ningún cliente del control llega al CRM ni al CSV y repetir la última ronda no crea ningún registro | 65.959 de 65.959 listas leídas de vuelta iguales; 0 del control en el CRM o en el CSV; 0 nuevas al repetir la última ronda | 65.959 de 65.959 listas entregadas se leyeron de vuelta del CRM iguales; 0 clientes del control llegaron al CRM y 0 a los archivos de correo; repetir la última ronda (R2011-12-05, 3.433 contactos) creó 0 registros nuevos; debían leerse todas iguales y no llegar ni crearse ninguno. |
| C10 Variantes y seguimiento (informativo) | sin umbral | sin umbral | Informativo: sin umbral. Las líneas base, el modelo elegido y la lista con hit@10, recall@10, precisión@10, NDCG@10 y cobertura, sin restricción y solo nuevos, por ronda y por segmento, las pruebas normales sin ajustar del A/A, el menor efecto detectable con 10, 20 y 30 % de control y la ronda censurada están en el resumen (17 variantes). |

Los intervalos del 95 % de los criterios que tienen uno, con los decimales del resumen (remuestreo por cliente, pareado, 2.000 remuestras):

- C01, intervalo del 95 %, 23,1 a 26,9 puntos de diferencia entre la lista y B2.
- C02, intervalo del 95 %, −1,9 a −0,4 puntos de diferencia entre la lista y B3.
- C03, intervalo del 95 %, −1,9 a −0,4 puntos: la misma diferencia, contra un umbral de 0; queda entero por debajo y por eso no se cumple.
- C04, intervalo del 95 %, 4,6 a 7,0 puntos de diferencia en productos nuevos entre el modelo elegido y B2; en la validación esa diferencia era de 3,8 puntos.

Lo que dice cada uno: C01 se esperaba y se cumplió con 25,1 puntos. C02 y C03 son la misma medida contra dos umbrales: la lista pierde 1,2 puntos frente a repetir lo que el cliente ya compra, dentro de lo tolerado y por debajo de lo que haría falta para superarlo. C04 salió mejor que en la validación.

**Un análisis posterior al sello** (`reports/post_seal_analysis.json`, atado a los bytes del sello; D49). No reemplaza ninguna cifra sellada. C05 como lo fija el preregistro, con los productos con alguna línea de compra en los 365 días anteriores como denominador, da 0,588 y se cumple; lo sellado, 0,559, cuenta los productos con alguna línea de canasta. Con la definición de la validación del plan (`p01`), la prueba da 0,153, comparable con su 0,158.

## Limitaciones

- **Un solo minorista, de 2009 a 2011.** Lo medido es la lista de una tienda en línea del Reino Unido con una fuerte parte de mayoristas; otro negocio, otro resultado. Los datos son reales, y por eso las cifras valen para ese archivo y no más.
- **Sin ofertas.** Nadie recibió una oferta ni quedó fuera de una campaña: no se mide cuánto vende una oferta, y el grupo de control queda listo, equilibrado y calibrado, sin un resultado que mostrar.
- **Sin categorías ni costos.** No hay categorías de producto, descuentos con contenido ni márgenes.
- **La recompra propia es la base que no se supera.** C03 no se cumple: con un 79,2 % de clientes que repiten algo que ya compraron, la mezcla con productos nuevos da 78,0 %. El valor de la lista está en los productos nuevos (C04) y en la cobertura, no en acertar más que repetir.
- **La tendencia de temporada.** La prueba cae entre agosto y noviembre y la validación entre mayo y julio; la mezcla sigue lo más vendido de cuatro semanas y no se separó cuánto de lo que acierta es temporada.
- **Los dos hallazgos de la corrida real** (L133), confirmados por la evaluación independiente (L136, B1 y B5) y corregidos sin tocar el sello; ninguno cambia un veredicto:
  - **Las listas de ejemplo de `algorithms.json` eran la lista de un cliente.** L133 contó 5, 5 y 6 clientes que habían comprado antes de la ventana los siete productos de recompra de cada una; la evaluación, dentro del perfil publicado, 5, 1 y 2, menos que el mínimo de 10 clientes de D30. Ahora cada una es la lista agregada de su perfil, rotulada, con cuántos clientes tienen cada producto y sin rangos (D46). La revisión nativa de U21 lo había anotado como advertencia (L134).
  - **C05 tiene otro denominador que el preregistrado, y la distancia con el 0,158 de la validación del plan es sobre todo el numerador.** Lo sellado, 0,559, cuenta los productos con alguna línea de canasta (compras de clientes e invitados) en los 365 días anteriores. El preregistro cuenta los productos con alguna línea de compra: con esa definición, la cobertura es 0,588 y se cumple igual. La validación del plan (`p01`) contó solo las listas de los clientes evaluados; con su definición, la prueba da 0,153. Las dos cifras se publican al lado del sello, como análisis posterior al sello (D49).
- **El sello guarda celdas de menos de 10 clientes.** Los tamaños de los 18 estratos del sorteo tienen 8 celdas de menos de 10 clientes; el sello es el registro de auditoría y no se reescribe, así que es la excepción con nombre de D30, y ningún otro archivo publicado muestra esos tamaños (D48).
- **El CRM es un sustituto local.** Se probó su forma, su idempotencia y su lectura de vuelta, pero nunca contra Mautic, HubSpot, Mailchimp ni otro; conectar uno real necesita su URL y sus claves.
- **Quien nunca compró no recibe lista.** Los compradores de una semana que no están en la base (primeras compras o clientes sin compras en el último año) se cuentan aparte en `round_ops` y ninguna lista los alcanza (plan, sección 7).

## Tiempos y memoria

Medidos en el equipo de desarrollo, sin GPU, en la corrida real, contra los límites de RNF02:

- Leer el libro y escribir las líneas canónicas: 37,7 s (límite 300 s).
- El lanzamiento, con la elección de las 48 recetas: 255 s, de los cuales el ajuste de la receta (`fit_recipe`) 176,8 s (límite 1.200 s).
- Cada ronda semanal: de 37 a 48 s, con 41,7 s de media (límite 60 s).
- El cierre, con el A/A y su calibración: 86 s (límite 300 s).
- La repetición completa: 1.094 s (límite 45 min). La prueba de Docker, con el DAG corrido dos veces en modo rápido: 80,1 s (límite 15 min).
- Memoria (RNF03): el pico de `PeakWorkingSetSize`, el conjunto de trabajo en Windows, fue de 2.056,5 MB, contra un límite de 6.144 MB de ese contador.

## La suite rápida

La suite rápida, la selección por defecto, recoge 1.253 pruebas y termina en 115,73 s y 113,60 s en dos corridas seguidas en reposo, medidas el 2026-11-20 con el código de las correcciones de la evaluación (las pruebas nuevas sumaron unos 6 s a los 108 s de U22), con un presupuesto de trabajo de 120 s, un límite de 180 s y un disparador de 100 s (RNF15, D31): pasa el presupuesto y el límite, y pasa el disparador de la unidad de velocidad. La unidad de velocidad (L131) la bajó de 112-117 s a unos 103 s sin quitar una prueba; lo que queda es plano: dos repeticiones completas que no se pueden saltar, unas 145 copias de estado de unos 120 archivos y unas 1.100 de ellas con menos de 0,2 s cada una. El margen no es estable: una unidad que sume pruebas debe volver a medirla. Que el presupuesto y el límite sean los de los proyectos 06 y 07 es una decisión que sigue abierta para el dueño (pendiente 13 del plan). Las pruebas con la fuente real (`real_data`) y con Docker (`docker`) no están en la selección por defecto.
