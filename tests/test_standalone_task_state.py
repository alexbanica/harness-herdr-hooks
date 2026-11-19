import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from harness_herdr_hooks.model import (
    Context, CreationProof, Harness, Lifecycle, Session,
    session_from_dict, session_to_dict,
)
from harness_herdr_hooks.state import StateStore, UnsafeState


class StandaloneTaskStateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = StateStore(Path(self.tmp.name), "standalone-test")

    def tearDown(self):
        self.tmp.cleanup()

    def test_creation_proof_roundtrip_and_strict_identity(self):
        home = Path("/tmp/profile")
        context = Context(Harness.CODEX, "default", home, home, home,
                          "/tmp/backend.sock", "child", "instance")
        proof = CreationProof("parent", "turn", "item", "child", "a" * 64)
        session = Session(context, "parent", None, Path("/tmp"), Lifecycle.RUNNING,
                          True, 12.0, (), None, "standalone", None, None, proof)
        encoded = session_to_dict(session)
        self.assertEqual(session_from_dict(encoded), session)
        del encoded["creation_proof"]["item_id"]
        with self.assertRaises(ValueError): session_from_dict(encoded)
        bad = session_to_dict(session); bad["creation_proof"]["child_id"] = "foreign"
        with self.assertRaises(ValueError): session_from_dict(bad)

    def test_cursor_and_candidates_commit_atomically_deduplicate_and_restart(self):
        event = SimpleNamespace(parent_id="parent", turn_id="turn", item_id="item",
                                child_id="child", cwd_sha256=None)
        cursor = {"device": 1, "inode": 2, "offset": 9, "parent_id": "parent",
                  "path": "/tmp/rollout.jsonl", "observed_size": 9,
                  "skip_to_newline": False}
        parent = {"parent_id": "parent", "path": "/tmp/rollout.jsonl",
                  "device": 1, "inode": 2, "owner_uid": 1000}
        context = {"profile": "default", "backend_id": "/tmp/backend.sock",
                   "backend_instance": "inst", "session_id": "parent"}
        destination = {"server_id": "s", "workspace_id": "w", "tab_id": "t", "pane_id": "p"}
        self.assertEqual(self.store.commit_task_records(cursor, [event, event], parent=parent,
                         context=context, destination=destination, now=10), 1)
        state = StateStore(Path(self.tmp.name), "standalone-test").task_discovery()
        self.assertEqual(state["cursor"], cursor)
        self.assertEqual(len(state["pending"]), 1)
        self.assertEqual(self.store.commit_task_records(cursor, [event], parent=parent,
                         context=context, destination=destination, now=11), 0)
        key = state["pending"][0]["event_key"]
        self.assertTrue(self.store.update_task_candidate(key, status="pending", now=12,
                                                         retry=True, reason="metadata unavailable"))
        self.assertEqual(StateStore(Path(self.tmp.name), "standalone-test").task_discovery()["pending"][0]["attempts"], 1)

    def test_state_never_persists_transcript_values_and_rejects_malformed_known_state(self):
        event = SimpleNamespace(parent_id="parent", turn_id="turn", item_id="item",
                                child_id="child", cwd_sha256=None)
        cursor = {"device": 1, "inode": 2, "offset": 0, "parent_id": "parent",
                  "path": "/tmp/r.jsonl", "observed_size": 0, "skip_to_newline": False}
        self.store.commit_task_records(cursor, [event],
            parent={"parent_id": "parent", "path": "/tmp/r.jsonl", "device": 1, "inode": 2, "owner_uid": 1000},
            context={"profile": "p", "backend_id": "b", "backend_instance": "i", "session_id": "parent"},
            destination={"server_id": "s", "workspace_id": "w", "tab_id": "t", "pane_id": "p"}, now=0)
        raw = (self.store.root / "state.json").read_text()
        self.assertNotIn("prompt", raw)
        self.assertNotIn("conversation body", raw)
        data = json.loads(raw); data["task_discovery"]["pending"][0]["prompt"] = "secret"
        (self.store.root / "state.json").write_text(json.dumps(data)); (self.store.root / "state.json").chmod(0o600)
        with self.assertRaises(UnsafeState): self.store.task_discovery()

    def test_known_state_reloads_reject_boolean_negative_and_nonfinite_retry_values(self):
        event = SimpleNamespace(parent_id="parent", turn_id="turn", item_id="item",
                                child_id="child", cwd_sha256=None)
        cursor = {"device": 1, "inode": 2, "offset": 0, "parent_id": "parent",
                  "path": "/tmp/r.jsonl", "observed_size": 0, "skip_to_newline": False}
        self.store.commit_task_records(cursor, [event],
            parent={"parent_id": "parent", "path": "/tmp/r.jsonl", "device": 1, "inode": 2, "owner_uid": 1000},
            context={"profile": "p", "backend_id": "b", "backend_instance": "i", "session_id": "parent"},
            destination={"server_id": "s", "workspace_id": "w", "tab_id": "t", "pane_id": "p"}, now=4)
        path = self.store.root / "state.json"
        original = json.loads(path.read_text())
        cases = (("attempts", True), ("first_seen", True), ("retry_after", True),
                 ("first_seen", -1), ("retry_after", -1), ("first_seen", float("nan")),
                 ("retry_after", float("inf")))
        for field, value in cases:
            with self.subTest(field=field, value=value):
                bad = json.loads(json.dumps(original))
                bad["task_discovery"]["pending"][0][field] = value
                path.write_text(json.dumps(bad, allow_nan=True)); path.chmod(0o600)
                with self.assertRaises(UnsafeState):
                    StateStore(Path(self.tmp.name), "standalone-test").task_discovery()
        path.write_text(json.dumps(original)); path.chmod(0o600)
        self.assertEqual(StateStore(Path(self.tmp.name), "standalone-test").task_discovery()["pending"][0]["first_seen"], 4.0)

    def test_oversized_parser_identity_is_skipped_without_poisoning_shared_state(self):
        cursor = {"device": 1, "inode": 2, "offset": 0, "parent_id": "parent",
                  "path": "/tmp/r.jsonl", "observed_size": 0,
                  "skip_to_newline": False}
        parent = {"parent_id": "parent", "path": "/tmp/r.jsonl", "device": 1,
                  "inode": 2, "owner_uid": 1000}
        context = {"profile": "default", "backend_id": "/tmp/backend.sock",
                   "backend_instance": "inst", "session_id": "parent"}
        destination = {"server_id": "s", "workspace_id": "w", "tab_id": "t", "pane_id": "p"}
        invalid = SimpleNamespace(parent_id="parent", turn_id="t" * 513,
                                  item_id="item", child_id="child", cwd_sha256=None)
        valid = SimpleNamespace(parent_id="parent", turn_id="turn", item_id="item",
                                child_id="child", cwd_sha256=None)
        self.assertEqual(self.store.commit_task_records(cursor, [invalid, valid], parent=parent,
                         context=context, destination=destination, now=10), 1)
        state = self.store.task_discovery()
        self.assertEqual(state["cursor"], cursor)
        self.assertEqual([item["turn_id"] for item in state["pending"]], ["turn"])
        self.assertIsNone(self.store.record("native-session"))

    def test_retry_budget_and_terminal_dedup_outcome(self):
        event = SimpleNamespace(parent_id="parent", turn_id="turn", item_id="item",
                                child_id="child", cwd_sha256=None)
        c = {"device": 1, "inode": 1, "offset": 0, "parent_id": "parent", "path": "/tmp/a",
             "observed_size": 0, "skip_to_newline": False}
        self.store.commit_task_records(c, [event], parent={"parent_id": "parent", "path": "/tmp/a", "device": 1, "inode": 1, "owner_uid": 1},
          context={"profile": "p", "backend_id": "b", "backend_instance": "i", "session_id": "parent"},
          destination={"server_id": "s", "workspace_id": "w", "tab_id": "t", "pane_id": "p"}, now=1)
        key = self.store.task_discovery()["pending"][0]["event_key"]
        for now in (2, 3, 4): self.store.update_task_candidate(key, status="pending", now=now, retry=True, reason="metadata unavailable")
        state = self.store.task_discovery()
        self.assertEqual(state["pending"], [])
        self.assertEqual(state["outcomes"][0]["status"], "rejected")
        self.assertEqual(self.store.commit_task_records(c, [event], parent={"parent_id": "parent", "path": "/tmp/a", "device": 1, "inode": 1, "owner_uid": 1},
          context={"profile": "p", "backend_id": "b", "backend_instance": "i", "session_id": "parent"},
          destination={"server_id": "s", "workspace_id": "w", "tab_id": "t", "pane_id": "p"}, now=5), 0)

    def test_verification_reservations_allow_three_attempts_then_reject(self):
        event = SimpleNamespace(parent_id="parent", turn_id="turn", item_id="item",
                                child_id="child", cwd_sha256=None)
        c = {"device": 1, "inode": 2, "offset": 0, "parent_id": "parent", "path": "/tmp/a",
             "observed_size": 0, "skip_to_newline": False}
        self.store.commit_task_records(c, [event], parent={"parent_id": "parent", "path": "/tmp/a", "device": 1, "inode": 2, "owner_uid": 1},
          context={"profile": "p", "backend_id": "b", "backend_instance": "i", "session_id": "parent"},
          destination={"server_id": "s", "workspace_id": "w", "tab_id": "t", "pane_id": "p"}, now=1)
        key = self.store.task_discovery()["pending"][0]["event_key"]
        self.assertTrue(self.store.reserve_task_verification(key, now=2))
        self.assertTrue(self.store.update_task_candidate(key, status="verified", now=2))
        self.assertTrue(self.store.reserve_task_verification(key, now=3))
        self.assertTrue(self.store.reserve_task_verification(key, now=4))
        self.assertEqual(self.store.task_discovery()["pending"][0]["attempts"], 3)
        self.assertFalse(self.store.reserve_task_verification(key, now=5))
        self.assertEqual(self.store.task_discovery()["outcomes"][0]["status"], "rejected")


if __name__ == "__main__": unittest.main()
