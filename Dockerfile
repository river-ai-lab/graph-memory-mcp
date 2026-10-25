# syntax=docker/dockerfile:1.7
FROM python:3.12-slim@sha256:57cd7c3a7a273101a6485ba99423ee568157882804b1124b4dd04266317710de

ARG UV_VERSION=0.8.6

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy \
    PATH="/app/.venv/bin:${PATH}" \
    EMBEDDING_BACKEND=onnx \
    EMBEDDING_MODEL=intfloat/multilingual-e5-small \
    HF_HOME=/tmp/huggingface \
    TOKENIZERS_PARALLELISM=false \
    HOME=/tmp

WORKDIR /app

RUN pip install --no-cache-dir "uv==${UV_VERSION}"

COPY pyproject.toml uv.lock README.md README_pypi.md ./
COPY graph_memory_mcp ./graph_memory_mcp
COPY docs ./docs

# Default image is ONNX Runtime only. The torch extra is not installed.
# Keep the project editable so the MCP policy resource resolves to /app/docs.
RUN uv sync --frozen --no-dev

RUN useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin app

USER 10001:10001

EXPOSE 8000

ENTRYPOINT ["graph-memory-mcp"]
CMD ["--host", "0.0.0.0", "--port", "8000", "--log-level", "INFO"]
