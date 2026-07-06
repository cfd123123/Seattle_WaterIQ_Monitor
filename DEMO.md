# Reviewer Demo Guide

A **near-zero-cost ($0)** public demo path for **recruiters, technical reviewers, and course evaluators**.

---

## 1. Overview ($0 path)

| Item | Recommendation |
|------|----------------|
| Code hosting | **Public GitHub repository** (free) |
| Runtime | Local **Docker Compose** (see `monitor_business/docker-compose.yml`) |
| Demo video | **2-minute** screen recording (see §3); upload to YouTube **unlisted** or Bilibili; link from README |
| Static screenshots | `docs/screenshots/` in the repo (see §4) |
| LLM (Copilot) | **Optional**: local **Ollama** (free) or note in README that an API key is required |

**Core capabilities you can show without spending money**: USGS data pull, short-horizon forecast curves, turbidity state/alerts, admin map and statistics.  
**Capabilities that need an LLM**: **Copilot Q&A** in the bottom-right corner, turbidity risk **AI text explanations** (without an LLM, APIs degrade gracefully or report not configured).

---

## 2. Quick path for reviewers (5 minutes)

### 2.1 Clone & run

```bash
git clone https://github.com/<your-username>/environment_project.git
cd environment_project/monitor_business
docker compose up -d postgres redis rabbitmq ai-inference-service monitor-service task-worker api-gateway
# Frontend (separate terminal)
cd frontend && npm install && npm run dev
```

- Gateway API: `http://localhost:8080`
- Admin frontend: typically `http://localhost:5173` (confirm Vite output)
- AI service health: `http://localhost:8000/health`

Full step-by-step instructions: [monitor_business/README.md](./monitor_business/README.md).

### 2.2 Works without LLM

| Feature | LLM required? | Notes |
|---------|---------------|-------|
| **Analytics → discharge/turbidity forecast charts** | No | Ridge model **fits on request** from IV CSV; no `.pkl` dependency |
| Turbidity four-state monitoring, threshold scan | No | Rules + statistics |
| Alert list, site map, stats overview | No | Spring + PostgreSQL |
| **Copilot panel Q&A** | **Yes** | Needs `ASSISTANT_LLM_*` (Ollama or OpenAI-compatible API) |
| Turbidity 12h risk **AI explanation text** | **Yes** | Numeric forecast still works; explanation field reports unavailable |

If reviewers **do not configure Ollama/API key**: focus on **forecast curves** and **alerts/map**; README and demo video can still show Copilot (recorded locally by the author).

### 2.3 Optional: local Ollama (free Copilot)

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

---

## 3. Recommended 2-minute demo video script

**Resolution**: 1920×1080 or 1280×720; voiceover or subtitles is enough.

| Time | Screen | Narration (English or Chinese) |
|------|--------|--------------------------------|
| 0:00–0:20 | Browser on **Analytics / Forecast**, site `12117500`, parameter discharge `00060` | Puget Sound USGS site; short multi-step forecast for shift review |
| 0:20–0:50 | Forecast curve loads; switch to turbidity `63680` or 12h risk card if present | Forecast service is standalone Python FastAPI; Java gateway proxies |
| 0:50–1:40 | Open **Copilot**; ask the **3 questions** below (can cut into three short answers) | Show RAG + tool calls (local Ollama must be running) |
| 1:40–2:00 | Alert list or map thumbnail + repo README “For reviewers / HR” and GitHub link | Wrap-up: monitoring, forecast, alerts, optional AI ops assistant |

### Three recommended Copilot demo questions

1. **Ops docs (RAG)**: `What is Phase B? How does recommend_alert relate to 12h risk?`
2. **Live data (tools)**: `What is the current turbidity state for site 12117500?`
3. **Mixed (RAG + tools)**: `Why might site 12117500 recommend_alert? What does the Phase B doc say?`

(Chinese questions work too; Copilot system prompts favor English for ops-doc answers.)

**Upload**: YouTube unlisted or Bilibili; paste the link in README under **For reviewers / HR**.

---

## 4. Screenshots

Suggested static images for reviewers:

```
docs/screenshots/
  01-analytics-forecast.png
  02-turbidity-risk.png
  03-copilot-panel.png
  04-alerts-map.png
  05-architecture-snippet.png   # optional: README architecture diagram
```

- The repo includes `docs/screenshots/.gitkeep`; **redact** internal URLs, secrets, and real employee info before committing PNGs.
- If you prefer not to store large images in Git, commit **3–5 compressed images** and put the rest on the video platform.

---

## 5. Safe push checklist

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
- Internal planning / interview Markdown (`ai_service/plan/`, `*implementation*`, etc.)

**Before first public push**:

```bash
# If large files were committed historically, remove from index only (keeps local files)
git rm -r --cached ai_service/reports/ 2>/dev/null || true
git rm -r --cached ai_service/plan/ 2>/dev/null || true
git rm --cached ai_service/models/*.pkl 2>/dev/null || true
git status   # confirm only source, config, DEMO, screenshot placeholders, etc.
git push -u origin main
```

In GitHub **Settings → General**, you can enable *Private vulnerability reporting*; **do not** put production database passwords in a public README.

---

## 6. Blurb for README (copy-paste)

In root [README.md](./README.md) under **For reviewers / HR**:

> **For reviewers / HR**  
> This is a water-quality monitoring demo (USGS IV, short-horizon forecast, alerts, optional RAG copilot).  
> **No cloud spend required** for core UI: use Docker Compose per `monitor_business/README.md`.  
> Copilot needs a local [Ollama](https://ollama.com) or your own LLM API key.  
> **2-min walkthrough video**: \<your link\> · **Screenshots**: `docs/screenshots/` · **Details**: [DEMO.md](./DEMO.md)

---

## 7. FAQ

**Q: Will a public repo leak training data?**  
A: `.gitignore` excludes `data/`, `reports/`, and `.pkl`; only source and minimal ops doc `ai_service/docs/turbidity_operations.md` are committed.

**Q: Copilot does nothing after clone?**  
A: Check `curl http://localhost:8000/assistant/health` (or the project’s health endpoint); confirm Ollama is running and run `python -m assistant.rag.indexer --rebuild`.

**Q: Can I demo entirely in the cloud?**  
A: Yes, but it is no longer $0; you need a cloud host and optionally OpenAI API. For HR review, **local Docker + video for Copilot** is recommended.

---

*Document version: keep in sync with repo `.gitignore` and `DEFAULT_RAG_DOC_REL_PATHS` in `assistant/config.py`.*
