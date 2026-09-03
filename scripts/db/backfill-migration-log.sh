#!/usr/bin/env sh
# Records the current migration set as already applied, for a database brought forward by hand.
#
# One-time, and only correct when the schema really is current. Run scripts/db/check-schema-drift.sh
# afterwards: its second check reads the tables rather than the ledger, so it will say if this
# recorded a fiction.
#
# Rows are marked backfilled = true. That distinction is worth keeping: a backfilled row means
# "somebody asserted this had been applied", and an ordinary row means "this script applied it".
set -eu

PGHOST=${PGHOST:-127.0.0.1}
PGPORT=${PGPORT:-5433}
PGUSER=${PGUSER:-postgres}
PGDATABASE=${PGDATABASE:-sto}
export PGHOST PGPORT PGUSER PGDATABASE

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPO_ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/../.." && pwd)
MIGRATIONS_DIR="$REPO_ROOT/infra/migrations"

psql -v ON_ERROR_STOP=1 -q <<'SQL'
SET client_min_messages = warning;
CREATE TABLE IF NOT EXISTS schema_migration_log (
  filename   TEXT PRIMARY KEY,
  sha256     TEXT NOT NULL,
  applied_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  applied_by TEXT NOT NULL DEFAULT current_user,
  backfilled BOOLEAN NOT NULL DEFAULT false
);
COMMENT ON TABLE schema_migration_log IS
  'Which infra/migrations files this database has had applied. Deployment bookkeeping, not application schema.';
SQL

for migration in "$MIGRATIONS_DIR"/V*.sql; do
  name=$(basename "$migration")
  hash=$(sha256sum "$migration" | cut -d' ' -f1)
  # Existing rows are left alone: a real apply is better evidence than a backfill.
  psql -v ON_ERROR_STOP=1 -q -c \
    "INSERT INTO schema_migration_log (filename, sha256, backfilled)
     VALUES ('$name', '$hash', true)
     ON CONFLICT (filename) DO NOTHING;"
  echo "    recorded $name"
done

echo "Backfilled. Run scripts/db/check-schema-drift.sh to confirm the schema agrees."
