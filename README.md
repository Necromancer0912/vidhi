# Vidhi

Plain-language answers to questions about Indian law, drawn from the text of 494 official documents, with the exact sections cited. Available in eleven languages.

**Live:** [project-vidhi.vercel.app](https://project-vidhi.vercel.app). The backend is self-hosted, so it may occasionally be offline.

![Vidhi landing page](docs/screenshots/landing.webp)

## What it does

You ask a question the way you'd ask a friend: "My employer hasn't paid my salary for two months. What can I do?" Vidhi searches a library of Indian acts, rules, government guidelines and landmark judgments, writes an answer from the passages it found, checks each claim in that answer against those passages, and streams the result with its sources.

- **Grounded answers.** Every answer lists the sections it relied on, and a verification step can send it back for another search before you see it.
- **Eleven languages.** English, Hindi, Bengali, Punjabi, Gujarati, Marathi, Tamil, Telugu, Kannada, Malayalam and Odia, for both the interface and the answers, including native digits and the official names of acts.
- **Deep Search** for questions that span several laws: the agent plans follow-up searches and shows each step.
- **A searchable library** of every document it answers from, with titles translated into each language.
- **PDF export** of any answer with its question and sources.
- **Accounts** that keep conversations for 90 days, with export and one-click deletion of chats or the whole account.

<p>
  <img src="docs/screenshots/chat.webp" alt="An answer with its checked sources" width="49%">
  <img src="docs/screenshots/landing-hi.webp" alt="The interface in Hindi" width="49%">
</p>

## How an answer is made

```mermaid
flowchart TD
    %% ───────────────────────── 1. Browser ─────────────────────────
    subgraph CLIENT["1 · Browser: React SPA"]
        direction TB
        U(["User asks a question<br/>typed, a starter card, or spoken (Web Speech API, 11 languages)"])
        CP["Composer.jsx<br/>max 2,000 chars · Enter sends, safe for Indic input methods<br/>Deep Search toggle (accounts only)"]
        CC["ChatContext.send()<br/>guest allowance: 5 answers per browser<br/>history: last 8 turns verbatim + one summary turn for older ones"]
        REQ["POST /api/v1/chat · response read as a server-sent event stream<br/>body: message, session_id (random UUID), preferred_language,<br/>deep_search, conversation_history<br/>header: Authorization Bearer JWT when signed in"]
        U --> CP --> CC --> REQ
    end

    %% ───────────────────────── 2. Network path ─────────────────────────
    subgraph EDGE["2 · Edge and network path"]
        direction TB
        VE["Vercel · vercel.json rewrite /api/* to the Funnel<br/>visitor IP in x-vercel-forwarded-for"]
        CFW["Cloudflare Pages · dist/_worker.js proxy<br/>visitor IP in x-client-ip (from cf-connecting-ip)"]
        FUN["Tailscale Funnel · public HTTPS 443, TLS terminated<br/>forwards to 127.0.0.1:8000 · replaces X-Forwarded-For"]
        NG["nginx 127.0.0.1:8000 · round-robin to 8001 and 8002<br/>proxy_buffering off for streaming · read timeout 600 s · body max 2 MB<br/>404 for /docs, /redoc, /openapi.json, /prometheus"]
        WK["uvicorn worker 127.0.0.1:8001 or 8002 · FastAPI<br/>middleware: CORS allow-list, security headers, Prometheus request metrics"]
        VE --> FUN
        CFW --> FUN
        FUN --> NG --> WK
    end
    REQ -->|"project-vidhi.vercel.app"| VE
    REQ -->|"projectvidhi.pages.dev"| CFW

    %% ───────────────────────── 3. Security gate ─────────────────────────
    subgraph GATE["3 · Security gate · src/api/routes/chat.py + src/api/security.py"]
        direction TB
        VAL["Pydantic validation, 422 on failure<br/>message 1 to 2,000 chars, control characters stripped<br/>session_id max 100 chars, letters digits _ . : -<br/>preferred_language one of 11 codes · max 50 history turns<br/>turn role user or assistant · turn max 12,000 chars"]
        AUTH{"Authorization header?"}
        JWTV["PyJWT HS256 verify · exp and sub required<br/>invalid or expired: 401, the browser signs out"]
        LIMU["Account limit: 60 requests per minute per email"]
        LIMG["Guest limits<br/>20 per minute per visitor IP · Deep Search refused (403)<br/>20 per day per IP · 30 per minute across all guests<br/>240 per minute per connecting address (can't be forged)"]
        MEMK["Memory key = sha256(owner and session_id), first 40 hex chars<br/>owner = account email, or guest plus visitor IP"]
        SEM["Concurrency: at most 15 pipelines at once<br/>overflow: queued event, keep-alive ping every 15 s"]
        VAL --> AUTH
        AUTH -->|"yes"| JWTV --> LIMU --> MEMK
        AUTH -->|"no, guest"| LIMG --> MEMK
        MEMK --> SEM
    end
    WK --> VAL

    %% ───────────────────────── Translation in ─────────────────────────
    TIN{"preferred_language is English?"}
    TRIN["TranslationService.translate_to_english<br/>IndicTrans2 (ai4bharat, 200M) if installed, else the LLM<br/>question and every history turn"]
    STATE["get_initial_state: RAGState<br/>query (English) · session_id = memory key · history · deep_search · retry_count 0"]
    SEM --> TIN
    TIN -->|"no"| TRIN --> STATE
    TIN -->|"yes"| STATE

    %% ───────────────────────── 4. LangGraph ─────────────────────────
    subgraph GRAPH["4 · LangGraph state machine · src/graph/builder.py · run with astream_events"]
        direction TB
        CHK{"cache_check<br/>skipped for Deep Search<br/>embed query with nomic-embed-text, 768-d<br/>cosine vs cached questions at least 0.92?"}
        HIT["Cache hit: stored answer, citations, confidence<br/>returned in under a second"]
        ROUTER{"router · src/agents/router.py<br/>1. regex rules first, English and Hinglish:<br/>emergency phrases, CNR or case status, earlier in chat, greetings<br/>2. otherwise LLM classification"}
        CHK -->|"hit"| HIT
        CHK -->|"miss"| ROUTER

        EMG["emergency<br/>hybrid search with top_k 30, a wide net<br/>emergency prompt: immediate steps · never retries"]
        MEM["memory_recall<br/>scoped Redis history, the LLM answers from the conversation"]
        TOOL["tool_call<br/>CNR or case status: eCourts guidance"]
        CHAT["chitchat<br/>short direct reply, no retrieval"]
        ROUTER -->|"EMERGENCY"| EMG
        ROUTER -->|"MEMORY"| MEM
        ROUTER -->|"TOOL"| TOOL
        ROUTER -->|"CHITCHAT"| CHAT

        subgraph DEEP["Deep Search loop · accounts only"]
            direction TB
            DSP{"deep_search_planner<br/>LLM reads the passages so far<br/>returns JSON: satisfy, next_query<br/>emits deep_search_step"}
            DSR["deep_search_retrieval<br/>hybrid search for next_query<br/>passages accumulate across rounds"]
            DSP -->|"not satisfied, fewer than 4 rounds"| DSR --> DSP
        end
        ROUTER -->|"RETRIEVE with Deep Search"| DSP

        HYDE["hyde<br/>LLM drafts a statute-style hypothetical answer<br/>embedded with nomic-embed-text, 768-d"]
        ROUTER -->|"RETRIEVE"| HYDE

        subgraph HS["hybrid_search"]
            direction LR
            DEN["Dense search<br/>Qdrant collection legal_docs<br/>cosine on the HyDE vector · top 20<br/>optional act_category filter"]
            SPA["Sparse search<br/>BM25Okapi over 72,771 chunks<br/>Unicode and Indic-aware tokens · top 20"]
            RRF["Weighted reciprocal rank fusion<br/>score = sum of weight / (60 + rank + 1)<br/>dense weight 0.6 · sparse weight 0.4"]
            DEN --> RRF
            SPA --> RRF
        end
        HYDE --> DEN
        HYDE --> SPA

        RR{"rerank · ENABLE_RERANKER?"}
        TOP5["Top 5 passages"]
        RRF --> RR
        RR -->|"false in production: keep the fused order"| TOP5
        RR -->|"true: bge-reranker-v2-m3 cross-encoder"| TOP5

        GEN["generate · src/agents/generator.py<br/>assemble_context: passages up to 1,500 tokens, builds citations<br/>system prompt holds rules only · passages and recent turns go in the user message<br/>gemma4:31b-cloud via Ollama · streamed, tagged streamable_answer"]
        TOP5 --> GEN
        DSP -->|"satisfied, or 4 rounds reached"| GEN

        CRIT["critic · src/agents/critic.py<br/>1. LLM extracts up to 8 atomic claims<br/>2. each claim embedded, best cosine vs the retrieved passages<br/>3. grounded if at least 0.6 · a year missing from every passage scores 0<br/>4. confidence = recency-weighted mean · legal-standing score"]
        GEN --> CRIT
        DEC{"critic_decision"}
        CRIT --> DEC

        REF["refine_query<br/>LLM rewrites the query around the failed claims<br/>retry_count + 1 · HyDE vector cleared"]
        STORE["cache_store<br/>only if confidence above 0.6<br/>Redis hash nyaya:cache:v1:HASH · embedding, answer, citations · 7-day TTL"]
        DEC -->|"Deep Search, or route not RETRIEVE"| STORE
        DEC -->|"confidence at least 0.55 and answer at least 300 chars"| STORE
        DEC -->|"failed claims at least CRITIC_MIN_FAILURES and retries left<br/>defaults 2 and 2 · production 5 and 1"| REF
        DEC -->|"otherwise"| STORE
        REF --> DEN
        REF --> SPA
        EMG --> STORE
    end
    STATE --> CHK

    %% ───────────────────────── 5. Stream to the browser ─────────────────────────
    subgraph SSE["5 · Server-sent events · sse-starlette"]
        direction TB
        EV1["route: Searching the library<br/>deep_search_step: Looking up the next query"]
        EV2["token: the answer streams word by word, English<br/>writing and translating: progress for other languages, English draft hidden"]
        EV3["verifying: Checking each claim against the sources<br/>retry: draft 2 is buffered silently<br/>final_answer: draft 2 replaces draft 1, which is kept as the first draft"]
        EV4["done: answer, citations, confidence_score, retry_count, cache_hit, latency_ms<br/>error: generic message with a Try again button"]
    end
    ROUTER -.-> EV1
    DSP -.-> EV1
    GEN -.-> EV2
    CRIT -.-> EV3
    REF -.-> EV3

    %% ───────────────────────── Translation out and bookkeeping ─────────────────────────
    TOUT{"preferred_language is English?"}
    TROUT["translate_from_english<br/>answer in the reader's language"]
    POST["Server bookkeeping<br/>memory.add_turn under the scoped key · 30-minute TTL · last 10 turns<br/>analytics: counts per route per day and retries, never question text"]
    STORE --> TOUT
    HIT --> TOUT
    MEM --> TOUT
    TOOL --> TOUT
    CHAT --> TOUT
    TOUT -->|"no"| TROUT --> POST
    TOUT -->|"yes"| POST
    POST --> EV4

    %% ───────────────────────── 6. Browser renders and saves ─────────────────────────
    subgraph UIX["6 · Browser renders and saves"]
        direction TB
        UI["Message.jsx<br/>Markdown through marked and DOMPurify: no raw HTML, images or handlers<br/>badges: Checked against N sources · source match · Revised · Deep Search · Answered before<br/>sources shown with titles in the reader's language · only http and https links open"]
        SAVE["Signed in: POST /api/v1/chat/history straight away, keepalive under 60 KB<br/>Redis nyaya:history:EMAIL · 90-day TTL · max 1.5 MB · 60 saves per minute<br/>Guest: kept in the tab only · guest allowance minus one"]
        FB["Helpful or Not helpful: POST /api/v1/feedback, 20 per minute per IP<br/>PDF: built in the browser with jsPDF and html2canvas"]
        UI --> SAVE
        UI --> FB
    end
    EV1 --> UI
    EV2 --> UI
    EV3 --> UI
    EV4 --> UI
```

1. **Retrieval.** Legal text is dense with exact tokens (section numbers, act names, years) that embeddings alone tend to blur, so every query runs through a BM25 index and a dense vector index in parallel, merged with reciprocal rank fusion. For legal questions the model first drafts a hypothetical statute-style answer and searches with that, which closes the gap between how people phrase problems and how laws are written.
2. **Generation.** The retrieved passages go into the prompt as the only material the answer may use, and the answer cites them.
3. **Verification.** The draft is split into atomic claims, and each claim is matched to the retrieved passages by embedding similarity. A separate check discards claims that cite a year absent from the sources. If too many claims fail, the graph refines the query and searches again, up to two more times. Only answers that pass are cached.

Questions in other languages are translated to English on the way in and answers translated back on the way out, so retrieval and verification are tuned once and serve every language.

## Results

Measured on the production setup with a fixed 25-question evaluation set and the cache cleared between runs (`scripts/evaluate_rag.py`, `scripts/benchmark_llm.py`).

**Choosing the model.** Eight prompts, the production prompt template, a fixed judge model:

| Model | Median time to first token | Median total | Grounding score |
|---|---|---|---|
| minimax-m3 (previous) | 4.54 s | 11.92 s | 0.679 |
| **gemma4:31b (chosen)** | **1.19 s** | **6.88 s** | **0.716** |
| gpt-oss:20b | 4.69 s | 9.63 s | 0.710 |

**Pipeline:** mean critic confidence 0.826, 4.6 sections cited per answer on average, a single uncached answer in about 24 seconds, and cached answers in under a second.

## Engineering notes

- **Verification is a graph node, not a label.** Built on LangGraph so the critic can loop back into retrieval, and so the same state machine drives a token-level event stream that the UI turns into live progress ("Searching the library…", "Checking each claim against the sources…").
- **Hindi retrieval was silently broken, then fixed.** An early ASCII-only tokenizer returned nothing for Hindi queries and section numbers. The tokenizer is now Unicode-aware (it also keeps Indic vowel signs attached to their words), and the index records its tokenizer version so an out-of-date index re-tokenizes itself on startup.
- **Translation pipeline for the interface.** English is the only locale anyone edits. `scripts/translate_locales.py` translates new or changed strings with the project's LLM and rejects any output that drops a `{{placeholder}}`, leaves Latin letters or ASCII digits, or isn't in the target script, retrying with the reason.
- **The LLM is configuration.** When free-tier models were retired mid-project, switching providers took a benchmark run and one setting, not a refactor.

## Security

- JWT sessions (7 days) with PBKDF2-SHA256 at 600,000 iterations and transparent rehashing of older hashes; login throttling and account lockout.
- Google sign-in accepts only access tokens issued to this app's OAuth client for a verified email.
- Guest limits enforced on the server: per visitor, per day, across all guests, and per connecting address. The last can't be dodged with forged forwarding headers.
- Conversation memory is keyed to the caller, not just a client-chosen session id; session ids are random UUIDs.
- Model output is sanitised Markdown with no raw HTML, images or inline handlers; the PDF export escapes everything it renders.
- A strict Content-Security-Policy and hardened headers on every host; admin and metrics endpoints require an admin secret or an allow-listed account; API docs are off by default.
- Databases and workers bind to localhost only; the API runs as a non-root user in Docker.

133 backend tests cover the pipeline and these guarantees (`make run-tests`).

## Architecture

```mermaid
flowchart LR
    %% ───────────────────────── Visitors and the frontend app ─────────────────────────
    subgraph BROWSER["Visitor's browser"]
        direction TB
        SPA["React 18 SPA · Vite build · Tailwind CSS 4"]
        ROUTES["History-API router<br/>/ landing · /chat · /library · /signin<br/>pages lazy-loaded"]
        CTX["State (React contexts)<br/>AuthContext: JWT and user in localStorage, guest counter<br/>ChatContext: sessions, stream reader, stop and retry, history sync<br/>PrefsContext: theme and language · ToastContext"]
        I18N["i18next with http-backend<br/>/locales/LANG/translation.json and documents.json<br/>11 languages · native digits via Intl · Noto font loaded per script"]
        SAFE["Rendering safety<br/>marked and DOMPurify · escaped PDF export (jsPDF, html2canvas, lazy)<br/>only http and https links"]
        SPA --> ROUTES
        SPA --> CTX
        SPA --> I18N
        SPA --> SAFE
    end

    %% ───────────────────────── Hosting ─────────────────────────
    subgraph VERCEL["Vercel · project-vidhi.vercel.app"]
        direction TB
        VS["Static dist/ from npm run build<br/>deployed with the Vercel CLI: vercel --prod"]
        VR["vercel.json rewrites<br/>/api/* and /health to the Funnel<br/>everything else to index.html"]
        VH["Response headers<br/>Content-Security-Policy · X-Frame-Options DENY · HSTS<br/>nosniff · Referrer-Policy · Permissions-Policy (microphone self)<br/>Cross-Origin-Opener-Policy · /locales/* cached 300 s"]
    end
    subgraph CLOUDFLARE["Cloudflare Pages · projectvidhi.pages.dev"]
        direction TB
        CB["Builds automatically on every push to no-neo4j<br/>Node 22 from .nvmrc · CF_PAGES=1 forces relative /api"]
        CW["dist/_worker.js, advanced mode<br/>proxies /api/* and /health to the Funnel, adds x-client-ip<br/>serves the site with the same security headers"]
    end

    %% ───────────────────────── Google ─────────────────────────
    subgraph GOOGLE["Google"]
        direction TB
        GIS["Identity Services popup · accounts.google.com<br/>token client, scopes openid email profile"]
        TOKI["oauth2.googleapis.com/tokeninfo<br/>audience must equal GOOGLE_CLIENT_ID · email_verified"]
        UINF["googleapis.com/oauth2/v3/userinfo<br/>display name"]
        FONTS["Google Fonts<br/>Geist, Geist Mono, Noto per script"]
    end

    %% ───────────────────────── Self-hosted backend ─────────────────────────
    subgraph MAC["Self-hosted Mac · every service bound to 127.0.0.1"]
        direction TB
        FUN["Tailscale Funnel · public HTTPS on a *.ts.net name, port 443<br/>TLS termination · replaces X-Forwarded-For<br/>forwards to 127.0.0.1:8000 · tailscale funnel --bg 8000"]
        NGX["nginx 127.0.0.1:8000 · infra/nginx_mac.conf<br/>upstream fastapi_backend, round-robin<br/>streaming: proxy_buffering off, HTTP/1.1, read timeout 600 s<br/>body max 2 MB · 404 on /docs, /redoc, /openapi.json, /prometheus"]
        subgraph WORKERS["two uvicorn workers · same code, shared Redis"]
            direction LR
            W1["worker 127.0.0.1:8001"]
            W2["worker 127.0.0.1:8002"]
        end
        subgraph APP["Inside each worker · src/"]
            direction TB
            MW["Middleware<br/>CORS allow-list · security headers<br/>Prometheus request metrics · generic 500 handler"]
            API["Routes under /api/v1<br/>auth: signup, login, google, account delete<br/>chat (stream), chat/sync, chat/history get, save, delete<br/>feedback · admin: stats, ingest, retrieve, export, translate<br/>/health public · /metrics admin · /prometheus local only"]
            SEC["security.py<br/>PyJWT HS256, 7-day tokens · PBKDF2-SHA256, 600k iterations<br/>login lockout: 8 failures, 15 minutes<br/>rate limiter: Redis fixed windows · client_ip and edge_peer<br/>admin: X-Admin-Secret or an ADMIN_EMAILS account"]
            LG["LangGraph RAG pipeline<br/>cache, router, HyDE, hybrid search, rerank, generate, critic, refine"]
            TS["TranslationService<br/>IndicTrans2 when installed, otherwise the LLM"]
            MW --> API
            API --> SEC
            API --> LG
            LG --> TS
        end
        subgraph DOCKER["Docker Compose · ports published on 127.0.0.1 only"]
            direction TB
            QD[("Qdrant · 6333 HTTP, 6334 gRPC<br/>collection legal_docs · 72,771 points<br/>768-d vectors, cosine · payload index act_category")]
            RD[("Redis 7 · 6379 · append-only file on<br/>nyaya:users:EMAIL · profile and password hash<br/>nyaya:history:EMAIL · 90 days<br/>nyaya:memory:KEY · 30 minutes<br/>nyaya:cache:v1:HASH · 7 days<br/>nyaya:ratelimit and nyaya:auth:failures<br/>nyaya:analytics · nyayabot:feedback")]
        end
        OLL["Ollama 127.0.0.1:11434<br/>nomic-embed-text runs locally, 768-d<br/>gemma4:31b-cloud forwarded to Ollama Cloud"]
        BM25[("data/processed/bm25_index.pkl<br/>BM25Okapi, tokenizer version 2<br/>re-tokenizes itself when outdated, atomic save")]
        FUN --> NGX
        NGX --> W1
        NGX --> W2
        W1 --> APP
        W2 --> APP
        LG --> QD
        LG --> RD
        SEC --> RD
        LG --> OLL
        TS --> OLL
        LG --> BM25
    end
    OCLOUD["Ollama Cloud<br/>gemma4:31b inference"]
    OLL --> OCLOUD

    %% ───────────────────────── Offline knowledge build ─────────────────────────
    subgraph OFFLINE["Offline knowledge build · make ingest"]
        direction TB
        RAW["data/raw: 494 official PDFs<br/>251 acts and codes · 171 rules · 22 judgments · 20 guidelines · 30 other<br/>plus data/situations guides"]
        EXT["Text extraction · src/ingestion/loaders.py<br/>pypdf, then pdfplumber, then OCR for scanned pages · cached"]
        CHU["LegalChunker<br/>256-token chunks, 32-token overlap<br/>metadata: title, section, category, source"]
        EMB["Embed with nomic-embed-text"]
        UPS["QdrantIndexer · upsert in batches of 100"]
        BMB["scripts/rebuild_bm25.py"]
        GIX["scripts/generate_index.py<br/>frontend/src/data/statutes.json, the library list"]
        RAW --> EXT --> CHU --> EMB --> UPS
        CHU --> BMB
        EXT --> GIX
    end
    UPS --> QD
    BMB --> BM25

    %% ───────────────────────── Developer workflow ─────────────────────────
    subgraph DEV["Developer workflow"]
        direction TB
        REPO["GitHub repository<br/>deploy branch no-neo4j"]
        I18NE["scripts/translate_locales.py · npm run i18n<br/>English to 10 languages through Ollama<br/>rejects Latin letters, 0-9 digits and lost placeholders"]
        QA["pytest, 133 tests · scripts/evaluate_rag.py<br/>scripts/benchmark_llm.py · npm run build"]
    end
    REPO -->|"git push"| CB
    I18NE -->|"locale files"| VS
    QA -.-> REPO
    DEV -->|"vercel --prod"| VS

    %% ───────────────────────── Request paths ─────────────────────────
    SPA -->|"HTTPS page load"| VS
    SPA -->|"HTTPS page load"| CW
    SPA -->|"sign-in popup"| GIS
    SPA -->|"fonts"| FONTS
    VR -->|"/api and /health"| FUN
    CW -->|"/api and /health"| FUN
    SEC -->|"verify Google token"| TOKI
    SEC -->|"fetch name"| UINF
```

**Backend:** Python 3.11, FastAPI, LangGraph, Qdrant, Redis, rank-bm25, Ollama (nomic-embed-text embeddings, gemma4 generation), PyJWT, Prometheus metrics, Server-Sent Events.
**Frontend:** React 18, Vite, Tailwind CSS 4, i18next, DOMPurify, jsPDF.
**Infrastructure:** nginx, Docker, Tailscale Funnel, Vercel, Cloudflare Pages.

## Running it locally

Prerequisites: Python 3.11+, Node 20+, Docker and [Ollama](https://ollama.com).

```bash
# Backend
python -m venv .venv && .venv/bin/pip install -r requirements.txt
ollama pull nomic-embed-text && ollama pull gemma4:31b-cloud
cp .env.example .env            # set JWT_SECRET; see the file for every option
make docker-up                  # Qdrant + Redis on localhost
make ingest                     # build the index from PDFs under data/raw
python scripts/rebuild_bm25.py
make run                        # API on http://localhost:8000

# Frontend
cd frontend && npm install
npm run dev                     # http://localhost:3000, proxies /api to the backend
```

To deploy the frontend, set the backend address in `frontend/vercel.json`; the Cloudflare build derives its proxy from the same file.

## Project layout

```
src/        FastAPI app, LangGraph nodes, agents, retrieval, caching, ingestion
frontend/   React app; locales in public/locales, Cloudflare worker in cloudflare/
scripts/    Evaluation, model benchmarking, index rebuilds, translation engine
tests/      Pytest suite
infra/      nginx configuration
```

## Limitations

- Vidhi gives legal information, not legal advice, and it can be wrong.
- The library is mostly central law; state laws and very recent amendments are largely missing.
- The evaluation set is small and generated from the corpus itself, so the grounding score is a useful proxy, not a substitute for review by a lawyer.
- The backend runs on personal hardware and a free-tier model provider, so availability isn't guaranteed.

## Authors

Sayan Das and Senjuti Ghosal. Released under the [MIT License](LICENSE).
