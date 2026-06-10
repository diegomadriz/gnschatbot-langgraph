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
        "falta de senal",
        "sin exito",
        "sin exito",
        "cobertura critica",
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
        "modem",
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
    category = ticket.get("category", "Sin categoria")
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
                "Si el problema continua, generar una nueva solicitud de soporte."
            ]
        }

    if decision == "DIAGNOSTICO_REMOTO":
        return {
            "ticket": ticket_number,
            "status": status,
            "category": category,
            "decision": decision,
            "message": "Detecte un posible problema de velocidad, lentitud o intermitencia. Iniciaremos diagnostico remoto.",
            "recommended_steps": [
                "Verificar que el modem o router este encendido.",
                "Reiniciar el equipo durante 30 segundos.",
                "Esperar a que las luces del modem estabilicen.",
                "Ejecutar una prueba de ping real desde la VM del agente.",
                "Si el problema persiste, escalar a soporte tecnico."
            ]
        }

    if decision == "ESCALAR_TECNICO":
        return {
            "ticket": ticket_number,
            "status": status,
            "category": category,
            "decision": decision,
            "message": "El problema parece requerir atencion tecnica. Se recomienda escalar el caso a un ingeniero de soporte.",
            "recommended_steps": [
                "No repetir reinicios si ya se intentaron sin exito.",
                "Registrar evidencia del problema.",
                "Enviar el caso a soporte tecnico humano."
            ]
        }

    return {
        "ticket": ticket_number,
        "status": status,
        "category": category,
        "decision": decision,
        "message": "Tu caso sera canalizado a soporte para revision.",
        "recommended_steps": [
            "Validar datos del servicio.",
            "Canalizar el caso a un agente humano de soporte.",
            "Dar seguimiento segun el tipo de solicitud."
        ]
    }
def build_escalation_payload(ticket, diagnosis):
    """
    Estructura JSON limpia para registrar la escalacion como comentario tecnico.
    No incluye datos personales.
    """
    return {
        "idTicket": ticket.get("idTicket"),
        "comment": (
            "Escalacion automatica generada por agente IA. "
            f"Ticket: {ticket.get('ticket_number')}. "
            f"Categoria: {ticket.get('category')}. "
            f"Decision: {diagnosis.get('decision')}. "
            f"Motivo: {diagnosis.get('message')} "
            "Se recomienda asignar este caso a un ingeniero de soporte tecnico humano."
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
    Busca automaticamente una IP tecnica asociada al ticket.
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
    Clasifica un problema cuando el cliente no tiene numero de ticket.
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
        "sin senal",
        "falta de senal",
        "fibra",
        "cable cortado",
        "poste",
        "corte",
        "ya reinicie",
        "ya reinicie",
        "reinicie y sigue",
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
        "contrasena",
        "password",
        "pagar",
        "pago",
        "cobranza",
        "factura",
        "cancelar",
        "cancelacion",
        "domicilio",
        "cambio de domicilio"
    ]

    if any(word in description for word in escalation_keywords):
        return {
            "decision": "ESCALAR_TECNICO",
            "category": "Falla critica reportada por cliente",
            "message": (
                "Por lo que describes, tu servicio podria requerir revision tecnica. "
                "Evitare pedirte que repitas pasos basicos si ya hay senales de falta de senal o falla fisica."
            )
        }

    if any(word in description for word in remote_keywords):
        return {
            "decision": "DIAGNOSTICO_REMOTO",
            "category": "Posible lentitud o intermitencia",
            "message": (
                "Parece que tu servicio esta lento o intermitente. "
                "Vamos a intentar una revision basica antes de enviarlo con un tecnico."
            )
        }

    if any(word in description for word in support_keywords):
        return {
            "decision": "REVISION_SOPORTE",
            "category": "Solicitud administrativa o de soporte",
            "message": (
                "Esto parece una solicitud de atencion o cambio administrativo. "
                "Lo mejor es canalizarlo con soporte para que revisen tu cuenta."
            )
        }

    return {
        "decision": "REVISION_SOPORTE",
        "category": "Caso no clasificado automaticamente",
        "message": (
            "No tengo suficiente informacion para clasificar el problema con seguridad. "
            "Te canalizare a soporte para que revisen tu caso."
        )
    }


def build_ticketless_escalation_payload(description, classification):
    """
    Crea un comentario general para evidenciar la intencion de escalamiento cuando no hay folio.
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
