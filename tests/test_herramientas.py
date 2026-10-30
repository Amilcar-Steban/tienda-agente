import httpx
from mcp import Client

from agente.escenario import BackendEscenario
from agente.herramientas import MAX_CARACTERES, BackendReal, crear_servidor

ESPERADAS = {"consultar_prometheus", "alertas_activas", "buscar_logs", "estado_pods", "eventos", "historial_despliegue"}


async def test_solo_herramientas_de_lectura():
    async with Client(crear_servidor(BackendEscenario({}))) as c:
        nombres = {t.name for t in (await c.list_tools()).tools}
    assert nombres == ESPERADAS  # si alguien añade una herramienta que escribe, este test lo delata


async def _llamar(backend, herramienta, args=None):
    async with Client(crear_servidor(backend)) as c:
        res = await c.call_tool(herramienta, args or {})
    return "\n".join(b.text for b in res.content)


async def test_redacta_secretos_antes_de_devolver():
    salida = await _llamar(BackendEscenario({"logs": "conectando con DB_PASSWORD=supersecreta"}), "buscar_logs",
                           {"consulta_logql": '{app="tienda-api"}'})
    assert "supersecreta" not in salida and "[REDACTADO]" in salida


async def test_recorta_salidas_largas():
    salida = await _llamar(BackendEscenario({"eventos": "x" * 50_000}), "eventos")
    assert len(salida) < MAX_CARACTERES + 100 and "recortado" in salida


def _backend_con(manejador):
    b = BackendReal()
    b.http = httpx.Client(transport=httpx.MockTransport(manejador))
    return b


def test_prometheus_real_pasa_la_consulta():
    vistas = []

    def manejador(req: httpx.Request):
        vistas.append(req.url)
        return httpx.Response(200, json={"status": "success", "data": {"result": []}})

    assert "success" in _backend_con(manejador).prometheus("up")
    assert vistas[0].path == "/api/v1/query" and vistas[0].params["query"] == "up"


def test_un_fallo_se_devuelve_como_error_no_se_inventa():
    salida = _backend_con(lambda req: httpx.Response(503)).alertas()
    assert salida.startswith("ERROR")


def test_logs_de_loki_legibles():
    cuerpo = {"data": {"result": [{"stream": {"service_name": "tienda-api", "k8s_pod_name": "api-1", "otra": "x"},
                                   "values": [["1761800000000000000", "error de conexión"]]}]}}
    salida = _backend_con(lambda req: httpx.Response(200, json=cuerpo)).logs('{app="tienda-api"}', 15)
    assert "k8s_pod_name=api-1,service_name=tienda-api error de conexión" in salida and "otra" not in salida


def test_un_403_de_kubernetes_llega_al_modelo_como_texto():
    class ApiFalsa:
        def list_namespaced_pod(self, ns):
            from kubernetes.client import ApiException
            raise ApiException(status=403, reason="Forbidden")

    b = BackendReal()
    b._k8s = (ApiFalsa(), None)
    assert b.pods("tienda") == "ERROR en pods('tienda',): 403 Forbidden"
