#!/usr/bin/env sh
# Applies unapplied migrations to a live database, and records what it applied.
#
# The loop this replaces started at V001 every time. Against a database that already has a schema
# that always fails on the first file, because V001 creates enums and PostgreSQL has no
# CREATE TYPE IF NOT EXISTS -- so the migrations after it were never reached. On 2026-08-21 the
# review deployment was found holding V001-V011 and V013, with V012 and V014 silently absent, and
# a merged feature depending on V012 that would have failed on a column that did not exist.
#
# Nothing recorded the gap because nothing recorded anything. This writes a ledger so that the
# question "which migrations has this database had" has an answer.
#
# schema_migration_log is deployment bookkeeping, not application schema, which is why it is
# created here rather than by a migration: infra/migrations/README.md keeps operational data out of
# migrations, and a ledger that needed a migration to exist could not record the migration that
# created it.
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

applied_any=false

for migration in "$MIGRATIONS_DIR"/V*.sql; do
  name=$(basename "$migration")
  hash=$(sha256sum "$migration" | cut -d' ' -f1)
  recorded=$(psql -Atc "SELECT sha256 FROM schema_migration_log WHERE filename = '$name'")

  if [ -n "$recorded" ]; then
    if [ "$recorded" != "$hash" ]; then
      echo "REFUSING: $name has changed since it was applied." >&2
      echo "  recorded $recorded" >&2
      echo "  on disk  $hash" >&2
      echo "A migration is never rewritten; add the next V### instead." >&2
      exit 1
    fi
    continue
  fi

  echo "    apply   $name"
  # One transaction per file, so a failure leaves nothing half-applied, and the ledger row commits
  # with the DDL so the two cannot disagree about what happened.
  psql --single-transaction -v ON_ERROR_STOP=1 -q \
    -f "$migration" \
    -c "INSERT INTO schema_migration_log (filename, sha256) VALUES ('$name', '$hash');"
  applied_any=true
done

if [ "$applied_any" = false ]; then
  echo "    nothing to apply; $PGDATABASE is up to date."
fi
