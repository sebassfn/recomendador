"""Citas con respaldo documental — doc 01 §8.

Dos tramos, elegidos automáticamente por el tamaño del corpus indexado (§8.2):

- **Tramo A** (< ~50 000 palabras, §8.3): los documentos completos van en el
  contexto del LLM, en un bloque marcado `cache_control: ephemeral` porque son
  un **prefijo estable**: la primera llamada de la sesión lo escribe en caché,
  el resto de las misiones lo leen a ~0.1x. El modelo devuelve el fragmento
  literal (y su ubicación) que respalda el slot.
- **Tramo B** (>= ~50 000 palabras, §8.4): recall amplio por FTS5 sobre chunks
  de ~400 palabras (top 30, no top 10 — el corpus es chico y el rerank lo hace
  el LLM); el modelo elige el chunk y extrae el span.

**Regla no negociable, vale para los dos tramos (doc 02 §8):** el span que
devuelve el LLM se valida como **substring literal** del documento indexado.
Si no lo es, la cita se descarta y la función devuelve `None` — la tarjeta
muestra "sin respaldo documental". La cita nunca se redacta ni se completa a
mano; se recorta, o no existe.

Este módulo depende únicamente de `app.llm.contracts.LLMProvider` y no de un
SDK concreto: el
proveedor que responde es el que indique `LLM_PROVIDER` en el entorno
(`app.llm.factory`). Doc 01 §8.2 asume que este tramo siempre tiene la key de
Anthropic a mano porque en general va a ser el proveedor default del stack;
en la práctica cualquier `LLMProvider` configurado sirve para responder la
pregunta "qué fragmento respalda este slot". Lo único que es específico de
Anthropic es *cómo* se cachea el corpus del Tramo A: `cacheable_prefix` en
`StructuredCompletionRequest` es el punto de extensión para eso — el
proveedor que sepa cachear (hoy sólo `AnthropicProvider`, con
`cache_control: ephemeral`) lo hace con ese campo, el resto simplemente lo
concatena al mensaje y sigue funcionando, sin caché pero con la misma salida.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from sqlite3 import Connection
from typing import Any, Sequence

from pydantic import BaseModel, ValidationError

from app.domain.schema import Citation
from app.llm.contracts import LLMProvider, StructuredCompletionRequest
from app.llm.errors import LLMError, LLMOutputError
from app.llm.factory import get_provider_safe

logger = logging.getLogger(__name__)

# Umbral de palabras que decide el tramo (doc 01 §8.2). Se mide sobre el
# corpus completo que se le pasaría al Tramo A, no sobre un documento suelto.
TRAMO_A_MAX_WORDS = 50_000

# "Recall amplio: top 30, no top 10" (doc 01 §8.4 punto 3) — el corpus es
# chico, ser permisivo acá es gratis y el LLM hace de rerank.
FTS_TOP_K = 30

# "chunks de ~400 palabras con solape de 50" (doc 01 §8.4).
CHUNK_WORDS = 400
CHUNK_OVERLAP_WORDS = 50

_MAX_TOKENS = 1024


class Tramo(str, Enum):
    A = "A"  # sin recuperación: documentos completos en contexto
    B = "B"  # FTS5 + rerank por LLM


# ---------------------------------------------------------------------------
# Documentos de entrada
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SourceDocument:
    """Un documento indexable, con su texto partido por página/sección.

    `pages` existe para que el Tramo A pueda ofrecerle al modelo un locator
    ("p. 3") sin inventar uno: si el insumo no trae páginas, `from_text`
    mete todo en una sola entrada y el locator que devuelva el modelo para
    ese documento será `None` (degradación de doc 01 §3.6: "se cita el
    documento sin página/sección").
    """

    doc_id: str
    title: str
    pages: list[str] = field(default_factory=list)

    @classmethod
    def from_text(cls, doc_id: str, title: str, text: str) -> "SourceDocument":
        return cls(doc_id=doc_id, title=title, pages=[text])

    @property
    def text(self) -> str:
        """Concatenación de todas las páginas: es el documento tal como se
        indexa, y contra esto se valida la cita como substring literal."""
        return "\n\n".join(self.pages)

    @property
    def word_count(self) -> int:
        return len(self.text.split())


@dataclass(frozen=True)
class DocumentChunk:
    """Un chunk del Tramo B: unidad que devuelve la consulta FTS5."""

    doc_id: str
    doc_title: str
    text: str
    locator: str | None = None


def corpus_word_count(documents: Sequence[SourceDocument]) -> int:
    return sum(doc.word_count for doc in documents)


def choose_tramo(documents: Sequence[SourceDocument]) -> Tramo:
    """Selector automático de §8.2. Ninguna otra parte del código decide esto
    a mano: se mide el corpus y el tramo sale solo."""
    return Tramo.A if corpus_word_count(documents) < TRAMO_A_MAX_WORDS else Tramo.B


# ---------------------------------------------------------------------------
# Chunking para Tramo B (lo que alimenta `documents_fts`)
# ---------------------------------------------------------------------------


def chunk_document(document: SourceDocument, chunk_words: int = CHUNK_WORDS, overlap_words: int = CHUNK_OVERLAP_WORDS) -> list[DocumentChunk]:
    """Parte un documento en chunks de `chunk_words` palabras con solape de
    `overlap_words`, uno por página para no perder el locator (doc 01 §8.4:
    "`doc_id` y `locator` por chunk"). Si una página sola ya excede
    `chunk_words`, se sub-parte con solape dentro de esa misma página.
    """
    chunks: list[DocumentChunk] = []
    step = max(chunk_words - overlap_words, 1)

    for page_index, page_text in enumerate(document.pages, start=1):
        words = page_text.split()
        if not words:
            continue
        locator = f"p. {page_index}" if len(document.pages) > 1 else None

        start = 0
        while start < len(words):
            piece = " ".join(words[start : start + chunk_words])
            chunks.append(
                DocumentChunk(doc_id=document.doc_id, doc_title=document.title, text=piece, locator=locator)
            )
            if start + chunk_words >= len(words):
                break
            start += step

    return chunks


# ---------------------------------------------------------------------------
# Salida estructurada esperada del LLM (ambos tramos)
# ---------------------------------------------------------------------------


class _LLMCitationOutput(BaseModel):
    found: bool
    doc_id: str | None = None
    locator: str | None = None
    snippet: str | None = None


_TOOL_NAME = "emitir_cita"

_SCHEMA_DESCRIPTION = (
    "Registra el fragmento literal de un documento que respalda (o no) la "
    "necesidad consultada."
)

_CITATION_TOOL_SCHEMA: dict[str, Any] = _LLMCitationOutput.model_json_schema()

_SYSTEM_PROMPT = """Sos un buscador de respaldo documental para un retailer. Se te \
da una necesidad de compra y uno o más documentos (guías, fichas técnicas, \
manuales, políticas). Tu único trabajo es encontrar, si existe, el fragmento \
que respalda esa necesidad, usando la herramienta que se te da.

Reglas estrictas:

- El `snippet` que devuelvas tiene que ser una COPIA LITERAL de texto que \
aparece tal cual en el documento: mismos espacios, misma puntuación, mismas \
mayúsculas. Nunca lo resumas, nunca lo parafrasees, nunca lo completes con \
información que no esté escrita ahí. Se valida por comparación exacta de \
texto: si no calza carácter por carácter, la cita se descarta entera.
- Preferí el fragmento más corto que siga siendo una prueba completa y \
autocontenida (una oración o dos, no un párrafo entero).
- `locator` es la página o el encabezado de donde sacaste el fragmento, tal \
como aparece marcado en el documento (ej. "p. 3"). Si el documento no trae \
esa marca, dejalo en null.
- Si ningún documento respalda la necesidad, o el respaldo es dudoso/indirecto, \
devolvé `found=false` y dejá los demás campos en null. Es preferible no citar \
a forzar una cita débil.
"""


def _parse_citation_output(data: dict[str, Any], tramo: Tramo) -> _LLMCitationOutput:
    try:
        return _LLMCitationOutput.model_validate(data)
    except ValidationError as exc:
        raise LLMOutputError(f"Salida de cita (Tramo {tramo.value}) no valida contra el contrato: {exc}") from exc


def _validate_and_build(parsed: _LLMCitationOutput, lookup: dict[str, tuple[str, str]]) -> Citation | None:
    """`lookup`: doc_id -> (doc_title, texto_completo_del_documento).

    Acá vive la regla no negociable: sin substring literal no hay cita, sea
    cual sea el tramo que la produjo.
    """
    if not parsed.found or not parsed.doc_id or not parsed.snippet:
        return None

    doc_info = lookup.get(parsed.doc_id)
    if doc_info is None:
        logger.warning("Cita descartada: doc_id %r no está entre los documentos consultados.", parsed.doc_id)
        return None

    doc_title, doc_text = doc_info
    if parsed.snippet not in doc_text:
        logger.warning(
            "Cita descartada: el snippet devuelto no es substring literal de %r. snippet=%r",
            parsed.doc_id,
            parsed.snippet,
        )
        return None

    return Citation(
        doc_id=parsed.doc_id,
        doc_title=doc_title,
        locator=parsed.locator,
        snippet=parsed.snippet,
    )


# ---------------------------------------------------------------------------
# Tramo A — documentos completos en contexto, cache_control ephemeral
# ---------------------------------------------------------------------------


def _render_document_block(document: SourceDocument) -> str:
    if len(document.pages) <= 1:
        body = document.text
    else:
        body = "\n\n".join(f"[p. {i}]\n{page}" for i, page in enumerate(document.pages, start=1))
    return f'<documento id="{document.doc_id}" titulo="{document.title}">\n{body}\n</documento>'


def find_citation_tramo_a(
    query: str,
    documents: Sequence[SourceDocument],
    *,
    provider: LLMProvider | None = None,
) -> Citation | None:
    """§8.3. Todo el corpus va como `cacheable_prefix` (es un prefijo estable
    entre misiones: si el proveedor sabe cachear, ahí lo hace); la consulta va
    en `user_message`, porque cambia en cada llamada.

    `provider` es el punto de inyección de dependencias: por defecto se resuelve el que
    indique `LLM_PROVIDER` en el entorno (`app.llm.factory.get_provider_safe`),
    pero un test o un llamador explícito puede pasar cualquier `LLMProvider`.
    Sin proveedor configurado, se degrada a `None` (sin respaldo documental)
    en vez de tirar el corpus entero al contexto igual.
    """
    if not documents:
        return None

    resolved_provider = provider if provider is not None else get_provider_safe()
    if resolved_provider is None:
        logger.warning("Sin LLMProvider configurado; no se puede buscar cita (Tramo A).")
        return None

    corpus_block = "\n\n".join(_render_document_block(doc) for doc in documents)
    lookup = {doc.doc_id: (doc.title, doc.text) for doc in documents}

    request = StructuredCompletionRequest(
        system_prompt=_SYSTEM_PROMPT,
        user_message=f"Necesidad a respaldar: {query}",
        cacheable_prefix=corpus_block,
        schema_name=_TOOL_NAME,
        schema_description=_SCHEMA_DESCRIPTION,
        json_schema=_CITATION_TOOL_SCHEMA,
        max_tokens=_MAX_TOKENS,
    )
    result = resolved_provider.complete_structured(request)
    parsed = _parse_citation_output(result.data, Tramo.A)

    return _validate_and_build(parsed, lookup)


# ---------------------------------------------------------------------------
# Tramo B — FTS5 con recall amplio, el LLM elige el chunk y extrae el span
# ---------------------------------------------------------------------------


def _fts_match_query(keywords: Sequence[str]) -> str:
    """`OR` entre keywords, con truncado de plurales vía prefix match (`*`)
    en vez de stemming — doc 01 §8.4 punto 2. Cada término se cita entre
    comillas para que un keyword multi-palabra sea una frase, no tokens
    sueltos unidos por AND implícito."""
    terms = []
    for kw in keywords:
        kw = kw.strip().replace('"', "")
        if not kw:
            continue
        if " " in kw:
            terms.append(f'"{kw}"')
        else:
            terms.append(f'{kw}*')
    return " OR ".join(terms) if terms else ""


def search_chunks(conn: Connection, keywords: Sequence[str], top_k: int = FTS_TOP_K) -> list[DocumentChunk]:
    """Consulta `documents_fts` (doc_id, doc_title, locator, chunk) con BM25 y
    recall amplio. Tabla ausente o vacía degrada a `[]`, no a excepción: el
    llamador la trata igual que "no hubo match" (sin respaldo documental).
    """
    match_query = _fts_match_query(keywords)
    if not match_query:
        return []

    try:
        rows = conn.execute(
            """
            SELECT doc_id, doc_title, locator, chunk
            FROM documents_fts
            WHERE documents_fts MATCH ?
            ORDER BY bm25(documents_fts)
            LIMIT ?
            """,
            (match_query, top_k),
        ).fetchall()
    except Exception:
        logger.exception("Consulta FTS5 sobre documents_fts falló; se trata como sin resultados.")
        return []

    return [
        DocumentChunk(doc_id=row["doc_id"], doc_title=row["doc_title"], text=row["chunk"], locator=row["locator"])
        for row in rows
    ]


def find_citation_tramo_b(
    query: str,
    keywords: Sequence[str],
    conn: Connection,
    *,
    provider: LLMProvider | None = None,
) -> Citation | None:
    """§8.4. `keywords` los escribe el LLM del intérprete de misión
    (`BasketSlot.keywords`, ya expandidos con sinónimos) — este tramo no
    tokeniza la frase del cliente, controla la consulta desde el origen.

    `provider`: mismo punto de inyección que en `find_citation_tramo_a`. Acá
    no hay `cacheable_prefix`: los chunks que trae la búsqueda FTS cambian
    con cada consulta, no son un prefijo estable entre llamadas.
    """
    chunks = search_chunks(conn, keywords)
    if not chunks:
        return None

    resolved_provider = provider if provider is not None else get_provider_safe()
    if resolved_provider is None:
        logger.warning("Sin LLMProvider configurado; no se puede buscar cita (Tramo B).")
        return None

    chunks_block = "\n\n".join(
        f'<fragmento doc_id="{c.doc_id}" titulo="{c.doc_title}" locator="{c.locator or ""}">\n{c.text}\n</fragmento>'
        for c in chunks
    )
    # El mismo doc_id puede volver en varios chunks (páginas distintas del
    # mismo documento matchearon la búsqueda): la validación de substring
    # tiene que poder encontrar el snippet en CUALQUIERA de ellos, no sólo en
    # el último que se haya procesado — de ahí la concatenación en vez de un
    # `dict` que pisaría los chunks anteriores del mismo doc_id.
    grouped: dict[str, list[DocumentChunk]] = {}
    for c in chunks:
        grouped.setdefault(c.doc_id, []).append(c)
    lookup = {doc_id: (group[0].doc_title, "\n\n".join(c.text for c in group)) for doc_id, group in grouped.items()}

    request = StructuredCompletionRequest(
        system_prompt=_SYSTEM_PROMPT,
        user_message=(
            f"Fragmentos candidatos (elegí el que mejor respalde la necesidad, "
            f"o ninguno si no calza):\n\n{chunks_block}\n\n"
            f"Necesidad a respaldar: {query}"
        ),
        schema_name=_TOOL_NAME,
        schema_description=_SCHEMA_DESCRIPTION,
        json_schema=_CITATION_TOOL_SCHEMA,
        max_tokens=_MAX_TOKENS,
    )
    result = resolved_provider.complete_structured(request)
    parsed = _parse_citation_output(result.data, Tramo.B)

    return _validate_and_build(parsed, lookup)


# ---------------------------------------------------------------------------
# Punto de entrada único
# ---------------------------------------------------------------------------


def find_citation(
    query: str,
    keywords: Sequence[str] = (),
    documents: Sequence[SourceDocument] | None = None,
    conn: Connection | None = None,
    *,
    provider: LLMProvider | None = None,
) -> Citation | None:
    """Selecciona el tramo por tamaño de corpus (§8.2) y busca la cita.

    `documents` es el corpus completo (para Tramo A o para decidir el tramo).
    Si el corpus mide por debajo de `TRAMO_A_MAX_WORDS`, se usa Tramo A y
    `conn` no hace falta. Si mide por encima, hace falta `conn` con
    `documents_fts` ya indexada (Tramo B); sin `conn` se degrada a `None`
    en vez de tirar el corpus entero al contexto igual.

    `provider` inyecta un `LLMProvider` (real o de prueba); por defecto se
    resuelve el que indique `LLM_PROVIDER` en el entorno
    (`app.llm.factory.get_provider_safe`), no uno fijo a Anthropic.

    Nunca levanta `LLMError`: cualquier falla de configuración, red o
    validación de salida se loguea y se traduce a `None`, porque sin cita la recomendación sigue
    siendo válida (doc 01 §3.6), nunca hay que tumbar la request por esto.
    """
    documents = documents or []

    try:
        if choose_tramo(documents) is Tramo.A:
            return find_citation_tramo_a(query, documents, provider=provider)

        if conn is None:
            logger.warning("Corpus >= %d palabras (Tramo B) pero no se pasó `conn`; sin cita.", TRAMO_A_MAX_WORDS)
            return None
        return find_citation_tramo_b(query, keywords, conn, provider=provider)
    except LLMError:
        logger.exception("Búsqueda de cita falló; se degrada a 'sin respaldo documental'.")
        return None
