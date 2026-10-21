-- Restore the defaults expected by the application and the original schema.
-- Changing defaults does not rewrite existing data or disable strict SQL mode.
ALTER TABLE bases
 ALTER COLUMN description SET DEFAULT '',
 ALTER COLUMN document_json SET DEFAULT '{}',
 ALTER COLUMN report_json SET DEFAULT '{}';
ALTER TABLE versions
 ALTER COLUMN profile_json SET DEFAULT '{}',
 ALTER COLUMN report_json SET DEFAULT '{}';
ALTER TABLE audit ALTER COLUMN details_json SET DEFAULT '{}';
ALTER TABLE queries
 ALTER COLUMN source_ids_json SET DEFAULT '[]',
 ALTER COLUMN retrieval_trace_json SET DEFAULT '{}',
 ALTER COLUMN cited_source_ids_json SET DEFAULT '[]';
