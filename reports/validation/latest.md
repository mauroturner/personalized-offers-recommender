# Validación de la entrega C2011-12-05

Corrida: 20261120T000628680396Z

| Regla | Nombre | Severidad | Alcance | Resultado | Líneas |
| --- | --- | --- | --- | --- | ---: |
| V10 | La entrega es la siguiente del plan | bloqueante | entrega | pasa | 0 |
| V11 | Filas y SHA-256 son los del manifiesto de la entrega | bloqueante | entrega | pasa | 0 |
| V12 | Toda línea tiene su fecha dentro del período de la entrega | bloqueante | entrega | pasa | 0 |
| V13 | Ninguna línea ya cargada ni repetida dentro de la entrega | bloqueante | entrega | pasa | 0 |
| V14 | Repeticiones internas, contadas (se conservan) | advertencia | línea | falla | 163 |
| V15 | Precio o cantidad en cero o negativos fuera de las anulaciones (se apartan) | advertencia | línea | falla | 36 |
| V16 | Descripción vacía (se conserva) | advertencia | línea | falla | 10 |
| V17 | Líneas por rol | informativa | entrega | pasa | 0 |
| V18 | Clientes y productos nuevos de la entrega | informativa | entrega | pasa | 0 |
