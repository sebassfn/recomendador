"""Motor común de todo subagente: system prompt + instrucción -> salida
estructurada, opcionalmente con un loop acotado de tool-calling en el medio.

Un subagente NO es un grafo aparte ni un agente de un framework: es una
función async que arma mensajes, opcionalmente dejar al LLM llamar tools
reales (`bind_tools`), y siempre termina con una llamada de salida
estructurada (`with_structured_output`) contra el `output_model` que le pasa
el nodo que lo invoca. Eso es lo único que "sube" al estado del grafo — nunca
texto libre sin validar.

`max_tool_calls` acota el loop para que un subagente nunca se cuelgue
reintentando tools indefinidamente — es un límite de mecanismo, distinto del
`AGENT_MAX_SUBAGENT_ATTEMPTS` de negocio que vive en `graph/routing.py`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import BaseTool
from pydantic import BaseModel

from app.agent.llm.errors import respect_retry_after


@dataclass
class SubagentResult:
    output: dict[str, Any]
    tool_calls_made: int = 0
    transcript: list[str] = field(default_factory=list)
    """Resumen legible de qué tools se llamaron, para trazabilidad/logs."""


async def run_subagent(
    *,
    llm: BaseChatModel,
    system_prompt: str,
    instruction: str,
    output_model: type[BaseModel],
    tools: list[BaseTool] | None = None,
    max_tool_calls: int = 3,
    retry_after_cap: float = 30.0,
) -> SubagentResult:
    messages: list[BaseMessage] = [SystemMessage(system_prompt), HumanMessage(instruction)]
    transcript: list[str] = []
    tool_calls_made = 0

    if tools:
        bound = llm.bind_tools(tools)
        tools_by_name = {t.name: t for t in tools}
        for _ in range(max_tool_calls):
            try:
                ai_message = await bound.ainvoke(messages)
            except Exception as exc:
                await respect_retry_after(exc, cap=retry_after_cap)
                raise
            calls = getattr(ai_message, "tool_calls", None)
            if not calls:
                # Se descarta: la conversación no puede terminar en un turno
                # `assistant` cuando se reinvoca abajo para salida
                # estructurada (algunos modelos rechazan ese "prefill"), y su
                # contenido de texto no se usa -- la salida real sale de esa
                # llamada aparte.
                break
            messages.append(ai_message)
            for call in calls:
                tool = tools_by_name.get(call["name"])
                if tool is None:
                    result = f"Tool desconocida: {call['name']!r}"
                else:
                    result = await tool.ainvoke(call["args"])
                transcript.append(f"{call['name']}({call['args']}) -> {result!r}"[:300])
                messages.append(ToolMessage(content=str(result), tool_call_id=call["id"]))
                tool_calls_made += 1

    # `method="function_calling"` explícito: el default de `ChatOpenAI` (lo
    # que usa el proveedor `openrouter`) es `"json_schema"`, la API de
    # structured outputs propia de OpenAI -- OpenRouter no la traduce bien
    # para Claude corriendo detrás (Azure/Bedrock/Anthropic), y el modelo
    # devuelve el JSON envuelto en ```json...``` como texto plano en vez de
    # una tool call, lo que rompe el parseo. Tool-calling forzado sí lo
    # soportan bien los tres proveedores.
    structured_llm = llm.with_structured_output(output_model, method="function_calling")
    try:
        parsed = await structured_llm.ainvoke(messages)
    except Exception as exc:
        await respect_retry_after(exc, cap=retry_after_cap)
        raise

    output = parsed.model_dump(mode="json") if isinstance(parsed, BaseModel) else dict(parsed)
    return SubagentResult(output=output, tool_calls_made=tool_calls_made, transcript=transcript)
