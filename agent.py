from logger_config import logger


def sanitize_ticket(ticket):
    """
    Elimina datos personales antes de mostrarlos en el chatbot.
    """
    hidden_fields = [
        "customer_name",
        "customer_lastname",
        "employee_name",
        "employee_lastname",
        "employee_email",
        "employee_phone_number",
    ]

    safe_ticket = dict(ticket)

    for field in hidden_fields:
        safe_ticket.pop(field, None)

    return safe_ticket


def classify_issue(category, description):
    category = str(category).lower()
    description = str(description).lower()

    escalation_keywords = [
        "corte",
        "sin servicio",
        "no tener servicio",
        "luz roja",
        "fibra",
        "falta de señal",
        "sin éxito",
        "sin exito",
        "cobertura crítica",
        "cobertura critica",
    ]

    remote_keywords = [
        "velocidad",
        "intermitencia",
        "lenta",
        "lento",
        "lentitud",
        "ping",
        "reinicio",
        "router",
        "módem",
        "modem",
    ]

    if any(word in description for word in escalation_keywords):
        return "ESCALAR_TECNICO"

    if "corte" in category or "fibra" in category or "cobertura" in category:
        return "ESCALAR_TECNICO"

    if "velocidad" in category or "intermitencia" in category:
        return "DIAGNOSTICO_REMOTO"

    if any(word in description for word in remote_keywords):
        return "DIAGNOSTICO_REMOTO"

    return "REVISION_SOPORTE"


def find_ticket_by_number(tickets, ticket_number):
    for ticket in tickets:
        if str(ticket.get("ticket_number", "")).upper() == str(ticket_number).upper():
            return ticket
    return None


def generate_diagnosis(ticket):
    category = ticket.get("category", "Sin categoría")
    description = ticket.get("description", "")
    status = ticket.get("status", "Sin estado")
    ticket_number = ticket.get("ticket_number", "Sin folio")

    decision = classify_issue(category, description)

    logger.info(
        f"DIAGNOSIS | ticket={ticket_number} | category={category} | status={status} | decision={decision}"
    )

    if str(status).lower() == "cerrado":
        return {
            "ticket": ticket_number,
            "status": status,
            "category": category,
            "decision": "INFORMAR_RESOLUCION",
            "message": "Tu ticket aparece como cerrado. El caso ya fue atendido previamente.",
            "recommended_steps": [
                "Validar si el servicio se encuentra funcionando actualmente.",
                "Si el problema continúa, generar una nueva solicitud de soporte."
            ]
        }

    if decision == "DIAGNOSTICO_REMOTO":
        return {
            "ticket": ticket_number,
            "status": status,
            "category": category,
            "decision": decision,
            "message": "Detecté un posible problema de velocidad, lentitud o intermitencia. Iniciaremos diagnóstico remoto.",
            "recommended_steps": [
                "Verificar que el módem o router esté encendido.",
                "Reiniciar el equipo durante 30 segundos.",
                "Esperar a que las luces del módem estabilicen.",
                "Ejecutar una prueba de ping real desde la VM del agente.",
                "Si el problema persiste, escalar a soporte técnico."
            ]
        }

    if decision == "ESCALAR_TECNICO":
        return {
            "ticket": ticket_number,
            "status": status,
            "category": category,
            "decision": decision,
            "message": "El problema parece requerir atención técnica. Se recomienda escalar el caso a un ingeniero de soporte.",
            "recommended_steps": [
                "No repetir reinicios si ya se intentaron sin éxito.",
                "Registrar evidencia del problema.",
                "Enviar el caso a soporte técnico humano."
            ]
        }

    return {
        "ticket": ticket_number,
        "status": status,
        "category": category,
        "decision": decision,
        "message": "Tu caso será canalizado a soporte para revisión.",
        "recommended_steps": [
            "Validar datos del servicio.",
            "Canalizar el caso a un agente humano de soporte.",
            "Dar seguimiento según el tipo de solicitud."
        ]
    }
def build_escalation_payload(ticket, diagnosis):
    """
    Estructura JSON limpia para registrar la escalación como comentario técnico.
    No incluye datos personales.
    """
    return {
        "idTicket": ticket.get("idTicket"),
        "comment": (
            "Escalación automática generada por agente IA. "
            f"Ticket: {ticket.get('ticket_number')}. "
            f"Categoría: {ticket.get('category')}. "
            f"Decisión: {diagnosis.get('decision')}. "
            f"Motivo: {diagnosis.get('message')} "
            "Se recomienda asignar este caso a un ingeniero de soporte técnico humano."
        )
    }

import subprocess
import ipaddress


def is_valid_ip(value):
    """
    Valida si un valor tiene formato de IP.
    """
    try:
        ipaddress.ip_address(str(value))
        return True
    except ValueError:
        return False


def get_target_ip_from_ticket(ticket):
    """
    Busca automáticamente una IP técnica asociada al ticket.
    Si la API no proporciona IP del cliente o del equipo, regresa None.
    """
    possible_fields = [
        "ip",
        "ip_address",
        "customer_ip",
        "router_ip",
        "onu_ip",
        "device_ip",
        "public_ip",
        "management_ip",
        "ipAddress",
        "customerIp",
        "routerIp",
        "onuIp",
        "deviceIp",
        "publicIp",
        "managementIp"
    ]

    for field in possible_fields:
        value = ticket.get(field)
        if value and is_valid_ip(value):
            return str(value)

    return None


def run_ping_test(host="8.8.8.8", count=4):
    """
    Ejecuta una prueba de ping real desde la VM hacia el host indicado.
    El host puede ser una IP del cliente si la API la proporciona.
    """
    try:
        result = subprocess.run(
            ["ping", "-c", str(count), host],
            capture_output=True,
            text=True,
            timeout=15
        )

        success = result.returncode == 0

        return {
            "host": host,
            "success": success,
            "return_code": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr
        }

    except Exception as error:
        return {
            "host": host,
            "success": False,
            "error": str(error)
        }
def classify_free_text_problem(description):
    """
    Clasifica un problema cuando el cliente no tiene número de ticket.
    Usa lenguaje escrito libremente por el cliente.
    """
    description = str(description).lower()

    escalation_keywords = [
        "sin internet",
        "no tengo internet",
        "sin servicio",
        "no tengo servicio",
        "luz roja",
        "rojo",
        "no prende",
        "no funciona",
        "sin señal",
        "falta de señal",
        "fibra",
        "cable cortado",
        "poste",
        "corte",
        "ya reinicié",
        "ya reinicie",
        "reinicié y sigue",
        "reinicie y sigue"
    ]

    remote_keywords = [
        "lento",
        "lenta",
        "lentitud",
        "velocidad",
        "intermitente",
        "intermitencia",
        "se va y viene",
        "se corta",
        "tarda",
        "ping alto",
        "lag",
        "no carga",
        "wifi lento"
    ]

    support_keywords = [
        "cambiar plan",
        "cambio de plan",
        "contraseña",
        "password",
        "pagar",
        "pago",
        "cobranza",
        "factura",
        "cancelar",
        "cancelación",
        "domicilio",
        "cambio de domicilio"
    ]

    if any(word in description for word in escalation_keywords):
        return {
            "decision": "ESCALAR_TECNICO",
            "category": "Falla crítica reportada por cliente",
            "message": (
                "Por lo que describes, tu servicio podría requerir revisión técnica. "
                "Evitaré pedirte que repitas pasos básicos si ya hay señales de falta de señal o falla física."
            )
        }

    if any(word in description for word in remote_keywords):
        return {
            "decision": "DIAGNOSTICO_REMOTO",
            "category": "Posible lentitud o intermitencia",
            "message": (
                "Parece que tu servicio está lento o intermitente. "
                "Vamos a intentar una revisión básica antes de enviarlo con un técnico."
            )
        }

    if any(word in description for word in support_keywords):
        return {
            "decision": "REVISION_SOPORTE",
            "category": "Solicitud administrativa o de soporte",
            "message": (
                "Esto parece una solicitud de atención o cambio administrativo. "
                "Lo mejor es canalizarlo con soporte para que revisen tu cuenta."
            )
        }

    return {
        "decision": "REVISION_SOPORTE",
        "category": "Caso no clasificado automáticamente",
        "message": (
            "No tengo suficiente información para clasificar el problema con seguridad. "
            "Te canalizaré a soporte para que revisen tu caso."
        )
    }


def build_ticketless_escalation_payload(description, classification):
    """
    Crea un comentario general para evidenciar la intención de escalamiento cuando no hay folio.
    Nota: la API de comentarios requiere idTicket, por eso no se puede hacer POST real
    sin un ticket existente.
    """
    return {
        "description": description,
        "decision": classification.get("decision"),
        "category": classification.get("category"),
        "reason": classification.get("message"),
        "source": "gns-chatbot-agent"
    }
