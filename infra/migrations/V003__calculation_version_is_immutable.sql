-- A calculation belongs to the import version under which it was computed.
-- Identical documents may have equal hashes and different version identities.
CREATE FUNCTION refuse_calculation_version_change() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'a calculation cannot change schedule version'
    USING ERRCODE = '23514';
END;
$$;

CREATE TRIGGER schedule_calculations_version_is_immutable
BEFORE UPDATE OF version_id ON schedule_calculations
FOR EACH ROW WHEN (OLD.version_id IS DISTINCT FROM NEW.version_id)
EXECUTE FUNCTION refuse_calculation_version_change();
