#!/usr/bin/env python3
"""
随机生成一条符合 POST /api/check 的请求体，调用 monitor_business 完成一次检测。

依赖：本机已启动 Spring Boot（默认 http://localhost:8080），且 AI 服务可访问（见 application.properties 中 water.ai.base-url）。
用法：
  python3 scripts/generate_and_check.py --station-code 你在库里登记过的站点编码
  python3 scripts/generate_and_check.py --station-code puget_12117000 --base-url http://127.0.0.1:8080
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import urllib.error
import urllib.request


def build_random_payload() -> dict:
    """在合理范围内随机 11 项指标（与 api.md / WaterQualityRequest 字段名一致）。"""
    return {
        "Water_Temperature_C": round(random.uniform(5.0, 32.0), 2),
        "pH": round(random.uniform(6.2, 8.8), 2),
        "Dissolved_Oxygen_mg_L": round(random.uniform(3.0, 12.0), 2),
        "Conductivity_uS_cm": round(random.uniform(120.0, 900.0), 2),
        "Turbidity_NTU": round(random.uniform(0.5, 25.0), 2),
        "Nitrate_mg_L": round(random.uniform(0.05, 8.0), 3),
        "Ammonia_N_mg_L": round(random.uniform(0.02, 3.0), 3),
        "Total_Phosphorus_mg_L": round(random.uniform(0.02, 0.35), 3),
        "COD_mg_L": round(random.uniform(8.0, 90.0), 2),
        "BOD_mg_L": round(random.uniform(1.0, 25.0), 2),
        "Heavy_Metals_Pb_ug_L": round(random.uniform(0.5, 45.0), 2),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="随机生成一条水质数据并调用 /api/check")
    parser.add_argument(
        "--base-url",
        default="http://localhost:8080",
        help="monitor_business 根地址（默认 http://localhost:8080）",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=None,
        help="可选随机种子，便于复现同一组指标",
    )
    parser.add_argument(
        "--station-code",
        required=True,
        help="须已在 monitor_station 中登记的 station_code（检测必填）",
    )
    args = parser.parse_args()

    if args.seed is not None:
        random.seed(args.seed)

    url = args.base_url.rstrip("/") + "/api/check"
    payload = build_random_payload()
    payload["stationCode"] = args.station_code.strip()
    body = json.dumps(payload).encode("utf-8")

    print("请求体:", json.dumps(payload, ensure_ascii=False, indent=2))
    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            raw = resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        print("HTTP", e.code, file=sys.stderr)
        print(e.read().decode("utf-8", errors="replace"), file=sys.stderr)
        return 1
    except urllib.error.URLError as e:
        print("请求失败:", e.reason, file=sys.stderr)
        print("请确认 monitor_business 与 AI 服务已启动。", file=sys.stderr)
        return 1

    print("响应:", raw)
    try:
        data = json.loads(raw)
        level = (data.get("data") or {}).get("pollution_level")
        if level:
            print("污染等级:", level)
    except json.JSONDecodeError:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
