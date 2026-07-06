# PostgreSQL 本地环境（monitor_business）

## 本机检测结果（可在终端自行复查）

- **`psql` / `postgres` 未找到**：当前环境很可能**尚未安装** PostgreSQL 服务端。
- **Docker**：若已安装 **Docker Desktop**，可先启动应用，再用本目录下的 **`docker-compose.yml`** 起库（见下文）。

---

## 方式 A：Docker（推荐，与项目对齐）

1. 启动 **Docker Desktop**（或确保 `docker info` 无报错）。
2. 在 **`monitor_business`** 目录执行（与 `docker-compose.yml` 同级）：

   ```bash
   docker compose up -d
   ```

3. 默认连接信息与 `application.properties` 一致：
   - 主机：`localhost`
   - 端口：`5432`
   - 库名：`water_monitor`
   - 用户 / 密码：`water` / `water`

4. 停止容器（数据在命名卷 `water_monitor_pgdata` 中保留）：

   ```bash
   docker compose down
   ```

---

## 方式 B：Homebrew 安装 PostgreSQL（macOS）

```bash
brew install postgresql@16
brew services start postgresql@16
export PATH="/opt/homebrew/opt/postgresql@16/bin:$PATH"   # Apple Silicon
# Intel 常见为：/usr/local/opt/postgresql@16/bin

createuser -s water 2>/dev/null || true
psql -U "$(whoami)" -d postgres -c "CREATE USER water WITH PASSWORD 'water';" 2>/dev/null || true
psql -U "$(whoami)" -d postgres -c "CREATE DATABASE water_monitor OWNER water;" 2>/dev/null || true
```

若本机已有默认 `postgres` 超级用户，也可用：

```bash
psql postgres -c "CREATE USER water WITH PASSWORD 'water';"
psql postgres -c "CREATE DATABASE water_monitor OWNER water;"
```

---

## 应用配置说明

- **默认**：使用 **`application.properties`** 中的 PostgreSQL URL（可用环境变量覆盖）：
  - `SPRING_DATASOURCE_URL`
  - `SPRING_DATASOURCE_USERNAME`
  - `SPRING_DATASOURCE_PASSWORD`
- **临时退回 H2 文件库**（不装 PostgreSQL 时）：

  ```bash
  cd backend && mvn spring-boot:run -Dspring-boot.run.profiles=h2
  ```

  对应 **`application-h2.properties`**，数据文件在 **`monitor_business/backend/data/`**（`AUTO_SERVER` 便于多进程访问同一文件库，仅开发用）。

---

## 验证

PostgreSQL 就绪后启动应用，日志中应出现连上 `jdbc:postgresql://...`，首次启动 **`ddl-auto=update`** 会自动建表。
