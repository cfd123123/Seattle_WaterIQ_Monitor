-- One-time cleanup: remove legacy water_quality_record table and FK columns.
-- Run against PostgreSQL after deploying the application version that no longer maps these columns.
-- Order: drop dependent columns first, then the fact table.

ALTER TABLE alert_event DROP COLUMN IF EXISTS water_quality_record_id;
ALTER TABLE model_call_log DROP COLUMN IF EXISTS water_quality_record_id;

DROP TABLE IF EXISTS water_quality_record;
