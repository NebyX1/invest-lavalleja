ALTER TABLE jobs ADD COLUMN stage TEXT NOT NULL DEFAULT 'queued';
ALTER TABLE jobs ADD COLUMN error_code TEXT;
ALTER TABLE jobs ADD COLUMN error_stage TEXT;
ALTER TABLE jobs ADD COLUMN action TEXT;
ALTER TABLE jobs ADD COLUMN retryable INTEGER NOT NULL DEFAULT 0;
ALTER TABLE jobs ADD COLUMN heartbeat_at REAL;
ALTER TABLE jobs ADD COLUMN last_attempt_at REAL;
ALTER TABLE jobs ADD COLUMN boot_id TEXT;
ALTER TABLE jobs ADD COLUMN recovery_boot_id TEXT;
CREATE TABLE job_events (
 id INTEGER PRIMARY KEY AUTOINCREMENT, job_id TEXT NOT NULL, at REAL NOT NULL,
 event TEXT NOT NULL, attempt INTEGER NOT NULL DEFAULT 0, boot_id TEXT,
 stage TEXT, code TEXT, message TEXT NOT NULL DEFAULT '', details_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX job_events_history ON job_events(job_id,id);
CREATE TABLE operational_events (
 id TEXT PRIMARY KEY, at REAL NOT NULL, boot_id TEXT NOT NULL, job_id TEXT, request_id TEXT,
 event TEXT NOT NULL, level TEXT NOT NULL, code TEXT, stage TEXT,
 details_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX operational_events_job ON operational_events(job_id,at);
CREATE INDEX operational_events_boot ON operational_events(boot_id,at);
UPDATE jobs SET error_code='storage_not_mounted',error_stage='storage',
 action='Revisá el montaje persistente de la carpeta de datos en el recurso de despliegue.'
 WHERE kind='warmup' AND error LIKE 'Falta un montaje persistente%';
