# Business Overview

This document explains **what the repository does from a business perspective**: audience, problems solved, and core capabilities. Technical details and APIs live in local design docs under `monitor_business/docs/` (not published to the public repo).

---

## 1. Product scope

This project is a **water-quality and environmental monitoring business system** (working name: **water business monitoring / monitor_business**) for **operations and engineering teams**: manage **monitoring stations**, pull and maintain **USGS NWIS instantaneous values (IV)**, run **short-horizon forecasts and anomaly detection** with rules and models, and produce **acknowledgeable, closable alerts**, plus **statistics, maps, and observability** for daily monitoring and troubleshooting.

The current implementation centers on **USGS Puget Sound area sites and IV data** as the reference scenario; sites and parameters are extensible beyond a single river or fixed CSV.

---

## 2. Business problems addressed

| Problem | Business approach |
|---------|-------------------|
| Scattered monitoring points and multiple data sources (NWIS, local IV files, etc.) | Maintain **station master data** (codes, coordinates, optional USGS `site_no`) shared with IV and forecasting. |
| Need to know “is it abnormal now, should we alert?” | Apply **dual-point turbidity thresholds**, **single-parameter anomaly (IF)**, and similar rules on **IV time series**; persist **alert events** with acknowledge and close. |
| Need short-term trend context for decisions | **Short-horizon forecasting** (Java proxies Python) reads IV history and returns values plus availability metadata. |
| Heavy jobs must not block online APIs | **Batch forecast, IV refresh**, etc. via **async tasks + message queue** on a dedicated worker with queryable status. |
| Need overview and traceability | **Stats overview / distribution / trends**, **map summaries** for sites and alerts, optional tie-in to **metrics, logs, and tracing**. |

---

## 3. Core business entities (domain language)

- **Monitoring station (`monitor_station`)**: A business “site” with station code, display name, location, and optional external source ID (e.g., USGS 8-digit site number).
- **Alert (`alert_event`)**: A lifecycle record (new → acknowledged → closed) with severity, rule code, description, etc.; linked to sites, USGS parameters, and business rules.
- **USGS single-parameter inspection run (`usgs_site_param_run`)**: Persisted run for one site and parameter (e.g., discharge `00060`, turbidity `63680`) — IV inspection and/or anomaly judgment for stats and trends.
- **Async task (`async_task`)**: State machine for IV refresh, batch forecast, etc. (queued, running, success/failure) for frontend polling or ops queries.

A historical “generic water-quality fact table” path existed; **the current product line is USGS / stations / alerts / forecasting**.

---

## 4. Main capabilities (user-visible)

1. **Station management**: Register and maintain sites; optional alignment with NWIS site existence checks.
2. **IV data refresh**: Pull IV from NWIS, merge into CSV; optional post-refresh actions such as **turbidity threshold scan**.
3. **Alerts**: List/filter, acknowledge, close; multiple sources (turbidity thresholds, forecast thresholds, USGS parameter anomaly, etc., per enabled rules).
4. **Short-horizon forecasting**: Request forecasts by site, parameter, and horizon steps.
5. **Statistics and map**: Overview, distribution, daily trends for USGS alert/inspection stats; map summaries for sites and alerts.
6. **Auto-forecast (optional)**: When enabled, scheduled batch forecast tasks for registered stations.

**AI service (`ai_service`)** handles **rule scoring, forecasting, IV pull/maintenance, and some anomaly detection**; Java owns orchestration, auth, persistence, tasks, and external APIs.

---

## 5. Deployment and access (brief)

- **Development**: Frontend on local Vite, backend on Spring Boot, AI on Python; database **PostgreSQL** (or H2).
- **Containers**: **Gateway** as single entry, `monitor-service` for business APIs, `task-worker` for queue consumption, **ai-inference-service** for inference and maintenance — see [monitor_business/README.md](./README.md) for local startup.

---

## 6. Relationship to roadmap docs

Phased evolution (async, cache, MQ, service split, observability) is documented in local files under `monitor_business/docs/`. This file is a **business summary** only; it does not replace API contracts or schema docs.

---

*For a fixed product name in external messaging, add one line at the top here and keep it aligned with the root README.*
