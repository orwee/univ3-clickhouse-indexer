# Experimentos de esquema con datos reales (sin concluir)

Mediciones para que Roberto decida el esquema. **Este documento no elige nada.**
Complementa a `SCHEMA_OPTIONS.md` (que razona) con números medidos. Las decisiones
van a `DECISIONS.md`, escritas por él.

## Actualización: los 30 días completos (863.587 swaps)

Repetido el 2026-09-19 con el backfill terminado: 216 ficheros, bloques 25.794.751 a
26.010.750, **863.587 swaps**. Mismo script, misma versión, caché de condiciones
apagada y encendida. Resultado bruto en `docs/experiments/schema-2026-09-19-30d.json`.
El resto del documento describe la primera pasada, con el 52 % de los datos; se deja
tal cual porque el método y las explicaciones son los mismos. **Ninguna observación
cambia de signo; las diferencias crecen con los datos.**

Reparto: USDC/WETH 0.01% 630.611 (73,0 %) · USDC/WETH 0.05% 227.678 (26,4 %) ·
wstETH/USDC 0.05% 4.688 (0,5 %) · wstETH/USDC 0.3% 610 (0,07 %).

| Observación | Primera pasada (463.447) | 30 días (863.587) |
|---|---|---|
| Replacing con clave no única: filas perdidas | 65,7 % | **64,4 %** (quedan 307.720) |
| Replacing sin `FINAL` ni merge: total inflado | 11,2 % | **10,5 %** (954.496 en vez de 863.587) |
| `FINAL` sin mergear, consulta principal | 69 ms frente a 23 (3,0×) | **114 ms frente a 41 (2,8×)**, 45 MB de memoria frente a 9 |
| `FINAL` sin mergear, un día de un pool | lee la tabla entera | lee la tabla entera (954.496 filas, 116 ms frente a 21) |
| Un día del pool grande, `(pool, timestamp)` | 32.768 filas · 4/57 gránulos | **32.768 filas · 4/106 gránulos** |
| Un día del pool grande, `(pool, block_number, log_index)` | 348.759 filas · 43/57 | **634.211 filas · 78/106** (19 veces más) |
| …la misma, con la caché de condiciones encendida | 49.152 | 49.152 |
| Un día del pool pequeño, claves con `pool` delante | 8.192 filas · 1 gránulo | 8.192 filas · 1 gránulo |
| Un día del pool pequeño, `(timestamp, pool)` | 49.152 filas | 49.152 filas |
| Un día, todos los pools: `(pool, ts)` / `(ts, pool)` / `(pool, block, log)` | 65.536 / 49.152 / 463.447 | 65.536 / 49.152 / **863.587** |
| Partición mensual frente a ninguna: filas leídas | idénticas | **idénticas** (poda 1 de 2 partes; el índice ya las descartaba) |
| Consulta principal, cualquier clave | tabla entera, 19 a 23 ms | tabla entera, **34 a 42 ms** |
| `tx_hash` en hex: parte del disco | 52,9 % | **53,0 %** (55,8 de 105,2 MB) |
| Tamaño de tabla con hashes en texto | 56,9 MB · 123 B/fila | **105,2 MB · 122 B/fila** |

Lo que se lee de la tabla, sin valorarlo: lo que lee una consulta bien servida por la
clave **no crece** con la tabla (32.768 filas con el doble de datos), y lo que lee una mal
servida crece en proporción (de 348.759 a 634.211).

### La tabla real, con los tipos decididos

Tras estos experimentos se decidió el esquema (DECISIONS.md #10 a #14) y se cargó
`onchain.raw_swaps`. Medido sobre esa tabla, con `tx_hash`, `sender` y `recipient` en
binario (`FixedString`):

| | Hashes en texto (candidata) | Hashes en binario (tabla real) |
|---|---|---|
| Comprimido | 105,2 MB | **73,2 MB (−30 %)** |
| Bytes por fila | 122 | **84,8** |
| `tx_hash` | 55,8 MB · 53,0 % | **26,2 MB · 35,7 %** |
| `sender` + `recipient` | 12,5 MB | 8,0 MB |
| Particiones / partes tras la carga | | 2 particiones, 5 partes (9 inserts) |

`tx_hash` sigue siendo la columna mayor incluso en binario: es aleatorio y no comprime
(ratio 1,0). Los tres enteros de 256 bits suman el 38,6 % de la tabla real.

---

## Qué se midió y con qué

- **Datos:** los primeros 113 ficheros de la zona de aterrizaje del backfill real,
  bloques 25.794.751 a 25.907.750 (20 de agosto a 4 de septiembre de 2026):
  **463.447 swaps**, el 52 % de la ventana de 30 días. El backfill seguía en marcha.
- **Servidor:** ClickHouse 26.3.33.24, el contenedor del repo (3 GiB, sin swap).
- **Reparto por pool:** USDC/WETH 0.01% 345.451 (74,5 %) · USDC/WETH 0.05% 115.418
  (24,9 %) · wstETH/USDC 0.05% 2.456 (0,5 %) · wstETH/USDC 0.3% 122 (0,03 %).
- **Método:** `scripts/schema_experiments.py`. Crea la base `test_schema_exp`, carga
  las mismas filas en cada tabla candidata (un `INSERT` por fichero, como haría un
  cargador real), mide, y **borra la base al terminar**. Resultado bruto en
  `docs/experiments/schema-2026-09-19.json`.
- **De dónde sale cada número:** filas y bytes leídos, de `system.query_log`;
  gránulos y partes que sobreviven, de `EXPLAIN indexes = 1`; tamaños y partes, de
  `system.parts` y `system.parts_columns`. Tiempos: mediana de 5 ejecuciones.

Columnas de todas las tablas (ilustrativas, no una propuesta de nombres):
`pool LowCardinality(String)`, `block_number UInt32`, `block_timestamp DateTime('UTC')`,
`log_index UInt32`, `tx_hash / sender / recipient String`, `amount0 / amount1 Int256`,
`sqrt_price_x96 UInt256`, `liquidity UInt128`, `tick Int32`.

### Reproducir

```
PYTHONPATH=src uv run python scripts/schema_experiments.py \
    --landing /var/lib/univ3-indexer/landing > resultados.json
```

Sin `--max-files` usa todo lo aterrizado: cuando acabe el backfill conviene repetirlo
con los 30 días completos. No necesita API keys ni red, solo ClickHouse. Tarda ~1 min.

### Dos avisos sobre cómo leer los números

1. **A este tamaño los tiempos no distinguen nada.** Todas las consultas tardan entre
   3 y 25 ms; las diferencias de 1 o 2 ms son ruido. Lo que sí discrimina es **cuántas
   filas y bytes se leen**, que es lo que escalaría con más datos. Leer los tiempos como
   "todo va sobrado", no como un ranking.
2. **La caché de condiciones de consulta engaña al medir.** Me pasó: la primera pasada
   daba, para una misma consulta, 43 de 57 gránulos según `EXPLAIN` pero solo 49.152
   filas leídas según `query_log`. La causa es `use_query_condition_cache = 1` (por
   defecto en esta versión): ClickHouse recuerda, por filtro, qué gránulos no tenían
   filas que casaran, y desde la segunda ejecución se los salta. Eso **tapa justo la
   diferencia entre claves de ordenación** que se quiere medir. Por eso las tablas de
   abajo dan las dos cifras: con la caché apagada (lo que poda el `ORDER BY` por sí
   solo) y con ella encendida (lo que verá el uso real en consultas repetidas).

## 1. Ida y vuelta de tipos con clickhouse-connect

Se insertaron los valores extremos reales de una muestra (los tres primeros ficheros,
~14.000 swaps) más los límites de cada tipo, y se leyeron de tres formas: como valor Python por el driver, como texto (`toString`) en
el servidor, y byte a byte (`hex(reinterpretAsFixedString(amount1))`, 32 bytes en
little-endian reconstruidos en Python).

| Valor | Bits | Driver exacto | Texto exacto | Bit a bit |
|---|---|---|---|---|
| amount1 máximo real: 635.972.951.593.090.648.054 (≈ 636 WETH) | 70 | sí | sí | sí |
| amount1 mínimo real: −633.544.440.917.790.349.267 | 70 | sí | sí | sí |
| amount0 máximo / mínimo reales (wstETH, ±1,3e17) | 57 | sí | sí | sí |
| sqrt_price_x96 máximo real (1,71e33) | 111 | sí | sí | sí |
| liquidity máxima real (3,3e20) | 69 | sí | sí | sí |
| tick mínimo / máximo reales: −196.981 / +199.650 | 18 | sí | sí | sí |
| Límites: Int256 mín. y máx., UInt256 máx., UInt128 máx., Int32 mín. | 256 | sí | sí | sí |

- **Sin sorpresas en los enteros grandes.** `Int256`, `UInt256` y `UInt128` entran y
  salen como `int` de Python, sin pasar por float, en todo el rango del tipo.
- **`JSONEachRow` con los enteros como cadena funciona** (`"amount1": "-6335…"` entra en
  una columna `Int256` exacto). Es el formato de la zona de aterrizaje, así que un
  cargador puede enviar los ficheros casi tal cual.
- **Sorpresa menor del driver:** una columna `DateTime('UTC')` vuelve como `datetime`
  **sin zona horaria** (`tzinfo=None`). El instante es correcto, pero es un `datetime`
  ingenuo: compararlo con uno consciente de zona lanza `TypeError` en Python.
- **El dato que ha crecido:** ayer el máximo visto eran 66 bits (50,8 WETH). Recorriendo
  todo lo aterrizado hasta el momento (525.295 swaps, 129 ficheros) el mayor `amount1`
  es de **1.136 WETH, 70 bits**: `Int64` se queda corto por un factor de 123. Otros
  extremos de ese recorrido: `amount0` 61 bits, `sqrt_price_x96` 111, `liquidity` 69,
  tick de −203.307 a +206.590, `log_index` hasta 10.500 (no cabe en `UInt8`; sí en
  `UInt16`, por poco margen de costumbre: mejor `UInt32`). Todos caben en los tipos
  probados, cuyo rango completo está verificado en la última fila de la tabla.
- **Lo que pasa si se cuela un Float64:** `toInt256(toFloat64(amount1))` sobre el mínimo
  real devuelve −633.544.440.917.790.**294.046**: se pierden 55.221 wei. No da error.

## 2. Tablas candidatas

Cada comparación cambia **una sola cosa**.

| Tabla | Motor | ORDER BY | PARTITION BY |
|---|---|---|---|
| `mt_pool_ts` (base) | MergeTree | (pool, block_timestamp) | ninguna |
| `mt_ts_pool` | MergeTree | **(block_timestamp, pool)** | ninguna |
| `mt_pool_block_log` | MergeTree | **(pool, block_number, log_index)** | ninguna |
| `rmt_pool_block_log` | **ReplacingMergeTree** | (pool, block_number, log_index) | ninguna |
| `mt_pool_ts_monthly` | MergeTree | (pool, block_timestamp) | **toYYYYMM(block_timestamp)** |

Pares a comparar: ORDER BY → las tres primeras entre sí. Motor → `mt_pool_block_log`
frente a `rmt_pool_block_log`. Partición → `mt_pool_ts` frente a `mt_pool_ts_monthly`.

Las consultas:

- **Q1, la principal:** volumen diario por pool, sobre toda la tabla.
- **Q2-grande:** un pool y un día (2026-08-21), para USDC/WETH 0.01% (74,5 % de las filas).
- **Q2-pequeño:** lo mismo para wstETH/USDC 0.3% (122 filas en total).
- **Q3:** todos los pools en ese día (filtro solo por fecha).

### 2.1 Almacenamiento

Tras `OPTIMIZE ... FINAL` (una parte por partición):

| Tabla | Partes antes → después | Comprimido | Sin comprimir | Índice primario en memoria | Marcas |
|---|---|---|---|---|---|
| mt_pool_ts | 113 → 1 | 56,87 MB | 140,4 MB | 448 B | 58 |
| mt_ts_pool | 113 → 1 | 56,39 MB | 140,4 MB | 232 B | 58 |
| mt_pool_block_log | 113 → 1 | 56,87 MB | 140,4 MB | 448 B | 58 |
| rmt_pool_block_log | 125 → 1 | 56,87 MB | 140,4 MB | 448 B | 58 |
| mt_pool_ts_monthly | 114 → 2 | 56,87 MB | 140,4 MB | 616 B | 60 |

- ~123 bytes por fila comprimida, ~303 sin comprimir. Extrapolado a 30 días (~881.000
  filas): **~108 MB** en disco. La zona de aterrizaje JSONL ocupa ~12 veces más.
- **El ORDER BY casi no cambia el tamaño** (menos de un 1 %). El índice primario ocupa
  cientos de bytes en todos los casos: a esta escala no es un criterio.
- "Antes" es una parte por `INSERT` porque los merges se pararon a propósito durante la
  carga (`SYSTEM STOP MERGES`), para que la cifra sea determinista. La tabla mensual
  tiene una más porque un fichero cruzaba de agosto a septiembre: **un insert que toca
  dos particiones crea dos partes.**

Por columna, en `mt_pool_ts`:

| Columna | Comprimido | % del total | Ratio |
|---|---|---|---|
| tx_hash | 30,11 MB | **52,9 %** | 1,1× |
| sqrt_price_x96 (UInt256) | 7,36 MB | 12,9 % | 2,0× |
| amount1 (Int256) | 5,23 MB | 9,2 % | 2,8× |
| recipient | 4,11 MB | 7,2 % | 5,6× |
| amount0 (Int256) | 3,46 MB | 6,1 % | 4,3× |
| sender | 2,73 MB | 4,8 % | 8,5× |
| log_index | 1,33 MB | 2,3 % | 1,4× |
| tick | 0,88 MB | 1,6 % | 2,1× |
| block_timestamp | 0,68 MB | 1,2 % | 2,7× |
| block_number | 0,67 MB | 1,2 % | 2,8× |
| liquidity (UInt128) | 0,31 MB | 0,5 % | 24,1× |
| pool (LowCardinality) | 0,002 MB | 0,0 % | 189× |

- **Más de la mitad del disco es `tx_hash`**, que al ser aleatorio no comprime (1,1×).
  Guardarlo como `FixedString(32)` binario lo dejaría en torno a la mitad: es, con
  diferencia, la decisión de tipos que más bytes mueve.
- **Los tres campos de 256 bits juntos son el 28 %.** `Int256` cuesta 32 bytes sin
  comprimir por valor, pero comprime 2,8 a 4,3×: `amount0` y `amount1` acaban en ~7 y
  ~11 bytes por fila. `sqrt_price_x96` comprime peor (2,0×) porque cambia en cada swap.
- `sender` comprime 8,5× siendo `String` (pocos routers repetidos); `recipient`, 5,6×.
- `pool` como `LowCardinality` ocupa 2,4 KB en total.

### 2.2 Lo que lee cada ORDER BY

Filas leídas con la caché de condiciones **apagada** (entre paréntesis, encendida), y
gránulos que sobreviven al índice primario sobre 57:

| Consulta | (pool, timestamp) | (timestamp, pool) | (pool, block_number, log_index) |
|---|---|---|---|
| Q1 principal, toda la tabla | 463.447 · 57/57 · 19 ms | 463.447 · 57/57 · 21 ms | 463.447 · 57/57 · 23 ms |
| Q2-grande (74,5 % de las filas) | **32.768** · 4/57 | 49.152 · 6/57 | **348.759** (49.152) · 43/57 |
| Q2-pequeño (122 filas) | **8.192** · 1/57 | 49.152 · 6/57 | **8.192** · 1/57 |
| Q3 un día, todos los pools | 65.536 · 8/57 | **49.152** · 6/57 | **463.447** (57.344) · 57/57 |

Lo que se observa, sin valorarlo:

- **La consulta principal lee la tabla entera con cualquier clave.** Agrupa todos los
  pools y todos los días: no hay nada que podar. El `ORDER BY` no le afecta (19 a 23 ms,
  17 MB leídos). Las claves solo se diferencian en las consultas **con filtro**.
- **`(pool, timestamp)`:** con el filtro de pool y fecha lee 4 gránulos para el pool
  grande y 1 para el pequeño. Filtrando **solo por fecha** (Q3) sigue podando (8/57)
  aunque la fecha sea la segunda columna de la clave: con solo 4 valores distintos en la
  primera, el índice puede saltar dentro de cada uno.
- **`(timestamp, pool)`:** lee siempre los 6 gránulos del día, **sea cual sea el pool**.
  Para el pool pequeño eso son 49.152 filas para encontrar unas pocas: 6 veces más que
  con el pool delante. Para el grande, 1,5 veces más. Es la mejor para Q3.
- **`(pool, block_number, log_index)`:** el filtro por fecha **no usa el índice**, porque
  la fecha no está en la clave. Para el pool grande lee sus 43 gránulos completos
  (348.759 filas, 10,6 veces más que con el timestamp en la clave) y para Q3, la tabla
  entera. Para el pool pequeño da igual: cabe en un gránulo.
- **El efecto del sesgo, medido:** poner `pool` delante le ahorra al pool pequeño casi
  todo (1 gránulo de 57) y al grande casi nada por sí solo (43 de 57): al grande lo que
  le poda es la **segunda** columna de la clave.
- **La caché de condiciones tapa el problema de la tercera clave** en consultas
  repetidas (348.759 → 49.152 filas), pero no en la primera ejecución de cada filtro, ni
  con `FINAL` (ver 2.4).

### 2.3 Partición mensual frente a ninguna

Misma clave `(pool, timestamp)`; los datos cruzan de agosto a septiembre.

| | Sin partición | Mensual |
|---|---|---|
| Partes tras optimizar | 1 | 2 (una por mes) |
| Q1 principal | 463.447 filas · 19 ms | 463.447 filas · 21 ms |
| Q2-grande | 32.768 filas · 4/57 gránulos · 1/1 partes | 32.768 filas · 4/43 gránulos · **1/2** partes |
| Q2-pequeño | 8.192 filas | 8.192 filas |
| Q3 | 65.536 filas | 65.536 filas |
| Índice primario en memoria | 448 B | 616 B |

- La poda por partición **ocurre** (descarta la parte de septiembre: 1 de 2), pero las
  filas leídas son **idénticas**: el índice primario ya descartaba esos gránulos.
- Lo que añade es una parte más, y una parte extra por cada insert que cruce de mes.
- Lo que no se ha medido aquí, porque no es una consulta: la partición mensual permite
  `DROP` / `REPLACE PARTITION` de un mes entero.

### 2.4 MergeTree frente a ReplacingMergeTree

Misma clave `(pool, block_number, log_index)`, que es única por log. A la tabla
Replacing se le reentregó uno de cada diez ficheros (51.883 filas repetidas), simulando
lo que hace el ejecutor del backfill si muere entre el sink y el checkpoint.

**Antes del merge** (merges parados; 125 partes):

| | `count()` | Q1 principal | Q2-grande |
|---|---|---|---|
| Sin `FINAL` | **515.330** (un 11,2 % de más) | 23 ms · 515.330 filas · 19 MB | 13 ms · 515.330 filas |
| Con `FINAL` | 463.447 (correcto) | **69 ms** · 515.330 filas · 23 MB · 16 MB de memoria | **67 ms** · 515.330 filas · 23 MB |

**Después del merge** (`OPTIMIZE ... FINAL`; 1 parte; 463.447 filas):

| | Q1 principal | Q2-grande | Q2-pequeño |
|---|---|---|---|
| MergeTree, sin `FINAL` | 23 ms · 17,2 MB | 4 ms · 348.759 filas · **2,5 MB** | 3 ms · 0,04 MB |
| Replacing, sin `FINAL` | 25 ms · 17,2 MB | 6 ms · 348.759 filas · 2,5 MB | 3 ms · 0,04 MB |
| Replacing, con `FINAL` | 22 ms · 17,2 MB | 7 ms · 348.759 filas · **12,9 MB** | 3 ms · 0,30 MB |

- **Sin `FINAL` y sin merge, el total sale inflado un 11,2 % y nada avisa.** Es el
  escenario del que habla `SCHEMA_OPTIONS.md`, ahora con cifra.
- **`FINAL` con muchas partes pequeñas cuesta 3 veces más** en la consulta principal
  (69 frente a 23 ms) y **anula la poda**: la consulta de un día lee la tabla entera
  (67 ms frente a 13). En absoluto siguen siendo milisegundos.
- **Con la tabla ya mergeada, `FINAL` es casi gratis en tiempo** (22 frente a 25 ms),
  pero lee **5 veces más bytes** en la consulta filtrada (12,9 frente a 2,5 MB). Mi
  explicación, no comprobada: con `FINAL` el filtro no se adelanta a la lectura
  (`PREWHERE`) y la caché de condiciones no actúa, así que se leen las columnas completas
  de todos los gránulos candidatos.
- Una vez mergeadas, las dos tablas ocupan exactamente lo mismo (56,87 MB).
- **En la primera prueba, con merges activos, los duplicados desaparecieron solos en
  menos de 3 segundos**: "eventual" puede ser muy rápido con tablas pequeñas. Pero no
  está garantizado, y por eso aquí se pararon los merges para medirlo.

### 2.5 Una trampa, medida

`ReplacingMergeTree` con `ORDER BY (pool, block_timestamp)`, una clave que **no es
única por swap** (todos los swaps de un pool en un bloque comparten timestamp):

| Filas cargadas | Filas en la tabla | Perdidas |
|---|---|---|
| 463.447 | **159.151** | **304.296 (65,7 %)** |

Sin error ni aviso. Y no es "eventual": la pérdida ya estaba **antes de cualquier
merge** (159.151 filas con los merges parados), porque el motor colapsa las claves
repetidas dentro de cada bloque insertado. Con Replacing, la clave de ordenación tiene
que ser la identidad de la fila; `(pool, block_number, log_index)` lo es.

## 3. Ajustes comprobados en esta versión

Varios puntos marcados **verificar** en `SCHEMA_OPTIONS.md`, leídos de `system.settings`
y `system.merge_tree_settings` en la 26.3.33.24:

| Ajuste | Valor por defecto aquí | Qué implica |
|---|---|---|
| `non_replicated_deduplication_window` | 0 | La deduplicación de inserts está **apagada** en MergeTree sin réplica. Hay que activarla en la tabla para que `insert_deduplication_token` sirva |
| `insert_deduplication_token` | vacío | Existe como ajuste de consulta |
| `max_partitions_per_insert_block` | 100 | Un insert que toque más de 100 particiones falla |
| `do_not_merge_across_partitions_select_final` | 0 | Apagado por defecto |
| `use_query_condition_cache` | 1 | Encendido por defecto. Ver el aviso 2 |
| `index_granularity` | 8192 | |
| `count_distinct_implementation` | uniqExact | |
| `join_use_nulls` | 0 | |

No probado: que `insert_deduplication_token` descarte de verdad un lote reentregado con
la ventana activada. Es el experimento que falta si se va por MergeTree con ingestión
idempotente.

## 4. Lo que estos números sugieren, sin elegir

- La **consulta principal no distingue** entre ninguna de las opciones. Lo que decida el
  `ORDER BY` serán las consultas con filtro que se quieran hacer además.
- Si se va a **filtrar por fecha**, que la fecha esté en la clave cambia lo leído en un
  orden de magnitud (32.768 frente a 348.759 filas). Si la clave tiene que ser la
  identidad del log (Replacing), eso hay que recuperarlo por otra vía.
- El **orden pool/fecha** es un intercambio entre consultas por pool (sobre todo los
  pequeños) y consultas de todos los pools por fecha. Con 4 pools la diferencia máxima
  medida es de 6 veces en filas y de 0 ms en tiempo.
- La **partición mensual no cambia ninguna lectura**. Su valor, si lo tiene, es operativo.
- **Replacing protege el total frente a reentregas solo si se lee con `FINAL`**, y
  `FINAL` cuesta más cuantas más partes sin mergear haya. MergeTree no protege nada: la
  garantía tiene que estar en la ingestión. La zona de aterrizaje ya hace idempotente la
  carga por fichero.
- En **tipos**, lo que más bytes mueve no son los enteros de 256 bits, sino el `tx_hash`.
- **A 881.000 filas, todo esto son milisegundos y ~108 MB.** Ninguna opción es lenta. Lo
  que separa las opciones es la corrección y lo que cada una obliga a recordar al
  escribir consultas.
