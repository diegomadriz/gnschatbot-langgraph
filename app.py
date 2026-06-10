import os
import re
import json
import unicodedata
from datetime import datetime
from pathlib import Path

from flask import Flask, request, jsonify, render_template_string
from dotenv import load_dotenv

from gns_api import (
    get_customer_by_id,
    get_customer_balance,
    get_customer_services,
    get_tickets_by_customer,
    get_categories,
    create_ticket_for_customer,
    select_category_id,
)
from agent import run_ping_test, classify_free_text_problem
from ai_client import generate_customer_response
from langgraph_agent import run_network_agent
from logger_config import logger
from support_graph import run_support_agent


load_dotenv()
app = Flask(__name__)


def ascii_json(value):
    if isinstance(value, str):
        return (
            unicodedata.normalize("NFKD", value)
            .encode("ascii", "ignore")
            .decode("ascii")
        )

    if isinstance(value, list):
        return [ascii_json(item) for item in value]

    if isinstance(value, dict):
        return {key: ascii_json(item) for key, item in value.items()}

    return value


HTML = """
<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">
    <title>GNS WhatsApp Chatbot</title>
    <style>
        body {
            margin: 0;
            font-family: Arial, sans-serif;
            background: #0f172a;
            color: #111827;
        }
        .phone {
            max-width: 460px;
            margin: 30px auto;
            background: #e5ddd5;
            border-radius: 24px;
            overflow: hidden;
            box-shadow: 0 20px 50px rgba(0,0,0,0.45);
        }
        .header {
            background: #075e54;
            color: white;
            padding: 18px;
            display: flex;
            align-items: center;
            gap: 12px;
        }
        .avatar {
            width: 42px;
            height: 42px;
            background: #10b981;
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
            font-weight: bold;
        }
        .header-text h1 {
            font-size: 18px;
            margin: 0;
        }
        .header-text p {
            margin: 2px 0 0;
            font-size: 12px;
            color: #d1fae5;
        }
        .chat {
            padding: 16px;
            min-height: 540px;
            background: #e5ddd5;
        }
        .bubble {
            max-width: 88%;
            padding: 12px 14px;
            border-radius: 12px;
            margin: 10px 0;
            line-height: 1.45;
            font-size: 14px;
            white-space: pre-line;
        }
        .bot {
            background: #ffffff;
            border-top-left-radius: 2px;
            color: #111827;
        }
        .user {
            background: #dcf8c6;
            border-top-right-radius: 2px;
            margin-left: auto;
            color: #111827;
        }
        .quick-buttons {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 8px;
            margin: 14px 0;
        }
        .quick-buttons button {
            border: none;
            background: #ffffff;
            color: #075e54;
            padding: 10px;
            border-radius: 999px;
            font-weight: bold;
            cursor: pointer;
            box-shadow: 0 2px 4px rgba(0,0,0,0.12);
        }
        .quick-buttons button:hover {
            background: #f0fdf4;
        }
        .quick-buttons .menu-button {
            grid-column: 1 / -1;
            background: #075e54;
            color: white;
        }
        form {
            background: #f0f2f5;
            padding: 12px;
            display: flex;
            gap: 8px;
            align-items: center;
        }
        input {
            flex: 1;
            border: none;
            border-radius: 999px;
            padding: 13px 16px;
            font-size: 14px;
            outline: none;
        }
        .send {
            width: 46px;
            height: 46px;
            border-radius: 50%;
            border: none;
            background: #25d366;
            color: white;
            font-size: 18px;
            cursor: pointer;
        }
        details {
            margin-top: 14px;
            background: rgba(255,255,255,0.86);
            padding: 10px;
            border-radius: 10px;
            font-size: 12px;
        }
        pre {
            white-space: pre-wrap;
            overflow-x: auto;
            color: #111827;
        }
        .meta {
            font-size: 11px;
            color: #64748b;
            margin-top: 6px;
        }
    </style>
</head>
<body>
    <div class="phone">
        <div class="header">
            <div class="avatar">G</div>
            <div class="header-text">
                <h1>Soporte GNS</h1>
                <p>Agente virtual en linea</p>
            </div>
        </div>

        <div class="chat">
            {% if not show_menu %}
                <div class="bubble bot">
Hola  Soy el asistente virtual de GNS.

Para comenzar, necesito validar tu cliente.
Escribe tu ID asi:

cliente 170

Despues de validarte podre mostrar tu estado de pago, servicio, tickets activos y menu de soporte.
                </div>
            {% endif %}

            {% if user_message %}
                <div class="bubble user">{{ user_message }}</div>
            {% endif %}

            {% if bot_message %}
                <div class="bubble bot">
{{ bot_message }}
                    <div class="meta">Registrado en logs/agent.log</div>
                </div>
            {% endif %}

            {% if show_menu %}
                <div class="quick-buttons">
                    <button type="button" onclick="setQuick('ver tickets activos')">Tickets activos</button>
                    <button type="button" onclick="setQuick('consultar saldo')">Estado de pago</button>
                    <button type="button" onclick="setQuick('tengo luz roja en el modem y no tengo internet')">Luz roja</button>
                    <button type="button" onclick="setQuick('fibra o cable cortado')">Fibra/cable cortado</button>
                    <button type="button" onclick="setQuick('mi internet esta lento')">Internet lento</button>
                    <button type="button" onclick="setQuick('quiero cambiar mi plan')">Administrativo</button>
                    <button type="button" onclick="setQuick('no funciono')">No funciono</button>
                    <button type="button" onclick="setQuick('si funciono')">Si funciono</button>
                    <button type="button" class="menu-button" onclick="window.location.href='/'">Volver al menu principal</button>
                </div>
            {% else %}
                <div class="quick-buttons">
                    <button type="button" class="menu-button" onclick="setQuick('cliente ')">Validar cliente</button>
                </div>
            {% endif %}

            {% if result %}
                <details>
                    <summary>Ver detalle tecnico</summary>
                    <pre>{{ result }}</pre>
                </details>
            {% endif %}
        </div>

        <form method="POST" action="/whatsapp">
            <input id="message" name="message" placeholder="Escribe tu mensaje..." required>
            <button class="send" type="submit">></button>
        </form>
    </div>

    <script>
        function setQuick(text) {
            const input = document.getElementById("message");
            input.value = text;
            input.focus();
            input.setSelectionRange(input.value.length, input.value.length);
        }
    </script>
</body>
</html>
"""


CRITICAL_KEYWORDS = [
    "fibra",
    "cable cortado",
    "cable roto",
    "luz roja",
    "sin internet",
    "no tengo internet",
    "sin servicio",
    "no tengo servicio",
    "sin senal",
    "falta de senal",
    "poste",
    "corte total",
]

ADMIN_KEYWORDS = [
    "pago",
    "saldo",
    "factura",
    "cambiar plan",
    "cambio de plan",
    "cancelar",
    "cancelacion",
    "contrasena",
    "password",
    "domicilio",
    "administrativo",
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


def extract_customer_id(message):
    text = str(message).lower()
    match = re.search(r"(?:cliente|idcustomer|id cliente|cliente id)\s*#?\s*(\d+)", text)
    if match:
        return int(match.group(1))
    return None


def read_session_customer():
    path = Path("data/session_customer.json")
    if not path.exists():
        return None

    try:
        return json.loads(path.read_text())
    except Exception:
        return None


def save_session_customer(customer):
    Path("data").mkdir(exist_ok=True)

    safe_customer = {
        "idCustomer": customer.get("idCustomer"),
        "active": customer.get("active"),
        "payment_status": customer.get("payment_status"),
        "city": customer.get("city"),
        "state": customer.get("state"),
    }

    Path("data/session_customer.json").write_text(
        json.dumps(safe_customer, ensure_ascii=False, indent=2)
    )

    return safe_customer


def clear_session_customer():
    path = Path("data/session_customer.json")
    if path.exists():
        path.unlink()


def should_show_menu(result):
    if not isinstance(result, dict):
        return False

    return result.get("mode") not in [
        "requires_customer_validation",
        "main_menu_reset",
    ]


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
        return "No encontre tickets activos."

    lines = []

    for ticket in tickets[:limit]:
        lines.append(
            f"- {ticket.get('ticket_number')} | {ticket.get('category')} | {ticket.get('status')}"
        )

    if len(tickets) > limit:
        lines.append(f"- Y {len(tickets) - limit} ticket(s) mas.")

    return "\n".join(lines)


def summarize_service(services):
    if isinstance(services, dict):
        services = [services]

    if not isinstance(services, list) or not services:
        return "No encontre servicio activo."

    service = services[0]
    package = service.get("package") or "paquete no disponible"
    status = service.get("status") or "estado no disponible"

    return f"{package} | {status}"


def save_local_modification(modification_type, description, customer=None, ticket=None, extra=None):
    Path("data").mkdir(exist_ok=True)

    record = {
        "created_at": datetime.utcnow().isoformat() + "Z",
        "modification_type": modification_type,
        "description": description,
        "source": "gns-whatsapp-chatbot",
        "customer": {
            "idCustomer": customer.get("idCustomer") if customer else None,
        },
        "ticket": ticket or {},
        "extra": extra or {},
    }

    with open("data/local_modifications.jsonl", "a", encoding="utf-8") as file:
        file.write(json.dumps(record, ensure_ascii=False) + "\n")

    logger.info(
        f"LOCAL_MODIFICATION | type={modification_type} | "
        f"idCustomer={record['customer']['idCustomer']}"
    )

    return record


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
            ["soporte general", "cobranza", "cambio de plan", "cancelacion"],
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


def use_ai_for_noncritical(message, context):
    return generate_customer_response(message, context)


def langgraph_enabled():
    return os.getenv("USE_LANGGRAPH_AGENT", "true").lower() in ["1", "true", "yes", "on"]


def support_graph_enabled():
    return os.getenv("USE_SUPPORT_GRAPH", "true").lower() in ["1", "true", "yes", "on"]


def validate_customer_flow(id_customer):
    customer, customer_status = get_customer_by_id(id_customer)

    if customer_status not in [200, 201] or not isinstance(customer, dict):
        return (
            "No encontre ese cliente. Por favor verifica el ID e intenta de nuevo.",
            {
                "mode": "requires_customer_validation",
                "customer_status": customer_status,
                "customer_response": customer,
            },
        )

    save_session_customer(customer)

    balance, balance_status = get_customer_balance(id_customer)
    services, services_status = get_customer_services(id_customer)
    tickets, tickets_status = get_tickets_by_customer(id_customer)
    open_tickets = active_tickets(tickets)

    service_summary = summarize_service(services)
    tickets_summary = summarize_tickets(open_tickets)
    payment_label = payment_status_label(customer.get("payment_status"))

    bot_message = (
        f"Cliente validado \n\n"
        f"Estado de pago: {payment_label}.\n"
        f"Servicio: {service_summary}.\n\n"
        f"Tickets activos:\n{tickets_summary}"
    )

    result = {
        "mode": "customer_validated",
        "safe_customer": {
            "idCustomer": customer.get("idCustomer"),
            "active": customer.get("active"),
            "payment_status": customer.get("payment_status"),
            "city": customer.get("city"),
            "state": customer.get("state"),
        },
        "balance_status": balance_status,
        "balance": balance,
        "services_status": services_status,
        "services": services,
        "tickets_status": tickets_status,
        "active_tickets": open_tickets,
    }

    logger.info(f"CUSTOMER_VALIDATED | idCustomer={id_customer} | openTickets={len(open_tickets)}")

    return bot_message, result


def handle_authenticated_message(message, customer):
    text = str(message).lower()
    id_customer = customer.get("idCustomer")

    if "volver" in text or "menu" in text or "menu" in text:
        clear_session_customer()
        return (
            "Volvi al menu principal \n\nPara iniciar de nuevo, escribe tu ID de cliente.",
            {"mode": "main_menu_reset"},
        )

    if "tickets" in text or "ticket" in text:
        tickets, status = get_tickets_by_customer(id_customer)
        open_tickets = active_tickets(tickets)

        return (
            f"Tus tickets activos son:\n{summarize_tickets(open_tickets)}",
            {
                "mode": "show_active_tickets",
                "tickets_status": status,
                "active_tickets": open_tickets,
            },
        )

    if "saldo" in text or "pago" in text:
        balance, status = get_customer_balance(id_customer)
        payment_value = balance.get("payment_status") if isinstance(balance, dict) else None
        payment_label = payment_status_label(payment_value)

        return (
            f"Tu estado de pago aparece como: {payment_label}.\n\n"
            "La API no expone un monto exacto de saldo en este ambiente, asi que usamos payment_status como referencia.",
            {
                "mode": "show_balance",
                "balance_status": status,
                "balance": balance,
            },
        )

    if "si funciono" in text or "si funciono" in text or "ya funciono" in text or "ya funciona" in text:
        record = save_local_modification(
            "resolved_after_guidance",
            message,
            customer=customer,
            extra={"resolution": "Cliente indica que las indicaciones basicas funcionaron."},
        )

        return (
            "Perfecto  Registre que el problema quedo solucionado despues de las indicaciones basicas.\n\n"
            "No modifique el dataset original; deje evidencia local para seguimiento.",
            {
                "mode": "resolved_after_guidance",
                "local_modification": record,
            },
        )

    if "no funciono" in text or "no funciono" in text or "sigue igual" in text or "no sirve" in text:
        created = create_support_ticket(
            id_customer,
            "critical",
            "Cliente indica que el diagnostico basico no funciono. Requiere revision tecnica.",
        )

        return (
            "Entiendo. Como no funciono la revision basica, cree un ticket para soporte tecnico \n\n"
            "Un integrante del equipo debera revisar el caso.",
            {
                "mode": "created_ticket_after_failed_guidance",
                "ticket_creation": created,
            },
        )

    if langgraph_enabled() and any(keyword in text for keyword in CRITICAL_KEYWORDS + REMOTE_KEYWORDS):
        bot_message, detail = run_network_agent(message, customer=customer)

        return (
            bot_message,
            {
                "mode": "langgraph_edge_diagnosis",
                "agent_detail": detail,
                "next_options": ["si funciono", "no funciono", "volver al menu"],
            },
        )

    if any(keyword in text for keyword in CRITICAL_KEYWORDS):
        created = create_support_ticket(
            id_customer,
            "critical",
            f"Reporte critico del cliente: {message}",
        )

        return (
            "Por lo que describes, puede requerirse revision tecnica directa.\n\n"
            "Cree un ticket de soporte tecnico ",
            {
                "mode": "critical_created_ticket",
                "ticket_creation": created,
            },
        )

    if any(keyword in text for keyword in ADMIN_KEYWORDS):
        created = create_support_ticket(
            id_customer,
            "administrative",
            f"Solicitud administrativa del cliente: {message}",
        )

        return (
            "Listo  Cree un ticket para que soporte revise tu solicitud administrativa.",
            {
                "mode": "administrative_created_ticket",
                "ticket_creation": created,
            },
        )

    if any(keyword in text for keyword in REMOTE_KEYWORDS):
        ping_result = run_ping_test("8.8.8.8", 4)

        if ping_result.get("success"):
            bot_message = (
                "Parece un problema de lentitud o intermitencia.\n\n"
                "Probemos primero:\n"
                "1. Revisa que el modem este encendido.\n"
                "2. Reinicialo durante 30 segundos.\n"
                "3. Espera a que las luces se estabilicen.\n\n"
                "Tambien ejecute una prueba de conexion desde el agente y respondio correctamente.\n\n"
                "Si esto no funciono, escribe: no funciono.\n"
                "Si ya quedo, escribe: si funciono."
            )
        else:
            bot_message = (
                "Detecte un posible problema de conexion general desde el agente.\n\n"
                "Si tu servicio sigue fallando, escribe: no funciono."
            )

        logger.info(
            f"PING_TEST | idCustomer={id_customer} | host=8.8.8.8 | success={ping_result.get('success')}"
        )

        return (
            bot_message,
            {
                "mode": "remote_guidance",
                "ping_test": ping_result,
                "next_options": ["si funciono", "no funciono", "volver al menu"],
            },
        )

    classification = classify_free_text_problem(message)

    bot_message = (
        "Puedo ayudarte con soporte, pero necesito un poco mas de contexto.\n\n"
        "Describe si es falla de internet, luz roja, cable cortado, lentitud, pago o cambio de plan."
    )

    bot_message = use_ai_for_noncritical(
        bot_message,
        {
            "mode": "authenticated_unclear",
            "has_ticket": False,
            "decision": classification.get("decision"),
            "category": classification.get("category"),
        },
    )

    return (
        bot_message,
        {
            "mode": "authenticated_unclear",
            "classification": classification,
        },
    )


def run_legacy_chatbot_flow(message):
    id_customer = extract_customer_id(message)

    if id_customer:
        return validate_customer_flow(id_customer)

    customer = read_session_customer()

    if not customer:
        return (
            "Antes de continuar necesito validar tu cliente.\n\nEscribe tu ID asi:\ncliente 170",
            {"mode": "requires_customer_validation"},
        )

    return handle_authenticated_message(message, customer)


def run_chatbot_flow(message):
    if support_graph_enabled():
        try:
            return run_support_agent(message)
        except Exception as error:
            logger.exception(f"SUPPORT_GRAPH_ERROR | fallback=legacy | error={error}")

    return run_legacy_chatbot_flow(message)


@app.route("/", methods=["GET"])
def home():
    clear_session_customer()
    return render_template_string(
        HTML,
        user_message=None,
        bot_message=None,
        result=None,
        show_menu=False,
    )


@app.route("/whatsapp", methods=["POST"])
def whatsapp():
    message = request.form.get("message", "").strip()
    bot_message, result = run_chatbot_flow(message)

    show_menu = should_show_menu(result)

    return render_template_string(
        HTML,
        user_message=message,
        bot_message=bot_message,
        result=json.dumps(result, indent=4, ensure_ascii=False),
        show_menu=show_menu,
    )


@app.route("/api/whatsapp", methods=["POST"])
def api_whatsapp():
    data = request.get_json() or {}
    message = data.get("message", "").strip()
    bot_message, result = run_chatbot_flow(message)

    return jsonify(
        ascii_json({
            "message": message,
            "chatbot_message": bot_message,
            "show_menu": should_show_menu(result),
            "technical_detail": result,
        })
    )


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "service": "gns-whatsapp-chatbot"})


@app.route("/api/summary", methods=["GET"])
def api_summary():
    categories, categories_status = get_categories()

    return jsonify(
        ascii_json({
            "service": "gns-whatsapp-chatbot",
            "categories_status": categories_status,
            "categories_available": len(categories) if isinstance(categories, list) else None,
            "status": "summary_generated",
        })
    )


if __name__ == "__main__":
    port = int(os.getenv("APP_PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)
