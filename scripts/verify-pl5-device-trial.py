"""Verify the bounded PL5 two-device trial against durable server receipts.

The JSON manifest records physical-device observations; this verifier checks
server facts and refuses an incomplete manifest. Credentials are supplied only
through STO_TRIAL_VERIFY_TOKEN, never in the manifest or command line.
"""

from __future__ import annotations

import json
import hashlib
import math
import os
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import datetime
from pathlib import Path


TRIAL_STARTS = ("2026-01-05T09:00:00", "2026-01-05T13:00:00", "2026-01-06T08:00:00")
TRIAL_TEXTS = ("A: isolation observed", "B: restore observed")
TRIAL_ACTIVITIES = (
    ("0d717f24-85ff-5d98-afce-2fcaf8bbb5cf", "Isolate equipment"),
    ("1256e448-70c8-5839-8a89-9300d703d276", "Execute inspection"),
    ("88f5407a-79c8-5501-a94a-50d91104ac0d", "Restore equipment"),
)


def validate_annotations(value: object) -> None:
    if not isinstance(value, list) or len(value) > 30:
        raise ValueError("media annotations missing or malformed")
    kinds = set()
    for item in value:
        if not isinstance(item, dict) or item.get("kind") not in {"arrow", "circle", "text"}:
            raise ValueError("unsupported media annotation")
        kind = item["kind"]
        for key in (("x", "y", "toX", "toY") if kind == "arrow" else ("x", "y")):
            number = item.get(key)
            if isinstance(number, bool) or not isinstance(number, (int, float)) or not math.isfinite(number) or not 0 <= number <= 1:
                raise ValueError("media annotation coordinate invalid")
        if kind == "circle":
            radius = item.get("radius")
            if isinstance(radius, bool) or not isinstance(radius, (int, float)) or not math.isfinite(radius) or not 0 < radius <= 1:
                raise ValueError("media annotation radius invalid")
        if kind == "arrow" and item["x"] == item["toX"] and item["y"] == item["toY"]:
            raise ValueError("media annotation arrow has no length")
        if kind == "text" and (not isinstance(item.get("text"), str) or
                                not 0 < len(item["text"].strip()) <= 80):
            raise ValueError("media annotation text invalid")
        kinds.add(kind)
    if kinds != {"arrow", "circle", "text"}:
        raise ValueError("prescribed arrow, circle and text annotations missing")


def require_reconciled_local(row: dict, state: str, domain: str) -> None:
    error = row.get("error_code")
    if (row.get("local_final_state") != state or
            not (error is None or isinstance(error, str) and error == "")):
        raise ValueError(f"{domain} local record not reconciled to {state} with cleared error")


def normalised_start(payload: dict) -> dict:
    # datetime-local may omit seconds; compare the parsed semantic value.
    value = dict(payload)
    try:
        value["actual_start"] = datetime.fromisoformat(value["actual_start"]).isoformat()
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError("trial actual start missing or invalid") from error
    return value


def verify(manifest: dict, token: str, *, expected_sha: str,
           device_tokens: tuple[str, str]) -> dict:
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
        for key in ("model", "os", "app_sha", "actor_user_id", "authority_evidence", "offline_evidence",
                    "termination_evidence", "reopen_evidence", "reconnect_evidence",
                    "final_cursor", "final_hash"):
            if not device.get(key):
                raise ValueError(f"{label} missing {key}")
        if device["app_sha"] != manifest["app_sha"]:
            raise ValueError(f"{label} build does not match manifest")
        try:
            device["actor_user_id"] = str(uuid.UUID(device["actor_user_id"]))
        except (TypeError, ValueError, AttributeError) as error:
            raise ValueError(f"{label} actor invalid") from error
        if device.get("authority_evidence", {}).get("user_id") != device["actor_user_id"]:
            raise ValueError(f"{label} captured authenticated actor mismatch")
    actor_a = manifest["device_a"]["actor_user_id"]
    actor_b = manifest["device_b"]["actor_user_id"]
    if actor_a == actor_b:
        raise ValueError("two distinct device actors required")
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
    if tuple(row.get("activity_uid") for row in manifest["execution"]) != tuple(uid for uid, _ in TRIAL_ACTIVITIES):
        raise ValueError("execution activities do not match prescribed fixture tasks")
    if tuple(row.get("actor_user_id") for row in manifest["execution"]) != (actor_a, actor_a, actor_b):
        raise ValueError("local execution actor attribution invalid")
    expected_facts = []
    for row, start in zip(manifest["execution"], TRIAL_STARTS):
        facts = {"activity_uid": row["activity_uid"], "actual_start": start,
                 "actual_finish": None, "remaining_seconds": 3600}
        expected_payload = {"operation_id": row["operation_id"],
                            "expected_version_id": manifest["baseline_version_id"],
                            "expected_hash": manifest["baseline_hash"], **facts}
        if normalised_start(row.get("payload", {})) != expected_payload:
            raise ValueError("local execution differs from prescribed trial command")
        expected_facts.append(facts)
    if tuple(row.get("actor_user_id") for row in manifest["communication"]) != (actor_a, actor_b):
        raise ValueError("local note actor attribution invalid")
    for row, activity, text in zip(manifest["communication"],
                                  (manifest["execution"][0]["activity_uid"],
                                   manifest["execution"][2]["activity_uid"]), TRIAL_TEXTS):
        if row.get("activity_uid") != activity or row.get("text") != text:
            raise ValueError("local message differs from prescribed trial note")

    def get(path: str, bearer: str = token) -> tuple[int, object]:
        request = urllib.request.Request(path, headers={"Authorization": f"Bearer {bearer}"})
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                return response.status, json.load(response)
        except urllib.error.HTTPError as error:
            return error.code, json.load(error)

    status, deployed_build = get(f"{manifest['server'].rstrip('/')}/api/trial-build")
    if status != 200 or deployed_build.get("server_sha") != expected_sha:
        raise ValueError("deployed server build does not match verifier checkout")
    for label, bearer in zip(("device_a", "device_b"), device_tokens):
        if not bearer:
            raise ValueError(f"{label} verifier credential missing")
        status, authority = get(f"{manifest['server'].rstrip('/')}/api/auth/session", bearer)
        if (status != 200 or authority.get("actor", {}).get("user_id") !=
                manifest[label]["actor_user_id"]):
            raise ValueError(f"{label} authenticated token does not name captured actor")
        status, _ = get(base, bearer)
        if status != 200:
            raise ValueError(f"{label} token lacks current trial project access")

    status, versions = get(f"{base}/versions")
    if (status != 200 or not isinstance(versions, list) or
            not any(row.get("kind") == "baseline" and
                    row.get("version_id") == manifest["baseline_version_id"] and
                    row.get("canonical_hash") == manifest["baseline_hash"]
                    for row in versions)):
        raise ValueError("baseline version/hash not present in immutable server history")
    status, calculation = get(f"{base}/calculations/latest?kind=baseline")
    if (status != 200 or calculation.get("version_id") != manifest["baseline_version_id"] or
            calculation.get("canonical_hash") != manifest["baseline_hash"] or
            not all(any(str(row.get("activity_uid")) == uid and row.get("name") == name
                        for row in calculation.get("activities", []))
                    for uid, name in TRIAL_ACTIVITIES)):
        raise ValueError("server baseline does not contain prescribed fixture activities")

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
    if (media.get("actor_user_id") != actor_a or
            media.get("message_id") != manifest["communication"][0]["id"] or
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
    ordered_sources = [(event.get("kind") or "execution",
                        event.get("operation_id") or event.get("media_id") or event.get("id"))
                       for event in events]
    if ordered_sources != [("execution", manifest["execution"][0]["operation_id"]),
                           ("trial_message", manifest["communication"][0]["id"]),
                           ("trial_media_link", media["id"]),
                           ("trial_message", manifest["communication"][1]["id"])]:
        raise ValueError("committed history differs from prescribed trial sequence")
    if (accepted[0].get("kind") not in (None, "execution") or
            str(accepted[0].get("actor_user_id")) != actor_a or
            any(row.get("activity_uid") != messages[row["id"]] or
                row.get("text") != manifest["communication"][index]["text"] or
                str(row.get("actor_user_id")) != (actor_a if index == 0 else actor_b)
                for index, row in enumerate(delivered_messages))):
        raise ValueError("committed trial domain/association changed")
    for row in manifest["execution"]:
        status, receipt = get(f"{base}/execution-operations/{row['operation_id']}")
        if row["operation_id"] in {x["operation_id"] for x in accepted}:
            require_reconciled_local(row, "applied", "accepted execution")
            if status != 200 or receipt["operation_id"] != row["operation_id"]:
                raise ValueError("accepted execution receipt missing")
            if normalised_start(receipt.get("execution", {})) != expected_facts[0]:
                raise ValueError("accepted execution differs from prescribed trial facts")
            if (receipt.get("base_version_id") != manifest["baseline_version_id"] or
                    str(receipt.get("actor_user_id")) != actor_a or
                    receipt.get("server_sequence") != accepted[0]["server_sequence"] or
                    receipt.get("canonical_hash") != accepted[0]["canonical_hash"]):
                raise ValueError("accepted execution does not derive from recorded baseline")
        elif status != 404 or row.get("local_final_state") != "needs_attention" or row.get("error_code") != "LIVE_STALE_HEAD":
            raise ValueError("stale intention was lost or misrepresented locally")
    for index, row in enumerate(manifest["communication"]):
        require_reconciled_local(row, "accepted", "accepted note")
        status, note_receipt = get(f"{base}/trial-messages/{row['id']}")
        if (status != 200 or note_receipt.get("id") != row["id"] or
                str(note_receipt.get("actor_user_id")) != (actor_a if index == 0 else actor_b) or
                note_receipt.get("activity_uid") != row["activity_uid"] or
                note_receipt.get("text") != row["text"] or
                note_receipt.get("server_sequence") != delivered_messages[index]["server_sequence"]):
            raise ValueError("trial note actor or content differs from durable receipt")
    require_reconciled_local(media, "linked", "linked media")
    status, media_receipt = get(f"{base}/trial-media/{media['id']}")
    if (status != 200 or media_receipt.get("status") != "linked" or
            media_receipt.get("id") != media["id"] or
            media_receipt.get("message_id") != media["message_id"] or
            media_receipt.get("activity_uid") != media["activity_uid"] or
            media_receipt.get("sha256") != media["original_sha256"] or
            str(media_receipt.get("actor_user_id")) != actor_a or
            media_receipt.get("server_sequence") != links[0]["server_sequence"]):
        raise ValueError("expected recovered media link/receipt missing or mismatched")
    validate_annotations(media_receipt.get("annotations"))
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
    if (len(sys.argv) != 2 or not all(os.environ.get(key) for key in
            ("STO_TRIAL_VERIFY_TOKEN", "STO_TRIAL_VERIFY_TOKEN_A", "STO_TRIAL_VERIFY_TOKEN_B"))):
        raise SystemExit("usage: set STO_TRIAL_VERIFY_TOKEN, STO_TRIAL_VERIFY_TOKEN_A and STO_TRIAL_VERIFY_TOKEN_B in the environment; then verify-pl5-device-trial.py manifest.json")
    checkout_sha = subprocess.check_output(
        ["git", "-C", str(Path(__file__).resolve().parents[1]), "rev-parse", "HEAD"],
        text=True).strip()
    print(json.dumps(verify(json.loads(Path(sys.argv[1]).read_text()),
                            os.environ["STO_TRIAL_VERIFY_TOKEN"],
                            expected_sha=checkout_sha,
                            device_tokens=(os.environ["STO_TRIAL_VERIFY_TOKEN_A"],
                                           os.environ["STO_TRIAL_VERIFY_TOKEN_B"])), indent=2))
