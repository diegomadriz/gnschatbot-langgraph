import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, TypedDict

from ai_client import generate_customer_response
from agent import classify_free_text_problem
from gns_api import (
    create_ticket_for_customer,
    get_categories,
    get_customer_balance,
    get_customer_by_id,
    get_customer_services,
    get_tickets_by_customer,
    select_category_id,
)
from logger_config import logger
from network_tools import run_edge_diagnostics, validate_target


DATA_DIR = Path("data")
SESSION_PATH = DATA_DIR / "session_customer.json"
LOCAL_MODIFICATIONS_PATH = DATA_DIR / "local_modifications.jsonl"
AGENT_LOG_PATH = Path("logs") / "agent.log"


CRITICAL_KEYWORDS = [
    "fibra",
    "cable cortado",
    "cable roto",
    "luz roja",
    "sin internet",
    "no tengo internet",
    "sin servicio",
    "no tengo servicio",
    "sin señal",
    "falta de señal",
    "poste",
    "corte total",
]

REMOTE_KEYWORDS = [
    "lento",
    "lenta",
    "lentitud",
    "intermitente",
    "intermitencia",
    "se va y viene",
    "velocidad",
    "lag",
    "no carga",
]

ADMIN_KEYWORDS = [
    "pago",
    "saldo",
    "factura",
    "cambiar plan",
    "cambio de plan",
    "cancelar",
    "cancelación",
    "contraseña",
    "password",
    "domicilio",
    "administrativo",
]


class SupportState(TypedDict, total=False):
    message: str
    text: str
    id_customer: int
    customer: Dict[str, Any]
    customer_status: int
    authenticated: bool
    intent: str
    problem_type: str
    classification: Dict[str, Any]
    context: Dict[str, Any]
    edge_diagnostics: Dict[str, Any]
    ticket_creation: Dict[str, Any]
    local_modification: Dict[str, Any]
    response: str
    technical_detail: Dict[str, Any]


def extract_customer_id(message):
    text = str(message).lower()
    match = re.search(r"(?:cliente|idcustomer|id cliente|cliente id)\s*#?\s*(\d+)", text)
    if match:
        return int(match.group(1))
    return None


def read_session_customer():
    if not SESSION_PATH.exists():
        return None

    try:
        return json.loads(SESSION_PATH.read_text(encoding="utf-8"))
    except Exception:
        logger.exception("SUPPORT_GRAPH_SESSION | action=read | status=error")
        return None


def save_session_customer(customer):
    DATA_DIR.mkdir(exist_ok=True)
    safe_customer = {
        "idCustomer": customer.get("idCustomer"),
        "active": customer.get("active"),
        "payment_status": customer.get("payment_status"),
        "city": customer.get("city"),
        "state": customer.get("state"),
    }

    SESSION_PATH.write_text(json.dumps(safe_customer, ensure_ascii=False, indent=2), encoding="utf-8")
    return safe_customer


def clear_session_customer():
    if SESSION_PATH.exists():
        SESSION_PATH.unlink()


def payment_status_label(value):
    if str(value) == "1":
        return "al corriente o habilitado"
    if str(value) == "0":
        return "pendiente o no confirmado"
    return "no disponible"


def active_tickets(tickets):
    if not isinstance(tickets, list):
        return []

    return [ticket for ticket in tickets if str(ticket.get("status", "")).lower() == "abierto"]


def summarize_tickets(tickets, limit=5):
    if not tickets:
        return "No encontré tickets activos."

    lines = []
    for ticket in tickets[:limit]:
        lines.append(
            f"- {ticket.get('ticket_number')} | {ticket.get('category')} | {ticket.get('status')}"
        )

    if len(tickets) > limit:
        lines.append(f"- Y {len(tickets) - limit} ticket(s) más.")

    return "\n".join(lines)


def summarize_service(services):
    if isinstance(services, dict):
        services = [services]

    if not isinstance(services, list) or not services:
        return "No encontré servicio activo."

    service = services[0]
    package = service.get("package") or "paquete no disponible"
    status = service.get("status") or "estado no disponible"
    return f"{package} | {status}"


def save_local_modification(modification_type, description, customer=None, ticket=None, extra=None):
    DATA_DIR.mkdir(exist_ok=True)
    record = {
        "created_at": datetime.utcnow().isoformat() + "Z",
        "modification_type": modification_type,
        "description": description,
        "source": "gns-whatsapp-chatbot",
        "customer": {"idCustomer": customer.get("idCustomer") if customer else None},
        "ticket": ticket or {},
        "extra": extra or {},
    }

    with LOCAL_MODIFICATIONS_PATH.open("a", encoding="utf-8") as file:
        file.write(json.dumps(record, ensure_ascii=False) + "\n")

    logger.info(
        f"LOCAL_MODIFICATION | type={modification_type} | "
        f"idCustomer={record['customer']['idCustomer']}"
    )
    return record


def read_tail(path, lines=20):
    if not path.exists():
        return []

    try:
        content = path.read_text(encoding="utf-8", errors="replace").splitlines()
        return content[-lines:]
    except Exception:
        logger.exception(f"SUPPORT_GRAPH_HISTORY | path={path.name} | status=error")
        return []


def create_support_ticket(id_customer, problem_type, problem_text):
    categories, categories_status = get_categories()

    if problem_type == "critical":
        id_category = select_category_id(
            categories,
            ["problemas de corte", "corte", "intermitencia", "soporte general"],
            fallback_id=6,
        )
    elif problem_type == "administrative":
        id_category = select_category_id(
            categories,
            ["soporte general", "cobranza", "cambio de plan", "cancelación"],
            fallback_id=1,
        )
    elif problem_type == "remote":
        id_category = select_category_id(
            categories,
            ["problemas de velocidad", "intermitencia", "soporte general"],
            fallback_id=7,
        )
    else:
        id_category = select_category_id(categories, ["soporte general"], fallback_id=1)

    ticket_response, ticket_status = create_ticket_for_customer(
        id_customer=id_customer,
        id_category=id_category,
        problem=problem_text,
    )

    logger.info(
        f"CREATE_TICKET | idCustomer={id_customer} | type={problem_type} | "
        f"idCategory={id_category} | HTTP={ticket_status}"
    )

    return {
        "http_status": ticket_status,
        "idCategory": id_category,
        "api_response": ticket_response,
        "categories_status": categories_status,
    }


def parse_message_node(state: SupportState) -> SupportState:
    message = str(state.get("message", "")).strip()
    text = message.lower()

    return {
        **state,
        "message": message,
        "text": text,
        "id_customer": extract_customer_id(message),
    }


def load_session_node(state: SupportState) -> SupportState:
    customer = read_session_customer()

    return {
        **state,
        "customer": customer or {},
        "authenticated": bool(customer),
    }


def validate_customer_node(state: SupportState) -> SupportState:
    id_customer = state.get("id_customer")
    if not id_customer:
        return state

    customer, customer_status = get_customer_by_id(id_customer)
    if customer_status in [200, 201] and isinstance(customer, dict):
        customer = save_session_customer(customer)
        authenticated = True
    else:
        authenticated = False

    logger.info(
        f"SUPPORT_GRAPH_NODE | node=validate_customer | "
        f"idCustomer={id_customer} | status={customer_status}"
    )

    return {
        **state,
        "customer": customer if isinstance(customer, dict) else {},
        "customer_status": customer_status,
        "authenticated": authenticated,
    }


def fetch_context_node(state: SupportState) -> SupportState:
    customer = state.get("customer") or {}
    id_customer = customer.get("idCustomer")

    if not id_customer or not state.get("authenticated"):
        return {**state, "context": {}}

    balance, balance_status = get_customer_balance(id_customer)
    services, services_status = get_customer_services(id_customer)
    tickets, tickets_status = get_tickets_by_customer(id_customer)
    open_tickets = active_tickets(tickets)

    context = {
        "safe_customer": customer,
        "balance_status": balance_status,
        "balance": balance,
        "services_status": services_status,
        "services": services,
        "tickets_status": tickets_status,
        "tickets": tickets,
        "active_tickets": open_tickets,
        "local_modifications_tail": read_tail(LOCAL_MODIFICATIONS_PATH, lines=8),
        "agent_log_tail": read_tail(AGENT_LOG_PATH, lines=12),
    }

    logger.info(
        f"SUPPORT_GRAPH_NODE | node=fetch_context | "
        f"idCustomer={id_customer} | openTickets={len(open_tickets)}"
    )

    return {**state, "context": context}


def classify_intent_node(state: SupportState) -> SupportState:
    text = state.get("text", "")
    classification = classify_free_text_problem(state.get("message", ""))

    if state.get("id_customer"):
        intent = "customer_validation"
        problem_type = "validation"
    elif not state.get("authenticated"):
        intent = "requires_customer_validation"
        problem_type = "validation"
    elif "volver" in text or "menú" in text or "menu" in text:
        intent = "main_menu_reset"
        problem_type = "navigation"
    elif "tickets" in text or "ticket" in text:
        intent = "show_active_tickets"
        problem_type = "query"
    elif "saldo" in text or "pago" in text:
        intent = "show_balance"
        problem_type = "query"
    elif "sí funcionó" in text or "si funciono" in text or "ya funcionó" in text or "ya funciona" in text:
        intent = "resolved_after_guidance"
        problem_type = "resolution"
    elif "no funcionó" in text or "no funciono" in text or "sigue igual" in text or "no sirve" in text:
        intent = "failed_guidance"
        problem_type = "critical"
    elif any(keyword in text for keyword in CRITICAL_KEYWORDS):
        intent = "edge_diagnosis"
        problem_type = "critical"
    elif any(keyword in text for keyword in REMOTE_KEYWORDS):
        intent = "edge_diagnosis"
        problem_type = "remote"
    elif any(keyword in text for keyword in ADMIN_KEYWORDS):
        intent = "administrative_ticket"
        problem_type = "administrative"
    else:
        intent = "authenticated_unclear"
        problem_type = "general"

    logger.info(
        f"SUPPORT_GRAPH_NODE | node=classify_intent | "
        f"intent={intent} | problem_type={problem_type}"
    )

    return {
        **state,
        "intent": intent,
        "problem_type": problem_type,
        "classification": classification,
    }


def reset_session_node(state: SupportState) -> SupportState:
    clear_session_customer()
    return state


def local_resolution_node(state: SupportState) -> SupportState:
    record = save_local_modification(
        "resolved_after_guidance",
        state.get("message", ""),
        customer=state.get("customer"),
        extra={"resolution": "Cliente indica que las indicaciones básicas funcionaron."},
    )
    return {**state, "local_modification": record}


def edge_diagnosis_node(state: SupportState) -> SupportState:
    target = validate_target(os.getenv("NETWORK_DIAG_TARGET"))
    diagnostics = run_edge_diagnostics(target)

    logger.info(
        f"SUPPORT_GRAPH_NODE | node=edge_diagnosis | "
        f"target={target} | success={diagnostics.get('success')}"
    )

    return {**state, "edge_diagnostics": diagnostics}


def create_ticket_node(state: SupportState) -> SupportState:
    customer = state.get("customer") or {}
    id_customer = customer.get("idCustomer")
    problem_type = state.get("problem_type", "general")

    if not id_customer:
        return state

    if state.get("intent") == "failed_guidance":
        problem = "Cliente indica que el diagnóstico básico no funcionó. Requiere revisión técnica."
    elif state.get("intent") == "administrative_ticket":
        problem = f"Solicitud administrativa del cliente: {state.get('message')}"
    elif state.get("intent") == "edge_diagnosis":
        problem = (
            f"Reporte de conectividad del cliente: {state.get('message')}. "
            "El agente ejecutó diagnóstico de borde y dejó evidencia en logs."
        )
    else:
        problem = f"Solicitud del cliente: {state.get('message')}"

    created = create_support_ticket(id_customer, problem_type, problem)
    return {**state, "ticket_creation": created}


def response_node(state: SupportState) -> SupportState:
    intent = state.get("intent")
    context = state.get("context") or {}
    customer = state.get("customer") or {}
    diagnostics = state.get("edge_diagnostics") or {}
    ticket_creation = state.get("ticket_creation") or {}

    if intent == "customer_validation":
        if not state.get("authenticated"):
            response = "No encontré ese cliente. Por favor verifica el ID e intenta de nuevo."
        else:
            response = (
                "Cliente validado.\n\n"
                f"Estado de pago: {payment_status_label(customer.get('payment_status'))}.\n"
                f"Servicio: {summarize_service(context.get('services'))}.\n\n"
                f"Tickets activos:\n{summarize_tickets(context.get('active_tickets'))}"
            )
    elif not state.get("authenticated"):
        response = "Antes de continuar necesito validar tu cliente.\n\nEscribe tu ID así:\ncliente 170"
    elif intent == "main_menu_reset":
        response = "Volví al menú principal.\n\nPara iniciar de nuevo, escribe tu ID de cliente."
    elif intent == "show_active_tickets":
        response = f"Tus tickets activos son:\n{summarize_tickets(context.get('active_tickets'))}"
    elif intent == "show_balance":
        balance = context.get("balance")
        payment_value = balance.get("payment_status") if isinstance(balance, dict) else None
        response = (
            f"Tu estado de pago aparece como: {payment_status_label(payment_value)}.\n\n"
            "La API no expone un monto exacto de saldo en este ambiente, así que usamos payment_status como referencia."
        )
    elif intent == "resolved_after_guidance":
        response = (
            "Perfecto. Registré que el problema quedó solucionado después de las indicaciones básicas.\n\n"
            "No modifiqué el dataset original; dejé evidencia local para seguimiento."
        )
    elif intent == "failed_guidance":
        response = (
            "Entiendo. Como no funcionó la revisión básica, creé un ticket para soporte técnico.\n\n"
            "Un integrante del equipo deberá revisar el caso."
        )
    elif intent == "administrative_ticket":
        response = "Listo. Creé un ticket para que soporte revise tu solicitud administrativa."
    elif intent == "edge_diagnosis":
        ping = diagnostics.get("ping") or {}
        parsed_ping = ping.get("parsed") or {}
        target = diagnostics.get("target") or os.getenv("NETWORK_DIAG_TARGET", "8.8.8.8")
        loss = parsed_ping.get("packet_loss_percent")
        avg = parsed_ping.get("avg_rtt_ms")

        if ping.get("success"):
            loss_text = f"{loss}% de pérdida" if loss is not None else "pérdida no determinada"
            avg_text = f"{avg} ms de latencia promedio" if avg is not None else "latencia promedio no determinada"
            response = (
                "He verificado tu conexión directamente desde nuestro router perimetral.\n\n"
                f"Destino probado: {target}\n"
                f"Resultado: {loss_text}, {avg_text}.\n\n"
                "Si tu servicio sigue fallando, escribe: no funcionó. Si ya quedó, escribe: sí funcionó."
            )
        else:
            response = (
                "Intenté verificar tu conexión desde el router perimetral, pero la prueba automática no pudo completarse.\n\n"
                "Dejé evidencia técnica en el registro del agente. Si el problema continúa, escribe: no funcionó."
            )
    else:
        response = (
            "Puedo ayudarte con soporte, pero necesito un poco más de contexto.\n\n"
            "Describe si es falla de internet, luz roja, cable cortado, lentitud, pago o cambio de plan."
        )
        response = generate_customer_response(
            response,
            {
                "mode": "authenticated_unclear",
                "decision": (state.get("classification") or {}).get("decision"),
                "history_available": bool(context.get("agent_log_tail") or context.get("local_modifications_tail")),
            },
        )

    technical_detail = {
        "mode": intent or "requires_customer_validation",
        "problem_type": state.get("problem_type"),
        "classification": state.get("classification"),
        "safe_customer": customer,
        "context_summary": {
            "active_tickets": len(context.get("active_tickets") or []),
            "local_history_loaded": bool(context.get("local_modifications_tail")),
            "agent_logs_loaded": bool(context.get("agent_log_tail")),
        },
        "edge_diagnostics": diagnostics,
        "ticket_creation": ticket_creation,
        "local_modification": state.get("local_modification"),
        "next_options": ["sí funcionó", "no funcionó", "volver al menú"],
    }

    return {**state, "response": response, "technical_detail": technical_detail}


def audit_node(state: SupportState) -> SupportState:
    customer = state.get("customer") or {}
    logger.info(
        f"SUPPORT_GRAPH_RESULT | intent={state.get('intent')} | "
        f"idCustomer={customer.get('idCustomer')} | "
        f"edgeSuccess={(state.get('edge_diagnostics') or {}).get('success')} | "
        f"ticketStatus={(state.get('ticket_creation') or {}).get('http_status')}"
    )
    return state


def route_after_parse(state: SupportState) -> str:
    if state.get("id_customer"):
        return "validate_customer"
    return "load_session"


def route_after_classify(state: SupportState) -> str:
    if not state.get("authenticated"):
        return "response"

    intent = state.get("intent")
    if intent == "main_menu_reset":
        return "reset_session"
    if intent == "resolved_after_guidance":
        return "local_resolution"
    if intent in ["failed_guidance", "administrative_ticket"]:
        return "create_ticket"
    if intent == "edge_diagnosis":
        return "edge_diagnosis"
    return "response"


def route_after_edge(state: SupportState) -> str:
    auto_create = os.getenv("AUTO_CREATE_TICKET_AFTER_EDGE_FAIL", "false").lower() in [
        "1",
        "true",
        "yes",
        "on",
    ]
    diagnostics = state.get("edge_diagnostics") or {}
    ping = diagnostics.get("ping") or {}
    parsed_ping = ping.get("parsed") or {}
    loss = parsed_ping.get("packet_loss_percent")

    if auto_create and (not ping.get("success") or (loss is not None and loss > 0)):
        return "create_ticket"
    return "response"


def _build_graph():
    try:
        from langgraph.graph import END, StateGraph
    except Exception as error:
        logger.warning(f"SUPPORT_GRAPH_INIT | status=fallback | error={error}")
        return None

    graph = StateGraph(SupportState)
    graph.add_node("parse_message", parse_message_node)
    graph.add_node("load_session", load_session_node)
    graph.add_node("validate_customer", validate_customer_node)
    graph.add_node("fetch_context", fetch_context_node)
    graph.add_node("classify_intent", classify_intent_node)
    graph.add_node("reset_session", reset_session_node)
    graph.add_node("local_resolution", local_resolution_node)
    graph.add_node("edge_diagnosis", edge_diagnosis_node)
    graph.add_node("create_ticket", create_ticket_node)
    graph.add_node("response", response_node)
    graph.add_node("audit", audit_node)

    graph.set_entry_point("parse_message")
    graph.add_conditional_edges(
        "parse_message",
        route_after_parse,
        {"validate_customer": "validate_customer", "load_session": "load_session"},
    )
    graph.add_edge("validate_customer", "fetch_context")
    graph.add_edge("load_session", "fetch_context")
    graph.add_edge("fetch_context", "classify_intent")
    graph.add_conditional_edges(
        "classify_intent",
        route_after_classify,
        {
            "reset_session": "reset_session",
            "local_resolution": "local_resolution",
            "edge_diagnosis": "edge_diagnosis",
            "create_ticket": "create_ticket",
            "response": "response",
        },
    )
    graph.add_edge("reset_session", "response")
    graph.add_edge("local_resolution", "response")
    graph.add_conditional_edges(
        "edge_diagnosis",
        route_after_edge,
        {"create_ticket": "create_ticket", "response": "response"},
    )
    graph.add_edge("create_ticket", "response")
    graph.add_edge("response", "audit")
    graph.add_edge("audit", END)

    logger.info("SUPPORT_GRAPH_INIT | status=success")
    return graph.compile()


_GRAPH = _build_graph()


def run_support_agent(message):
    initial_state: SupportState = {"message": message}

    if _GRAPH:
        result = _GRAPH.invoke(initial_state)
    else:
        result = parse_message_node(initial_state)
        result = validate_customer_node(result) if result.get("id_customer") else load_session_node(result)
        result = fetch_context_node(result)
        result = classify_intent_node(result)
        route = route_after_classify(result)
        if route == "reset_session":
            result = reset_session_node(result)
        elif route == "local_resolution":
            result = local_resolution_node(result)
        elif route == "edge_diagnosis":
            result = edge_diagnosis_node(result)
            if route_after_edge(result) == "create_ticket":
                result = create_ticket_node(result)
        elif route == "create_ticket":
            result = create_ticket_node(result)
        result = response_node(result)
        result = audit_node(result)

    return result.get("response"), result.get("technical_detail")
