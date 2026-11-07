ALTER TABLE jobs ADD COLUMN IF NOT EXISTS stage VARCHAR(64) NOT NULL DEFAULT 'queued';
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS error_code VARCHAR(128);
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS error_stage VARCHAR(64);
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS action TEXT;
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS retryable INTEGER NOT NULL DEFAULT 0;
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS heartbeat_at DOUBLE;
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS last_attempt_at DOUBLE;
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS boot_id VARCHAR(64);
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS recovery_boot_id VARCHAR(64);
CREATE TABLE IF NOT EXISTS job_events (
 id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY, job_id VARCHAR(255) NOT NULL, at DOUBLE NOT NULL,
 event VARCHAR(64) NOT NULL, attempt INTEGER NOT NULL DEFAULT 0, boot_id VARCHAR(64),
 stage VARCHAR(64), code VARCHAR(128), message TEXT NOT NULL,
 details_json LONGTEXT NOT NULL, KEY job_events_history(job_id,id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
CREATE TABLE IF NOT EXISTS operational_events (
 id VARCHAR(32) PRIMARY KEY, at DOUBLE NOT NULL, boot_id VARCHAR(64) NOT NULL,
 job_id VARCHAR(64), request_id VARCHAR(64), event VARCHAR(100) NOT NULL,
 level VARCHAR(16) NOT NULL, code VARCHAR(100), stage VARCHAR(100),
 details_json LONGTEXT NOT NULL DEFAULT '{}',
 KEY operational_events_job(job_id,at), KEY operational_events_boot(boot_id,at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
UPDATE jobs SET error_code='storage_not_mounted',error_stage='storage',
 action='Revisá el montaje persistente de la carpeta de datos en el recurso de despliegue.'
 WHERE kind='warmup' AND error LIKE 'Falta un montaje persistente%';
