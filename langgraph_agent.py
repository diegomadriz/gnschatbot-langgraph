from typing import Any, Dict, TypedDict

from ai_client import generate_customer_response
from logger_config import logger
from network_tools import run_edge_diagnostics, validate_target


class NetworkAgentState(TypedDict, total=False):
    message: str
    customer: Dict[str, Any]
    target: str
    intent: str
    needs_edge_diagnostics: bool
    diagnostics: Dict[str, Any]
    response: str
    technical_detail: Dict[str, Any]


NETWORK_PROBLEM_KEYWORDS = [
    "lento",
    "lenta",
    "lentitud",
    "intermitente",
    "intermitencia",
    "se va y viene",
    "velocidad",
    "lag",
    "no carga",
    "sin internet",
    "no tengo internet",
    "sin servicio",
    "desconexion",
    "desconexión",
    "se desconecta",
    "corte",
    "ping",
]


def classify_network_intent(state: NetworkAgentState) -> NetworkAgentState:
    text = str(state.get("message", "")).lower()
    needs_edge_diagnostics = any(keyword in text for keyword in NETWORK_PROBLEM_KEYWORDS)
    intent = "network_diagnosis" if needs_edge_diagnostics else "general_support"

    logger.info(
        f"LANGGRAPH_NODE | node=classify_network_intent | intent={intent} | "
        f"needs_edge_diagnostics={needs_edge_diagnostics}"
    )

    return {
        **state,
        "intent": intent,
        "needs_edge_diagnostics": needs_edge_diagnostics,
    }


def run_mikrotik_tool_node(state: NetworkAgentState) -> NetworkAgentState:
    target = validate_target(state.get("target"))
    diagnostics = run_edge_diagnostics(target)

    logger.info(
        f"LANGGRAPH_NODE | node=run_mikrotik_tool | target={target} | "
        f"success={diagnostics.get('success')}"
    )

    return {
        **state,
        "target": target,
        "diagnostics": diagnostics,
    }


def build_customer_response_node(state: NetworkAgentState) -> NetworkAgentState:
    diagnostics = state.get("diagnostics") or {}
    ping = diagnostics.get("ping") or {}
    parsed_ping = ping.get("parsed") or {}
    traceroute = diagnostics.get("traceroute") or {}
    parsed_trace = traceroute.get("parsed") or {}
    target = diagnostics.get("target") or state.get("target") or "8.8.8.8"

    if not ping.get("success"):
        base_message = (
            "Intenté verificar tu conexión directamente desde el router perimetral, "
            "pero no pude completar la prueba automática en este momento. "
            "Voy a dejar registrada la revisión para soporte técnico."
        )
    else:
        loss = parsed_ping.get("packet_loss_percent")
        avg = parsed_ping.get("avg_rtt_ms")
        hop_count = parsed_trace.get("hop_count")

        loss_text = f"{loss}% de pérdida" if loss is not None else "pérdida no determinada"
        avg_text = f"{avg} ms de latencia promedio" if avg is not None else "latencia promedio no determinada"
        hops_text = f"{hop_count} salto(s) WAN observados" if hop_count else "traza WAN registrada"

        if loss == 0:
            health = "El enlace WAN se observa estable desde el borde."
        elif loss is not None and loss > 0:
            health = "La prueba muestra pérdida de paquetes y requiere revisión técnica."
        else:
            health = "La prueba se completó, pero la salida requiere revisión técnica."

        base_message = (
            "He verificado tu conexión directamente desde nuestro router perimetral.\n\n"
            f"Destino probado: {target}\n"
            f"Resultado: {loss_text}, {avg_text}.\n"
            f"Ruta: {hops_text}.\n\n"
            f"{health}"
        )

    response = generate_customer_response(
        base_message,
        {
            "mode": "edge_network_diagnosis",
            "decision": "DIAGNOSTICO_BORDE",
            "classification": state.get("intent"),
        },
    )

    return {
        **state,
        "response": response,
        "technical_detail": {
            "mode": "edge_network_diagnosis",
            "target": target,
            "diagnostics": diagnostics,
        },
    }


def _route_after_classification(state: NetworkAgentState) -> str:
    if state.get("needs_edge_diagnostics"):
        return "run_mikrotik_tool"
    return "build_customer_response"


def _build_graph():
    try:
        from langgraph.graph import END, StateGraph
    except Exception as error:
        logger.warning(f"LANGGRAPH_INIT | status=fallback | error={error}")
        return None

    graph = StateGraph(NetworkAgentState)
    graph.add_node("classify_network_intent", classify_network_intent)
    graph.add_node("run_mikrotik_tool", run_mikrotik_tool_node)
    graph.add_node("build_customer_response", build_customer_response_node)

    graph.set_entry_point("classify_network_intent")
    graph.add_conditional_edges(
        "classify_network_intent",
        _route_after_classification,
        {
            "run_mikrotik_tool": "run_mikrotik_tool",
            "build_customer_response": "build_customer_response",
        },
    )
    graph.add_edge("run_mikrotik_tool", "build_customer_response")
    graph.add_edge("build_customer_response", END)

    logger.info("LANGGRAPH_INIT | status=success")
    return graph.compile()


_GRAPH = _build_graph()


def run_network_agent(message, customer=None, target=None):
    initial_state: NetworkAgentState = {
        "message": message,
        "customer": customer or {},
        "target": validate_target(target),
    }

    if _GRAPH:
        result = _GRAPH.invoke(initial_state)
    else:
        result = classify_network_intent(initial_state)
        if result.get("needs_edge_diagnostics"):
            result = run_mikrotik_tool_node(result)
        result = build_customer_response_node(result)

    return result.get("response"), result.get("technical_detail")
