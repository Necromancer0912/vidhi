# NyayaBot — Developer shortcut commands
#
# ─── PROFILE SWITCHING ──────────────────────────────────────────────────────
# make test   → local dev with Ollama gemma4:31b-cloud (no GPU needed on Mac)
# make prod   → production with llama.cpp on a remote RTX 4060 Ti via Tailscale
#
# ─── RUNNING ────────────────────────────────────────────────────────────────
# make run    → start FastAPI backend (respects current .env profile)
# make fe     → start Vite frontend dev server
#
# ─── OTHER ──────────────────────────────────────────────────────────────────
# make setup-gpu  → print step-by-step remote GPU PC setup commands
# make run-tests  → run full pytest suite
# make docker-up  → start Qdrant + Redis locally via Docker
# make kill       → kill ports 8080 and 3000

.PHONY: dev test prod env-dev env-test env-prod run fe setup-gpu install run-tests test-router test-critic \
        docker-up docker-down kill ingest ingest-static help

# ─── Profile: DEV (Groq LLM on Mac Standalone) ──────────────────────────────
dev: docker-up
	@echo "🚀 Starting backend + frontend in DEV mode (Mac Standalone)..."
	ENV_FILE=.env.dev $(MAKE) -j 2 run fe

# ─── Profile: TEST (Ollama gemma4:31b-cloud, no local GPU) ──────────────────
test: docker-up
	@echo "🚀 Starting backend + frontend in TEST mode..."
	ENV_FILE=.env.test $(MAKE) -j 2 run fe

# ─── Profile: PROD (Mac backend connecting to remote GPU PC via Tailscale) ─
prod: docker-up
	@echo "🚀 Starting backend + frontend in PROD mode (Mac -> GPU PC)..."
	ENV_FILE=.env.prod $(MAKE) -j 2 run fe

# ─── Profile: GPU (Running everything on remote GPU PC locally) ────────────
gpu: docker-up
	@echo "🚀 Starting backend + frontend in GPU mode (Local GPU PC)..."
	ENV_FILE=.env.gpu $(MAKE) -j 2 run fe

# ─── Start backend ───────────────────────────────────────────────────────────
run:
	ENV_FILE=$${ENV_FILE:-.env} .venv/bin/uvicorn main:app --host 127.0.0.1 --port 8000 --reload

run-8001:
	ENV_FILE=$${ENV_FILE:-.env} .venv/bin/uvicorn main:app --host 127.0.0.1 --port 8001 --reload

run-8002:
	ENV_FILE=$${ENV_FILE:-.env} .venv/bin/uvicorn main:app --host 127.0.0.1 --port 8002 --reload

nginx-start:
	nginx -c $(shell pwd)/infra/nginx_mac.conf

nginx-stop:
	nginx -s stop -c $(shell pwd)/infra/nginx_mac.conf || true

funnel:
	@if command -v tailscale >/dev/null 2>&1; then \
		tailscale funnel 8000; \
	elif [ -f /Applications/Tailscale.app/Contents/MacOS/Tailscale ]; then \
		/Applications/Tailscale.app/Contents/MacOS/Tailscale funnel 8000; \
	else \
		echo "Tailscale CLI not found in PATH or Applications."; \
		exit 1; \
	fi

scale: docker-up
	@echo "🚀 Starting backend instances on 8001/8002 and frontend..."
	ENV_FILE=.env.test $(MAKE) -j 3 run-8001 run-8002 fe

# ─── Start frontend ──────────────────────────────────────────────────────────
fe:
	cd frontend && npm run dev

# ─── Install Python deps ─────────────────────────────────────────────────────
install:
	pip install -r requirements.txt

# ─── Tests ───────────────────────────────────────────────────────────────────
run-tests:
	ENV_FILE=$${ENV_FILE:-.env.test} .venv/bin/pytest tests/ -v --tb=short

test-router:
	ENV_FILE=$${ENV_FILE:-.env.test} .venv/bin/pytest tests/test_router.py -v

test-critic:
	ENV_FILE=$${ENV_FILE:-.env.test} .venv/bin/pytest tests/test_critic.py -v

# ─── Docker (local Qdrant + Redis) ───────────────────────────────────────────
docker-up:
	docker compose up -d qdrant redis
	@echo "Qdrant: http://localhost:6333"
	@echo "Redis:  localhost:6379"

docker-down:
	docker compose down

# ─── Kill dev ports ──────────────────────────────────────────────────────────
kill:
	@kill -9 $$(lsof -t -i:8000 -i:3000) 2>/dev/null || true
	@echo "Killed ports 8000 and 3000"

# ─── Ingestion ───────────────────────────────────────────────────────────────
ingest:
	ENV_FILE=$${ENV_FILE:-.env} .venv/bin/python -u -m src.ingestion.pipeline

ingest-static:
	ENV_FILE=$${ENV_FILE:-.env} .venv/bin/python -u -m src.ingestion.pipeline --skip-scraping

# ─── GPU PC setup instructions ───────────────────────────────────────────────
setup-gpu:
	@echo ""
	@echo "════════════════════════════════════════════════════════════════════"
	@echo "  KOLKATA RTX 4060 Ti — llama.cpp Setup"
	@echo "  Run these commands on the GPU PC (SSH in or sit at keyboard)"
	@echo "════════════════════════════════════════════════════════════════════"
	@echo ""
	@echo "## Step 1 — Build llama.cpp with CUDA"
	@echo "git clone https://github.com/ggerganov/llama.cpp"
	@echo "cd llama.cpp"
	@echo "cmake -B build -DGGML_CUDA=ON"
	@echo "cmake --build build --config Release -j\$$(nproc)"
	@echo ""
	@echo "## Step 2 — Download models"
	@echo "mkdir -p models"
	@echo ""
	@echo "# LLM: Qwen3.5-4B Q8_0 — ~4.5GB VRAM"
	@echo "huggingface-cli download unsloth/Qwen3.5-4B-GGUF \\"
	@echo "  Qwen3.5-4B-Q8_0.gguf --local-dir models/"
	@echo ""
	@echo "# Embeddings: nomic-embed-text v1.5 — ~0.3GB VRAM"
	@echo "huggingface-cli download nomic-ai/nomic-embed-text-v1.5-GGUF \\"
	@echo "  nomic-embed-text-v1.5.Q8_0.gguf --local-dir models/"
	@echo ""
	@echo "## Step 3 — Start LLM server on port 8080 (in screen or tmux)"
	@echo "screen -S llm"
	@echo "./build/bin/llama-server \\"
	@echo "  -m models/Qwen3.5-4B-Q8_0.gguf \\"
	@echo "  --host 0.0.0.0 \\"
	@echo "  --port 8080 \\"
	@echo "  -ngl 99 \\"
	@echo "  -c 8192 \\"
	@echo "  --parallel 4 \\"
	@echo "  --api-key llama-cpp-key"
	@echo "# Detach screen: Ctrl+A then D"
	@echo ""
	@echo "## Step 4 — Start embedding server on port 8081 (in screen or tmux)"
	@echo "screen -S embed"
	@echo "./build/bin/llama-server \\"
	@echo "  -m models/nomic-embed-text-v1.5.Q8_0.gguf \\"
	@echo "  --host 0.0.0.0 \\"
	@echo "  --port 8081 \\"
	@echo "  -ngl 99 \\"
	@echo "  --embedding \\"
	@echo "  --pooling mean \\"
	@echo "  --api-key llama-cpp-key"
	@echo "# Detach screen: Ctrl+A then D"
	@echo ""
	@echo "## Step 5 — Get Tailscale IP (run on GPU PC)"
	@echo "tailscale ip -4"
	@echo "# Example output: 100.64.0.42"
	@echo ""
	@echo "## Step 6 — On your Mac, add to .env:"
	@echo "LLAMACPP_BASE_URL=http://100.64.0.42:8080"
	@echo "LLAMACPP_EMBED_URL=http://100.64.0.42:8081"
	@echo "LLAMACPP_API_KEY=llama-cpp-key"
	@echo ""
	@echo "## Step 7 — Switch to prod profile and start"
	@echo "make prod"
	@echo "make run"
	@echo ""
	@echo "## VRAM Budget Check (RTX 4060 Ti 8GB)"
	@echo "  Qwen3.5-4B Q8_0  →  ~4.5 GB"
	@echo "  nomic-embed-text →  ~0.3 GB"
	@echo "  bge-reranker-v2-m3 (runs on Mac CPU/GPU separately)"
	@echo "  Total on GPU PC: ~4.8 GB  ✅ (3.2 GB headroom)"
	@echo "════════════════════════════════════════════════════════════════════"
	@echo ""

# ─── Help ────────────────────────────────────────────────────────────────────
help:
	@echo "NyayaBot — Available commands:"
	@echo ""
	@echo "  make dev            Switch to DEV profile and start backend + frontend"
	@echo "  make test           Switch to TEST profile and start backend + frontend"
	@echo "  make prod           Switch to PROD profile and start backend + frontend"
	@echo ""
	@echo "  make env-dev        Switch to DEV profile (Groq) only"
	@echo "  make env-test       Switch to TEST profile (Ollama gemma4:31b-cloud) only"
	@echo "  make env-prod       Switch to PROD profile (llama.cpp on remote GPU) only"
	@echo ""
	@echo "  make run            Start FastAPI backend (port 8080) separately"
	@echo "  make fe             Start Vite frontend (port 3000) separately"
	@echo "  make setup-gpu      Print remote GPU PC setup instructions"
	@echo ""
	@echo "  make run-tests      Run full pytest suite"
	@echo "  make docker-up      Start Qdrant + Redis via Docker"
	@echo "  make kill           Kill ports 8080 and 3000"
	@echo "  make ingest         Run full ingestion pipeline"
