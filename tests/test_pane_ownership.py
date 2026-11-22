from __future__ import annotations

import unittest
import shutil
import tempfile
import os
import multiprocessing
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from harness_herdr_hooks.model import Context, Harness
from harness_herdr_hooks.coordinator import NativeRuntime


def _standalone_fixture(root):
    import hashlib
    import json
    from harness_herdr_hooks.model import CreationProof, Session, Lifecycle
    from harness_herdr_hooks.state import StateStore
    root = Path(root)
    profile = root / "profile"
    sessions = profile / "sessions"
    sessions.mkdir(parents=True, exist_ok=True)
    parent_file = sessions / "parent.jsonl"
    parent_file.write_text('{"type":"session_meta","payload":{"id":"parent"}}\n')
    context = Context(Harness.CODEX, str(profile), profile, profile, profile,
                      "/socket", "parent", "1:2:3")
    from harness_herdr_hooks.model import ParentBinding
    parent = ParentBinding(context, "server", "ws", "tab", "pane", session_path=parent_file)
    store = StateStore(root / "state", "standalone-test")
    cursor = {"device": 1, "inode": 2, "offset": 0, "parent_id": "parent",
              "path": str(parent_file), "observed_size": 0, "skip_to_newline": False}
    event = SimpleNamespace(parent_id="parent", turn_id="turn", item_id="item",
                            child_id="standalone", cwd_sha256=None)
    store.commit_task_records(cursor, [event],
        parent={"parent_id": "parent", "path": str(parent_file), "device": 1,
                "inode": 2, "owner_uid": os.getuid()},
        context={"profile": context.profile, "backend_id": context.backend_id,
                 "backend_instance": context.backend_instance, "session_id": "parent"},
        destination={"server_id": "server", "workspace_id": "ws", "tab_id": "tab", "pane_id": "pane"}, now=1)
    event_key = hashlib.sha256(json.dumps(["parent", "turn", "item"], separators=(",", ":")).encode()).hexdigest()
    store.update_task_candidate(event_key, status="verified", now=2)
    store.establish_baseline(set())
    child_context = Context(Harness.CODEX, context.profile, context.config_root,
        context.data_root, context.state_root, context.backend_id, "standalone", context.backend_instance)
    child = Session(child_context, "parent", "safe task", Path("/tmp/work"), Lifecycle.RUNNING,
                    True, 3, kind="standalone", creation_proof=CreationProof("parent", "turn", "item", "standalone"))
    return store, parent, child, event_key


def _watchdog_standalone(root, result_queue):
    """Real child process: state reads inside runtime calls deadlock if coordinator holds state.lock."""
    from harness_herdr_hooks.coordinator import Coordinator
    store, parent, child, _ = _standalone_fixture(root)
    class Runtime:
        def verify_parent(self, value): return value == parent
        def find_existing_pane(self, p, c):
            store.record(c.context.key())
            store.task_discovery()
            return None
        def can_attach_now(self, p, c):
            store.record(c.context.key())
            return True
        def open_and_attach(self, p, c, binding):
            store.task_discovery()
            return True
        def owned_pane_state(self, p, c, binding): return "unknown"
        def update_title(self, binding, title): pass
    result_queue.put(Coordinator(store, Runtime()).handle(parent, child).decision.value)


class PaneOwnershipTests(unittest.TestCase):





    def test_standalone_external_runtime_calls_do_not_hold_state_lock(self):
        with tempfile.TemporaryDirectory() as root:
            ctx = multiprocessing.get_context("fork")
            result = ctx.Queue()
            process = ctx.Process(target=_watchdog_standalone, args=(root, result))
            process.start()
            process.join(4)
            if process.is_alive():
                process.terminate()
                process.join(1)
                self.fail("standalone runtime call blocked on coordinator state lock")
            self.assertEqual(process.exitcode, 0)
            self.assertEqual(result.get(timeout=1), "attached")

    def test_standalone_baseline_restart_and_concurrent_observation_open_once(self):
        import tempfile
        from harness_herdr_hooks.coordinator import Coordinator
        with tempfile.TemporaryDirectory() as root:
            store, parent, child, _ = _standalone_fixture(root)
            class Runtime:
                opened = 0
                gate = threading.Event()
                calls = 0
                def verify_parent(self, p): return p == parent
                def sessions(self, p): return [child]
                def find_existing_pane(self, p, c): return None
                def can_attach_now(self, p, c): return True
                def open_and_attach(self, p, c, binding):
                    self.opened += 1
                    time.sleep(.15)
                    return True
                def owned_pane_state(self, p, c, binding): return "unknown"
                def update_title(self, binding, title): pass
            runtime = Runtime()
            coordinator = Coordinator(store, runtime)
            # A restarted observer sees the standalone session, but it must not
            # turn that newly created task into a pre-existing baseline entry.
            coordinator.observe_initial(parent)
            results = []
            def observe():
                try:
                    results.append(coordinator.handle(parent, child))
                except BlockingIOError:
                    # Observer serialization is deliberately nonblocking.
                    results.append(None)
            threads = [threading.Thread(target=observe) for _ in range(2)]
            for thread in threads: thread.start()
            for thread in threads: thread.join(2)
            self.assertTrue(all(not thread.is_alive() for thread in threads))
            self.assertEqual(runtime.opened, 1)
            self.assertEqual(sum(x is not None and x.decision.value == "attached" for x in results), 1)
            with store.locked() as state:
                self.assertNotIn(child.context.key(), state.get("baseline", []))

    def test_initial_snapshot_baselines_native_sessions_but_keeps_standalone_candidate_eligible(self):
        from dataclasses import replace
        from harness_herdr_hooks.coordinator import Coordinator
        with tempfile.TemporaryDirectory() as root:
            store, parent, child, _ = _standalone_fixture(root)
            native = replace(child, context=replace(child.context, session_id="native"),
                             kind="subagent", creation_proof=None)
            class Runtime:
                def verify_parent(self, value): return value == parent
                def initial_sessions(self, _parent): return [native, child]
            outcome = Coordinator(store, Runtime()).observe_initial(parent)
            self.assertEqual(outcome.decision.value, "baseline")
            with store.locked() as state:
                self.assertEqual(state["baseline"], [native.context.key()])

    def test_standalone_candidate_mutation_during_attach_fails_closed(self):
        import tempfile
        from harness_herdr_hooks.coordinator import Coordinator
        with tempfile.TemporaryDirectory() as root:
            store, parent, child, event_key = _standalone_fixture(root)
            class Runtime:
                def verify_parent(self, p): return p == parent
                def find_existing_pane(self, p, c):
                    store.update_task_candidate(event_key, status="pending", now=4)
                    return None
                def can_attach_now(self, p, c): return True
                def open_and_attach(self, p, c, binding): return True
                def owned_pane_state(self, p, c, binding): return "unknown"
                def update_title(self, binding, title): pass
            outcome = Coordinator(store, Runtime()).handle(parent, child)
            self.assertEqual(outcome.decision.value, "wait")
            state = store.task_discovery()
            self.assertEqual(state["pending"][0]["status"], "pending")
            self.assertFalse(any(x["status"] == "attached" for x in state["outcomes"]))
            self.assertNotEqual(store.record(child.context.key()).get("status"), "attached")

    def test_standalone_pending_candidate_authority_change_during_attach_fails_closed(self):
        import tempfile
        from harness_herdr_hooks.coordinator import Coordinator
        with tempfile.TemporaryDirectory() as root:
            store, parent, child, _ = _standalone_fixture(root)
            class Runtime:
                def verify_parent(self, p): return p == parent
                def find_existing_pane(self, p, c):
                    with store.locked() as state:
                        state["task_discovery"]["authority"]["destination"]["pane_id"] = "changed"
                    return None
                def can_attach_now(self, p, c): return True
                def open_and_attach(self, p, c, binding): return True
                def owned_pane_state(self, p, c, binding): return "unknown"
                def update_title(self, binding, title): pass
            outcome = Coordinator(store, Runtime()).handle(parent, child)
            self.assertEqual(outcome.decision.value, "wait")
            state = store.task_discovery()
            self.assertEqual(state["pending"][0]["status"], "verified")
            self.assertFalse(any(x["status"] == "attached" for x in state["outcomes"]))
            self.assertNotEqual(store.record(child.context.key()).get("status"), "attached")

    def test_standalone_terminal_replay_rejects_changed_authority(self):
        import tempfile
        from harness_herdr_hooks.coordinator import Coordinator
        with tempfile.TemporaryDirectory() as root:
            store, parent, child, _ = _standalone_fixture(root)
            class Runtime:
                mutate = False
                def verify_parent(self, p): return p == parent
                def find_existing_pane(self, p, c): return None
                def can_attach_now(self, p, c): return True
                def open_and_attach(self, p, c, binding): return True
                def owned_pane_state(self, p, c, binding):
                    if self.mutate:
                        with store.locked() as state:
                            state["task_discovery"]["authority"]["destination"]["pane_id"] = "changed"
                        return "live"
                    return "unknown"
                def update_title(self, binding, title): pass
            runtime = Runtime(); coordinator = Coordinator(store, runtime)
            self.assertEqual(coordinator.handle(parent, child).decision.value, "attached")
            runtime.mutate = True
            replay = coordinator.handle(parent, child)
            self.assertEqual(replay.decision.value, "wait")
            self.assertEqual(store.record(child.context.key())["status"], "attached")
            self.assertEqual(store.task_discovery()["outcomes"][-1]["status"], "attached")

    def test_standalone_replay_suppresses_verified_manual_close(self):
        import tempfile
        from harness_herdr_hooks.coordinator import Coordinator
        with tempfile.TemporaryDirectory() as root:
            store, parent, child, _ = _standalone_fixture(root)
            class Runtime:
                closed = False
                def verify_parent(self, p): return p == parent
                def find_existing_pane(self, p, c): return None
                def can_attach_now(self, p, c): return True
                def open_and_attach(self, p, c, binding): return True
                def owned_pane_state(self, p, c, binding): return "closed" if self.closed else "unknown"
                def update_title(self, binding, title): pass
            runtime = Runtime(); coordinator = Coordinator(store, runtime)
            self.assertEqual(coordinator.handle(parent, child).decision.value, "attached")
            runtime.closed = True
            self.assertEqual(coordinator.handle(parent, child).decision.value, "skip")
            self.assertEqual(store.record(child.context.key())["status"], "suppressed")
            self.assertEqual(coordinator.handle(parent, child).decision.value, "skip")

    def test_standalone_existing_pane_reuse_requires_positive_attachability(self):
        import tempfile
        from harness_herdr_hooks.coordinator import Coordinator
        with tempfile.TemporaryDirectory() as root:
            store, parent, child, _ = _standalone_fixture(root)
            class Runtime:
                def verify_parent(self, p): return p == parent
                def find_existing_pane(self, p, c): return "reused-binding"
                def can_attach_now(self, p, c): return False
                def open_and_attach(self, p, c, binding): self.fail("must not open when not attachable")
                def owned_pane_state(self, p, c, binding): return "unknown"
                def update_title(self, binding, title): pass
            outcome = Coordinator(store, Runtime()).handle(parent, child)
            self.assertEqual(outcome.decision.value, "wait")
            self.assertNotEqual(store.record(child.context.key()).get("status"), "attached")




if __name__ == '__main__':
    unittest.main()
