ALTER TABLE queries ADD COLUMN retrieval_trace_json TEXT NOT NULL DEFAULT '{}';
ALTER TABLE queries ADD COLUMN cited_source_ids_json TEXT NOT NULL DEFAULT '[]';
