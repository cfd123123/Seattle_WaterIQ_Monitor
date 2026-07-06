# Water Quality & Environmental Monitoring Platform

An integrated system for **monitoring data ingestion, short-horizon forecasting, alerting, and station management** for operations and engineering teams. The typical data scenario is **USGS NWIS instantaneous values (IV)** (e.g., Puget Sound area sites); the architecture supports extensible sites and parameters.

---

## Requirements & Capabilities

### 1. Forecasting

**Goal**: Given historical IV time series, produce **multi-hour ahead** value trends for a specified site and parameter to support shift review and situational awareness (**decision support** — not a replacement for official hydrologic forecasts).

**Implementation highlights**:

- **Data**: Merged USGS **IV CSV** (site, time, multi-parameter columns); build **hourly series** by `site_no` and `parameter_cd` (e.g., discharge `00060`, turbidity `63680`).
- **Models**: Production MVP uses **lag features + Ridge recursive multi-step extrapolation** (`ai_service` / `forecast_engine`); the repo also includes **LightGBM direct multi-step** experiments and tuning scripts (walk-forward, sMAPE) for research and model selection.
- **Output**: Forecast values, **availability** flags (e.g., insufficient history), and optional series with a historical window for charting.
- **Integration**: The business backend calls the **Python AI service (FastAPI)** over HTTP for forecasting and IV maintenance in a separate process, keeping the business API responsive.

### 2. Alerting

**Goal**: Detect **anomalies or threshold breaches** from real-time or near-real-time IV using rules and model assistance; produce **acknowledgeable, closable** alerts with list, filter, and optional stats/map views.

**Implementation highlights**:

- **Example sources**: **Dual-point turbidity thresholds**, **single-site single-parameter** anomaly detection (e.g., on-demand Isolation Forest); can combine with forecasts or business rules (per enabled rule codes).
- **Lifecycle**: Alerts flow **new → acknowledged → closed**, persisted for audit and linked to sites, parameters, and inspection/run records.
- **Division of labor**: Forecasting emphasizes **trend anticipation**; alerting emphasizes **breach/anomaly**; the two complement each other with clear responsibilities.
- **Heavy jobs**: Full IV refresh, batch forecasting, etc. can run as **async tasks** to avoid blocking online reads/writes.

### Other: Stations & Foundation

- **Station management**: **Create / edit / delete (or deactivate)** monitoring sites; maintain codes, display names, geo location, optional external IDs (e.g., USGS 8-digit site numbers); optional NWIS **site validation** when integrated.
- **Data maintenance**: Pull and merge IV from NWIS into local data files; default site config and extensible site lists.
- **Overview**: Stats dashboard, distribution and trends, **map** summaries for sites and alerts (admin console).
- **Engineering layout**: Separated frontend/backend, optional **API gateway** and **Docker Compose** orchestration, observability stack (see docs under `monitor_business`).

---

## Repository Layout (Brief)

| Directory | Description |
|-----------|-------------|
| `ai_service/` | Python: FastAPI, IV maintenance, forecasting, thresholds, anomaly inference, and utility scripts |
| `monitor_business/` | Business backend (Spring Boot), frontend (Vite + React), gateway, and orchestration docs |

For local startup, Docker, and phased rollout details, see **[monitor_business/README.md](./monitor_business/README.md)** and **[monitor_business/BUSINESS.md](./monitor_business/BUSINESS.md)** (business overview).

---

## For reviewers / HR

A **near-zero-cost** demo guide for recruiters and technical reviewers (public GitHub, 2-minute screen-recording script, screenshot folder, features that work without an LLM) is in **[DEMO.md](./DEMO.md)**.

| Resource | Description |
|----------|-------------|
| [DEMO.md](./DEMO.md) | Reviewer demo guide and safe push checklist |
| `docs/screenshots/` | Suggested 3–5 admin-console screenshots (forecast page, Copilot, alerts/map) |
| Demo video (optional) | Record per DEMO §3, then add the link in this table or at the end of DEMO |

**Verifiable without an LLM**: After Docker Compose startup — **forecast curves**, **turbidity monitoring**, **alerts and map**.  
**Copilot / AI explanations** require local [Ollama](https://ollama.com) or your own API key (see `ai_service/.env.example`).
