# 06 — Riesgos y planes B

> Una ficha por supuesto que puede salir falso. Cada una con: **síntoma detectable**,
> **cuándo se detecta**, **plan B concreto**, **costo en minutos** y **qué feature
> degrada**.
>
> El criterio transversal: **ningún riesgo puede matar la demo, sólo encogerla.**
> Si un plan B no cabe en su ventana de tiempo, no es un plan B.

---

## R1 — No hay documentos útiles (o son escaneos sin texto)

| | |
|---|---|
| **Síntoma** | La extracción devuelve vacío o basura pese al OCR de docling; los documentos son políticas corporativas sin relación con productos; o simplemente no hay documentos. |
| **Detección** | T+0:15, triage (pregunta 6 del doc 01 §5). |
| **Impacto** | Muere la feature "recomendación con cita a la fuente", que es **uno de los cinco features núcleo**. |

**Plan B escalonado:**

1. **Si hay texto pero no es sobre productos** (10 min): indexar igual (por el tramo que corresponda,
   doc 01 §8.2) y citar sólo cuando haya coincidencia real. Los productos sin match muestran "sin respaldo
   documental". Cobertura parcial es mejor que ninguna.
2. **Si no hay texto útil** (20 min): la "cita" degrada a **razón estructural**
   derivada de `component_scores` + los atributos del producto: *"cubre el atributo
   SPF50 que pide esta necesidad · alta rotación"*. Ícono distinto al de cita, para
   que nunca se confunda con respaldo documental.
3. **Último recurso** (15 min): escribir a mano un `documentos/guia-misiones.md` de
   ~40 líneas con criterios de selección por misión (SPF para niños, presión de
   llantas antes de viaje, etc.), indexarlo y citarlo. **Se declara al jurado**:
   *"el insumo no traía documentos aprovechables, así que escribí una guía mínima para
   demostrar el mecanismo de citación; con documentos reales el mecanismo es idéntico"*.

**Costo: 10–20 min.** **Degrada:** cita → razón estructural.

---

## R2 — La base de datos no tiene margen

| | |
|---|---|
| **Síntoma** | No hay columna de costo, de margen ni de utilidad. |
| **Detección** | T+0:15, triage (pregunta 2). |
| **Impacto** | El Modo Negocio pierde su señal más vendedora. |

**Plan B escalonado:**

1. **Si hay costo** (5 min): `margin_pct = (pvp − costo) / pvp` → `DERIVED`. Sin badge
   de advertencia fuerte; es una derivación estándar.
2. **Si hay una jerarquía de categorías confiable** (15 min): tabla de márgenes típicos
   de retail por categoría (abarrotes 18–25 %, marca propia +8–12 pp, llantas 20–30 %,
   decoración 35–50 %) → `DERIVED`, badge gris "estimado", tooltip con la fuente de la
   estimación.
3. **Si no hay nada** (10 min): `SIMULATED` con badge ámbar visible en cada tarjeta y
   una nota permanente en el `WeightPanel`.
4. **Si se decide no simular**: la señal muere, el slider queda deshabilitado con
   "no disponible en este dataset", y su peso se redistribuye (doc 02 §4).

**Costo: 5–15 min.** **Degrada:** margen real → estimado o simulado, siempre etiquetado.

> **Nota de demo:** la opción 2 es la mejor. Un margen estimado por categoría, **dicho
> en voz alta como estimado**, demuestra criterio de retail y no compromete la
> honestidad. Es preferible a un slider gris.

---

## R3 — No hay dato de stock

| | |
|---|---|
| **Síntoma** | No hay columna de inventario, o hay una sola tienda, o está 100 % en nulos. |
| **Detección** | T+0:15, triage (pregunta 3). |
| **Impacto** | Se debilita "validación contra stock/precio/tienda", uno de los núcleo. |

**Plan B:**

1. Todos los productos reciben `StoreStock(store_id="__ALL__", status=UNKNOWN)`.
2. El criterio 3 del filtro duro **se desactiva entero** — recordar que `UNKNOWN` no
   descarta, porque descartaría el catálogo completo.
3. El `StoreSelect` de P1 **se oculta** (no se muestra deshabilitado).
4. Cada tarjeta lleva badge gris "disponibilidad no verificada".
5. El filtro duro degrada a `is_active`, que sigue siendo una validación real contra la
   base — el argumento "la BD decide, no el modelo" **no se pierde**.

**Costo: 10 min.** **Degrada:** validación de stock → validación de producto activo.

> Si hay stock pero **no por tienda**: se conserva el estado agregado y sólo se oculta
> el selector. Cuesta 5 min y conserva el badge verde "En stock", que en pantalla vale
> bastante.

---

## R4 — No hay atributos de compatibilidad

| | |
|---|---|
| **Síntoma** | Los productos de auto no traen medida, ni aplicación por vehículo, ni tabla de fitment. |
| **Detección** | T+0:15 (pregunta 5), confirmado a T+3:30. |
| **Impacto** | Muere el fitment, que es el **escenario 2 completo** de la demo. |

**Plan B escalonado:**

1. **Si la medida está en el nombre** (20 min): extraer con regex
   `\d{3}/\d{2}[RZ]?\d{2}` a `attributes["tire_size"]` durante el ETL. El fitment pasa
   a ser real aunque el dato venga sucio — **esta suele funcionar y vale la pena
   intentarla primero**.
2. **Si no hay medidas en ningún lado** (10 min): la verificación degrada a
   coincidencia textual sobre `name` + `description`. `compatibility_checked=False`, y
   la UI dice "verificación por coincidencia de texto" en vez de "compatibilidad
   verificada". **No se miente sobre el nivel de verificación.**
3. **Si la categoría auto es demasiado pobre** (0 min extra): **se sustituye el
   escenario 2 de la demo** por una segunda misión con presupuesto o una misión de
   evento, y se dice: *"el dataset de la prueba no trae atributos de compatibilidad; la
   regla ya está modelada en el esquema y sólo espera el dato"* — mostrando
   `CompatibilityRule` si preguntan.

**Costo: 0–20 min.** **Degrada:** fitment verificado → coincidencia textual → escenario
sustituido.

---

## R5 — El volumen es enorme (> 1M filas)

| | |
|---|---|
| **Síntoma** | El CSV pesa cientos de MB; `pd.read_csv` se queda sin memoria; el SQLite supera 500 MB. |
| **Detección** | T+0:15, al intentar abrir el archivo. |
| **Impacto** | La imagen Docker no cabe, el deploy tarda, el ETL se come el presupuesto. |

**Plan B:**

1. Leer con `chunksize=50_000` y **nunca** cargar el archivo entero.
2. **Muestreo estratificado** a ~20 000 productos: proporcional por categoría canónica,
   con mínimo garantizado de 2 000 por categoría para que las tres sobrevivan, y
   **inclusión forzada** de todo producto que haga match con los keywords de los 3
   escenarios de la demo (esto es lo crítico: el muestreo no puede vaciar la demo).
3. Índice FTS5 sólo sobre el subconjunto.
4. Se declara al jurado como decisión consciente: *"el catálogo completo son 1.2
   millones de SKU; para la demo trabajo con una muestra estratificada de 20 000 porque
   el costo de ranking depende del candidate set, no del catálogo"* — que además es el
   pie perfecto para la pregunta P4 del doc 04.

**Costo: 20 min.** **Degrada:** nada visible. Sólo hay que decirlo.

> **Techo duro:** `catalog.db` ≤ 50 MB. Por encima, el ciclo build/push/deploy se
> vuelve demasiado lento para iterar con el reloj corriendo.

---

## R6 — Los insumos vienen en formato hostil

| | |
|---|---|
| **Síntoma** | PDF escaneado, base Access, dump propietario, XLSX con celdas combinadas y encabezados en la fila 7, o un ZIP con 40 archivos sin documentar. |
| **Detección** | T+0:15. |
| **Impacto** | Potencialmente letal: se come el presupuesto entero de adaptación. |

**Plan B por caso:**

| Formato | Ataque | Minutos |
|---|---|---|
| XLSX sucio | `pd.read_excel(skiprows=N)`, `ffill` en columnas combinadas, renombrado manual | 20 |
| Access `.mdb` | `mdb-export` a CSV; si falla, abrir en LibreOffice y exportar a mano | 25 |
| Dump Postgres | `grep -E '^COPY'` para extraer sólo las tablas necesarias | 20 |
| PDF escaneado | **Docling trae OCR** (doc 07 §2): se intenta una vez. Si falla o tarda >10 min, va a R1 plan B. | 10 |
| ZIP con 40 archivos | Ordenar por tamaño, quedarse con los 2 más grandes, ignorar el resto | 10 |

**🔴 Umbral duro de 30 minutos.** Si a T+0:45 no hay un DataFrame limpio, se abandona el
parseo automático y se hace **extracción manual de 150–300 productos** representativos
de las tres categorías, a mano o con copiar/pegar, hacia un CSV propio.

Suena a derrota y no lo es: una demo con 200 productos reales bien mapeados y tres
escenarios que funcionan derrota por goleada a una app vacía con un ETL elegante. Y la
conversación con el jurado queda en el producto, no en el parser.

**Costo: 0–30 min.** **Degrada:** volumen del catálogo.

---

## R7 — ⚠️ No hay tres categorías en el dataset

| | |
|---|---|
| **Síntoma** | El dataset trae sólo supermercado, o sólo dos de las tres categorías. |
| **Detección** | T+0:15, triage (pregunta 4). |
| **Impacto** | **El más grave de todos: la tesis completa de la propuesta es la canasta cross-categoría.** |

**Plan B:**

1. **Si hay dos categorías** (0 min): la tesis se sostiene igual. Cross-categoría
   significa "cruzar categorías", no "cruzar exactamente tres". Se ajustan los
   escenarios del doc 04 a las dos disponibles y no se menciona la tercera como falta.
2. **Si hay una sola categoría** (30 min): **decisión difícil.** Se crea un catálogo
   complementario mínimo de ~40 productos para las categorías faltantes,
   **visiblemente marcado como demostrativo** en la UI (badge ámbar por producto +
   banner en la canasta), y se dice al jurado desde la primera frase:
   > *"El insumo sólo traía supermercado. Como la tesis de la propuesta es la canasta
   > cross-categoría, agregué 40 productos de demostración en autos y hogar, marcados
   > como tales en pantalla. Todo lo que ven de supermercado es dato real del insumo."*

   Declararlo **antes** de que lo descubran convierte un problema en una decisión de
   producto. Descubierto por ellos, es un golpe del que no se vuelve.
3. **Alternativa más conservadora** (0 min): abandonar el eje cross-categoría y pivotar
   la tesis a "misión de compra dentro de la categoría" (canasta de misión: parrilla,
   lonchera escolar, limpieza profunda). Se pierde el diferencial, pero todo lo demás
   —filtro duro, scoring, Modo Negocio, citas— sigue intacto y siendo bueno.

**Costo: 0–30 min.** **Degrada:** la tesis central. **Leer esta ficha completa antes de
decidir; es la única del documento que cambia el discurso y no sólo una feature.**

---

## R8 — El LLM falla o es inconsistente

| | |
|---|---|
| **Síntoma** | Latencia > 5 s, JSON inválido, o slots sin sentido. |
| **Detección** | T+2:45 – 3:15. |
| **Impacto** | La entrada por necesidad, que es la puerta de entrada de toda la demo. |

**Plan B:**

1. **Salida estructurada forzada** con `tool_use` / JSON schema y reintento único.
2. **Caché en disco de las 3 misiones semilla** apenas funcionen. Los chips del doc 04
   leen de ahí: **la demo nunca llama a la API en vivo.**
3. **Fallback determinista:** diccionario de palabras clave → `MissionKind` →
   plantilla de slots pre-escrita. Cubre los 3 escenarios y cualquier frase parecida.
4. Si el jurado escribe una frase libre y el fallback no la reconoce: `MissionKind.GENERIC`
   arma slots desde los sustantivos extraídos. Peor resultado, pero **nunca pantalla en
   blanco**.

**Costo: 15 min** (el fallback ya está pre-construido). **Degrada:** calidad de la
interpretación en frases no vistas.

---

## R9 — Riesgos de infraestructura

| Riesgo | Mitigación | Costo |
|---|---|---|
| Cloud Run no despliega (IAM, cuota, API sin habilitar) | Deploy de prueba **el día anterior** + deploy de humo a T+1:45. Corte a T+2:00 → túnel. | 0 (preventivo) |
| Cold start en la demo | `min-instances=1` desde 30 min antes; abrir la URL uno mismo justo antes. | 2 min |
| Imagen demasiado grande | `python:3.12-slim`, `uv sync --no-dev`, `.dockerignore` con los insumos crudos. `catalog.db` ≤ 50 MB. | 0 (preventivo) |
| Caída de wifi durante la demo | 6 capturas en `respaldo/` + copia local en pestaña de respaldo. | 15 min (bloque T+5:00) |
| API key expuesta | Variable de entorno en Cloud Run, nunca en la imagen ni en el repo. `.env` en `.gitignore` (ya está). | 0 |
| Se pasa la cuota del LLM | Caché de semillas: la demo no consume cuota. | 0 |

---

## R10 — Claude Code caído o sin cuota

| | |
|---|---|
| **Síntoma** | Sin red, cuota agotada, o latencia inutilizable. |
| **Detección** | En cualquier momento. Sin aviso previo. |
| **Impacto** | Está en el camino crítico: escribe la mayoría del código. |

**Plan B: ninguno hace falta, y eso es por diseño.** Los bloques del doc 05 están
escritos **sin** asumir compresión por agente (doc 07 §7.2). El tiempo que el agente
libera es techo, no piso. Si se cae, seguís con el cronograma tal cual —más lento— y
llegás igual, porque los cortes ya estaban calculados para ese caso.

Lo que sí se pierde es el excedente: el comparador y la pantalla de diagnóstico vuelven
a ser sacrificables.

**Mitigaciones (noche anterior):** verificar cuota disponible y tener hotspot del celular
probado. Es la única herramienta del plan cuyo agotamiento no avisa con anticipación.

**Costo: 0 min de replanificación.** **Degrada:** el excedente de features, no el núcleo.

---

## 10. Matriz resumen

| Riesgo | Prob. | Impacto | Costo del plan B | Feature degradada |
|---|---|---|---|---|
| R1 sin documentos | Media | Alto | 10–20 min | cita → razón estructural |
| R2 sin margen | **Alta** | Alto | 5–15 min | margen real → estimado |
| R3 sin stock | Media | Medio | 10 min | stock → producto activo |
| R4 sin fitment | **Alta** | Medio | 0–20 min | fitment → texto / escenario sustituido |
| R5 volumen enorme | Baja | Medio | 20 min | tamaño del catálogo |
| R6 formato hostil | Media | **Letal** | 0–30 min | volumen del catálogo |
| R7 una sola categoría | Baja | **Letal** | 0–30 min | **la tesis** |
| R8 LLM inconsistente | Media | Alto | 15 min | calidad de interpretación |
| R9 infraestructura | Media | Alto | 0–15 min | ninguna (preventivo) |
| R10 Claude Code caído | Baja | Medio | **0 min** | excedente (comparador, diagnóstico) |

**Peor caso realista acumulado: R2 + R4 + R6 = ~65 minutos de planes B.** Cabe dentro
del bloque de adaptación si — y sólo si — se respetan los cortes de T+0:45 y T+1:15 del
doc 05. **Ese es el margen completo. No hay más.**
