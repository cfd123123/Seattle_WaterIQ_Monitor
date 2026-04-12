#!/usr/bin/env bash
# 需先在 application.properties 中设置 water.demo-seed=true 并重启 Spring，再执行本脚本。
set -euo pipefail
BASE="${1:-http://127.0.0.1:8080}"
echo "POST $BASE/api/demo/seed-fake-alerts"
curl -sS -X POST "$BASE/api/demo/seed-fake-alerts" -H 'Content-Type: application/json' | python3 -m json.tool 2>/dev/null || curl -sS -X POST "$BASE/api/demo/seed-fake-alerts" -H 'Content-Type: application/json'
echo
