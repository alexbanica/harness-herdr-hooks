import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from harness_herdr_hooks.coordinator import Coordinator, run_observer
from harness_herdr_hooks import cli
from harness_herdr_hooks.model import (
    Context, Decision, Harness, Lifecycle, Outcome, ParentBinding, Session,
)
from harness_herdr_hooks.state import StateStore


class FakeProxy:
    def __init__(self):
        self.turns = []
        self.items_requested = []

    def request(self, method, params):
        self.items_requested.append(params)
        if params.get("cursor"):
            return {"data": [], "nextCursor": None}
        return {"data": list(self.turns), "nextCursor": None}


class FakeProvider:
    def __init__(self, proxy):
        self.proxy = proxy
        self.status = {"type": "active"}

    def _read_thread(self, _thread_id):
        return {"status": self.status}


class FakeRuntime:
    def __init__(self, provider):
        self.provider = provider
        self.closed = []
        self.attached = []
        self.pane_state = "live"

    def verify_parent(self, _parent):
        return True

    def find_existing_pane(self, _parent, _child):
        return None

    def open_and_attach(self, _parent, child, binding_id):
        self.attached.append((child.generation, binding_id))
        return True

    def can_attach_now(self, _parent, child):
        return child.lifecycle == Lifecycle.RUNNING and child.attachable

    def owned_pane_state(self, _parent, _child, _binding_id):
        return self.pane_state

    def close_owned_pane(self, _parent, child, binding_id, generation, status, _process_pin):
        if self.pane_state != "live":
            return False
        self.closed.append((child.generation, binding_id, generation, status))
        return True

    def capture_owned_process(self, _parent, _child, _binding_id):
        return {"pid": 42, "start_ticks": 99, "uid": 1000,
                "executable": "/usr/bin/codex", "cwd": "/tmp"}

    def update_title(self, _binding_id, _title):
        pass


def fixtures():
    home = Path("/tmp/codex-profile")
    context = Context(Harness.CODEX, str(home), home, home, home,
                      "/tmp/codex.sock", "child", "1:2:3")
    parent = ParentBinding(context=Context(Harness.CODEX, str(home), home, home, home,
                                           "/tmp/codex.sock", "parent", "1:2:3"),
                           herdr_server_id="server", workspace_id="w1",
                           tab_id="w1:t1", pane_id="w1:p1")
    return parent, context


class CompletionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = StateStore(Path(self.tmp.name), "test")
        self.store.establish_baseline(set())
        self.parent, self.context = fixtures()
        self.proxy = FakeProxy()
        self.provider = FakeProvider(self.proxy)
        self.runtime = FakeRuntime(self.provider)
        self.coordinator = Coordinator(self.store, self.runtime)

    def tearDown(self):
        self.tmp.cleanup()

    def child(self, turn, lifecycle=Lifecycle.RUNNING):
        return Session(self.context, "parent", "child", Path("/tmp"), lifecycle,
                       lifecycle == Lifecycle.RUNNING, 1.0, ("parent",), None,
                       "subagent", turn, turn)

    def turn(self, turn, status):
        return {"id": turn, "status": status, "itemsView": "notLoaded", "items": []}

    def test_running_attaches_once_and_terminal_generation_closes_owned_pane(self):
        self.proxy.turns = [self.turn("t1", "inProgress")]
        self.assertEqual(self.coordinator.handle(self.parent, self.child("t1")).decision,
                         Decision.ATTACHED)
        binding = self.runtime.attached[0][1]
        self.provider.status = {"type": "idle"}
        self.proxy.turns = [self.turn("t1", "completed")]
        result = self.coordinator.handle(self.parent, self.child("t1", Lifecycle.FINISHED))
        self.assertEqual(result.decision, Decision.SKIP)
        self.assertEqual(self.runtime.closed, [("t1", binding, "t1", "completed")])
        record = self.store.record(self.context.key())
        self.assertEqual(record["cleanup"], {"outcome": "closed", "generation": "t1"})
        self.assertTrue(all(p["itemsView"] == "notLoaded" for p in self.proxy.items_requested))

    def test_successful_close_is_monotonic_across_repeated_terminal_polls(self):
        self.proxy.turns = [self.turn("t1", "inProgress")]
        self.coordinator.handle(self.parent, self.child("t1"))
        self.proxy.turns = [self.turn("t1", "completed")]
        self.provider.status = {"type": "idle"}
        child = self.child("t1", Lifecycle.FINISHED)
        self.coordinator.handle(self.parent, child)
        self.provider.status = {"type": "unknown"}
        self.coordinator.handle(self.parent, child)
        self.assertEqual(len(self.runtime.closed), 1)
        self.assertEqual(self.store.record(self.context.key())["cleanup"],
                         {"outcome": "closed", "generation": "t1"})

    def test_unverified_terminal_cleanup_is_recorded(self):
        self.proxy.turns = [self.turn("t1", "inProgress")]
        self.coordinator.handle(self.parent, self.child("t1"))
        self.proxy.turns = [self.turn("t1", "completed")]
        self.runtime.pane_state = "unknown"
        self.coordinator.handle(self.parent, self.child("t1", Lifecycle.FINISHED))
        self.assertEqual(self.store.record(self.context.key())["cleanup"],
                         {"outcome": "retained-unverified", "generation": "t1"})

    def test_stop_hint_and_temporary_idle_never_close_in_progress_turn(self):
        self.proxy.turns = [self.turn("t1", "inProgress")]
        self.coordinator.handle(self.parent, self.child("t1"))
        key = self.context.key()
        self.store.note_stop_hint(key, "t1", "t1", stop_hook_active=True)
        self.provider.status = {"type": "idle"}
        result = self.coordinator.handle(self.parent, self.child("t1", Lifecycle.FINISHED))
        self.assertEqual(result.decision, Decision.SKIP)
        self.assertEqual(self.runtime.closed, [])

    def test_stop_reentry_hint_does_not_prevent_confirmed_terminal_close(self):
        self.proxy.turns = [self.turn("t1", "inProgress")]
        self.coordinator.handle(self.parent, self.child("t1"))
        key = self.context.key()
        self.store.note_stop_hint(key, "t1", "t1", stop_hook_active=True)
        self.provider.status = {"type": "idle"}
        self.proxy.turns = [self.turn("t1", "completed")]
        result = self.coordinator.handle(self.parent, self.child("t1", Lifecycle.FINISHED))
        self.assertEqual(result.decision, Decision.SKIP)
        self.assertEqual(len(self.runtime.closed), 1)

    def test_persisted_generation_mismatch_retains_pane_even_for_latest_terminal(self):
        self.proxy.turns = [self.turn("t1", "inProgress")]
        self.coordinator.handle(self.parent, self.child("t1"))
        self.store.begin_generation(self.context.key(), "t2", turn_id="t2")
        self.provider.status = {"type": "idle"}
        self.proxy.turns = [self.turn("t1", "completed")]
        self.coordinator.handle(self.parent, self.child("t1", Lifecycle.FINISHED))
        self.assertEqual(self.runtime.closed, [])

    def test_stale_stop_hint_retains_pane(self):
        self.proxy.turns = [self.turn("t1", "inProgress")]
        self.coordinator.handle(self.parent, self.child("t1"))
        key = self.context.key()
        self.store.note_stop_hint(key, "t1", "t1", stop_hook_active=False)
        with self.store.locked() as state:
            state["records"][key]["stop_hints"][0]["turn_id"] = "old"
        self.provider.status = {"type": "idle"}
        self.proxy.turns = [self.turn("t1", "completed")]
        self.coordinator.handle(self.parent, self.child("t1", Lifecycle.FINISHED))
        self.assertEqual(self.runtime.closed, [])

    def test_duplicate_observer_loser_does_not_publish_or_skip_provider_cleanup(self):
        calls = []
        class Provider:
            def close(self): calls.append("provider-closed")
        provider = Provider()
        with self.store.observing():
            run_observer(self.parent, self.store, provider, object(), Path("/bin/true"),
                         Path(self.tmp.name), on_start=lambda: calls.append("running"),
                         on_end=lambda: calls.append("ended"))
        self.assertEqual(calls, ["provider-closed"])

    def test_lock_owning_observer_publishes_running_then_ended(self):
        calls = []
        class Runtime:
            checks = 0
            def __init__(self, *_args): pass
            def verify_parent(self, _parent):
                self.checks += 1
                return self.checks <= 2
            def observe_initial(self, _parent): return Outcome(Decision.BASELINE)
            def sessions(self, _parent): return []
        class Provider:
            def close(self): calls.append("provider-closed")
        with patch("harness_herdr_hooks.coordinator.NativeRuntime", Runtime), \
             patch("harness_herdr_hooks.coordinator.time.sleep", lambda _n: None):
            run_observer(self.parent, self.store, Provider(), object(), Path("/bin/true"),
                         Path(self.tmp.name), on_start=lambda:(calls.append("running"),
                             cli._publish_observer(Path(self.tmp.name), self.parent, "running", {"start_ticks": 1})),
                         on_end=lambda:(calls.append("ended"),
                             cli._publish_observer(Path(self.tmp.name), self.parent, "ended", {"start_ticks": 1})))
        observer = cli._runtime_read(cli._runtime_path(Path(self.tmp.name), str(self.parent.context.config_root)))["observer"]
        self.assertEqual(calls, ["running", "ended", "provider-closed"])
        self.assertEqual(observer["state"], "ended")

    def test_unknown_status_old_turn_and_new_generation_retain_pane(self):
        self.proxy.turns = [self.turn("t1", "inProgress")]
        self.coordinator.handle(self.parent, self.child("t1"))
        self.proxy.turns = [self.turn("t2", "inProgress"), self.turn("t1", "completed")]
        self.provider.status = {"type": "unknown"}
        result = self.coordinator.handle(self.parent, self.child("t1", Lifecycle.FINISHED))
        self.assertEqual(result.decision, Decision.SKIP)
        self.assertEqual(self.runtime.closed, [])
        self.assertEqual(self.runtime.attached[0][0], "t1")

    def test_manual_closure_is_suppressed_and_failure_is_terminal_only_with_metadata(self):
        self.proxy.turns = [self.turn("t1", "inProgress")]
        self.coordinator.handle(self.parent, self.child("t1"))
        self.runtime.pane_state = "closed"
        # A pane already manually closed is never closed again.
        self.proxy.turns = [self.turn("t1", "failed")]
        self.provider.status = {"type": "idle"}
        self.coordinator.handle(self.parent, self.child("t1", Lifecycle.FINISHED))
        self.assertEqual(self.runtime.closed, [])


if __name__ == "__main__":
    unittest.main()
