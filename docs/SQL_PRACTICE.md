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

Los ejercicios corren contra el **esquema real**, no contra una tabla de prácticas:

```
make up && make load && make mv-setup && make dbt-build     # una vez
PYTHONPATH=src uv run python scripts/check_sql_practice.py  # ejecuta TODAS las soluciones (solo lectura)
make ch-client
```

Sin datos propios, `make demo` deja las mismas tablas en bases `demo_*` con los fixtures.

## Las tablas

| Tabla | Qué es | Ojo con |
|---|---|---|
| `onchain.raw_swaps` | Un swap por fila, tal como sale de la cadena. `MergeTree`, `ORDER BY (pool_address, block_timestamp, block_number, log_index)`, partición mensual | `tx_hash`, `sender` y `recipient` son **binarios** (`FixedString`): `lower(hex(x))` para verlos, `unhex('…')` para filtrar. `amount0` / `amount1` son `Int256` crudos con signo (positivo = el pool recibe) |
| `onchain.swaps_daily` | Vista de lectura sobre la materialized view: swaps y volumen **crudo** por pool y día | Se lee la vista, no `swaps_daily_agg` (ejercicio 16) |
| `onchain_dbt.stg_swaps` | Staging de dbt (view): hashes en hex, `block_date`, importes escalados `Decimal(76, 18)` junto a los crudos (`amount0_raw`), `volume_usd` | Es una vista: cada consulta recalcula el escalado sobre `raw_swaps` |
| `onchain_dbt.fct_pool_daily` | Mart diario: swaps, volumen de cada token, `volume_usd`, `fees_usd` | Lleva `pool_label` y `fee` **denormalizados**: no hace falta JOIN |
| `onchain_dbt.dim_pools` | `pools.yml` como tabla | `pool_address` en minúsculas, como en todo ClickHouse |

Fórmulas: importe legible = `amount / 10^decimals` (ya hecho en `stg_swaps`). Precio crudo
(token1 por token0) = `(sqrt_price_x96 / 2^96)^2`; en los pools USDC/WETH el precio en dólares por
ETH es `1e12 / precio_crudo`.

## Ejercicios

**1. Calentamiento.** Swaps por pool, con la fecha del primero y del último.
Ordenado de más a menos.

**2. Volumen diario por pool.** Es la consulta principal del proyecto. (a) Sácala del mart, sin
ningún JOIN. (b) Sácala de `stg_swaps` uniendo con `dim_pools` y comprueba que coincide. ¿Qué
ganas y qué pierdes con cada una?

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

**16. La materialized view por dentro.** En una sola fila: cuántas filas tiene
`swaps_daily_agg`, cuántos pool-días da la vista `swaps_daily`, cuántos pool-días hay de verdad en
`raw_swaps`, y el total de swaps por cada camino. ¿Por qué el destino tiene más filas que pool-días
y aun así los totales cuadran? (b) Compara, para los últimos días, los swaps por la MV y por un
`GROUP BY` directo.

**17. Buscar por hash en una columna binaria.** Saca todos los swaps de la transacción más reciente
de la tabla, filtrando `raw_swaps` por `tx_hash`. ¿Cómo escribirías el filtro si te dan el hash
como texto `0x…`? ¿Cuántas filas lee esa consulta y por qué?

## Qué cambió al pasar al esquema real

Esta práctica se escribió primero contra una tabla candidata y se adaptó después al esquema
decidido (DECISIONS.md #10 a #14). Lo que hubo que tocar es, en sí, materia de entrevista:

- **Hashes binarios:** cualquier `tx_hash` o `sender` de `raw_swaps` necesita `lower(hex(...))`
  para verse y `unhex(...)` para filtrarse. En `stg_swaps` ya vienen en texto.
- **`pool` pasó a `pool_address`**, y la etiqueta ya no sale de un JOIN obligatorio: el mart la
  lleva denormalizada (ejercicios 2 y 9), el staging no (2b, 4, 7, 8, 12).
- **Importes:** los ejercicios de volumen usan `volume_usd` y `amount0` de `stg_swaps`, que son
  `Decimal` exactos, en vez de dividir un `Int256` convertido a float.
- **Partición mensual:** en el ejercicio 15 `EXPLAIN` muestra ahora tres etapas (min/max de
  partición, clave de partición, clave primaria) y `Parts: 1/2`.
- **No es ReplacingMergeTree**, así que ninguna consulta necesita `FINAL`. La única tabla del
  proyecto que sí lo exige es `external_daily_volume`.
