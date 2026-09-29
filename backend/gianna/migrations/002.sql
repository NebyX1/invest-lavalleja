CREATE TABLE embedding_cache(
 fingerprint TEXT NOT NULL, embedding_hash TEXT NOT NULL, dense_json TEXT NOT NULL, sparse_json TEXT NOT NULL,
 created_at REAL NOT NULL, PRIMARY KEY(fingerprint,embedding_hash)
);
