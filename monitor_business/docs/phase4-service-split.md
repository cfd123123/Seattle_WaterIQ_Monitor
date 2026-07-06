# Phase 4 Service Split Guide

This document records the current Phase 4 split in a runnable, demo-friendly form.

## Services and Boundaries

- `monitor-service`: Spring business API, task submission/query, Redis cache, MQ producer.
- `task-worker`: Spring worker process (same image, `worker` profile), MQ consumer/executor.
- `ai-inference-service`: Python FastAPI inference/maintenance service.
- `api-gateway`: **Spring Cloud Gateway** unified ingress/routing（工程目录 `api-gateway/`）。

## Compose File

- `monitor_business/docker-compose.yml`（`monitor-service` / `task-worker` 构建上下文为 `backend/`；`api-gateway` 为 `api-gateway/`；AI 为仓库根目录 `ai_service/`）

## Start (all in Docker)

```bash
cd monitor_business
docker compose up -d --build postgres redis rabbitmq ai-inference-service monitor-service task-worker api-gateway
```

可选一并起可观测栈：`docker compose up -d tempo prometheus grafana`（Prometheus 默认抓取 `monitor-service:8080`，需业务容器已加入同一 Compose网络）。

## Repository layout

- Java/Spring code lives in `monitor_business/backend/` (not mixed with `frontend/`).

## Endpoints

- Unified gateway: `http://localhost:8080`（Spring Cloud Gateway）
  - Java APIs: `/api/*` → `monitor-service:8080`
  - AI（可选前缀）: `/ai/*` → `ai-inference-service:8000`（会去掉前缀 `/ai`，例如 `/ai/health` → AI 的 `/health`）
  - 网关自身健康: `http://localhost:8080/actuator/health`
  - **monitor-service** 的 Actuator（含 Prometheus 等）请直连: `http://localhost:18080/actuator/...`
- Direct debug ports:
  - `monitor-service`: `http://localhost:18080`
  - `task-worker` health: `http://localhost:18088/actuator/health`
  - `ai-inference-service`: `http://localhost:8000/health`
  - RabbitMQ console: `http://localhost:15672`

## Why this is Phase 4-aligned

- Services deploy independently (API, worker, AI, gateway separated).
- Boundaries are explicit and failure isolation is observable.
- Keeps shared Postgres initially, matching the plan's data strategy.

## Notes

- For DLQ operations and failure handling, still use `docs/mq-runbook.md`.
