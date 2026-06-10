import os
import requests
from dotenv import load_dotenv
from logger_config import logger

load_dotenv()

API_BASE_URL = os.getenv("GNS_API_BASE_URL", "https://app.gns.com.mx/gns-sandbox")
API_USER = os.getenv("GNS_API_USER", "gns-sandbox")
API_PASSWORD = os.getenv("GNS_API_PASSWORD", "")

TIMEOUT_SECONDS = 20


def _request(method, endpoint, payload=None, params=None):
    """
    Función central para consumir la API GNS Sandbox con Basic Auth.
    """
    url = f"{API_BASE_URL.rstrip('/')}/{endpoint.lstrip('/')}"

    try:
        response = requests.request(
            method=method,
            url=url,
            auth=(API_USER, API_PASSWORD),
            json=payload,
            params=params,
            timeout=TIMEOUT_SECONDS,
        )

        status_code = response.status_code

        try:
            data = response.json()
        except Exception:
            data = {"raw_response": response.text}

        logger.info(f"API_CALL | {method} {endpoint} | HTTP={status_code}")
        return data, status_code

    except Exception as error:
        logger.exception(f"API_ERROR | {method} {endpoint} | error={error}")
        return {
            "error": str(error),
            "endpoint": endpoint,
            "method": method,
        }, 500


def _as_single_item(data, key_name, key_value):
    """
    Algunas rutas regresan una lista con un solo elemento.
    Esta función devuelve el elemento correcto como diccionario.
    """
    if isinstance(data, dict):
        return data

    if isinstance(data, list):
        for item in data:
            if not isinstance(item, dict):
                continue

            try:
                if int(item.get(key_name)) == int(key_value):
                    return item
            except (TypeError, ValueError):
                continue

        if len(data) == 1 and isinstance(data[0], dict):
            return data[0]

    return None


def get_tickets():
    """
    Endpoint oficial:
    GET /tickets/
    Obtiene todos los tickets.
    """
    return _request("GET", "tickets/")


def get_tickets_by_customer(id_customer):
    """
    Endpoint oficial:
    GET /tickets/{idCustomer}
    Obtiene tickets asociados a un cliente.
    """
    data, status = _request("GET", f"tickets/{id_customer}")

    if status == 204:
        return [], status

    return data, status


def get_categories():
    """
    Obtiene categorías disponibles.
    """
    return _request("GET", "categories")


def get_comments():
    """
    Obtiene comentarios, si el endpoint está disponible.
    """
    return _request("GET", "comments")


def get_customers():
    """
    Obtiene todos los clientes.
    """
    return _request("GET", "customers")


def get_customer_by_id(id_customer):
    """
    Valida cliente por idCustomer.
    Primero intenta endpoint directo.
    Si no funciona, busca dentro de GET /customers.
    """
    data, status = _request("GET", f"customers/{id_customer}")

    if status in [200, 201] and data:
        customer = _as_single_item(data, "idCustomer", id_customer)
        if customer:
            return customer, status

    customers, customers_status = get_customers()

    if customers_status not in [200, 201] or not isinstance(customers, list):
        return {
            "error": "Cliente no encontrado",
            "idCustomer": id_customer,
        }, 404

    for customer in customers:
        if not isinstance(customer, dict):
            continue

        try:
            if int(customer.get("idCustomer")) == int(id_customer):
                return customer, 200
        except (TypeError, ValueError):
            continue

    return {
        "error": "Cliente no encontrado",
        "idCustomer": id_customer,
    }, 404


def get_customer_balance(id_customer):
    """
    Intenta obtener saldo del cliente.
    Si la API no tiene endpoint dedicado, usa payment_status del cliente.
    """
    possible_endpoints = [
        f"balance/{id_customer}",
        f"saldo/{id_customer}",
        f"customers/{id_customer}/balance",
        f"customers/{id_customer}/saldo",
    ]

    for endpoint in possible_endpoints:
        data, status = _request("GET", endpoint)

        if status in [200, 201] and data:
            if isinstance(data, dict) and not data.get("idCustomer"):
                return data, status

    customer, customer_status = get_customer_by_id(id_customer)

    if customer_status in [200, 201] and isinstance(customer, dict):
        return {
            "idCustomer": id_customer,
            "payment_status": customer.get("payment_status"),
            "balance_source": "customer.payment_status",
            "note": "La API no expuso saldo exacto; se usa payment_status como referencia.",
        }, 200

    return {
        "error": "No se pudo obtener saldo del cliente",
        "idCustomer": id_customer,
    }, 404


def get_customer_services(id_customer):
    """
    Intenta obtener servicios/paquetes del cliente.
    Si no existe endpoint real, usa información derivada de tickets.
    """
    possible_endpoints = [
        f"customer-packages/{id_customer}",
        f"services/{id_customer}",
        f"customers/{id_customer}/services",
        f"customers/{id_customer}/packages",
    ]

    for endpoint in possible_endpoints:
        data, status = _request("GET", endpoint)

        if status in [200, 201] and data:
            if isinstance(data, list):
                first = data[0] if data else {}
                if isinstance(first, dict) and (
                    "idCustomerPackage" in first
                    or "idPackage" in first
                    or "package" in first
                ):
                    return data, status

            if isinstance(data, dict) and (
                "idCustomerPackage" in data
                or "idPackage" in data
                or "package" in data
            ):
                return data, status

    tickets, tickets_status = get_tickets_by_customer(id_customer)

    if tickets_status in [200, 201] and isinstance(tickets, list):
        services = []

        for ticket in tickets:
            if not isinstance(ticket, dict):
                continue

            service = {
                "idCustomerPackage": ticket.get("idCustomerPackage"),
                "idPackage": ticket.get("idPackage"),
                "package": ticket.get("package"),
                "source": "tickets",
            }

            if service["idCustomerPackage"]:
                services.append(service)

        return services, 200

    return [], 200


def get_first_active_customer_package(id_customer):
    """
    Obtiene un idCustomerPackage usable para crear tickets.
    Prioridad:
    1. Servicios del cliente.
    2. Tickets históricos del cliente.
    """
    services, services_status = get_customer_services(id_customer)

    if services_status in [200, 201]:
        if isinstance(services, dict):
            services = [services]

        if isinstance(services, list):
            for service in services:
                if not isinstance(service, dict):
                    continue

                package_id = (
                    service.get("idCustomerPackage")
                    or service.get("id_customer_package")
                    or service.get("customer_package_id")
                )

                if package_id:
                    return package_id

    tickets, tickets_status = get_tickets_by_customer(id_customer)

    if tickets_status in [200, 201] and isinstance(tickets, list):
        for ticket in tickets:
            if not isinstance(ticket, dict):
                continue

            package_id = ticket.get("idCustomerPackage")

            if package_id:
                return package_id

    return None


def post_escalation(payload):
    """
    Registra comentario/escalamiento en ticket existente.
    Endpoint usado previamente con éxito:
    POST /comments
    """
    possible_endpoints = [
        "comments",
        "ticket-comments",
        "tickets/comments",
    ]

    last_response = None
    last_status = None

    for endpoint in possible_endpoints:
        data, status = _request("POST", endpoint, payload=payload)
        last_response = data
        last_status = status

        if status in [200, 201]:
            return data, status

    return last_response, last_status or 400


def post_ticket_comment(id_ticket, comment):
    """
    Registra comentario en un ticket existente.
    """
    payload = {
        "idTicket": id_ticket,
        "comment": comment,
    }

    return post_escalation(payload)


def create_ticket(payload):
    """
    Endpoint oficial:
    POST /tickets

    Campos requeridos según documentación:
    - idCategory
    - idCustomerPackage
    - problem

    Opcionales:
    - visit_date
    - contact_name
    - phone_number
    """
    return _request("POST", "tickets", payload=payload)


def create_ticket_for_customer(
    id_customer,
    id_category,
    problem,
    contact_name=None,
    phone_number=None,
    visit_date=None,
):
    """
    Crea ticket nuevo para cliente validado.
    Busca idCustomerPackage automáticamente.
    """
    id_customer_package = get_first_active_customer_package(id_customer)

    if not id_customer_package:
        return {
            "error": "No se encontró idCustomerPackage para crear ticket",
            "idCustomer": id_customer,
        }, 400

    payload = {
        "idCategory": id_category,
        "idCustomerPackage": id_customer_package,
        "problem": problem,
    }

    if contact_name:
        payload["contact_name"] = contact_name

    if phone_number:
        payload["phone_number"] = phone_number

    if visit_date:
        payload["visit_date"] = visit_date

    return create_ticket(payload)


def select_category_id(categories, preferred_names, fallback_id=1):
    """
    Busca idCategory por nombre de categoría.
    """
    if not isinstance(categories, list):
        return fallback_id

    preferred_names = [name.lower() for name in preferred_names]

    for category in categories:
        if not isinstance(category, dict):
            continue

        category_name = str(category.get("category", "")).lower()

        for preferred in preferred_names:
            if preferred in category_name:
                return category.get("idCategory") or fallback_id

    return fallback_id
