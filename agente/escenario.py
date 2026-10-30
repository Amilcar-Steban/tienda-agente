"""Un incidente simulado: las herramientas devuelven respuestas grabadas en vez de consultar el clúster.

Sirve para las evaluaciones (evals/) y los tests: el mismo agente, las mismas herramientas, sin clúster.
"""


class BackendEscenario:
    def __init__(self, respuestas: dict[str, str]):
        self.r = respuestas

    def _de(self, clave: str) -> str:
        return self.r.get(clave, "sin resultados")

    def prometheus(self, query: str) -> str:
        return self._de("prometheus")

    def alertas(self) -> str:
        return self._de("alertas")

    def logs(self, consulta: str, minutos: int) -> str:
        return self._de("logs")

    def pods(self, namespace: str) -> str:
        return self._de("pods")

    def eventos(self, namespace: str) -> str:
        return self._de("eventos")

    def historial(self, deployment: str, namespace: str) -> str:
        return self._de("historial")
