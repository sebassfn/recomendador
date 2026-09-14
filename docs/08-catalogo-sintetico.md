# Catálogo sintético de pruebas

El catálogo tiene 876 productos: 786 de supermercado, 42 de autos y 48 de hogar.

| Prefijo | Productos | Origen |
|---|---|---|
| `CAT-*` | 10 | Originales de `scripts/seed_catalog.py` (3 categorías) |
| `PRD-*` | 132 | 44 familias cross-categoría × variantes Individual, Dúo y Familiar |
| `SUP-*` | 672 | 224 familias de supermercado × variantes Individual, Dúo y Familiar |
| `BRD-*` | 62 | Presentaciones de marcas comerciales para probar preferencia de marca |

Los nombres y marcas son comerciales reales; precios, existencias, atributos y
fichas son ficticios. Todas las señales de los productos generados
(`PRD-*`, `SUP-*`, `BRD-*`) tienen procedencia `simulated` y se etiquetan en la UI.
Los `CAT-*` salvo `CAT-G001` tienen señales parciales, para ver la redistribución
de pesos.

## Reproducir

Desde la raíz, con una base `catalog.db` que ya tenga la tabla `products`:

```bash
uv run python scripts/expand_catalog.py
```

También acepta una ruta de base como argumento. Es una ampliación transaccional:
no borra productos existentes; inserta o actualiza sus propios IDs `PRD-*`, `SUP-*` y `BRD-*`.
Repetirla no duplica filas. Cada producto se valida mediante el adaptador de
la aplicación antes de confirmar la transacción.

Para crear una base de prueba desde cero, en una ruta diferente de tu catálogo:

```bash
uv run python scripts/seed_catalog.py /tmp/catalog-pruebas.db
uv run python scripts/expand_catalog.py /tmp/catalog-pruebas.db
```

El script original `seed_catalog.py` reemplaza la base de destino: ejecutarlo
contra `catalog.db` vuelve a dejar únicamente los 10 productos originales.

## Supermercado ampliado

La fuente editable es `app/data/seeds/supermarket.csv`. Cada fila define una
familia con ID estable, subcategoría, nombre, unidad, tamaño de presentación,
precio base de referencia en USD y términos de búsqueda. No reutilizar IDs para
otras familias. `scripts/supermarket_catalog.py` genera las tres variantes
(Individual ×1, Dúo ×1,85, Familiar ×3,45 del precio base; 1, 2 y 4 unidades por
pack) y rota tres marcas comerciales por subcategoría; el precio representa la
presentación completa, no el precio por kg o litro. Por ejemplo, un pollo de 2 kg
tiene precio base total de $ 22,00.

Cobertura: frutas, verduras, aves, res, cerdo, pescados, mariscos, embutidos,
lácteos, huevos, panadería, granos, harinas, pastas, conservas, aceites,
condimentos, salsas, repostería, desayuno, snacks, congelados, bebidas,
licores, limpieza, higiene, bebés y mascotas (28 subcategorías).

Los nuevos productos pertenecen a `grocery`. Incluyen sinónimos y términos sin
tildes para búsquedas coloquiales. Las variantes Dúo tienen 8 % de promoción y
las Familiar 12 %. Hay casos controlados de stock bajo, agotado, desconocido y
productos inactivos; cada familia conserva al menos una variante activa con stock. Las edades de inventario de perecederos
refrigerados/frescos son sintéticas de 1 a 3 días. Las fichas son textos de demo,
no recomendaciones sanitarias ni certificados del producto.

Los atributos `storage`, `synthetic` y `contains_alcohol` (en licores) son
metadatos del catálogo; por sí mismos no implementan filtros de usuario.

Ejemplos adicionales para probar con el agente y un LLM configurado:

| Entrada | Productos disponibles para cubrirla |
|---|---|
| Compra semanal: leche, huevos, pan, pollo, arroz, frutas y verduras | Lácteos, huevos, panadería, aves, despensa y frescos |
| Asado para 8 adultos con costillas, chorizos, ensalada y cerveza | Res/cerdo, embutidos, verduras, chimichurri y cervezas |
| Cena especial con salmón, papas y vino blanco | Pescado, guarnición y vino |
| Cena navideña con pavo, arroz con pasas y panetón | Pavo congelado, arroz, pasas y panetón |
| Cumpleaños infantil con hot dogs, jugo, torta y gelatina | Pan, salchichas, jugos, torta y gelatina |
| Quiero hacer lasaña de carne con salsa de tomate y queso | Pasta de lasaña, carne molida, salsa, mozzarella y parmesano |
| Reponer azúcar, sal, comino, orégano, mayonesa y mostaza | Granos, condimentos y salsas |

## Frases para la interfaz

| Entrada | Qué explorar |
|---|---|
| Voy a la playa con 2 adultos y 2 niños; necesito bloqueador, agua y una hielera | Protección solar, hidratación, transporte térmico |
| Voy de camping y necesito carpa, sillas, repelente y agua | Necesidades distintas del ejemplo guardado de viaje |
| Necesito llantas 195/65R15 y aceite 10W40 para mi carro | Extracción de atributos y diferencias con otras medidas |
| Me mudo y necesito cajas, una repisa, sábanas y productos de limpieza | Hogar y supermercado |
| Organizo un cumpleaños con bebidas, vasos, platos y mantel | Evento y alternativas por necesidad |
| Necesito reponer arroz, lentejas, aceite, detergente y papel higiénico | Abastecimiento semanal |
| Necesito una silla de ruedas eléctrica | Necesidad fuera del catálogo; observar si el ranking propone algo irrelevante |

Estas frases requieren un LLM configurado para que el agente interprete todos los
detalles. Sin LLM, el fallback del agente (`app/mission_agent/keyword_fallback.py`)
clasifica por palabras clave y genera sus necesidades predefinidas. Los tres botones
de ejemplo siguen usando JSON en caché (`app/data/seeds/`), pero consultan el
catálogo ampliado para elegir los productos.

## Casos controlados

- Cada familia tiene tres precios y perfiles distintos de margen y rotación.
  La Individual es la más barata por pack, pero ser más barato no garantiza ganar.
- Algunas variantes Dúo tienen stock bajo; algunas Familiar están agotadas, tienen
  disponibilidad desconocida o están inactivas. El repositorio omite inactivos; el
  motor descarta agotados.
- La redistribución de pesos por señal ausente se observa con los `CAT-*`: todos los
  productos generados traen margen, rotación y marca propia.
- La variante Dúo tiene una ficha explícitamente ficticia, copiada de su descripción;
  las otras variantes generadas no tienen documentos.
- Carbón y parrillas están en `auto` para cubrir la categoría usada actualmente
  por la plantilla local de eventos; es una decisión de datos de esta demo.

## Productos con marca real (`BRD-*`)

Existen para probar la preferencia de marca (doc 02 §3.2) y la presentación
(`units_per_pack`, `volume_ml`, doc 01 §3.2). La marca es real; precios, stock y
señales son simulados y se etiquetan como tales en la UI. La fuente editable es
`app/data/seeds/branded.csv` (`scripts/branded_catalog.py` valida columnas, IDs y
rangos). Forma de una fila — es el fixture de `tests/test_catalog_adapter.py`, con
"(DEMO)" y `currency: "$"` a propósito para probar la tolerancia del adaptador; las
filas reales del catálogo usan `"USD"` y nombres limpios (p. ej. `BRD-010` "Oreo
Galleta chocolate paquete x12"):

```json
{
  "product_id": "BRD-004",
  "name": "Coca-Cola Sin Azúcar Pack x6 500ml (DEMO)",
  "category": "grocery", "subcategory": "bebidas", "raw_category": "supermercado/bebidas",
  "brand": "Coca-Cola",
  "description": "Gaseosa cola sin azúcar en botellas de 500 ml, paquete de 6 unidades. Producto y datos comerciales simulados.",
  "unit": "ml", "pack_size": 500,
  "price_amount": "24.90", "currency": "$", "promo_amount": "22.41", "is_active": 1,
  "attributes_json": "{\"units_per_pack\": 6, \"flavor\": \"cola\", \"sugar_free\": \"sí\", \"container_type\": \"botella\", \"volume_ml\": 500}",
  "stock_json": "[{\"store_id\": \"__ALL__\", \"status\": \"in_stock\", \"qty\": 30}]",
  "signals_json": "{\"margin_pct\": {\"value\": 0.28, \"source\": \"simulated\"}, \"turnover_index\": {\"value\": 8.5, \"source\": \"simulated\"}, \"is_private_label\": {\"value\": false, \"source\": \"simulated\"}}",
  "documents_json": "[]"
}
```

Reglas que el motor necesita de estos datos:

- `brand` limpio, sin "(DEMO)" pegado. Igual se tolera: la comparación ignora el
  token `demo`, mayúsculas, tildes y separadores ("Coca-Cola" = "coca cola").
- La descripción o el nombre deben decir el **tipo** de producto ("gaseosa cola",
  "galleta"): la marca sola no pasa el filtro de texto del slot.
- Varias presentaciones por marca con margen, rotación o promo distintos: es lo que
  hace visible que las señales comerciales eligen **cuál** producto de la marca va
  primero.
- `currency` acepta `"$"` o `"USD"`; ambos se muestran como `$`.

Frases de prueba: "quiero comprar coca-cola", "galletas oreo paquete de 12",
"quiero una gaseosa big cola" (marca inexistente → aviso y otras colas).
`tests/test_catalog_adapter.py` valida la fila de arriba;
`tests/test_web_routes.py::test_marca_pedida_ordena_primero_contra_el_catalogo_real`
recorre la ruta completa y se salta si el catálogo no tiene Coca-Cola.

## Límites actuales de las pruebas

El presupuesto declarado se muestra en el medidor de la UI, pero
`resolve_mission` (`app/services/basket_service.py`) no se lo pasa al motor, aunque
`app/engine/scoring.py` ya acepta `budget_remaining`. Las reglas de compatibilidad y
el filtro por tienda tampoco se pasan desde ese servicio. Las medidas permiten
explorar relevancia y atributos, pero no garantizan compatibilidad vehicular.
La web muestra el ganador y alternativas por slot, con las acciones "Optimizar
precio" y "Mejorar calidad"; los sliders de pesos del Modo Negocio todavía no existen en la UI.

Validación: cada producto generado pasa por el adaptador de la app antes de
confirmar la transacción, y repetir la ampliación no duplica filas.
`uv run pytest tests/test_supermarket_catalog.py tests/test_catalog_adapter.py tests/test_scoring.py`
cubre señales, citas, precios, disponibilidad por familia y ranking, sin llamadas
reales a proveedores LLM.
