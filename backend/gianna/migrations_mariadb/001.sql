CREATE TABLE IF NOT EXISTS users (
 id VARCHAR(255) PRIMARY KEY, email VARCHAR(320) NOT NULL UNIQUE, name VARCHAR(255) NOT NULL,
 role VARCHAR(32) NOT NULL CHECK(role IN ('owner','editor','viewer')), password_hash VARCHAR(255) NOT NULL,
 active INTEGER NOT NULL DEFAULT 1, mfa_method VARCHAR(16) NOT NULL DEFAULT 'totp' CHECK(mfa_method IN ('totp','email')),
 totp_secret TEXT, totp_last_step BIGINT NOT NULL DEFAULT -1, mfa_enrolled INTEGER NOT NULL DEFAULT 0,
 created_at DOUBLE NOT NULL, last_login DOUBLE, must_change_password INTEGER NOT NULL DEFAULT 0
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
CREATE TABLE IF NOT EXISTS auth_challenges (
 id VARCHAR(255) PRIMARY KEY, user_id VARCHAR(255) NOT NULL, kind VARCHAR(32) NOT NULL,
 code_hash VARCHAR(255), secret TEXT, attempts INTEGER NOT NULL DEFAULT 0,
 expires_at DOUBLE NOT NULL, consumed INTEGER NOT NULL DEFAULT 0,
 CONSTRAINT fk_auth_challenges_user FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
CREATE TABLE IF NOT EXISTS admin_sessions (
 id_hash VARCHAR(255) PRIMARY KEY, user_id VARCHAR(255) NOT NULL,
 created_at DOUBLE NOT NULL, touched_at DOUBLE NOT NULL, expires_at DOUBLE NOT NULL, reauthenticated_at DOUBLE NOT NULL,
 CONSTRAINT fk_admin_sessions_user FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
CREATE TABLE IF NOT EXISTS recovery_codes (
 user_id VARCHAR(255) NOT NULL, code_hash VARCHAR(255) NOT NULL, PRIMARY KEY(user_id,code_hash),
 CONSTRAINT fk_recovery_codes_user FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
CREATE TABLE IF NOT EXISTS rate_limits (
 `key` VARCHAR(255) NOT NULL, bucket BIGINT NOT NULL, count BIGINT NOT NULL, PRIMARY KEY(`key`,bucket)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
CREATE TABLE IF NOT EXISTS settings (`key` VARCHAR(191) PRIMARY KEY, value LONGTEXT NOT NULL)
 ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
CREATE TABLE IF NOT EXISTS bases (
 id VARCHAR(255) PRIMARY KEY, name VARCHAR(255) NOT NULL, description TEXT NOT NULL,
 status VARCHAR(32) NOT NULL DEFAULT 'draft', revision INTEGER NOT NULL DEFAULT 1,
 created_at DOUBLE NOT NULL, updated_at DOUBLE NOT NULL, source_filename VARCHAR(512), source_sha256 VARCHAR(64),
 document_json LONGTEXT NOT NULL, report_json LONGTEXT NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
CREATE TABLE IF NOT EXISTS records (
 id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY, base_id VARCHAR(255) NOT NULL,
 record_key VARCHAR(512) NOT NULL, title VARCHAR(512) NOT NULL, topic VARCHAR(255) NOT NULL,
 audience VARCHAR(16) NOT NULL CHECK(audience IN ('public','internal')), evidence_type VARCHAR(64) NOT NULL,
 enabled INTEGER NOT NULL DEFAULT 1, approved INTEGER NOT NULL DEFAULT 0, content_json LONGTEXT NOT NULL,
 updated_at DOUBLE NOT NULL, reviewed_by VARCHAR(255), UNIQUE KEY uq_records_base_key(base_id,record_key),
 KEY record_filters(base_id,audience,approved,topic),
 CONSTRAINT fk_records_base FOREIGN KEY(base_id) REFERENCES bases(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
CREATE TABLE IF NOT EXISTS sources (
 base_id VARCHAR(255) NOT NULL, source_key VARCHAR(512) NOT NULL, content_json LONGTEXT NOT NULL,
 PRIMARY KEY(base_id,source_key), CONSTRAINT fk_sources_base FOREIGN KEY(base_id) REFERENCES bases(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
CREATE TABLE IF NOT EXISTS versions (
 id VARCHAR(255) PRIMARY KEY, base_id VARCHAR(255) NOT NULL, revision INTEGER NOT NULL,
 status VARCHAR(32) NOT NULL DEFAULT 'queued', collection_name VARCHAR(191) NOT NULL UNIQUE,
 profile_json LONGTEXT NOT NULL, chunk_count INTEGER NOT NULL DEFAULT 0, created_at DOUBLE NOT NULL,
 published_at DOUBLE, report_json LONGTEXT NOT NULL,
 CONSTRAINT fk_versions_base FOREIGN KEY(base_id) REFERENCES bases(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
CREATE TABLE IF NOT EXISTS version_records (
 version_id VARCHAR(255) NOT NULL, record_key VARCHAR(512) NOT NULL, content_json LONGTEXT NOT NULL,
 PRIMARY KEY(version_id,record_key), CONSTRAINT fk_version_records_version FOREIGN KEY(version_id) REFERENCES versions(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
CREATE TABLE IF NOT EXISTS version_sources (
 version_id VARCHAR(255) NOT NULL, source_key VARCHAR(512) NOT NULL, content_json LONGTEXT NOT NULL,
 PRIMARY KEY(version_id,source_key), CONSTRAINT fk_version_sources_version FOREIGN KEY(version_id) REFERENCES versions(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
CREATE TABLE IF NOT EXISTS chunks (
 id VARCHAR(255) PRIMARY KEY, version_id VARCHAR(255) NOT NULL, record_key VARCHAR(512) NOT NULL,
 position INTEGER NOT NULL, title VARCHAR(512) NOT NULL, topic VARCHAR(255) NOT NULL, token_count INTEGER NOT NULL,
 text LONGTEXT NOT NULL, content_json LONGTEXT NOT NULL, embedding_hash VARCHAR(191) NOT NULL,
 vector_json LONGTEXT, projection_x DOUBLE, projection_y DOUBLE,
 KEY chunk_version(version_id,record_key,position),
 CONSTRAINT fk_chunks_version FOREIGN KEY(version_id) REFERENCES versions(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
CREATE TABLE IF NOT EXISTS active_knowledge (
 singleton INTEGER PRIMARY KEY CHECK(singleton=1), version_id VARCHAR(255),
 CONSTRAINT fk_active_knowledge_version FOREIGN KEY(version_id) REFERENCES versions(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
INSERT IGNORE INTO active_knowledge(singleton,version_id) VALUES(1,NULL);
CREATE TABLE IF NOT EXISTS jobs (
 id VARCHAR(255) PRIMARY KEY, kind VARCHAR(64) NOT NULL, status VARCHAR(32) NOT NULL DEFAULT 'queued',
 base_id VARCHAR(255), version_id VARCHAR(255), payload_json LONGTEXT NOT NULL,
 progress INTEGER NOT NULL DEFAULT 0, total INTEGER NOT NULL DEFAULT 0, message VARCHAR(1024) NOT NULL DEFAULT '',
 error LONGTEXT, created_at DOUBLE NOT NULL, started_at DOUBLE, finished_at DOUBLE,
 cancel_requested INTEGER NOT NULL DEFAULT 0, lease_until DOUBLE, owner_token VARCHAR(255), result_json LONGTEXT,
 KEY jobs_queue(status,created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
CREATE TABLE IF NOT EXISTS audit (
 id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY, at DOUBLE NOT NULL, user_id VARCHAR(255),
 action VARCHAR(128) NOT NULL, target VARCHAR(512), details_json LONGTEXT NOT NULL,
 KEY audit_at(at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
CREATE TABLE IF NOT EXISTS chat_sessions (
 id_hash VARCHAR(255) PRIMARY KEY, created_at DOUBLE NOT NULL, expires_at DOUBLE NOT NULL,
 origin VARCHAR(512) NOT NULL, history_encrypted LONGTEXT, busy_until DOUBLE NOT NULL DEFAULT 0
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
CREATE TABLE IF NOT EXISTS queries (
 id VARCHAR(255) PRIMARY KEY, at DOUBLE NOT NULL, session_hash VARCHAR(255), version_id VARCHAR(255),
 mode VARCHAR(32) NOT NULL, status VARCHAR(32) NOT NULL, topic VARCHAR(255),
 retrieval_ms DOUBLE NOT NULL DEFAULT 0, generation_ms DOUBLE NOT NULL DEFAULT 0, total_ms DOUBLE NOT NULL DEFAULT 0,
 source_ids_json LONGTEXT NOT NULL, prompt_tokens INTEGER, output_tokens INTEGER,
 feedback INTEGER CHECK(feedback IN (-1,1)), question_hash VARCHAR(255), error_code VARCHAR(128),
 retrieval_trace_json LONGTEXT NOT NULL, cited_source_ids_json LONGTEXT NOT NULL,
 KEY queries_at(at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
CREATE TABLE IF NOT EXISTS embedding_cache (
 fingerprint VARCHAR(191) NOT NULL, embedding_hash VARCHAR(191) NOT NULL,
 dense_json LONGTEXT NOT NULL, sparse_json LONGTEXT NOT NULL, created_at DOUBLE NOT NULL,
 PRIMARY KEY(fingerprint,embedding_hash)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
CREATE TABLE IF NOT EXISTS captcha_challenges (
 id_hash VARCHAR(255) PRIMARY KEY, purpose VARCHAR(32) NOT NULL CHECK(purpose IN ('admin-login','chat-session')),
 origin VARCHAR(512) NOT NULL, answer_digest VARCHAR(255) NOT NULL, expires_at DOUBLE NOT NULL,
 KEY captcha_challenges_expiry(expires_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
