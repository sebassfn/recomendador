# 05 — Plan de 6 horas

> Reloj absoluto desde **T+0:00** = momento en que entregan los insumos.
> **FEATURE FREEZE: T+4:30.** No es una sugerencia.

---

## 0. Lo que se pre-construye ANTES de la prueba

**Decisión asumida (zona gris confirmada con el usuario):** se lleva andamiaje
**genérico**, sin nada específico del dominio del retailer ni de los insumos. Es
defendible: es el equivalente a llevar un editor configurado.

| Pieza | Estado al llegar | Minutos que ahorra |
|---|---|---|
| `app/domain/schema.py` | ✅ escrito y verificado | 45 |
| Scaffold FastAPI + Jinja + HTMX + layout Tailwind | app "hola mundo" que corre | 40 |
| Motor de scoring genérico (`score()`, normalizadores, renormalización) | escrito contra el esquema, con datos falsos | 50 |
| Esqueleto del adaptador (`adapter.py` con las funciones vacías y sus firmas) | firmas + `AdapterReport` | 20 |
| `Dockerfile` + `.dockerignore` + `uv` lock | probado localmente | 25 |
| **Proyecto GCP, Artifact Registry, service account, `gcloud` autenticado** | ✅ creado y probado con un deploy de prueba | **40** |
| Script `deploy.sh` (build + push + `gcloud run deploy`) | probado con la app hola mundo | 20 |
| Prompt del intérprete de misión + parseo a `MissionPlan`, **con expansión de sinónimos en `keywords`** (doc 01 §8.3) | escrito, probado con frases inventadas | 30 |
| Extracción de cita: tramo A (documentos en contexto + `cache_control`) y tramo B (chunking + `documents_fts`), con validación de substring literal — doc 01 §8 | ambos escritos contra texto de prueba | 25 |
| Tests del motor (`pytest`, 10 casos — doc 07 §4) | escritos y en verde | 20 |
| Assets vendorizados (`htmx.min.js`, `tailwind.js` en `app/static/`) | descargados, sin CDN en vivo | 5 |
| **Docling instalado Y corrido una vez** (modelos en caché — doc 07 §2) | verificado offline, `pypdf` como fallback | **20** |
| **`CLAUDE.md`** con contrato, reglas y orden de corte (doc 07 §7.4) | ✅ | 25 |
| Estos 7 documentos | ✅ | — |

**Total ahorrado: ~370 min.** Es la razón por la que este plan de 6 horas cabe.

> ⚠️ **Lo único que NO se pre-construye:** cualquier cosa que toque la taxonomía, los
> nombres de campo o el dominio del retailer. Eso se escribe en vivo y se nota que se
> escribió en vivo.

> ⚠️ **El deploy de prueba a Cloud Run se hace el día anterior con la app hola mundo.**
> Descubrir un problema de permisos de IAM a las 4 horas de prueba es la forma más
> tonta de perderla, y es completamente evitable.

---

## 1. Bloques

### T+0:00 – 0:15 · Triage ciego

Correr el protocolo del doc 01 §5. **No escribir código de aplicación.** Sólo mirar.

**Salida obligatoria:** las 6 respuestas del doc 01 §5 escritas en una hoja.

> Si a T+0:15 no se sabe cuántos productos hay ni si hay margen, el problema es de
> formato: saltar directo al doc 06 §R6.

### T+0:15 – 0:45 · Mapeo

Llenar la plantilla del doc 01 §6 y la tabla de sinónimos de categorías.

**🔴 CORTE T+0:45:** la plantilla se congela tal como esté. Las filas vacías son
degradaciones declaradas, no trabajo pendiente. Volver a pelear con un campo después
de esta hora es la forma número uno de perder la prueba.

### T+0:45 – 1:30 · Adaptador + ETL

Escribir `adapter.py` sobre las firmas pre-construidas: leer el insumo, normalizar
categorías, derivar señales, poblar `AdapterReport`, escribir SQLite + FTS5.

**Salida obligatoria:** `catalog.db` con N productos válidos y un `AdapterReport`
impreso en consola.

**🔴 CORTE T+1:15:** si el adaptador no produce **≥ 50 productos canónicos válidos**,
se abandona el insumo secundario y se sigue sólo con el principal. Si con el
principal tampoco llega: doc 06 §R6, extracción manual de un subconjunto.

**🔴 CORTE T+1:30:** si el adaptador no termina, se congela con lo que produzca y se
sigue. Una app con 200 productos bien mapeados demuestra más que una con 200 000 que
no se alcanzó a mostrar.

### T+1:30 – 1:45 · 🚀 DEPLOY DE HUMO

Con la app semi-vacía y el `catalog.db` real horneado: `./deploy.sh`. Abrir la URL en
el celular.

**Este bloque no se salta jamás.** Su propósito es descubrir a la hora y media —
cuando hay 4 horas y media de margen — cualquier problema de imagen, tamaño,
permisos, puerto o variable de entorno. Descubrirlos a T+5:00 es fatal; a T+1:45 son
15 minutos.

**🔴 CORTE T+2:00:** si el deploy no funciona a las dos horas, **se abandona Cloud Run**
y se cambia a túnel (Cloudflare Tunnel / ngrok), que da URL pública en 3 minutos. El
jurado igual abre desde su celular; nadie pregunta dónde corre.

### T+1:45 – 2:45 · Motor conectado

Cablear el motor pre-construido contra `catalog.db`: filtro duro con los criterios que
sobrevivieron al mapeo, candidate set por slot, scoring, renormalización de pesos
según cobertura real.

**Salida obligatoria:** un script que, dado un `MissionPlan` escrito a mano, imprime la
canasta rankeada en consola. **Sin UI todavía.**

**🔴 CORTE T+2:45:** si el motor no rankea, se apaga el scoring multi-señal y se ordena
sólo por relevancia. El Modo Negocio pasa a mostrar las señales **sin** poder
reordenar. Cuesta la mitad del "wow" pero salva la demo.

### T+2:45 – 3:15 · Intérprete de misión

Conectar el prompt pre-escrito al parseo a `MissionPlan`. **Cachear en disco las 3
misiones semilla del doc 04 inmediatamente después de que funcionen.**

**🔴 CORTE T+3:15:** si el LLM no devuelve `MissionPlan` válido de forma consistente,
se activa el fallback determinista por palabras clave (plantillas por `MissionKind`) y
las 3 semillas se escriben a mano en JSON. **La demo no depende del LLM ni un segundo.**

### T+3:15 – 4:30 · UI

En este orden estricto, cortando desde abajo cuando se acabe el tiempo:

1. P2 canasta con `SlotCard` + `CitationBlock` — **35 min**
2. P1 entrada + chips semilla — **15 min**
3. `BasketSummary` + uplift — **10 min**
4. **Modo Negocio** (toggle + 3 sliders + breakdown) — **35 min**
5. Responsive 768 px — **20 min**
6. P3 detalle — **15 min**
7. P5 diagnóstico — **20 min**
8. `AlternativesDrawer` / `RejectionDrawer` — **15 min**

Suman 165 min contra 75 disponibles. **Los puntos 1 a 4 son los que entran.** Si algo
de 1–4 se atrasa, se cortan 5–8 enteros; el responsive (5) es la única excepción, se
hace siempre porque el jurado abre desde el celular.

**🔴 CORTE T+4:00:** si el Modo Negocio no está en pie, se abandona. El resto de la UI
vale más que un Modo Negocio a medias, y el doc 04 tiene el guion alternativo.

### 🧊 T+4:30 · FEATURE FREEZE

**A partir de acá no se escribe una línea de feature.** Sólo: bugs que rompen la demo,
deploy, y ensayo. Cualquier "es sólo un cambio chiquito" después de esta hora es una
apuesta con mala relación riesgo/beneficio.

### T+4:30 – 5:00 · Deploy final

`./deploy.sh` con el `catalog.db` definitivo. `min-instances=1`. Verificar **desde el
celular**, no desde el navegador de escritorio: los 3 escenarios completos, el Modo
Negocio y la hoja inferior de sliders.

**🔴 CORTE T+5:00:** si el deploy final está roto, se revierte a la revisión anterior de
Cloud Run (que quedó viva del deploy de humo) o se levanta el túnel. **Nunca se debuggea
infraestructura después de T+5:00.**

### T+5:00 – 5:30 · Respaldo y evidencia

- 6 capturas a pantalla completa en `respaldo/` (doc 04 §6).
- Verificar la caché de las 3 semillas (respuesta instantánea, sin red).
- Levantar la copia local en una pestaña de respaldo.
- `README.md` de entrega: qué hace, cómo correrlo, **qué campos se degradaron y por qué**.

### T+5:30 – 6:00 · Ensayo

**Dos pasadas cronometradas completas del doc 04, en voz alta.** No una lectura: en voz
alta, con el reloj.

La primera pasada siempre descubre dos cosas: un clic que se demora más de lo que se
recordaba, y una frase que no se sostiene al decirla. La segunda las arregla.

Repasar las 8 preguntas del doc 04 §5, en particular **la del ML**.

---

## 2. Tabla de cortes

| Hora | Condición | Acción |
|---|---|---|
| T+0:45 | Plantilla de mapeo incompleta | Se congela. Filas vacías = degradaciones. |
| T+1:15 | < 50 productos canónicos válidos | Se abandona el insumo secundario. |
| T+1:30 | Adaptador sin terminar | Se congela con lo que produzca. |
| T+2:00 | Cloud Run no despliega | Se cambia a túnel. Cloud Run se abandona. |
| T+2:45 | Motor no rankea | Sólo relevancia; Modo Negocio pasa a solo lectura. |
| T+3:15 | LLM inconsistente | Fallback por keywords + 3 semillas en JSON. |
| T+3:30 | Fitment no valida | Degrada a coincidencia textual (doc 06 §R4). |
| T+4:00 | Modo Negocio no en pie | Se abandona; guion alternativo del doc 04. |
| **T+4:30** | **Lo que sea** | **FEATURE FREEZE.** |
| T+5:00 | Deploy final roto | Revertir a la revisión anterior o túnel. |

---

## 3. Sobre Claude Code en el camino crítico

**Los bloques de arriba NO asumen compresión por agente, y es deliberado.** El plan sin
agente es el plan B del plan con agente (doc 07 §7.2): si se cae la red o se agota la
cuota a T+2:30, no hay nada que rehacer.

La compresión real es de **45–60 min, casi toda en UI** — el triage, el mapeo, el deploy
y el ensayo no se comprimen nada. Ese excedente va, en orden: comparador lado a lado
(30 min), pantalla de diagnóstico (20 min), y después **ensayo, no features**.

**El FEATURE FREEZE sigue a T+4:30.** Escribir más rápido no mueve el freeze: existe por
riesgo, no por productividad.

---

## 4. Lectura escéptica del plan

**Lo que más probablemente salga mal, en orden:**

1. **La adaptación de datos se come 2 horas en vez de 1:30.** Es lo más común y lo
   mitiga el corte de T+1:15, que hay que respetar aunque duela.
2. **La UI se come el Modo Negocio.** Por eso el Modo Negocio va **antes** que el
   responsive, el detalle y el diagnóstico: es lo que diferencia esta entrega.
3. **El deploy final descubre un problema nuevo.** Por eso existe el deploy de humo a
   T+1:45 con el `catalog.db` real, no con datos falsos.

**El escenario realista, no el optimista:** entran la canasta cross-categoría con
citas, el Modo Negocio, el responsive y el deploy. **No entran** el comparador lado a
lado ni la canasta editable con cantidades. Y está bien: el comparador se demuestra con
`AlternativesDrawer`, que sale casi gratis del mismo objeto `ScoredProduct`.

**Si a T+3:15 sólo hay dos horas de UI y tres features en pie**, la elección correcta es
canasta + citas + Modo Negocio. En ese orden. Sin negociar.
