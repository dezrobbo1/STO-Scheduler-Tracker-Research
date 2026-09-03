#!/usr/bin/env sh
# Fails if a live database is behind the migration set. Read-only; safe to run anywhere.
#
# Two checks, because either alone can be fooled:
#
#   1. The ledger against the directory listing. Answers "has every migration been applied".
#   2. The tables the migrations create against the tables the database has. Answers "does the
#      schema actually look right", and does not trust the ledger to say so.
#
# Both expectations are derived, never transcribed. A hand-maintained list rots exactly the way
# validate-migrations.sh's EXPECTED_TABLES did: it named 33 tables when the migrations created 35,
# so it passed against a database missing the two most recent ones. Keeping such a list current is
# the same discipline that failed in the first place.
set -eu

PGHOST=${PGHOST:-127.0.0.1}
PGPORT=${PGPORT:-5433}
PGUSER=${PGUSER:-postgres}
PGDATABASE=${PGDATABASE:-sto}
export PGHOST PGPORT PGUSER PGDATABASE

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPO_ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/../.." && pwd)
MIGRATIONS_DIR="$REPO_ROOT/infra/migrations"

WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT

status=0

# --- 1. every migration file recorded as applied -----------------------------------------------
if [ "$(psql -Atc "SELECT to_regclass('public.schema_migration_log') IS NOT NULL")" != "t" ]; then
  echo "No schema_migration_log in $PGDATABASE." >&2
  echo "Nothing records which migrations this database has had. Run scripts/db/backfill-migration-log.sh" >&2
  echo "once you have confirmed the schema is current, then use scripts/db/apply-migrations.sh." >&2
  exit 1
fi

ls "$MIGRATIONS_DIR"/V*.sql | xargs -n1 basename | sort > "$WORK/expected"
psql -Atc "SELECT filename FROM schema_migration_log" | sort > "$WORK/applied"

if comm -23 "$WORK/expected" "$WORK/applied" | grep -q . ; then
  echo "Not applied to $PGDATABASE:" >&2
  comm -23 "$WORK/expected" "$WORK/applied" | sed 's/^/  /' >&2
  status=1
fi

if comm -13 "$WORK/expected" "$WORK/applied" | grep -q . ; then
  echo "Recorded as applied but no longer in infra/migrations:" >&2
  comm -13 "$WORK/expected" "$WORK/applied" | sed 's/^/  /' >&2
  status=1
fi

# --- 2. the schema itself, not the ledger's opinion of it --------------------------------------
grep -hoiE 'CREATE TABLE (IF NOT EXISTS )?[a-z_.]+' "$MIGRATIONS_DIR"/V*.sql \
  | sed -E 's/.*[[:space:]]//; s/^public\.//' | sort -u > "$WORK/tables-expected"
# schema_migration_log is this script's own bookkeeping and no migration creates it.
psql -Atc "SELECT tablename FROM pg_tables WHERE schemaname = 'public'" \
  | grep -vx 'schema_migration_log' | sort > "$WORK/tables-live"

if comm -23 "$WORK/tables-expected" "$WORK/tables-live" | grep -q . ; then
  echo "Tables the migrations create but $PGDATABASE does not have:" >&2
  comm -23 "$WORK/tables-expected" "$WORK/tables-live" | sed 's/^/  /' >&2
  status=1
fi

if comm -13 "$WORK/tables-expected" "$WORK/tables-live" | grep -q . ; then
  echo "Tables $PGDATABASE has that no migration creates:" >&2
  comm -13 "$WORK/tables-expected" "$WORK/tables-live" | sed 's/^/  /' >&2
  status=1
fi

if [ "$status" -eq 0 ]; then
  echo "Schema matches infra/migrations ($(wc -l < "$WORK/expected" | tr -d ' ') migrations, $(wc -l < "$WORK/tables-expected" | tr -d ' ') tables)."
fi

exit "$status"
