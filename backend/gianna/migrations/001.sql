CREATE TABLE IF NOT EXISTS schema_versions(version INTEGER PRIMARY KEY, applied_at REAL NOT NULL);
CREATE TABLE users(
 id TEXT PRIMARY KEY, email TEXT UNIQUE NOT NULL, name TEXT NOT NULL, role TEXT NOT NULL CHECK(role IN ('owner','editor','viewer')),
 password_hash TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1, mfa_method TEXT NOT NULL DEFAULT 'totp' CHECK(mfa_method IN ('totp','email')),
 totp_secret TEXT, totp_last_step INTEGER NOT NULL DEFAULT -1, mfa_enrolled INTEGER NOT NULL DEFAULT 0,
 created_at REAL NOT NULL, last_login REAL, must_change_password INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE auth_challenges(
 id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE, kind TEXT NOT NULL,
 code_hash TEXT, secret TEXT, attempts INTEGER NOT NULL DEFAULT 0, expires_at REAL NOT NULL, consumed INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE admin_sessions(
 id_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 created_at REAL NOT NULL, touched_at REAL NOT NULL, expires_at REAL NOT NULL, reauthenticated_at REAL NOT NULL
);
CREATE TABLE recovery_codes(user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE, code_hash TEXT NOT NULL, PRIMARY KEY(user_id,code_hash));
CREATE TABLE rate_limits(key TEXT NOT NULL, bucket INTEGER NOT NULL, count INTEGER NOT NULL, PRIMARY KEY(key,bucket));
CREATE TABLE settings(key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE bases(
 id TEXT PRIMARY KEY, name TEXT NOT NULL, description TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'draft',
 revision INTEGER NOT NULL DEFAULT 1, created_at REAL NOT NULL, updated_at REAL NOT NULL,
 source_filename TEXT, source_sha256 TEXT, document_json TEXT NOT NULL DEFAULT '{}', report_json TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE records(
 id INTEGER PRIMARY KEY AUTOINCREMENT, base_id TEXT NOT NULL REFERENCES bases(id) ON DELETE CASCADE,
 record_key TEXT NOT NULL, title TEXT NOT NULL, topic TEXT NOT NULL, audience TEXT NOT NULL CHECK(audience IN ('public','internal')),
 evidence_type TEXT NOT NULL, enabled INTEGER NOT NULL DEFAULT 1, approved INTEGER NOT NULL DEFAULT 0,
 content_json TEXT NOT NULL, updated_at REAL NOT NULL, reviewed_by TEXT, UNIQUE(base_id,record_key)
);
CREATE INDEX record_filters ON records(base_id,audience,approved,topic);
CREATE TABLE sources(base_id TEXT NOT NULL REFERENCES bases(id) ON DELETE CASCADE, source_key TEXT NOT NULL, content_json TEXT NOT NULL, PRIMARY KEY(base_id,source_key));
CREATE TABLE versions(
 id TEXT PRIMARY KEY, base_id TEXT NOT NULL REFERENCES bases(id) ON DELETE CASCADE, revision INTEGER NOT NULL,
 status TEXT NOT NULL DEFAULT 'queued', collection_name TEXT UNIQUE NOT NULL, profile_json TEXT NOT NULL DEFAULT '{}',
 chunk_count INTEGER NOT NULL DEFAULT 0, created_at REAL NOT NULL, published_at REAL, report_json TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE version_records(
 version_id TEXT NOT NULL REFERENCES versions(id) ON DELETE CASCADE, record_key TEXT NOT NULL, content_json TEXT NOT NULL,
 PRIMARY KEY(version_id,record_key)
);
CREATE TABLE version_sources(version_id TEXT NOT NULL REFERENCES versions(id) ON DELETE CASCADE, source_key TEXT NOT NULL, content_json TEXT NOT NULL, PRIMARY KEY(version_id,source_key));
CREATE TABLE chunks(
 id TEXT PRIMARY KEY, version_id TEXT NOT NULL REFERENCES versions(id) ON DELETE CASCADE, record_key TEXT NOT NULL,
 position INTEGER NOT NULL, title TEXT NOT NULL, topic TEXT NOT NULL, token_count INTEGER NOT NULL,
 text TEXT NOT NULL, content_json TEXT NOT NULL, embedding_hash TEXT NOT NULL, vector_json TEXT, projection_x REAL, projection_y REAL
);
CREATE INDEX chunk_version ON chunks(version_id,record_key,position);
CREATE TABLE active_knowledge(singleton INTEGER PRIMARY KEY CHECK(singleton=1), version_id TEXT REFERENCES versions(id));
INSERT INTO active_knowledge(singleton,version_id) VALUES(1,NULL);
CREATE TABLE jobs(
 id TEXT PRIMARY KEY, kind TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'queued', base_id TEXT,
 version_id TEXT, payload_json TEXT NOT NULL, progress INTEGER NOT NULL DEFAULT 0, total INTEGER NOT NULL DEFAULT 0,
 message TEXT NOT NULL DEFAULT '', error TEXT, created_at REAL NOT NULL, started_at REAL, finished_at REAL,
 cancel_requested INTEGER NOT NULL DEFAULT 0, lease_until REAL, owner_token TEXT, result_json TEXT
);
CREATE INDEX jobs_queue ON jobs(status,created_at);
CREATE TABLE audit(id INTEGER PRIMARY KEY AUTOINCREMENT, at REAL NOT NULL, user_id TEXT, action TEXT NOT NULL, target TEXT, details_json TEXT NOT NULL DEFAULT '{}');
CREATE INDEX audit_at ON audit(at);
CREATE TABLE chat_sessions(
 id_hash TEXT PRIMARY KEY, created_at REAL NOT NULL, expires_at REAL NOT NULL, origin TEXT NOT NULL,
 history_encrypted TEXT, busy_until REAL NOT NULL DEFAULT 0
);
CREATE TABLE queries(
 id TEXT PRIMARY KEY, at REAL NOT NULL, session_hash TEXT, version_id TEXT, mode TEXT NOT NULL, status TEXT NOT NULL,
 topic TEXT, retrieval_ms REAL NOT NULL DEFAULT 0, generation_ms REAL NOT NULL DEFAULT 0, total_ms REAL NOT NULL DEFAULT 0,
 source_ids_json TEXT NOT NULL DEFAULT '[]', prompt_tokens INTEGER, output_tokens INTEGER,
 feedback INTEGER CHECK(feedback IN (-1,1)), question_hash TEXT, error_code TEXT
);
CREATE INDEX queries_at ON queries(at);
