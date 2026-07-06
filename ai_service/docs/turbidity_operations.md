# Turbidity (63680) Operations and Modeling Handbook

Site: **USGS 12117500** (Cedar River near Landsburg, WA)  
Primary data: `data/features_12117500_63680_openmeteo_upstream_2022.csv` (from 2022-01-01, hourly UTC)  
Frozen thresholds: `reports/turbidity_state/12117500_v2/state_thresholds.json` (**turbidity-state-v2.1**)  
Product scope: monitoring / tiering / 12h **alert risk** (not NTU point forecast as primary KPI)

---

## 1. Requirements Checklist (REQUIREMENTS)

| ID | Requirement | Status |
|----|-------------|--------|
| R1 | Anomaly detection: water-quality tiers (v2.1) + gap tiers + 6h/12h rule alerts | Implemented |
| R2 | Data gap tiering (SENSOR_GAP / DATA_STALE) and gap reports | Implemented |
| R3 | Univariate IF vs tiers (holdout) | Implemented |
| R4 | Multivariate IF (63680 + precipitation + upstream flow) vs tiers | Implemented |
| R5 | Holdout tier evaluation (calibration month ≥70% valid) | Implemented |
| R6 | Phase A: Ridge direct 12h NTU → tier → `recommend_alert` | Implemented (backtest) |
| R7 | Phase A': 12h risk **classification** (full-tier alert_12h; no precip ffill) | Implemented (backtest) |
| R7a | **escalate_12h**: NORMAL@T only → WATCH+ within 12h (ML + flood sample weighting) | Implemented (backtest) |
| R7b | **recover_12h**: WATCH+@T → back to NORMAL within 12h (ops doc; optional stub) | Doc only |
| R8 | tier vs univariate IF vs multivariate IF (holdout comparison) | Implemented |
| R9 | **Phase B**: 12h alert risk API + Spring + frontend (not NTU curve) | Implemented |
| R10 | **Future**: rule/model alerts + LLM explanation (no change to `recommend_alert`) + Agent Q&A | Planned only |

---

## 2. R1 — Water-Quality Tiers and State Monitoring

### 2.1 Implementation Steps

1. **EDA / feature table**: confirm 63680 distribution, plateaus, and storm spikes; build Open-Meteo precipitation + upstream 12116400 flow.
2. **Threshold estimation (tuning segment only)**: P75/P90/P95/P99, 1h rise rate, absolute NTU severity lines; **calibration month** keeps only hours within tuning months with `y_valid_rate ≥ 0.70`.
3. **v2.1 tiers**: NORMAL / WATCH / HIGH / CRITICAL + gap tiers SENSOR_GAP / DATA_STALE / UNKNOWN.
4. **Legacy four states** (Normal/Rising/High/Recovering) still emitted for 6h/12h rules.
5. **API / Java / UI**: snapshot, check writes `STATE_ALERT`, scheduled scan.

### 2.2 Operational Steps

```bash
cd ai_service

# Full monitoring + artifacts (optional)
.venv/bin/python turbidity_state_monitoring.py \
  --features-csv data/features_12117500_63680_openmeteo_upstream_2022.csv \
  --out-dir reports/turbidity_state/12117500_v2

# Snapshot only (FastAPI)
curl -s -X POST http://127.0.0.1:8000/turbidity/state/snapshot \
  -H 'Content-Type: application/json' \
  -d '{"site_no":"12117500","thresholds_json_path":"reports/turbidity_state/12117500_v2/state_thresholds.json"}'
```

**Spring (8080)**

- `GET /api/usgs/turbidity-state/snapshot?siteNo=12117500`
- `POST /api/usgs/turbidity-state/check?siteNo=12117500`
- `POST /api/usgs/turbidity-state/scan`

**Key Files**

- `models/turbidity_state_monitoring.py` — core logic, `MODEL_VERSION = turbidity-state-v2.1`
- `plan/turbidity_state_monitoring.md` — product description
- Outputs: `reports/turbidity_state/12117500_v2/state_thresholds.json`, `hourly_states.csv`, `summary.json`

**Configuration**: `monitor_business/.../application.properties` → `water.turbidity-state.*`

---

## 3. R2 — Gap Tiering and Gap Reports

### 3.1 Implementation Steps

1. Mark missing and stale observations on the feature-table hourly grid (default: no new observation for >3h → DATA_STALE).
2. Summarize gap rate by year/month, longest gap, and co-occurrence with HIGH tier.
3. Emit JSON + Markdown for operations and holdout interpretation.

### 3.2 Operational Steps

```bash
cd ai_service
.venv/bin/python turbidity_gap_report.py \
  --features-csv data/features_12117500_63680_openmeteo_upstream_2022.csv \
  --thresholds-json reports/turbidity_state/12117500_v2/state_thresholds.json \
  --out-dir reports/turbidity_gap_12117500
```

**Outputs**: `reports/turbidity_gap_12117500/gap_report.json` (and `.md` if enabled)

**Code**: `models/turbidity_gap_report.py`

---

## 4. R5 — Holdout Tier Evaluation

### 4.1 Implementation Steps

1. Re-label tiers on the **holdout** window (default last 20%, ≥336h) using frozen `state_thresholds.json`.
2. Summarize tier distribution by UTC month and compare to tuning; validate calibration-month strategy.
3. Do not write back thresholds.

### 4.2 Operational Steps

```bash
cd ai_service
.venv/bin/python turbidity_holdout_eval.py \
  --thresholds-json reports/turbidity_state/12117500_v2/state_thresholds.json \
  --features-csv data/features_12117500_63680_openmeteo_upstream_2022.csv \
  --out-dir reports/turbidity_holdout_12117500
```

**Outputs**: `holdout_eval.json` / `.md`  
**Code**: `models/turbidity_holdout_eval.py`

---

## 5. R3 / R4 / R8 — Tiers vs Isolation Forest

### 5.1 Univariate IF (63680)

```bash
cd ai_service
.venv/bin/python turbidity_tier_vs_if_eval.py \
  --features-csv data/features_12117500_63680_openmeteo_upstream_2022.csv \
  --thresholds-json reports/turbidity_state/12117500_v2/state_thresholds.json \
  --out-dir reports/turbidity_tier_vs_if_12117500
```

### 5.2 Multivariate IF + Three-Way Holdout Comparison

```bash
cd ai_service
.venv/bin/python turbidity_tier_vs_multivar_if_eval.py \
  --features-csv data/features_12117500_63680_openmeteo_upstream_2022.csv \
  --thresholds-json reports/turbidity_state/12117500_v2/state_thresholds.json \
  --out-dir reports/turbidity_tier_univariate_vs_multivar_holdout_12117500
```

**Online API**: `POST /anomaly/site-param-multivar-from-features`  
**Spring**: `POST /api/usgs/anomaly/site-param-multivar/check`

**Code**: `models/turbidity_tier_vs_if_eval.py`, `models/turbidity_tier_vs_multivar_if_eval.py`

### 5.3 IF-Only Lead Time (Holdout Tier Upgrade Rate)

At anchor hour **t** (water-quality tier NORMAL, non-gap, IF available), measure whether WATCH/HIGH/CRITICAL appears within **(t, t+H]** (H=6/12/24), comparing:

| Cohort | Condition |
|--------|-----------|
| IF-only (univariate) | tier NORMAL + univariate IF alert |
| IF-only (multivariate) | tier NORMAL + multivariate IF alert |
| Control | tier NORMAL + corresponding IF normal |
| Reference tier-only | tier WATCH+ + univariate IF normal |

Minimum valid future hours: `min(6, H)` (consistent with 12h risk classification backtest). Outputs include upgrade rate, uplift vs control, and secondary stats for max NTU / ΔNTU within the window.

```bash
cd ai_service
.venv/bin/python turbidity_if_only_lead_time.py \
  --report-dir reports/turbidity_state/12117500_v2 \
  --plot
```

Regenerate plots from existing JSON only (skip IF scoring, faster):

```bash
cd ai_service
.venv/bin/python turbidity_if_only_lead_time.py \
  --report-dir reports/turbidity_state/12117500_v2 \
  --plot-only
```

**Outputs**: `if_only_lead_time.json`, `.md`; with `--plot` or `--plot-only` also generates  
`if_only_lead_time_upgrade_rates.png` (grouped bar chart of 6/12/24h upgrade rates by cohort),  
`if_only_lead_time_uplift.png` (uplift vs control, percentage points).  
**Code**: `models/turbidity_if_only_lead_time.py`

---

## 6. R6 — Phase A (Ridge NTU → Tier Risk)

### 6.1 Protocol Highlights

- At cutoff `T`, use **direct Ridge** to predict `T+1..T+12` NTU (non-recursive NTU curve used for risk aggregation).
- Map predicted NTU to tiers via frozen `tier_rules`; `recommend_alert` = max tier within future 12h ∈ {WATCH,HIGH,CRITICAL}.
- Modes: `oracle` (future exog ground truth) vs `persistence` (exog held at T).

### 6.2 Commands

```bash
cd ai_service
.venv/bin/python turbidity_risk_forecast_backtest.py \
  --features-csv data/features_12117500_63680_openmeteo_upstream_2022.csv \
  --thresholds-json reports/turbidity_state/12117500_v2/state_thresholds.json \
  --report-dir reports/turbidity_risk_forecast_12117500 \
  --holdout-step 24
```

**Outputs**: `reports/turbidity_risk_forecast_12117500/risk_forecast_holdout.json`, `.md`  
**Code**: `models/turbidity_risk_forecast_backtest.py`

---

## 7. R7 / R7a / R7b — Phase A' (12h Risk Classification)

### 7.0 Product Split (R7a / R7b)

| Sub-requirement | Condition @ T | Label | Online recommendation |
|-----------------|---------------|-------|----------------------|
| **R7** (full) | any water-quality tier | `alert_12h` | persistence (WATCH+ already alerted) |
| **R7a escalate** | **NORMAL** (non-gap) | `escalate_12h` = WATCH+ within 12h | NORMAL → **ML escalate experiment**; if gate fails, persistence (always 0) |
| **R7b recover** | WATCH+ | back to NORMAL within 12h | WATCH+ → **persistence** (doc; full training optional) |

**R7a Evaluation Contract**:

- **normal_escalate_events** (NORMAL and will escalate): primary KPI = **recall**, **FN**; persistence_escalate recall=0.
- **normal_no_escalate**: guardrail = **FP**, FP rate; when tuning selects τ, `fp ≤ persistence_fp × 1.05` (persistence FP=0 on NORMAL).
- **flood_window_normal**: 2025-12 flood-window operational stress test.
- **Training weights**: on tuning rows, flood window or `escalate_12h=1` → weight=`--flood-weight` (default 5.0).

```bash
cd ai_service
.venv/bin/python turbidity_risk_escalate_backtest.py \
  --features-csv data/features_12117500_63680_openmeteo_upstream_2022.csv \
  --thresholds-json reports/turbidity_state/12117500_v2/state_thresholds.json \
  --report-dir reports/turbidity_risk_forecast_12117500 \
  --holdout-step 24 \
  --tuning-dense-step 24 \
  --no-precip-ffill \
  --with-if-features \
  --tune-alert-threshold \
  --flood-weight 5.0
```

**Outputs**: `risk_class_escalate_12h.json` / `.md`  
**Code**: `models/turbidity_risk_escalate_backtest.py`, `turbidity_risk_escalate_backtest.py`

**R7b recover (planned only)**: at `WATCH+`@T predict whether `T+1..T+12` returns to NORMAL; symmetric to R7a; full training not run by default; stub CLI may be added later.

---

### 7.1 R7 Full — Protocol Highlights

- Label: at `T`, look at max water-quality tier over valid 63680 hours in `T+1..T+12`; `alert_12h` = whether WATCH+ appears.
- Features: lag blocks of 63680 + precipitation + upstream flow (default lag=36); **no forward-fill for precipitation**, upstream may ffill (24h).
- Models: persistence_alert, persistence_max_tier, logistic, LightGBM; holdout step=24h.
- Skip: cutoffs with < 6 valid y hours in future 12h.

### 7.2 Commands (Recommended Exog Strategy)

```bash
cd ai_service
.venv/bin/python turbidity_risk_class_backtest.py \
  --features-csv data/features_12117500_63680_openmeteo_upstream_2022.csv \
  --thresholds-json reports/turbidity_state/12117500_v2/state_thresholds.json \
  --report-dir reports/turbidity_risk_forecast_12117500 \
  --holdout-step 24 \
  --no-precip-ffill
```

**Outputs**: `risk_class_holdout_no_precip_ffill.json` / `.md`

### 7.3 Holdout Metrics Summary (255 cutoffs, 2025-07 ~ 2026-05)

| Model | alert_12h F1 | max_tier macro-F1 | 2025-12 flood-window alert lead time |
|-------|--------------|-------------------|--------------------------------------|
| persistence_alert | **0.80** | 0.20 | 23h (matches observed) |
| persistence_max_tier | 0.80 | **0.80** | 23h |
| logistic_regression | 0.79 | 0.60 | 23h |
| lightgbm | 0.80 | 0.62 | 23h |
| majority_always_normal | — | 0.20 | no alert |

**Selection conclusion (Phase B)**: online service uses **persistence** (aligned with Phase A' best baseline; interpretable, no training dependency).

**Code**: `models/turbidity_risk_class_backtest.py`  
**Tests**: `tests/test_turbidity_risk_class_backtest.py`

### 7.4 Phase A' Lead-Time v3 (Event-Local Window + FP Guardrail)

**Primary KPI**: **lead time** on holdout for "tier upgrade events" (median/mean lead hours, % events with early alert), not just `alert_12h` F1.  
**Event definition**: at cutoff `T`, water-quality tier **NORMAL**, and **first** **WATCH+** within `T+1..T+12` (valid future y hours ≥ 6).  
**Lead time (v3, event-local)**: search only within **`[T, min(T+12, first_upgrade_ix − 1)]`** for first `predicted alert_12h=1`; lead time = first upgrade hour − cutoff hour, capped at `min(12, first_upgrade − T)`. **Do not** scan backward from holdout start (v2 inflated median to ~2700h).  
**No alert**: no `alert_12h=1` before upgrade → `lead_hours=null`, excluded from median/mean.  
**Guardrail**: FP rate on no-upgrade windows (`alert_12h=0`) and control cohort (tier NORMAL + univariate IF normal) must not be materially worse than persistence.

**Extended features** (`models/turbidity_risk_features.py`):

- Existing: 63680 / precipitation / upstream lag blocks (no precip ffill)
- New: `precip_sum_6h/12h/24h`, `upstream_q_diff`, `upstream_q_rolling_max_6h/12h/24h`
- Optional `--with-if-features`: univariate/multivariate IF `is_anomaly` + `score` at cutoff `T` (train from 72 points, max 2500, contamination 0.05; cached per cutoff)

```bash
cd ai_service
.venv/bin/python turbidity_risk_class_backtest.py \
  --features-csv data/features_12117500_63680_openmeteo_upstream_2022.csv \
  --thresholds-json reports/turbidity_state/12117500_v2/state_thresholds.json \
  --report-dir reports/turbidity_risk_forecast_12117500 \
  --holdout-step 24 \
  --no-precip-ffill \
  --with-if-features \
  --leadtime-eval \
  --output-basename risk_class_leadtime_v3 \
  --plot-leadtime
```

**Outputs**: `risk_class_leadtime_v3.json` / `.md` (includes v2 comparison section; optional `risk_class_leadtime_v3_leadtime.png`)  
**History**: v2 used full holdout scan; see `risk_class_leadtime_v2.json`.

**Latest holdout lead time (v3, event-local, step=1 eval)** (`risk_class_leadtime_v3.json`):

| Model | Median lead (h) | % with lead time | FP (no 12h upgrade) |
|-------|----------------:|-----------------:|--------------------:|
| persistence_alert | — | 0% | 0.81% |
| logistic_regression | 5.0 | 83.8% | 17.7% |
| lightgbm | 4.0 | 77.4% | 14.2% |

Compared to v2: persistence / LR / LGBM v2 medians were inflated to **2700h / 2279h / 2273h** (full holdout scan); v3 corrected to **— / 5.0 / 4.0**.  
**Launch conclusion**: persistence remains default; ML failed FP guardrail (see `launch_policy`).

### 7.5 Phase A' Lead-Time v4 (IF Features + ML Probability Threshold Tuning)

Building on v3 event-local lead time and FP guardrail, add **univariate/multivariate IF** (`is_anomaly` + `score`) to Logistic / LightGBM training features, and sweep `alert_12h` probability thresholds on the **tuning segment** (τ ∈ [0.05, 0.95], step 0.05); holdout is evaluation only (no τ selection on holdout).

| Step | Description |
|------|-------------|
| Features | `--with-if-features`: extended exog + uni/multi IF @ T |
| Select τ | compare τ values only on tuning dense cutoffs (default step=1) |
| FP guardrail | on tuning, `fp(no upgrade 12h) ≤ persistence_fp × --fp-guardrail-ratio` (default 1.05) |
| Objective | among τ meeting FP constraint, pick **median lead** maximum |
| Holdout | apply selected τ; report lead-time / FP / `launch_policy` |

```bash
cd ai_service
.venv/bin/python turbidity_risk_class_backtest.py \
  --features-csv data/features_12117500_63680_openmeteo_upstream_2022.csv \
  --thresholds-json reports/turbidity_state/12117500_v2/state_thresholds.json \
  --report-dir reports/turbidity_risk_forecast_12117500 \
  --holdout-step 24 \
  --no-precip-ffill \
  --with-if-features \
  --leadtime-eval \
  --tune-alert-threshold \
  --fp-guardrail-ratio 1.05 \
  --output-basename risk_class_leadtime_v4_threshold \
  --plot-leadtime
```

**Outputs**: `risk_class_leadtime_v4_threshold.json` / `.md` (includes `threshold_tuning`, v3 comparison section)  
**Code**: `models/turbidity_risk_class_backtest.py` (`tune_ml_alert_thresholds`, `sweep_ml_alert_threshold`)

**Launch gate (report `launch_policy`)**:

| Condition | Conclusion |
|-----------|------------|
| ML **median lead** > persistence **and** FP (no 12h upgrade) ≤ persistence × 1.05 | **production candidate** (may replace default persistence) |
| Otherwise | **persistence remains default**; ML marked **experimental** in API/UI |

### 7.6 Event-Window Classification Metrics (`risk_class_event_metrics`)

Beyond holdout F1, report `alert_12h` **TP/FP/FN/TN counts** and precision/recall/F1 by **cohort**:

| Cohort | Purpose |
|--------|---------|
| `full_holdout` | all holdout cutoffs (step=24) |
| `tier_upgrade_events` | T is NORMAL and WATCH+ appears in T+1..T+12 (same as lead-time upgrade events) |
| `no_upgrade_12h` | `alert_12h=0`, no tier upgrade within 12h — **FP guardrail** |
| `flood_window` | cutoff ∈ 2025-12-09 .. 2025-12-17 UTC |
| `y_rise_12h` | T is NORMAL and turbidity rise within 12h ≥ `delta_up_1h` |

**Evaluation contract**:

- **Upgrade/rise events** (`tier_upgrade_events`, `y_rise_12h`): primary metrics = **recall**, **FN count** (missed alerts); F1 is secondary.
- **No-upgrade cutoffs** (`no_upgrade_12h`): guardrail = **FP count**, **FP rate** (false-alert cost).
- **Flood window**: operational stress test (mixed positive/negative samples).

Models compared: `persistence_alert`; `logistic_regression` / `lightgbm` at **τ=0.5** and **v4 tuned τ** (from `risk_class_leadtime_v4_threshold.json` or on-the-fly tuning).

```bash
cd ai_service
.venv/bin/python turbidity_risk_event_eval.py \
  --features-csv data/features_12117500_63680_openmeteo_upstream_2022.csv \
  --thresholds-json reports/turbidity_state/12117500_v2/state_thresholds.json \
  --report-dir reports/turbidity_risk_forecast_12117500 \
  --holdout-step 24 \
  --no-precip-ffill \
  --with-if-features \
  --tuning-dense-step 24
```

**Outputs**: `risk_class_event_metrics.json` / `.md`  
**Code**: `models/turbidity_risk_event_eval.py`, `turbidity_risk_event_eval.py`

---

## 8. R9 — Phase B (12h Alert Risk — Online)

### 8.1 Implementation Steps

1. Python: `run_risk_forecast_12h()` — read feature CSV + frozen thresholds; current tier persistence → `alert_12h_forecast`, `max_tier_forecast`, `recommend_alert`, `rationale_template_key`, 1–12 color bar.
2. FastAPI: `POST /turbidity/risk-forecast-12h`
3. Spring Feign + `POST /api/usgs/turbidity-risk/forecast-12h`
4. Frontend: "12-Hour Alert Risk (Phase B)" section in turbidity detection panel; rationale text via i18n keys (EN/ZH).

### 8.2 Commands and Configuration

```bash
# Direct Python
curl -s -X POST http://127.0.0.1:8000/turbidity/risk-forecast-12h \
  -H 'Content-Type: application/json' \
  -d '{
    "site_no": "12117500",
    "features_csv_path": "data/features_12117500_63680_openmeteo_upstream_2022.csv",
    "thresholds_json_path": "reports/turbidity_state/12117500_v2/state_thresholds.json"
  }'

# Spring
curl -s -X POST 'http://127.0.0.1:8080/api/usgs/turbidity-risk/forecast-12h?siteNo=12117500'
```

**Key Files**

| Layer | Path |
|-------|------|
| Python logic | `models/turbidity_risk_forecast_12h.py` |
| FastAPI | `main.py` |
| Spring config | `water.turbidity-risk-forecast.*` |
| Spring API | `TurbidityRiskForecastController.java` |
| Frontend | `App.tsx`, `locale/messages.ts` (`forecast.turbidityRisk.*`) |

**Tests**

```bash
cd ai_service && .venv/bin/pytest tests/test_turbidity_risk_forecast_12h.py -q
cd monitor_business/backend && mvn -q test -Dtest=TurbidityRiskForecastControllerTest
```

### 8.3 UI Verification Steps

1. Start `ai_service` (:8000), Spring (:8080), and frontend dev server.
2. On the forecast page, select site **12117500**, click **Turbidity Detection**.
3. Below detection results, view **12-Hour Alert Risk (Phase B)**: alert risk, possible max tier, whether alert is recommended, one-line rationale, optional 1–12 hour color bar.
4. Switch UI language and confirm rationale switches between English and Chinese (keys such as `forecast.turbidityRisk.rationale.persistenceElevated`).

---

## 9. R10 — Future: LLM Explanation Layer (Not Implemented)

See `plan/turbidity_state_monitoring.md` §6:

- LLM generates explanation text **only**; **must not** modify `recommend_alert` or any automatic alert boolean fields.
- Agent may read `reports/**` and this handbook for operational Q&A.

---

## 10. Feature Engineering and Upstream Data

```bash
cd ai_service
# Build 2022+ feature table (63680 + Open-Meteo precipitation + upstream 12116400)
.venv/bin/python fetch_turbidity_upstream_features.py \
  --out-csv data/features_12117500_63680_openmeteo_upstream_2022.csv
```

**Upstream notes**: 12116400 (Cedar Falls) is upstream of 12117500; 12117600 is deprecated (redundant with target site).

---

## 11. Evaluation Contract and Reproducibility

- Time split: default last 20% holdout; `split_index` in `state_thresholds.json` / each holdout JSON.
- Walk-forward spirit: cutoff `T` uses only features `≤T`; labels use `T+1..T+12`.
- Details: `plan/evaluation_contract.md`

---

## 12. Related Report Paths Quick Reference

| Topic | Directory or File |
|-------|-------------------|
| State/thresholds v2 | `reports/turbidity_state/12117500_v2/` |
| Gap | `reports/turbidity_gap_12117500/` |
| Holdout tiers | `reports/turbidity_holdout_12117500/` |
| Phase A / A' risk | `reports/turbidity_risk_forecast_12117500/` |
| Tier vs IF | `reports/turbidity_tier_vs_if_12117500/` |
| Tier vs multivariate IF | `reports/turbidity_tier_univariate_vs_multivar_holdout_12117500/` |
| NTU exogenous regression suite | `reports/turbidity_exog_suite/` |

---

## 13. Versions and Model Tags

| Component | Version / Tag |
|-----------|---------------|
| Water-quality tiers | `turbidity-state-v2.1` |
| Phase B online risk | `persistence_alert` + `persistence_max_tier` |
| Multivariate IF | `site_param_multivar` pipeline (see anomaly API) |
| Flow forecast (independent track) | `00060` / `plan/model_selection_and_next_steps_plan.md` |

---

*Document updated with Phase B rollout; operational steps for §9 will be appended after LLM layer implementation.*
