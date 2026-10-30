from starlette.testclient import TestClient

from agente import webhook

ALERTA = {"status": "firing", "fingerprint": "abc", "startsAt": "2026-10-30T10:00:00Z",
          "labels": {"alertname": "TiendaApiSinReplicas", "namespace": "tienda"},
          "annotations": {"summary": "tienda-api sin réplicas disponibles"}}


def test_investiga_solo_lo_nuevo_y_lo_que_dispara(monkeypatch):
    vistas = []

    async def falsa(texto, huella):
        vistas.append((texto, huella))

    monkeypatch.setattr(webhook, "_investigar", falsa)
    webhook._vistas.clear()
    c = TestClient(webhook.app)
    resuelta = {**ALERTA, "status": "resolved", "fingerprint": "def"}
    r = c.post("/alertmanager", json={"alerts": [ALERTA, resuelta]})
    assert r.status_code == 202 and r.json() == {"investigando": 1}
    assert vistas[0][1] == "abc" and "TiendaApiSinReplicas" in vistas[0][0] and "sin réplicas" in vistas[0][0]
    # la misma alerta, otra vez dentro de los 30 minutos: no se repite (ni se paga dos veces)
    assert c.post("/alertmanager", json={"alerts": [ALERTA]}).json() == {"investigando": 0}


def test_salud():
    assert TestClient(webhook.app).get("/salud").json() == {"estado": "ok"}
