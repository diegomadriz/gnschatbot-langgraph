# GNS Chatbot Agent

Agente de IA para la gestión y diagnóstico de incidentes residenciales y empresariales de GNS.

## Objetivo

Automatizar soporte técnico de primer nivel mediante un chatbot que consulta tickets desde la API GNS Sandbox, diagnostica incidentes y decide si el caso debe resolverse mediante diagnóstico remoto, revisión por soporte o escalamiento a técnico.

## Infraestructura

- VM desplegada en XenServer
- Sistema operativo: Ubuntu 26.04 LTS
- IP estática: 10.32.66.113
- Gateway: 10.32.66.1
- DNS: 10.32.65.43 y 10.32.65.53
- Puerto de servicio: 5000

## Funciones principales

- Consulta de tickets activos e históricos desde la API GNS Sandbox.
- Diagnóstico autónomo basado en categoría y descripción del ticket.
- Orquestación opcional con LangGraph para el flujo completo de soporte.
- Diagnóstico SSH hacia router Mikrotik mediante herramienta controlada.
- Revisión de contexto del cliente, tickets, historial local y logs del agente.
- Flujo de diagnóstico remoto para velocidad, lentitud e intermitencia.
- Escalamiento automático para corte, luz roja, fibra o falta de señal.
- Generación de payload JSON para escalación.
- Registro persistente de logs de auditoría.
- Interfaz web básica con Flask.

## Reglas de decisión

| Tipo de caso | Acción |
|---|---|
| Problemas de velocidad | Diagnóstico remoto |
| Intermitencia | Diagnóstico remoto |
| Conexión lenta | Diagnóstico remoto |
| Corte de servicio | Escalar a técnico |
| Luz roja / falta de señal | Escalar a técnico |
| Fibra / cobertura crítica | Escalar a técnico |
| Soporte general o administrativo | Revisión por soporte |

## Variables de entorno

Crear archivo `.env`:

```env
GNS_API_BASE_URL=https://app.gns.com.mx/gns-sandbox
GNS_API_USER=usuario
GNS_API_PASSWORD=password
APP_PORT=5000
USE_SUPPORT_GRAPH=true
USE_LANGGRAPH_AGENT=true
AUTO_CREATE_TICKET_AFTER_EDGE_FAIL=false
NETWORK_DIAG_TARGET=8.8.8.8
SSH_TIMEOUT_SECONDS=15
ROUTER_COMMAND_TIMEOUT_SECONDS=10
ENABLE_TRACEROUTE=true
MIKROTIK_HOST=ip_del_router
MIKROTIK_PORT=22
MIKROTIK_USER=usuario_ssh
MIKROTIK_PASSWORD=password_ssh
```

## Orquestación con LangGraph

Cuando `USE_SUPPORT_GRAPH=true`, el chatbot usa un grafo de soporte para:

- Validar al cliente desde la API GNS Sandbox.
- Consultar estado de pago, servicios y tickets activos.
- Revisar evidencia local registrada por el agente.
- Clasificar la intención del mensaje del usuario.
- Decidir si responde, consulta datos, registra solución, crea ticket o ejecuta diagnóstico de borde.
- Registrar cada decisión relevante en `logs/agent.log`.

El flujo anterior de Flask se conserva como respaldo si se desactiva `USE_SUPPORT_GRAPH`
o si el grafo no puede inicializarse.

## Diagnóstico de borde

Los reportes de lentitud, intermitencia, desconexión o corte activan una
herramienta SSH controlada contra el router Mikrotik y ejecutan únicamente
comandos permitidos:

- `/ping <target> count=5`
- `/tool traceroute <target>`

Las credenciales del router se leen desde `.env`; no deben guardarse en el
repositorio. Si la Mac local no tiene alcance al router, el flujo responde con
un error controlado y deja evidencia en `logs/agent.log`. La prueba real debe
validarse desde la VM en XenServer.

`AUTO_CREATE_TICKET_AFTER_EDGE_FAIL=false` evita crear tickets automáticamente
durante pruebas locales. En la VM puede activarse si se desea que una pérdida
de paquetes o falla de diagnóstico dispare el ticket de soporte.

Si el traceroute de RouterOS tarda demasiado, `ROUTER_COMMAND_TIMEOUT_SECONDS`
limita la espera por comando. Para una demostración enfocada en el ping real
del Mikrotik, puede usarse `ENABLE_TRACEROUTE=false`.
