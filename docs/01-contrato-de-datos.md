# 01 — Contrato de datos

> El artefacto más importante del paquete. Define el **esquema canónico interno**
> que la aplicación consume. La capa de adaptación que se escribe el día de la
> prueba tiene un único trabajo: producir instancias válidas de este esquema.
> Implementación ejecutable: [`app/domain/schema.py`](../app/domain/schema.py).

---

## 1. Flujo de datos

```
INSUMOS REALES            ADAPTADOR                 ESQUEMA CANÓNICO        MOTOR              UI
(desconocidos)            (se escribe el día)       (fijo, ya escrito)

  base de datos  ──┐                                   Product
  (csv/xlsx/dump)  │   ┌──────────────────┐            ├─ Price            ┌──────────┐   ┌─────────┐
                   ├──▶│ normalize()      │──────────▶ ├─ StoreStock  ────▶│ filtro   │──▶│ canasta │
  documentos    ───┤   │ map_categories() │            ├─ BusinessSignals  │ duro     │   │ + Modo  │
  (pdf/md/docx) ───┘   │ derive_signals() │            ├─ Citation         │ ranking  │   │ Negocio │
                       │ index_docs()     │            └─ attributes{}     └──────────┘   └─────────┘
                       └──────────────────┘                   │
                                │                             │
                                └──────▶ AdapterReport ◀──────┘
                                         (qué se resolvió, qué se degradó)
```

**Regla de oro:** nada aguas abajo del adaptador conoce el formato original. Si un
campo canónico no se pudo llenar, el adaptador lo deja ausente y lo anota en
`AdapterReport`. Nunca inventa silenciosamente.

---

## 2. Campos obligatorios (sin ellos no hay producto)

Son **cuatro**, deliberadamente. Un producto que sólo traiga esto debe poder
recorrer el sistema completo y aparecer en la demo.

| Campo canónico | Tipo | Si falta |
|---|---|---|
| `product_id` | `str` | Se genera un hash del nombre + fila. Si tampoco hay nombre, se descarta la fila. |
| `name` | `str` | Fila descartada. Contada en `AdapterReport.products_rejected`. |
| `category` | `Category` (`grocery`/`auto`/`home`/`unknown`) | Se asigna `UNKNOWN`: el producto es buscable pero **nunca** se propone en una canasta cross-categoría. |
| `price.amount` | `Decimal >= 0` | Fila descartada con `ExclusionReason.NO_PRICE`. Un precio inventado destruye la credibilidad ante el jurado; la ausencia se declara. |

---

## 3. Campos degradables — tabla maestra

Columna **Si falta** = comportamiento exacto del sistema. Columna **Feature afectada**
= qué se ve distinto en pantalla. Esta tabla es la implementación de la regla de
degradación: **toda feature tiene una fila aquí**.

### 3.1 Identidad y descripción

| Campo canónico | Tipo | Oblig. | Si falta | Feature afectada |
|---|---|---|---|---|
| `brand` | `str?` | Degradable | Se oculta la línea de marca en la tarjeta. No afecta ranking. | Tarjeta, comparador |
| `subcategory` | `str?` | Degradable | Se usa `category` en su lugar en los agrupadores. | Agrupación de canasta |
| `raw_category` | `str?` | Degradable | Se pierde la auditoría del mapeo; `AdapterReport` marca el mapeo como no verificable. | Pantalla de diagnóstico |
| `description` | `str?` | Degradable | Relevancia se calcula sólo sobre `name` + `attributes` (pierde recall, no rompe). | Ranking, detalle |
| `image_url` | `str?` | Degradable | Placeholder con la inicial de la categoría y color por categoría. **No se buscan imágenes externas**: cuesta minutos y rompe el deploy sin red. | Tarjeta |
| `unit` / `pack_size` | `str?`/`float?` | Degradable | Se oculta el precio por unidad. El comparador omite esa fila. | Comparador |
| `is_active` | `bool` | Default `True` | Si el dataset no trae estado, todo se asume activo. | Filtro duro |

### 3.2 Atributos libres (`attributes: dict[str, str|float]`)

Es el saco donde entra todo lo específico del dataset: medida de llanta, color,
capacidad en litros, material, sabor, aroma. **Se copia tal cual, sin esquema.**

| Situación | Comportamiento |
|---|---|
| Hay atributos ricos | Fitment real por regla, comparador con filas por atributo común. |
| Hay atributos pobres (< 3 claves promedio) | Comparador degrada a comparar precio, marca y señales de negocio. |
| No hay atributos | Fitment degrada a coincidencia textual sobre `name` (ver doc 06). El comparador sigue vivo con precio/marca/señales. |

### 3.3 Stock y tienda

| Campo canónico | Tipo | Oblig. | Si falta | Feature afectada |
|---|---|---|---|---|
| `stock[].store_id` | `str` | Degradable | Se crea una tienda única sintética `__ALL__`. El selector de tienda **se oculta** (no se muestra roto). | Filtro duro, selector de tienda |
| `stock[].qty` | `int?` | Degradable | No se muestra cantidad; sólo el estado. | Badge de disponibilidad |
| `stock[].status` | enum | Default `UNKNOWN` | **Crítico:** `UNKNOWN` ≠ `OUT_OF_STOCK`. Si no hay stock, el filtro duro **no descarta nada** (descartaría todo) y degrada a `is_active`. La tarjeta muestra "disponibilidad no verificada". | Filtro duro, tarjeta |
| `stock[].updated_at` | `datetime?` | Degradable | Se omite la leyenda "actualizado hace X". | Tarjeta |

> **Decisión asumida:** con stock ausente el sistema no finge. Muestra el badge gris
> "disponibilidad no verificada" en cada tarjeta. Es más defendible ante el jurado
> que un "En stock" falso, y es un punto de conversación a favor.

### 3.4 Precio y promoción

| Campo canónico | Tipo | Oblig. | Si falta | Feature afectada |
|---|---|---|---|---|
| `price.currency` | enum | Default `PEN` | Se asume moneda única del dataset; se declara en el diagnóstico. | Todo lo monetario |
| `price.promo_amount` | `Decimal?` | Degradable | La señal `promo` sale del scoring y su peso se redistribuye. No se muestra el tachado. | Ranking, tarjeta |
| `price.promo_starts_on` / `promo_ends_on` | `date?` | Degradable | La promo se asume vigente. Se omite el contador "válido hasta". | Tarjeta |

### 3.5 Señales de negocio (`BusinessSignals`)

Ninguna es obligatoria. Todas van envueltas en `Signal[T]` con `source ∈ {REAL, DERIVED, SIMULATED}`.
**Ausente ≠ cero.** El motor elimina la señal y redistribuye su peso (doc 02 §4).

| Campo canónico | Tipo | Si falta | Proxy permitido | Feature afectada |
|---|---|---|---|---|
| `margin_pct` | `Signal[float]?` 0–1 | Slider de margen **deshabilitado con leyenda**, peso redistribuido. | 1) `(pvp − costo)/pvp` si hay costo → `DERIVED`. 2) Mediana por categoría → `DERIVED`. 3) Tabla de márgenes típicos por categoría → `SIMULATED` + badge. | Modo Negocio, ranking |
| `turnover_index` | `Signal[float]?` | Slider de rotación deshabilitado, peso redistribuido. | 1) Conteo de ventas si hay tabla de transacciones → `DERIVED`. 2) Invertir `inventory_age_days` → `DERIVED`. 3) `SIMULATED` con badge. | Modo Negocio, ranking |
| `inventory_age_days` | `Signal[float]?` | Se omite la columna "antigüedad". Rotación absorbe su rol. | Fecha de ingreso vs hoy → `DERIVED`. | Modo Negocio |
| `is_private_label` | `Signal[bool]?` | Peso redistribuido, se omite el badge "marca propia". | Lista de marcas propias del retailer contra `brand` → `DERIVED`. | Ranking, tarjeta |

> **Política de datos simulados (confirmada con el usuario):** permitidos **sólo si
> la UI los etiqueta**. Todo `SignalSource.SIMULATED` renderiza un badge ámbar
> "simulado" con tooltip explicando la derivación. `DERIVED` renderiza badge gris
> "estimado". `REAL` no renderiza badge. Sin excepciones.

### 3.6 Respaldo documental

| Campo canónico | Tipo | Si falta | Feature afectada |
|---|---|---|---|
| `documents[]` (`Citation`) | `list` | La tarjeta muestra el estado **"sin respaldo documental"** con texto explícito. La recomendación sigue siendo válida. **Nunca se inventa la cita.** | Cita a la fuente |
| `Citation.locator` | `str?` | Se cita el documento sin página/sección. | Cita |
| `Citation.snippet` | `str` | Obligatorio dentro de una `Citation`: sin texto literal no hay cita, se omite la cita entera. | Cita |

### 3.7 Compatibilidad

| Campo canónico | Tipo | Si falta | Feature afectada |
|---|---|---|---|
| `CompatibilityRule[]` | `list` | No se evalúa fitment. La verificación degrada a coincidencia textual de medida en `name`/`attributes`. Si tampoco hay medidas, **el escenario 2 de la demo se sustituye** (doc 06). | Fitment |

---

## 4. Normalización de categorías

El dataset traerá su propia taxonomía. El adaptador la colapsa a las tres canónicas
con esta tabla, que se llena en el triage.

| Categoría canónica | Señales típicas en el dataset (llenar el día) |
|---|---|
| `grocery` | abarrotes, bebidas, lácteos, limpieza, cuidado personal, congelados, … |
| `auto` | llantas, neumáticos, lubricantes, accesorios auto, autopartes, … |
| `home` | decoración, almacenaje, organización, textil hogar, muebles, … |

**Tabla de sinónimos — llenar en el triage:**

| Valor crudo en el dataset | → Canónico | Confianza | Nota |
|---|---|---|---|
| | | | |
| | | | |
| | | | |
| | | | |
| | | | |
| | | | |
| | | | |
| | | | |
| | | | |
| | | | |

**Criterio de corte:** si tras 20 minutos más del 40 % de los productos cae en
`UNKNOWN`, se abandona el mapeo exhaustivo y se mapean **sólo** las ramas necesarias
para los 3 escenarios de la demo (doc 04). El resto queda `UNKNOWN` y se declara.

---

## 5. Protocolo de triage — primeros 15 minutos

Correr esto **antes** de escribir una sola línea de adaptador. El objetivo no es
entender los datos, es saber qué features sobreviven.

```bash
# 1. Inventario de archivos
ls -lhR ./insumos
file ./insumos/*

# 2. Si es CSV/XLSX: forma y columnas
python - <<'PY'
import pandas as pd, glob
for f in glob.glob("insumos/*.csv") + glob.glob("insumos/*.xlsx"):
    df = pd.read_csv(f) if f.endswith("csv") else pd.read_excel(f)
    print("=" * 70); print(f, df.shape)
    print(df.dtypes)
    print("NULOS %:"); print((df.isna().mean() * 100).round(1).sort_values(ascending=False))
    print("CARDINALIDAD:"); print(df.nunique().sort_values(ascending=False).head(20))
    print(df.head(3).to_string())
PY

# 3. Si es un dump SQL / sqlite
sqlite3 insumos/db.sqlite ".tables" ".schema"
# postgres dump: grep -E '^CREATE TABLE|^COPY' dump.sql | head -50

# 4. Documentos
ls insumos/*.pdf
uv run --group etl python -c "import pypdf,glob;print(sum(len(p.extract_text().split()) for f in glob.glob('insumos/*.pdf') for p in pypdf.PdfReader(f).pages))"   # palabras -> tramo de §8.2
# extracción real: docling (doc 07 §2); pypdf es el fallback
```

**Las 7 preguntas que este triage debe responder (anotar la respuesta literal):**

1. ¿Cuántos productos hay?  → `______`
2. ¿Hay una columna de costo o de margen?  → `______`  *(decide si vive el Modo Negocio con datos reales)*
3. ¿Hay stock, y es por tienda?  → `______`  *(decide si vive el selector de tienda)*
4. ¿Las tres categorías están representadas?  → `______`  *(decide si vive la demo cross-categoría, que es la tesis entera)*
5. ¿Hay atributos estructurados, y en cuántos productos?  → `______`  *(decide si vive el fitment real)*
6. ¿Los documentos son texto extraíble o escaneos?  → `______`  *(decide si viven las citas)*
7. ¿Cuántas palabras tiene el corpus documental?  → `______`  *(ver el comando del triage — decide el tramo de §8.2: < 50k → A, si no → B)*

> Si la respuesta a **(4)** es "no, sólo hay supermercado", detener todo y leer el
> doc 06 §R7 antes de seguir: cambia la tesis de la demo, no sólo una feature.

---

## 6. Plantilla de mapeo — llenar en los primeros 45 minutos

Una fila por campo canónico. `Resolución`: `REAL` / `DERIVED` / `SIMULATED` / `AUSENTE`.
Al terminar, esta tabla se transcribe a `AdapterReport.mappings` y se vuelve la
pantalla de diagnóstico de la app.

| # | Campo canónico | Campo del insumo (tabla.columna) | Transformación | Cobertura % | Resolución | Decisión / nota |
|---|---|---|---|---|---|---|
| 1 | `product_id` | | | | | |
| 2 | `name` | | | | | |
| 3 | `category` | | mapa de sinónimos §4 | | | |
| 4 | `price.amount` | | | | | |
| 5 | `price.currency` | | | | | |
| 6 | `price.promo_amount` | | | | | |
| 7 | `brand` | | | | | |
| 8 | `subcategory` | | | | | |
| 9 | `description` | | | | | |
| 10 | `image_url` | | | | | |
| 11 | `unit` / `pack_size` | | | | | |
| 12 | `attributes{}` | | | | | |
| 13 | `stock[].store_id` | | | | | |
| 14 | `stock[].qty` | | | | | |
| 15 | `stock[].status` | | umbral: 0→OUT, 1-5→LOW, >5→IN | | | |
| 16 | `signals.margin_pct` | | | | | |
| 17 | `signals.turnover_index` | | | | | |
| 18 | `signals.inventory_age_days` | | | | | |
| 19 | `signals.is_private_label` | | | | | |
| 20 | `documents[]` | | | | | |
| 21 | `CompatibilityRule[]` | | | | | |
| 22 | `is_active` | | | | | |

**Regla de tiempo:** a los **45 minutos** esta tabla se congela tal como esté. Las
filas vacías se convierten en degradaciones declaradas, no en trabajo pendiente.
Volver a pelear con un campo después de T+0:45 es la forma más común de perder la
prueba.

---

## 7. Contrato del persistente

- **Formato:** SQLite de solo lectura, generado por el ETL y **horneado en la imagen
  Docker**. Cloud Run es stateless: no hay disco que sobreviva al reinicio.
- **Tablas:** `products` (una fila por producto, `attributes`/`stock`/`signals`/`documents`
  como columnas JSON), `documents`, `compatibility_rules`, `products_fts` (FTS5 sobre
  `name || description || brand || attributes`) y `documents_fts` (FTS5 sobre chunks;
  ver §8).
- **Tamaño objetivo:** ≤ 50 MB. Por encima, muestreo estratificado (doc 06 §R5).
- **Decisión asumida:** no hay base de datos externa, no hay migraciones, no hay ORM.
  Un `sqlite3.connect(..., check_same_thread=False)` en modo read-only y consultas
  escritas a mano. Cualquier otra cosa es tiempo regalado.

---

## 8. Indexación de documentos

> Sección aparte de §7 a propósito: **el catálogo y los documentos son dos problemas
> de recuperación distintos y no merecen la misma respuesta.** Mezclarlos es el error
> que esta sección corrige.

### 8.1 Por qué el catálogo va léxico y no vectorial

El match real de un producto contra un slot es **por atributo**, no por semántica:
`tire_size == "185/65R15"` es un `WHERE`, y un coseno ahí es estrictamente peor.
Además, un vector no dice *por qué* matcheó — y toda la tesis del proyecto es que cada
decisión sea auditable (doc 02 §8). Súmese que a escala de catálogo real los
embeddings son un costo de indexación que no se ve en pantalla.

**Esa justificación vale para `products_fts`. No se extiende a los documentos.**

### 8.2 Tres tramos, decididos con un comando

**La decisión no es "BM25 o embeddings".** Es cuál de tres tramos aplica, y lo decide el
**tamaño del corpus**, que se mide en quince segundos dentro del triage:

```bash
uv run --group etl python -c "import pypdf,glob;print(sum(len(p.extract_text().split()) for f in glob.glob('insumos/*.pdf') for p in pypdf.PdfReader(f).pages))"
```

La extracción real la hace **docling** (doc 07 §2), que además da encabezados para el
`locator` y OCR para escaneados; `pypdf` queda como fallback.

| Palabras | Tramo | Mecanismo | Infra extra |
|---|---|---|---|
| **< ~50 000** | **A — sin recuperación** | Los documentos van completos en el contexto del LLM, que devuelve el fragmento literal. | **Ninguna** |
| **~50 000 – 500 000** | **B — BM25 + rerank** | FTS5 con recall amplio → el LLM elige el chunk y extrae el span. | FTS5 (stdlib) |
| **> 500 000 y prosa técnica** | **C — embeddings** | Embedder por API en el ETL + coseno en numpy. | Proveedor nuevo |

**Tramo A es el caso más probable.** 50 000 palabras son unas 150–200 páginas de PDF; un
set típico de guías y fichas de un retailer cae debajo de eso.

**Los tramos A y B usan sólo la key de Anthropic, que ya vas a tener.** Por eso ninguno
introduce una dependencia nueva, y por eso la decisión es segura sin saber nada de los
insumos: **el peor caso es que haya que subir un tramo, nunca que falte una pieza.**

### 8.3 Tramo A — sin recuperación (el más probable)

Si el corpus entra en contexto, recuperar es trabajo inútil: se le pasan los documentos
al LLM junto con el slot y se le pide el fragmento que lo respalda.

- **Semánticamente perfecto.** Desaparece el problema de vocabulario: *"bloqueador"* vs
  *"factor de protección solar"* lo resuelve el modelo leyendo, no un tokenizador.
- **Sigue sin redactar la cita.** Devuelve un span, y se valida que sea **substring
  literal** del documento. Si no lo es, se descarta la cita y la tarjeta muestra "sin
  respaldo documental". La garantía de doc 02 §8 queda intacta.
- **El costo lo mata el caché.** El corpus es un **prefijo estable** → va con
  `cache_control: {"type": "ephemeral"}`. La primera llamada lo escribe, el resto lo lee
  a ~0.1x. Sumado a que las 3 misiones semilla están cacheadas en disco (doc 04 §6),
  **la demo no paga latencia ni cuota**.

**Costo: ~15 min.** Es el tramo más barato *y* el de mejor calidad. Esa coincidencia es
rara y hay que aprovecharla.

### 8.4 Tramo B — BM25 con expansión en el origen

Si el corpus no entra en contexto, entra FTS5 como piso de recall.

**La clave: en este sistema controlamos el lado de la consulta.** No hay un usuario
tipeando en una caja — los `keywords` del slot los **escribe el LLM**
(`BasketSlot.keywords`, ya en el contrato).

| # | Paso | Costo |
|---|---|---|
| 1 | **Expansión de sinónimos en el prompt.** El intérprete emite `["bloqueador", "protector solar", "filtro solar", "SPF", "factor de protección"]`. Cierra la mayor parte del hueco de vocabulario. | **0 min** — cambio al prompt pre-escrito |
| 2 | `tokenize="unicode61 remove_diacritics 2"` y truncado de plurales antes de consultar. | 5 min |
| 3 | **BM25 con `OR` y recall amplio: top 30**, no top 10. El corpus es chico; ser permisivo es gratis y el rerank filtra. | 10 min |
| 4 | **El LLM elige el chunk y extrae el span**, con la misma validación de substring literal del tramo A. | 20 min |

**Tabla `documents_fts`:** chunks de ~400 palabras con solape de 50, con `doc_id` y
`locator` (página o encabezado) por chunk — el `locator` es lo que hace citable la cita.

**Costo: ~35 min.**

### 8.5 Tramo C — embeddings, y por qué no se va a ejercer

**Requiere las tres condiciones a la vez:** corpus > 500 000 palabras, vocabulario
técnico lejano al del consumidor, y **la key del proveedor ya en la mano** — la API de
Anthropic no expone endpoint de embeddings, haría falta Voyage u otro.

**Decisión asumida: no se saca esa key, y el tramo C queda documentado pero muerto.**
No es por los 10 minutos que cuesta darla de alta. Es que tenerla crea una tentación
real: a T+2:00, con el motor a medias, *"son sólo 25 minutos"* es el pensamiento que
cuesta el Modo Negocio. **Y el Modo Negocio es la feature que gana la prueba; las citas
ya funcionan bien en los tramos A y B.**

> **Nota sobre el modelo local — qué corre en ETL y qué corre en runtime.**
>
> El criterio **no es el peso de la dependencia**, es en qué momento se ejecuta. Docling
> pesa mucho (usa torch) y aun así está aprobado, porque es **ETL puro**: convierte los
> documentos una vez en la máquina local, el texto queda horneado en `catalog.db` y **el
> contenedor nunca ve un PDF**. La dependencia no existe en producción.
>
> Un embedder **local** es distinto: necesita el modelo también en **runtime**. El vector
> de la consulta tiene que salir del *mismo* modelo que indexó los documentos, y la
> consulta es texto libre que el jurado escribe en vivo — no se puede precalcular. Ahí sí
> el modelo viaja en la imagen y encarece el ciclo build/push y el cold start.
>
> Y aun eso admite matices: un modelo chico sobre `onnxruntime` (sin torch) son ~50-90 MB
> y sería perfectamente viable. **Así que el motivo real para preferir el embedder por API
> no es técnico, son los minutos:** por API se embebe en el ETL, viaja un array numpy de
> ~2 MB y en consulta es una llamada más un producto punto. El tramo C sigue descartado
> por lo que dice arriba —la tentación de gastar 25 minutos fuera del camino crítico—, no
> porque torch sea inaceptable.
