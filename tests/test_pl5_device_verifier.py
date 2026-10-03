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
ACTIVITIES = [f"{n:08x}-eeee-4eee-8eee-eeeeeeeeeeee" for n in range(1, 4)]
EXECUTIONS = [f"{n:08x}-aaaa-4aaa-8aaa-aaaaaaaaaaaa" for n in range(1, 4)]
MESSAGES = [f"{n:08x}-bbbb-4bbb-8bbb-bbbbbbbbbbbb" for n in range(1, 3)]
MEDIA = "ffffffff-ffff-4fff-8fff-ffffffffffff"
BASE_HASH = "a" * 64
HEAD_HASH = "b" * 64
ORIGINAL = b"synthetic photo"
ORIGINAL_HASH = hashlib.sha256(ORIGINAL).hexdigest()
SHA = "d" * 40


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
        "device_a": copy.deepcopy(devices), "device_b": copy.deepcopy(devices),
        "execution": [{"operation_id": op, "activity_uid": activity,
                       **({} if index == 0 else {"local_final_state": "needs_attention",
                           "error_code": "LIVE_STALE_HEAD"})}
                      for index, (op, activity) in enumerate(zip(EXECUTIONS, ACTIVITIES))],
        "communication": [{"id": message, "activity_uid": activity}
                          for message, activity in zip(MESSAGES, [ACTIVITIES[0], ACTIVITIES[2]])],
        "media": {"id": MEDIA, "message_id": MESSAGES[0],
                  "activity_uid": ACTIVITIES[0], "original_sha256": ORIGINAL_HASH},
        "final_hash": HEAD_HASH}
    events = [
        {"operation_id": EXECUTIONS[0], "server_sequence": 1,
         "canonical_hash": HEAD_HASH},
        {"kind": "trial_message", "id": MESSAGES[0], "activity_uid": ACTIVITIES[0],
         "server_sequence": 2},
        {"kind": "trial_media_link", "id": "11111111-1111-4111-8111-111111111111",
         "media_id": MEDIA, "message_id": MESSAGES[0], "server_sequence": 3},
        {"kind": "trial_message", "id": MESSAGES[1], "activity_uid": ACTIVITIES[2],
         "server_sequence": 4},
    ]
    receipt = {"operation_id": EXECUTIONS[0], "base_version_id": VERSION,
               "canonical_hash": HEAD_HASH, "server_sequence": 1,
               "execution": {"activity_uid": ACTIVITIES[0]}}
    media_receipt = {"id": MEDIA, "message_id": MESSAGES[0],
                     "activity_uid": ACTIVITIES[0], "sha256": ORIGINAL_HASH,
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
              deployed_sha=SHA):
        def urlopen(request, timeout):
            path = request.full_url
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
            if path.endswith("/live"):
                return Response({"version_id": "eeeeeeee-dddd-4ddd-8ddd-dddddddddddd",
                                 "canonical_hash": HEAD_HASH})
            if path.endswith(f"/trial-media/{MEDIA}"):
                return Response(media_receipt)
            if path.endswith(f"/trial-media/{MEDIA}/original"):
                return Response(original)
            if "/execution-operations/" in path:
                if path.endswith(EXECUTIONS[0]):
                    return Response(receipt)
                from urllib.error import HTTPError
                raise HTTPError(path, 404, "not found", {}, io.BytesIO(b'{}'))
            raise AssertionError(f"unexpected verifier request: {path}")

        with patch.object(verifier.urllib.request, "urlopen", side_effect=urlopen):
            return verifier.verify(manifest, "synthetic-token", expected_sha=SHA)

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


if __name__ == "__main__":
    unittest.main()
