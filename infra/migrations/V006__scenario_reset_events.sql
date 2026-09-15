-- STO V006: append-only attribution for PL14 scenario resets.
--
-- A reset moves only the scenario head; immutable scenario versions,
-- calculations and their change records remain.  This table records the
-- authenticated decision that moved the planner back to its baseline.

CREATE TABLE scenario_reset_events (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id UUID NOT NULL REFERENCES projects(id),
  actor_user_id UUID NOT NULL REFERENCES users(id),
  prior_scenario_version_id UUID NOT NULL REFERENCES schedule_versions(id),
  restored_baseline_version_id UUID NOT NULL REFERENCES schedule_versions(id),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT scenario_reset_events_versions_differ_check
    CHECK (prior_scenario_version_id <> restored_baseline_version_id)
);

CREATE FUNCTION validate_scenario_reset_lineage() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
  scenario_project UUID;
  scenario_kind TEXT;
  scenario_parent UUID;
  baseline_project UUID;
  baseline_kind TEXT;
BEGIN
  SELECT project_id, kind, parent_id
    INTO scenario_project, scenario_kind, scenario_parent
    FROM schedule_versions WHERE id = NEW.prior_scenario_version_id;
  SELECT project_id, kind
    INTO baseline_project, baseline_kind
    FROM schedule_versions WHERE id = NEW.restored_baseline_version_id;

  IF scenario_project IS DISTINCT FROM NEW.project_id
     OR baseline_project IS DISTINCT FROM NEW.project_id
     OR scenario_kind <> 'scenario'
     OR baseline_kind <> 'baseline'
     OR scenario_parent IS DISTINCT FROM NEW.restored_baseline_version_id THEN
    RAISE EXCEPTION 'invalid scenario reset lineage'
      USING ERRCODE = '23514';
  END IF;
  RETURN NEW;
END;
$$;

CREATE TRIGGER scenario_reset_events_lineage_is_valid
BEFORE INSERT OR UPDATE ON scenario_reset_events
FOR EACH ROW EXECUTE FUNCTION validate_scenario_reset_lineage();

CREATE FUNCTION refuse_scenario_reset_event_mutation() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'scenario reset events are append-only'
    USING ERRCODE = '23514';
END;
$$;

CREATE TRIGGER scenario_reset_events_are_append_only
BEFORE UPDATE OR DELETE ON scenario_reset_events
FOR EACH ROW EXECUTE FUNCTION refuse_scenario_reset_event_mutation();

CREATE TRIGGER scenario_reset_events_refuse_truncate
BEFORE TRUNCATE ON scenario_reset_events
FOR EACH STATEMENT EXECUTE FUNCTION refuse_scenario_reset_event_mutation();

CREATE INDEX idx_scenario_reset_events_project_created
  ON scenario_reset_events(project_id, created_at DESC);

COMMENT ON TABLE scenario_reset_events IS
  'Authenticated append-only decisions that move the PL14 planner from a scenario to its baseline.';
