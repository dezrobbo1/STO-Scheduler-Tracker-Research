-- STO V001: projects, source files, import batches, and the schedule-version envelope.
--
-- projects, source_files and import_batches are Shutdown-Tracker-Claude's V002,
-- with its PostgreSQL enums replaced by TEXT + CHECK (ADR-006 there was the
-- lesson: an enum rebuild is a migration of its own). project_snapshots is not
-- carried: an accepted import is a schedule version of kind 'baseline', and one
-- envelope holds every kind of version this product has (ADR-007).
--
-- A version is immutable. The head for each (project, kind) is a pointer that
-- moves; that is how a working copy exists without anything being mutated.
-- Every version carries the full canonical document and the identity map that
-- produced it; deltas arrive with the live loop, when there is something to
-- delta against.

CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE projects (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name TEXT NOT NULL,
  description TEXT,
  status TEXT NOT NULL DEFAULT 'active',
  timezone TEXT NOT NULL DEFAULT 'UTC',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  created_by_user_id UUID,
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  CONSTRAINT projects_status_check CHECK (status IN ('draft', 'active', 'archived')),
  CONSTRAINT projects_metadata_object_check CHECK (jsonb_typeof(metadata) = 'object')
);

COMMENT ON TABLE projects IS 'One shutdown, turnaround or outage. The scope every schedule version belongs to.';
COMMENT ON COLUMN projects.timezone IS 'IANA zone of the site. Schedules carry wall-clock times; this says where the clock is.';

CREATE TABLE source_files (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id UUID NOT NULL REFERENCES projects(id),
  original_filename TEXT NOT NULL,
  file_kind TEXT NOT NULL,
  storage_uri TEXT NOT NULL,
  content_hash TEXT NOT NULL,
  size_bytes BIGINT NOT NULL,
  uploaded_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  uploaded_by_user_id UUID,
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  CONSTRAINT source_files_file_kind_check
    CHECK (file_kind IN ('mspdi_xml', 'mpp', 'xer', 'pmxml', 'csv', 'other')),
  CONSTRAINT source_files_content_hash_check CHECK (content_hash ~ '^[0-9a-f]{64}$'),
  CONSTRAINT source_files_size_bytes_check CHECK (size_bytes >= 0),
  CONSTRAINT source_files_metadata_object_check CHECK (jsonb_typeof(metadata) = 'object')
);

COMMENT ON TABLE source_files IS 'An uploaded schedule file, immutable. The bytes live on disk at storage_uri; the row is the hash and provenance.';
COMMENT ON COLUMN source_files.content_hash IS 'SHA-256 of the bytes. What every evidence record and canonical document cites as its source.';

CREATE TABLE import_batches (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id UUID NOT NULL REFERENCES projects(id),
  source_file_id UUID NOT NULL REFERENCES source_files(id),
  status TEXT NOT NULL,
  parser_name TEXT,
  parser_version TEXT,
  started_at TIMESTAMPTZ,
  completed_at TIMESTAMPTZ,
  warning_count INTEGER NOT NULL DEFAULT 0,
  error_count INTEGER NOT NULL DEFAULT 0,
  parse_summary JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  created_by_user_id UUID,
  CONSTRAINT import_batches_status_check
    CHECK (status IN ('pending', 'parsing', 'parsed', 'accepted', 'failed', 'superseded')),
  CONSTRAINT import_batches_warning_count_check CHECK (warning_count >= 0),
  CONSTRAINT import_batches_error_count_check CHECK (error_count >= 0),
  CONSTRAINT import_batches_parse_summary_object_check CHECK (jsonb_typeof(parse_summary) = 'object'),
  CONSTRAINT import_batches_completed_after_started_check CHECK (
    started_at IS NULL OR completed_at IS NULL OR completed_at >= started_at
  )
);

COMMENT ON TABLE import_batches IS 'One parser run against one source file. Its result, if accepted, is a baseline schedule version.';

CREATE TABLE schedule_versions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id UUID NOT NULL REFERENCES projects(id),
  kind TEXT NOT NULL,
  sequence INTEGER NOT NULL,
  parent_id UUID REFERENCES schedule_versions(id),
  canonical_hash TEXT NOT NULL,
  schema_version TEXT NOT NULL,
  engine_profile TEXT,
  cause_type TEXT NOT NULL,
  cause_id UUID,
  document JSONB NOT NULL,
  identity_map JSONB NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  created_by_user_id UUID,
  CONSTRAINT schedule_versions_kind_check
    CHECK (kind IN ('baseline', 'approved_forecast', 'live_working', 'scenario')),
  CONSTRAINT schedule_versions_cause_type_check
    CHECK (cause_type IN ('import', 'progress', 'planner_edit', 'review', 'promotion')),
  CONSTRAINT schedule_versions_sequence_check CHECK (sequence > 0),
  CONSTRAINT schedule_versions_canonical_hash_check CHECK (canonical_hash ~ '^[0-9a-f]{64}$'),
  CONSTRAINT schedule_versions_document_object_check CHECK (jsonb_typeof(document) = 'object'),
  CONSTRAINT schedule_versions_identity_object_check CHECK (jsonb_typeof(identity_map) = 'object'),
  CONSTRAINT schedule_versions_project_sequence_unique UNIQUE (project_id, sequence)
);

COMMENT ON TABLE schedule_versions IS 'Immutable canonical schedule documents. Never updated; a change is a new row with a parent.';
COMMENT ON COLUMN schedule_versions.canonical_hash IS 'SHA-256 of the canonical JSON bytes of document, computed before storage and re-verified on load.';
COMMENT ON COLUMN schedule_versions.engine_profile IS 'Null until an engine has computed dates for this version.';
COMMENT ON COLUMN schedule_versions.identity_map IS 'The durable identity map after this version, so a later import reconciles against it.';

CREATE TABLE schedule_heads (
  project_id UUID NOT NULL REFERENCES projects(id),
  kind TEXT NOT NULL,
  version_id UUID NOT NULL REFERENCES schedule_versions(id),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT schedule_heads_kind_check
    CHECK (kind IN ('baseline', 'approved_forecast', 'live_working', 'scenario')),
  PRIMARY KEY (project_id, kind)
);

COMMENT ON TABLE schedule_heads IS 'The current version of each kind for a project. The only thing here that moves.';

CREATE INDEX idx_projects_status ON projects(status);
CREATE INDEX idx_source_files_project_uploaded ON source_files(project_id, uploaded_at DESC);
CREATE INDEX idx_source_files_project_hash ON source_files(project_id, content_hash);
CREATE INDEX idx_import_batches_project_created ON import_batches(project_id, created_at DESC);
CREATE INDEX idx_import_batches_source_file ON import_batches(source_file_id);
CREATE INDEX idx_schedule_versions_project_kind_created ON schedule_versions(project_id, kind, created_at DESC);
CREATE INDEX idx_schedule_versions_cause ON schedule_versions(cause_type, cause_id);
