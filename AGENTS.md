# Agente de guardia de la tienda

Instrucciones para los agentes de código (Claude Code, Codex CLI, Gemini CLI…) que trabajen en este
repositorio. Si una persona nueva necesitaría saberlo, va aquí.

## Comandos
- Tests: `uv run pytest -q` (sin red ni modelo; deben pasar siempre)
- Evaluaciones: `LLM_BASE_URL=http://localhost:11434/v1 LLM_MODELO=qwen3:4b-instruct uv run python evals/evaluar.py`
  (necesitan un modelo; tardan minutos)
- Reglas de Prometheus: `promtool test rules alertas/anomalias_test.yml`
- Workflows: `actionlint` y `zizmor .github/workflows/`

## Reglas
- `agente/herramientas.py` solo tiene herramientas de LECTURA. No añadas ninguna que escriba, borre,
  reinicie o escale: `test_solo_herramientas_de_lectura` lo comprueba. Las acciones las aprueba una persona.
- Todo lo que devuelve una herramienta pasa por `redactar()` y `_limpiar()`. No lo saltes.
- Si cambias `SISTEMA` (el prompt), las herramientas o el modelo, ejecuta las evaluaciones antes y
  después y pon los dos resultados en el PR.
- Las versiones van fijadas (`uv.lock`, SHAs en los workflows, etiquetas de imagen).
- Nunca pongas claves en el código ni en los casos de evaluación.

## Estructura
- `agente/` el servidor MCP (`herramientas.py`), el bucle (`agente.py`) y el receptor de Alertmanager (`webhook.py`)
- `evals/` incidentes simulados y su evaluador · `tests/` tests sin modelo
- `alertas/` reglas de anomalías con su test · `k8s/` permisos y despliegue · `scripts/` utilidades del CI
