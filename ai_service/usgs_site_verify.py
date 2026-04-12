"""
调用 USGS NWIS Site Service，判断站点号是否在档案中存在。

接口文档：https://waterservices.usgs.gov/rest/Site-Service.html
"""
from __future__ import annotations

import re
import urllib.error
import urllib.request


def nwis_site_exists(site_no: str) -> tuple[bool, str | None]:
    """
    查询 NWIS Site File，判断 ``site_no`` 是否有记录。

    :return: (是否存在, 不存在或出错时的说明；存在时为 None)
    """
    raw = (site_no or "").strip()
    if not raw:
        return False, "USGS 站点号（external_id）不能为空"
    if not re.fullmatch(r"\d{8,15}", raw):
        return False, "USGS 站点号须为 8–15 位数字（NWIS site_no）"
    url = (
        "https://waterservices.usgs.gov/nwis/site/"
        f"?sites={raw}&siteOutput=Basic&siteStatus=all"
    )
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "water-monitor/1.0 (environment_project)"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=25) as resp:
            text = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return False, "NWIS 中未找到该站点号（站点不存在或查询无结果）"
        try:
            body = e.read().decode("utf-8", errors="replace")
        except Exception:
            body = ""
        return False, f"NWIS 站点查询失败（HTTP {e.code}）: {body[:200]}"
    except Exception as e:
        return False, f"NWIS 站点查询失败: {e}"

    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("agency_cd"):
            continue
        # 列宽说明行，如 "5s 15s 50s..."
        if re.match(r"^\d+s\s", line):
            continue
        parts = line.split()
        if len(parts) >= 2 and parts[0] == "USGS" and parts[1] == raw:
            return True, None

    return False, "NWIS 返回中未解析到该站点记录（请核对站点号）"


def nwis_site_verify_json(site_no: str) -> dict:
    """供 FastAPI 返回 JSON。"""
    exists, message = nwis_site_exists(site_no)
    return {
        "exists": exists,
        "site_no": (site_no or "").strip(),
        "message": message,
    }
