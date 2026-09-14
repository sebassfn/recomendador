"""Arma y compila el grafo. Se llama UNA vez por proceso
(`AgentService.create`) con el `AgentRuntime` ya armado -- el grafo compilado
se reutiliza para todas las corridas, cada una con su propio `thread_id`.

```mermaid
flowchart TD
    START --> intake --> shortcut
    shortcut -- hit --> finalize
    shortcut -- miss --> orchestrator
    orchestrator -- Send x N --> history_researcher & disambiguator
    orchestrator -- Send --> planner
    orchestrator -- "guarda: iter>=max o sin tareas" --> fallback
    orchestrator -- finish --> finalize
    history_researcher & disambiguator & planner --> reviewer
    reviewer -- "errores, iter<max" --> orchestrator
    reviewer -- ambiguo --> clarify
    reviewer -- listo --> finalize
    clarify -- resume --> orchestrator
    fallback --> finalize --> END
```
"""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from app.agent.graph.nodes.clarify import clarify
from app.agent.graph.nodes.disambiguator import disambiguator_node
from app.agent.graph.nodes.fallback import fallback_node
from app.agent.graph.nodes.finalize import finalize
from app.agent.graph.nodes.history_researcher import history_researcher_node
from app.agent.graph.nodes.intake import intake
from app.agent.graph.nodes.orchestrator import orchestrator
from app.agent.graph.nodes.planner import planner_node
from app.agent.graph.nodes.reviewer import reviewer
from app.agent.graph.nodes.shortcut import shortcut
from app.agent.graph.policies import network_retry_policy
from app.agent.graph.routing import make_route_after_reviewer, route_after_orchestrator, route_after_shortcut
from app.agent.graph.state import AgentState
from app.agent.runtime import AgentRuntime

_SUBAGENT_DESTINATIONS = ("history_researcher", "disambiguator", "planner", "fallback", "finalize")


def build_graph(runtime: AgentRuntime):
    retry = network_retry_policy(runtime.settings)
    graph = StateGraph(AgentState, context_schema=AgentRuntime)

    graph.add_node("intake", intake)
    graph.add_node("shortcut", shortcut)
    graph.add_node("orchestrator", orchestrator, retry_policy=retry, destinations=_SUBAGENT_DESTINATIONS)
    graph.add_node("history_researcher", history_researcher_node, retry_policy=retry)
    graph.add_node("disambiguator", disambiguator_node, retry_policy=retry)
    graph.add_node("planner", planner_node, retry_policy=retry)
    graph.add_node("reviewer", reviewer, retry_policy=retry)
    graph.add_node("clarify", clarify)
    graph.add_node("fallback", fallback_node)
    graph.add_node("finalize", finalize)

    graph.add_edge(START, "intake")
    graph.add_edge("intake", "shortcut")
    graph.add_conditional_edges(
        "shortcut", route_after_shortcut, {"finalize": "finalize", "orchestrator": "orchestrator"}
    )
    graph.add_conditional_edges("orchestrator", route_after_orchestrator)

    # Fan-in: los tres subagentes desembocan en el mismo revisor.
    graph.add_edge("history_researcher", "reviewer")
    graph.add_edge("disambiguator", "reviewer")
    graph.add_edge("planner", "reviewer")

    graph.add_conditional_edges(
        "reviewer",
        make_route_after_reviewer(runtime.settings),
        {"finalize": "finalize", "clarify": "clarify", "fallback": "fallback", "orchestrator": "orchestrator"},
    )
    graph.add_edge("clarify", "orchestrator")
    graph.add_edge("fallback", "finalize")
    graph.add_edge("finalize", END)

    return graph.compile(checkpointer=runtime.checkpointer)
