-- 清空告警表 alert_event 全部数据（不可逆）
-- PostgreSQL：同时重置 id 自增序列，新告警从 id=1 起算。
--
-- 用法：
--   psql -h localhost -U water -d water_monitor -f scripts/delete_all_alert_events.sql
--
-- Deletes all rows from alert_event only (monitor_station and other tables are untouched).

BEGIN;

TRUNCATE TABLE alert_event RESTART IDENTITY;

COMMIT;
