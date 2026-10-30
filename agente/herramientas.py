"""Servidor MCP de solo lectura sobre la plataforma de la tienda.

Expone a cualquier cliente MCP (tu agente de terminal, tu IDE o agente.py) lo que hace falta para
diagnosticar: métricas (Prometheus), logs (Loki) y el estado de Kubernetes. No hay ni una
herramienta que escriba: actuar es cosa de una persona, o de un PR al repo GitOps.

    python -m agente.herramientas                     # stdio, para un cliente local
    PROMETHEUS_URL=… LOKI_URL=… python -m agente.herramientas

Kubernetes: usa el ServiceAccount del pod (k8s/rbac-solo-lectura.yaml) o tu kubeconfig.
"""

import json
import os
import time
from typing import Protocol

import httpx
from mcp.server import MCPServer

from agente.redactar import marcar_inyecciones, redactar

MAX_CARACTERES = 8000  # lo que vuelve al contexto del modelo se paga y lo distrae: recórtalo


def _limpiar(texto: str) -> str:
    texto = marcar_inyecciones(redactar(texto))
    if len(texto) > MAX_CARACTERES:
        texto = texto[:MAX_CARACTERES] + f"\n[… recortado: {len(texto) - MAX_CARACTERES} caracteres más]"
    return texto


class Backend(Protocol):
    def prometheus(self, query: str) -> str: ...
    def alertas(self) -> str: ...
    def logs(self, consulta: str, minutos: int) -> str: ...
    def pods(self, namespace: str) -> str: ...
    def eventos(self, namespace: str) -> str: ...
    def historial(self, deployment: str, namespace: str) -> str: ...


def crear_servidor(backend: Backend) -> MCPServer:
    mcp = MCPServer("tienda-ops")

    @mcp.tool()
    def consultar_prometheus(query: str) -> str:
        """Ejecuta una consulta PromQL instantánea. Ejemplos: tasa de errores 5xx de la API
        `sum(rate(http_server_request_duration_seconds_count{job="tienda-api",http_response_status_code=~"5.."}[5m]))`,
        reinicios `increase(kube_pod_container_status_restarts_total{namespace="tienda"}[30m])`."""
        return _limpiar(backend.prometheus(query))

    @mcp.tool()
    def alertas_activas() -> str:
        """Lista las alertas que están disparando ahora mismo en Prometheus."""
        return _limpiar(backend.alertas())

    @mcp.tool()
    def buscar_logs(consulta_logql: str, minutos: int = 15) -> str:
        """Busca en Loki con LogQL las últimas líneas de los últimos `minutos` (máximo 120).
        Las etiquetas son las de OpenTelemetry: `{service_name="tienda-api"} |= "error"`, o en
        Kubernetes `{k8s_namespace_name="tienda", service_name="tienda-postgres"}`."""
        return _limpiar(backend.logs(consulta_logql, max(1, min(minutos, 120))))

    @mcp.tool()
    def estado_pods(namespace: str = "tienda") -> str:
        """Estado de los pods de un namespace: fase, listos, reinicios, imagen y el motivo si
        esperan o terminaron (ImagePullBackOff, CrashLoopBackOff, OOMKilled…)."""
        return _limpiar(backend.pods(namespace))

    @mcp.tool()
    def eventos(namespace: str = "tienda") -> str:
        """Los últimos eventos de Kubernetes del namespace (los Warning primero)."""
        return _limpiar(backend.eventos(namespace))

    @mcp.tool()
    def historial_despliegue(deployment: str, namespace: str = "tienda") -> str:
        """Revisiones de un Deployment (sus ReplicaSets) con la imagen de cada una y cuándo se
        creó: sirve para relacionar un síntoma con el último cambio."""
        return _limpiar(backend.historial(deployment, namespace))

    return mcp


def _sin_excepciones(metodo):
    """Un 403 o un 404 de Kubernetes vuelve como texto: el modelo debe saber que no tiene el dato (o
    el permiso). Si la excepción escapa, el cliente MCP solo recibe "Error executing tool …"."""

    def envoltura(self, *args):
        try:
            return metodo(self, *args)
        except Exception as e:  # ApiException, ConfigException, errores de red…
            detalle = f"{getattr(e, 'status', '')} {getattr(e, 'reason', '') or e}".strip()
            return f"ERROR en {metodo.__name__}{args}: {detalle}"

    return envoltura


class BackendReal:
    """Habla con Prometheus, Loki y la API de Kubernetes. Solo hace lecturas."""

    def __init__(self) -> None:
        self.prom = os.environ.get("PROMETHEUS_URL", "http://prometheus.monitoring:9090")
        self.loki = os.environ.get("LOKI_URL", "http://loki.monitoring:3100")
        self.http = httpx.Client(timeout=10)
        self._k8s = None

    def _get(self, url: str, **params) -> str:
        try:
            r = self.http.get(url, params=params)
            r.raise_for_status()
            return r.text
        except httpx.HTTPError as e:  # el modelo debe saber que falló, no inventar el resultado
            return f"ERROR consultando {url}: {e}"

    def prometheus(self, query: str) -> str:
        return self._get(f"{self.prom}/api/v1/query", query=query)

    def alertas(self) -> str:
        return self._get(f"{self.prom}/api/v1/alerts")

    def logs(self, consulta: str, minutos: int) -> str:
        fin = time.time_ns()
        crudo = self._get(f"{self.loki}/loki/api/v1/query_range", query=consulta, limit=200,
                          start=fin - minutos * 60 * 10**9, end=fin, direction="backward")
        if crudo.startswith("ERROR"):
            return crudo
        lineas = []
        for flujo in json.loads(crudo).get("data", {}).get("result", []):
            etiquetas = ",".join(f"{k}={v}" for k, v in sorted(flujo["stream"].items())
                                 if k in ("service_name", "k8s_pod_name", "detected_level"))
            lineas += [f"{time.strftime('%H:%M:%S', time.gmtime(int(ts) / 1e9))} {etiquetas} {linea}" for ts, linea in flujo["values"]]
        return "\n".join(sorted(lineas, reverse=True)) or "sin resultados"

    @property
    def k8s(self):
        if self._k8s is None:
            from kubernetes import client, config

            try:
                config.load_incluster_config()
            except config.ConfigException:
                config.load_kube_config()
            self._k8s = (client.CoreV1Api(), client.AppsV1Api())
        return self._k8s

    @_sin_excepciones
    def pods(self, namespace: str) -> str:
        filas = []
        for p in self.k8s[0].list_namespaced_pod(namespace).items:
            for c in p.status.container_statuses or []:
                motivo = ""
                if c.state.waiting:
                    motivo = f"esperando: {c.state.waiting.reason} {c.state.waiting.message or ''}"
                elif c.last_state.terminated:
                    motivo = f"última terminación: {c.last_state.terminated.reason} (código {c.last_state.terminated.exit_code})"
                filas.append(f"{p.metadata.name} [{c.name}] fase={p.status.phase} listo={c.ready} "
                             f"reinicios={c.restart_count} imagen={c.image} {motivo}".strip())
            if not p.status.container_statuses:
                filas.append(f"{p.metadata.name} fase={p.status.phase} (sin contenedores arrancados)")
        return "\n".join(filas) or f"no hay pods en {namespace}"

    @_sin_excepciones
    def eventos(self, namespace: str) -> str:
        evs = self.k8s[0].list_namespaced_event(namespace).items
        evs.sort(key=lambda e: (e.type != "Warning", -(e.last_timestamp or e.event_time or e.metadata.creation_timestamp).timestamp()))
        return "\n".join(f"{e.type} {e.reason} {e.involved_object.kind}/{e.involved_object.name} x{e.count or 1}: {e.message}"
                         for e in evs[:30]) or "sin eventos"

    @_sin_excepciones
    def historial(self, deployment: str, namespace: str) -> str:
        core, apps = self.k8s
        d = apps.read_namespaced_deployment(deployment, namespace)
        sel = ",".join(f"{k}={v}" for k, v in d.spec.selector.match_labels.items())
        rss = apps.list_namespaced_replica_set(namespace, label_selector=sel).items
        rss.sort(key=lambda r: int(r.metadata.annotations.get("deployment.kubernetes.io/revision", 0)), reverse=True)
        return "\n".join(
            f"revisión {r.metadata.annotations.get('deployment.kubernetes.io/revision')} "
            f"creada {r.metadata.creation_timestamp:%Y-%m-%d %H:%M:%S}Z réplicas={r.status.replicas or 0} "
            f"listas={r.status.ready_replicas or 0} imágenes={[c.image for c in r.spec.template.spec.containers]}"
            for r in rss[:10])


if __name__ == "__main__":
    crear_servidor(BackendReal()).run()  # stdio por defecto
