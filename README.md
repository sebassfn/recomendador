# Recomendador de misión de compra

MVP de un recomendador de productos para un retailer multicategoría
(supermercado · autos · hogar y almacenaje), construido para una prueba práctica de 6 horas.

**Tesis:** no es un buscador en lenguaje natural. Es un **asesor de misión de compra**
que recibe una necesidad ("me voy con los niños a la playa") y arma una canasta que
**cruza las tres categorías**, porque tenerlas bajo el mismo techo es el activo
diferencial de la empresa. KPI atacado: **ticket promedio e ítems por canasta**.

**Arquitectura en una frase:** la base de datos decide qué existe, el negocio decide el
orden, el documento decide la explicación, el agente decide qué preguntar y a quién. El
agente (`app/agent/`, LangGraph) no hace ninguna de las tres primeras — sólo traduce la
necesidad a un plan estructurado (incluidas las especificaciones y las marcas que el
cliente nombra, que el motor usa para ordenar), con memoria de conversación, desambiguación con
human-in-the-loop y reintentos ante fallas de red. Ver [`app/agent/README.md`](app/agent/README.md).

---

## Contenido

| Archivo | Qué es | Cuándo se usa |
|---|---|---|
| [`CLAUDE.md`](CLAUDE.md) | Reglas del proyecto: contrato, prohibiciones, orden de corte | Cargado en cada sesión |
| [`app/domain/schema.py`](app/domain/schema.py) | **El contrato.** Esquema canónico en Pydantic: `Product`, `MissionPlan`, `BasketSlot`, `Basket`... | Referencia permanente |
| [`app/agent/README.md`](app/agent/README.md) | Módulo de agente de IA (LangGraph): grafo, memoria, cómo copiarlo a otro proyecto | Al tocar interpretación de necesidad |
| [`docs/01-contrato-de-datos.md`](docs/01-contrato-de-datos.md) | Campos, degradación, triage y **plantilla de mapeo en blanco** | **T+0:00 a T+0:45** |
| [`docs/02-motor-de-scoring.md`](docs/02-motor-de-scoring.md) | Fórmula, normalización, pesos, sliders, especificaciones, preferencia de marca y ejemplos resueltos | T+1:45 a T+2:45 |
| [`docs/03-inventario-de-ui.md`](docs/03-inventario-de-ui.md) | Pantallas, componentes, estados, responsive, orden de sacrificio | T+3:15 a T+4:30 |
| [`docs/04-guion-de-demo.md`](docs/04-guion-de-demo.md) | 3 escenarios cronometrados + **8 preguntas del jurado** | T+5:30 y la demo |
| [`docs/05-plan-6-horas.md`](docs/05-plan-6-horas.md) | Bloques, **FEATURE FREEZE T+4:30**, cortes objetivos | Todo el tiempo |
| [`docs/06-riesgos-y-planes-b.md`](docs/06-riesgos-y-planes-b.md) | 9 riesgos con plan B y costo en minutos | Cuando algo sale mal |
| [`docs/07-herramientas-y-comandos.md`](docs/07-herramientas-y-comandos.md) | Dependencias pinneadas, comandos de ETL/deploy y **checklist de la noche anterior** | La noche anterior y T+0:00 |
| [`docs/08-catalogo-sintetico.md`](docs/08-catalogo-sintetico.md) | Catálogo de pruebas (`CAT-*`, `PRD-*`, `SUP-*`, `BRD-*`): qué es simulado y cómo reproducirlo | Al regenerar `catalog.db` |

## Orden de lectura el día de la prueba

1. **La noche anterior:** doc 07 §6 (checklist, se ejecuta), doc 05 §0 (pre-construcción)
   y doc 04 §5 (las 8 preguntas).
2. **T+0:00, con los insumos en la mano:** doc 01 §5 (triage) → §6 (plantilla de mapeo).
3. **Si algo del triage sale mal:** doc 06, la ficha que corresponda. Empezar por R7 si
   faltan categorías — es el único riesgo que cambia el discurso y no sólo una feature.
4. **Durante la construcción:** doc 05 en pantalla, mirando la tabla de cortes.
5. **T+5:30:** doc 04, dos pasadas en voz alta con reloj.

---

## Reglas que gobiernan todo el paquete

1. **Regla de degradación.** Ninguna feature depende de un campo que quizá no exista.
   Cada una declara su comportamiento degradado en el doc 01 §3.
2. **Cuatro campos obligatorios y nada más:** `product_id`, `name`, `category`,
   `price.amount`. Todo lo demás degrada.
3. **Ausente no es cero.** Una señal que falta se elimina del scoring y su peso se
   redistribuye; nunca se puntúa como el peor del set. (doc 02 §4, contraejemplo
   numérico en §6.)
4. **Los datos simulados se etiquetan siempre.** `SignalSource.SIMULATED` → badge
   ámbar; `DERIVED` → badge gris; `REAL` → sin badge. Sin excepciones.
5. **Las citas nunca las redacta el LLM.** Se recortan del documento indexado.
6. **El agente sólo produce un `MissionPlan`.** Nunca ve productos, precios ni orden.
   El filtro duro y el ranking son Python determinista (`app/engine/scoring.py`). Las
   acciones rápidas ("más baratas", "sólo de marca") no pasan por el agente.
7. **La marca pedida es preferencia, no filtro.** Ordena primero dentro del slot sin
   tocar `total_score`; la presentación ("paquete de 12", "500 ml", "sin azúcar") sí es
   especificación dura vía `attribute_requirements` (doc 02 §3.2).
8. **FEATURE FREEZE a T+4:30.** Después de esa hora sólo bugs, deploy y ensayo.

---

## Estructura del código

```
app/
  domain/          schema.py (el contrato) · specifications.py (operadores y unidades de atributos)
  data/            attribute_definitions.json · seeds/ (3 misiones semilla + CSV del catálogo sintético)
  etl/             insumos reales -> catalog.db (firmas vacías hasta el día de la prueba)
  adapters/        filas de catalog.db -> Product
  repositories/    SQL a mano sobre catalog.db (solo lectura)
  engine/          scoring.py: filtro duro + ranking + preferencia de marca
  services/        basket_service.py (MissionPlan -> Basket) · advisor_service.py (turnos del asesor)
  agent/           agente LangGraph genérico y copiable; no importa nada de app.* (ver su README)
  mission_agent/   plugin de dominio del agente: bridge, caché de semillas, fallback por palabras clave, validación de marcas
  llm/             extracción de citas con validación de substring literal (doc 01 §8) y sus proveedores; aún no conectada a la web
  presentation/    projector.py (dominio -> view model) · cart.py (operaciones deterministas del carrito)
  web/             routes.py (FastAPI + HTMX) · session.py (misión en memoria + cookie `uid` anónima)
  templates/       Jinja: base, index, mission y partials/
  static/          htmx.min.js y tailwind.js vendorizados
scripts/           seed_catalog.py · expand_catalog.py · supermarket_catalog.py · branded_catalog.py
tests/             motor, carrito, adaptador, citas, proyector, rutas web · agent/ · mission_agent/
```

## Correr en local

```bash
uv sync
uv run python scripts/seed_catalog.py        # crea catalog.db (se reemplaza; no se versiona)
uv run python scripts/expand_catalog.py      # agrega el catálogo sintético (doc 08)
uv run --env-file .env uvicorn app.main:app  # http://127.0.0.1:8000
```

`.env` necesita al menos `ANTHROPIC_API_KEY`. El agente usa `AGENT_STORE_BACKEND=memory`
por defecto, sin credenciales de Firebase; el resto de las variables `AGENT_*` está en
[`app/agent/.env.example`](app/agent/.env.example). Sin API key, las 3 misiones semilla
salen de la caché y el resto cae al fallback por palabras clave.

Proveedores alternativos, sólo si se configuran:
`uv sync --extra agent-google` o `uv sync --extra agent-openrouter`.

## Tests

```bash
uv run pytest                  # suite completa, sin red
uv run pytest tests/agent/     # control de loop del agente con LLM de mentira
uv run pytest tests/test_scoring.py
```

Los tests de Firestore (`-m firestore`) se saltan salvo que haya `FIRESTORE_EMULATOR_HOST`
(ver la sección Cloud Firestore de [`app/agent/README.md`](app/agent/README.md)).

## Deploy

```bash
PROJECT=mi-proyecto REGION=us-central1 ANTHROPIC_API_KEY=sk-... ./deploy.sh
```

Construye la imagen (`Dockerfile`, con `catalog.db` horneado), la sube a Artifact Registry
y despliega en Cloud Run con **`--min-instances=1 --max-instances=1`**: la canasta y el
carrito viven en memoria del proceso. Para que la conversación del agente persista, pasar
`AGENT_STORE_BACKEND=firestore` (la cuenta de servicio necesita `roles/datastore.user`).

## Stack

FastAPI · Jinja2 · HTMX 2 y Tailwind vendorizados en `app/static/` (sin build step) ·
SQLite + FTS5 de solo lectura horneado en la imagen · Python 3.12 con `uv` · **docling**
para extraer documentos (ETL local, `pypdf` de fallback) · agente de IA con **LangGraph**
(`app/agent/`, ver su README): **`claude-sonnet-5`** estándar y **`claude-opus-5`** de
razonamiento, memoria por checkpoints de LangGraph (Cloud Firestore en producción) ·
Docker en Artifact Registry · Cloud Run (`min-instances=1` durante la demo) · caché en
disco de las 3 misiones semilla para no depender de ningún LLM en la demo.

## Verificar el contrato

```bash
uv sync
PYTHONPATH=. uv run python -c "
from decimal import Decimal
from app.domain.schema import Product, Price, Category
p = Product(product_id='1', name='X', category=Category.GROCERY, price=Price(amount=Decimal('10')))
print('contrato OK:', p.availability, p.signals.available_signals)
"
```

Un `Product` con sólo los cuatro campos obligatorios **debe** validar. Si falla, la
regla de degradación está rota en el contrato y todo lo demás se cae detrás.
