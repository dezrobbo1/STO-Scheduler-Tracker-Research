-- STO V002: the per-activity result projection ADR-006 deferred.
--
-- ADR-006 shipped the version envelope without result columns, on the grounds
-- that the engine did not exist: no backward pass, no criticality definition,
-- and no result type for the columns to mirror. Building them first would have
-- meant choosing units, nullability and a criticality rule before the slices
-- that settle them, in a table versions already pointed at. S3 to S6 settled
-- all three, so the columns mirror sto.core.engine.result.
--
-- A calculation is not a property of a version. The same document computed
-- over a wider horizon, or under a different progress policy, is a different
-- answer, and a stored row that did not say which would be unreadable a month
-- later. So the run is a row of its own carrying everything that decided the
-- numbers, and the per-activity rows hang off it.
--
-- Nothing here is updated. A recalculation is a new calculation row, exactly
-- as a change to a schedule is a new version.
--
-- Schedule dates are TIMESTAMP, not TIMESTAMPTZ, and the difference is not
-- pedantry. A Microsoft Project date is wall-clock in the project's own
-- calendar and carries no offset; the canonical model keeps it that way, and
-- the calendars are compiled against it. Storing one as TIMESTAMPTZ would
-- attach an offset the source never had, and the same row read back in
-- another session timezone would name a different hour of the working day.
-- computed_at is TIMESTAMPTZ because it is a real instant: when the engine
-- ran, not when the work is planned.

CREATE TABLE schedule_calculations (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id UUID NOT NULL REFERENCES projects(id),
  version_id UUID NOT NULL REFERENCES schedule_versions(id),
  canonical_hash TEXT NOT NULL,
  result_fingerprint TEXT NOT NULL,
  epoch TIMESTAMP NOT NULL,
  horizon_start TIMESTAMP NOT NULL,
  horizon_finish TIMESTAMP NOT NULL,
  progress_policy TEXT NOT NULL,
  critical_float_threshold BIGINT NOT NULL,
  status_time TIMESTAMP,
  status_time_outside_window BOOLEAN NOT NULL DEFAULT FALSE,
  resource_calendars_apply BOOLEAN NOT NULL DEFAULT TRUE,
  relationship_dispositions JSONB NOT NULL DEFAULT '[]'::jsonb,
  profiles JSONB NOT NULL,
  computed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT schedule_calculations_canonical_hash_check
    CHECK (canonical_hash ~ '^[0-9a-f]{64}$'),
  CONSTRAINT schedule_calculations_fingerprint_check
    CHECK (result_fingerprint ~ '^[0-9a-f]{64}$'),
  CONSTRAINT schedule_calculations_horizon_check CHECK (horizon_finish > horizon_start),
  CONSTRAINT schedule_calculations_profiles_object_check CHECK (jsonb_typeof(profiles) = 'object'),
  CONSTRAINT schedule_calculations_relationships_array_check
    CHECK (jsonb_typeof(relationship_dispositions) = 'array'),
  -- A status date that fell outside the compiled window was dropped, so the
  -- passes ran without one. The two facts cannot both be present.
  CONSTRAINT schedule_calculations_status_window_check
    CHECK (NOT status_time_outside_window OR status_time IS NULL),
  CONSTRAINT schedule_calculations_version_fingerprint_unique
    UNIQUE (version_id, result_fingerprint)
);

COMMENT ON TABLE schedule_calculations IS
  'One run of the engine over one schedule version. Immutable; a recalculation is a new row.';
COMMENT ON COLUMN schedule_calculations.canonical_hash IS
  'The hash of the document computed from, so a result names its input rather than being trusted to belong to it.';
COMMENT ON COLUMN schedule_calculations.result_fingerprint IS
  'SHA-256 over the rows and their provenance. Two runs that agree hash alike.';
COMMENT ON COLUMN schedule_calculations.horizon_start IS
  'The compiled window is the caller''s choice, not the file''s, and a pass over a wider one is a different calculation.';
COMMENT ON COLUMN schedule_calculations.status_time IS
  'The status date the passes used. NULL with status_time_outside_window true means the source carried one and it was dropped.';
COMMENT ON COLUMN schedule_calculations.resource_calendars_apply IS
  'Whether resource calendars were applied when the plan was built. The caller''s choice, and it moves the dates on any schedule with assignments.';
COMMENT ON COLUMN schedule_calculations.relationship_dispositions IS
  'Edges the plan dropped and edges it kept under a labelled assumption: what decided these dates besides the activities themselves.';
COMMENT ON COLUMN schedule_calculations.profiles IS
  'The engine profile of every stage that contributed, so a rule change cannot be mistaken for the old rule.';

CREATE TABLE activity_results (
  calculation_id UUID NOT NULL REFERENCES schedule_calculations(id) ON DELETE CASCADE,
  activity_uid UUID NOT NULL,
  disposition TEXT NOT NULL,
  early_start TIMESTAMP,
  early_finish TIMESTAMP,
  late_start TIMESTAMP,
  late_finish TIMESTAMP,
  remaining_start TIMESTAMP,
  total_float_seconds BIGINT,
  free_float_seconds BIGINT,
  start_float_seconds BIGINT,
  finish_float_seconds BIGINT,
  critical BOOLEAN,
  progress_state TEXT,
  placed_by TEXT,
  driving_relationship_uid UUID,
  late_placed_by TEXT,
  late_driving_relationship_uid UUID,
  constraint_override TEXT,
  exclusion_code TEXT,
  exclusion_detail TEXT,
  assumptions TEXT[] NOT NULL DEFAULT '{}',
  PRIMARY KEY (calculation_id, activity_uid),
  CONSTRAINT activity_results_disposition_check
    CHECK (disposition IN ('scheduled', 'excluded')),
  CONSTRAINT activity_results_progress_state_check
    CHECK (progress_state IS NULL OR progress_state IN ('not_started', 'in_progress', 'complete')),
  -- A scheduled row has all four dates and a float; an excluded row has none
  -- of them and a code. Half a row would be a date that means nothing.
  CONSTRAINT activity_results_scheduled_is_complete CHECK (
    (disposition = 'scheduled'
      AND early_start IS NOT NULL AND early_finish IS NOT NULL
      AND late_start IS NOT NULL AND late_finish IS NOT NULL
      AND total_float_seconds IS NOT NULL AND free_float_seconds IS NOT NULL
      AND start_float_seconds IS NOT NULL AND finish_float_seconds IS NOT NULL
      AND total_float_seconds = least(start_float_seconds, finish_float_seconds)
      AND critical IS NOT NULL AND progress_state IS NOT NULL
      AND exclusion_code IS NULL)
    OR
    (disposition = 'excluded'
      AND early_start IS NULL AND early_finish IS NULL
      AND late_start IS NULL AND late_finish IS NULL
      AND remaining_start IS NULL
      AND total_float_seconds IS NULL AND free_float_seconds IS NULL
      AND start_float_seconds IS NULL AND finish_float_seconds IS NULL
      AND critical IS NULL AND progress_state IS NULL
      AND exclusion_code IS NOT NULL)
  ),
  -- Remaining start is where the unfinished part of work under way begins, so
  -- it belongs to the in-progress rows and to no others. Without this the
  -- excluded branch above is the only rule it has, and a scheduled row could
  -- carry one while claiming not to have started.
  CONSTRAINT activity_results_remaining_start_is_progress CHECK (
    progress_state IS NULL
    OR (remaining_start IS NOT NULL) = (progress_state = 'in_progress')
  ),
  CONSTRAINT activity_results_remaining_start_within_span CHECK (
    remaining_start IS NULL
    OR (remaining_start >= early_start AND remaining_start <= early_finish)
  ),
  CONSTRAINT activity_results_span_ordered
    CHECK (early_finish IS NULL OR early_finish >= early_start),
  CONSTRAINT activity_results_late_span_ordered
    CHECK (late_finish IS NULL OR late_finish >= late_start)
);

COMMENT ON TABLE activity_results IS
  'One row per activity of one calculation: the answer, or the coded reason there is none.';
COMMENT ON COLUMN activity_results.start_float_seconds IS
  'One of the two readings total float is the smaller of. They differ when the early and late spans straddle a calendar gap differently.';
COMMENT ON COLUMN activity_results.remaining_start IS
  'Where the unfinished part of work under way begins. Set for exactly the in-progress rows.';
COMMENT ON COLUMN activity_results.placed_by IS
  'What put the activity where it is: a predecessor, the project start, a constraint, its actuals, or the status date.';
COMMENT ON COLUMN activity_results.late_placed_by IS
  'What bounded the late span. In a chain this is a successor, not the predecessor that bounded the early one.';
COMMENT ON COLUMN activity_results.constraint_override IS
  'A hard constraint that overrode precedence, and the coordinate the logic required instead. NULL when none did.';
COMMENT ON COLUMN activity_results.assumptions IS
  'Codes from Plan.assumed: the rules this row rests on that are labelled rather than measured.';

CREATE TABLE summary_results (
  calculation_id UUID NOT NULL REFERENCES schedule_calculations(id) ON DELETE CASCADE,
  wbs_uid UUID NOT NULL,
  span_start TIMESTAMP,
  span_finish TIMESTAMP,
  placed INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (calculation_id, wbs_uid),
  CONSTRAINT summary_results_span_ordered
    CHECK (span_finish IS NULL OR span_finish >= span_start),
  -- A branch with nothing placed beneath it has no span rather than a guessed
  -- one, and says so by carrying neither date and a count of zero.
  CONSTRAINT summary_results_empty_has_no_span CHECK (
    (placed = 0 AND span_start IS NULL AND span_finish IS NULL)
    OR (placed > 0 AND span_start IS NOT NULL AND span_finish IS NOT NULL)
  )
);

COMMENT ON TABLE summary_results IS
  'One row per WBS node of one calculation: the span rolled up from what sits beneath it.';
COMMENT ON COLUMN summary_results.placed IS
  'Placed rows anywhere beneath this node, so an empty branch is visibly empty rather than absent.';

CREATE INDEX idx_schedule_calculations_version ON schedule_calculations(version_id, computed_at DESC);
CREATE INDEX idx_activity_results_activity ON activity_results(activity_uid);
