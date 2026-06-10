import re
import requests
from logger_config import logger

OLLAMA_URL = "http://127.0.0.1:11434/api/generate"
OLLAMA_MODEL = "llama3.2:1b"


SENSITIVE_KEYS = {
    "idCustomer",
    "idCustomerPackage",
    "idTicket",
    "ticket_number",
    "customer_name",
    "customer_lastname",
    "customer_email",
    "email",
    "employee_email",
    "phone",
    "phone_number",
    "employee_phone_number",
    "address",
    "domicilio",
    "saldo",
    "balance",
    "amount",
    "total",
    "package",
}


def sanitize_text_for_ai(text):
    """
    Elimina o enmascara datos sensibles antes de enviar texto a Ollama.
    Aunque Ollama corre local, se trata como capa no confiable.
    """
    text = str(text)

    # Correos
    text = re.sub(
        r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}",
        "[EMAIL_REMOVIDO]",
        text,
    )

    # Teléfonos largos
    text = re.sub(
        r"\b\d{10,}\b",
        "[TELEFONO_REMOVIDO]",
        text,
    )

    # Tickets tipo TCK
    text = re.sub(
        r"\bTCK\d+\b",
        "[TICKET]",
        text,
        flags=re.IGNORECASE,
    )

    # IDs explícitos
    text = re.sub(
        r"\b(idCustomer|idCustomerPackage|idTicket)\s*[:=]\s*\d+\b",
        r"\1=[ID_REMOVIDO]",
        text,
        flags=re.IGNORECASE,
    )

    # Montos
    text = re.sub(
        r"\$\s?\d+(?:[.,]\d+)?",
        "[MONTO_REMOVIDO]",
        text,
    )

    return text


def sanitize_context_for_ai(context):
    """
    Reduce el contexto a información no sensible.
    No manda nombres, teléfonos, correos, saldos, paquetes ni IDs internos.
    """
    context = context or {}

    allowed_keys = {
        "mode",
        "category",
        "decision",
        "problem_type",
        "has_ticket",
        "ticket_status",
        "classification",
    }

    safe_context = {}

    for key, value in context.items():
        if key in SENSITIVE_KEYS:
            continue

        if key in allowed_keys:
            safe_context[key] = sanitize_text_for_ai(value)

    return safe_context


def looks_bad_ai_response(text):
    """
    Si Ollama genera algo inseguro, ambiguo o inventado, usamos el mensaje base.
    """
    if not text:
        return True

    lowered = text.lower()

    bad_phrases = [
        "no puedo ayudar",
        "no puedo ayudarte",
        "lo siento, pero no puedo",
        "no estoy seguro",
        "no puedo acceder",
        "por correo electrónico",
        "he revisado el estado",
        "he revisado",
        "las luces están estables",
        "confirma si se ha registrado",
        "revisa la nota",
        "contactes al equipo técnico",
    ]

    return any(phrase in lowered for phrase in bad_phrases)


def generate_customer_response(base_message, context=None):
    """
    Usa Ollama solo como capa de redacción.
    La decisión técnica ya fue tomada por reglas/API/ping/POST.

    Importante:
    - No se envían datos sensibles.
    - Si la respuesta generada no es segura, se regresa el mensaje base.
    """
    safe_base_message = sanitize_text_for_ai(base_message)
    safe_context = sanitize_context_for_ai(context)

    prompt = f"""
Eres un asistente virtual de soporte de internet para clientes de GNS.

Tu tarea es REESCRIBIR el mensaje técnico en una respuesta para cliente.

Reglas obligatorias:
- Responde solo en español.
- Sé amable, claro y breve.
- Estilo WhatsApp.
- No inventes datos.
- No cambies la decisión técnica.
- No elimines confirmaciones importantes.
- No afirmes que revisaste el módem, las luces, la red o el servicio si esa información no viene en el mensaje técnico.
- Usa frases como "por favor revisa" o "te sugiero revisar", no "he revisado".
- No menciones datos personales.
- No menciones saldos.
- No menciones teléfonos, correos, direcciones ni nombres completos.
- No menciones IDs internos.
- No pidas enviar correo.
- No menciones que eres un modelo de IA.
- Máximo 80 palabras.

Mensaje técnico original sanitizado:
{safe_base_message}

Contexto técnico sanitizado:
{safe_context}

Respuesta final para cliente:
"""

    try:
        response = requests.post(
            OLLAMA_URL,
            json={
                "model": OLLAMA_MODEL,
                "prompt": prompt,
                "stream": False,
                "options": {
                    "temperature": 0.2,
                    "num_predict": 120,
                },
            },
            timeout=30,
        )

        response.raise_for_status()
        data = response.json()
        ai_message = data.get("response", "").strip()

        if looks_bad_ai_response(ai_message):
            logger.warning("AI_RESPONSE | provider=ollama | status=rejected_bad_response")
            return base_message

        logger.info("AI_RESPONSE | provider=ollama | model=llama3.2:1b | status=success_sanitized")
        return ai_message

    except Exception as error:
        logger.warning(f"AI_RESPONSE | provider=ollama | status=fallback | error={error}")
        return base_message
