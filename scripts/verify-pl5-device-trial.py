"""Verify the bounded PL5 two-device trial against durable server receipts.

The JSON manifest records physical-device observations; this verifier checks
server facts and refuses an incomplete manifest. Credentials are supplied only
through STO_TRIAL_VERIFY_TOKEN, never in the manifest or command line.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path


def verify(manifest: dict, token: str) -> dict:
    required = ("server", "project_id", "baseline_hash", "baseline_version_id",
                "baseline_cursor", "server_sha", "app_sha", "device_a", "device_b",
                "execution", "communication", "final_hash")
    for key in required:
        if key not in manifest:
            raise ValueError(f"missing {key}")
    if not manifest["server"].startswith("https://"):
        raise ValueError("server must use HTTPS")
    project = str(uuid.UUID(manifest["project_id"]))
    base = f"{manifest['server'].rstrip('/')}/api/projects/{project}"
    for label in ("device_a", "device_b"):
        device = manifest[label]
        for key in ("model", "os", "app_sha", "offline_evidence",
                    "termination_evidence", "reopen_evidence", "reconnect_evidence",
                    "final_cursor", "final_hash"):
            if not device.get(key):
                raise ValueError(f"{label} missing {key}")
        if device["app_sha"] != manifest["app_sha"]:
            raise ValueError(f"{label} build does not match manifest")
    if len(manifest["execution"]) != 3 or len(manifest["communication"]) != 2:
        raise ValueError("expected exactly three execution and two communication intentions")
    activities = {str(uuid.UUID(row["activity_uid"])) for row in manifest["execution"]}
    if len(activities) != 3:
        raise ValueError("execution intentions must target three distinct activities")

    def get(path: str) -> tuple[int, dict]:
        request = urllib.request.Request(path, headers={"Authorization": f"Bearer {token}"})
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                return response.status, json.load(response)
        except urllib.error.HTTPError as error:
            return error.code, json.load(error)

    cursor = manifest["baseline_cursor"]
    events = []
    while True:
        status, page = get(f"{base}/changes?after={cursor}&limit=100")
        if status != 200:
            raise ValueError(f"catch-up failed: {status}")
        for event in page["events"]:
            if event["server_sequence"] != cursor + 1:
                raise ValueError("committed cursor gap")
            cursor += 1
            events.append(event)
        if page["next_cursor"] != cursor:
            raise ValueError("catch-up cursor mismatch")
        if not page["has_more"]:
            break

    expected = {row["operation_id"] for row in manifest["execution"]}
    messages = {row["id"]: row["activity_uid"] for row in manifest["communication"]}
    if len(expected) != 3 or len(messages) != 2:
        raise ValueError("duplicate client identities")
    accepted = [row for row in events if row.get("operation_id") in expected]
    delivered_messages = [row for row in events if row.get("kind") == "trial_message"
                          and row.get("id") in messages]
    if len(accepted) != 1 or len(delivered_messages) != 2:
        raise ValueError("expected one accepted execution and two accepted messages")
    if len({row["operation_id"] for row in accepted}) != len(accepted):
        raise ValueError("duplicate accepted execution effect")
    if len({row["id"] for row in delivered_messages}) != 2:
        raise ValueError("duplicate accepted communication")
    if len(events) not in (3, 4) or any(row.get("kind") not in
        (None, "execution", "trial_message", "trial_media_link") for row in events):
        raise ValueError("unexpected committed trial history")
    if any(row["activity_uid"] != messages[row["id"]] for row in delivered_messages):
        raise ValueError("activity association changed")
    for row in manifest["execution"]:
        status, receipt = get(f"{base}/execution-operations/{row['operation_id']}")
        if row["operation_id"] in {x["operation_id"] for x in accepted}:
            if status != 200 or receipt["operation_id"] != row["operation_id"]:
                raise ValueError("accepted execution receipt missing")
            if receipt["execution"]["activity_uid"] != row["activity_uid"]:
                raise ValueError("execution activity changed")
        elif status != 404 or row.get("local_final_state") != "needs_attention" or row.get("error_code") != "LIVE_STALE_HEAD":
            raise ValueError("stale intention was lost or misrepresented locally")
    status, head = get(f"{base}/live")
    if status != 200 or head["canonical_hash"] != manifest["final_hash"]:
        raise ValueError("head hash does not match trial manifest")
    if head["canonical_hash"] != accepted[0]["canonical_hash"]:
        raise ValueError("trial head differs from accepted execution effect")
    for label in ("device_a", "device_b"):
        if (manifest[label]["final_cursor"] != cursor or
                manifest[label]["final_hash"] != head["canonical_hash"]):
            raise ValueError(f"{label} did not converge to committed state")
    return {"passed": True, "committed_cursor": cursor,
            "ordered_sequences": [row["server_sequence"] for row in events],
            "accepted_execution": accepted[0]["operation_id"],
            "messages": sorted(messages), "final_hash": head["canonical_hash"]}


if __name__ == "__main__":
    if len(sys.argv) != 2 or not os.environ.get("STO_TRIAL_VERIFY_TOKEN"):
        raise SystemExit("usage: STO_TRIAL_VERIFY_TOKEN=... python scripts/verify-pl5-device-trial.py manifest.json")
    print(json.dumps(verify(json.loads(Path(sys.argv[1]).read_text()),
                            os.environ["STO_TRIAL_VERIFY_TOKEN"]), indent=2))
