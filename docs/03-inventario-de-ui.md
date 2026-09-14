# 03 — Inventario de UI

> Pantallas, componentes, estados y responsive. Stack: **FastAPI + Jinja2 + HTMX +
> Tailwind por CDN**. Sin build step, sin bundler, sin framework de front.
>
> Leyenda: **[N]** = núcleo innegociable · **[W]** = wow · **[S]** = sacrificable
> (orden de corte en el doc 05).

---

## 1. Mapa de pantallas

```
  ┌─────────────────────────────────────────┐
  │ P1  ENTRADA DE MISIÓN            [N]    │   "/"
  │  textarea + 3 chips de ejemplo          │
  └────────────────┬────────────────────────┘
                   │ POST /mission
  ┌────────────────▼────────────────────────┐
  │ P2  CANASTA                      [N]    │   "/mission/{id}"
  │  cabecera de misión                     │
  │  ├ SlotCard × N   (agrupados por cat.)  │
  │  ├ BasketSummary (sticky)               │
  │  └ BusinessModeToggle          [W]      │
  └───┬──────────────────┬──────────────┬───┘
      │                  │              │
  ┌───▼──────────┐ ┌─────▼────────┐ ┌───▼──────────────┐
  │ P3 DETALLE   │ │ P4 COMPARADOR│ │ P5 DIAGNÓSTICO   │
  │ /product/{id}│ │ ?compare=... │ │ /diagnostics     │
  │     [N]      │ │     [S]      │ │     [W]          │
  └──────────────┘ └──────────────┘ └──────────────────┘
```

**Decisión asumida:** el Modo Negocio **no es una pantalla**, es una capa sobre P2.
Un toggle que expande cada tarjeta y despliega el panel de pesos. Mismo contexto,
mismos productos, misma canasta — el jurado ve *el mismo resultado con otra lente*,
que es mucho más contundente que navegar a otra vista.

---

## 2. P1 — Entrada de misión **[N]**

Una pantalla, un campo, cero fricción. El jurado escribe y pasan cosas.

```
┌──────────────────────────────────────────────────────┐
│              ¿Qué necesitas resolver?                │
│  ┌────────────────────────────────────────────────┐  │
│  │ Me voy con los niños a la playa el feriado     │  │
│  │                                                │  │
│  └────────────────────────────────────────────────┘  │
│  [ Viaje a la playa ] [ Revisión del carro ]         │
│  [ Mudanza a depto chico ]      ← chips semilla      │
│                                                      │
│  Tienda: [ Todas ▾ ]   Presupuesto: [ opcional ]     │
│                        ( Armar mi canasta → )        │
└──────────────────────────────────────────────────────┘
```

| Componente | Tipo | Estados |
|---|---|---|
| `MissionInput` | textarea + submit | **vacío**: placeholder rotativo con un ejemplo real · **cargando**: botón con spinner + texto "Interpretando tu necesidad…" · **error**: banner rojo con "No pude interpretar eso" + los chips como salida · límite 500 caracteres |
| `SeedChips` | 3 botones | Rellenan el textarea **sin enviar** (el jurado ve el texto antes de que pase nada). Son las 3 misiones cacheadas del doc 04 → latencia cero y demo a prueba de red. |
| `StoreSelect` | select | **oculto por completo** si no hay `store_id` real en el dataset. No se muestra deshabilitado: un control muerto es peor que ningún control. |
| `BudgetInput` | number | Opcional siempre. Vacío = sin restricción de presupuesto. |

> **Sobre la latencia del LLM:** la interpretación tarda 1–3 s. El botón pasa a
> "Interpretando tu necesidad…" y bajo él aparecen los slots a medida que se resuelven
> (respuesta HTMX en streaming de fragmentos). Si el streaming da problemas antes de
> T+3:00, degrada a un spinner simple — **[S]**.

---

## 3. P2 — Canasta **[N]** · la pantalla que decide la prueba

```
┌────────────────────────────────────────────────────────────────┐
│ ← Viaje a la playa con niños       [ Modo Negocio ⚪──── ]      │ MissionHeader
│ 3 categorías · 9 ítems · $ 264.50                             │
├────────────────────────────────────────────────────────────────┤
│ 🛒 SUPERMERCADO                                                │ CategoryGroup
│  ┌──────────────────────────────────────────────────────────┐  │
│  │ Protección solar              ×2          $ 29.90 c/u   │  │ SlotCard
│  │ ┌────┐  Bloqueador Marca Propia SPF50                    │  │
│  │ │img │  ✓ En stock  · marca propia · en promoción        │  │
│  │ └────┘  score 0.745                                      │  │
│  │ 📄 "Para niños se recomienda SPF50 o superior"           │  │ CitationBlock
│  │    — Guía de verano 2025, p. 4                           │  │
│  │ [ Ver alternativas (3) ]  [ Por qué no otros (3) ]       │  │
│  └──────────────────────────────────────────────────────────┘  │
│  ┌── Hidratación ×4 ────────────────────────────────────┐ …    │
├────────────────────────────────────────────────────────────────┤
│ 🚗 AUTOS        · 🏠 HOGAR Y ALMACENAJE                         │
├────────────────────────────────────────────────────────────────┤
│ ▸ Total $ 264.50 · 9 ítems · 3 categorías · +47 % ticket      │ BasketSummary
└────────────────────────────────────────────────────────────────┘
```

### 3.1 Componentes y estados

| Componente | Marca | Estados que DEBEN existir |
|---|---|---|
| `MissionHeader` | [N] | normal · **misión no reconocida**: "Interpreté esto como una compra general" + botón reinterpretar |
| `UnderstandingChips` | [N] | un chip por dato declarado · **marca pedida**: chip "🏷️ Marca: Coca-Cola" por cada marca de `preferred_brands`, justo después de las exclusiones · sin datos: chip con el tipo de misión |
| `CategoryGroup` | [N] | normal · **una sola categoría**: se muestra igual, con nota "esta misión no cruzó categorías" (nunca se oculta la evidencia en contra) |
| `SlotCard` | [N] | **cargando** (skeleton gris) · **resuelto** · **sin candidatos**: caja punteada con el `label` del slot y el motivo dominante de descarte + botón "relajar filtros" · **error** |
| `ProductRow` | [N] | normal · **sin imagen**: cuadro con la inicial y color por categoría · **disponibilidad desconocida**: badge gris "no verificada" · **señal simulada**: badge ámbar |
| `ProductCard` | [N] | normal · **marca pedida**: píldora índigo "🏷️ Marca que pediste" (`ProductCardVM.requested_brand`); las tarjetas de otras marcas no llevan nada, no un "otra marca" |
| `CitationBlock` | [N] | **con cita**: snippet literal entrecomillado + documento + locator, clic abre el documento · **razón estructural**: texto derivado de `component_scores`, con ícono distinto · **sin respaldo documental**: línea gris explícita, nunca vacío |
| `ScoreBadge` | [N] | oculto en modo cliente salvo hover · visible y descompuesto en Modo Negocio |
| `AlternativesDrawer` | [S] | colapsado por defecto · 3 alternativas · **sin alternativas**: "no hay otro producto que cumpla los filtros" |
| `RejectionDrawer` | [S] | colapsado · hasta 3 descartes con su `ExclusionReason` en lenguaje humano · **sin descartes**: se oculta el botón entero |
| `BasketSummary` | [N] | sticky abajo en móvil, fijo abajo en desktop · **canasta vacía**: "no pude armar ninguna canasta con estos filtros" + botón para quitar restricciones |
| `QtyStepper` | [S] | editar cantidad recalcula total · **degradado**: canasta de solo lectura, los totales siguen correctos |

### 3.2 Traducción de `ExclusionReason` a lenguaje humano

La tabla siguiente queda para diagnósticos y detalle de descartes. En las
recomendaciones del asesor sólo se muestran productos que pasaron los filtros;
los slots y categorías sin opciones se omiten. Si no queda ninguna categoría,
se oculta la sección de recomendaciones.

`app/presentation/advisor_reply.py` formula el mensaje de chat desde el resultado
real: nombra los tipos de producto, la categoría donde se muestran y el número
de opciones visibles cuando hay más de una. Los faltantes se explican allí:
"Por ahora no tengo pañales en stock" si están agotados; si falta verificar un
dato de compatibilidad, se dice eso sin atribuirlo al stock. No se muestran
contadores internos de slots agregados, eliminados o reconciliados.

Si el cliente nombró una marca y el producto elegido del slot no es de esa marca
(`ResolvedSlot.preferred_brand_found is False`), el mensaje agrega "No encontré
{marca} disponible para {necesidad}; te muestro otras marcas." Si sí la hay, no se
agrega nada: el chip y la píldora ya lo muestran.

| Código | Texto en pantalla |
|---|---|
| `OUT_OF_STOCK` | Sin stock en este momento |
| `NOT_IN_SELECTED_STORE` | No disponible en la tienda seleccionada |
| `OVER_BUDGET` | Excede el presupuesto asignado a este ítem |
| `INCOMPATIBLE` | No compatible con el vehículo indicado |
| `WRONG_CATEGORY` | No corresponde a esta necesidad |
| `MISSING_REQUIRED_ATTRIBUTE` | Le falta un atributo que la necesidad exige |
| `DISCONTINUED` | Producto descontinuado |
| `NO_PRICE` | Sin precio publicado |

---

## 4. Modo Negocio **[W]** · la feature de mayor retorno por minuto

Toggle en `MissionHeader`. **No navega.** Transforma P2 en sitio.

```
┌────────────────────────────────────────────────────────────────┐
│ Viaje a la playa con niños          [ Modo Negocio ────⚫ ]     │
├────────────────────────────────────────────────────────────────┤
│ Prioridad de margen      [────⚫──────]  0.20                   │ WeightPanel
│ Liquidar inventario      [──⚫────────]  0.15                   │
│ Impulso marca propia     [─⚫─────────]  0.08                   │
│ Margen ausente en el dataset — slider deshabilitado ⓘ          │  ← estado degradado
├────────────────────────────────────────────────────────────────┤
│ Ticket $ 264.50 (+47 %) · Margen ponderado 31.2 % ·           │ ImpactPanel
│ 9 ítems · 3 categorías                                         │
├────────────────────────────────────────────────────────────────┤
│ Bloqueador Marca Propia SPF50                   score 0.745    │
│  relev 0.390 │ margen 0.170 │ rotac 0.105 │ m.propia 0.080     │ ScoreBreakdown
│  ▓▓▓▓▓▓▓▓▓▓▓▓│▓▓▓▓▓      │▓▓▓        │▓▓                      │
│  margen 62 % ⚠ estimado · rotación 7.1 · 34 días en almacén    │
└────────────────────────────────────────────────────────────────┘
```

| Componente | Estados |
|---|---|
| `BusinessModeToggle` | off (default) · on · **sin ninguna señal viva**: el toggle sigue clicable y muestra el panel con "este dataset no trae señales de negocio; el ranking se ordena sólo por relevancia" — **no se oculta** |
| `WeightPanel` (3 sliders) | activo · **deshabilitado por señal muerta**: slider gris + leyenda "no disponible en este dataset" · botón **Restablecer** siempre visible |
| `ImpactPanel` | normal con deltas en verde/rojo contra el default · **sin margen**: la métrica de margen ponderado se sustituye por "ítems por canasta" |
| `ScoreBreakdown` | barras apiladas por componente + valores crudos · señales `DERIVED` con badge gris, `SIMULATED` con badge ámbar y tooltip explicando la derivación |

**Comportamiento:** `hx-post` con debounce 250 ms sobre el candidate set cacheado en
memoria. Reordena la lista sin recargar y sin volver a llamar al LLM ni a SQLite.
**El reordenamiento visible es el efecto completo** — si no se ve instantáneo, no
convence. Presupuesto: ≤ 35 min de implementación (doc 05).

---

## 5. P3 — Detalle de producto **[N]**

Ficha, atributos, todas las citas, stock por tienda, y en Modo Negocio el desglose
completo. Estados: cargando · normal · **producto sin atributos**: se oculta la tabla
y se muestra sólo descripción · **404**.

## 6. P4 — Comparador **[S]**

Tabla lado a lado de 2–3 productos del mismo slot: precio efectivo, atributos comunes,
disponibilidad, y en Modo Negocio las señales.

| Estado | Comportamiento |
|---|---|
| < 2 seleccionados | Botón deshabilitado con "elige al menos 2" |
| Sin atributos comunes | Se comparan sólo precio, marca, disponibilidad y señales |
| Móvil | **Degrada a tarjetas apiladas** con las diferencias resaltadas; no hay tabla horizontal en 400 px |

> **Corte:** si a T+4:00 el comparador no está, se elimina. Su valor demostrativo ya
> está cubierto por `AlternativesDrawer`, que muestra las 3 alternativas con su score.

## 7. P5 — Diagnóstico de datos **[W]**

Renderiza `AdapterReport`: archivos leídos, productos ingeridos/válidos/rechazados por
motivo, cobertura por campo canónico, y **la lista de features degradadas con su
motivo**.

Cuesta ~20 minutos (es una tabla sobre un objeto que ya existe) y es la respuesta
visual a la pregunta más incómoda del jurado: "¿y cómo sé que esto no está inventando
datos?". Se abre en la demo sólo si preguntan.

---

## 8. Responsive

**Breakpoint único: 768 px.** Uno solo. Cada breakpoint extra es tiempo de prueba y
de depuración que no está presupuestado.

| Elemento | Desktop (≥ 768) | Móvil (< 768) |
|---|---|---|
| Layout de canasta | 2 columnas: slots + resumen lateral sticky | 1 columna; `BasketSummary` fijo abajo |
| `SlotCard` | imagen a la izquierda, texto a la derecha | imagen arriba, apilado |
| `WeightPanel` | panel lateral derecho siempre visible | **hoja inferior desplegable** (`<details>`), colapsada por defecto |
| `ScoreBreakdown` | barras horizontales con etiquetas | barras sin etiquetas, valores en una línea bajo ellas |
| Comparador | tabla | tarjetas apiladas con diferencias resaltadas |
| `CitationBlock` | snippet completo | snippet a 2 líneas con "ver más" |
| Chips semilla | en fila | en columna, ancho completo (targets ≥ 44 px) |

**Se verifica en un teléfono real antes del FEATURE FREEZE, no en el devtools.** El
jurado abrirá la URL de Cloud Run desde su propio celular: un layout roto ahí borra
todo lo demás.

---

## 9. Presupuesto y orden de sacrificio

| Componente | Marca | Minutos | Orden de corte |
|---|---|---|---|
| P1 entrada + chips | [N] | 20 | — |
| P2 canasta + SlotCard + CitationBlock | [N] | 70 | — |
| `BasketSummary` + uplift | [N] | 20 | — |
| Responsive 768 px | [N] | 25 | — |
| **Modo Negocio completo** | [W] | 35 | — |
| P3 detalle | [N] | 15 | — |
| P5 diagnóstico | [W] | 20 | 4.º en caer |
| Fitment con regla real | [W] | 30 | 3.º — degrada a filtro textual |
| `AlternativesDrawer` | [S] | 15 | — |
| `RejectionDrawer` | [S] | 15 | **1.º en caer** |
| P4 comparador | [S] | 30 | **2.º en caer** |
| `QtyStepper` editable | [S] | 20 | degrada a solo lectura |

**Total si entra todo: ~315 min de UI.** Eso **no cabe** junto a la adaptación de
datos, el motor y el deploy. El orden de corte de arriba es la lista real: se
construye de arriba hacia abajo y se corta desde abajo sin negociar.

---

## 10. Decisiones técnicas asumidas

1. **Tailwind por CDN, no compilado.** Warning de consola a cambio de cero build.
2. **HTMX 2 por CDN.** Los sliders y los drawers son `hx-post` que devuelven
   fragmentos Jinja. No hay estado en cliente que sincronizar.
3. **Sin imágenes externas.** Placeholder generado en CSS con inicial y color por
   categoría. Si el dataset trae URLs, se usan con `onerror` al placeholder.
4. **Estado de misión en memoria del proceso**, con TTL de 1 hora, indexado por
   `mission_id`. Cloud Run con `min-instances=1` durante la demo lo hace seguro. Si
   la instancia se recicla, la misión se reinterpreta desde la caché de semillas.
5. **Sin autenticación, sin cuentas, sin carrito persistente.** Nada de eso se
   demuestra en 8 minutos.
