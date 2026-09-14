"""Errores unificados de la capa LLM.

Ningún llamador —ni `app.llm.citation`, ni nada aguas arriba— debe atrapar
una excepción nativa de un proveedor concreto (`anthropic.APIError`, un
`HTTPError` de `urllib`, `google.auth.exceptions.DefaultCredentialsError`…).
Cada módulo de `app.llm.providers` traduce lo suyo a una de estas tres. Es lo
que permite que el resto de la app dependa sólo de `LLMError` sin conocer qué
proveedor está detrás.
"""

from __future__ import annotations


class LLMError(Exception):
    """Raíz de la jerarquía. No se levanta directamente."""


class LLMConfigError(LLMError):
    """Configuración inválida o incompleta: falta una variable de entorno
    obligatoria del proveedor seleccionado, o `LLM_PROVIDER` no está
    registrado en la fábrica. Se levanta al construir el proveedor, antes de
    llamar a nada por red — nunca a mitad de una respuesta.
    """


class LLMRequestError(LLMError):
    """La llamada al proveedor falló: red, timeout, credenciales rechazadas,
    rate limit, 4xx/5xx. El proveedor existe y está bien configurado; la
    llamada puntual no se pudo completar.
    """


class LLMOutputError(LLMError):
    """El proveedor respondió, pero la salida no sirve: no hay bloque
    estructurado, el JSON no parsea, o no valida contra el schema pedido.
    """
