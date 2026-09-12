# Recomendador de misión de compra — reglas del proyecto

Prueba práctica de 6 horas. Retailer multicategoría: supermercado + autos + hogar.
**No es un buscador. Es un asesor de misión de compra** que arma una canasta que cruza
las tres categorías. KPI: ticket promedio e ítems por canasta.

## Arquitectura en una frase

**La base de datos decide qué existe, el negocio decide el orden, el documento decide la
explicación.** El LLM no hace ninguna de las tres.

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
6. **El LLM sólo traduce la necesidad a un `MissionPlan`.** No ve productos, no ve
   precios, no ordena nada. El filtro duro y el ranking son Python determinista.

## Prohibido

- Frameworks de agentes (LangChain, LlamaIndex, CrewAI, pydantic-ai). **No hay agente**:
  hay una sola llamada `texto → MissionPlan`.
- ORM, migraciones, base de datos externa. SQLite de solo lectura y SQL a mano.
- Build step de front. Jinja + HTMX + Tailwind vendorizados en `app/static/`.
- Autenticación, cuentas, carrito persistente.
- Embeddings locales en runtime (doc 01 §8.5).
- Imágenes externas: placeholder CSS por categoría.

## Stack

FastAPI · Jinja2 · HTMX · Tailwind (vendorizados) · SQLite + FTS5 de solo lectura
horneado en la imagen · Python 3.12 con `uv` · `anthropic` con **`claude-opus-5`** ·
Docker en Artifact Registry · Cloud Run.

ETL local (pandas, docling) — **nunca entra a la imagen**, sólo viaja `catalog.db`.

## Orden de construcción y corte

Se construye de arriba hacia abajo; se corta desde abajo sin negociar:

1. Canasta cross-categoría con filtro duro + citas ← **núcleo**
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
  asumir.
- Los tests del motor (`tests/test_scoring.py`) son la red de seguridad: un bug de
  renormalización da números plausibles y mal ordenados.
- Código feo que se entiende > código elegante que no. Estamos contra un reloj.
- Documentación completa en `docs/`. Ver `README.md` para el índice y el orden de lectura.
