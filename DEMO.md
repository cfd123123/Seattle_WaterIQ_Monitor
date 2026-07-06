# HR / 审阅者演示指南 · Reviewer Demo Guide

面向 **招聘方、技术审阅、课程作业评分** 的 **几乎零成本（$0）** 公开演示路径。  
English section headers below; body is Chinese-first for local HR workflows.

---

## 1. 方案概览 · Overview ($0 path)

| 项目 | 建议 |
|------|------|
| 代码托管 | **GitHub 公开仓库**（免费） |
| 运行环境 | 本机 **Docker Compose**（见 `monitor_business/docker-compose.yml`） |
| 演示视频 | **2 分钟** 屏幕录制（见 §3），上传 YouTube **未列出** 或 B 站，链接写在 README |
| 静态截图 | 仓库内 `docs/screenshots/`（见 §4） |
| LLM（Copilot） | **可选**：本机 **Ollama**（免费）或 README 中说明「需自备 API Key」 |

**不花钱也能展示的核心能力**：USGS 数据拉取、短时预测曲线、浊度状态/告警、管理台地图与统计。  
**需要 LLM 的能力**：右下角 **Copilot 问答**、浊度风险 **AI 文字解释**（无 LLM 时接口会降级或提示未配置）。

---

## 2. 审阅者 5 分钟快速路径 · Quick path for reviewers

### 2.1 克隆与启动 · Clone & run

```bash
git clone https://github.com/<你的用户名>/environment_project.git
cd environment_project/monitor_business
docker compose up -d postgres redis rabbitmq ai-inference-service monitor-service task-worker api-gateway
# 前端（另开终端）
cd frontend && npm install && npm run dev
```

- 网关 API：`http://localhost:8080`
- 管理台前端：通常为 `http://localhost:5173`（以 Vite 输出为准）
- AI 服务健康检查：`http://localhost:8000/health`

更完整的分步说明见 [monitor_business/README.md](./monitor_business/README.md)。

### 2.2 无需 LLM 即可验证 · Works without LLM

| 功能 | 是否需要 LLM | 说明 |
|------|----------------|------|
| **Analytics → 流量/浊度预测图** | 否 | Ridge 模型在请求时从 IV CSV **现场拟合**，不依赖 `.pkl` |
| 浊度四态监控、阈值扫描 | 否 | 规则 + 统计 |
| 告警列表、站点地图、统计总览 | 否 | Spring + PostgreSQL |
| **Copilot 浮窗问答** | **是** | 需 `ASSISTANT_LLM_*`（Ollama 或 OpenAI 兼容 API） |
| 浊度 12h 风险 **AI 解释文案** | **是** | 无 LLM 时仍可看数值预测，解释字段会提示不可用 |

审阅者若 **不配置 Ollama/API Key**：请重点看 **预测页曲线** 与 **告警/地图**；README 与演示视频可展示 Copilot（由作者本地录制）。

### 2.3 可选：本机 Ollama（免费 Copilot）· Optional local LLM

```bash
# macOS 示例：安装 Ollama 后
ollama pull qwen2.5:3b   # 或 llama3.1:8b（与 docker-compose 默认一致）
```

`monitor_business/docker-compose.yml` 中 `ai-inference-service` 已默认指向 `host.docker.internal:11434`。  
复制 `ai_service/.env.example` 为 `ai_service/.env.local` 仅在你 **不用 Compose 环境变量、改本机直跑 uvicorn** 时需要。

首次启用 Copilot 前在 `ai_service` 目录重建 RAG 索引（仅需已提交的 `docs/turbidity_operations.md`）：

```bash
cd ai_service
python -m assistant.rag.indexer --rebuild
```

---

## 3. 推荐 2 分钟演示视频 · 2-min video script

**画幅**：1920×1080 或 1280×720；**旁白或字幕**二选一即可。

| 时间段 | 画面 | 旁白要点（中文） |
|--------|------|------------------|
| 0:00–0:20 | 浏览器打开 **Analytics / 预测** 页，选站点 `12117500`、参数流量 `00060` | 说明：Puget Sound USGS 站点，短时多步预测，辅助值班研判 |
| 0:20–0:50 | 展示预测曲线加载、切换浊度 `63680` 或 12h 风险卡片（若有） | 强调：预测服务为独立 Python FastAPI，Java 网关转发 |
| 0:50–1:40 | 展开 **Copilot**，依次输入下面 **3 个问题**（可剪成三个短回答） | 展示 RAG + 工具调用（需本机 Ollama 已启动） |
| 1:40–2:00 | 告警列表或地图缩略 + 仓库 README「For reviewers / HR」与 GitHub 链接 | 总结：监测、预测、告警、可选 AI 运维助手 |

### Copilot 推荐的 3 个演示问题

1. **运维文档（RAG）**：`Phase B 是什么？recommend_alert 和 12h 风险有什么关系？`  
2. **实时数据（工具）**：`站点 12117500 当前浊度状态是什么？`  
3. **混合（RAG + 工具）**：`为什么站点 12117500 可能 recommend_alert？Phase B 文档怎么说？`

（英文问题亦可，Copilot 系统提示以英文回答运维文档类内容。）

**上传**：YouTube「未列出」或 B 站；在 README 的 **For reviewers / HR** 一节贴上链接。

---

## 4. 截图文件夹 · Screenshots

建议将审阅用静态图放在：

```
docs/screenshots/
  01-analytics-forecast.png
  02-turbidity-risk.png
  03-copilot-panel.png
  04-alerts-map.png
  05-architecture-snippet.png   # 可选：README 架构示意
```

- 仓库已预留 `docs/screenshots/.gitkeep`；提交 PNG 前请 **打码** 任何内部 URL、密钥、真实员工信息。
- 若不想把大图放进 Git，可只放 **3–5 张压缩图**，其余放在视频平台。

---

## 5. 安全推送到 GitHub · Safe push checklist

推送前在仓库根目录执行：

```bash
git status
git check-ignore -v ai_service/reports/eda/12117000_00060.png   # 应被忽略
git check-ignore -v ai_service/.env.local                        # 应被忽略
```

**切勿提交**：

- `.env`、`.env.local`、任何 `*.pem` / `*.key`、API Key
- `ai_service/data/`（IV CSV、特征表等，体积大且可能含敏感运维信息）
- `ai_service/reports/`、回测 JSON、EDA 图、`models/*.pkl` 等大文件（见根目录 `.gitignore`）
- 内部规划/面试用 Markdown（`ai_service/plan/`、`*implementation*` 等）

**建议首次公开前**：

```bash
# 若历史上误提交过大文件，先从索引移除（不删本地文件）
git rm -r --cached ai_service/reports/ 2>/dev/null || true
git rm -r --cached ai_service/plan/ 2>/dev/null || true
git rm --cached ai_service/models/*.pkl 2>/dev/null || true
git status   # 确认仅源码、配置、DEMO、截图占位等
git push -u origin main
```

在 GitHub 仓库 **Settings → General** 可开启 *Private vulnerability reporting*；**不要**在公开 README 写生产数据库密码。

---

## 6. README 中写给 HR 的一段话（可复制）· Blurb for README

在根目录 [README.md](./README.md) 的 **For reviewers / HR** 小节可写：

> **For reviewers / HR**  
> This is a water-quality monitoring demo (USGS IV, short-horizon forecast, alerts, optional RAG copilot).  
> **No cloud spend required** for core UI: use Docker Compose per `monitor_business/README.md`.  
> Copilot needs a local [Ollama](https://ollama.com) or your own LLM API key.  
> **2-min walkthrough video**: \<你的链接\> · **Screenshots**: `docs/screenshots/` · **Details**: [DEMO.md](./DEMO.md)

---

## 7. 常见问题 · FAQ

**Q：公开仓库会不会泄露训练数据？**  
A：`.gitignore` 已排除 `data/`、`reports/`、`.pkl`；仅提交源码与最小运维文档 `ai_service/docs/turbidity_operations.md`。

**Q：审阅者 clone 后 Copilot 没反应？**  
A：检查 `curl http://localhost:8000/assistant/health`（或项目内等价健康接口）；确认 Ollama 运行且已 `python -m assistant.rag.indexer --rebuild`。

**Q：能否完全云端演示？**  
A：可以，但不再是 $0 方案；需自付云主机 + 可选 OpenAI API。HR 路径推荐 **本地 Docker + 视频补 Copilot**。

---

*文档版本：与仓库 `.gitignore` 及 `assistant/config.py` 中 `DEFAULT_RAG_DOC_REL_PATHS` 同步维护。*
