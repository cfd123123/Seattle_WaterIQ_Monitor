# AI inference service (FastAPI + uvicorn); matches ai-inference-service in monitor_business/docker-compose.
FROM python:3.11-slim-bookworm

WORKDIR /app

# System packages:
# - build-essential: fallback compilers in case any dep lacks a prebuilt wheel
# - libgomp1: OpenMP runtime required by LightGBM at import/runtime on Debian-based images
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential libgomp1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

COPY . .

# Runtime data dir (e.g. IV CSVs); compose can mount a volume here for persistence.
RUN mkdir -p /app/data

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
