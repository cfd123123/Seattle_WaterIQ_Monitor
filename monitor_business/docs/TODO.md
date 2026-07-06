# monitor_business 待办与后续项

跟踪实现缺口与规划，完成某项后可将对应条目勾掉或删除。

**数据库**：默认 **PostgreSQL**，安装与 Docker 步骤见 [postgresql-setup.md](./postgresql-setup.md)。

**时间与多时区**：业界惯例与当前项目取舍见 [time-and-timezone.md](./time-and-timezone.md)。

**统计口径**：V4.4 统计接口与 Grafana 面板口径见 [stats-definition.md](./stats-definition.md)。

**AI 服务演进（规则 + 短时预测 + USGS）**：见 [ai-rules-forecast-roadmap.md](./ai-rules-forecast-roadmap.md)；**USGS 参数映射**见 [usgs-parameter-mapping.md](./usgs-parameter-mapping.md)。

## 暂不实施（主功能做完后再优化）

以下两项**刻意延后**：当前以 **代码 + `water.alert.threshold`** 与**同步流程**为主，等主要功能闭环后再做。

- [ ] **`rule_config` 表 / 规则配置化**：告警规则仍由 **`PollutionLevelThresholds`**、常量（`HARDCODED_LEVEL_THRESHOLD` 等）与 **`water.alert.threshold`** 控制；后续再考虑库表、管理接口、运营可配阈值与多规则启停。
- [ ] **异步通知**：告警产生后通过 **消息队列** 或 **`@Async`** 推送（短信/邮件/IM 等）尚未实现；当前仅落库 + HTTP 查询/确认。
- [ ] **时区统一到 UTC（最低优先级）**：将时间字段与接口筛选逐步从 `LocalDateTime`/`timestamp` 迁移到 UTC 语义（如 `Instant` + `timestamptz` 或统一 `Z` 输出），并更新 API 文档与调用约定。详见 [time-and-timezone.md](./time-and-timezone.md)。
- [ ] **V4.3 权限体系（暂缓，当前非重点）**：JWT / 角色权限（如 `VIEWER`、`OPERATOR`）以及 `ack/close` 写接口鉴权先不做，待主功能稳定后再推进。
- [ ] **数据治理与模型重训（暂后）**：在自有标注或规则标注的训练 CSV 上清洗（负值/异常值、标签口径），用 `ai_service/train_water_model.py --input <csv>` 重训 `water_model.pkl`，并保留可复现的评估记录。

## 其它（可选）

- [ ] **LangChain / LLM（可选，非核心刚需）**：当前仓库**未使用** LangChain；核心业务（USGS IV 拉数、Ridge 短时预测、阈值/IsolationForest 异常与告警）**不依赖** LLM 编排。若无明确产品场景，引入会增加复杂度与运维面。**若**需补强 LLM 方向简历或运营能力，可后续以**独立模块**试点：**RAG（文档/运维手册问答）**、**告警摘要**、**自然语言→结构化 API 调用**等，并明确**不替代**数值预测与合规/规则终裁主路径。
- [ ] 数据库层显式外键约束（当前为逻辑关联 + JPA 字段）。
- [x] **持久化库**：默认已切换 **PostgreSQL**（`docker-compose.yml` + [postgresql-setup.md](./postgresql-setup.md)）；无 PG 时可用 **`h2` profile** 文件库。
- [ ] **前端驾驶舱体验优化（后置）**：
  - 地图/图表空态与加载态（Skeleton / Empty）。
  - 顶部 KPI 卡片（近24h检测、近24h告警、未关闭告警）。
  - 地图与图表统一污染等级配色映射。
  - 告警列表内联 `ack/close` 操作。
  - 地图点选后按站点联动过滤图表/列表。

## 本地验证约定

- **每次新测试前**：先停掉上一次用于联调的 **Spring Boot**（在 `monitor_business/backend` 下 `mvn spring-boot:run` 的终端 **Ctrl+C**），以及不再需要的 **Python uvicorn** / **Docker 起的 PostgreSQL**（若需释放 **5432**）；避免 **端口占用**（如 `8080` / `8000` / `5432`）。
- **排查占用**（macOS）：`lsof -i :<端口>`，再 `kill <PID>`。
