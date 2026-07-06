# Local Demo Guide

Run the monitoring platform locally with **Docker Compose** and optionally enable **Copilot** (RAG + tool calls) via Ollama or an OpenAI-compatible API.

---

## 1. Clone and run

```bash
git clone https://github.com/<your-username>/environment_project.git
cd environment_project/monitor_business
docker compose up -d postgres redis rabbitmq ai-inference-service monitor-service task-worker api-gateway
# Frontend (separate terminal)
cd frontend && npm install && npm run dev
```

| Endpoint | URL |
|----------|-----|
| Gateway API | `http://localhost:8080` |
| Admin frontend | `http://localhost:5173` (confirm Vite output) |
| AI service health | `http://localhost:8000/health` |

Full step-by-step instructions: [monitor_business/README.md](./monitor_business/README.md).

---

## 2. Features with and without an LLM

| Feature | LLM required? | Notes |
|---------|---------------|-------|
| **Analytics → discharge/turbidity forecast charts** | No | Ridge model **fits on request** from IV CSV; no `.pkl` dependency |
| Turbidity four-state monitoring, threshold scan | No | Rules + statistics |
| Alert list, site map, stats overview | No | Spring + PostgreSQL |
| **Copilot panel Q&A** | **Yes** | Needs `ASSISTANT_LLM_*` (Ollama or OpenAI-compatible API) |
| Turbidity 12h risk **AI explanation text** | **Yes** | Numeric forecast still works; explanation field reports unavailable |

Without an LLM configured, focus on **forecast curves** and **alerts/map** — they exercise the full data and business stack.

---

## 3. Optional: local Ollama (Copilot)

```bash
# macOS example: after installing Ollama
ollama pull qwen2.5:3b   # or llama3.1:8b (matches docker-compose default)
```

`monitor_business/docker-compose.yml` defaults `ai-inference-service` to `host.docker.internal:11434`.  
Copy `ai_service/.env.example` to `ai_service/.env.local` only if you **run uvicorn locally** instead of Compose env vars.

Before first Copilot use, rebuild the RAG index in `ai_service` (only needs committed `docs/turbidity_operations.md`):

```bash
cd ai_service
python -m assistant.rag.indexer --rebuild
```

### Copilot demo questions

Try these in the bottom-right Copilot panel once Ollama is running:

1. **Ops docs (RAG)**: `What is Phase B? How does recommend_alert relate to 12h risk?`
2. **Live data (tools)**: `What is the current turbidity state for site 12117500?`
3. **Mixed (RAG + tools)**: `Why might site 12117500 recommend_alert? What does the Phase B doc say?`

Chinese questions work too; Copilot system prompts favor English for ops-doc answers.

---

## 4. Safe push checklist

Before pushing from the repo root:

```bash
git status
git check-ignore -v ai_service/reports/eda/12117000_00060.png   # should be ignored
git check-ignore -v ai_service/.env.local                        # should be ignored
```

**Never commit**:

- `.env`, `.env.local`, any `*.pem` / `*.key`, API keys
- `ai_service/data/` (IV CSV, feature tables — large and may contain sensitive ops info)
- `ai_service/reports/`, backtest JSON, EDA plots, `models/*.pkl`, and other large artifacts (see root `.gitignore`)
- Internal planning Markdown (`ai_service/plan/`, `*implementation*`, etc.)

**Before first public push**:

```bash
# If large files were committed historically, remove from index only (keeps local files)
git rm -r --cached .cursor/ 2>/dev/null || true
git rm -r --cached ai_service/reports/ 2>/dev/null || true
git rm -r --cached ai_service/plan/ 2>/dev/null || true
git rm --cached ai_service/models/*.pkl 2>/dev/null || true
git status   # confirm only source, config, DEMO, etc.
git push -u origin main
```

In GitHub **Settings → General**, you can enable *Private vulnerability reporting*; **do not** put production database passwords in a public README.

---

*Keep this document in sync with repo `.gitignore` and `DEFAULT_RAG_DOC_REL_PATHS` in `assistant/config.py`.*
