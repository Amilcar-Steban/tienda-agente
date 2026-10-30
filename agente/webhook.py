"""Receptor del webhook de Alertmanager: una investigación por cada alerta que empieza a disparar.

    uvicorn agente.webhook:app --host 0.0.0.0 --port 8080

En Alertmanager (Fase 7), un receptor más junto al de la guardia:
    receivers:
      - name: agente
        webhook_configs: [{ url: "http://agente.tienda-agente:8080/alertmanager", send_resolved: false }]

El informe va al log (JSON, para Loki) y, si hay SLACK_WEBHOOK_URL, al canal del incidente.
"""

import asyncio
import json
import logging
import os
import time

import httpx
from mcp import Client
from openai import AsyncOpenAI
from starlette.applications import Starlette
from starlette.background import BackgroundTask
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from agente import agente

log = logging.getLogger("tienda.agente")
logging.basicConfig(level=logging.INFO, format="%(message)s")

_una_a_la_vez = asyncio.Semaphore(1)  # cada investigación cuesta tokens: no en paralelo
_vistas: dict[str, float] = {}  # huella de la alerta → cuándo se investigó
REPETIR_TRAS = 30 * 60  # una alerta que sigue disparando no se reinvestiga en 30 min


def _texto(alerta: dict) -> str:
    etiquetas = ", ".join(f"{k}={v}" for k, v in sorted(alerta.get("labels", {}).items()))
    notas = alerta.get("annotations", {})
    return (f"{alerta.get('labels', {}).get('alertname', '?')} ({etiquetas})\n"
            f"{notas.get('summary', '')}\n{notas.get('description', '')}\nDesde: {alerta.get('startsAt', '?')}").strip()


async def _investigar(texto: str, huella: str) -> None:
    async with _una_a_la_vez:
        llm = AsyncOpenAI(base_url=os.environ["LLM_BASE_URL"], api_key=os.environ.get("LLM_API_KEY", "local"), timeout=600)
        async with Client(agente.servidor_local()) as mcp:
            inf = await agente.investigar(texto, mcp, llm, os.environ["LLM_MODELO"],
                                          opciones=json.loads(os.environ.get("LLM_OPCIONES", "{}")))
    log.info(json.dumps({"evento": "informe", "huella": huella, "pasos": inf.pasos, "fin": inf.motivo_fin,
                         "tokens": inf.tokens_entrada + inf.tokens_salida, "rechazadas": inf.rechazadas,
                         "herramientas": [h for h, _ in inf.herramientas], "informe": inf.texto}, ensure_ascii=False))
    if url := os.environ.get("SLACK_WEBHOOK_URL"):
        async with httpx.AsyncClient(timeout=10) as http:
            await http.post(url, json={"text": f"*Investigación automática* (revísala antes de actuar)\n{inf.texto}"})


async def alertmanager(request: Request) -> JSONResponse:
    carga = await request.json()
    nuevas = []
    ahora = time.time()
    for a in carga.get("alerts", []):
        huella = a.get("fingerprint", "")
        if a.get("status") != "firing" or ahora - _vistas.get(huella, 0) < REPETIR_TRAS:
            continue
        _vistas[huella] = ahora
        nuevas.append((_texto(a), huella))

    async def todas():
        for texto, huella in nuevas:
            try:
                await _investigar(texto, huella)
            except Exception as e:  # una investigación fallida no tumba el receptor
                log.error(json.dumps({"evento": "error", "huella": huella, "error": repr(e)}))

    return JSONResponse({"investigando": len(nuevas)}, status_code=202, background=BackgroundTask(todas))


async def salud(request: Request) -> JSONResponse:
    return JSONResponse({"estado": "ok"})


app = Starlette(routes=[Route("/alertmanager", alertmanager, methods=["POST"]), Route("/salud", salud)])
