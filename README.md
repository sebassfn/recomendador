# Recomendador de misión de compra — paquete de preparación

Preparación para una prueba práctica de 6 horas: MVP de un recomendador de productos
para un retailer multicategoría (supermercado · autos · hogar y almacenaje).

**Tesis:** no es un buscador en lenguaje natural. Es un **asesor de misión de compra**
que recibe una necesidad ("me voy con los niños a la playa") y arma una canasta que
**cruza las tres categorías**, porque tenerlas bajo el mismo techo es el activo
diferencial de la empresa. KPI atacado: **ticket promedio e ítems por canasta**.

**Arquitectura en una frase:** la base de datos decide qué existe, el negocio decide el
orden, el documento decide la explicación. El LLM no hace ninguna de las tres — sólo
traduce la necesidad a un plan estructurado.

---

## Contenido

| Archivo | Qué es | Cuándo se usa |
|---|---|---|
| [`CLAUDE.md`](CLAUDE.md) | Reglas del proyecto para el agente: contrato, prohibiciones, orden de corte | Cargado en cada sesión |
| [`app/domain/schema.py`](app/domain/schema.py) | **El contrato.** Esquema canónico en Pydantic. Único código escrito de antemano. | Referencia permanente |
| [`docs/01-contrato-de-datos.md`](docs/01-contrato-de-datos.md) | Campos, degradación, triage y **plantilla de mapeo en blanco** | **T+0:00 a T+0:45** |
| [`docs/02-motor-de-scoring.md`](docs/02-motor-de-scoring.md) | Fórmula, normalización, pesos, sliders, 3 ejemplos resueltos | T+1:45 a T+2:45 |
| [`docs/03-inventario-de-ui.md`](docs/03-inventario-de-ui.md) | Pantallas, componentes, estados, responsive, orden de sacrificio | T+3:15 a T+4:30 |
| [`docs/04-guion-de-demo.md`](docs/04-guion-de-demo.md) | 3 escenarios cronometrados + **8 preguntas del jurado** | T+5:30 y la demo |
| [`docs/05-plan-6-horas.md`](docs/05-plan-6-horas.md) | Bloques, **FEATURE FREEZE T+4:30**, cortes objetivos | Todo el tiempo |
| [`docs/06-riesgos-y-planes-b.md`](docs/06-riesgos-y-planes-b.md) | 9 riesgos con plan B y costo en minutos | Cuando algo sale mal |
| [`docs/07-herramientas-y-comandos.md`](docs/07-herramientas-y-comandos.md) | Dependencias pinneadas, comandos de ETL/deploy y **checklist de la noche anterior** | La noche anterior y T+0:00 |

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
6. **FEATURE FREEZE a T+4:30.** Después de esa hora sólo bugs, deploy y ensayo.

---

## Stack

FastAPI · Jinja2 · HTMX 2 (CDN) · Tailwind (CDN) · SQLite + FTS5 de solo lectura
horneado en la imagen · Python 3.12 con `uv` · **docling** para extraer documentos (ETL local,
`pypdf` de fallback) · modelo **`claude-opus-5`**, sin framework de agentes ·
Docker en Artifact Registry ·
Cloud Run (`min-instances=1` durante la demo) · Anthropic API sólo para interpretar la
necesidad, con caché en disco de las 3 misiones semilla.

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
