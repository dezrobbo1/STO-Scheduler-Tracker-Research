-- STO V005: authenticated actors and project-scoped authorization.
--
-- Password and TOTP verification live at the API edge.  PostgreSQL stores
-- only Argon2id hashes, authenticated ciphertext, and hashes of the random
-- browser/device credentials.  Project membership is the single authority
-- used by every project route.

CREATE TABLE users (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  username TEXT NOT NULL,
  normalized_username TEXT NOT NULL UNIQUE,
  display_name TEXT,
  password_hash TEXT NOT NULL,
  totp_secret_encrypted BYTEA NOT NULL,
  last_totp_counter BIGINT,
  enabled BOOLEAN NOT NULL DEFAULT TRUE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  password_changed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  last_authenticated_at TIMESTAMPTZ,
  disabled_at TIMESTAMPTZ,
  CONSTRAINT users_username_not_blank CHECK (btrim(username) <> ''),
  CONSTRAINT users_normalized_username_not_blank CHECK (btrim(normalized_username) <> ''),
  CONSTRAINT users_password_is_argon2id CHECK (password_hash LIKE '$argon2id$%'),
  CONSTRAINT users_totp_ciphertext_present CHECK (octet_length(totp_secret_encrypted) >= 32),
  CONSTRAINT users_disabled_state_check CHECK (
    (enabled AND disabled_at IS NULL) OR (NOT enabled AND disabled_at IS NOT NULL)
  )
);

CREATE TABLE project_memberships (
  project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  user_id UUID NOT NULL REFERENCES users(id),
  role TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  created_by_user_id UUID REFERENCES users(id),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_by_user_id UUID REFERENCES users(id),
  revoked_at TIMESTAMPTZ,
  CONSTRAINT project_memberships_role_check CHECK (role IN ('viewer', 'planner', 'admin')),
  CONSTRAINT project_memberships_update_check CHECK (updated_at >= created_at),
  CONSTRAINT project_memberships_revocation_check CHECK (
    revoked_at IS NULL OR revoked_at >= created_at
  ),
  PRIMARY KEY (project_id, user_id)
);

CREATE TABLE project_membership_events (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  user_id UUID NOT NULL REFERENCES users(id),
  action TEXT NOT NULL,
  previous_role TEXT,
  role TEXT,
  actor_user_id UUID REFERENCES users(id),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT project_membership_events_action_check
    CHECK (action IN ('granted', 'role_changed', 'revoked')),
  CONSTRAINT project_membership_events_roles_check CHECK (
    (action = 'granted' AND previous_role IS NULL
      AND role IN ('viewer', 'planner', 'admin'))
    OR (action = 'role_changed'
      AND previous_role IN ('viewer', 'planner', 'admin')
      AND role IN ('viewer', 'planner', 'admin')
      AND previous_role <> role)
    OR (action = 'revoked'
      AND previous_role IN ('viewer', 'planner', 'admin')
      AND role IS NULL)
  )
);

CREATE FUNCTION record_project_membership_event() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP = 'INSERT' THEN
    INSERT INTO project_membership_events
      (project_id, user_id, action, role, actor_user_id)
    VALUES
      (NEW.project_id, NEW.user_id, 'granted', NEW.role, NEW.created_by_user_id);
  ELSIF OLD.revoked_at IS NOT NULL AND NEW.revoked_at IS NULL THEN
    INSERT INTO project_membership_events
      (project_id, user_id, action, role, actor_user_id)
    VALUES
      (NEW.project_id, NEW.user_id, 'granted', NEW.role, NEW.updated_by_user_id);
  ELSIF OLD.revoked_at IS NULL AND NEW.revoked_at IS NOT NULL THEN
    INSERT INTO project_membership_events
      (project_id, user_id, action, previous_role, actor_user_id)
    VALUES
      (NEW.project_id, NEW.user_id, 'revoked', OLD.role, NEW.updated_by_user_id);
  ELSIF OLD.role IS DISTINCT FROM NEW.role THEN
    INSERT INTO project_membership_events
      (project_id, user_id, action, previous_role, role, actor_user_id)
    VALUES
      (NEW.project_id, NEW.user_id, 'role_changed', OLD.role, NEW.role,
       NEW.updated_by_user_id);
  END IF;
  RETURN NEW;
END;
$$;

CREATE TRIGGER project_memberships_record_history
AFTER INSERT OR UPDATE ON project_memberships
FOR EACH ROW EXECUTE FUNCTION record_project_membership_event();

CREATE FUNCTION refuse_project_membership_event_mutation() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'project membership events are append-only'
    USING ERRCODE = '23514';
END;
$$;

CREATE TRIGGER project_membership_events_are_append_only
BEFORE UPDATE OR DELETE ON project_membership_events
FOR EACH ROW EXECUTE FUNCTION refuse_project_membership_event_mutation();

CREATE TABLE server_sessions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES users(id),
  token_hash TEXT NOT NULL UNIQUE,
  token_prefix TEXT NOT NULL UNIQUE,
  issued_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  expires_at TIMESTAMPTZ NOT NULL,
  last_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  revoked_at TIMESTAMPTZ,
  CONSTRAINT server_sessions_hash_check CHECK (token_hash ~ '^[0-9a-f]{64}$'),
  CONSTRAINT server_sessions_prefix_not_secret CHECK (
    token_prefix ~ '^sto_s_[A-Za-z0-9_-]{8}$'
  ),
  CONSTRAINT server_sessions_expiry_check CHECK (expires_at > issued_at),
  CONSTRAINT server_sessions_revocation_check CHECK (
    revoked_at IS NULL OR revoked_at >= issued_at
  )
);

CREATE TABLE device_tokens (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL,
  project_id UUID NOT NULL,
  role TEXT NOT NULL,
  token_hash TEXT NOT NULL UNIQUE,
  token_prefix TEXT NOT NULL UNIQUE,
  issued_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  expires_at TIMESTAMPTZ,
  revoked_at TIMESTAMPTZ,
  issued_by_user_id UUID NOT NULL REFERENCES users(id),
  CONSTRAINT device_tokens_role_check CHECK (role IN ('viewer', 'planner')),
  CONSTRAINT device_tokens_hash_check CHECK (token_hash ~ '^[0-9a-f]{64}$'),
  CONSTRAINT device_tokens_prefix_not_secret CHECK (
    token_prefix ~ '^sto_dev_[A-Za-z0-9_-]{8}$'
  ),
  CONSTRAINT device_tokens_expiry_check CHECK (
    expires_at IS NULL OR expires_at > issued_at
  ),
  CONSTRAINT device_tokens_revocation_check CHECK (
    revoked_at IS NULL OR revoked_at >= issued_at
  ),
  CONSTRAINT device_tokens_membership_fk
    FOREIGN KEY (project_id, user_id)
    REFERENCES project_memberships(project_id, user_id)
    ON DELETE CASCADE
);

-- These actor columns already existed so old scheduling rows remain valid.
-- V005 makes future non-null provenance referentially sound.  They were
-- unconstrained before authentication existed, so NOT VALID deliberately
-- preserves any historical UUID attribution while PostgreSQL still checks
-- every INSERT/UPDATE made after this migration.
ALTER TABLE projects
  ADD CONSTRAINT projects_created_by_user_fk
  FOREIGN KEY (created_by_user_id) REFERENCES users(id) NOT VALID;
ALTER TABLE source_files
  ADD CONSTRAINT source_files_uploaded_by_user_fk
  FOREIGN KEY (uploaded_by_user_id) REFERENCES users(id) NOT VALID;
ALTER TABLE import_batches
  ADD CONSTRAINT import_batches_created_by_user_fk
  FOREIGN KEY (created_by_user_id) REFERENCES users(id) NOT VALID;
ALTER TABLE schedule_versions
  ADD CONSTRAINT schedule_versions_created_by_user_fk
  FOREIGN KEY (created_by_user_id) REFERENCES users(id) NOT VALID;
ALTER TABLE scenario_changes
  ADD CONSTRAINT scenario_changes_created_by_user_fk
  FOREIGN KEY (created_by_user_id) REFERENCES users(id) NOT VALID;
ALTER TABLE schedule_calculations
  ADD COLUMN created_by_user_id UUID REFERENCES users(id);

CREATE INDEX idx_project_memberships_user_project
  ON project_memberships(user_id, project_id);
CREATE INDEX idx_project_membership_events_project_user
  ON project_membership_events(project_id, user_id, created_at);
CREATE INDEX idx_server_sessions_user_active
  ON server_sessions(user_id, expires_at) WHERE revoked_at IS NULL;
CREATE INDEX idx_device_tokens_user_project_active
  ON device_tokens(user_id, project_id) WHERE revoked_at IS NULL;

COMMENT ON TABLE users IS
  'Authenticated browser and device actors; secrets are hashed or encrypted at the API edge.';
COMMENT ON TABLE project_memberships IS
  'The authoritative viewer/planner/admin boundary for one project.';
COMMENT ON TABLE project_membership_events IS
  'Append-only grant, role-change and revocation history for project authority.';
COMMENT ON TABLE server_sessions IS
  'Persistent revocable browser sessions. token_hash is keyed; the raw token exists only in the cookie.';
COMMENT ON TABLE device_tokens IS
  'Persistent revocable project-scoped bearer credentials. The raw token is displayed once.';
