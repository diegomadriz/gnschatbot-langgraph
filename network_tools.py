import ipaddress
import os
import re
import time

from dotenv import load_dotenv

from logger_config import logger

load_dotenv()


DEFAULT_TARGET = os.getenv("NETWORK_DIAG_TARGET", "8.8.8.8")
SSH_TIMEOUT_SECONDS = int(os.getenv("SSH_TIMEOUT_SECONDS", "15"))
ROUTER_COMMAND_TIMEOUT_SECONDS = int(os.getenv("ROUTER_COMMAND_TIMEOUT_SECONDS", "10"))
ENABLE_TRACEROUTE = os.getenv("ENABLE_TRACEROUTE", "true").lower() in [
    "1",
    "true",
    "yes",
    "on",
]
ENABLE_UBIQUITI_CHECK = os.getenv("ENABLE_UBIQUITI_CHECK", "true").lower() in [
    "1",
    "true",
    "yes",
    "on",
]
UBIQUITI_HTTPS_TIMEOUT_SECONDS = int(os.getenv("UBIQUITI_HTTPS_TIMEOUT_SECONDS", "8"))
UBIQUITI_VERIFY_TLS = os.getenv("UBIQUITI_VERIFY_TLS", "false").lower() in [
    "1",
    "true",
    "yes",
    "on",
]

def _load_paramiko():
    try:
        import paramiko

        return paramiko, None
    except Exception as error:
        return None, str(error)


def _load_requests():
    try:
        import requests

        return requests, None
    except Exception as error:
        return None, str(error)


def validate_target(target):
    """
    Restringe el destino a IPs o nombres DNS simples.
    No permite comandos arbitrarios ni separadores de shell/router.
    """
    target = str(target or DEFAULT_TARGET).strip()

    try:
        ipaddress.ip_address(target)
        return target
    except ValueError:
        pass

    if re.fullmatch(r"[A-Za-z0-9.-]{1,253}", target) and "." in target:
        return target

    return DEFAULT_TARGET


def get_mikrotik_config():
    return {
        "host": os.getenv("MIKROTIK_HOST", ""),
        "username": os.getenv("MIKROTIK_USER", ""),
        "password": os.getenv("MIKROTIK_PASSWORD", ""),
        "port": int(os.getenv("MIKROTIK_PORT", "22")),
    }


def get_ubiquiti_config():
    return {
        "host": os.getenv("UBIQUITI_HOST", ""),
        "username": os.getenv("UBIQUITI_USER", ""),
        "password": os.getenv("UBIQUITI_PASSWORD", ""),
        "port": int(os.getenv("UBIQUITI_PORT", "443")),
    }


def _config_is_complete(config):
    return bool(config["host"] and config["username"] and config["password"])


def _base_https_url(config):
    host = str(config["host"]).strip().removeprefix("https://").removeprefix("http://")
    if config.get("port") and int(config["port"]) != 443:
        return f"https://{host}:{config['port']}"
    return f"https://{host}"


def run_mikrotik_command(command, command_label, command_timeout=None):
    """
    Ejecuta un comando permitido en RouterOS via SSH.
    Las credenciales se leen desde .env y nunca se registran.
    """
    config = get_mikrotik_config()
    started_at = time.time()

    if not _config_is_complete(config):
        logger.warning(
            f"NETWORK_TOOL | device=mikrotik | command={command_label} | status=missing_env"
        )
        return {
            "success": False,
            "status": "missing_env",
            "command": command_label,
            "output": "",
            "error": "Faltan variables MIKROTIK_HOST, MIKROTIK_USER o MIKROTIK_PASSWORD en .env.",
        }

    paramiko, import_error = _load_paramiko()

    if import_error:
        logger.warning(
            f"NETWORK_TOOL | device=mikrotik | command={command_label} | status=missing_paramiko"
        )
        return {
            "success": False,
            "status": "missing_paramiko",
            "command": command_label,
            "output": "",
            "error": "La dependencia paramiko no está instalada.",
        }

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    try:
        client.connect(
            hostname=config["host"],
            port=config["port"],
            username=config["username"],
            password=config["password"],
            timeout=SSH_TIMEOUT_SECONDS,
            banner_timeout=SSH_TIMEOUT_SECONDS,
            auth_timeout=SSH_TIMEOUT_SECONDS,
            look_for_keys=False,
            allow_agent=False,
        )

        _, stdout, stderr = client.exec_command(command, timeout=SSH_TIMEOUT_SECONDS)
        channel = stdout.channel
        channel.settimeout(1.0)
        command_timeout = int(command_timeout or ROUTER_COMMAND_TIMEOUT_SECONDS)
        output_chunks = []
        error_chunks = []
        deadline = time.time() + command_timeout

        while True:
            if channel.recv_ready():
                output_chunks.append(channel.recv(65535).decode("utf-8", errors="replace"))

            if channel.recv_stderr_ready():
                error_chunks.append(channel.recv_stderr(65535).decode("utf-8", errors="replace"))

            if channel.exit_status_ready():
                while channel.recv_ready():
                    output_chunks.append(channel.recv(65535).decode("utf-8", errors="replace"))
                while channel.recv_stderr_ready():
                    error_chunks.append(channel.recv_stderr(65535).decode("utf-8", errors="replace"))
                break

            if time.time() >= deadline:
                duration_ms = int((time.time() - started_at) * 1000)
                logger.warning(
                    f"NETWORK_TOOL | device=mikrotik | host={config['host']} | "
                    f"command={command_label} | status=command_timeout | duration_ms={duration_ms}"
                )

                try:
                    channel.close()
                except Exception:
                    pass

                return {
                    "success": False,
                    "status": "command_timeout",
                    "command": command_label,
                    "output": "".join(output_chunks),
                    "error": f"El comando excedió {command_timeout} segundos.",
                    "duration_ms": duration_ms,
                }

            time.sleep(0.2)

        output = "".join(output_chunks)
        error = "".join(error_chunks)
        duration_ms = int((time.time() - started_at) * 1000)
        success = not error.strip()

        logger.info(
            f"NETWORK_TOOL | device=mikrotik | host={config['host']} | "
            f"command={command_label} | success={success} | duration_ms={duration_ms}"
        )

        return {
            "success": success,
            "status": "ok" if success else "router_error",
            "command": command_label,
            "output": output,
            "error": error,
            "duration_ms": duration_ms,
        }

    except Exception as error:
        duration_ms = int((time.time() - started_at) * 1000)
        logger.exception(
            f"NETWORK_TOOL | device=mikrotik | host={config['host']} | "
            f"command={command_label} | status=exception | duration_ms={duration_ms}"
        )
        return {
            "success": False,
            "status": "exception",
            "command": command_label,
            "output": "",
            "error": str(error),
            "duration_ms": duration_ms,
        }

    finally:
        try:
            client.close()
        except Exception:
            pass


def mikrotik_ping(target=None, count=5):
    target = validate_target(target)
    command = f"/ping {target} count={int(count)}"
    result = run_mikrotik_command(command, f"ping:{target}", command_timeout=ROUTER_COMMAND_TIMEOUT_SECONDS)
    result["target"] = target
    result["parsed"] = parse_mikrotik_ping(result.get("output", ""))
    return result


def mikrotik_traceroute(target=None):
    target = validate_target(target)
    if not ENABLE_TRACEROUTE:
        logger.info(
            f"NETWORK_TOOL | device=mikrotik | command=traceroute:{target} | status=disabled"
        )
        return {
            "success": True,
            "status": "disabled",
            "command": f"traceroute:{target}",
            "target": target,
            "output": "",
            "error": "",
            "parsed": {"hop_count": 0, "hops": []},
        }

    command = f"/tool traceroute {target}"
    result = run_mikrotik_command(command, f"traceroute:{target}", command_timeout=ROUTER_COMMAND_TIMEOUT_SECONDS)
    result["target"] = target
    result["parsed"] = parse_mikrotik_traceroute(result.get("output", ""))
    return result


def ubiquiti_https_status():
    if not ENABLE_UBIQUITI_CHECK:
        logger.info("NETWORK_TOOL | device=ubiquiti | command=https_status | status=disabled")
        return {
            "success": True,
            "status": "disabled",
            "device": "ubiquiti",
            "checks": [],
            "error": "",
        }

    config = get_ubiquiti_config()
    started_at = time.time()

    if not _config_is_complete(config):
        logger.warning("NETWORK_TOOL | device=ubiquiti | command=https_status | status=missing_env")
        return {
            "success": False,
            "status": "missing_env",
            "device": "ubiquiti",
            "checks": [],
            "error": "Faltan variables UBIQUITI_HOST, UBIQUITI_USER o UBIQUITI_PASSWORD en .env.",
        }

    requests, import_error = _load_requests()
    if import_error:
        logger.warning("NETWORK_TOOL | device=ubiquiti | command=https_status | status=missing_requests")
        return {
            "success": False,
            "status": "missing_requests",
            "device": "ubiquiti",
            "checks": [],
            "error": "La dependencia requests no está instalada.",
        }

    if not UBIQUITI_VERIFY_TLS:
        try:
            requests.packages.urllib3.disable_warnings(
                requests.packages.urllib3.exceptions.InsecureRequestWarning
            )
        except Exception:
            pass

    base_url = _base_https_url(config)
    endpoints = ["/status.cgi", "/api/status", "/status", "/"]
    checks = []

    for endpoint in endpoints:
        url = f"{base_url}{endpoint}"
        check_started_at = time.time()

        try:
            response = requests.get(
                url,
                auth=(config["username"], config["password"]),
                timeout=UBIQUITI_HTTPS_TIMEOUT_SECONDS,
                verify=UBIQUITI_VERIFY_TLS,
            )
            elapsed_ms = int((time.time() - check_started_at) * 1000)
            content_type = response.headers.get("content-type", "")
            text_sample = response.text[:400] if response.text else ""
            is_json = "json" in content_type.lower()

            parsed = None
            if is_json:
                try:
                    parsed = response.json()
                except Exception:
                    parsed = None

            checks.append(
                {
                    "endpoint": endpoint,
                    "http_status": response.status_code,
                    "elapsed_ms": elapsed_ms,
                    "content_type": content_type,
                    "json": parsed if isinstance(parsed, dict) else None,
                    "sample": text_sample if not is_json else "",
                }
            )

            if response.status_code in [200, 401, 403]:
                duration_ms = int((time.time() - started_at) * 1000)
                success = response.status_code == 200
                status = "ok" if success else "auth_or_forbidden"

                logger.info(
                    f"NETWORK_TOOL | device=ubiquiti | host={config['host']} | "
                    f"command=https_status:{endpoint} | http={response.status_code} | "
                    f"status={status} | duration_ms={duration_ms}"
                )

                return {
                    "success": success,
                    "status": status,
                    "device": "ubiquiti",
                    "host": config["host"],
                    "selected_endpoint": endpoint,
                    "checks": checks,
                    "duration_ms": duration_ms,
                    "error": "" if success else "El equipo respondió por HTTPS, pero no autorizó la consulta de estado.",
                }

        except Exception as error:
            checks.append(
                {
                    "endpoint": endpoint,
                    "http_status": None,
                    "elapsed_ms": int((time.time() - check_started_at) * 1000),
                    "error": str(error),
                }
            )

    duration_ms = int((time.time() - started_at) * 1000)
    logger.warning(
        f"NETWORK_TOOL | device=ubiquiti | host={config['host']} | "
        f"command=https_status | status=failed | duration_ms={duration_ms}"
    )
    return {
        "success": False,
        "status": "failed",
        "device": "ubiquiti",
        "host": config["host"],
        "checks": checks,
        "duration_ms": duration_ms,
        "error": "No se pudo obtener respuesta HTTPS válida de la antena Ubiquiti.",
    }


def parse_mikrotik_ping(output):
    text = str(output or "")
    parsed = {
        "packet_loss_percent": None,
        "sent": None,
        "received": None,
        "avg_rtt_ms": None,
        "min_rtt_ms": None,
        "max_rtt_ms": None,
    }

    loss_match = re.search(r"packet-loss=([0-9.]+)%", text)
    if loss_match:
        parsed["packet_loss_percent"] = float(loss_match.group(1))

    sent_match = re.search(r"sent=([0-9]+)", text)
    received_match = re.search(r"received=([0-9]+)", text)
    if sent_match:
        parsed["sent"] = int(sent_match.group(1))
    if received_match:
        parsed["received"] = int(received_match.group(1))

    rtt_match = re.search(
        r"min-rtt=([0-9.]+)ms\s+avg-rtt=([0-9.]+)ms\s+max-rtt=([0-9.]+)ms",
        text,
    )
    if rtt_match:
        parsed["min_rtt_ms"] = float(rtt_match.group(1))
        parsed["avg_rtt_ms"] = float(rtt_match.group(2))
        parsed["max_rtt_ms"] = float(rtt_match.group(3))

    if parsed["packet_loss_percent"] is None and "received" in text and parsed["sent"]:
        if parsed["received"] is not None:
            parsed["packet_loss_percent"] = round(
                100 - (parsed["received"] / parsed["sent"] * 100),
                2,
            )

    return parsed


def parse_mikrotik_traceroute(output):
    text = str(output or "")
    hops = []
    unique_hops = {}

    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.lower().startswith(("address", "columns")):
            continue

        hop_match = re.match(r"^(\d+)\s+([0-9a-fA-F:.]+|\*)", stripped)
        if hop_match:
            hop_number = int(hop_match.group(1))
            hops.append(
                {
                    "hop": hop_number,
                    "address": hop_match.group(2),
                    "raw": stripped,
                }
            )
            unique_hops.setdefault(
                hop_number,
                {
                    "hop": hop_number,
                    "address": hop_match.group(2),
                    "raw": stripped,
                },
            )

    return {
        "hop_count": len(hops),
        "unique_hop_count": len(unique_hops),
        "hops": hops[:12],
        "unique_hops": [unique_hops[key] for key in sorted(unique_hops.keys())[:12]],
    }


def run_edge_diagnostics(target=None):
    target = validate_target(target)
    ping = mikrotik_ping(target, count=5)
    traceroute = mikrotik_traceroute(target)
    ubiquiti = ubiquiti_https_status()
    traceroute_status = traceroute.get("status")
    traceroute_partial = traceroute_status == "command_timeout" and bool(
        (traceroute.get("parsed") or {}).get("hop_count")
    )
    status = "ok"

    if ping.get("success") and traceroute_partial:
        status = "partial_success"
    elif ping.get("success") and traceroute_status == "disabled":
        status = "ping_only"
    elif not (ping.get("success") and traceroute.get("success")):
        status = "failed"

    return {
        "target": target,
        "ping": ping,
        "traceroute": traceroute,
        "ubiquiti": ubiquiti,
        "success": ping.get("success") and (traceroute.get("success") or traceroute_partial),
        "status": status,
        "traceroute_partial": traceroute_partial,
    }
