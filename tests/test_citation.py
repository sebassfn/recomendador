"""Tests de citas con respaldo documental (app/llm/citation.py, doc 01 §8).

El caso que manda es la regla no negociable de doc 02 §8: un snippet que el
LLM devuelve pero que NO es substring literal del documento se descarta y la
función devuelve `None`, sea cual sea el tramo. Se prueba inyectando un
`LLMProvider` falso (mismo patrón que `tests/test_interpreter.py` usa para
`interpret_mission`) para no depender de red, credenciales, ni de qué
proveedor esté configurado en `LLM_PROVIDER`.
"""

from __future__ import annotations

import sqlite3

import pytest

from app.llm import citation
from app.llm.contracts import LLMProvider, StructuredCompletionRequest, StructuredCompletionResult
from app.llm.citation import (
    Tramo,
    chunk_document,
    choose_tramo,
    find_citation_tramo_a,
    find_citation_tramo_b,
    search_chunks,
)
from app.llm.citation import SourceDocument


class _FakeProvider(LLMProvider):
    """Proveedor de prueba: no llama a nada, sólo devuelve lo que se le
    configuró y guarda el último `request` recibido para poder inspeccionar
    qué le pasó `citation.py` (p. ej. que `cacheable_prefix` sea el corpus y
    `user_message` sólo la consulta)."""

    name = "fake"

    def __init__(self, data: dict | None = None) -> None:
        self._data = data or {}
        self.last_request: StructuredCompletionRequest | None = None

    def complete_structured(self, request: StructuredCompletionRequest) -> StructuredCompletionResult:
        self.last_request = request
        return StructuredCompletionResult(data=self._data, provider=self.name, model="fake-model")


# ---------------------------------------------------------------------------
# Selector de tramo (§8.2)
# ---------------------------------------------------------------------------


def test_choose_tramo_small_corpus_is_a() -> None:
    docs = [SourceDocument.from_text("doc-1", "Guía corta", "protector solar SPF 50 para toda la familia")]
    assert choose_tramo(docs) is Tramo.A


def test_choose_tramo_large_corpus_is_b(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(citation, "TRAMO_A_MAX_WORDS", 5)
    docs = [SourceDocument.from_text("doc-1", "Guía larga", "una dos tres cuatro cinco seis siete")]
    assert choose_tramo(docs) is Tramo.B


# ---------------------------------------------------------------------------
# Tramo A — documentos completos en contexto
# ---------------------------------------------------------------------------


def test_tramo_a_literal_snippet_is_accepted() -> None:
    text = "Aplicar el protector solar SPF 50 cada dos horas de exposición directa."
    docs = [SourceDocument.from_text("doc-1", "Guía de playa", text)]
    fake = _FakeProvider(
        {
            "found": True,
            "doc_id": "doc-1",
            "locator": None,
            "snippet": "protector solar SPF 50 cada dos horas",
        }
    )

    result = find_citation_tramo_a("protección solar para la playa", docs, provider=fake)

    assert result is not None
    assert result.doc_id == "doc-1"
    assert result.doc_title == "Guía de playa"
    assert result.snippet in text


def test_tramo_a_fabricated_snippet_is_discarded() -> None:
    """El test pedido: un snippet que el modelo "alucina" (no está en el
    documento) nunca se convierte en una `Citation` — se descarta y la
    función devuelve `None` ("sin respaldo documental")."""
    text = "Aplicar el protector solar SPF 50 cada dos horas de exposición directa."
    docs = [SourceDocument.from_text("doc-1", "Guía de playa", text)]
    fake = _FakeProvider(
        {
            "found": True,
            "doc_id": "doc-1",
            "locator": "p. 1",
            "snippet": "el protector solar SPF 100 dura todo el día sin reaplicar",
        }
    )

    result = find_citation_tramo_a("protección solar para la playa", docs, provider=fake)

    assert result is None


def test_tramo_a_found_false_returns_none() -> None:
    docs = [SourceDocument.from_text("doc-1", "Guía de playa", "no hay nada relevante acá")]
    fake = _FakeProvider({"found": False, "doc_id": None, "locator": None, "snippet": None})

    result = find_citation_tramo_a("llantas para el auto", docs, provider=fake)

    assert result is None


def test_tramo_a_unknown_doc_id_is_discarded() -> None:
    docs = [SourceDocument.from_text("doc-1", "Guía de playa", "protector solar SPF 50")]
    fake = _FakeProvider({"found": True, "doc_id": "doc-inexistente", "locator": None, "snippet": "protector solar"})

    result = find_citation_tramo_a("protección solar", docs, provider=fake)

    assert result is None


def test_tramo_a_sends_corpus_as_cacheable_prefix_separate_from_query() -> None:
    docs = [SourceDocument.from_text("doc-1", "Guía de playa", "protector solar SPF 50")]
    fake = _FakeProvider({"found": False})

    find_citation_tramo_a("protección solar", docs, provider=fake)

    request = fake.last_request
    assert request is not None
    assert request.cacheable_prefix is not None
    assert "doc-1" in request.cacheable_prefix
    assert "protección solar" in request.user_message
    assert "doc-1" not in request.user_message


def test_tramo_a_empty_documents_returns_none_without_calling_provider() -> None:
    fake = _FakeProvider({"found": True, "doc_id": "doc-1", "snippet": "x"})

    result = find_citation_tramo_a("cualquier cosa", [], provider=fake)

    assert result is None
    assert fake.last_request is None


def test_tramo_a_without_provider_configured_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    from app.llm import factory

    factory.reset_provider_cache()
    docs = [SourceDocument.from_text("doc-1", "Guía de playa", "protector solar SPF 50")]

    result = find_citation_tramo_a("protección solar", docs)

    assert result is None


# ---------------------------------------------------------------------------
# Chunking (insumo de Tramo B)
# ---------------------------------------------------------------------------


def test_chunk_document_tags_locator_per_page() -> None:
    doc = SourceDocument(doc_id="doc-1", title="Manual", pages=["contenido de la primera página", "contenido de la segunda página"])

    chunks = chunk_document(doc, chunk_words=100, overlap_words=10)

    assert [c.locator for c in chunks] == ["p. 1", "p. 2"]
    assert all(c.doc_id == "doc-1" for c in chunks)


def test_chunk_document_splits_long_page_with_overlap() -> None:
    words = [f"palabra{i}" for i in range(1000)]
    doc = SourceDocument.from_text("doc-1", "Manual largo", " ".join(words))

    chunks = chunk_document(doc, chunk_words=400, overlap_words=50)

    assert len(chunks) == 3  # 0-400, 350-750, 700-1000
    assert chunks[0].text.split()[-1] == chunks[1].text.split()[49]  # solape de 50 palabras


def test_chunk_document_single_page_has_no_locator() -> None:
    doc = SourceDocument.from_text("doc-1", "Manual", "una sola página sin marcar")

    chunks = chunk_document(doc)

    assert chunks[0].locator is None


# ---------------------------------------------------------------------------
# Tramo B — FTS5 + rerank por LLM
# ---------------------------------------------------------------------------


@pytest.fixture
def fts_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        """CREATE VIRTUAL TABLE documents_fts USING fts5(
            doc_id, doc_title, locator, chunk,
            tokenize="unicode61 remove_diacritics 2"
        )"""
    )
    conn.execute(
        "INSERT INTO documents_fts (doc_id, doc_title, locator, chunk) VALUES (?, ?, ?, ?)",
        ("doc-1", "Guía de neumáticos", "p. 2", "La presión recomendada para llantas 185/65R15 es de 32 PSI en frío."),
    )
    conn.execute(
        "INSERT INTO documents_fts (doc_id, doc_title, locator, chunk) VALUES (?, ?, ?, ?)",
        ("doc-2", "Política de garantía", "encabezado: Devoluciones", "Las devoluciones se aceptan dentro de los 30 días con boleta."),
    )
    conn.commit()
    return conn


def test_search_chunks_finds_match_with_or_and_wildcard(fts_conn: sqlite3.Connection) -> None:
    results = search_chunks(fts_conn, ["llanta", "neumatico"])

    assert any(r.doc_id == "doc-1" for r in results)


def test_search_chunks_missing_table_returns_empty_not_exception() -> None:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row

    results = search_chunks(conn, ["llanta"])

    assert results == []


def test_search_chunks_no_keywords_returns_empty(fts_conn: sqlite3.Connection) -> None:
    assert search_chunks(fts_conn, []) == []


def test_tramo_b_literal_snippet_is_accepted(fts_conn: sqlite3.Connection) -> None:
    fake = _FakeProvider(
        {
            "found": True,
            "doc_id": "doc-1",
            "locator": "p. 2",
            "snippet": "32 PSI en frío",
        }
    )

    result = find_citation_tramo_b("presión de llantas", ["llanta", "presion"], fts_conn, provider=fake)

    assert result is not None
    assert result.doc_id == "doc-1"
    assert result.doc_title == "Guía de neumáticos"
    assert result.snippet == "32 PSI en frío"


def test_tramo_b_fabricated_snippet_is_discarded(fts_conn: sqlite3.Connection) -> None:
    fake = _FakeProvider(
        {
            "found": True,
            "doc_id": "doc-1",
            "locator": "p. 2",
            "snippet": "la presión ideal es 40 PSI para uso en autopista",
        }
    )

    result = find_citation_tramo_b("presión de llantas", ["llanta", "presion"], fts_conn, provider=fake)

    assert result is None


def test_tramo_b_accepts_snippet_from_an_earlier_chunk_of_a_repeated_doc_id() -> None:
    """Regresión: cuando la misma búsqueda FTS devuelve varios chunks del
    mismo `doc_id` (páginas distintas de un documento multi-página que
    matchean), la validación tiene que poder encontrar el snippet en
    CUALQUIERA de ellos — no sólo en el último que se procesó. Un `dict`
    ingenuo `{doc_id: chunk}` pisa los chunks anteriores del mismo doc_id y
    descarta citas legítimas.
    """
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        """CREATE VIRTUAL TABLE documents_fts USING fts5(
            doc_id, doc_title, locator, chunk,
            tokenize="unicode61 remove_diacritics 2"
        )"""
    )
    conn.execute(
        "INSERT INTO documents_fts (doc_id, doc_title, locator, chunk) VALUES (?, ?, ?, ?)",
        ("doc-1", "Guía de la llanta", "p. 1", "Cambiar una llanta pinchada es una habilidad esencial para todo conductor."),
    )
    conn.execute(
        "INSERT INTO documents_fts (doc_id, doc_title, locator, chunk) VALUES (?, ?, ?, ?)",
        ("doc-1", "Guía de la llanta", "p. 2", "Afloje las tuercas antes de levantar el vehículo con el gato."),
    )
    conn.commit()

    fake = _FakeProvider(
        {
            "found": True,
            "doc_id": "doc-1",
            "locator": "p. 1",
            # Substring literal del chunk de la página 1, NO del de la
            # página 2 (que es el que quedaría si el lookup se pisara).
            "snippet": "Cambiar una llanta pinchada es una habilidad esencial",
        }
    )

    result = find_citation_tramo_b("cómo cambiar una llanta", ["llanta"], conn, provider=fake)

    assert result is not None
    assert result.locator == "p. 1"


def test_tramo_b_no_chunks_returns_none_without_calling_provider(fts_conn: sqlite3.Connection) -> None:
    fake = _FakeProvider({"found": True, "doc_id": "doc-1", "snippet": "x"})

    result = find_citation_tramo_b("algo sin ningún match posible", ["xyzxyzxyz"], fts_conn, provider=fake)

    assert result is None
    assert fake.last_request is None


def test_tramo_b_request_has_no_cacheable_prefix(fts_conn: sqlite3.Connection) -> None:
    fake = _FakeProvider({"found": False})

    find_citation_tramo_b("presión de llantas", ["llanta"], fts_conn, provider=fake)

    assert fake.last_request is not None
    assert fake.last_request.cacheable_prefix is None


# ---------------------------------------------------------------------------
# Punto de entrada único
# ---------------------------------------------------------------------------


def test_find_citation_routes_small_corpus_to_tramo_a() -> None:
    docs = [SourceDocument.from_text("doc-1", "Guía", "protector solar SPF 50 recomendado")]
    fake = _FakeProvider({"found": True, "doc_id": "doc-1", "snippet": "protector solar SPF 50"})

    result = citation.find_citation("protección solar", documents=docs, provider=fake)

    assert result is not None
    assert result.snippet == "protector solar SPF 50"


def test_find_citation_large_corpus_without_conn_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(citation, "TRAMO_A_MAX_WORDS", 3)
    docs = [SourceDocument.from_text("doc-1", "Guía", "una dos tres cuatro cinco")]
    fake = _FakeProvider({"found": True, "doc_id": "doc-1", "snippet": "x"})

    result = citation.find_citation("algo", documents=docs, conn=None, provider=fake)

    assert result is None
    assert fake.last_request is None


def test_find_citation_routes_large_corpus_to_tramo_b(monkeypatch: pytest.MonkeyPatch, fts_conn: sqlite3.Connection) -> None:
    monkeypatch.setattr(citation, "TRAMO_A_MAX_WORDS", 3)
    docs = [SourceDocument.from_text("doc-1", "Guía", "una dos tres cuatro cinco")]
    fake = _FakeProvider({"found": True, "doc_id": "doc-1", "locator": "p. 2", "snippet": "32 PSI en frío"})

    result = citation.find_citation(
        "presión de llantas", keywords=["llanta"], documents=docs, conn=fts_conn, provider=fake
    )

    assert result is not None
    assert result.doc_id == "doc-1"
