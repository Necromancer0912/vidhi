# Backend API image. Qdrant, Redis and Ollama run as separate services
# (docker-compose.yml starts Qdrant and Redis); point QDRANT_URL, REDIS_URL and
# the OLLAMA_* settings at them. Mount the processed data at /app/data so the
# BM25 index (data/processed/bm25_index.pkl) is available.
FROM python:3.11-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Dependencies first, in their own layer, so code changes don't reinstall them.
# The CPU build of PyTorch goes in first: the default Linux wheel pulls several
# gigabytes of CUDA libraries this API never uses.
COPY pyproject.toml ./
RUN python -c "import tomllib; deps = tomllib.load(open('pyproject.toml', 'rb'))['project']['dependencies']; open('/tmp/requirements.txt', 'w').write('\n'.join(deps))" \
    && pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu \
    && pip install --no-cache-dir -r /tmp/requirements.txt

COPY src/ ./src/
COPY main.py ./

# Never run the API as root.
RUN useradd --create-home --uid 10001 vidhi && chown -R vidhi /app
USER vidhi

ENV PYTHONPATH=/app \
    PYTHONUNBUFFERED=1

EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
