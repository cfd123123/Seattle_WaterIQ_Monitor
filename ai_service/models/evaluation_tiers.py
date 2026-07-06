"""
Horizon tiers and aggregates aligned with plan/evaluation_contract.md (v2).

Tier A (primary KPI for flow claims): h = 1..6
Tier B (exploratory): h = 7..12
"""

from __future__ import annotations

from typing import Any

import numpy as np

TIER_A_HORIZONS: tuple[int, ...] = (1, 2, 3, 4, 5, 6)
TIER_B_HORIZONS: tuple[int, ...] = (7, 8, 9, 10, 11, 12)
CONTRACT_REF = "plan/evaluation_contract.md v2"


def _row_ok(row: dict[str, Any]) -> bool:
    if row.get("error"):
        return False
    return "smape_pct" in row and "mae" in row


def tier_means_from_per_horizon_list(per_h: list[dict[str, Any]]) -> dict[str, Any]:
    """Build h -> row from a list of per-horizon dicts (each has key 'h')."""
    by_h: dict[int, dict[str, Any]] = {}
    for row in per_h:
        if "h" not in row:
            continue
        by_h[int(row["h"])] = row
    return tier_means_from_by_h(by_h)


def tier_means_from_by_h(by_h: dict[int, dict[str, Any]]) -> dict[str, Any]:
    def agg(tier: tuple[int, ...], prefix: str) -> dict[str, Any]:
        sm: list[float] = []
        ma: list[float] = []
        for h in tier:
            if h not in by_h:
                continue
            r = by_h[h]
            if not _row_ok(r):
                continue
            sm.append(float(r["smape_pct"]))
            ma.append(float(r["mae"]))
        if not sm:
            return {
                f"{prefix}_mean_smape_pct": None,
                f"{prefix}_mean_mae": None,
                f"{prefix}_horizons_ok": 0,
            }
        return {
            f"{prefix}_mean_smape_pct": round(float(np.mean(sm)), 6),
            f"{prefix}_mean_mae": round(float(np.mean(ma)), 6),
            f"{prefix}_horizons_ok": len(sm),
        }

    out: dict[str, Any] = {
        "evaluation_contract_ref": CONTRACT_REF,
        "tier_a_horizons": list(TIER_A_HORIZONS),
        "tier_b_horizons": list(TIER_B_HORIZONS),
    }
    out.update(agg(TIER_A_HORIZONS, "tier_a"))
    out.update(agg(TIER_B_HORIZONS, "tier_b"))
    return out


def ranking_scores_from_horizon_metrics(
    horizon_keys: list[int],
    smape_by_h: dict[int, float],
    mae_by_h: dict[int, float],
) -> dict[str, Any]:
    """
    Primary sort key: mean sMAPE over (horizon_keys ∩ tier A) if non-empty, else all keys.
    Returns tier means for any overlapping horizons present in smape_by_h.
    """
    tier_a_used = [h for h in horizon_keys if h in TIER_A_HORIZONS and h in smape_by_h]
    tier_b_used = [h for h in horizon_keys if h in TIER_B_HORIZONS and h in smape_by_h]
    all_used = [h for h in horizon_keys if h in smape_by_h]

    def mean_hs(hs: list[float]) -> float | None:
        if not hs:
            return None
        return round(float(np.mean(hs)), 6)

    sm_a = [smape_by_h[h] for h in tier_a_used]
    sm_b = [smape_by_h[h] for h in tier_b_used]
    sm_all = [smape_by_h[h] for h in all_used]
    ma_a = [mae_by_h[h] for h in tier_a_used if h in mae_by_h]
    ma_b = [mae_by_h[h] for h in tier_b_used if h in mae_by_h]
    ma_all = [mae_by_h[h] for h in all_used if h in mae_by_h]

    primary_label = "tier_a_intersection"
    primary_smape = mean_hs(sm_a)
    primary_mae = mean_hs(ma_a)
    if primary_smape is None:
        primary_label = "all_requested_horizons"
        primary_smape = mean_hs(sm_all)
        primary_mae = mean_hs(ma_all)

    return {
        "ranking_primary_mean_smape_pct": primary_smape,
        "ranking_primary_mean_mae": primary_mae,
        "ranking_primary_key": primary_label,
        "tier_a_mean_smape_pct": mean_hs(sm_a),
        "tier_a_mean_mae": mean_hs(ma_a),
        "tier_a_horizons_evaluated": len(tier_a_used),
        "tier_b_mean_smape_pct": mean_hs(sm_b),
        "tier_b_mean_mae": mean_hs(ma_b),
        "tier_b_horizons_evaluated": len(tier_b_used),
    }
