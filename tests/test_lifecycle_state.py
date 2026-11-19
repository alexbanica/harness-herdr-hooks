import json
import tempfile
import unittest
from pathlib import Path

from harness_herdr_hooks.model import (
    Context, CreationProof, Harness, Lifecycle, Session, session_from_dict, session_to_dict,
)
from harness_herdr_hooks.state import (
    StateStore, binding_is_close_owned, load_existing_binding, save_binding,
)
from harness_herdr_hooks.coordinator import Coordinator


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

    def test_standalone_kind_requires_minimum_creation_proof(self):
        current = session_to_dict(make_session())
        current["kind"] = "standalone"
        current["creation_proof"] = {"parent_id": "parent", "turn_id": "turn",
                                     "item_id": "item", "child_id": "child"}
        current["context"]["session_id"] = "child"
        current["parent_session_id"] = "parent"
        standalone = session_from_dict(current)
        self.assertEqual(standalone.kind, "standalone")
        self.assertEqual(standalone.creation_proof, CreationProof("parent", "turn", "item", "child"))
        del current["creation_proof"]
        with self.assertRaises(ValueError): session_from_dict(current)

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

    def test_terminal_metadata_does_not_erase_manual_suppression(self):
        self.store.begin_generation("child", "turn-1", turn_id="turn-1")
        self.store.mark_suppressed("child", "manual close observed")
        self.assertTrue(self.store.mark_generation_terminal("child", "turn-1", "turn-1", "completed"))
        record = self.store.generation("child")
        self.assertEqual(record["status"], "suppressed")
        self.assertEqual(record["turn_status"], "completed")
        self.assertIn("turn-1", record["terminal_generations"])

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

    def test_pending_cleanup_snapshot_is_persisted_and_suppression_wins(self):
        self.store.begin_generation("child", "turn-1", turn_id="turn-1")
        with self.store.locked() as data:
            data["records"]["child"].update(status="attached", binding_id="b1", ownership="created")
        self.assertIn("child", StateStore(self.root, "test").pending_cleanup_records())
        self.store.mark_suppressed("child", "manual close")
        self.assertNotIn("child", self.store.pending_cleanup_records())

    def test_runtime_reconciles_persisted_owned_child_missing_from_discovery(self):
        from harness_herdr_hooks.coordinator import NativeRuntime
        from harness_herdr_hooks.model import parent_from_dict
        child = make_session()
        parent = parent_from_dict(session_parent())
        save_binding(self.root, "bind-1", {
            "parent": session_parent(), "child": session_to_dict(child), "pane_id": "p1",
            "backend_pid": None, "server_socket": "/tmp/herdr.sock", "entrypoint": "/tmp/bin",
            "shell_pid": 12, "ownership": "created", "generation": "turn-1", "turn_id": "turn-1"})
        self.store.begin_generation(child.context.key(), "turn-1", turn_id="turn-1")
        with self.store.locked() as data:
            data["records"][child.context.key()].update(status="attached", binding_id="bind-1", ownership="created")
        class Provider:
            def sessions(self, _parent): return ()
        runtime = NativeRuntime.__new__(NativeRuntime)
        runtime.store, runtime.provider, runtime.state_root = self.store, Provider(), self.root
        runtime.verify_parent = lambda _parent: True
        self.assertEqual(runtime.initial_sessions(parent), [])
        reconciled = list(runtime.sessions(parent))
        self.assertEqual(len(reconciled), 1)
        self.assertEqual(reconciled[0].generation, "turn-1")

    def test_initial_native_snapshot_catches_lazy_provider_failure_and_accepts_empty(self):
        from harness_herdr_hooks.coordinator import NativeRuntime
        from harness_herdr_hooks.model import parent_from_dict
        parent = parent_from_dict(session_parent())
        class Provider:
            def sessions(self, _parent):
                def broken():
                    yield make_session()
                    raise RuntimeError("lazy enumeration failed")
                return broken()
        runtime = NativeRuntime.__new__(NativeRuntime)
        runtime.provider = Provider()
        runtime.verify_parent = lambda _parent: True
        self.assertIsNone(runtime.initial_sessions(parent))
        runtime.provider.sessions = lambda _parent: iter(())
        self.assertEqual(runtime.initial_sessions(parent), [])

    def test_terminal_confirmation_accepts_not_loaded_but_rejects_active_and_newer(self):
        class Proxy:
            turns = []
            def request(inner, method, params):
                self.assertEqual(method, "thread/turns/list")
                self.assertEqual(params["itemsView"], "notLoaded")
                return {"data": inner.turns, "nextCursor": None}
        class Provider:
            proxy = Proxy()
            thread_status = "notLoaded"
            def _read_thread(inner, _thread_id):
                return {"status": {"type": inner.thread_status}}
        class Runtime:
            provider = Provider()
        child = make_session()
        self.store.begin_generation(child.context.key(), "turn-1", turn_id="turn-1")
        coordinator = Coordinator(self.store, Runtime())
        Provider.proxy.turns = [{"id": "turn-1", "status": "completed", "items": []}]
        self.store.note_stop_hint(child.context.key(), "turn-1", "turn-1", stop_hook_active=True)
        self.assertEqual(coordinator._confirmed_terminal(child, "turn-1"), "completed")
        Provider.thread_status = "active"
        self.assertIsNone(coordinator._confirmed_terminal(child, "turn-1"))
        Provider.thread_status = "idle"
        Provider.proxy.turns = [{"id": "turn-2", "status": "inProgress", "items": []},
                                {"id": "turn-1", "status": "completed", "items": []}]
        self.assertIsNone(coordinator._confirmed_terminal(child, "turn-1"))

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
