#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
EVIDENCE="$ROOT/artifacts/pl5-cloud-emulator"
SETUP_FILE="${STO_EMULATOR_SETUP_FILE:?STO_EMULATOR_SETUP_FILE is required}"
APP_APK="$ROOT/field/android/app/build/outputs/apk/debug/app-debug.apk"
TEST_APK="$ROOT/field/android/app/build/outputs/apk/androidTest/debug/app-debug-androidTest.apk"
HOST_SERVER="http://127.0.0.1:8092"
DEVICE_SERVER="http://10.0.2.2:8092"
PACKAGE="au.com.sto.fieldtrial"
TEST_RUNNER="au.com.sto.fieldtrial.test/androidx.test.runner.AndroidJUnitRunner"
SERVER_PID=""

mkdir -p "$EVIDENCE/instrumentation" "$EVIDENCE/screenshots"

mapfile -t VALUES < <("$ROOT/.venv/bin/python" - "$SETUP_FILE" <<'PY'
import json
import sys

payload = json.load(open(sys.argv[1], encoding="utf-8"))
for key in (
    "project_id", "credential_a", "credential_b", "actor_a", "actor_b",
    "baseline_hash",
):
    print(payload[key])
for key in ("isolate", "inspect", "restore"):
    print(payload["activities"][key])
PY
)

PROJECT_ID="${VALUES[0]}"
CREDENTIAL_A="${VALUES[1]}"
CREDENTIAL_B="${VALUES[2]}"
ACTOR_A="${VALUES[3]}"
ACTOR_B="${VALUES[4]}"
BASELINE_HASH="${VALUES[5]}"
ISOLATE_UID="${VALUES[6]}"
INSPECT_UID="${VALUES[7]}"
RESTORE_UID="${VALUES[8]}"

echo "::add-mask::$CREDENTIAL_A"
echo "::add-mask::$CREDENTIAL_B"

start_server() {
  local logfile="$1"
  if [[ -n "$SERVER_PID" ]] && kill -0 "$SERVER_PID" 2>/dev/null; then
    return 0
  fi
  (
    cd "$ROOT"
    exec env PYTHONPATH="$ROOT/src" "$ROOT/.venv/bin/python"       -m sto.cli serve --host 0.0.0.0 --port 8092
  ) >>"$logfile" 2>&1 &
  SERVER_PID=$!
  for _ in $(seq 1 80); do
    if curl -fsS "$HOST_SERVER/healthz" >/dev/null 2>&1; then
      return 0
    fi
    sleep 0.25
  done
  echo "STO API did not become healthy" >&2
  tail -200 "$logfile" >&2 || true
  return 1
}

start_server_after_delay() {
  local logfile="$1"
  (
    sleep 8
    cd "$ROOT"
    exec env PYTHONPATH="$ROOT/src" "$ROOT/.venv/bin/python"       -m sto.cli serve --host 0.0.0.0 --port 8092
  ) >>"$logfile" 2>&1 &
  SERVER_PID=$!
}

stop_server() {
  if [[ -n "$SERVER_PID" ]] && kill -0 "$SERVER_PID" 2>/dev/null; then
    kill "$SERVER_PID" || true
    wait "$SERVER_PID" 2>/dev/null || true
  fi
  SERVER_PID=""
}

collect_evidence() {
  adb logcat -d >"$EVIDENCE/logcat.txt" 2>&1 || true
  adb shell dumpsys package "$PACKAGE" >"$EVIDENCE/package.txt" 2>&1 || true
  adb pull "/sdcard/Android/data/$PACKAGE/files/cloud-emulator"     "$EVIDENCE/screenshots" >/dev/null 2>&1 || true
}

cleanup() {
  stop_server
  collect_evidence
}
trap cleanup EXIT

run_instrumentation() {
  local method="$1"
  shift
  local logfile="$EVIDENCE/instrumentation/$method.txt"
  set +e
  adb shell am instrument -w -r     -e class "au.com.sto.fieldtrial.CloudEmulatorFlowTest#$method"     "$@" "$TEST_RUNNER" | tee "$logfile"
  local rc=${PIPESTATUS[0]}
  set -e
  if [[ "$rc" -ne 0 ]] ||
     grep -Eq 'FAILURES!!!|INSTRUMENTATION_FAILED|Process crashed|shortMsg=' "$logfile" ||
     ! grep -q 'INSTRUMENTATION_CODE: -1' "$logfile"; then
    echo "Instrumentation phase failed: $method" >&2
    return 1
  fi
}

if [[ ! -f "$APP_APK" || ! -f "$TEST_APK" ]]; then
  echo "Android APKs are missing" >&2
  exit 1
fi

sha256sum "$APP_APK" >"$EVIDENCE/app-debug.sha256"
printf '%s\n' "$STO_BUILD_SHA" >"$EVIDENCE/source-sha.txt"
adb logcat -c
adb install -r "$APP_APK"
adb install -r "$TEST_APK"

start_server "$EVIDENCE/server.log"

BUILD_JSON="$(curl -fsS -H "Authorization: Bearer $CREDENTIAL_A" "$HOST_SERVER/api/trial-build")"
"$ROOT/.venv/bin/python" - "$BUILD_JSON" "$STO_BUILD_SHA" <<'PY'
import json
import sys

payload = json.loads(sys.argv[1])
if payload != {"server_sha": sys.argv[2]}:
    raise SystemExit(f"unexpected trial build identity: {payload!r}")
PY

run_instrumentation connectAndCache   -e stoServer "$DEVICE_SERVER"   -e stoProject "$PROJECT_ID"   -e stoCredential "$CREDENTIAL_A"   -e stoActor "$ACTOR_A"   -e stoBaselineHash "$BASELINE_HASH"

stop_server
adb shell am force-stop "$PACKAGE"

run_instrumentation queueWhileBackendUnavailable   -e stoActivity "$ISOLATE_UID"

adb shell am force-stop "$PACKAGE"

run_instrumentation reopenWhileBackendUnavailable   -e stoActivity "$ISOLATE_UID"

start_server "$EVIDENCE/server-restarted.log"

run_instrumentation reconnectAndReconcile

run_instrumentation logoutAndConnectB   -e stoServer "$DEVICE_SERVER"   -e stoProject "$PROJECT_ID"   -e stoCredential "$CREDENTIAL_B"   -e stoActor "$ACTOR_B"

run_instrumentation onlineDeepLinkSelectsTarget   -e stoProject "$PROJECT_ID"   -e stoActivity "$RESTORE_UID"

stop_server
start_server_after_delay "$EVIDENCE/server-delayed-restart.log"

run_instrumentation offlineDeepLinkRecovers   -e stoProject "$PROJECT_ID"   -e stoActivity "$INSPECT_UID"

for _ in $(seq 1 80); do
  if curl -fsS "$HOST_SERVER/healthz" >/dev/null 2>&1; then
    break
  fi
  sleep 0.25
done

curl -fsS -H "Authorization: Bearer $CREDENTIAL_A"   "$HOST_SERVER/api/projects/$PROJECT_ID/changes?after=0"   >"$EVIDENCE/final-feed.json"

"$ROOT/.venv/bin/python" - "$SETUP_FILE" "$EVIDENCE/final-feed.json" "$EVIDENCE/summary.json" <<'PY'
import json
import sys
from pathlib import Path

setup = json.load(open(sys.argv[1], encoding="utf-8"))
feed = json.load(open(sys.argv[2], encoding="utf-8"))
events = feed.get("events", [])
if feed.get("next_cursor") != 2 or feed.get("has_more") is not False or len(events) != 2:
    raise SystemExit(f"unexpected disposable emulator history: {feed!r}")
if sum(1 for row in events if row.get("operation_id")) != 1:
    raise SystemExit(f"expected exactly one execution event: {events!r}")
if sum(1 for row in events if row.get("kind") == "trial_message") != 1:
    raise SystemExit(f"expected exactly one trial message: {events!r}")

safe = {
    "server_sha": setup["server_sha"],
    "project_id": setup["project_id"],
    "baseline_version_id": setup["baseline_version_id"],
    "baseline_hash": setup["baseline_hash"],
    "actor_a": setup["actor_a"],
    "actor_b": setup["actor_b"],
    "credential_a_id": setup["credential_a_id"],
    "credential_b_id": setup["credential_b_id"],
    "final_cursor": feed["next_cursor"],
    "event_kinds": [
        row.get("kind") or ("execution" if row.get("operation_id") else "unknown")
        for row in events
    ],
    "classification": "cloud emulator shakeout only; not physical-device evidence",
}
Path(sys.argv[3]).write_text(json.dumps(safe, indent=2) + "\n", encoding="utf-8")
PY

collect_evidence
echo "PL5 cloud emulator smoke passed at $STO_BUILD_SHA"
