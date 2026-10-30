# Agente de guardia de la tienda (Fase 10)

Recibe las alertas de Alertmanager e investiga con herramientas de **solo lectura**: métricas,
logs, pods, eventos e historial de despliegues. Después escribe una hipótesis con sus evidencias y
una acción propuesta. No ejecuta nada. Un rollback lo propone como PR al repo `tienda-gitops`, y lo
aprueba una persona.

| Archivo | Qué es |
|---|---|
| `agente/herramientas.py` | Servidor MCP `tienda-ops`: 6 herramientas de lectura (Prometheus, Loki, Kubernetes), con secretos redactados y salidas recortadas |
| `agente/agente.py` | El bucle: modelo con API compatible con OpenAI (Ollama, vLLM, un proveedor), límite de pasos y de tokens, auditoría JSONL y trazas OTel GenAI |
| `agente/webhook.py` | Receptor del webhook de Alertmanager: una investigación por alerta nueva, de una en una |
| `agente/redactar.py` | Quita claves, tokens y contraseñas antes de que nada llegue al modelo |
| `evals/` | 5 incidentes simulados (imagen inexistente, OOM, base de datos sin disco, inyección en los logs, caché caída) y su evaluador |
| `tests/` | 26 tests sin modelo ni clúster: herramientas, límites del bucle, trazas, webhook, redacción |
| `alertas/` | Detección de anomalías de tráfico en PromQL, con su test de `promtool` |
| `k8s/` | ServiceAccount con `view` solo en `tienda`, y el Deployment del agente |
| `.github/workflows/` | CI del agente (tests + evals con Ollama) y explicación de fallos del CI con Bedrock |
| `AGENTS.md` | Instrucciones para los agentes de código que trabajen en este repo |

## Probarlo en tu portátil

Necesitas uv y Ollama (o Docker). El modelo de referencia es `qwen3:4b-instruct` (2,5 GB): pequeño, sabe
usar herramientas y no "piensa" antes de responder (la variante `qwen3:4b` sí, y en CPU es unas 4 veces más
lenta). Arranca Ollama con **`OLLAMA_CONTEXT_LENGTH=16384`**: por defecto usa 4096 tokens de contexto y,
cuando una conversación no cabe, la recorta sin avisar.

```bash
uv lock && uv run pytest -q                       # 26 tests, sin red: siempre en verde
OLLAMA_CONTEXT_LENGTH=16384 ollama serve &       # o el contenedor ollama/ollama:0.40.13 con -e OLLAMA_CONTEXT_LENGTH=16384
ollama pull qwen3:4b-instruct
export LLM_BASE_URL=http://localhost:11434/v1 LLM_MODELO=qwen3:4b-instruct
uv run python evals/evaluar.py                     # los 5 incidentes simulados: ~6 min en CPU
promtool test rules alertas/anomalias_test.yml     # o con la imagen prom/prometheus:v3.15.1
```

Contra tu clúster de verdad (usa tu kubeconfig; Prometheus y Loki, por port-forward):

```bash
PROMETHEUS_URL=http://localhost:9090 LOKI_URL=http://localhost:3100 \
  uv run python -m agente.agente "TiendaApiSinReplicas: tienda-api no tiene réplicas disponibles"
```

Y para usar las herramientas desde tu agente de terminal o tu IDE, regístralas como servidor MCP
stdio con el comando `uv run python -m agente.herramientas`.

## En el clúster

```bash
docker build -t ghcr.io/TU-USUARIO/tienda-agente:0.1.0 .   # mejor: con el pipeline firmado de la Fase 8
kubectl apply -f k8s/rbac-solo-lectura.yaml -f k8s/despliegue.yaml
```

Y en Alertmanager, un receptor más (la ruta que lo usa, con `continue: true`, para que la guardia
siga recibiendo la alerta):

```yaml
receivers:
  - name: agente
    webhook_configs: [{ url: "http://agente.tienda-agente:8080/alertmanager", send_resolved: false }]
```

Lo que falta para producción, y queda como ejercicio: una NetworkPolicy de salida que solo deje
hablar con la API de Kubernetes, Prometheus, Loki y el endpoint del modelo, y la herramienta que abre
el PR de rollback (con un token de GitHub que solo pueda abrir PRs en `tienda-gitops`).

## Explicar los fallos del CI

`.github/workflows/explicar-fallo.yml` se llama desde `ci.yml` cuando un job falla en un PR del propio
repo (los de forks quedan fuera). Necesita la variable `ROL_BEDROCK_CI`: un rol de AWS con confianza
OIDC para este repo y permiso `bedrock:InvokeModel` sobre un único modelo. Y también `BEDROCK_MODELO`.
