# 07 — Herramientas y comandos

> La hoja que abrís a T+0:00 y no volvés a pensar. Todo lo de acá se instala y se
> verifica **la noche anterior**.
>
> ⚠️ Nada de este documento está instalado todavía. `pyproject.toml` hoy sólo declara
> `pydantic`. El checklist de §6 es el que lo deja listo.

---

## 1. Separación de dependencias

**Regla:** el ETL corre **local** y produce `catalog.db`; sólo el `.db` viaja en la
imagen. Por eso las dependencias pesadas (pandas, docling) **nunca entran al contenedor**.

```
┌─ grupo por defecto ──────────────┐   ┌─ grupo "etl" (local) ────────────┐
│ fastapi   uvicorn[standard]      │   │ pandas    openpyxl               │
│ jinja2    python-multipart       │   │ docling   pypdf                  │
│ pydantic  anthropic              │   └──────────────────────────────────┘
└──────────────────────────────────┘   ┌─ grupo "dev" ────────────────────┐
        ↑ esto va en la imagen          │ pytest    ruff                   │
                                        └──────────────────────────────────┘
```

### 1.1 Runtime de la app (va en la imagen)

| Librería | Para qué | Pin |
|---|---|---|
| `fastapi` | endpoints + fragmentos HTMX | `>=0.115` |
| `uvicorn[standard]` | servidor ASGI; Cloud Run escucha en `$PORT` | `>=0.32` |
| `jinja2` | plantillas y fragmentos | `>=3.1` |
| `python-multipart` | `POST` de formularios (misión, sliders) | `>=0.0.9` |
| `pydantic` | **el contrato** (`app/domain/schema.py`) | `>=2.13` ✅ ya instalado |
| `anthropic` | intérprete de misión + extracción de cita | `>=0.40` |

**Modelo pinneado: `claude-opus-5`.** El argumento de latencia a favor de uno más
rápido casi no aplica: las 3 misiones semilla están cacheadas en disco y la demo no
llama a la API en vivo (doc 04 §6). La latencia sólo se paga si el jurado escribe
texto libre — y ahí querés la mejor interpretación, no la más rápida.

> **Sin framework de agentes — decisión, no omisión.** No hay LangChain, LlamaIndex,
> CrewAI ni `pydantic-ai`, porque **no hay un agente**: hay una sola llamada
> `texto → MissionPlan`, sin loop, sin tools, sin estado. Un framework orquesta loops
> de razonamiento; acá no hay nada que orquestar. Lo único que se querría de uno
> —salida estructurada validada— ya lo da Pydantic: **el contrato es el esquema**.
> Además sostiene la respuesta al jurado de que *el modelo no elige productos*.

> `sqlite3` es stdlib. No se instala nada para la base.

### 1.2 ETL, local (**no** va en la imagen)

| Librería | Para qué | Pin |
|---|---|---|
| `pandas` | lectura de insumos, nulos, cardinalidad, muestreo estratificado (R5) | `>=2.2` |
| `openpyxl` | motor de `read_excel` para XLSX | `>=3.1` |
| `docling` | **extracción de documentos** — ver §2 | `>=2.0` |
| `pypdf` | **red de seguridad** si docling falla | `>=5.0` |

### 1.3 Desarrollo

| Librería | Para qué |
|---|---|
| `pytest` | tests del motor de scoring (§4) |
| `ruff` | formato y lint, opcional |

---

## 2. Docling — decisión y riesgo

**Se elige docling como extractor primario**, y no por capricho: resuelve dos cosas que
ninguna otra opción cubre.

1. **`export_to_markdown()` con estructura de encabezados.** Eso es exactamente lo que
   §8 necesita para el `locator` de la `Citation` ("p. 4, sección Playa con niños").
   Con `pypdf` el locator se reduce al número de página; con docling sale gratis.
2. **OCR para escaneados.** Esto **cambia el riesgo R1 del doc 06**, donde hoy dice
   *"PDF escaneado → no se hace OCR → va directo al plan B"*. Con docling ese caso deja
   de ser letal.

También trae reconocimiento de tablas (útil si los insumos son fichas técnicas) y un
`HybridChunker` que sirve para el tramo B de §8.

### ⚠️ Riesgo y mitigación

Docling es **la dependencia más pesada de todo el plan** y descarga modelos la primera
vez que corre. Dos reglas:

| Regla | Por qué |
|---|---|
| **Instalarlo Y correrlo una vez la noche anterior** sobre un PDF de prueba. | Si los modelos se descargan a T+0:45, perdiste el bloque de adaptación entero. |
| **`pypdf` queda como fallback declarado.** Si docling no responde en 5 minutos, se cambia de una línea y se sigue. | Misma regla de degradación que el resto del paquete: ninguna pieza sin plan B. |

> **No verificado:** si docling expone un comando de pre-descarga de modelos o un
> `artifacts_path` para modo offline. La verificación real es empírica y está en el
> checklist §6: correrlo dos veces y confirmar que la segunda no toca la red.

---

## 3. Prerequisitos de sistema

| Herramienta | Verificar con | Si falta |
|---|---|---|
| `uv` | `uv --version` | `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| Docker | `docker info` | daemon corriendo, no sólo instalado |
| `gcloud` | `gcloud auth list` | `gcloud auth login` + `gcloud config set project <ID>` |
| `sqlite3` CLI | `sqlite3 --version` | sólo para inspeccionar dumps en el triage |

---

## 4. Tests del motor de scoring

Se escriben **en tiempo de pre-build**, no durante la prueba. `tests/test_scoring.py`:

| # | Test | Qué protege |
|---|---|---|
| 1-3 | Los 3 ejemplos numéricos del doc 02 §6 | Que la fórmula da los números documentados |
| 4 | Señal ausente en todo el set → se elimina y los pesos renormalizan a 1.0 | La regla central de degradación |
| 5 | Cobertura 70 % → se imputa la **mediana**, nunca 0 | El contraejemplo del doc 02 §6 Ej. 2b |
| 6 | Umbral de cobertura 60 %: 59 % mata la señal, 61 % la mantiene | El borde exacto |
| 7 | Piso de `w_relevance` = 0.20 con los 3 sliders al máximo | Que el negocio no secuestre el ranking |
| 8 | `score ∈ [0,1]` siempre, con cualquier combinación de señales | Que la UI nunca muestre un número imposible |
| 9 | Candidate set < 3 → min-max degrada a 0.5 constante | El caso borde del doc 02 §3.1 |
| 10 | `Product` con sólo los 4 campos obligatorios recorre el motor entero | El smoke test del contrato |

**Un bug de renormalización es silencioso**: da números plausibles y mal ordenados. Es
justo el tipo de fallo que no ves a ojo a T+2:30.

---

## 5. Comandos

### 5.1 Preparación (noche anterior)

```bash
uv add fastapi "uvicorn[standard]" jinja2 python-multipart anthropic
uv add --group etl pandas openpyxl docling pypdf
uv add --group dev pytest ruff

# Assets vendorizados: sin dependencia de red en vivo
mkdir -p app/static
curl -Lo app/static/htmx.min.js https://unpkg.com/htmx.org@2.0.4/dist/htmx.min.js
curl -Lo app/static/tailwind.js  https://cdn.tailwindcss.com/3.4.16
```

### 5.2 Durante la prueba

```bash
# ETL: insumos -> catalog.db  (local, con el grupo etl)
uv run --group etl python -m app.etl ./insumos --out catalog.db

# Correr local
uv run uvicorn app.main:app --reload --port 8080

# Tests del motor
uv run --group dev pytest -q
```

### 5.3 Deploy a Cloud Run

```bash
export PROJECT=<tu-project-id>
export REGION=us-central1
export IMG=$REGION-docker.pkg.dev/$PROJECT/recomendador/app

# --- una sola vez, la noche anterior ---
gcloud artifacts repositories create recomendador \
  --repository-format=docker --location=$REGION
gcloud auth configure-docker $REGION-docker.pkg.dev

# --- cada deploy ---
docker build -t $IMG:$(date +%H%M) -t $IMG:latest .
docker push $IMG:latest
gcloud run deploy recomendador \
  --image=$IMG:latest --region=$REGION \
  --allow-unauthenticated --port=8080 \
  --set-env-vars=ANTHROPIC_API_KEY=$ANTHROPIC_API_KEY

# --- 30 min antes de la demo: matar el cold start ---
gcloud run services update recomendador --region=$REGION --min-instances=1
```

> **La key va por `--set-env-vars`, nunca en la imagen ni en el repo** (doc 06 §R9).
> `.env` ya está en `.gitignore`.
> Cloud Run inyecta `$PORT`: uvicorn debe leerlo, no hardcodear 8080.

### 5.4 Plan B de deploy (corte T+2:00, doc 05)

```bash
cloudflared tunnel --url http://localhost:8080   # URL pública en ~3 min
```

---

## 6. Checklist de la noche anterior

Cada línea se marca **sólo si el comando respondió**, no si "debería andar".

- [ ] `uv sync --all-groups` termina sin error
- [ ] `uv run --group dev pytest -q` → 10 tests en verde
- [ ] `uv run python -c "import docling"` importa
- [ ] **Docling corre sobre un PDF de prueba y produce Markdown con encabezados**
- [ ] **Docling corre una SEGUNDA vez sin descargar nada** ← el que más importa
- [ ] `uv run python -c "import pypdf"` (el fallback existe)
- [ ] `app/static/htmx.min.js` y `tailwind.js` descargados y con tamaño > 0
- [ ] `docker build .` termina, y la imagen **no incluye** el grupo `etl`
- [ ] **Deploy de prueba a Cloud Run con un hola mundo → URL abierta desde el celular**
- [ ] `gcloud run services update ... --min-instances=1` probado y revertido
- [ ] `ANTHROPIC_API_KEY` exportada y probada con una llamada real
- [ ] Cachés de las 3 misiones semilla generables (doc 04 §6)
- [ ] **`CLAUDE.md` en la raíz del repo** (doc 07 §7.4)
- [ ] **Cuota de Claude Code verificada** ← no avisa cuando se agota
- [ ] Hotspot del celular probado con la laptop

> El penúltimo bloque —deploy de prueba— es el que más te puede salvar. Descubrir un
> problema de IAM o de puerto la noche anterior cuesta 20 minutos. Descubrirlo a T+5:00
> cuesta la prueba.

---

## 7. Claude Code — la herramienta que escribe el código

**Permitido explícitamente por las reglas de la prueba** (confirmado). Va en el camino
crítico: escribe la mayoría del código durante las 6 horas.

### 7.1 Dónde comprime y dónde no

El error sería asumir que todo se acelera parejo. No es así, y la diferencia importa:

| Bloque del doc 05 | Compresión | Por qué |
|---|---|---|
| T+0:00–0:45 triage y mapeo | **0 %** | Es criterio, no tipeo. Decidir que `precio_lista` es el precio y no `precio_sugerido` no lo hace el agente. |
| T+0:45–1:30 adaptador | ~20 % | Escribe el pandas rápido, pero **vos** decidís cada fila de la plantilla de mapeo. |
| T+1:30–1:45 deploy de humo | **0 %** | Es esperar builds y pushes. |
| T+1:45–2:45 motor | ~40 % | Está pre-construido; es cableado. |
| T+2:45–3:15 intérprete | ~30 % | El prompt está pre-escrito. |
| T+3:15–4:30 UI | **~50 %** | Jinja + Tailwind + HTMX es donde más rinde. |
| T+4:30–6:00 deploy, respaldo, ensayo | **0 %** | Nada de esto es código. |

**Realista: se liberan 45–60 minutos, casi todos en UI.**

### 7.2 Qué se hace con ese tiempo — y qué NO

**Los bloques del doc 05 se quedan escritos como están.** No los recalibro hacia abajo,
y es deliberado: **el plan sin agente es el plan B del plan con agente.** Si a T+2:30 se
cae la red o se agota la cuota, no hay nada que rehacer — seguís con el cronograma tal
cual, más lento, y llegás igual porque los cortes ya estaban calculados para eso.

Si se recalibrara hacia abajo, perder el agente rompería el plan entero. Así, el tiempo
liberado es **techo, no piso**.

Con esos 45–60 minutos, en este orden:

1. **El comparador lado a lado** (30 min, era el 2.º en caer del doc 03 §9). Vuelve a ser
   plausible y es la feature núcleo que hoy se sacrifica.
2. **La pantalla de diagnóstico** (20 min). Pasa de "se abre sólo si preguntan" a
   probable.
3. **Nada más.** El excedente sobrante va a ensayo, no a features.

> ⚠️ **El FEATURE FREEZE sigue a T+4:30, sin discusión.** La velocidad no cambia el
> congelamiento: el freeze existe por *riesgo*, no por cuánto alcanzaste a hacer.
> "Ahora escribo más rápido, así que puedo seguir hasta las 5" es exactamente el
> razonamiento que pierde la prueba.

### 7.3 El costo que el agente agrega

No todo es ganancia, y conviene tenerlo escrito:

- **Revisar código que no escribiste cuesta tiempo.** Con un dataset desconocido, el
  agente va a asumir cosas sobre los datos que no son ciertas. Por eso el bloque de
  adaptación comprime sólo un 20 %: el cuello de botella es verificar, no escribir.
- **Regla:** después de cada bloque, correr el código y **mirar la salida real** —
  no leer el diff y asumir. El script de consola del bloque T+1:45 existe para eso.
- **Los tests del §4 valen el doble acá.** Un bug de renormalización escrito por un
  agente es tan silencioso como uno escrito por vos, y lo revisás con menos desconfianza.

### 7.4 Preparación: `CLAUDE.md`

Va en la raíz del repo, escrito la noche anterior. Es lo que evita que a T+0:45 el agente
re-derive el contrato o proponga features que ya decidiste cortar. Contiene:

- El contrato y la **regla de degradación** (ausente ≠ cero).
- Los 4 campos obligatorios y nada más.
- El orden de corte de features y el FEATURE FREEZE.
- Que las citas nunca se redactan, se recortan.
- Prohibiciones: nada de frameworks de agentes, nada de ORM, nada de migraciones.

**Estrategia de contexto durante la prueba** — cargar sólo lo que corresponde al bloque:

| Bloque | Documentos a dar de contexto |
|---|---|
| Adaptador | `schema.py` + doc 01 + la plantilla de mapeo ya llena |
| Motor | `schema.py` + doc 02 |
| UI | `schema.py` + doc 03 |
| Deploy | doc 07 §5 |

Dar los 7 documentos en todos los bloques diluye el contexto y hace que el agente
mezcle decisiones de fases distintas.

### 7.5 Plan B

| Falla | Qué hacés | Costo |
|---|---|---|
| Se cae la red | Hotspot del celular, verificado la noche anterior | 2 min |
| Se agota la cuota | **Seguís con el cronograma del doc 05 tal cual.** Ese plan ya cierra sin agente. | 0 min de replanificación |
| El agente escribe algo que no entendés | No lo integrás. Lo reescribís simple. A T+3:00 un código feo que entendés vale más que uno elegante que no. | — |

**Verificar la cuota disponible la noche anterior.** Es la única herramienta del plan
cuyo agotamiento no te avisa con anticipación.
