# 04 — Guion de demo

> **Supuesto asumido:** ~10 minutos de demo + preguntas. Si dan menos, se corta el
> escenario 3 (§4) y se conserva 1 y 2. Si dan más, se abre el diagnóstico de datos.
>
> Regla de oro: **la primera frase no describe la app, describe el negocio.** El
> jurado ya vio muchas demos de buscadores.

---

## 0. Apertura — 0:00 a 0:40

> "Esta empresa tiene un activo que casi ningún competidor tiene: vende el arroz, la
> llanta y el organizador de la sala **bajo el mismo techo**. Pero el cliente compra
> como si fueran tres tiendas distintas.
>
> Lo que construí no es un buscador. Es un **asesor de misión de compra**: el cliente
> dice para qué, no qué. Y el sistema arma una canasta que cruza las tres categorías.
> El KPI que ataca es ticket promedio e ítems por canasta.
>
> Tres reglas del diseño: **la base de datos decide qué existe, el negocio decide el
> orden, y el documento decide la explicación.** El modelo de lenguaje no hace
> ninguna de las tres."

*(Pantalla: P1, ya abierta, sin nada escrito.)*

> **Nota de entrega:** antes de empezar, dar la URL de Cloud Run al jurado para que la
> abran en su celular **mientras** se habla. Que la vean viva en su mano es la mitad
> del argumento de "esto es una app de verdad, no un notebook".

---

## 1. Escenario 1 — Misión de viaje cross-categoría · 0:40 a 3:20

**Entrada exacta** (chip semilla, cacheada):

> `Me voy con los niños a la playa este feriado largo, somos 4 y vamos en carro`

| Tiempo | Acción | Lo que digo |
|---|---|---|
| 0:40 | Clic en el chip. El texto aparece en el textarea. | "Una frase. Nada de categorías, nada de filtros." |
| 0:48 | Enviar. Aparece "Interpretando tu necesidad…" | "Acá, y **sólo acá**, hay un modelo de lenguaje. Su único trabajo es convertir esta frase en una lista de necesidades: hidratación para cuatro, protección solar para niños, algo donde llevar todo, revisión del carro. **No elige productos. No ve precios.**" |
| 1:05 | Aparece la canasta, agrupada por categoría. | "Y acá está lo que importa: **tres categorías**. Supermercado, autos y hogar. Ningún cliente hubiera pensado en las tres. El sistema sí." |
| 1:25 | Scroll a "Protección solar". Señalar la cita. | "Cada recomendación trae **la línea literal del documento** que la justifica. *'Para niños se recomienda SPF50 o superior'* — Guía de verano, página 4. No es el modelo redactando; es el texto recortado del documento." |
| 1:45 | Señalar el badge de stock. | "Y todo esto ya pasó por el filtro duro: existe, hay stock, está en la tienda. Un producto que no cumple **nunca llega a la pantalla**." |
| 2:00 | Abrir "Por qué no otros". | "Y cuando algo no aparece, el sistema dice por qué. Este bloqueador quedó fuera porque está sin stock; este otro, porque excede el presupuesto del ítem." |
| 2:15 | Señalar el resumen. | "9 ítems, tres categorías, **+47 % de ticket** contra la canasta que habría armado si sólo resolvíamos la categoría obvia del pedido." |
| **2:30** | **⚡ ACTIVAR MODO NEGOCIO** | "Todo lo que vieron es la vista del cliente. Ahora la del negocio." |
| 2:35 | El panel se despliega. Dejar 3 segundos de silencio. | "Mismo pedido, misma canasta, otra lente: margen, rotación y marca propia por producto. Y el score descompuesto en sus componentes." |
| 2:50 | **Subir "Prioridad de margen" despacio.** La lista se reordena en vivo. | "Y esto es lo que un category manager pide de verdad: **poder inclinar el ranking sin tocar código**." |
| 3:05 | Subir "Liquidar inventario". | "Esto sube el stock antiguo. Es la palanca que convierte inventario parado en ticket." |
| 3:15 | Señalar el piso de relevancia. | "Pero fíjense: por mucho que suba, **la relevancia tiene un piso del 20 %**. El negocio puede inclinar el ranking. No puede secuestrarlo. Eso es una decisión de producto, y está en el código." |

> **Si el Modo Negocio no llegó a implementarse**, este bloque se reemplaza por abrir
> la vista de diagnóstico y decir: "y el sistema declara qué señales tiene y cuáles no;
> los sliders comerciales son el siguiente paso, con el motor ya preparado para
> recibirlos". No se improvisa una explicación larga: se cambia de escenario.

---

## 2. Escenario 2 — Compatibilidad / fitment · 3:20 a 5:10

**Entrada exacta:**

> `Necesito hacerle mantenimiento al carro antes de viajar, es un Toyota Yaris 2018`

| Tiempo | Acción | Lo que digo |
|---|---|---|
| 3:20 | Enviar. | "Segunda misión, otro eje. Acá hay un dato que cambia todo: el modelo del vehículo." |
| 3:35 | Aparece la canasta con el slot de llantas. | "El sistema entendió el vehículo y lo convirtió en una **restricción dura**: medida 185/65R15." |
| 3:50 | Señalar el badge de compatibilidad verificada. | "Esta llanta no aparece porque el modelo crea que sirve. Aparece porque **el atributo del producto coincide con la medida del vehículo**, verificado contra la base. Es una comparación, no una opinión." |
| 4:05 | Abrir "Por qué no otros" en el slot de llantas. | "Y estas quedaron fuera por incompatibles. En una categoría donde equivocarse cuesta una devolución y un cliente, poder mostrar **por qué no** vale tanto como el por qué sí." |
| 4:20 | Señalar los otros slots. | "Pero fíjense qué más armó: líquido limpiaparabrisas del supermercado y un organizador de maletera de hogar. **Otra vez cruzó las tres.** Nadie entra a comprar llantas y sale con un organizador… salvo que se lo propongas en el momento correcto." |
| 4:40 | Abrir el detalle de la llanta. | "Ficha completa, atributos, disponibilidad por tienda, y la cita del manual que respalda la recomendación." |
| 5:00 | Cerrar. | "Este es el eje de compatibilidad: es donde el catálogo estructurado gana a cualquier chat." |

> **Degradación en vivo:** si el dataset no trajo atributos de fitment, este escenario
> se sustituye por el de presupuesto (doc 06 §R4) y se dice en voz alta: *"el dataset
> de la prueba no trae atributos de compatibilidad, así que la verificación corre por
> coincidencia de medida en el nombre; la regla ya está modelada y sólo espera el
> dato"*. **Se dice, no se disimula.** Un jurado técnico detecta el maquillaje.

---

## 3. Escenario 3 — Canasta con presupuesto · 5:10 a 6:40

**Entrada exacta:**

> `Me mudo a un departamento chico y tengo 300 soles para organizarlo`

| Tiempo | Acción | Lo que digo |
|---|---|---|
| 5:10 | Enviar, con el presupuesto en el campo. | "Tercera misión. Acá hay una restricción que la mayoría de recomendadores ignora: **la plata**." |
| 5:25 | Aparece la canasta dentro del presupuesto. | "El presupuesto no es un filtro sobre productos sueltos, es una restricción sobre **la canasta entera**. Se reparte entre las necesidades según prioridad." |
| 5:45 | Señalar un slot vacío o degradado. | "Y cuando algo no entra, el sistema **lo deja vacío y lo dice**, en vez de armar una canasta que miente sobre el total." |
| 6:00 | Subir el presupuesto y reenviar. | "Si subo el presupuesto, el slot se llena. La canasta responde a la restricción real del cliente." |
| 6:20 | Modo Negocio sobre esta canasta. | "Y con la lente de negocio: dentro del mismo presupuesto, el sistema puede favorecer marca propia sin sacarse de encima lo que el cliente pidió." |

---

## 4. Cierre — 6:40 a 7:30

> "Resumo en tres frases.
>
> Uno: **el filtro duro lo hace la base de datos**, nunca el modelo. Por eso no puede
> recomendar algo que no existe o que no hay.
>
> Dos: **el ranking es un score ponderado, auditable y ajustable en vivo.** Lo acaban
> de ver moverse. Un modelo de caja negra no se puede gobernar así.
>
> Tres: **la explicación cita el documento, literal.** Y cuando no hay documento, la
> app lo dice en vez de inventar.
>
> Lo que no está: no hay histórico de compras, así que no hay personalización. Con esa
> señal, el mismo motor admite una capa de colaborative filtering sobre la señal de
> relevancia, **sin tocar el resto de la arquitectura**. Ese es el siguiente paso, y el
> motor ya está estructurado para recibirlo."

---

## 5. Las 9 preguntas del jurado

### P1 — "¿Dónde está el modelo de machine learning?"

*La pregunta que va a caer sí o sí. Respuesta preparada, sin defensiva:*

> "En un solo lugar, y a propósito: **interpretar la necesidad**. Convertir 'me voy con
> los niños a la playa' en una lista estructurada de necesidades es un problema de
> lenguaje, y ahí un LLM es la herramienta correcta.
>
> Donde deliberadamente **no** lo puse es en elegir el producto y en ordenarlo. Y esa
> es una decisión de diseño, no una limitación de tiempo. Tres razones:
>
> **Primera: no hay con qué entrenar.** Un ranker aprendido necesita histórico de
> clics, conversiones o compras. En un catálogo que hoy no tiene esa señal etiquetada,
> un modelo de ranking sería un número inventado con más pasos.
>
> **Segunda: un ranking aprendido no se gobierna.** Ustedes acaban de mover tres
> sliders y ver el orden cambiar. Con un modelo entrenado, la respuesta a 'quiero
> empujar marca propia este trimestre' es un ciclo de reentrenamiento. Acá es un
> slider. Para un retailer, la capacidad de inclinar el ranking por decisión comercial
> **es** el producto.
>
> **Tercera: es auditable.** Cada score se abre en sus componentes en pantalla. Cuando
> algo se recomienda, se puede decir exactamente por qué.
>
> Dicho eso, **sé exactamente dónde entra el ML cuando haya datos**: la señal de
> relevancia es un solo término de la fórmula. Se reemplaza por un modelo aprendido de
> co-ocurrencia de canastas o un two-tower, y el resto de la arquitectura — filtro
> duro, pesos comerciales, explicación — no cambia una línea. El motor está diseñado
> para ese reemplazo."

### P2 — "¿Cómo evitan que el modelo alucine productos o precios?"

> "Estructuralmente: el modelo **nunca ve el catálogo**. Recibe la frase y devuelve un
> objeto con necesidades. Los productos los busca y los filtra Python contra SQLite.
> Aunque el modelo alucinara un producto, no hay ruta por la que llegue a pantalla.
>
> Y las citas son texto **recortado** del documento indexado, no redactado por el
> modelo. Si no hay documento que respalde, la tarjeta dice 'sin respaldo documental'."

### P3 — "¿Qué pasa si el dataset no tiene margen / stock / atributos?"

> "Está previsto campo por campo, y es la razón por la que esta app funciona hoy con
> los datos que me dieron. Cada señal declara su comportamiento degradado: si no hay
> margen, el slider se deshabilita con la leyenda 'no disponible en este dataset' y su
> peso se **redistribuye** entre las señales vivas — no se pone en cero, porque cero
> castigaría al producto por un defecto del dato.
>
> Y hay una pantalla de diagnóstico que muestra exactamente qué campos se resolvieron,
> cuáles se derivaron, cuáles se simularon y qué features quedaron degradadas."
>
> *(Si preguntan más, abrir P5.)*

### P4 — "¿Esto escala a un catálogo real de cientos de miles de SKU?"

> "Lo que hoy corre en SQLite con FTS5 es exactamente la misma arquitectura de tres
> capas. Lo que cambia al escalar es la implementación de la capa 1: el filtro duro
> pasa a un índice de búsqueda — Elastic, OpenSearch, o el motor que ya tengan — y el
> ranking se aplica sobre un candidate set de 50 a 200 por slot, que es lo que hace
> hoy. El costo de ranking **no depende del tamaño del catálogo**, depende del tamaño
> del candidate set, y ese ya está acotado.
>
> El punto de presión real no es el catálogo, es la llamada al LLM: 1 a 3 segundos por
> misión. Se resuelve con caché de misiones frecuentes — que ya está implementada — y
> con un clasificador liviano para las intenciones más comunes."

### P5 — "Ese +47 % de ticket, ¿de dónde sale?"

*No inflar. Esta es una pregunta trampa y la honestidad gana:*

> "Es una comparación estructural, no una medición causal, y quiero ser preciso: compara
> el ticket de la canasta cross-categoría contra el ticket de resolver **sólo la
> categoría obvia del pedido**. Es el tamaño de la oportunidad que hoy se deja sobre la
> mesa, no una predicción de conversión.
>
> Para convertirlo en una cifra real hace falta un A/B con tráfico. Lo que sí puedo
> afirmar con los datos de la prueba es cuántas categorías cruza cada canasta y cuántos
> ítems tiene — y eso es directamente el KPI de ítems por canasta."

### P6 — "¿Por qué no un chatbot? Un chat es más natural."

> "Porque un chat pone al cliente a escribir varias veces y no le deja **ver** la
> canasta. Acá el output no es texto: es una canasta editable, con precios reales,
> stock real y un total. El cliente puede sacar un ítem, cambiar la cantidad y ver el
> total moverse.
>
> Y para el negocio, un chat es casi imposible de gobernar: no hay dónde poner el peso
> de margen. Acá el punto de control es explícito."

### P7 — "¿Cómo manejan el cliente que ya sabe exactamente qué quiere?"

> "Ese cliente no es el usuario de esta herramienta y no hay que forzarlo: escribe
> 'llanta 185/65R15' y el mismo motor le devuelve ese slot resuelto con sus
> alternativas. La misión con un solo slot es un buscador.
>
> Si además nombra una marca —'galletas Oreo paquete de 12'— la marca pasa al plan
> tal cual la escribió y esa marca va primero; el 'paquete de 12' es una
> especificación dura y deja fuera los paquetes de 6. Si no tengo la marca, se lo
> digo y le muestro otras. Y la palanca comercial sigue viva donde corresponde:
> decide **cuál** Coca-Cola, nunca le cambia Coca-Cola por Pepsi."
>
> *Para mostrarlo en vivo:* "quiero comprar coca-cola" (chip de marca, Coca-Cola
> primero), "galletas oreo paquete de 12" (sólo el pack x12), "quiero una gaseosa big
> cola" (aviso de marca no encontrada).
>
> "
> El valor diferencial aparece en la intención difusa, que es donde el buscador
> tradicional devuelve cero resultados y el cliente se va."

### P8 — "¿Qué harías con una semana más?"

*Tener la respuesta lista demuestra que se sabe qué falta:*

> "Tres cosas, en este orden.
>
> **Una:** señal de co-compra desde el histórico de transacciones. Es lo que convierte
> los slots de una plantilla a una canasta aprendida de lo que la gente realmente
> compra junto, y es el primer lugar donde entra ML de verdad.
>
> **Dos:** evaluación. Un set de 50 misiones etiquetadas a mano con la canasta esperada,
> para medir cobertura de slots y precisión, y poder decir si un cambio de pesos mejora
> o empeora. Hoy no tengo esa medición y no voy a pretender que sí.
>
> **Tres:** las palancas comerciales persistidas por categoría y por temporada, en vez
> de sliders de sesión. Es el paso de demo a herramienta operativa."

### P9 — "¿Escribiste esto vos o lo escribió una IA?"

*Permitido por las reglas, así que no hay nada que esconder. Pero la respuesta no es
"sí": es mostrar dónde estuvo tu criterio.*

> "Usé Claude Code para escribir código, sí — es la herramienta que me permitió entregar
> esto en seis horas en vez de dos días.
>
> Lo que no delegué son las decisiones, que es lo que me parece que están evaluando:
> el esquema canónico con sus cuatro campos obligatorios, la regla de que una señal
> ausente se redistribuye en vez de valer cero, el piso de relevancia del 20 %, el orden
> en que sacrifico features si el reloj aprieta, y qué hago cuando el dataset no trae
> margen. Eso está escrito y decidido antes de tocar los datos.
>
> Puedo mostrarles el documento de degradación: cada campo que puede faltar tiene
> declarado qué hace el sistema sin él. Ninguna herramienta toma esas decisiones por
> vos — y son las que hacen que esta app funcione con el dataset que me dieron hoy."

*(Si insisten, abrir `docs/01-contrato-de-datos.md` §3 o la pantalla de diagnóstico.)*

---

## 6. Contingencias en vivo

| Falla | Qué hago | Qué digo |
|---|---|---|
| La app no carga | Cambiar a la pestaña de respaldo, ya abierta con los 3 escenarios precargados. | "Tengo la versión local, sigo desde acá." *(Sin disculparse dos veces.)* |
| El LLM no responde | Los 3 chips semilla están **cacheados en disco**: no llaman a la API. | *(Nada. El jurado no se entera.)* |
| Se cae el wifi | Seguir con capturas en pantalla completa (carpeta `respaldo/`, 6 imágenes: canasta, cita, modo negocio antes/después, fitment, diagnóstico). | "Sigo con capturas del mismo flujo mientras vuelve." |
| Un escenario devuelve una canasta pobre | No insistir. Pasar al siguiente. | "Este caso tiene poca cobertura en el dataset de la prueba; el siguiente lo muestra mejor." |
| Cold start de Cloud Run | `min-instances=1` desde 30 min antes. Además, abrir la URL uno mismo justo antes de empezar. | — |

**Checklist de 10 minutos antes:**

- [ ] `min-instances=1` aplicado y confirmado.
- [ ] URL abierta y respondiendo en **el propio celular**.
- [ ] Los 3 chips semilla devuelven canasta desde caché (probados).
- [ ] Pestaña de respaldo local abierta en segundo plano.
- [ ] Carpeta `respaldo/` con las 6 capturas.
- [ ] Modo Negocio probado en móvil (la hoja inferior abre y los sliders responden).
- [ ] Notificaciones del sistema silenciadas.
