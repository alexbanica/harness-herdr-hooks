from __future__ import annotations

import multiprocessing
import tempfile
import unittest
from pathlib import Path

from harness_herdr_hooks.coordinator import Coordinator, MAX_RETRIES
from harness_herdr_hooks.model import Context, Harness, ParentBinding, Session, Lifecycle, Decision
from harness_herdr_hooks.state import StateStore
from harness_herdr_hooks.tabs import OperationBusy


def _watchdog_runtime_reentry(root, result):
    store = StateStore(Path(root), "coord-watch")
    parent = ParentBinding(Context(Harness.CODEX, "p", Path(root), Path(root), Path(root),
                                   "backend", "main", "inc"), "server", "ws", "tab", "pane")
    child = Session(Context(Harness.CODEX, "p", Path(root), Path(root), Path(root),
                            "backend", "child", "inc"), "main", "Child", Path(root),
                    Lifecycle.RUNNING, True, 1, generation="g1")
    store.establish_baseline(set())

    class Runtime:
        def verify_parent(self, _): return True
        def find_existing_pane(self, _p, c): store.record(c.context.key()); return None
        def can_attach_now(self, _p, c): store.record(c.context.key()); return True
        def open_and_attach(self, _p, c, _b): store.record(c.context.key()); return True
        def owned_pane_state(self, _p, c, _b): store.record(c.context.key()); return "live"
        def update_title(self, _b, _t): store.record(child.context.key())

    coord = Coordinator(store, Runtime())
    first = coord.handle(parent, child)
    # Exercise the attached title path too; each callback reenters real state.
    changed = Session(child.context, "main", "Renamed", Path(root), Lifecycle.RUNNING, True, 2,
                     generation="g1")
    second = coord.handle(parent, changed)
    result.put((first.decision.value, second.decision.value))


class CoordinatorTabTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.store = StateStore(self.root / "state", "coord-test")
        self.parent = ParentBinding(Context(Harness.CODEX, "p", self.root, self.root, self.root,
                                           "backend", "main", "inc"), "server", "ws", "tab", "pane")
        self.child = Session(Context(Harness.CODEX, "p", self.root, self.root, self.root,
                                     "backend", "child", "inc"), "main", "Child", self.root,
                             Lifecycle.RUNNING, True, 1, generation="g1")
        self.store.establish_baseline(set())

    def tearDown(self): self.tmp.cleanup()

    def test_runtime_callbacks_can_reenter_state_under_watchdog(self):
        ctx = multiprocessing.get_context("fork")
        result = ctx.Queue()
        proc = ctx.Process(target=_watchdog_runtime_reentry, args=(str(self.root / "subprocess"), result))
        proc.start(); proc.join(3)
        if proc.is_alive():
            proc.terminate(); proc.join()
            self.fail("runtime callback deadlocked while reentering StateStore")
        self.assertEqual(proc.exitcode, 0)
        self.assertEqual(result.get(timeout=1), (Decision.ATTACHED.value, Decision.ATTACHED.value))

    def test_operation_busy_does_not_consume_retries_or_leave_claim(self):
        class Runtime:
            busy = MAX_RETRIES + 1
            def verify_parent(self, _): return True
            def find_existing_pane(self, *_):
                if self.busy:
                    self.busy -= 1
                    raise OperationBusy("contended")
                return None
            def can_attach_now(self, *_): return True
            def open_and_attach(self, *_): return True
            def owned_pane_state(self, *_): return "unknown"
        runtime = Runtime(); coordinator = Coordinator(self.store, runtime)
        for _ in range(MAX_RETRIES + 1):
            result = coordinator.handle(self.parent, self.child)
            self.assertEqual(result.decision, Decision.WAIT)
            record = self.store.record(self.child.context.key())
            self.assertEqual(record["status"], "pending")
            self.assertEqual(record["attempts"], 0)
        result = coordinator.handle(self.parent, self.child)
        self.assertEqual(result.decision, Decision.ATTACHED)
        self.assertEqual(self.store.record(self.child.context.key())["attempts"], 0)

    def test_open_busy_is_deferred_until_lock_available(self):
        class Runtime:
            busy = MAX_RETRIES + 1
            def verify_parent(self, _): return True
            def find_existing_pane(self, *_): return None
            def can_attach_now(self, *_): return True
            def open_and_attach(self, *_):
                if self.busy:
                    self.busy -= 1
                    raise OperationBusy("contended")
                return True
            def owned_pane_state(self, *_): return "unknown"
        runtime = Runtime(); coordinator = Coordinator(self.store, runtime)
        for _ in range(MAX_RETRIES + 1):
            self.assertEqual(coordinator.handle(self.parent, self.child).decision, Decision.WAIT)
            record = self.store.record(self.child.context.key())
            self.assertEqual((record["status"], record["attempts"]), ("pending", 0))
        self.assertEqual(coordinator.handle(self.parent, self.child).decision, Decision.ATTACHED)
        self.assertEqual(self.store.record(self.child.context.key())["attempts"], 0)

    def test_external_callback_suppression_and_generation_are_not_overwritten(self):
        class Runtime:
            def verify_parent(self, _): return True
            def find_existing_pane(self, *_):
                with store.locked() as state:
                    rec = state["records"][child.context.key()]
                    rec["status"] = "suppressed"
                    rec["reason"] = "concurrent manual closure"
                    rec["generation"] = "newer"
                return None
            def can_attach_now(self, *_): return True
            def open_and_attach(self, *_): self.fail("stale claim must not attach")
            def owned_pane_state(self, *_): return "unknown"
        store, child = self.store, self.child
        outcome = Coordinator(store, Runtime()).handle(self.parent, child)
        self.assertEqual(outcome.decision, Decision.WAIT)
        rec = store.record(child.context.key())
        self.assertEqual(rec["status"], "suppressed")
        self.assertEqual(rec["generation"], "newer")


if __name__ == "__main__": unittest.main()
