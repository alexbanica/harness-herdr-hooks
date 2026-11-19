import json
import tempfile
import unittest
from pathlib import Path

from harness_herdr_hooks.model import (
    Context, Harness, Lifecycle, Session, session_from_dict, session_to_dict,
)
from harness_herdr_hooks.state import (
    StateStore, binding_is_close_owned, load_existing_binding, save_binding,
)


def make_session():
    home = Path("/tmp/codex-profile")
    context = Context(Harness.CODEX, str(home), home, home, home, "/tmp/codex.sock", "child", "1:2:3")
    return Session(context, "parent", None, Path("/tmp"), Lifecycle.RUNNING, True, 1.0,
                   ("parent",), None, "subagent", "turn-1", "turn-1")


class LifecycleModelTests(unittest.TestCase):
    def test_session_roundtrip_and_legacy_kind_is_not_independent(self):
        current = session_to_dict(make_session())
        self.assertEqual(session_from_dict(current), make_session())
        legacy = {k: v for k, v in current.items() if k not in {"kind", "turn_id", "generation"}}
        self.assertEqual(session_from_dict(legacy).kind, "subagent")
        legacy["kind"] = "arbitrary"
        with self.assertRaises(ValueError):
            session_from_dict(legacy)

    def test_parent_backend_proof_roundtrip_is_bounded_and_path_checked(self):
        from harness_herdr_hooks.model import ParentBinding, parent_from_dict, parent_to_dict
        home = Path("/tmp/codex-profile")
        context = Context(Harness.CODEX, str(home), home, home, home, "/tmp/codex.sock", "parent", "1:2:3")
        proof = {"socket_alias": "/tmp/codex-profile/app-server-control/app-server-control.sock",
                 "socket_target": "/tmp/codex-profile/private.sock", "pid": 10,
                 "uid": 1000, "executable": "/usr/bin/codex", "cwd": "/tmp",
                 "start_ticks": 88}
        parent = ParentBinding(context, "server", "w1", "w1:t1", "w1:p1", backend_proof=proof)
        self.assertEqual(parent_from_dict(parent_to_dict(parent)), parent)
        proof["argv"] = ["secret"]
        with self.assertRaises(ValueError):
            parent_from_dict(parent_to_dict(parent))


class LifecycleStateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.store = StateStore(self.root, "test")

    def tearDown(self):
        self.tmp.cleanup()

    def test_generation_hints_terminal_and_restart_are_correlated(self):
        self.store.establish_baseline({"old"})
        self.assertTrue(self.store.begin_generation("child", "turn-1", turn_id="turn-1"))
        self.assertFalse(self.store.begin_generation("child", "turn-1", turn_id="turn-1"))
        self.assertTrue(self.store.note_stop_hint("child", "turn-1", "turn-1", stop_hook_active=True))
        self.assertEqual(self.store.generation("child")["status"], "pending")
        self.assertTrue(self.store.generation("child")["stop_reentered"])
        self.assertFalse(self.store.mark_generation_terminal("child", "turn-1", "turn-1", "inProgress"))
        self.assertTrue(self.store.mark_generation_terminal("child", "turn-1", "turn-1", "completed"))

        # Reopening state models helper restart; duplicate and stale deliveries
        # remain unable to reset the terminal generation.
        restarted = StateStore(self.root, "test")
        self.assertFalse(restarted.begin_generation("child", "turn-1", turn_id="turn-1"))
        self.assertFalse(restarted.note_stop_hint("child", "turn-1", "turn-old", stop_hook_active=False))
        self.assertTrue(restarted.begin_generation("child", "turn-2", turn_id="turn-2"))
        self.assertFalse(restarted.mark_generation_terminal("child", "turn-1", "turn-1", "failed"))
        self.assertEqual(restarted.generation("child")["generation"], "turn-2")

    def test_superseded_generation_cannot_replay_or_erase_current_binding(self):
        self.store.begin_generation("child", "turn-1", turn_id="turn-1")
        with self.store.locked() as data:
            data["records"]["child"].update(status="attached", binding_id="binding-1",
                                               ownership="created")
        self.assertTrue(self.store.begin_generation("child", "turn-2", turn_id="turn-2"))
        current = self.store.generation("child")
        self.assertEqual(current["prior_generations"][-1]["binding_id"], "binding-1")
        self.assertEqual(current["status"], "pending")
        with self.store.locked() as data:
            data["records"]["child"].update(status="attached", binding_id="binding-2",
                                               ownership="created")
        restarted = StateStore(self.root, "test")
        self.assertFalse(restarted.begin_generation("child", "turn-1", turn_id="turn-1"))
        current = restarted.generation("child")
        self.assertEqual(current["generation"], "turn-2")
        self.assertEqual(current["binding_id"], "binding-2")
        self.assertEqual(current["status"], "attached")

    def test_nonterminal_supersession_history_survives_restart(self):
        self.store.begin_generation("child", "turn-1", turn_id="turn-1")
        self.assertTrue(self.store.begin_generation("child", "turn-2", turn_id="turn-2"))
        restarted = StateStore(self.root, "test")
        self.assertFalse(restarted.begin_generation("child", "turn-1", turn_id="turn-1"))
        self.assertEqual(restarted.generation("child")["generation"], "turn-2")

    def test_stop_hint_never_replaces_attached_or_suppressed_state(self):
        self.store.begin_generation("child", "turn-1", turn_id="turn-1")
        with self.store.locked() as data:
            data["records"]["child"].update(status="attached", binding_id="pane-binding")
        self.store.note_stop_hint("child", "turn-1", "turn-1", stop_hook_active=True)
        self.assertEqual(self.store.generation("child")["status"], "attached")
        self.assertTrue(self.store.generation("child")["stop_reentered"])
        self.store.mark_suppressed("child", "manual close")
        self.store.note_stop_hint("child", "turn-1", "turn-1", stop_hook_active=False)
        self.assertEqual(self.store.generation("child")["status"], "suppressed")
        self.assertFalse(self.store.generation("child")["stop_reentered"])

    def test_schema_one_state_is_adopted_without_claiming_ownership(self):
        path = self.store.root / "state.json"
        path.write_text(json.dumps({"schema": 1, "baseline": ["old"],
                                   "records": {"legacy": {"status": "attached", "binding_id": "x"}}}))
        path.chmod(0o600)
        self.assertEqual(self.store.record("legacy")["ownership"], "unknown")
        data = json.loads(path.read_text())
        self.assertEqual(data["schema"], 2)
        self.assertEqual(data["baseline"], ["old"])

    def test_legacy_binding_is_never_close_owned_and_creation_is_positive(self):
        record = {"parent": session_parent(), "child": session_to_dict(make_session()), "pane_id": "p1", "backend_pid": None,
                  "server_socket": "/tmp/herdr.sock", "entrypoint": "/tmp/bin", "shell_pid": 12}
        save_binding(self.root, "legacy", record)
        loaded = load_existing_binding(self.root, "legacy")
        self.assertEqual(loaded["ownership"], "unknown")
        self.assertFalse(binding_is_close_owned(loaded))
        record.update(parent=session_parent(), child=session_to_dict(make_session()), ownership="created")
        save_binding(self.root, "created", record)
        self.assertTrue(binding_is_close_owned(load_existing_binding(self.root, "created")))

    def test_reused_or_suppressed_binding_cannot_gain_close_rights(self):
        record = {"parent": session_parent(), "child": session_to_dict(make_session()),
                  "pane_id": "p1", "backend_pid": None, "server_socket": "/tmp/herdr.sock",
                  "entrypoint": "/tmp/bin", "shell_pid": 12, "ownership": "reused"}
        save_binding(self.root, "reused", record)
        record["ownership"] = "created"
        save_binding(self.root, "reused", record)
        self.assertFalse(binding_is_close_owned(load_existing_binding(self.root, "reused")))
        record["ownership"] = "created"
        record["close_suppressed"] = True
        save_binding(self.root, "suppressed", record)
        self.assertFalse(binding_is_close_owned(load_existing_binding(self.root, "suppressed")))


def session_parent():
    home = Path("/tmp/codex-profile")
    context = Context(Harness.CODEX, str(home), home, home, home, "/tmp/codex.sock", "parent", "1:2:3")
    from harness_herdr_hooks.model import ParentBinding, parent_to_dict
    return parent_to_dict(ParentBinding(context, "server", "w1", "w1:t1", "w1:p1"))


if __name__ == "__main__":
    unittest.main()
