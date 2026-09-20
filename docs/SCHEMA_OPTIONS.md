# Opciones de esquema para la tabla de swaps (sin decidir)

Documento de trabajo para que Roberto decida. **Aquí no se decide nada**: cada
apartado da opciones, tradeoffs, una recomendación razonada y la pregunta de
entrevista que esa decisión suele provocar. Las decisiones, cuando se tomen,
van a `DECISIONS.md`, escritas por él.

Los nombres de columna que aparecen son ilustrativos, no una propuesta de
nombres.

> **Aviso de fiabilidad.** Lo que sale de mediciones propias está marcado como
> *medido*. Lo que afirmo sobre el comportamiento de ClickHouse es conocimiento
> general, no comprobado contra la 26.3.33.24 de este repo. Donde el detalle
> importa (nombres de ajustes, valores por defecto) pone **verificar**: son
> buenos candidatos para probarlos en el contenedor antes de darlos por buenos.

## 0. Los números que mandan

Medidos el 2026-09-18 contra Alchemy (detalle en `docs/MEASUREMENTS.md`, rama
del cliente RPC):

| Dato | Valor |
|---|---|
| Filas estimadas en 30 días | **~684.000** (3,17 swaps por bloque, 216.000 bloques) |
| Filas por día | ~23.000 |
| Reparto por pool | USDC/WETH 0.01%: **99,5 %** · wstETH/USDC 0.05%: ~3.100 filas · wstETH/USDC 0.3%: del orden de 1.000 |
| Swaps por bloque (máx. visto) | 9 |
| Swaps por transacción (máx. visto) | 4 |

Dos consecuencias que atraviesan todo el documento:

1. **El conjunto es diminuto para ClickHouse.** Con la granularidad por defecto
   (8.192 filas por marca) son unas **84 marcas** en total. Cualquier esquema
   razonable responde en milisegundos. Casi ninguna decisión de aquí se va a
   notar en velocidad: se notan en **corrección** (duplicados, pérdida de
   precisión) y en **lo que eres capaz de explicar**. Conviene decirlo tal cual
   en la entrevista en vez de fingir un problema de escala.
2. **El sesgo es extremo.** Un pool es el 99,5 % de las filas. Un índice que
   empieza por `pool` descarta casi todo cuando preguntas por un pool pequeño y
   casi nada cuando preguntas por el grande.

---

## a. Motor: MergeTree o ReplacingMergeTree

### El problema real

Los logs de bloques finalizados son inmutables: la cadena no los corrige. Los
duplicados solo pueden venir **de nuestra propia tubería**. El ejecutor del
backfill (rama del cliente RPC) entrega *al menos una vez*: si el proceso muere
después de que el sink acepte un lote y antes de guardar el checkpoint, ese
lote se entrega otra vez. Hay un test que lo demuestra a propósito. La pregunta
es dónde se resuelve eso.

### Opción 1: MergeTree + ingestión idempotente

La tabla no sabe nada de duplicados; la tubería garantiza que no los mete.
Formas de conseguirlo:

- **Deduplicación de inserts por token.** ClickHouse puede descartar un insert
  repetido. En tablas replicadas viene activado; en MergeTree sin réplica hay
  que activarlo con el ajuste de tabla `non_replicated_deduplication_window`
  (por defecto 0, desactivado) (**verificar**). Con el ajuste de consulta
  `insert_deduplication_token` el token lo pones tú, por ejemplo el rango del
  lote (`"26000000-26000499"`): un lote reentregado con el mismo token se
  descarta entero. Encaja con el ejecutor, que reentrega con el mismo bloque
  inicial. Letra pequeña: la ventana es finita (los últimos N inserts), y el
  último lote corto de una ejecución puede reentregarse con un final mayor, así
  que el token debería derivarse del bloque inicial.
- **Carga por partición con intercambio atómico.** Cargar en una tabla de
  staging y hacer `ALTER TABLE ... REPLACE PARTITION`. Idempotente por
  construcción y atómico, pero ata la ingestión al particionado (apartado c).
- **Borrar el rango y reinsertar.** `ALTER TABLE ... DELETE` es una mutación:
  asíncrona y reescribe partes enteras. Existe el `DELETE FROM` ligero, más
  barato. Funciona, pero es usar un martillo: en ClickHouse borrar es la
  operación cara.

A favor: las consultas son simples y siempre correctas, sin `FINAL` ni
`argMax`. Lo que ves en la tabla es lo que hay.
En contra: si la tubería falla en su garantía, los duplicados se quedan para
siempre y nadie avisa. Hay que acompañarlo de un test que lo vigile (en dbt:
`count()` frente a `uniqExact` de la identidad del log).

### Opción 2: ReplacingMergeTree

La tabla elimina, **durante los merges**, las filas con la misma clave de
ordenación, quedándose con la última (o la de mayor versión si se le da columna
de versión).

Lo que hay que tener claro, porque es donde la gente se equivoca:

- La deduplicación es **eventual y sin garantía de plazo**. Los merges ocurren
  cuando ClickHouse quiere. Entre tanto, los duplicados están y se leen.
- Solo deduplica filas **con la misma clave de ORDER BY** y **dentro de la
  misma partición**. La clave de ordenación pasa a ser la clave de
  deduplicación: esto condiciona el apartado b.
- Para leer sin duplicados hay que pedirlo: `SELECT ... FINAL`, o agregar con
  `argMax` / `GROUP BY` sobre la clave. Olvidarlo en una sola consulta da un
  número mal, en silencio.
- **Coste de `FINAL`**: hace en lectura el trabajo del merge. Históricamente
  era serio (lectura casi secuencial); las versiones recientes lo paralelizan y
  permiten no mezclar entre particiones
  (`do_not_merge_across_partitions_select_final`) (**verificar**). Con 684.000
  filas el coste es de milisegundos: aquí no es un argumento de rendimiento,
  sino de **disciplina en las consultas**.
- `OPTIMIZE TABLE ... FINAL` fuerza el merge. Sirve para una demo o tras un
  backfill, no como operación programada: reescribe todo.

A favor: red de seguridad dentro de la tabla; tolera una tubería imperfecta.
En contra: cada consulta (y cada modelo dbt) carga con `FINAL` o equivalente, y
la clave de ordenación deja de elegirse solo por las consultas.

### Recomendación

**MergeTree con ingestión idempotente (token por lote) y un test de
duplicados.** El dato es inmutable por naturaleza; ReplacingMergeTree está
pensado para filas que cambian (upserts, CDC), y usarlo para tapar un defecto
de la tubería traslada el coste a todas las consultas para siempre. Arreglarlo
en origen es más barato y más fácil de razonar.

Dicho esto, para este proyecto hay un argumento a favor de **probar las dos**:
cargar los mismos datos en una tabla de cada tipo, provocar la reentrega de un
lote y enseñar con `system.parts` y `system.query_log` qué pasa antes y después
del merge y cuánto cuesta `FINAL`. Es exactamente el tipo de cosa que el
proyecto dice querer observar (DECISIONS #1).

### Pregunta de entrevista

*"Tienes duplicados en una tabla ReplacingMergeTree y tu dashboard da cifras
infladas. ¿Por qué, si el motor deduplica?"* Respuesta esperada: deduplica en
merges, eventualmente, por clave de ordenación y por partición; hay que leer
con `FINAL` o agregar; y la pregunta de fondo es por qué llegan duplicados.
Repregunta habitual: *"¿y cuánto cuesta FINAL y cómo lo reducirías?"*

---

## b. ORDER BY

### Cómo funciona, en tres frases

Las filas de cada parte se guardan **ordenadas** por la clave. El índice
primario es **disperso**: guarda el valor de la clave una vez por gránulo
(8.192 filas), no por fila, y cabe en memoria. Una consulta con filtro sobre un
prefijo de la clave hace búsqueda binaria sobre esas marcas y lee solo los
gránulos que pueden contener datos; para columnas que no son prefijo el índice
ayuda poco, salvo que las anteriores tengan cardinalidad baja.

Regla práctica: columnas por las que filtras, **de menor a mayor
cardinalidad**. El orden también decide la compresión: valores parecidos
juntos comprimen mejor.

Aquí: 684.000 filas son ~84 gránulos. Los dos pools pequeños caben en **menos
de un gránulo cada uno**. Un escaneo completo de la tabla es trivial. La
decisión importa por corrección (si el motor es Replacing) y por saber
justificarla.

### La consulta principal

Volumen diario por pool: filtra (o agrupa) por `pool` y por rango de fechas.

### La tensión

La identidad "natural" de un log suele escribirse `(tx_hash, log_index)`. Como
clave de ordenación es **la peor posible**: `tx_hash` es aleatorio, así que
destruye la localidad (filas del mismo día repartidas por toda la tabla), el
índice no sirve para rangos de fecha y la compresión empeora.

Salida: `log_index` es el índice del log **dentro del bloque**, no dentro de la
transacción. Por tanto `(block_number, log_index)` identifica un log en la
cadena canónica igual de bien que `(tx_hash, log_index)`, y además es
monótono en el tiempo. Una clave `(pool, block_number, log_index)` sirve **a la
vez** a las consultas y a la deduplicación. La tensión se disuelve casi del
todo; lo que queda es el matiz de los reorgs (mismo número de bloque, distinto
hash), que se evita ingiriendo solo bloques finalizados (el ejecutor se queda
64 bloques por detrás de la punta).

*Medido en los fixtures:* `(block_hash, log_index)` es único en los 205 logs
reales (hay un test que lo comprueba).

### Candidatos

| Clave | Para la consulta principal | Como clave de dedup | Comentario |
|---|---|---|---|
| `(pool, block_timestamp, log_index)` | Muy buena: prefijo de baja cardinalidad y luego tiempo; el filtro por fecha usa el índice | Válida en la práctica (un bloque por slot de 12 s, timestamp único por bloque), pero depende de esa propiedad | La más directa para consultas por fecha |
| `(pool, block_number, log_index)` | Buena por pool; **un filtro por fecha no usa el índice** (la clave no contiene la fecha) salvo índice minmax sobre el timestamp o poda por partición | Exacta y sin supuestos | La más limpia como identidad; coincide con cómo trabaja el checkpoint |
| `(toDate(block_timestamp), pool, ...)` | Buena si lo normal es "todos los pools en un rango de fechas" | Igual que arriba | Con 3 pools la diferencia con pool-primero es inapreciable |
| `(tx_hash, log_index)` | Mala | Exacta | Solo para explicar por qué no |

Apunte: `PRIMARY KEY` puede ser un **prefijo** de `ORDER BY`. Por ejemplo
ordenar por `(pool, block_timestamp, log_index)` e indexar solo
`(pool, block_timestamp)`: `log_index` da orden determinista (y dedup) sin
ocupar sitio en el índice en memoria. Aquí el ahorro es nulo, pero es un
detalle que demuestra que se entiende la diferencia entre las dos cláusulas.

### Recomendación

`ORDER BY (pool, block_timestamp, log_index)` si el motor es MergeTree (apartado
a): es la que responde a la consulta principal sin ayudas. Si se elige
ReplacingMergeTree, mejor `(pool, block_number, log_index)`, que es identidad
exacta, añadiendo un índice de salto `minmax` sobre el timestamp o confiando en
la poda por partición para los filtros de fecha.

Con el sesgo del 99,5 %, `pool` primero ayuda mucho a los pools pequeños y nada
al grande: para el grande lo que poda es el tiempo, que va segundo. Es el orden
correcto igualmente.

### Pregunta de entrevista

*"¿En qué se diferencia el índice primario de ClickHouse del de Postgres, y qué
pasa si filtro por una columna que no es prefijo de la clave?"* Y la trampa:
*"¿Por qué no ordenar por tx_hash, si es lo que identifica la fila?"*

---

## c. PARTITION BY

### Lo honesto primero

**Particionar es gestión de datos, no velocidad.** Una partición es la unidad
para borrar, mover, intercambiar o caducar datos (`DROP` / `DETACH` /
`REPLACE PARTITION`, TTL). Para que las consultas vayan rápido está la clave de
ordenación. Hay poda por partición, sí, pero el índice primario ya hace ese
trabajo, y particionar de más **empeora** las cosas:

- Las partes **nunca se mezclan entre particiones**. Más particiones = más
  partes pequeñas = más ficheros y peor compresión.
- Un insert que toca N particiones crea N partes. Con lotes pequeños y
  particiones finas se llega al error de "demasiadas partes".
- Hay un límite de particiones por bloque de insert
  (`max_partitions_per_insert_block`, 100 por defecto) (**verificar**): un
  backfill de un año con particiones diarias lo rompe en el primer insert.
- La orientación general es mantener el número de particiones en decenas o
  cientos, no miles.

### Opciones para ~30 días y ~684.000 filas

| Opción | Particiones | Filas por partición | Valoración |
|---|---|---|---|
| Ninguna | 1 | 684.000 | Perfectamente defendible a este tamaño. La más simple. Se pierde la posibilidad de recargar o tirar un trozo con una operación de partición |
| Mensual `toYYYYMM(ts)` | 1 o 2 | ~340.000 a 684.000 | La convención. Da `REPLACE PARTITION` como mecanismo de recarga idempotente y escala sin cambios si la ventana crece a un año (12 particiones) |
| Diaria `toDate(ts)` | 30 | ~23.000 | 30 particiones de 3 gránulos cada una. No da problemas a este tamaño, pero es el hábito equivocado: a un año son 365, y cada lote del backfill que cruce días crea varias partes. Solo se justifica si la unidad de recarga real es el día |

Interacción con el apartado a: ReplacingMergeTree no deduplica entre
particiones. No es problema aquí (un mismo log cae siempre en la misma
partición), pero hay que saberlo.

### Recomendación

**Mensual.** No por velocidad (a este tamaño no hay diferencia medible), sino
porque es la unidad de gestión natural, deja abierta la recarga por partición y
es la respuesta que no hay que rectificar si la ventana pasa de 30 días a un
año. "Ninguna" es la segunda opción y es honesta; "diaria" es la que habría que
defender, y aquí no hay con qué.

### Pregunta de entrevista

*"¿Particionarías esta tabla por día para que las consultas por fecha vayan más
rápido?"* La respuesta que buscan es "no, para eso está el ORDER BY", seguida de
qué problemas trae particionar de más. Repregunta: *"¿y cuándo sí particionarías
por día?"* (retención por TTL diaria, recargas diarias atómicas, volúmenes de
miles de millones de filas por mes).

---

## d. Tipos

Rangos *medidos* sobre 1.474 swaps reales decodificados (los 205 de los
fixtures más el resto de la muestra de la que salieron), bloques 26.003.451 a
26.003.970.

| Campo | Tipo Solidity | Rango visto | Bits necesarios (visto) | Opciones | Recomendación |
|---|---|---|---|---|---|
| amount0 | int256 con signo | USDC: ±1,27e11 (±127.000 USDC). wstETH: ±6,1e16 | 37 / 56 | Int64, Int128, **Int256** | **Int256** |
| amount1 | int256 con signo | WETH: **±5,08e19** (±50,8 WETH). USDC: ±1,9e8 | **66** / 28 | Int64, Int128, **Int256** | **Int256** |
| sqrtPriceX96 | uint160 | 1,58e33 (USDC/WETH) · 4,4e24 (wstETH/USDC) | 111 / 82 | UInt128, **UInt256** | **UInt256** |
| liquidity | uint128 | 1,3e13 a 7,7e17 | 60 | UInt64, **UInt128** | **UInt128** |
| tick | int24 con signo | +198.002 a +198.131 · −195.874 a −195.601 | 18 + signo | Int16, **Int32** | **Int32** |
| log_index | entero | máx. 2.253 | 12 | UInt16, UInt32 | UInt32 |
| tx_index | entero | máx. 575 | 10 | UInt16, UInt32 | UInt16 o UInt32 |
| block_number | entero | ~26.003.000 | 25 | **UInt32**, UInt64 | UInt32 |
| block_timestamp | segundos | viene en el propio log (Alchemy) | | **DateTime('UTC')**, DateTime64 | DateTime('UTC') |

Lo que los datos dicen, más allá de la tabla:

- **Int64 desborda con datos reales.** Un swap de 50,8 WETH son 5,08e19
  unidades mínimas y el máximo de Int64 es 9,22e18. No es un caso teórico:
  aparece en media hora de datos de un pool de comisión baja. Cualquier tipo de
  64 bits para importes de tokens de 18 decimales es un bug esperando.
- **Int128 cabría para lo visto**, pero el tipo de la ABI es int256 y la
  decisión #3 habla de decodificar sin pérdida. Int256 es la única opción que
  no requiere argumentar. El coste: 32 bytes por valor sin comprimir, pero los
  bytes altos son casi siempre ceros (o `ff` en negativos) y la compresión se
  los come; la aritmética sobre 256 bits es más lenta, irrelevante a 684.000
  filas. Se puede medir en `system.columns` (bytes comprimidos frente a sin
  comprimir por columna), que es una buena demo.
- **Cuidado al convertir a coma flotante.** `toFloat64` de un Int256 pierde
  precisión por encima de 2^53. Para analítica (volumen en USD) da igual; para
  **reconciliar** contra el subgrafo, no: la reconciliación debe hacerse sobre
  enteros o sobre `Decimal`, y los importes legibles deben ser columnas
  derivadas en dbt, no sustituir a las crudas. `Decimal(38, 18)` admite 38
  dígitos y lo visto tiene 20: cabe con margen (**verificar** el comportamiento
  de la división Int256 a Decimal).
- **sqrtPriceX96 no tiene tipo nativo de 160 bits.** UInt128 contendría lo
  visto (111 bits), pero no el rango del tipo: un par con decimales muy
  dispares puede superarlo. UInt256.
- **tick no cabe en Int16** (±32.767): lo visto llega a ±198.000. No existe
  Int24 en ClickHouse; Int32.
- **liquidity** es uint128 y ClickHouse tiene UInt128: encaje exacto.

Campos de texto y hashes:

| Campo | Opciones | Comentario |
|---|---|---|
| pool (3 valores) | `LowCardinality(String)` en hex, `FixedString(20)` binario, `Enum` | LowCardinality en hex: legible y, con 3 valores, ocupa prácticamente nada. Enum obliga a un `ALTER` por cada pool nuevo |
| tx_hash | `String` de 66 caracteres, `FixedString(32)` binario | Aleatorio, no comprime: ~45 MB frente a ~22 MB en 684.000 filas. El binario ahorra la mitad pero obliga a `hex()` / `unhex()` en cada consulta y en el cruce con el subgrafo, cuyos identificadores son texto hex. A este tamaño, legibilidad |
| sender | `LowCardinality(String)`, `String` | *Medido:* 145 distintos en 1.474 swaps (son sobre todo routers). Buen candidato a LowCardinality |
| recipient | `String`, `LowCardinality(String)` | *Medido:* 277 distintos en 1.474 y crece sin techo. LowCardinality deja de compensar hacia las decenas o cientos de miles de valores (**verificar**). Medir con el mes completo antes de decidir |
| block_hash | guardarlo o no | No hace falta para analítica. Sirve para auditar reorgs. 66 bytes por fila que no comprimen |

Códecs (opcional, medible): `Delta` o `DoubleDelta` más `ZSTD` en
`block_number` y `block_timestamp`, que son monótonos. Ganancia real en bytes,
nula en percepción a este tamaño; útil como demostración con `system.columns`.

Comprobar antes de fijar nada: que `clickhouse-connect` inserta y lee Int256 /
UInt256 como `int` de Python sin pasar por float (**verificar** con un test de
ida y vuelta usando el valor extremo de los fixtures).

### Pregunta de entrevista

*"¿Por qué Int256 y no Decimal o Float64 para los importes?"* Se responde con el
dato: 50,8 WETH ya no caben en 64 bits, Float64 pierde enteros a partir de 2^53,
y la reconciliación exige igualdad exacta. Repregunta: *"¿y qué te cuesta?"*
(almacenamiento casi nada por compresión; aritmética más lenta; conversiones
explícitas en la capa de presentación).

---

## e. Qué denormalizar desde pools.yml

`pools.yml` tiene, por pool: dirección, símbolos, decimales, comisión y
etiqueta. Los decimales hacen falta para cualquier importe legible; la etiqueta
y la comisión, para cualquier informe.

| Opción | A favor | En contra |
|---|---|---|
| **Nada en la tabla cruda**; `pools.yml` cargado como seed de dbt (o tabla pequeña) y unido en los modelos | La tabla cruda es fiel a la cadena. `pools.yml` sigue siendo la única fuente. Cambiar una etiqueta no toca datos | Un join en cada modelo que necesite decimales (contra una tabla de 3 filas: gratis) |
| **Diccionario de ClickHouse** sobre esa tabla, con `dictGet` | Idiomático en ClickHouse, sin join, en memoria | Una pieza más que crear y refrescar; menos natural en dbt |
| **Denormalizar en la tabla cruda** (símbolos, decimales, comisión en cada fila) | Consultas directas sin join. En columnar, con 3 valores distintos y LowCardinality, el coste en disco es casi cero | Mezcla hechos de la cadena con metadatos mantenidos a mano. Si un valor de `pools.yml` estaba mal, hay que reescribir la tabla. Dos fuentes de verdad |
| **Denormalizar en la capa de marts de dbt**, no en la cruda | Lo mejor de ambos: cruda fiel, marts cómodos y reconstruibles con `dbt run` | Ninguno relevante |

Contexto que conviene saber explicar: en ClickHouse denormalizar es barato
(columnar y compresión) y los joins son comparativamente caros porque el lado
derecho se carga en memoria como tabla hash. Por eso la cultura es "tabla
ancha". Pero ese coste depende del tamaño del lado derecho, y aquí son 3 filas.

### Recomendación

**Tabla cruda solo con la dirección del pool; `pools.yml` como seed de dbt;
denormalizar en los marts.** Los decimales y la comisión son inmutables en la
cadena, así que denormalizarlos no sería un error, pero la etiqueta es
editorial y `pools.yml` debe seguir siendo la única fuente (es también una
regla para los agentes).

### Pregunta de entrevista

*"En ClickHouse se recomienda denormalizar. ¿Por qué aquí harías un join?"*
Respuesta: porque la recomendación viene del coste del join, que depende del
tamaño del lado derecho; con una dimensión de 3 filas el coste es nulo y se
gana una sola fuente de verdad. Repregunta: *"¿y con 50.000 pools?"*
(diccionario, o denormalizar en la ingestión).

---

## Resumen para decidir

| # | Decisión | Recomendación | Alternativa razonable | Decisión de Roberto |
|---|---|---|---|---|
| a | Motor | MergeTree + ingestión idempotente (token por lote) + test de duplicados | ReplacingMergeTree, o las dos en paralelo como experimento | |
| b | ORDER BY | `(pool, block_timestamp, log_index)` | `(pool, block_number, log_index)` si el motor es Replacing | |
| c | PARTITION BY | Mensual | Ninguna | |
| d | Tipos | Int256 / UInt256 / UInt128 / Int32; texto hex legible | FixedString binario para hashes | |
| e | Denormalización | Nada en la cruda; seed de dbt; denormalizar en marts | Diccionario | |

Orden sugerido: **a** antes que **b** (el motor condiciona la clave), y **d**
con una prueba de ida y vuelta de Int256 por `clickhouse-connect` antes de
escribir el DDL.
