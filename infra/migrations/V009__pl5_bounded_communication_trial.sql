-- Bounded PL5 trial domain. PL15 retains the permanent communication product.
-- A message or media link has no foreign key or route into schedule versions.
ALTER TABLE project_committed_changes DROP CONSTRAINT project_committed_changes_kind_check;
ALTER TABLE project_committed_changes ADD CONSTRAINT project_committed_changes_kind_check
  CHECK (kind IN ('execution', 'trial_message', 'trial_media_link'));

CREATE TABLE pl5_trial_messages (
  id UUID NOT NULL,
  project_id UUID NOT NULL REFERENCES projects(id),
  actor_user_id UUID NOT NULL REFERENCES users(id),
  activity_uid UUID NOT NULL,
  version_id UUID NOT NULL REFERENCES schedule_versions(id),
  body TEXT NOT NULL CHECK (length(body) BETWEEN 1 AND 2000),
  semantic_fingerprint TEXT NOT NULL CHECK (semantic_fingerprint ~ '^[0-9a-f]{64}$'),
  change_id UUID NOT NULL UNIQUE REFERENCES project_committed_changes(id),
  PRIMARY KEY (project_id, id)
);

CREATE TABLE pl5_trial_media (
  id UUID NOT NULL,
  project_id UUID NOT NULL REFERENCES projects(id),
  actor_user_id UUID NOT NULL REFERENCES users(id),
  activity_uid UUID NOT NULL,
  mime TEXT NOT NULL CHECK (mime IN ('image/jpeg', 'image/png')),
  original BYTEA NOT NULL CHECK (octet_length(original) BETWEEN 1 AND 5242880),
  sha256 TEXT NOT NULL CHECK (sha256 ~ '^[0-9a-f]{64}$'),
  annotations JSONB NOT NULL CHECK (jsonb_typeof(annotations) = 'array'),
  semantic_fingerprint TEXT NOT NULL CHECK (semantic_fingerprint ~ '^[0-9a-f]{64}$'),
  uploaded_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  PRIMARY KEY (project_id, id)
);

CREATE TABLE pl5_trial_media_links (
  id UUID NOT NULL DEFAULT gen_random_uuid(),
  project_id UUID NOT NULL REFERENCES projects(id),
  media_id UUID NOT NULL,
  message_id UUID NOT NULL,
  actor_user_id UUID NOT NULL REFERENCES users(id),
  change_id UUID NOT NULL UNIQUE REFERENCES project_committed_changes(id),
  linked_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  PRIMARY KEY (project_id, id),
  UNIQUE (project_id, media_id),
  FOREIGN KEY (project_id, media_id) REFERENCES pl5_trial_media(project_id, id),
  FOREIGN KEY (project_id, message_id) REFERENCES pl5_trial_messages(project_id, id)
);

CREATE INDEX pl5_trial_messages_activity ON pl5_trial_messages(project_id, activity_uid);

CREATE FUNCTION refuse_pl5_trial_history_change() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'accepted trial history is append-only' USING ERRCODE = '23514';
END;
$$;

CREATE TRIGGER pl5_trial_messages_immutable BEFORE UPDATE OR DELETE ON pl5_trial_messages
  FOR EACH ROW EXECUTE FUNCTION refuse_pl5_trial_history_change();
CREATE TRIGGER pl5_trial_messages_no_truncate BEFORE TRUNCATE ON pl5_trial_messages
  FOR EACH STATEMENT EXECUTE FUNCTION refuse_pl5_trial_history_change();
CREATE TRIGGER pl5_trial_media_immutable BEFORE UPDATE OR DELETE ON pl5_trial_media
  FOR EACH ROW EXECUTE FUNCTION refuse_pl5_trial_history_change();
CREATE TRIGGER pl5_trial_media_no_truncate BEFORE TRUNCATE ON pl5_trial_media
  FOR EACH STATEMENT EXECUTE FUNCTION refuse_pl5_trial_history_change();
CREATE TRIGGER pl5_trial_media_links_immutable BEFORE UPDATE OR DELETE ON pl5_trial_media_links
  FOR EACH ROW EXECUTE FUNCTION refuse_pl5_trial_history_change();
CREATE TRIGGER pl5_trial_media_links_no_truncate BEFORE TRUNCATE ON pl5_trial_media_links
  FOR EACH STATEMENT EXECUTE FUNCTION refuse_pl5_trial_history_change();
