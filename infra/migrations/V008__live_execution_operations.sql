-- Shared project change order; execution and later communication remain
-- different domain rows. A later slice may add its own kind/projection without
-- granting a communication row any path to the execution scheduler.
-- Writers hold the projects row lock while allocating server_sequence. An
-- aborted transaction exposes neither a sequence nor an authoritative effect.
CREATE TABLE project_committed_changes (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id UUID NOT NULL REFERENCES projects(id),
  server_sequence BIGINT NOT NULL CHECK (server_sequence > 0),
  kind TEXT NOT NULL CHECK (kind = 'execution'),
  source_id UUID NOT NULL,
  accepted_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  UNIQUE (project_id, server_sequence),
  UNIQUE (project_id, kind, source_id)
);

-- One committed execution operation and its immutable schedule result.
CREATE TABLE live_execution_operations (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id UUID NOT NULL REFERENCES projects(id),
  operation_id UUID NOT NULL,
  actor_user_id UUID NOT NULL REFERENCES users(id),
  semantic_schema INTEGER NOT NULL DEFAULT 1 CHECK (semantic_schema = 1),
  semantic_payload JSONB NOT NULL CHECK (jsonb_typeof(semantic_payload) = 'object'),
  semantic_fingerprint TEXT NOT NULL CHECK (semantic_fingerprint ~ '^[0-9a-f]{64}$'),
  baseline_version_id UUID NOT NULL REFERENCES schedule_versions(id),
  base_version_id UUID NOT NULL REFERENCES schedule_versions(id),
  base_calculation_id UUID NOT NULL REFERENCES schedule_calculations(id),
  result_version_id UUID NOT NULL REFERENCES schedule_versions(id),
  calculation_id UUID NOT NULL REFERENCES schedule_calculations(id),
  result_hash TEXT NOT NULL CHECK (result_hash ~ '^[0-9a-f]{64}$'),
  result_fingerprint TEXT NOT NULL CHECK (result_fingerprint ~ '^[0-9a-f]{64}$'),
  change_id UUID NOT NULL UNIQUE REFERENCES project_committed_changes(id),
  UNIQUE (project_id, operation_id),
  UNIQUE (result_version_id),
  UNIQUE (calculation_id)
);

CREATE FUNCTION refuse_live_execution_history_change() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'accepted execution history is append-only' USING ERRCODE = '23514';
END;
$$;

CREATE TRIGGER live_execution_history_immutable
BEFORE UPDATE OR DELETE ON live_execution_operations
FOR EACH ROW EXECUTE FUNCTION refuse_live_execution_history_change();

CREATE TRIGGER live_execution_history_no_truncate
BEFORE TRUNCATE ON live_execution_operations
FOR EACH STATEMENT EXECUTE FUNCTION refuse_live_execution_history_change();

CREATE TRIGGER project_committed_changes_immutable
BEFORE UPDATE OR DELETE ON project_committed_changes
FOR EACH ROW EXECUTE FUNCTION refuse_live_execution_history_change();

CREATE TRIGGER project_committed_changes_no_truncate
BEFORE TRUNCATE ON project_committed_changes
FOR EACH STATEMENT EXECUTE FUNCTION refuse_live_execution_history_change();
