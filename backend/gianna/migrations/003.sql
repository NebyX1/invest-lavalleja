CREATE TABLE captcha_challenges(
 id_hash TEXT PRIMARY KEY,
 purpose TEXT NOT NULL CHECK(purpose IN ('admin-login','chat-session')),
 origin TEXT NOT NULL,
 answer_digest TEXT NOT NULL,
 expires_at REAL NOT NULL
);
CREATE INDEX captcha_challenges_expiry ON captcha_challenges(expires_at);
