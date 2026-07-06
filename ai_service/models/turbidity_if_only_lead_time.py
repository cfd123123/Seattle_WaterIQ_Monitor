"""
IF-only lead-time analysis on turbidity holdout (site 12117500).

At anchor hour t (tier NORMAL on quality hours), measure how often alert tiers
(WATCH | HIGH | CRITICAL) appear in (t, t+H] for IF-alert vs control populations.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Final

import numpy as np
import pandas as pd

from .backtest_turbidity_exog_ridge_lgbm import _split_index_for_holdout
from .turbidity_holdout_eval import (
    _holdout_mask_from_split,
    _load_hourly_states,
    _load_thresholds,
    _resolve_features_csv,
)
from .turbidity_risk_forecast_backtest import max_quality_tier
from .turbidity_state_monitoring import (
    WARNING_HORIZONS,
    is_gap_tier,
    is_quality_alert_tier,
    label_alert_tier,
    load_features,
)
from .turbidity_tier_vs_if_eval import (
    DEFAULT_REPORT_DIR,
    build_calendar_y_series,
    score_if_on_holdout_hours,
    tier_is_alert,
)
from .turbidity_tier_vs_multivar_if_eval import (
    MULTIVAR_MODEL_VERSION,
    build_multivar_matrix,
    score_multivar_if_on_holdout_hours,
)

DEFAULT_LEAD_HORIZONS: Final[tuple[int, ...]] = (6, 12, 24)
DEFAULT_MIN_VALID_FUTURE_HOURS: Final[int] = 6

UPGRADE_RATES_PNG: Final[str] = "if_only_lead_time_upgrade_rates.png"
UPLIFT_PNG: Final[str] = "if_only_lead_time_uplift.png"

# Stakeholder-facing chart labels (Chinese).
_POP_LABELS_ZH: Final[dict[str, str]] = {
    "if_only_univariate": "IF-only（单变量）",
    "if_only_multivariate": "IF-only（多变量）",
    "control_univariate": "对照（单变量 IF 正常）",
    "control_multivariate": "对照（多变量 IF 正常）",
    "tier_only_univariate": "参考 tier-only",
}
_POP_COLORS: Final[dict[str, str]] = {
    "if_only_univariate": "#e76f51",
    "if_only_multivariate": "#f4a261",
    "control_univariate": "#2a6f97",
    "control_multivariate": "#457b9d",
    "tier_only_univariate": "#6c757d",
}
_UPGRADE_RATE_POP_ORDER: Final[tuple[str, ...]] = (
    "if_only_univariate",
    "if_only_multivariate",
    "control_univariate",
    "control_multivariate",
    "tier_only_univariate",
)


def _min_valid_future_for_horizon(horizon_h: int, *, default_min: int = DEFAULT_MIN_VALID_FUTURE_HOURS) -> int:
    """Require at least ``default_min`` valid future hours, capped by the horizon length."""
    return min(int(default_min), int(horizon_h))


def _future_upgrade_in_window(
    tiers: pd.Series,
    y: pd.Series,
    idx_t: int,
    *,
    horizon_h: int,
    min_valid_future_hours: int,
) -> dict[str, Any] | None:
    """
    Labels for (t, t+horizon_h]: upgrade if any quality alert tier appears.

    Only hours with finite y and non-gap tier count toward validity and upgrade.
    Returns None when the window has too few valid future hours.
    """
    n = len(tiers)
    h_end = min(int(horizon_h), n - 1 - idx_t)
    if h_end < 1:
        return None

    quality_tiers: list[str] = []
    future_y: list[float] = []
    for h in range(1, h_end + 1):
        ti = idx_t + h
        y_val = float(y.iloc[ti])
        if not np.isfinite(y_val):
            continue
        tname = str(tiers.iloc[ti])
        if is_gap_tier(tname):
            continue
        quality_tiers.append(tname)
        future_y.append(y_val)

    if len(quality_tiers) < int(min_valid_future_hours):
        return None

    max_t = max_quality_tier(quality_tiers)
    upgraded = bool(max_t is not None and is_quality_alert_tier(max_t))
    y_anchor = float(y.iloc[idx_t])
    max_ntu = float(max(future_y)) if future_y else None
    delta_ntu = round(max_ntu - y_anchor, 6) if max_ntu is not None and np.isfinite(y_anchor) else None

    return {
        "upgraded": upgraded,
        "max_tier": max_t,
        "n_valid_future_hours": len(quality_tiers),
        "future_horizon_max": h_end,
        "max_ntu_future": round(max_ntu, 6) if max_ntu is not None else None,
        "delta_ntu_from_anchor": delta_ntu,
    }


def _summarize_ntu_secondary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    deltas = [r["delta_ntu_from_anchor"] for r in rows if r.get("delta_ntu_from_anchor") is not None]
    max_ntus = [r["max_ntu_future"] for r in rows if r.get("max_ntu_future") is not None]
    if not deltas:
        return {
            "n_with_future_ntu": 0,
            "mean_delta_ntu": None,
            "median_delta_ntu": None,
            "mean_max_ntu": None,
            "median_max_ntu": None,
        }
    d_arr = np.asarray(deltas, dtype=float)
    m_arr = np.asarray(max_ntus, dtype=float)
    return {
        "n_with_future_ntu": int(len(deltas)),
        "mean_delta_ntu": round(float(d_arr.mean()), 6),
        "median_delta_ntu": round(float(np.median(d_arr)), 6),
        "mean_max_ntu": round(float(m_arr.mean()), 6),
        "median_max_ntu": round(float(np.median(m_arr)), 6),
    }


def _lead_time_for_population(
    anchor_positions: np.ndarray,
    tiers: pd.Series,
    y: pd.Series,
    *,
    horizons: tuple[int, ...],
    min_valid_future_hours: int,
) -> dict[str, Any]:
    """Upgrade rates and NTU secondary stats per horizon for one anchor population."""
    out: dict[str, Any] = {}
    for h in horizons:
        min_valid = _min_valid_future_for_horizon(h, default_min=min_valid_future_hours)
        upgraded_n = 0
        anchor_rows: list[dict[str, Any]] = []
        skipped_insufficient = 0

        for pos in anchor_positions:
            lab = _future_upgrade_in_window(
                tiers,
                y,
                int(pos),
                horizon_h=h,
                min_valid_future_hours=min_valid,
            )
            if lab is None:
                skipped_insufficient += 1
                continue
            anchor_rows.append(lab)
            if lab["upgraded"]:
                upgraded_n += 1

        n_anchors = len(anchor_rows)
        rate = round(upgraded_n / n_anchors, 6) if n_anchors else None
        out[str(h)] = {
            "horizon_h": h,
            "min_valid_future_hours": min_valid,
            "n_anchors": n_anchors,
            "n_upgraded": upgraded_n,
            "upgrade_rate": rate,
            "n_skipped_insufficient_future": skipped_insufficient,
            "ntu_secondary": _summarize_ntu_secondary(anchor_rows),
        }
    return out


def _uplift_vs_control(
    populations: dict[str, Any],
    *,
    alert_key: str,
    control_key: str = "control",
) -> dict[str, Any]:
    """Rate difference alert_pop - control for each horizon."""
    alert = populations.get(alert_key) or {}
    control = populations.get(control_key) or {}
    out: dict[str, Any] = {}
    for h_str, block in alert.items():
        if h_str not in control:
            continue
        a_rate = block.get("upgrade_rate")
        c_rate = control[h_str].get("upgrade_rate")
        if a_rate is None or c_rate is None:
            uplift = None
        else:
            uplift = round(float(a_rate) - float(c_rate), 6)
        out[h_str] = {
            "upgrade_rate_alert": a_rate,
            "upgrade_rate_control": c_rate,
            "uplift_absolute": uplift,
            "n_anchors_alert": block.get("n_anchors"),
            "n_anchors_control": control[h_str].get("n_anchors"),
        }
    return out


def _configure_matplotlib() -> None:
    """Use headless backend, repo font cache, and a CJK-capable sans font when available."""
    mpl_dir = Path(__file__).resolve().parent.parent / ".mplconfig"
    if mpl_dir.is_dir():
        os.environ.setdefault("MPLCONFIGDIR", str(mpl_dir))
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.font_manager as fm

    for family in (
        "PingFang SC",
        "Hiragino Sans GB",
        "Arial Unicode MS",
        "Songti SC",
        "STHeiti",
        "DejaVu Sans",
    ):
        try:
            fm.findfont(family, fallback_to_default=False)
        except (ValueError, OSError):
            continue
        matplotlib.rcParams["font.sans-serif"] = [family, "DejaVu Sans"]
        matplotlib.rcParams["axes.unicode_minus"] = False
        break


def _horizon_keys(result: dict[str, Any]) -> tuple[str, ...]:
    defs = result.get("definitions") or {}
    raw = defs.get("horizons_h") or [6, 12, 24]
    return tuple(str(int(h)) for h in raw)


def _upgrade_rate_pct(pop_block: dict[str, Any], horizon: str) -> float | None:
    hb = (pop_block or {}).get(horizon) or {}
    rate = hb.get("upgrade_rate")
    if rate is None:
        return None
    return float(rate) * 100.0


def plot_if_only_lead_time_upgrade_rates(
    result: dict[str, Any],
    out_png: Path,
    *,
    include_tier_only: bool = True,
) -> bool:
    """Grouped bar chart: tier-upgrade rate by population and horizon (holdout)."""
    try:
        _configure_matplotlib()
        import matplotlib.pyplot as plt
    except ImportError:
        return False

    pops = result.get("populations") or {}
    horizons = _horizon_keys(result)
    pop_keys = [k for k in _UPGRADE_RATE_POP_ORDER if k in pops]
    if include_tier_only is False:
        pop_keys = [k for k in pop_keys if k != "tier_only_univariate"]
    if not pop_keys or not horizons:
        return False

    n_h = len(horizons)
    n_p = len(pop_keys)
    x = np.arange(n_h, dtype=float)
    width = 0.8 / max(n_p, 1)

    fig, ax = plt.subplots(figsize=(11, 5.5))
    for i, key in enumerate(pop_keys):
        rates = [_upgrade_rate_pct(pops.get(key) or {}, h) for h in horizons]
        heights = [r if r is not None else 0.0 for r in rates]
        offset = (i - (n_p - 1) / 2.0) * width
        bars = ax.bar(
            x + offset,
            heights,
            width=width * 0.92,
            label=_POP_LABELS_ZH.get(key, key),
            color=_POP_COLORS.get(key, "#888888"),
        )
        for bar, raw in zip(bars, rates):
            if raw is None:
                continue
            ax.text(
                bar.get_x() + bar.get_width() / 2.0,
                bar.get_height() + 0.8,
                f"{raw:.1f}%",
                ha="center",
                va="bottom",
                fontsize=7,
            )

    ax.set_ylabel("档位升级率 (%)")
    ax.set_xlabel("前瞻窗口")
    site = result.get("site_no") or ""
    ax.set_title(f"IF-only 提前量：锚点后档位升级率（holdout，站点 {site}）")
    ax.set_xticks(x)
    ax.set_xticklabels([f"{h}h" for h in horizons])
    ymax = max(
        (
            _upgrade_rate_pct(pops.get(k) or {}, h) or 0.0
            for k in pop_keys
            for h in horizons
        ),
        default=0.0,
    )
    ax.set_ylim(0, min(105.0, ymax * 1.18 + 5.0))
    ax.legend(loc="upper left", fontsize=8, framealpha=0.92)
    ax.grid(axis="y", alpha=0.25)
    fig.tight_layout()
    out_png.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_png, dpi=120, bbox_inches="tight")
    plt.close(fig)
    return True


def plot_if_only_lead_time_uplift(result: dict[str, Any], out_png: Path) -> bool:
    """Grouped bar chart: IF-only uplift vs control (percentage points) by horizon."""
    try:
        _configure_matplotlib()
        import matplotlib.pyplot as plt
    except ImportError:
        return False

    uplift = result.get("uplift_vs_control") or {}
    horizons = _horizon_keys(result)
    tracks = (
        ("univariate", "IF-only 单变量 vs 对照"),
        ("multivariate", "IF-only 多变量 vs 对照"),
    )
    series: list[tuple[str, list[float | None]]] = []
    for track_key, label in tracks:
        block = uplift.get(track_key) or {}
        pp = []
        for h in horizons:
            ub = block.get(h) or {}
            u = ub.get("uplift_absolute")
            pp.append(float(u) * 100.0 if u is not None else None)
        if any(v is not None for v in pp):
            series.append((label, pp))
    if not series or not horizons:
        return False

    n_h = len(horizons)
    n_s = len(series)
    x = np.arange(n_h, dtype=float)
    width = 0.35 if n_s > 1 else 0.55
    colors = ("#e76f51", "#2a6f97")

    fig, ax = plt.subplots(figsize=(8, 5))
    for i, (label, pp_vals) in enumerate(series):
        heights = [v if v is not None else 0.0 for v in pp_vals]
        offset = (i - (n_s - 1) / 2.0) * width if n_s > 1 else 0.0
        bars = ax.bar(
            x + offset,
            heights,
            width=width * 0.9,
            label=label,
            color=colors[i % len(colors)],
        )
        for bar, raw in zip(bars, pp_vals):
            if raw is None:
                continue
            ax.text(
                bar.get_x() + bar.get_width() / 2.0,
                bar.get_height() + 0.4,
                f"+{raw:.1f} pp",
                ha="center",
                va="bottom",
                fontsize=8,
            )

    ax.set_ylabel("相对对照 uplift（百分点）")
    ax.set_xlabel("前瞻窗口")
    site = result.get("site_no") or ""
    ax.set_title(f"IF-only 提前量：相对对照 uplift（holdout，站点 {site}）")
    ax.set_xticks(x)
    ax.set_xticklabels([f"{h}h" for h in horizons])
    ax.axhline(0, color="#333333", linewidth=0.8, alpha=0.5)
    ax.legend(loc="upper left", fontsize=8)
    ax.grid(axis="y", alpha=0.25)
    fig.tight_layout()
    out_png.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_png, dpi=120, bbox_inches="tight")
    plt.close(fig)
    return True


def write_if_only_lead_time_plots(
    result: dict[str, Any],
    report_dir: Path,
    *,
    include_tier_only: bool = True,
) -> dict[str, str]:
    """Write stakeholder PNG charts; returns relative filenames written."""
    report_path = Path(report_dir)
    written: dict[str, str] = {}
    rates_png = report_path / UPGRADE_RATES_PNG
    if plot_if_only_lead_time_upgrade_rates(
        result, rates_png, include_tier_only=include_tier_only
    ):
        written["upgrade_rates_png"] = UPGRADE_RATES_PNG
    uplift_png = report_path / UPLIFT_PNG
    if plot_if_only_lead_time_uplift(result, uplift_png):
        written["uplift_png"] = UPLIFT_PNG
    return written


def load_if_only_lead_time_json(json_path: Path) -> dict[str, Any]:
    path = Path(json_path)
    if not path.is_file():
        raise FileNotFoundError(f"IF-only lead-time JSON not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def format_if_only_lead_time_md(
    result: dict[str, Any],
    *,
    plot_paths: dict[str, str] | None = None,
) -> str:
    defs = result.get("definitions") or {}
    holdout = result.get("holdout") or {}
    pops = result.get("populations") or {}
    uplift = result.get("uplift_vs_control") or {}

    lines = [
        "# IF-only lead-time: tier upgrade after anchor (holdout)",
        "",
        f"- Site: `{result.get('site_no')}`",
        f"- Tier model: `{result.get('tier_model_version')}`",
        f"- Holdout: {holdout.get('start_utc')} → {holdout.get('end_utc')}",
        f"- Tier source: {result.get('tier_source')}",
        "",
        "## Definitions",
        "",
        f"- Anchor population: {defs.get('anchor_population')}",
        f"- Upgrade in (t, t+H]: {defs.get('upgrade_definition')}",
        f"- Min valid future hours: {defs.get('min_valid_future_hours_rule')}",
        f"- Horizons (h): {defs.get('horizons_h')}",
        "",
        "## Holdout counts",
        "",
        f"| Segment | Hours |",
        f"|---------|------:|",
        f"| Grid (holdout) | {holdout.get('n_grid_hours')} |",
        f"| Finite y | {holdout.get('n_finite_y')} |",
        f"| Quality (finite y, non-gap) | {holdout.get('n_quality_hours')} |",
        f"| Three-way (uni + multivar IF available) | {holdout.get('n_three_way_hours')} |",
        "",
        "## Upgrade rate by population",
        "",
        "| Population | H=6 rate (n) | H=12 rate (n) | H=24 rate (n) |",
        "|------------|-------------:|--------------:|--------------:|",
    ]

    pop_order = (
        "if_only_univariate",
        "if_only_multivariate",
        "control_univariate",
        "control_multivariate",
        "tier_only_univariate",
    )
    for key in pop_order:
        block = pops.get(key) or {}
        cells = []
        for h in ("6", "12", "24"):
            hb = block.get(h) or {}
            rate = hb.get("upgrade_rate")
            n = hb.get("n_anchors")
            cells.append(f"{rate} ({n})" if rate is not None else f"— ({n})")
        lines.append(f"| {key} | {cells[0]} | {cells[1]} | {cells[2]} |")

    if plot_paths:
        lines.extend(
            [
                "",
                "## Charts",
                "",
            ]
        )
        if plot_paths.get("upgrade_rates_png"):
            rel = plot_paths["upgrade_rates_png"]
            lines.append(f"![档位升级率对比]({rel})")
            lines.append("")
        if plot_paths.get("uplift_png"):
            rel = plot_paths["uplift_png"]
            lines.append(f"![相对对照 uplift]({rel})")
            lines.append("")

    lines.extend(
        [
            "",
            "## Uplift vs control (alert − control rate)",
            "",
        ]
    )
    for track, label in (
        ("univariate", "IF-only univariate vs control_univariate"),
        ("multivariate", "IF-only multivariate vs control_multivariate"),
    ):
        u = uplift.get(track) or {}
        lines.append(f"### {label}")
        lines.append("")
        for h in ("6", "12", "24"):
            ub = u.get(h) or {}
            lines.append(
                f"- H={h}: uplift={ub.get('uplift_absolute')} "
                f"(alert={ub.get('upgrade_rate_alert')}, control={ub.get('upgrade_rate_control')})"
            )
        lines.append("")

    lines.extend(
        [
            "## NTU secondary (mean ΔNTU from anchor, upgraded windows only)",
            "",
        ]
    )
    for key in ("if_only_univariate", "control_univariate"):
        block = pops.get(key) or {}
        lines.append(f"### {key}")
        for h in ("6", "12", "24"):
            sec = (block.get(h) or {}).get("ntu_secondary") or {}
            lines.append(
                f"- H={h}: mean ΔNTU={sec.get('mean_delta_ntu')}, "
                f"median ΔNTU={sec.get('median_delta_ntu')}"
            )
        lines.append("")

    return "\n".join(lines)


def run_if_only_lead_time(
    report_dir: Path,
    *,
    features_csv: Path | None = None,
    iv_csv: Path | None = None,
    holdout_fraction: float = 0.2,
    holdout_min_hours: int = 336,
    horizons_h: tuple[int, ...] = DEFAULT_LEAD_HORIZONS,
    min_valid_future_hours: int = DEFAULT_MIN_VALID_FUTURE_HOURS,
    progress_every: int = 500,
    n_jobs: int = -1,
    write_md: bool = True,
    write_plots: bool = False,
    include_tier_only: bool = True,
) -> dict[str, Any]:
    """
    Compare forward tier-upgrade rates for IF-only vs control anchors on holdout.

    Writes ``if_only_lead_time.json``, optional ``if_only_lead_time.md``, and
    optional PNG charts when ``write_plots`` is True.
    """
    from .site_param_anomaly_on_demand import MODEL_VERSION as UNIVARIATE_IF_MODEL_VERSION

    report_path = Path(report_dir)
    thresholds = _load_thresholds(report_path)
    csv_path = _resolve_features_csv(report_path, thresholds, features_csv)
    site_no = str(thresholds.get("site_no") or "12117500")

    df_raw = load_features(csv_path, use_exog_ffill=False)
    x_num = build_multivar_matrix(df_raw)
    y = build_calendar_y_series(features_csv=csv_path, iv_csv=iv_csv, site_no=site_no)
    if not y.index.equals(df_raw.index):
        raise ValueError("63680 calendar index mismatch between raw features and y series")

    n = len(y)
    max_h = max(max(horizons_h), max(WARNING_HORIZONS))
    split_info = _split_index_for_holdout(
        n,
        max_horizon=max_h,
        holdout_fraction=float(holdout_fraction),
        holdout_min_hours=int(holdout_min_hours),
        min_tuning_hours=2000,
    )
    holdout_mask = _holdout_mask_from_split(y, thresholds, split_info)

    hourly = _load_hourly_states(report_path)
    if hourly is not None and "alert_tier" in hourly.columns:
        aligned = hourly.reindex(y.index)
        if aligned["alert_tier"].notna().all():
            tiers_full = pd.Series(aligned["alert_tier"].astype(str).values, index=y.index)
            tier_source = "hourly_states.csv"
        else:
            tiers_full = label_alert_tier(y, thresholds)
            tier_source = "recomputed_from_thresholds"
    else:
        tiers_full = label_alert_tier(y, thresholds)
        tier_source = "recomputed_from_thresholds"

    holdout_ix = y.index[holdout_mask]
    y_holdout = y.loc[holdout_ix]
    y_finite = np.isfinite(pd.to_numeric(y_holdout, errors="coerce").to_numpy(dtype=float, copy=False))
    finite_ix = holdout_ix[y_finite]

    print(f"Scoring univariate IF on {len(finite_ix)} holdout hours with finite y...", flush=True)
    uni_scores = score_if_on_holdout_hours(
        y, finite_ix, progress_every=progress_every, n_jobs=n_jobs
    )
    print(
        f"Scoring multivariate IF on {len(finite_ix)} holdout hours (complete exog at t only)...",
        flush=True,
    )
    multivar_scores = score_multivar_if_on_holdout_hours(
        x_num,
        finite_ix,
        y.index,
        progress_every=progress_every,
        n_jobs=n_jobs,
    )

    tiers_finite = tiers_full.reindex(finite_ix)
    gap_mask = tiers_finite.map(is_gap_tier).to_numpy()
    quality_ix = finite_ix[~gap_mask]
    quality_tiers = tiers_finite.loc[quality_ix]

    uni_avail = uni_scores.loc[quality_ix, "if_available"].astype(bool)
    mif_avail = multivar_scores.loc[quality_ix, "mif_available"].astype(bool)
    three_ix = quality_ix[uni_avail.to_numpy() & mif_avail.to_numpy()]

    tier_s = quality_tiers.loc[three_ix]
    tier_alert = tier_s.map(tier_is_alert)
    tier_normal = ~tier_alert
    uni_alert = uni_scores.loc[three_ix, "if_is_anomaly"].astype(bool)
    uni_normal = ~uni_alert
    mif_alert = multivar_scores.loc[three_ix, "mif_is_anomaly"].astype(bool)
    mif_normal = ~mif_alert

    pos_by_time = {ts: i for i, ts in enumerate(y.index)}
    three_positions = np.asarray([pos_by_time[ts] for ts in three_ix], dtype=int)

    masks: dict[str, np.ndarray] = {
        "if_only_univariate": (tier_normal & uni_alert).to_numpy(),
        "if_only_multivariate": (tier_normal & mif_alert).to_numpy(),
        "control_univariate": (tier_normal & uni_normal).to_numpy(),
        "control_multivariate": (tier_normal & mif_normal).to_numpy(),
    }
    if include_tier_only:
        masks["tier_only_univariate"] = (tier_alert & uni_normal).to_numpy()

    populations: dict[str, Any] = {}
    pop_counts: dict[str, int] = {}
    for name, mask in masks.items():
        positions = three_positions[mask]
        pop_counts[name] = int(len(positions))
        populations[name] = _lead_time_for_population(
            positions,
            tiers_full,
            y,
            horizons=horizons_h,
            min_valid_future_hours=min_valid_future_hours,
        )

    uplift = {
        "univariate": _uplift_vs_control(
            populations, alert_key="if_only_univariate", control_key="control_univariate"
        ),
        "multivariate": _uplift_vs_control(
            populations, alert_key="if_only_multivariate", control_key="control_multivariate"
        ),
    }

    result: dict[str, Any] = {
        "spec": "turbidity_if_only_lead_time_holdout",
        "site_no": site_no,
        "tier_model_version": thresholds.get("model_version"),
        "univariate_if_model_version": UNIVARIATE_IF_MODEL_VERSION,
        "multivariate_if_model_version": MULTIVAR_MODEL_VERSION,
        "report_dir": str(report_path.resolve()),
        "features_csv": str(csv_path.resolve()),
        "iv_csv": str(iv_csv.resolve()) if iv_csv else None,
        "tier_source": tier_source,
        "definitions": {
            "anchor_population": (
                "holdout hours with finite 63680, non-gap alert_tier, "
                "univariate and multivariate IF available; anchor tier NORMAL for IF-only/control"
            ),
            "upgrade_definition": (
                "any hour in (t, t+H] with finite y and non-gap tier in WATCH | HIGH | CRITICAL"
            ),
            "min_valid_future_hours_rule": (
                f"min({min_valid_future_hours}, H) valid future quality hours required per anchor"
            ),
            "horizons_h": list(horizons_h),
            "populations": {
                "if_only_univariate": "tier NORMAL, univariate IF alert",
                "if_only_multivariate": "tier NORMAL, multivariate IF alert",
                "control_univariate": "tier NORMAL, univariate IF normal",
                "control_multivariate": "tier NORMAL, multivariate IF normal",
                "tier_only_univariate": "tier alert (WATCH+), univariate IF normal (reference)",
            },
        },
        "holdout": {
            "start_utc": str(holdout_ix.min()) if len(holdout_ix) else None,
            "end_utc": str(holdout_ix.max()) if len(holdout_ix) else None,
            "n_grid_hours": int(len(holdout_ix)),
            "n_finite_y": int(len(finite_ix)),
            "n_quality_hours": int(len(quality_ix)),
            "n_three_way_hours": int(len(three_ix)),
        },
        "population_anchor_counts": pop_counts,
        "populations": populations,
        "uplift_vs_control": uplift,
        "holdout_split": split_info,
    }

    report_path.mkdir(parents=True, exist_ok=True)
    (report_path / "if_only_lead_time.json").write_text(
        json.dumps(result, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    plot_paths: dict[str, str] = {}
    if write_plots:
        plot_paths = write_if_only_lead_time_plots(
            result, report_path, include_tier_only=include_tier_only
        )
        if plot_paths:
            result["chart_outputs"] = plot_paths
    if write_md:
        (report_path / "if_only_lead_time.md").write_text(
            format_if_only_lead_time_md(result, plot_paths=plot_paths or None),
            encoding="utf-8",
        )
    return result


def run_if_only_lead_time_plots_only(
    report_dir: Path,
    *,
    json_path: Path | None = None,
    write_md: bool = True,
    include_tier_only: bool = True,
) -> dict[str, Any]:
    """Regenerate PNG charts (and optional MD) from existing ``if_only_lead_time.json``."""
    report_path = Path(report_dir)
    src = Path(json_path) if json_path else report_path / "if_only_lead_time.json"
    result = load_if_only_lead_time_json(src)
    plot_paths = write_if_only_lead_time_plots(
        result, report_path, include_tier_only=include_tier_only
    )
    if plot_paths:
        result["chart_outputs"] = plot_paths
    if write_md:
        (report_path / "if_only_lead_time.md").write_text(
            format_if_only_lead_time_md(result, plot_paths=plot_paths or None),
            encoding="utf-8",
        )
    return result


def main() -> int:
    import argparse

    p = argparse.ArgumentParser(description="IF-only lead-time tier-upgrade analysis (holdout).")
    p.add_argument("--report-dir", type=Path, default=DEFAULT_REPORT_DIR)
    p.add_argument("--features-csv", type=Path, default=None)
    p.add_argument("--iv-csv", type=Path, default=None)
    p.add_argument("--holdout-fraction", type=float, default=0.2)
    p.add_argument("--holdout-min-hours", type=int, default=336)
    p.add_argument("--horizons", type=str, default="6,12,24", help="Comma-separated forward hours")
    p.add_argument("--min-valid-future-hours", type=int, default=DEFAULT_MIN_VALID_FUTURE_HOURS)
    p.add_argument("--progress-every", type=int, default=500)
    p.add_argument("--n-jobs", type=int, default=-1)
    p.add_argument("--no-md", action="store_true")
    p.add_argument("--no-tier-only", action="store_true", help="Skip tier-only reference population")
    p.add_argument(
        "--plot",
        action="store_true",
        help="Write PNG charts (upgrade rates, uplift) to report-dir",
    )
    p.add_argument(
        "--plot-only",
        action="store_true",
        help="Read existing if_only_lead_time.json and write PNGs only (skip IF scoring)",
    )
    p.add_argument(
        "--json-path",
        type=Path,
        default=None,
        help="JSON input for --plot-only (default: report-dir/if_only_lead_time.json)",
    )
    args = p.parse_args()

    report_dir = Path(args.report_dir)
    include_tier_only = not args.no_tier_only

    if args.plot_only:
        result = run_if_only_lead_time_plots_only(
            report_dir,
            json_path=args.json_path,
            write_md=not args.no_md,
            include_tier_only=include_tier_only,
        )
        plot_paths = result.get("chart_outputs") or {}
        print(format_if_only_lead_time_md(result, plot_paths=plot_paths or None))
        print()
        print(
            json.dumps(
                {
                    "mode": "plot_only",
                    "chart_outputs": plot_paths,
                    "outputs": {
                        "json": str(args.json_path or report_dir / "if_only_lead_time.json"),
                        "md": None if args.no_md else str(report_dir / "if_only_lead_time.md"),
                        "png": [str(report_dir / name) for name in plot_paths.values()],
                    },
                },
                indent=2,
                ensure_ascii=False,
            )
        )
        return 0

    horizons = tuple(int(x.strip()) for x in str(args.horizons).split(",") if x.strip())
    result = run_if_only_lead_time(
        report_dir,
        features_csv=args.features_csv,
        iv_csv=args.iv_csv,
        holdout_fraction=float(args.holdout_fraction),
        holdout_min_hours=int(args.holdout_min_hours),
        horizons_h=horizons,
        min_valid_future_hours=int(args.min_valid_future_hours),
        progress_every=int(args.progress_every),
        n_jobs=int(args.n_jobs),
        write_md=not args.no_md,
        write_plots=bool(args.plot),
        include_tier_only=include_tier_only,
    )
    plot_paths = result.get("chart_outputs") or {}
    print(format_if_only_lead_time_md(result, plot_paths=plot_paths or None))
    print()
    print(
        json.dumps(
            {
                "population_anchor_counts": result.get("population_anchor_counts"),
                "uplift_vs_control": result.get("uplift_vs_control"),
                "chart_outputs": plot_paths or None,
                "outputs": {
                    "json": str(report_dir / "if_only_lead_time.json"),
                    "md": None if args.no_md else str(report_dir / "if_only_lead_time.md"),
                    "png": [str(report_dir / name) for name in (plot_paths or {}).values()],
                },
            },
            indent=2,
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
