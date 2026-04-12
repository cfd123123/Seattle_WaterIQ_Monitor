# 系统架构一页总览

面向简历/汇报：**浏览器 → Spring 业务与持久化 → Python AI 与 USGS 数据 → PostgreSQL**。下方图可在支持 Mermaid 的编辑器（VS Code、GitHub、Notion、Typora）中直接渲染；也可粘贴到 [mermaid.live](https://mermaid.live) 导出 PNG/SVG。

---

## 1. 总体部署与数据流

```mermaid
flowchart TB
  subgraph User["用户侧"]
    UI["React + Vite\n(开发期 /api 代理至 8080)"]
  end

  subgraph Java["Spring Boot · monitor_business :8080"]
    API["REST：检测 / 站点 / 告警 / 统计 / 预测 / IV 刷新 / 浊度阈值扫描"]
    FEIGN["OpenFeign → Python"]
    SCH["@Scheduled\n自动预测 · 浊度阈值扫描"]
    API --> FEIGN
    SCH --> FEIGN
    API --> PG
    SCH --> PG
  end

  subgraph DB["持久化"]
    PG[("PostgreSQL\nmonitor_station · water_quality_record\nalert_event · model_call_log …")]
  end

  subgraph Py["Python · ai_service :8000"]
    FAST["FastAPI"]
    RS["规则评分 /predict"]
    FC["短时预测 /forecast"]
    IV["IV 拉取与覆盖写 CSV"]
    AN["单参异常 /anomaly"]
    TB["浊度阈值 batch · sites-with-63680"]
    FAST --> RS
    FAST --> FC
    FAST --> IV
    FAST --> AN
    FAST --> TB
  end

  subgraph Ext["外部数据"]
    NWIS["USGS NWIS\n(IV 瞬时数据)"]
  end

  subgraph Files["本地文件"]
    CSV["data/usgs_puget_iv.csv\n(宽表：site_no + 参数列)"]
  end

  UI -->|"HTTP /api/*"| API
  FEIGN -->|"HTTP JSON"| FAST
  IV --> NWIS
  FC --> CSV
  AN --> CSV
  TB --> CSV
  IV --> CSV
```



---

## 2. 两条核心告警链路（概念）

```mermaid
flowchart LR
  subgraph PathA["路径 A：在线检测"]
    C1["POST /api/check\n11 项指标"] --> P1["Python /predict\n规则或遗留模型"]
    P1 --> R1["water_quality_record"]
    R1 --> A1["alert_event\n达阈值时"]
  end

  subgraph PathB["路径 B：USGS 浊度阈值"]
    IV1["IV CSV 含 63680"] --> T1["仅已登记且 IV 有浊度的站"]
    T1 --> T2["连续 2 点规则\nJava 判定"]
    T2 --> A2["alert_event\nTHRESHOLD_ALERT"]
  end
```



---

## 3. 技术栈速览


| 层级  | 技术                                                               |
| --- | ---------------------------------------------------------------- |
| 前端  | React 18、Vite、Axios、Leaflet、Recharts                             |
| 后端  | Spring Boot 3、JPA、OpenFeign、Resilience4j、Actuator/Prometheus（可选） |
| AI  | Python 3、FastAPI、pandas、scikit-learn（预测/异常按需）                    |
| 数据  | PostgreSQL（默认），可选 H2                                             |


---

## 4. 与详细文档的关系

- 接口清单与请求体：**[api.md](./api.md)**  
- 表结构与字段：**[database-schema.md](./database-schema.md)**  
- 业务分层与演进说明：**[architecture.md](./architecture.md)**（长文）

---

*文档版本：与当前仓库实现一致；若端口或路径变更，请同步更新上图。*