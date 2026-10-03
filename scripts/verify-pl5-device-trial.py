"""Verify the bounded PL5 two-device trial against durable server receipts.

The JSON manifest records physical-device observations; this verifier checks
server facts and refuses an incomplete manifest. Credentials are supplied only
through STO_TRIAL_VERIFY_TOKEN, never in the manifest or command line.
"""

from __future__ import annotations

import json
import hashlib
import os
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path


def verify(manifest: dict, token: str, *, expected_sha: str) -> dict:
    required = ("server", "project_id", "baseline_hash", "baseline_version_id",
                "baseline_cursor", "server_sha", "app_sha", "device_a", "device_b",
                "execution", "communication", "media", "baseline_server", "final_hash")
    for key in required:
        if key not in manifest:
            raise ValueError(f"missing {key}")
    if not manifest["server"].startswith("https://"):
        raise ValueError("server must use HTTPS")
    if (not re.fullmatch(r"[0-9a-f]{40}", expected_sha) or
            manifest["server_sha"] != expected_sha or manifest["app_sha"] != expected_sha):
        raise ValueError("server/app build does not match verifier checkout")
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
    if type(manifest["baseline_cursor"]) is not int or manifest["baseline_cursor"] != 0:
        raise ValueError("fresh trial must begin at committed cursor zero")
    baseline = manifest["baseline_server"]
    if (baseline.get("live", {}).get("version_id") != manifest["baseline_version_id"] or
            baseline.get("live", {}).get("canonical_hash") != manifest["baseline_hash"] or
            baseline.get("live", {}).get("kind") != "baseline" or
            baseline.get("changes") != {"events": [], "next_cursor": 0, "has_more": False}):
        raise ValueError("captured baseline response does not describe a fresh baseline")
    activities = {str(uuid.UUID(row["activity_uid"])) for row in manifest["execution"]}
    if len(activities) != 3:
        raise ValueError("execution intentions must target three distinct activities")

    def get(path: str) -> tuple[int, object]:
        request = urllib.request.Request(path, headers={"Authorization": f"Bearer {token}"})
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                return response.status, json.load(response)
        except urllib.error.HTTPError as error:
            return error.code, json.load(error)

    status, deployed_build = get(f"{manifest['server'].rstrip('/')}/api/trial-build")
    if status != 200 or deployed_build.get("server_sha") != expected_sha:
        raise ValueError("deployed server build does not match verifier checkout")

    status, versions = get(f"{base}/versions")
    if (status != 200 or not isinstance(versions, list) or
            not any(row.get("kind") == "baseline" and
                    row.get("version_id") == manifest["baseline_version_id"] and
                    row.get("canonical_hash") == manifest["baseline_hash"]
                    for row in versions)):
        raise ValueError("baseline version/hash not present in immutable server history")

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
    media = manifest["media"]
    if (media.get("message_id") not in messages or
            media.get("activity_uid") != messages[media["message_id"]] or
            not re.fullmatch(r"[0-9a-f]{64}", media.get("original_sha256", ""))):
        raise ValueError("expected media identity/association invalid")
    accepted = [row for row in events if row.get("operation_id") in expected]
    delivered_messages = [row for row in events if row.get("kind") == "trial_message"
                          and row.get("id") in messages]
    links = [row for row in events if row.get("kind") == "trial_media_link" and
             row.get("media_id") == media["id"] and row.get("message_id") == media["message_id"]]
    identities = []
    for event in events:
        if event.get("operation_id") in expected and event.get("kind") in (None, "execution"):
            identities.append(("execution", event["operation_id"]))
        elif event.get("kind") == "trial_message" and event.get("id") in messages:
            identities.append(("trial_message", event["id"]))
        elif event.get("kind") == "trial_media_link" and event in links and event.get("id"):
            identities.append(("trial_media_link", event["id"]))
        else:
            raise ValueError("unaccounted committed trial event")
    if (len(events) != 4 or len(accepted) != 1 or len(delivered_messages) != 2 or
            len(links) != 1 or len(set(identities)) != 4):
        raise ValueError("unexpected or duplicate committed trial history")
    if (accepted[0].get("kind") not in (None, "execution") or
            any(row.get("activity_uid") != messages[row["id"]]
                for row in delivered_messages)):
        raise ValueError("committed trial domain/association changed")
    for row in manifest["execution"]:
        status, receipt = get(f"{base}/execution-operations/{row['operation_id']}")
        if row["operation_id"] in {x["operation_id"] for x in accepted}:
            if status != 200 or receipt["operation_id"] != row["operation_id"]:
                raise ValueError("accepted execution receipt missing")
            if receipt["execution"]["activity_uid"] != row["activity_uid"]:
                raise ValueError("execution activity changed")
            if (receipt.get("base_version_id") != manifest["baseline_version_id"] or
                    receipt.get("server_sequence") != accepted[0]["server_sequence"] or
                    receipt.get("canonical_hash") != accepted[0]["canonical_hash"]):
                raise ValueError("accepted execution does not derive from recorded baseline")
        elif status != 404 or row.get("local_final_state") != "needs_attention" or row.get("error_code") != "LIVE_STALE_HEAD":
            raise ValueError("stale intention was lost or misrepresented locally")
    status, media_receipt = get(f"{base}/trial-media/{media['id']}")
    if (status != 200 or media_receipt.get("status") != "linked" or
            media_receipt.get("id") != media["id"] or
            media_receipt.get("message_id") != media["message_id"] or
            media_receipt.get("activity_uid") != media["activity_uid"] or
            media_receipt.get("sha256") != media["original_sha256"] or
            media_receipt.get("server_sequence") != links[0]["server_sequence"]):
        raise ValueError("expected recovered media link/receipt missing or mismatched")
    original_request = urllib.request.Request(
        f"{base}/trial-media/{media['id']}/original",
        headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(original_request, timeout=20) as response:
        if (response.status != 200 or
                hashlib.sha256(response.read(5 * 1024 * 1024 + 1)).hexdigest() !=
                media["original_sha256"]):
            raise ValueError("server original bytes differ from recorded media digest")
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
            "messages": sorted(messages), "media_id": media["id"],
            "final_hash": head["canonical_hash"]}


if __name__ == "__main__":
    if len(sys.argv) != 2 or not os.environ.get("STO_TRIAL_VERIFY_TOKEN"):
        raise SystemExit("usage: STO_TRIAL_VERIFY_TOKEN=... python scripts/verify-pl5-device-trial.py manifest.json")
    checkout_sha = subprocess.check_output(
        ["git", "-C", str(Path(__file__).resolve().parents[1]), "rev-parse", "HEAD"],
        text=True).strip()
    print(json.dumps(verify(json.loads(Path(sys.argv[1]).read_text()),
                            os.environ["STO_TRIAL_VERIFY_TOKEN"],
                            expected_sha=checkout_sha), indent=2))
