-- Preserve both coordinates used by the backward pass for work in progress.
-- Project exposes the immutable actual start as LateStart, while the movable
-- remaining duration can start later (or, under negative float, finish before
-- that public coordinate). V002's public-span check could not represent that.

ALTER TABLE activity_results
  ADD COLUMN late_remaining_start TIMESTAMP;

ALTER TABLE activity_results
  DROP CONSTRAINT activity_results_late_span_ordered;

ALTER TABLE activity_results
  ADD CONSTRAINT activity_results_late_remaining_start_is_progress CHECK (
    late_remaining_start IS NULL
    OR (disposition = 'scheduled' AND progress_state = 'in_progress')
  ),
  ADD CONSTRAINT activity_results_late_span_ordered CHECK (
    late_finish IS NULL
    OR late_finish >= COALESCE(late_remaining_start, late_start)
  );

COMMENT ON COLUMN activity_results.late_remaining_start IS
  'Latest start of unfinished work. Distinct from public LateStart for in-progress rows; NULL on legacy result-profile-v1 calculations.';
