# 02 — Motor de scoring

> Cómo se ordena. Determinista, auditable y ajustable en vivo. **El LLM no participa
> de este documento**: cuando el motor recibe un `MissionPlan`, el modelo ya terminó
> su trabajo. Lo único que el modelo aporta al orden es lo que el cliente **declaró**
> y el plan copió: especificaciones (`attribute_requirements`) y marcas nombradas
> (`preferred_brands`). Qué hacer con eso lo decide este documento.

---

## 1. Las tres capas, en orden

```
  candidatos del catálogo
          │
   ┌──────▼──────────────────────────────────┐
   │ CAPA 1 — FILTRO DURO (booleano)         │  ← la BD decide, no el modelo
   │ stock · tienda · presupuesto ·          │
   │ compatibilidad · categoría · activo     │
   └──────┬──────────────────────────┬───────┘
          │ pasan                    │ descartados → ExclusionReason
   ┌──────▼──────────────────────────▼───────┐
   │ CAPA 2 — RANKING (score 0-1)            │  ← pesos ajustables en vivo
   │ relevancia · margen · rotación ·        │
   │ marca propia · promoción                │
   └──────┬──────────────────────────────────┘
          │
   ┌──────▼──────────────────────────────────┐
   │ CAPA 3 — EXPLICACIÓN                    │  ← cita literal, nunca parafraseada
   └─────────────────────────────────────────┘
```

Un producto **nunca** llega a la capa 2 si no pasó la 1. Esa es la respuesta corta a
"¿y si el modelo alucina un producto?": no puede, porque no elige productos. Tampoco
puede alucinar una marca: sólo se conservan las que aparecen literalmente en el texto
del cliente (§3.2).

---

## 2. Capa 1 — Filtro duro

Se evalúa por slot de la canasta. El primer criterio que falla corta y produce el
`ExclusionReason`, que se guarda en `ScoredProduct.excluded_reason` y alimenta la
feature "explicación del descarte".

| # | Criterio | Condición de descarte | Código | Si el dato falta |
|---|---|---|---|---|
| 1 | Precio | `price.amount` ausente | `NO_PRICE` | El producto ya fue descartado en el adaptador. |
| 2 | Activo | `is_active == False` | `DISCONTINUED` | Se asume activo; el criterio no descarta a nadie. |
| 3 | Stock | `availability == OUT_OF_STOCK` | `OUT_OF_STOCK` | `UNKNOWN` **no descarta**. Sin stock en el dataset, este criterio se desactiva entero. |
| 4 | Tienda | tienda seleccionada no está en `stock[]` | `NOT_IN_SELECTED_STORE` | Sin `store_id` real, el selector se oculta y el criterio se desactiva. |
| 5 | Categoría | `product.category != slot.target_category` (y el slot no es `UNKNOWN`) | `WRONG_CATEGORY` | Con categoría `UNKNOWN` el producto no compite por slots tipados. |
| 6 | Compatibilidad | alguna `CompatibilityRule` aplicable evalúa `False` | `INCOMPATIBLE` | Sin reglas, el criterio se desactiva y `compatibility_checked=False`. |
| 7a | Atributo requerido ausente | falta una clave de `slot.required_attributes` | `MISSING_REQUIRED_ATTRIBUTE` | Se relaja a advertencia si la cobertura del atributo en el catálogo < 50 %. |
| 7b | Atributo requerido con valor distinto | la clave existe pero su valor no matchea el esperado (talla de llanta, viscosidad de aceite, voltaje de batería...) | `WRONG_REQUIRED_ATTRIBUTE_VALUE` | **Nunca se relaja por cobertura** — un producto con la medida equivocada no sirve sin importar cuántos otros del catálogo también la tengan mal. Sólo aplica si `required_attributes[clave]` no es `""` (string vacío = "sólo tiene que existir", cualquier valor sirve). |
| 8 | Presupuesto | el precio efectivo excede el remanente del presupuesto | `OVER_BUDGET` | Sin presupuesto declarado, el criterio no se evalúa. |

> **Criterio 8, detalle:** el presupuesto se asigna por slot en proporción a
> `priority` (1 = imprescindible recibe más). Si al terminar quedan slots sin
> resolver por presupuesto, se retiran los `is_optional=True` de mayor precio y se
> reintenta una vez. Si un slot queda sin resolver, se omite de las recomendaciones
> y se explica el motivo en el chat. Una categoría sin opciones también se oculta.

**Especificaciones de producto:** `attribute_requirements` modela de forma
uniforme igualdad, mínimos, máximos, intervalos y pertenencia a un rango para
cualquier categoría. Las claves, alias, unidades, conversiones y patrones de
extracción viven en `app/data/attribute_definitions.json`. Cada restricción
debe citar en `source_text` el texto literal del usuario; una especificación
inferida no filtra productos como si hubiera sido confirmada. El adaptador
puede derivar metadatos desde el nombre sólo mediante patrones declarados y
marca su procedencia como `DERIVED`. Nunca se convierte automáticamente una
especificación en otra: peso no implica talla, ni modelo implica medida.

Presentación de producto empaquetado también es especificación dura:
`units_per_pack` ("paquete de 12"), `volume_ml` ("de 500 ml", convierte `l`),
`sugar_free`, `flavor`, `container_type` (doc 01 §3.2). "Galletas Oreo paquete de
12" deja fuera a los paquetes de 6 y a cualquier galleta que no declare cuántas
unidades trae. La marca **no** es especificación dura: ver §3.2.

Los diagnósticos de faltantes se calculan sólo entre candidatos relacionados
con el slot. Si queda alguno con stock, se explica su problema de compatibilidad
o información; no se anuncia que todo está agotado por contar otros descartes.

---

## 3. Capa 2 — La fórmula

```
score(p) = Σ  w'ᵢ · nᵢ(p)          con   w'ᵢ = wᵢ / Σ wⱼ
          i∈S                                     j∈S

  S  = señales vivas para este candidate set (§4)
  nᵢ = señal i normalizada a [0,1]
  w'ᵢ = peso renormalizado; Σ w'ᵢ = 1  ⇒  score ∈ [0,1] siempre
```

### 3.1 Normalización por señal

| Señal | Rango | Normalización | Nota |
|---|---|---|---|
| `relevance` | 0–1 | `0.45·attr_match + 0.35·text_match + 0.20·category_match` | `attr_match` = fracción de `slot.required_attributes` satisfechos; `text_match` = BM25 de FTS5 sobre los `keywords` del slot, escalado por el máximo del set; `category_match` ∈ {0, 1}. |
| `margin` | 0–1 | min-max sobre el candidate set del slot | Se usa el set del slot, no el catálogo entero: comparar el margen de un bloqueador contra el de una llanta no significa nada. |
| `turnover` | 0–1 | `0.70·minmax(turnover_index) + 0.30·(1 − pct(inventory_age_days))` | Si sólo hay una de las dos, esa se lleva el 100 %. Antigüedad **invertida**: más viejo = mejor candidato a liquidar. |
| `private_label` | {0,1} | binaria | |
| `promo` | {0,1} | binaria, 1 si hay promo vigente a la fecha | Sin fechas de vigencia, toda promo se asume vigente. |

> **Decisión asumida — min-max y no z-score:** min-max mantiene todo en [0,1], hace
> los números legibles en pantalla durante el Modo Negocio y no explota con
> distribuciones sesgadas. Con un candidate set de menos de 3 elementos, min-max
> degrada a 0.5 constante para esa señal (evita que el único candidato saque 1.0
> artificial en todo).

### 3.2 Preferencia de marca — un nivel de orden, no una señal

Si el cliente nombra una marca ("quiero comprar coca-cola"), el slot trae
`preferred_brands=["coca-cola"]`. El motor:

1. **No la usa en el filtro duro ni en el filtro de texto.** Un "Helado sabor Oreo" en
   un slot de galletas sigue fuera por `NO_TEXT_MATCH`; una Coca-Cola sin stock sigue
   fuera por `OUT_OF_STOCK`.
2. **No la suma al score.** `total_score` es exactamente el mismo con o sin marca pedida.
   Por eso no hay peso de marca que calibrar ni slider que la anule.
3. **Ordena en dos niveles:** `(descartado, no_es_la_marca, −score)`. Todo lo de la marca
   pedida va arriba; dentro de ese nivel manda el score normal, así que entre
   presentaciones de la misma marca gana la de mejor relevancia, margen, rotación o
   promo. Debajo quedan las demás marcas, también por score.

La comparación es por `brand_key`: palabras sin tildes ni mayúsculas, sin el token
`demo`, unidas sin separadores. "Coca-Cola", "coca cola" y "cocacola" son la misma
marca. Un producto sin `brand` no coincide (ausente ≠ otra marca, pero tampoco se puede
afirmar que sea la pedida) y queda en el nivel inferior sin descartarse.

`ScoredProduct.matches_preferred_brand` registra el resultado (`None` si el slot no pidió
marca) y `ResolvedSlot.preferred_brand_found` resume si el `picked` es de esa marca.
Cuando no lo es, la respuesta lo dice: "No encontré Big Cola disponible para gaseosa
cola; te muestro otras marcas."

> **Decisión asumida — nivel y no peso:** un peso de marca en la relevancia podría
> perder contra un producto de otra marca con más margen o promo, y el cliente vería
> Pepsi primero después de pedir Coca-Cola. Un nivel es predecible para el cliente y
> deja intacta la palanca comercial donde tiene sentido: elegir **cuál** Coca-Cola.

---

## 4. Degradación: qué pasa cuando falta una señal

Es la regla más importante del motor y la que se explica al jurado.

**Regla de cobertura (umbral 60 %).** Una señal está viva para un candidate set si
al menos el **60 %** de sus productos la tienen.

| Caso | Comportamiento |
|---|---|
| Cobertura ≥ 60 % | La señal **vive**. Los productos que no la tienen reciben la **mediana del set**, marcada `DERIVED`, y su tarjeta lleva badge "estimado". |
| Cobertura < 60 % | La señal **muere** para todo el set. Se elimina de `S`, su peso se reparte proporcionalmente entre las vivas, y su slider del Modo Negocio queda **deshabilitado con la leyenda "no disponible en este dataset"**. |
| Cobertura 0 % pero hay proxy derivable | Se aplica el proxy del doc 01 §3.5 y la señal vive marcada `DERIVED` o `SIMULATED`. |

**Lo que NO se hace nunca: asignar 0 a una señal ausente.** Cero no significa
"desconocido", significa "el peor del set". Castiga al producto por un defecto del
dataset. Contraejemplo numérico en §6, Ejemplo 2b.

**Piso de relevancia.** `w_relevance` nunca baja de **0.20** por mucho que se suban
los sliders comerciales. El negocio puede inclinar el ranking; no puede secuestrarlo.
Es una decisión de producto, no técnica, y es un buen argumento ante el jurado.

**Caso extremo:** si mueren todas las señales de negocio, `S = {relevance}`, el peso
es 1.0, el sistema se comporta como un buscador honesto y el Modo Negocio se muestra
**vacío con explicación**, no oculto. Ver el dataset no tiene margen es información,
no un fallo.

---

## 5. Modo Negocio — los tres sliders

| Slider | Escribe | Rango | Default | Lectura de negocio |
|---|---|---|---|---|
| **Prioridad de margen** | `w_margin` | 0.00 – 0.50 | 0.20 | Cuánto empujar rentabilidad sobre ajuste al cliente. |
| **Liquidar inventario** | `w_turnover` | 0.00 – 0.40 | 0.15 | Combina rotación y antigüedad: sube el stock viejo. |
| **Impulso marca propia** | `w_private_label` | 0.00 – 0.30 | 0.08 | Palanca de mix de marca. |

`w_promo` queda fijo en **0.07** (no es palanca comercial, es higiene: lo que está en
promoción debe verse).

`w_relevance = max(0.20, 1 − w_margin − w_turnover − w_private_label − w_promo)`,
y después todo se renormaliza para que sume 1.

**Panel de impacto** (lo que el jurado mira mientras arrastra):

- **Ticket estimado** de la canasta y su delta contra el default.
- **Margen ponderado** de la canasta y su delta.
- **Ítems por canasta** y **categorías cubiertas**.
- **Uplift vs. canasta monocategoría** (§7).

> **Decisión asumida:** los sliders reordenan **en vivo**, sin recargar, vía un
> `hx-post` con debounce de 250 ms que devuelve sólo el fragmento de la lista. El
> recálculo es sobre el candidate set ya filtrado y cacheado en memoria — no vuelve a
> tocar SQLite ni al LLM. Esto es lo que hace que el gesto se vea instantáneo, que es
> el 90 % del efecto "wow".

---

## 6. Ejemplos numéricos resueltos

### Ejemplo 1 — Todas las señales presentes, pesos por defecto

Slot "Protección solar". Pesos: rel 0.50 · mar 0.20 · rot 0.15 · mp 0.08 · promo 0.07
(suman 1, no hay que renormalizar).

| Producto | rel | margen | rotación | marca propia | promo |
|---|---|---|---|---|---|
| A — Bloqueador líder SPF50 | 0.92 | 0.30 | 0.55 | 0 | 1 |
| B — Bloqueador marca propia SPF50 | 0.78 | 0.85 | 0.70 | 1 | 0 |
| C — Bloqueador SPF30 | 0.85 | 0.40 | 0.20 | 0 | 0 |

```
A = 0.92·0.50 + 0.30·0.20 + 0.55·0.15 + 0·0.08 + 1·0.07
  = 0.4600 + 0.0600 + 0.0825 + 0.0000 + 0.0700 = 0.6725
B = 0.78·0.50 + 0.85·0.20 + 0.70·0.15 + 1·0.08 + 0·0.07
  = 0.3900 + 0.1700 + 0.1050 + 0.0800 + 0.0000 = 0.7450
C = 0.85·0.50 + 0.40·0.20 + 0.20·0.15 + 0·0.08 + 0·0.07
  = 0.4250 + 0.0800 + 0.0300 + 0.0000 + 0.0000 = 0.5350
```

**Orden: B (0.745) > A (0.673) > C (0.535).** La marca propia gana pese a ser menos
relevante que A, porque acumula margen + rotación + marca propia. Eso es exactamente
el comportamiento buscado, y es defendible porque se ve descompuesto en pantalla.

---

### Ejemplo 2a — El dataset no trae margen (cobertura 0 %)

La señal muere. `S = {rel, rot, mp, promo}`, suma de pesos crudos
`0.50 + 0.15 + 0.08 + 0.07 = 0.80`. Renormalización:

```
w'_rel   = 0.50/0.80 = 0.6250
w'_rot   = 0.15/0.80 = 0.1875
w'_mp    = 0.08/0.80 = 0.1000
w'_promo = 0.07/0.80 = 0.0875      Σ = 1.0000  ✓
```

| Producto | rel | rotación | marca propia | promo |
|---|---|---|---|---|
| D — Organizador de maletera marca propia | 0.60 | 0.90 | 1 | 0 |
| E — Organizador importado en oferta | 0.80 | 0.20 | 0 | 1 |

```
D = 0.60·0.6250 + 0.90·0.1875 + 1·0.1000 + 0·0.0875
  = 0.3750 + 0.1688 + 0.1000 + 0.0000 = 0.6438
E = 0.80·0.6250 + 0.20·0.1875 + 0·0.1000 + 1·0.0875
  = 0.5000 + 0.0375 + 0.0000 + 0.0875 = 0.6250
```

**Orden: D (0.644) > E (0.625).** El score sigue en [0,1] y sigue siendo legible. En
la UI, el slider de margen aparece gris con "no disponible en este dataset" — y esa
franqueza es un punto a favor, no una disculpa.

---

### Ejemplo 2b — Contraejemplo: por qué "margen ausente = 0" está mal

Ahora la cobertura de margen es **70 %** (vive), y el producto E es de los que no lo
traen. La mediana de margen del set es **0.55**.

| | rel | margen | rotación | mp | promo | score |
|---|---|---|---|---|---|---|
| D (margen real 0.62) | 0.60 | 0.62 | 0.90 | 1 | 0 | **0.6390** |
| E — con mediana imputada | 0.80 | *0.55* | 0.20 | 0 | 1 | **0.6100** |
| E — con cero (incorrecto) | 0.80 | 0.00 | 0.20 | 0 | 1 | **0.5000** |

```
D          = 0.3000 + 0.1240 + 0.1350 + 0.0800 + 0.0000 = 0.6390
E mediana  = 0.4000 + 0.1100 + 0.0300 + 0.0000 + 0.0700 = 0.6100
E cero     = 0.4000 + 0.0000 + 0.0300 + 0.0000 + 0.0700 = 0.5000
```

Usar cero le cuesta a E **0.11 puntos** y amplía la brecha contra D de 0.029 a 0.139.
E no es peor producto: es un producto peor documentado. El motor distingue esas dos
cosas; un `COALESCE(margen, 0)` no.

---

### Ejemplo 3 — El slider invierte el top-2 (el momento de la demo)

Slot "Llanta 185/65R15". Ambos pasaron el fitment.

| Producto | rel | margen | rotación | mp | promo |
|---|---|---|---|---|---|
| F — Llanta marca líder, la más buscada | 0.95 | 0.35 | 0.30 | 0 | 0 |
| G — Llanta marca propia, stock antiguo | 0.50 | 0.70 | 0.60 | 1 | 0 |

**Con pesos por defecto** (rel 0.50 · mar 0.20 · rot 0.15 · mp 0.08 · promo 0.07):

```
F = 0.4750 + 0.0700 + 0.0450 + 0.0000 + 0.0000 = 0.5900   ← gana
G = 0.2500 + 0.1400 + 0.0900 + 0.0800 + 0.0000 = 0.5600
```

**El jurado sube los tres sliders** a margen 0.45 · liquidar 0.30 · marca propia 0.20:

```
w_rel crudo = max(0.20, 1 − 0.45 − 0.30 − 0.20 − 0.07) = max(0.20, −0.02) = 0.20
Σ crudo     = 0.20 + 0.45 + 0.30 + 0.20 + 0.07 = 1.22
w'_rel = 0.1639   w'_mar = 0.3689   w'_rot = 0.2459   w'_mp = 0.1639   w'_promo = 0.0574

F = 0.95·0.1639 + 0.35·0.3689 + 0.30·0.2459 + 0 + 0
  = 0.1557 + 0.1291 + 0.0738 = 0.3586
G = 0.50·0.1639 + 0.70·0.3689 + 0.60·0.2459 + 1·0.1639 + 0
  = 0.0819 + 0.2582 + 0.1475 + 0.1639 = 0.6515   ← gana
```

**Se invierte: G (0.652) desplaza a F (0.359).** Y el piso de relevancia se activó: el
0.20 de `w_rel` es lo que impide que la llanta marca propia gane aunque no sirva. Ese
detalle, dicho en voz alta, es la diferencia entre "un ranking manipulable" y "un
ranking gobernable".

### Ejemplo 4 — Marca pedida: el nivel reordena, el score no cambia

Catálogo real, slot "Gaseosa cola" con keywords `gaseosa, gaseosa cola, cola, refresco`,
pesos por defecto. Mismos `total_score` en ambas columnas:

| Producto | Marca | Score | Sin marca pedida | `preferred_brands=["Coca-Cola"]` |
|---|---|---|---|---|
| BRD-002 Gaseosa cola 1.5L | Coca-Cola | 0.855 | 1 | 1 |
| BRD-007 Gaseosa cola 1.5L | Pepsi | 0.813 | **2** | después de todas las Coca-Cola |
| BRD-003 Gaseosa cola 3L | Coca-Cola | 0.812 | 3 | **2** |
| BRD-004 Gaseosa cola sin azúcar 1.5L | Coca-Cola | 0.794 | 4 | 3 |
| BRD-001 Gaseosa cola 500ml | Coca-Cola | 0.779 | 5 | 4 |
| SUP-190-1 Gaseosa cola 2L | Coca-Cola | 0.583 | lejos | 5 |

Dentro de Coca-Cola, la 1.5 L gana a la 3 L aunque ésta tenga más margen normalizado
(0.75 vs 0.71): la 1.5 L tiene relevancia 1.0 vs 0.91 y más rotación (0.95 vs 0.91).
Esa es la palanca comercial operando **dentro** de la marca. Y la Coca-Cola de 0.583
queda por encima de la Pepsi de 0.813: el nivel manda sobre el score.

---

## 7. Uplift vs. canasta monocategoría

El KPI que la propuesta ataca es ticket promedio, así que hay que mostrarlo medido.

```
baseline_ticket = Σ  precio_efectivo(slot) · cantidad     (sólo la categoría dominante)
                slots ∈ categoría_dominante

uplift_pct = (estimated_ticket − baseline_ticket) / baseline_ticket
```

Es decir: **qué habría comprado el cliente si sólo hubiéramos resuelto la categoría
obvia de su pedido**, contra lo que se lleva con la canasta cross-categoría.

- Se muestra como "+$ 84 · +47 % de ticket · 3 categorías cubiertas".
- **Si la canasta resulta monocategoría** (`is_cross_category == False`), el uplift se
  muestra como "0 % — esta misión no cruzó categorías" en vez de ocultarse. Honestidad
  otra vez: es el mismo número que valida la tesis cuando sí cruza.
- **Decisión asumida:** el uplift es una comparación estructural dentro de la sesión,
  no una estimación estadística contra ventas históricas. Se dice así al jurado
  (pregunta 5 del doc 04). No se presenta como medición causal.

---

## 8. Capa 3 — Explicación

Cada producto recomendado renderiza, en orden de disponibilidad:

1. **Cita literal** de un documento (`Citation.snippet` + `doc_title` + `locator`).
2. Si no hay documento: **razón estructural** derivada de `component_scores`
   ("cubre el atributo SPF50 que pide la misión; alta rotación").
3. Si no hay ninguna de las dos: estado **"sin respaldo documental"**, explícito.

**El texto de la cita nunca pasa por el LLM.** Se recorta del documento indexado. El
modelo puede redactar la frase de contexto alrededor, nunca el contenido entre
comillas. Esta separación es la respuesta a "¿cómo evitan alucinaciones?".

---

## 9. Parámetros congelados

| Parámetro | Valor | Dónde se toca |
|---|---|---|
| Umbral de cobertura de señal | 60 % | constante del motor |
| Piso de `w_relevance` | 0.20 | constante del motor |
| `w_promo` fijo | 0.07 | constante del motor |
| Mezcla rotación / antigüedad | 0.70 / 0.30 | constante del motor |
| Tamaño mínimo de set para min-max | 3 | constante del motor |
| Candidatos por slot antes de rankear | 50 | consulta SQL |
| Alternativas mostradas por slot | 3 | UI |
| Descartes mostrados por slot | 3 | UI |
| Debounce de sliders | 250 ms | HTMX |
| Orden por marca pedida | nivel: `(descartado, no_es_la_marca, −score)` | `scoring._order` |

**No se tunea nada de esto durante la prueba salvo que un dato real lo obligue.**
Cada minuto gastado ajustando pesos es un minuto que no se gasta en que la demo
corra. Los defaults ya producen un orden defendible.
