# Imagen del agente: dependencias fijadas por uv.lock, sin herramientas de build, sin root.
FROM ghcr.io/astral-sh/uv:0.13.6-python3.13-trixie-slim AS deps
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never UV_PROJECT_ENVIRONMENT=/app/.venv
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

FROM python:3.13.18-slim-trixie
WORKDIR /app
COPY --from=deps /app/.venv /app/.venv
COPY agente ./agente
ENV PATH=/app/.venv/bin:$PATH PYTHONUNBUFFERED=1
USER 10001:10001
EXPOSE 8080
CMD ["uvicorn", "agente.webhook:app", "--host", "0.0.0.0", "--port", "8080"]
