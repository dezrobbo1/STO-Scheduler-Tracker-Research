-- STO V004: one explicit changed input for each planner scenario version.
--
-- The canonical schedule remains the scheduling authority and every edit is
-- still a complete immutable schedule_versions row.  This table records the
-- small piece of lineage a planner needs beside it: which baseline the
-- scenario derives from and which planned duration changed.  It deliberately
-- models only PL14's one editable field.

CREATE TABLE scenario_changes (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id UUID NOT NULL REFERENCES projects(id),
  baseline_version_id UUID NOT NULL REFERENCES schedule_versions(id),
  scenario_version_id UUID NOT NULL UNIQUE REFERENCES schedule_versions(id),
  activity_uid UUID NOT NULL,
  field TEXT NOT NULL DEFAULT 'planned_duration_seconds',
  before_seconds BIGINT NOT NULL,
  after_seconds BIGINT NOT NULL,
  remaining_before_seconds BIGINT,
  remaining_after_seconds BIGINT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  created_by_user_id UUID,
  CONSTRAINT scenario_changes_field_check
    CHECK (field = 'planned_duration_seconds'),
  CONSTRAINT scenario_changes_before_check CHECK (before_seconds > 0),
  CONSTRAINT scenario_changes_after_check CHECK (after_seconds > 0),
  CONSTRAINT scenario_changes_remaining_pair_check CHECK (
    (remaining_before_seconds IS NULL AND remaining_after_seconds IS NULL)
    OR (remaining_before_seconds IS NOT NULL AND remaining_after_seconds IS NOT NULL
        AND remaining_before_seconds > 0 AND remaining_after_seconds > 0)
  ),
  CONSTRAINT scenario_changes_changed_check CHECK (before_seconds <> after_seconds),
  CONSTRAINT scenario_changes_versions_differ_check
    CHECK (baseline_version_id <> scenario_version_id)
);

COMMENT ON TABLE scenario_changes IS
  'The single planned-duration edit represented by an immutable scenario version.';
COMMENT ON COLUMN scenario_changes.baseline_version_id IS
  'The immutable imported baseline from which the scenario document was derived.';

CREATE FUNCTION validate_scenario_change_lineage() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
  baseline_project UUID;
  baseline_kind TEXT;
  scenario_project UUID;
  scenario_kind TEXT;
  scenario_parent UUID;
  scenario_cause UUID;
  scenario_cause_type TEXT;
BEGIN
  SELECT project_id, kind
    INTO baseline_project, baseline_kind
    FROM schedule_versions WHERE id = NEW.baseline_version_id;
  SELECT project_id, kind, parent_id, cause_id, cause_type
    INTO scenario_project, scenario_kind, scenario_parent, scenario_cause, scenario_cause_type
    FROM schedule_versions WHERE id = NEW.scenario_version_id;

  IF baseline_project IS DISTINCT FROM NEW.project_id
     OR scenario_project IS DISTINCT FROM NEW.project_id
     OR baseline_kind <> 'baseline'
     OR scenario_kind <> 'scenario'
     OR scenario_parent IS DISTINCT FROM NEW.baseline_version_id
     OR scenario_cause_type <> 'planner_edit'
     OR scenario_cause IS DISTINCT FROM NEW.id THEN
    RAISE EXCEPTION 'invalid scenario change lineage'
      USING ERRCODE = '23514';
  END IF;
  RETURN NEW;
END;
$$;

CREATE TRIGGER scenario_changes_lineage_is_valid
BEFORE INSERT OR UPDATE ON scenario_changes
FOR EACH ROW EXECUTE FUNCTION validate_scenario_change_lineage();

CREATE FUNCTION refuse_scenario_change_mutation() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'scenario change lineage is immutable'
    USING ERRCODE = '23514';
END;
$$;

CREATE TRIGGER scenario_changes_are_immutable
BEFORE UPDATE OR DELETE ON scenario_changes
FOR EACH ROW EXECUTE FUNCTION refuse_scenario_change_mutation();

CREATE INDEX idx_scenario_changes_project_created
  ON scenario_changes(project_id, created_at DESC);
