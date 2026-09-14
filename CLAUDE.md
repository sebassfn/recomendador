# Recomendador de misión de compra — reglas del proyecto

Prueba práctica de 6 horas. Retailer multicategoría: supermercado + autos + hogar.
**No es un buscador. Es un asesor de misión de compra** que arma una canasta que cruza
las tres categorías. KPI: ticket promedio e ítems por canasta.

## Arquitectura en una frase

**La base de datos decide qué existe, el negocio decide el orden, el documento decide la
explicación, el agente decide qué preguntar y a quién.** Ninguno de los tres primeros es
trabajo del LLM: el agente (`app/agent/`) sólo orquesta la interpretación de la
necesidad y copia lo que el cliente declara (especificaciones, marcas que nombra) —
nunca ve productos, nunca ve precios, nunca ordena nada. El filtro duro y el ranking
siguen siendo Python determinista (`app/engine/scoring.py`).

## Reglas que no se negocian

1. **El contrato es `app/domain/schema.py`.** Nada aguas abajo del adaptador conoce el
   formato original de los insumos. No inventes campos nuevos: si algo falta, se declara
   ausente en `AdapterReport`.
2. **Sólo 4 campos son obligatorios:** `product_id`, `name`, `category`, `price.amount`.
   Todo lo demás es degradable y cada feature declara su comportamiento sin él (doc 01 §3).
3. **Ausente ≠ cero.** Una señal que falta se elimina del scoring y su peso se
   redistribuye entre las presentes. **Nunca** `COALESCE(margen, 0)` (doc 02 §4).
4. **Los datos derivados o simulados se etiquetan en la UI.** `SignalSource.SIMULATED` →
   badge ámbar; `DERIVED` → badge gris; `REAL` → sin badge. Sin excepciones.
5. **Las citas nunca se redactan, se recortan.** El texto entre comillas es substring
   literal del documento indexado, y se valida como tal. Si no hay respaldo, la tarjeta
   dice "sin respaldo documental".
6. **El agente sólo traduce la necesidad a un `MissionPlan`.** Ni el orquestador ni
   ninguno de sus subagentes (`app/agent/subagents/`) ve productos, precios ni orden de
   catálogo — lo que producen es un plan estructurado (`app/domain/schema.MissionPlan`,
   vía `app/domain/schema.MissionPlanDraft`). El filtro duro y el ranking son Python
   determinista y viven exclusivamente en `app/engine/scoring.py` y
   `app/services/basket_service.py`. Una acción que el agente no puede expresar
   ("más barato", "sólo productos de marca" sin nombrar ninguna) **no pasa por el
   agente**: es una operación determinista sobre la canasta ya resuelta
   (`app/presentation/cart.py`).
8. **La marca pedida es preferencia, no filtro.** Si el cliente nombra una marca, el
   planner la copia en `BasketSlot.preferred_brands`; `app/mission_agent/attributes.py`
   descarta cualquier marca que no aparezca literalmente en su texto. El motor pone esa
   marca **primero** dentro del slot sin tocar `total_score`: entre productos de la
   misma marca decide el score normal (relevancia + margen, rotación, marca propia,
   promo). Si no hay stock de esa marca se muestran otras y la respuesta lo dice. La
   marca nunca salta el filtro duro ni el filtro de texto. Presentación ("paquete de
   12", "500 ml", "sin azúcar") sí es especificación dura vía `attribute_requirements`
   (`units_per_pack`, `volume_ml`, `sugar_free`, ver `app/data/attribute_definitions.json`).
7. **`app/agent/` no importa nada de `app.*`.** Es un módulo genérico, pensado para
   copiarse completo a otro proyecto (ver `app/agent/README.md`). Lo específico de este
   retailer —qué es un `MissionPlan`, la caché de semillas, el fallback por
   palabras clave— vive en `app/mission_agent/`, que es quien le habla al agente y a
   `app/services/advisor_service.py` a la vez. Un test de portabilidad
   (`tests/agent/test_module_is_portable.py`) lo hace cumplir.

## Prohibido

- Frameworks de agentes de alto nivel (CrewAI, LlamaIndex, pydantic-ai, un `AgentExecutor`
  de LangChain). **LangGraph + `langchain-core` SÍ están permitidos**, confinados a
  `app/agent/` (ver ese README): construyen el grafo determinista del agente — orquestador,
  subagentes, checkpoints — nunca un loop de agente "mágico" sin control de iteraciones.
- ORM, migraciones, base de datos externa **para el catálogo**. SQLite de solo lectura y
  SQL a mano sigue siendo la única fuente de verdad de productos. La ÚNICA base externa
  permitida es Cloud Firestore, y sólo para lo que `app/agent/persistence/` declara:
  checkpoints de conversación (memoria del agente), nunca catálogo ni carrito.
- Build step de front. Jinja + HTMX + Tailwind vendorizados en `app/static/`.
- Autenticación, cuentas, carrito persistente. El `uid` anónimo en cookie
  (`app/web/session.py`) identifica sesiones ante el agente, no es una cuenta.
- Embeddings locales en runtime (doc 01 §8.5).
- Imágenes externas: placeholder CSS por categoría.

## Stack

FastAPI · Jinja2 · HTMX · Tailwind (vendorizados) · SQLite + FTS5 de solo lectura
horneado en la imagen · Python 3.12 con `uv` · Docker en Artifact Registry · Cloud Run.

**Agente de IA** (`app/agent/`, ver su `README.md`): LangGraph + `langchain-core`,
modelo estándar **`claude-sonnet-5`** y modelo de razonamiento **`claude-opus-5`**
(escalado por turno, nunca fijo) vía `anthropic`, memoria de conversación **sólo** por
checkpoints de LangGraph sobre Cloud Firestore en producción (`AGENT_STORE_BACKEND=memory`
en local/tests, sin credenciales de Firebase).

ETL local (pandas, docling) — **nunca entra a la imagen**, sólo viaja `catalog.db`.

## Orden de construcción y corte

Se construye de arriba hacia abajo; se corta desde abajo sin negociar:

1. Canasta cross-categoría con filtro duro + citas, interpretada por el agente ← **núcleo**
2. Modo Negocio (toggle + 3 sliders + breakdown) ← **el wow que gana la prueba**
3. Responsive 768 px ← **nunca se corta**: el jurado abre desde su celular
4. Detalle de producto
5. Pantalla de diagnóstico
6. Alternativas / explicación del descarte
7. Comparador lado a lado ← primero en caer

**FEATURE FREEZE T+4:30.** Después: sólo bugs que rompen la demo, deploy y ensayo.

## Cómo trabajar en este repo

- **Rebanada vertical antes de generalizar.** Un caso completo de punta a punta —una
  misión, un slot, un producto, una tarjeta renderizada con datos reales— antes de
  escribir el segundo de cualquier cosa. Los bugs viven en las costuras entre capas, no
  dentro de ellas. Y el primer ejemplo real es el molde del que se copia todo lo demás:
  si la primera tarjeta maneja bien `Signal[T]`, el badge de `SIMULATED` y el estado
  "sin respaldo documental", las siguientes salen casi solas.

- Después de cada bloque, **correr el código y mirar la salida real**. No leer el diff y
  asumir. Para el agente, eso significa correr `uv run pytest tests/agent/` (LLM de
  mentira, sin red) Y levantar `uv run --env-file .env uvicorn app.main:app` para ver
  una misión real armada de punta a punta.
- Los tests del motor (`tests/test_scoring.py`) son la red de seguridad del ranking: un
  bug de renormalización da números plausibles y mal ordenados. Los tests del agente
  (`tests/agent/`) son la red de seguridad del control de loop: un bug ahí deja al agente
  reintentando para siempre o devolviendo una salida a medio validar.
- Código feo que se entiende > código elegante que no. Estamos contra un reloj.
- Documentación completa en `docs/`. Ver `README.md` para el índice y el orden de lectura;
  `app/agent/README.md` para el agente en particular.
