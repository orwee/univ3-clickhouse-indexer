# Práctica de SQL en ClickHouse sobre los swaps

Quince ejercicios de dificultad creciente, pensados para una prueba técnica en
vivo. Aquí solo están los enunciados. Las soluciones comentadas están en
[`SQL_PRACTICE_SOLUTIONS.md`](SQL_PRACTICE_SOLUTIONS.md) y, ejecutables, en
[`sql_practice_solutions.sql`](sql_practice_solutions.sql). Inténtalos sin mirar.

Todas las soluciones se han ejecutado contra ClickHouse 26.3.33.24 con datos
reales (`scripts/check_sql_practice.py`). Dos de ellas fallaron en el primer
intento por detalles del dialecto; están señalados en las soluciones porque son
justo el tipo de tropiezo que aparece en una prueba.

## Preparar el entorno

```
PYTHONPATH=src:scripts uv run python scripts/check_sql_practice.py \
    --landing /var/lib/univ3-indexer/landing --keep
make ch-client
USE test_sql_practice;
```

`--keep` deja la base `test_sql_practice` creada. Al terminar: `DROP DATABASE test_sql_practice`.

## Las tablas

`swaps` es la candidata más sencilla de `SCHEMA_EXPERIMENTS.md`:
`MergeTree ORDER BY (pool, block_timestamp)`, sin particionar.

| Columna | Tipo | Nota |
|---|---|---|
| pool | LowCardinality(String) | dirección en minúsculas |
| block_number | UInt32 | |
| block_timestamp | DateTime('UTC') | |
| log_index | UInt32 | índice del log dentro del **bloque** |
| tx_hash, sender, recipient | String | hex |
| amount0, amount1 | Int256 | con signo, desde el punto de vista del pool: positivo = el pool recibe |
| sqrt_price_x96 | UInt256 | precio tras el swap, ver abajo |
| liquidity | UInt128 | |
| tick | Int32 | |

`pools` es `pools.yml`: `address`, `token0`, `token1`, `decimals0`, `decimals1`, `fee`, `label`.

Dos fórmulas que necesitarás:

- Importe legible: `amount / 10^decimals`.
- Precio crudo (token1 por token0, en unidades mínimas): `(sqrt_price_x96 / 2^96)^2`.
  En los pools USDC/WETH (token0 = USDC con 6 decimales, token1 = WETH con 18),
  el precio en dólares por ETH es `1e12 / precio_crudo`.

## Ejercicios

**1. Calentamiento.** Swaps por pool, con la fecha del primero y del último.
Ordenado de más a menos.

**2. Volumen diario por pool.** Es la consulta principal del proyecto. Por pool
(con su `label`) y día: número de swaps y volumen en unidades legibles de token0.
Ojo: `amount0` tiene signo.

**3. Tramos de 4 horas.** Para USDC/WETH 0.05%, swaps y volumen en USDC por tramos
de 4 horas. No uses `toStartOfHour`.

**4. Compras y ventas en una sola pasada.** Por pool: cuántos swaps tienen
`amount0 > 0`, cuántos `amount0 < 0`, y cuánto token0 entra y sale en total. Sin
subconsultas y sin `CASE`.

**5. Precio de cierre diario.** Para USDC/WETH 0.05%, el precio en USD por ETH del
**último** swap de cada día. "Último" significa por orden en la cadena, no por
timestamp (¿por qué no basta el timestamp?).

**6. Velas horarias (OHLC).** Apertura, máximo, mínimo, cierre y número de swaps
por hora para el mismo pool.

**7. Tamaño típico de un swap.** Para los dos pools USDC/WETH: mediana, p90 y p99
del tamaño del swap en USDC, en una sola llamada de agregación. Añade la mediana
exacta y compara. ¿Por qué difieren?

**8. Los 3 mayores swaps de cada pool cada día.** Con su `tx_hash`. Hay una forma
en ClickHouse que no necesita funciones de ventana.

**9. Acumulado y cuota.** Para los dos pools USDC/WETH, por día: volumen en USDC,
volumen acumulado del pool hasta ese día, y qué porcentaje del volumen total de
ese día se hizo en cada pool.

**10. Los mayores saltos de precio entre swaps consecutivos.** Para USDC/WETH
0.05%, los 10 mayores saltos en puntos básicos entre un swap y el anterior. Cuidado
con la primera fila.

**11. Horas sin actividad.** Para wstETH/USDC 0.3% (casi no opera), swaps por hora
**incluyendo las horas con cero**. Sin generar un calendario a mano ni hacer joins.

**12. Transacciones que tocan más de un pool.** (a) Las 10 transacciones con más
swaps entre las que pasan por más de un pool, con la lista legible de pools.
(b) Cuántas transacciones hay por cada combinación de pools. ¿Qué te dice el
resultado sobre por qué existen dos fee tiers del mismo par?

**13. El mismo par, dos precios.** Para cada swap de USDC/WETH 0.05%, busca el
precio más reciente de USDC/WETH 0.01% en ese instante o antes, y calcula la
diferencia media y el p99 en puntos básicos. Es un join "al valor más reciente", no
por igualdad.

**14. El LEFT JOIN que no da NULL.** En la primera media hora de datos, cuenta por
pool (partiendo de `pools`, para que salgan todos) los swaps y los `sender`
distintos. Mira el resultado para wstETH/USDC 0.3%. ¿Es correcto? Arréglalo de dos
formas.

**15. ¿Cuánto ha leído mi consulta?** (a) Sin ejecutarla, averigua cuántos
gránulos leerá una consulta de un día sobre wstETH/USDC 0.05%. (b) Después de
ejecutar varias consultas, saca de las tablas de sistema cuánto tardó y cuántas
filas y bytes leyó cada una.

## Qué cambiaría con el esquema final

- **ReplacingMergeTree:** todas las consultas necesitarían `FROM swaps FINAL` (o
  agregar por la identidad del log) para no contar duplicados pendientes de merge.
  Olvidarlo no da error: da un número más alto.
- **ORDER BY (pool, block_number, log_index):** los resultados son los mismos; lo
  que cambia es el ejercicio 15. Un filtro por fecha ya no usa el índice primario,
  salvo que haya un índice `minmax` sobre el timestamp o partición por fecha.
- **Partición mensual:** nada cambia en las consultas. En el 15 aparece además la
  poda por partición (`Parts: x/y`).
- **Hashes como `FixedString(32)`:** el ejercicio 8 necesitaría
  `lower(hex(tx_hash))` para mostrarlos, y los filtros por hash, `unhex(...)`.
- **Denormalizar `label` y decimales en `swaps`:** desaparecen los `JOIN pools` de
  los ejercicios 2, 4, 7, 8, 9 y 12.
