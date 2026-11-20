# Build context: the repo root (the tool runs on the library in this same checkout).
FROM ghcr.io/astral-sh/uv:0.13.7-python3.14-trixie-slim

ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never UV_NO_DEV=1 \
    PATH="/app/.venv/bin:$PATH" HOME=/tmp PYTHONUNBUFFERED=1

WORKDIR /app
COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --locked --no-install-project
COPY src ./src
COPY platform/sql-tool ./sql-tool
RUN uv sync --locked

USER 1000:1000
HEALTHCHECK --interval=10s --timeout=3s --start-period=20s --retries=5 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2)"]
CMD ["uvicorn", "--app-dir", "sql-tool", "app:app", "--host", "0.0.0.0", "--port", "8000"]
