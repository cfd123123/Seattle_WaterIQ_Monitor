# monitor_business 统计口径说明（V4.4）

本文定义 `StatsController` 相关接口与 Grafana 统计面板的计算口径，避免“同一指标多种解释”。

## 1. 适用范围

- API：
  - `GET /api/stats/overview`
  - `GET /api/stats/distribution`
  - `GET /api/stats/trend`
- 面板：
  - `observability/grafana/dashboards/water-business-overview.json` 中“统计总览（近 24h / 7d）”与分布图

## 2. 时间口径

- 当前后端使用 `LocalDateTime` + PostgreSQL `timestamp`（无时区）。
- `trend` 与 `distribution` 的 `from` / `to` 为 `yyyy-MM-dd`，按**闭区间日期**解释：
  - `from` 当天 `00:00:00` 起
  - `to` 次日 `00:00:00` 前（SQL 上限采用 `< to+1d`）
- `overview` 的“今日”以服务端当天自然日计算。
- `overview` 的“最近 7 天”是**含今天在内**的 7 个自然日（`today-6` 到 `today`）。
- 查询跨度保护：`trend` 与带日期参数的 `distribution` 默认最多 **365 天**（可由 `water.stats.max-range-days` 调整）。
- 配置校验：`water.stats.max-range-days` 在应用启动期做参数校验，最小值为 **1**（小于 1 会启动失败）。

## 3. 指标定义（API）

### 3.1 `/api/stats/overview`

- `totalCheckCount`：`usgs_site_param_run` 表总行数（USGS 单参数 IV 巡检/异常检测运行记录）。
- `totalAlertCount`：`alert_event` 总记录数。
- `totalAiFailureCount`：`model_call_log.success=false` 总记录数。
- `openAlertCount`：`alert_event.status IN ('NEW','ACK')` 的数量。
- `todayCheckCount` / `todayAlertCount` / `todayAiFailureCount`：当天自然日窗口内的计数。
- `last7DaysCheckCount` / `last7DaysAlertCount` / `last7DaysAiFailureCount`：最近 7 天窗口内的计数。

### 3.2 `/api/stats/distribution`

- `pollutionLevelDistribution`：按 `alert_event.pollution_level` 分组计数（来自告警快照字段，非独立事实表）。
  - 输出进行标准化：`excellent/good/moderate/poor/very poor` 归一为 `Excellent/Good/Moderate/Poor/Very Poor`。
- `alertSeverityDistribution`：按 `alert_event.severity` 分组计数。
  - 输出归一为 `LOW/MEDIUM/HIGH`，空值为 `UNKNOWN`。
- 若不传 `from`/`to`：统计全量数据；
- 传参时必须同时传两者，按日期窗口统计。

### 3.3 `/api/stats/trend`

- 当前仅支持 `granularity=day`。
- `series[i].date`：自然日。
- `checkCount`：趋势接口中保留字段，当前 USGS 趋势以 `flowDetectionCount` / `turbidityDetectionCount` 等为主；全零为预期（见实现）。
- `alertCount`：当日告警记录数。
- `aiFailureCount`：当日 AI 失败日志数（`model_call_log.success=false`）。
- `pollutionLevelBreakdown`：当日按污染等级分组统计。

## 4. 指标定义（Grafana / Prometheus）

- `water_checks_completed_total`：若应用内仍注册该 Micrometer 指标，则与「水质检测事实表」无绑定；以当前代码为准（可能未再递增）。以 Prometheus 实际抓取到的序列为准。
- `water_alerts_total`：每次创建告警后 +1（Micrometer 对 `water.alerts.created` 导出的 Prometheus 名称），带 `severity`、`pollution_level` 标签；同样预注册常见 `severity`×`pollution_level` 组合。
- `water_ai_predict_seconds_count{outcome="failure"}`：AI 调用失败次数（Timer count）。

说明：

- Grafana 面板中的“近24h 检测数/告警数/AI失败数”来自 `increase(...[24h])`，反映最近 24 小时滚动窗口。
- “近7天分布”来自 `increase(...[7d])` + 标签聚合，反映近 7 天滚动窗口。
- API `overview` 使用自然日窗口，Grafana 使用滚动窗口，二者数值可能存在边界差异，属于预期。

## 5. 已知差异与解释建议

- **API vs Grafana 时间边界差异**：自然日 vs 滚动窗口。
- **历史数据补录**：若手工改库/导入历史数据，API 会立刻反映；Prometheus 只统计抓取后产生的指标样本。
- **时区升级计划**：后续若统一 UTC，需同步更新本文与 `time-and-timezone.md`。
