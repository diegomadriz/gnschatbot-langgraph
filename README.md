# GNS Chatbot Agent

Agente de IA para la gestión y diagnóstico de incidentes residenciales y empresariales de GNS.

## Objetivo

Automatizar soporte técnico de primer nivel mediante un chatbot que consulta
tickets desde la API GNS Sandbox y ejecuta diagnósticos reales sobre la
infraestructura de borde del laboratorio. El agente interpreta salidas crudas
del router y de la antena, responde al cliente en lenguaje claro y conserva la
evidencia técnica en logs y detalle estructurado.

## Infraestructura

- VM desplegada en XenServer
- Sistema operativo: Ubuntu 26.04 LTS
- IP estática: 10.32.66.113
- Gateway: 10.32.66.1
- DNS: 10.32.65.43 y 10.32.65.53
- Puerto recomendado de prueba: 5001

## Funciones principales

- Consulta de tickets activos e históricos desde la API GNS Sandbox.
- Diagnóstico autónomo basado en categoría y descripción del ticket.
- Orquestación opcional con LangGraph para el flujo completo de soporte.
- Diagnóstico SSH hacia router Mikrotik mediante herramienta controlada.
- Consulta HTTPS de solo lectura hacia antena Ubiquiti.
- Parsing de ping, traceroute y respuesta HTTPS para generar una conclusión WAN.
- Respuesta sintetizada para cliente final, sin exponer hops ni salida cruda.
- Detalle técnico compacto para API, sin incluir dumps extensos de comandos.
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
APP_PORT=5001
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
ENABLE_UBIQUITI_CHECK=true
UBIQUITI_HOST=ip_de_antena
UBIQUITI_PORT=443
UBIQUITI_USER=usuario_https
UBIQUITI_PASSWORD=password_https
UBIQUITI_HTTPS_TIMEOUT_SECONDS=8
UBIQUITI_VERIFY_TLS=false
```

## Orquestación con LangGraph

Cuando `USE_SUPPORT_GRAPH=true`, el chatbot usa un grafo de soporte para:

- Validar al cliente desde la API GNS Sandbox.
- Consultar estado de pago, servicios y tickets activos.
- Revisar evidencia local registrada por el agente.
- Clasificar la intención del mensaje del usuario.
- Decidir si responde, consulta datos, registra solución, crea ticket o ejecuta diagnóstico de borde.
- Interpretar métricas parseadas como `optimal`, `high_latency`, `packet_loss_detected` o `not_verified`.
- Registrar cada decisión relevante en `logs/agent.log`.

El flujo anterior de Flask se conserva como respaldo si se desactiva `USE_SUPPORT_GRAPH`
o si el grafo no puede inicializarse.

## Diagnóstico de borde

Los reportes de lentitud, intermitencia, desconexión o corte activan una
herramienta SSH controlada contra el router Mikrotik y ejecutan únicamente
comandos permitidos:

- `/ping <target> count=5`
- `/tool traceroute <target>`

El agente parsea la salida del router para extraer pérdida de paquetes,
latencia promedio, paquetes enviados/recibidos y saltos únicos de traceroute.
Con esos datos genera una interpretación de estado WAN. Por ejemplo, si detecta
0% de pérdida y latencia baja, responde que el enlace WAN opera de manera
óptima desde el router perimetral.

Además, el agente intenta una consulta HTTPS de solo lectura contra la antena
Ubiquiti para validar alcance, autenticación y respuesta del equipo de radio.
La consulta registra endpoint probado, código HTTP y latencia; no ejecuta
cambios de configuración sobre la antena.

La respuesta al cliente es deliberadamente breve y empática. No muestra hops,
salida cruda del router ni HTML de la antena. Esa evidencia queda en
`technical_detail` de forma compacta y en `logs/agent.log`.

Las credenciales del router se leen desde `.env`; no deben guardarse en el
repositorio. Si la Mac local no tiene alcance al router, el flujo responde con
un error controlado y deja evidencia en `logs/agent.log`. La prueba real debe
validarse desde la VM en XenServer.

`AUTO_CREATE_TICKET_AFTER_EDGE_FAIL=false` evita crear tickets automáticamente
durante pruebas locales. En la VM puede activarse si se desea que una pérdida
de paquetes o falla de diagnóstico dispare el ticket de soporte.

Si el traceroute de RouterOS tarda demasiado, `ROUTER_COMMAND_TIMEOUT_SECONDS`
limita la espera por comando. Cuando se alcanza ese límite, el agente conserva
la salida parcial, registra el corte controlado en logs y responde sin bloquear
la conversación.

## Evidencia en logs

Los eventos principales se registran en `logs/agent.log`:

- `NETWORK_TOOL | device=mikrotik | command=ping:<target>` registra ejecución de ping.
- `NETWORK_TOOL | device=mikrotik | command=traceroute:<target>` registra traceroute o timeout controlado.
- `NETWORK_TOOL | device=ubiquiti | command=https_status:<endpoint>` registra la consulta HTTPS a la antena.
- `NETWORK_DIAGNOSIS_PARSED` registra pérdida, latencia promedio, paquetes enviados/recibidos, estado de traceroute y estado Ubiquiti.
- `SUPPORT_GRAPH_RESULT` registra la decisión final del grafo.

Las credenciales nunca se escriben en logs ni en el repositorio.

## Prueba rápida

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python app.py
```

En otra terminal:

```bash
curl http://127.0.0.1:5001/health

curl -X POST http://127.0.0.1:5001/api/whatsapp \
  -H "Content-Type: application/json" \
  -d '{"message":"cliente 170"}'

curl -X POST http://127.0.0.1:5001/api/whatsapp \
  -H "Content-Type: application/json" \
  -d '{"message":"mi internet esta lento e intermitente"}'
```

Para revisar evidencia:

```bash
tail -n 80 logs/agent.log
```
