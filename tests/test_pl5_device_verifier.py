"""Fail-closed synthetic PL5 device-return verification (not device evidence)."""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import io
import json
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("pl5_trial_verifier",
                                          ROOT / "scripts/verify-pl5-device-trial.py")
verifier = importlib.util.module_from_spec(spec)
spec.loader.exec_module(verifier)

PROJECT = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"
VERSION = "dddddddd-dddd-4ddd-8ddd-dddddddddddd"
ACTIVITIES = [uid for uid, _ in verifier.TRIAL_ACTIVITIES]
ACTOR_A = "aaaaaaaa-1111-4111-8111-aaaaaaaaaaaa"
ACTOR_B = "bbbbbbbb-2222-4222-8222-bbbbbbbbbbbb"
EXECUTIONS = [f"{n:08x}-aaaa-4aaa-8aaa-aaaaaaaaaaaa" for n in range(1, 4)]
MESSAGES = [f"{n:08x}-bbbb-4bbb-8bbb-bbbbbbbbbbbb" for n in range(1, 3)]
MEDIA = "ffffffff-ffff-4fff-8fff-ffffffffffff"
BASE_HASH = "a" * 64
HEAD_HASH = "b" * 64
ORIGINAL = b"synthetic photo"
ORIGINAL_HASH = hashlib.sha256(ORIGINAL).hexdigest()
SHA = "d" * 40
ANNOTATIONS = [{"kind": "arrow", "x": .1, "y": .2, "toX": .3, "toY": .4},
               {"kind": "circle", "x": .5, "y": .6, "radius": .08},
               {"kind": "text", "x": .7, "y": .8, "text": "Check"}]
STARTS = ["2026-01-05T09:00:00", "2026-01-05T13:00:00", "2026-01-06T08:00:00"]
TEXTS = ["A: isolation observed", "B: restore observed"]


def fixture():
    devices = {"model": "synthetic", "os": "synthetic", "app_sha": SHA,
               "offline_evidence": "A-00", "termination_evidence": "A-01",
               "reopen_evidence": "A-02", "reconnect_evidence": "A-03",
               "final_cursor": 4, "final_hash": HEAD_HASH}
    manifest = {"server": "https://sto.example", "project_id": PROJECT,
        "server_sha": SHA, "app_sha": SHA,
        "baseline_version_id": VERSION, "baseline_hash": BASE_HASH,
        "baseline_cursor": 0,
        "baseline_server": {"live": {"version_id": VERSION, "canonical_hash": BASE_HASH,
                                      "kind": "baseline"},
                            "changes": {"events": [], "next_cursor": 0, "has_more": False}},
        "device_a": {**copy.deepcopy(devices), "actor_user_id": ACTOR_A,
                     "authority_evidence": {"user_id": ACTOR_A}},
        "device_b": {**copy.deepcopy(devices), "actor_user_id": ACTOR_B,
                     "authority_evidence": {"user_id": ACTOR_B}},
        "execution": [{"operation_id": op, "activity_uid": activity,
                       "actor_user_id": ACTOR_A if index < 2 else ACTOR_B,
                       "payload": {"operation_id": op, "activity_uid": activity,
                           "expected_version_id": VERSION, "expected_hash": BASE_HASH,
                           "actual_start": STARTS[index], "actual_finish": None,
                           "remaining_seconds": 3600},
                       **({} if index == 0 else {"local_final_state": "needs_attention",
                           "error_code": "LIVE_STALE_HEAD"})}
                      for index, (op, activity) in enumerate(zip(EXECUTIONS, ACTIVITIES))],
        "communication": [{"id": MESSAGES[index], "activity_uid": ACTIVITIES[0 if index == 0 else 2],
                           "text": TEXTS[index], "actor_user_id": ACTOR_A if index == 0 else ACTOR_B}
                          for index in range(2)],
        "media": {"id": MEDIA, "message_id": MESSAGES[0],
                  "activity_uid": ACTIVITIES[0], "original_sha256": ORIGINAL_HASH,
                  "actor_user_id": ACTOR_A},
        "final_hash": HEAD_HASH}
    events = [
        {"operation_id": EXECUTIONS[0], "server_sequence": 1,
         "canonical_hash": HEAD_HASH, "actor_user_id": ACTOR_A},
        {"kind": "trial_message", "id": MESSAGES[0], "activity_uid": ACTIVITIES[0],
         "text": TEXTS[0], "actor_user_id": ACTOR_A, "server_sequence": 2},
        {"kind": "trial_media_link", "id": "11111111-1111-4111-8111-111111111111",
         "media_id": MEDIA, "message_id": MESSAGES[0], "server_sequence": 3},
        {"kind": "trial_message", "id": MESSAGES[1], "activity_uid": ACTIVITIES[2],
         "text": TEXTS[1], "actor_user_id": ACTOR_B, "server_sequence": 4},
    ]
    receipt = {"operation_id": EXECUTIONS[0], "base_version_id": VERSION,
               "actor_user_id": ACTOR_A,
               "canonical_hash": HEAD_HASH, "server_sequence": 1,
               "execution": {"activity_uid": ACTIVITIES[0], "actual_start": STARTS[0],
                             "actual_finish": None, "remaining_seconds": 3600}}
    media_receipt = {"id": MEDIA, "message_id": MESSAGES[0],
                     "activity_uid": ACTIVITIES[0], "sha256": ORIGINAL_HASH,
                     "actor_user_id": ACTOR_A, "annotations": copy.deepcopy(ANNOTATIONS),
                     "status": "linked", "server_sequence": 3}
    return manifest, events, receipt, media_receipt


class Response:
    status = 200

    def __init__(self, data):
        self.stream = io.BytesIO(data if isinstance(data, bytes) else json.dumps(data).encode())

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.stream.close()

    def read(self, *args):
        return self.stream.read(*args)


class VerifierTests(unittest.TestCase):
    def check(self, manifest, events, receipt, media_receipt, original=ORIGINAL,
              deployed_sha=SHA, device_tokens=("A-token", "B-token"),
              note_actors=(ACTOR_A, ACTOR_B), calculation_rows=None):
        def urlopen(request, timeout):
            path = request.full_url
            if path.endswith("/api/auth/session"):
                actor = {"Bearer A-token": ACTOR_A, "Bearer B-token": ACTOR_B}.get(
                    request.get_header("Authorization"))
                return Response({"actor": {"user_id": actor}})
            if path.endswith(f"/projects/{PROJECT}"):
                return Response({"id": PROJECT})
            if path.endswith("/trial-build"):
                return Response({"server_sha": deployed_sha})
            if "/changes?" in path:
                after = int(path.split("after=")[1].split("&")[0])
                page = [row for row in events if row["server_sequence"] > after]
                return Response({"events": page, "next_cursor": page[-1]["server_sequence"] if page else after,
                                 "has_more": False})
            if path.endswith("/versions"):
                return Response([{"version_id": VERSION, "canonical_hash": BASE_HASH,
                                  "kind": "baseline"}])
            if "/calculations/latest?" in path:
                return Response({"version_id": VERSION, "canonical_hash": BASE_HASH,
                                 "activities": calculation_rows if calculation_rows is not None else
                                 [{"activity_uid": uid, "name": name}
                                  for uid, name in verifier.TRIAL_ACTIVITIES]})
            if "/trial-messages/" in path:
                for index, message in enumerate(MESSAGES):
                    if path.endswith(message):
                        return Response({"id": message, "actor_user_id": note_actors[index],
                                         "activity_uid": ACTIVITIES[0 if index == 0 else 2],
                                         "text": TEXTS[index], "server_sequence": 2 if index == 0 else 4})
            if path.endswith("/live"):
                return Response({"version_id": "eeeeeeee-dddd-4ddd-8ddd-dddddddddddd",
                                 "canonical_hash": HEAD_HASH})
            if path.endswith(f"/trial-media/{MEDIA}"):
                return Response(media_receipt)
            if path.endswith(f"/trial-media/{MEDIA}/original"):
                return Response(original)
            if "/execution-operations/" in path:
                if path.endswith(receipt["operation_id"]):
                    return Response(receipt)
                from urllib.error import HTTPError
                raise HTTPError(path, 404, "not found", {}, io.BytesIO(b'{}'))
            raise AssertionError(f"unexpected verifier request: {path}")

        with patch.object(verifier.urllib.request, "urlopen", side_effect=urlopen):
            return verifier.verify(manifest, "synthetic-token", expected_sha=SHA,
                                   device_tokens=device_tokens)

    def test_exact_trial_history_and_provenance_pass(self):
        manifest, events, receipt, media = fixture()
        result = self.check(manifest, events, receipt, media)
        self.assertTrue(result["passed"])
        self.assertEqual(result["committed_cursor"], 4)
        self.assertEqual(result["media_id"], MEDIA)

    def test_wrong_build_or_baseline_provenance_fails(self):
        for change in (lambda m: m.update(server_sha="e" * 40),
                       lambda m: m.update(app_sha="e" * 40),
                       lambda m: m["device_a"].update(app_sha="e" * 40),
                       lambda m: m["device_b"].update(app_sha="e" * 40),
                       lambda m: m.update(baseline_version_id=EXECUTIONS[2]),
                       lambda m: m.update(baseline_hash="e" * 64),
                       lambda m: m.update(baseline_cursor=1)):
            manifest, events, receipt, media = fixture()
            change(manifest)
            with self.subTest(manifest=manifest):
                with self.assertRaises(ValueError):
                    self.check(manifest, events, receipt, media)
        manifest, events, receipt, media = fixture()
        with self.assertRaisesRegex(ValueError, "deployed server build"):
            self.check(manifest, events, receipt, media, deployed_sha="e" * 40)

    def test_unaccounted_or_duplicate_committed_events_fail(self):
        mutations = [
            lambda e: e.append({"operation_id": EXECUTIONS[1], "server_sequence": 5}),
            lambda e: e.append({"kind": "trial_message", "id": EXECUTIONS[1], "server_sequence": 5}),
            lambda e: e.append({"kind": "trial_media_link", "id": EXECUTIONS[1],
                                "media_id": EXECUTIONS[1], "message_id": MESSAGES[1],
                                "server_sequence": 5}),
            lambda e: e.append({"id": EXECUTIONS[1], "server_sequence": 5}),
            lambda e: e.append({**e[0], "server_sequence": 5}),
            lambda e: e.append({**e[1], "server_sequence": 5}),
            lambda e: e.append({**e[2], "server_sequence": 5}),
        ]
        for mutate in mutations:
            manifest, events, receipt, media = fixture()
            mutate(events)
            with self.subTest(extra=events[-1]):
                with self.assertRaises(ValueError):
                    self.check(manifest, events, receipt, media)

    def test_missing_or_wrong_media_link_fails(self):
        for mutation in (lambda e: e.pop(2),
                         lambda e: e[2].update(media_id=EXECUTIONS[2]),
                         lambda e: e[2].update(message_id=MESSAGES[1])):
            manifest, events, receipt, media = fixture()
            mutation(events)
            if len(events) == 3:
                events[2]["server_sequence"] = 3
            with self.subTest(events=events):
                with self.assertRaises(ValueError):
                    self.check(manifest, events, receipt, media)

    def test_receipt_base_and_linked_original_digest_must_match_server_history(self):
        manifest, events, receipt, media = fixture()
        receipt["base_version_id"] = EXECUTIONS[2]
        with self.assertRaisesRegex(ValueError, "recorded baseline"):
            self.check(manifest, events, receipt, media)
        manifest, events, receipt, media = fixture()
        media["sha256"] = "e" * 64
        with self.assertRaisesRegex(ValueError, "media link"):
            self.check(manifest, events, receipt, media)
        manifest, events, receipt, media = fixture()
        with self.assertRaisesRegex(ValueError, "original bytes"):
            self.check(manifest, events, receipt, media, b"different media")

    def test_changed_execution_or_message_semantics_fail(self):
        for field, value in (("actual_start", "2026-01-05T10:00:00"),
                             ("actual_finish", "2026-01-05T10:00:00"),
                             ("remaining_seconds", 7200)):
            manifest, events, receipt, media = fixture()
            receipt["execution"][field] = value
            with self.subTest(receipt_field=field):
                with self.assertRaises(ValueError):
                    self.check(manifest, events, receipt, media)
        for field, value in (("actual_start", "2026-01-07T08:00:00"),
                             ("remaining_seconds", 7200),
                             ("expected_version_id", EXECUTIONS[2]),
                             ("expected_hash", HEAD_HASH)):
            manifest, events, receipt, media = fixture()
            manifest["execution"][1]["payload"][field] = value
            with self.subTest(local_field=field):
                with self.assertRaises(ValueError):
                    self.check(manifest, events, receipt, media)
        for source in ("manifest", "event"):
            manifest, events, receipt, media = fixture()
            if source == "manifest": manifest["communication"][0]["text"] = "different note"
            else: events[1]["text"] = "different note"
            with self.subTest(note_source=source):
                with self.assertRaises(ValueError):
                    self.check(manifest, events, receipt, media)

    def test_different_execution_winner_or_committed_order_fails(self):
        manifest, events, receipt, media = fixture()
        events[0]["operation_id"] = EXECUTIONS[1]
        receipt["operation_id"] = EXECUTIONS[1]
        receipt["execution"] = {"activity_uid": ACTIVITIES[1], "actual_start": STARTS[1],
                                "actual_finish": None, "remaining_seconds": 3600}
        manifest["execution"][0].update(local_final_state="needs_attention",
                                         error_code="LIVE_STALE_HEAD")
        with self.assertRaises(ValueError):
            self.check(manifest, events, receipt, media)
        manifest, events, receipt, media = fixture()
        events[1], events[3] = events[3], events[1]
        events[1]["server_sequence"], events[3]["server_sequence"] = 2, 4
        with self.assertRaises(ValueError):
            self.check(manifest, events, receipt, media)

    def test_local_datetime_minutes_are_semantically_identical(self):
        manifest, events, receipt, media = fixture()
        for entry in manifest["execution"]:
            entry["payload"]["actual_start"] = entry["payload"]["actual_start"][:-3]
        self.assertTrue(self.check(manifest, events, receipt, media)["passed"])

    def test_distinct_actor_and_durable_actor_provenance(self):
        changes = [
            lambda m, e, r, media: m["device_b"].update(actor_user_id=ACTOR_A,
                                                          authority_evidence={"user_id": ACTOR_A}),
            lambda m, e, r, media: m["device_a"].update(authority_evidence={"user_id": ACTOR_B}),
            lambda m, e, r, media: m["execution"][2].update(actor_user_id=ACTOR_A),
            lambda m, e, r, media: r.update(actor_user_id=ACTOR_B),
            lambda m, e, r, media: e[0].update(actor_user_id=ACTOR_B),
            lambda m, e, r, media: e[1].update(actor_user_id=ACTOR_B),
            lambda m, e, r, media: e[3].update(actor_user_id=ACTOR_A),
            lambda m, e, r, media: media.update(actor_user_id=ACTOR_B),
        ]
        for change in changes:
            manifest, events, receipt, media = fixture()
            change(manifest, events, receipt, media)
            with self.subTest(change=change):
                with self.assertRaises(ValueError):
                    self.check(manifest, events, receipt, media)
        manifest, events, receipt, media = fixture()
        with self.assertRaisesRegex(ValueError, "authenticated token"):
            self.check(manifest, events, receipt, media, device_tokens=("B-token", "A-token"))
        for actors in ((ACTOR_B, ACTOR_B), (ACTOR_A, ACTOR_A)):
            with self.assertRaisesRegex(ValueError, "durable receipt"):
                self.check(manifest, events, receipt, media, note_actors=actors)
        manifest["device_a"]["actor_user_id"] = "not-a-uuid"
        with self.assertRaises(ValueError):
            self.check(manifest, events, receipt, media)

    def test_all_three_prescribed_annotations_are_required_and_well_formed(self):
        variants = [[], ANNOTATIONS[:1], ANNOTATIONS[1:2], ANNOTATIONS[2:],
                    ANNOTATIONS[1:], [ANNOTATIONS[0], ANNOTATIONS[2]], ANNOTATIONS[:2],
                    [{**ANNOTATIONS[0], "x": float('nan')}, *ANNOTATIONS[1:]],
                    [{**ANNOTATIONS[0], "toX": -1}, *ANNOTATIONS[1:]],
                    [{**ANNOTATIONS[0], "toX": .1, "toY": .2}, *ANNOTATIONS[1:]],
                    [ANNOTATIONS[0], {**ANNOTATIONS[1], "radius": 0}, ANNOTATIONS[2]],
                    [*ANNOTATIONS[:2], {**ANNOTATIONS[2], "text": " "}]]
        for value in variants:
            manifest, events, receipt, media = fixture()
            media["annotations"] = value
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    self.check(manifest, events, receipt, media)

    def test_task_identity_cannot_be_consistently_relabelled(self):
        manifest, events, receipt, media = fixture()
        replacement = "12345678-1111-4111-8111-123456789abc"
        manifest["execution"][0]["activity_uid"] = replacement
        manifest["execution"][0]["payload"]["activity_uid"] = replacement
        manifest["communication"][0]["activity_uid"] = replacement
        manifest["media"]["activity_uid"] = replacement
        events[1]["activity_uid"] = replacement
        receipt["execution"]["activity_uid"] = replacement
        media["activity_uid"] = replacement
        with self.assertRaisesRegex(ValueError, "fixture tasks"):
            self.check(manifest, events, receipt, media)
        manifest, events, receipt, media = fixture()
        rows = [{"activity_uid": uid, "name": name} for uid, name in verifier.TRIAL_ACTIVITIES]
        rows[0]["name"] = "Different project task"
        with self.assertRaisesRegex(ValueError, "fixture activities"):
            self.check(manifest, events, receipt, media, calculation_rows=rows)

    def test_device_final_convergence_and_physical_artifact_fields_fail_closed(self):
        for change in (lambda m: m["device_a"].update(final_cursor=3),
                       lambda m: m["device_b"].update(final_hash="e" * 64),
                       lambda m: m.update(final_hash="e" * 64),
                       lambda m: m["device_a"].update(termination_evidence=""),
                       lambda m: m["device_b"].update(offline_evidence="")):
            manifest, events, receipt, media = fixture()
            change(manifest)
            with self.subTest(change=change):
                with self.assertRaises(ValueError):
                    self.check(manifest, events, receipt, media)


if __name__ == "__main__":
    unittest.main()
