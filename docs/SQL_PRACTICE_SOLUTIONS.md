# Soluciones comentadas

El SQL está en [`sql_practice_solutions.sql`](sql_practice_solutions.sql), una solución por bloque
`-- [N]`, contra el **esquema real** (`onchain.raw_swaps`, `onchain.swaps_daily`,
`onchain_dbt.stg_swaps`, `onchain_dbt.fct_pool_daily`). Las 23 sentencias se ejecutan con
`scripts/check_sql_practice.py`, que solo admite lecturas. Aquí va lo que hay que saber decir de
cada una, y la diferencia con Postgres donde la hay. Los números de ejemplo de los ejercicios 7 a
14 son de una primera pasada con tres días de datos; los del 16 y el 17, de la tabla completa.

## 1. Calentamiento

`count()` sin argumento es lo idiomático (en Postgres, `count(*)`). Se puede
ordenar y agrupar por alias: `ORDER BY swaps`. ClickHouse resuelve alias del
`SELECT` en casi cualquier cláusula, incluido `WHERE`, cosa que Postgres no permite.

## 2. Volumen diario por pool

(a) Desde el mart es un `SELECT` sin JOIN ni agregación: `pool_label` y `fee` están
**denormalizados** en `fct_pool_daily` a propósito. (b) Desde `stg_swaps` hay que unir con
`dim_pools` y agregar 881.187 filas. Dan lo mismo (hay un test de dbt que lo exige). Lo que se
intercambia: el mart responde al instante y se lee solo, pero su etiqueta es tan fresca como el
último `dbt build`; el staging es siempre actual y recalcula todo en cada consulta, porque es una
vista.

El JOIN contra `dim_pools` (4 filas) es gratis: ClickHouse carga el lado derecho en una tabla hash
en memoria. Por eso la tabla pequeña va **a la derecha**.

`volume_usd` y `amount0` son `Decimal(76, 18)` exactos. Para un volumen agregado un double
sobraría, pero **para reconciliar no**: por eso el proyecto escala con Decimal y la comprobación
interna se hace en enteros crudos.

## 3. Tramos de 4 horas

`toStartOfInterval(ts, INTERVAL 4 HOUR)`. Hay atajos (`toStartOfHour`,
`toStartOfFifteenMinutes`, `toStartOfDay`), pero esta es la general. En Postgres:
`date_bin('4 hours', ts, origen)` o `date_trunc`. Los tramos se alinean con la
medianoche UTC (04:00, 08:00…), no con el primer dato.

## 4. Compras y ventas en una pasada

Combinador `-If`: `countIf(cond)`, `sumIf(x, cond)`. Cualquier función de
agregación admite el sufijo. Equivale al `count(*) FILTER (WHERE cond)` de Postgres.
Otros combinadores que conviene conocer: `-Array`, `-State` / `-Merge` (para
vistas materializadas con `AggregatingMergeTree`), `-OrNull`.

`any(p.decimals0)`: ClickHouse exige que lo que no está en el `GROUP BY` vaya en
una agregación; `any` coge un valor cualquiera del grupo, y aquí todos son iguales.

## 5. Precio de cierre diario

`argMax(valor, clave)`: el `valor` de la fila donde `clave` es máxima. La clave es
una **tupla** `(block_number, log_index)` porque el timestamp no desempata: todos
los swaps de un bloque comparten timestamp, y en un bloque hay hasta decenas. Las
tuplas se comparan lexicográficamente.

En Postgres esto es `DISTINCT ON (dia) ... ORDER BY dia, block_number DESC` o una
ventana con `row_number()`. `argMax` es una pasada y sin ordenar.

El `WITH expr AS nombre` de ClickHouse define un **alias de expresión**, no una
CTE: se sustituye en cada uso. También existen las CTE normales (`WITH nombre AS (SELECT…)`).

## 6. Velas horarias

`argMin` para la apertura, `argMax` para el cierre, `max` / `min` para los extremos.
Misma idea que el 5. Es el ejemplo clásico: si te piden OHLC, no pienses en ventanas.

## 7. Cuantiles

`quantiles(0.5, 0.9, 0.99)(x)` devuelve un array con los tres en una pasada: es una
función **paramétrica**, con dos pares de paréntesis (parámetros y argumentos).

`quantile` es **aproximado** (muestreo con reservorio) y no determinista entre
ejecuciones; por eso la mediana sale 835,73 frente a 870,29 de `quantileExact`.
Variantes: `quantileExact` (exacto, memoria O(n)), `quantileTDigest`,
`quantileTiming`. En Postgres solo existe el exacto: `percentile_cont(0.5) WITHIN GROUP (ORDER BY x)`.
En una entrevista: decir que es aproximado **antes** de que te lo pregunten.

## 8. Top 3 por grupo

`ORDER BY ... LIMIT 3 BY pool, dia`. `LIMIT n BY` se queda con las n primeras filas
de cada combinación, según el `ORDER BY`. En Postgres hace falta
`row_number() OVER (PARTITION BY ...)` y filtrar en una subconsulta, o un `LATERAL`.

No confundir con `LIMIT n` (global) ni con `LIMIT n, m` (offset).

## 9. Acumulado y cuota

Funciones de ventana estándar: `sum(x) OVER (PARTITION BY label ORDER BY dia)` para
el acumulado y `sum(x) OVER (PARTITION BY dia)` para el total del día. Con `ORDER BY`
el marco por defecto es "desde el principio hasta la fila actual", igual que en
Postgres.

Se agrega primero en una subconsulta y se aplica la ventana después: mezclar
`GROUP BY` y ventanas en el mismo nivel funciona, pero se lee peor.

## 10. Saltos entre swaps consecutivos

`lagInFrame(x)` es la función clásica de ClickHouse: respeta el **marco** de la
ventana, así que hay que dárselo (`ROWS BETWEEN 1 PRECEDING AND CURRENT ROW`).
Comprobado en la 26.3.33.24: también existe ya `lag(x) OVER (ORDER BY …)`, sin
marco, como en Postgres. Mucho material que encontrarás dice que no existe: era
cierto en versiones antiguas.

**El tropiezo:** ninguna de las dos devuelve `NULL` en la primera fila. Devuelven el
valor por defecto del tipo, `0` (comprobado con las dos). Dividir por él da `inf`, y
ese `inf` encabeza el ranking. Tres salidas:

- filtrar en una capa exterior, `WHERE usd_anterior > 0` (la solución del fichero);
- `QUALIFY usd_anterior > 0` en el mismo nivel: `QUALIFY` existe en la 26.3
  (comprobado) y filtra por el resultado de una ventana, cosa que Postgres no tiene;
- hacer el argumento `Nullable`: `lagInFrame(toNullable(usd))` sí devuelve `NULL`
  en la primera fila (comprobado).

El resultado es curioso por sí mismo: los dos mayores saltos (−264 y +258 puntos
básicos) están en el mismo segundo, uno de ida y otro de vuelta. Tiene toda la
pinta de un sándwich, aunque con estos datos no se puede afirmar.

## 11. Horas sin actividad

`ORDER BY hora WITH FILL STEP toIntervalHour(1)`. `WITH FILL` rellena los huecos de
la columna ordenada; las demás columnas toman su valor por defecto (0). En Postgres:
`generate_series` y `LEFT JOIN`.

**El tropiezo (me pasó a mí):** `FROM` y `TO` tienen que ser **constantes**. Una
subconsulta escalar (`FROM (SELECT min(...))`) da *"Sort FILL FROM expression must
be constant"*. Sin `FROM` / `TO` rellena solo entre el primer y el último valor
presentes. Si necesitas un rango fijo, escribe las fechas literales o pásalas como
parámetro.

## 12. Transacciones multi-pool

`groupUniqArray(x)` agrega valores distintos en un array; `length`, `arraySort` y
`arrayStringConcat` lo manipulan. En Postgres: `array_agg(DISTINCT x)`.

`arrayJoin(arr)` hace lo contrario: **desdobla** un array en filas (el `unnest` de
Postgres). Peculiaridad: es una función en el `SELECT` que multiplica las filas de
toda la consulta. En 12b aparece solo para practicarlo; la agrupación por `ruta` no
lo necesita.

El resultado: 9.408 transacciones (de ~100.000 swaps) tocan **los dos fee tiers de
USDC/WETH a la vez**. Son arbitrajes entre tiers y routers que parten la orden. Es
la respuesta a "por qué añadir el cuarto pool".

## 13. ASOF JOIN

Une cada fila de la izquierda con la fila de la derecha **más cercana** que cumpla
la desigualdad: aquí, el último precio del pool 0.01% en ese instante o antes. En
Postgres es un `LATERAL (… ORDER BY ts DESC LIMIT 1)`, mucho más caro.

**El tropiezo (me pasó a mí):** ASOF exige **al menos una columna de igualdad**
además de la desigualdad: *"ASOF join with hash algorithm needs at least one
equi-join column"*. Si no hay ninguna natural, se inventa una constante **en los dos
lados** (`SELECT 1 AS k`) y se une por `a.k = b.k AND a.ts >= b.ts`. Solo se admite
**una** condición de desigualdad, y tiene que ser la última.

Resultado: diferencia media de 3,9 puntos básicos y p99 de 17,9. Coherente con que
entre una comisión de 1 pb y otra de 5 pb el arbitraje no cierre huecos menores.

## 14. El LEFT JOIN que no da NULL

Por defecto (`join_use_nulls = 0`) las filas sin pareja **no** traen `NULL`: traen
el valor por defecto del tipo (`''`, `0`, `1970-01-01`). Consecuencias en el
ejemplo, para wstETH/USDC 0.3%, que no tuvo swaps en esa media hora:

- `count()` da 1, no 0: cuenta la fila "vacía".
- `uniq(sender)` da 1: la cadena vacía cuenta como un sender.

Arreglos: (a) `SETTINGS join_use_nulls = 1` y contar con `countIf(x IS NOT NULL)`,
que es la solución 14b; (b) dejar el ajuste y contar `countIf(s.tx_hash != '')`.
El motivo del diseño: las columnas `Nullable` cuestan (un mapa de nulos aparte) y
ClickHouse las evita salvo que se las pidas.

De paso: `uniq` es aproximado (HyperLogLog-like, ~1-2 % de error), `uniqExact` no.
`count(DISTINCT x)` equivale a `uniqExact` por defecto (ajuste `count_distinct_implementation`).
Con pocos valores coinciden, como aquí.

## 15. ¿Cuánto ha leído mi consulta?

(a) `EXPLAIN indexes = 1 SELECT …` muestra, por cada parte, cuántos gránulos
sobreviven al índice primario: `Granules: 1/14`. Es la forma de **demostrar** que un
`ORDER BY` sirve para una consulta sin ejecutarla. Otras variantes útiles:
`EXPLAIN PIPELINE`, `EXPLAIN PLAN actions = 1`, `EXPLAIN ESTIMATE`.

(b) `system.query_log`: `query_duration_ms`, `read_rows`, `read_bytes`,
`memory_usage`. Se escribe cada ~7,5 s; `SYSTEM FLUSH LOGS` lo fuerza. Filtrar por
`type = 'QueryFinish'` (cada consulta tiene también una fila `QueryStart`).

En Postgres el equivalente es `EXPLAIN (ANALYZE, BUFFERS)` y `pg_stat_statements`.
La diferencia de fondo: en Postgres miras si usó el índice; en ClickHouse miras
**cuántos gránulos leyó**, porque el índice siempre "se usa" y lo que cambia es
cuánto descarta.

## 16. La materialized view por dentro

Resultado real: el destino tiene **136 filas**, la vista da **124 pool-días**, que son los que hay
en `raw_swaps`, y los swaps suman **881.187** por los dos caminos.

El destino es un `AggregatingMergeTree`: cada INSERT en `raw_swaps` dispara la vista y añade al
destino **una fila por cada (pool, día) presente en ese bloque insertado**. Las filas con la misma
clave se funden (sumando, por `SimpleAggregateFunction(sum)`) cuando las partes se mezclan, que es
eventual. Hasta entonces hay varias filas por clave: 136 en vez de 124. La suma cuadra igual porque
sumar es asociativo; lo que no cuadraría es un `count()` o leer una fila suelta. Por eso existe
`swaps_daily`, que hace `GROUP BY` + `sum()` al leer, y por eso nadie lee el destino directamente.

La pregunta de entrevista que viene detrás: *"¿y si creas la MV sobre una tabla que ya tiene
datos?"* El destino queda **vacío**: una MV de ClickHouse es un disparador de INSERT, no una
consulta guardada (`docs/MATERIALIZED_VIEW.md`).

## 17. Buscar por hash en una columna binaria

`tx_hash` es `FixedString(32)`: si te dan `0xabc…` en texto, el filtro es
`WHERE tx_hash = unhex('abc…')` (sin el `0x`). Comparar contra el texto no da error: no casa nada.
La solución evita escribir un hash a mano tomándolo de una subconsulta.

Lee **toda la tabla** (881.187 filas): `tx_hash` no está en la clave de ordenación ni en ningún
índice. En `docs/QUERY_PERFORMANCE.md` está medido qué cambia con un índice `bloom_filter`
(8.192 filas, 1,4 % más de disco) y cómo la caché de condiciones de consulta disimula el problema a
partir de la segunda ejecución del **mismo** hash.

## Diferencias con Postgres que hacen tropezar, en una lista

1. **No hay transacciones ni `UPDATE` / `DELETE` baratos.** Son mutaciones
   asíncronas que reescriben partes.
2. **La clave primaria no es única.** Dos filas con la misma clave conviven.
3. **`LEFT JOIN` rellena con valores por defecto**, no con `NULL` (ejercicio 14).
4. **`lag` / `lagInFrame` devuelven 0, no `NULL`**, en la primera fila, salvo con argumento `Nullable` (ejercicio 10).
5. **`quantile` y `uniq` son aproximados** (7 y 14).
6. **División de enteros:** `7 / 2` da `3.5` (Float64), no `3`. Para la entera,
   `intDiv(7, 2)`. En Postgres es al revés.
7. **Los nombres de función distinguen mayúsculas**: `toDate`, no `todate`.
   Las palabras clave, no.
8. **Desbordamiento silencioso:** sumar `UInt32` puede dar la vuelta sin error. Las
   sumas promocionan el tipo (`sum` de `UInt32` es `UInt64`), las multiplicaciones
   entre columnas no siempre.
9. **Tablas pequeñas a la derecha** del `JOIN`.
10. **`WITH x AS nombre` es un alias de expresión**; la CTE es `WITH nombre AS (SELECT…)`.
