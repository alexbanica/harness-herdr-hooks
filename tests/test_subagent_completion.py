import tempfile
import unittest
import multiprocessing
import threading
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from harness_herdr_hooks.coordinator import Coordinator, NativeRuntime, run_observer
from harness_herdr_hooks import cli
from harness_herdr_hooks.model import (
    Context, Decision, Harness, Lifecycle, Outcome, ParentBinding, Session,
)
from harness_herdr_hooks.state import StateStore, save_binding
from harness_herdr_hooks.model import parent_to_dict, session_to_dict


def _real_close_chain(root, exited=False, mutation=None, managed=False, retain_user=False, pause_events=None):
    """Child-process target: exercise NativeRuntime.close_owned_pane end to end."""
    parent, context = fixtures()
    store = StateStore(Path(root), "real-close")
    store.establish_baseline(set())
    proxy = FakeProxy()
    provider = FakeProvider(proxy)
    runtime = FakeRuntime(provider)
    live_pid = os.getpid()
    stat_fields = Path(f"/proc/{live_pid}/stat").read_text().rsplit(")", 1)[1].split()
    live_start_ticks = int(stat_fields[19])
    pinned_pid = 2147483647 if exited else live_pid
    runtime.capture_owned_process = lambda *_args: {
        "pid": pinned_pid, "start_ticks": 999 if exited else live_start_ticks,
        "uid": os.getuid(), "executable": "/usr/bin/codex", "cwd": "/tmp",
        **({"tty": "/dev/pts/test", "tty_identity": [1, 2, 3]} if exited else {})}
    coordinator = Coordinator(store, runtime)
    child = Session(context, "parent", "child", Path("/tmp"), Lifecycle.RUNNING,
                    True, 1.0, ("parent",), None, "subagent", "t1", "t1")
    proxy.turns = [{"id": "t1", "status": "inProgress", "itemsView": "notLoaded", "items": []}]
    coordinator.handle(parent, child)
    binding = runtime.attached[0][1]
    binding_record = {"parent": parent_to_dict(parent),
        "child": session_to_dict(child), "pane_id": "p1", "backend_pid": None,
        "server_socket": "/tmp/codex.sock", "entrypoint": "/bin/true",
        "shell_pid": None, "ownership": "created", "kind": "subagent",
        "generation": "t1", "turn_id": "t1"}
    if managed:
        from harness_herdr_hooks.model import destination_to_dict
        from harness_herdr_hooks.tabs import SubagentTabManager
        manager = SubagentTabManager(store, parent.context, "server", "w1",
                                     _workspace_anchor=Path(root) / "canonical")
        class CreateClient:
            def create_subagent_tab(self, _workspace, _cwd, label, env=None):
                return "managed-tab", "p1"
        with manager.operations() as token:
            destination = manager.select_create(token, CreateClient(), Path("/tmp"), "Root", "parent", "root-gen")
            destination = manager.bind_child(token, destination, child_pane_id="p1")
        binding_record["destination"] = destination_to_dict(destination)
    save_binding(Path(root), binding, binding_record)
    if managed:
        from harness_herdr_hooks.attach import binding_tab_id
        if binding_tab_id(Path(root), binding_record, parent) != "managed-tab":
            raise AssertionError("managed binding destination did not validate")
    class Herdr:
        socket_path = Path("/tmp/codex.sock")
        closed = False
        def server_identity(self):
            return "server"
        def process_info(self, _pane):
            return {"foreground_processes": [] if exited else [{"pid": live_pid, "name": "codex", "cwd": "/tmp"}],
                    **({"tty": "/dev/pts/test"} if exited else {})}
        def snapshot(self):
            if mutation == "generation": store.begin_generation(context.key(), "t2", turn_id="t2")
            elif mutation == "suppressed": store.mark_suppressed(context.key(), "manual close observed")
            if managed:
                return {"tabs": list(self.tabs), "panes": list(self.panes)}
            return {"tabs": [], "panes": [{"pane_id": "p1", "workspace_id": "w1",
                                           "tab_id": "w1:t1", "agent_session": {}}]}
        def close(self, pane):
            if pause_events is not None:
                pause_events[0].set()
                if not pause_events[1].wait(4):
                    raise AssertionError("managed close pause was not released")
            self.closed = pane
            if managed:
                self.panes = [p for p in getattr(self, "panes", []) if p.get("pane_id") != pane]
                if not retain_user:
                    self.tabs = []
    herdr = Herdr()
    herdr.panes = []
    herdr.tabs = []
    if managed:
        # The live transport view includes the exact managed child reference;
        # the optional user pane is deliberately an unrelated occupant.
        herdr.panes = [{"pane_id": "p1", "workspace_id": "w1", "tab_id": "managed-tab",
                        "agent_session": {"kind": "id", "value": "child"}}]
        if retain_user:
            herdr.panes.append({"pane_id": "user-pane", "workspace_id": "w1",
                                "tab_id": "managed-tab", "agent_session": None})
        herdr.tabs = [{"tab_id": "managed-tab", "workspace_id": "w1",
                       "title": "Subagents: Root [parent]"}]
    native = NativeRuntime(store, provider, herdr, Path("/bin/true"), state_root=Path(root))
    native.verify_parent = lambda _parent: True
    if managed:
        provider.context = parent.context
        provider.main_metadata = lambda _parent: (parent.context, "Root")
    native.owned_pane_state = lambda *_args: "live"
    native._process_matches = lambda *_args: True
    with patch("harness_herdr_hooks.coordinator.matches_agent_session_ref", return_value=True), \
         patch("harness_herdr_hooks.herdr._codex_proc_proof",
               return_value=SimpleNamespace(pid=live_pid, start_ticks=live_start_ticks, uid=os.getuid(),
                                            executable=Path("/usr/bin/codex"), cwd=Path("/tmp"))), \
         patch("harness_herdr_hooks.tabs._resolve_workspace_anchor",
               return_value=Path(root) / "canonical"):
        coordinator.runtime = native
        provider.status = {"type": "idle"}
        proxy.turns = [{"id": "t1", "status": "completed", "itemsView": "notLoaded", "items": []}]
        with patch("harness_herdr_hooks.attach._tty_identity", return_value=(1, 2, 3)), \
             patch("harness_herdr_hooks.attach._tty_has_no_processes", return_value=True):
            coordinator.handle(parent, Session(context, "parent", "child", Path("/tmp"),
                Lifecycle.FINISHED, False, 1.0, ("parent",), None, "subagent", "t1", "t1"))
    if mutation is None and not herdr.closed:
        raise AssertionError("real NativeRuntime close path did not close pane")
    if mutation is not None and herdr.closed:
        raise AssertionError(f"NativeRuntime closed after final snapshot {mutation} mutation")
    if managed and mutation is None:
        if herdr.closed != "p1":
            raise AssertionError("managed cleanup did not close only the owned child pane")
        with manager.workspace_store.locked() as data:
            entries = [v for v in data.get("subagent_tabs", {}).get("reservations", {}).values()
                       if v.get("root_key") == manager.root_key]
        with manager.root_store.locked() as data:
            claim = data.get("subagent_tab", {})
        if retain_user:
            if not any(p.get("pane_id") == "user-pane" for p in herdr.panes):
                raise AssertionError("managed cleanup removed the retained user pane")
            if claim.get("status") != "created" or not entries or entries[0].get("status") == "released":
                raise AssertionError("user occupancy did not retain the managed claim and label")
        elif herdr.tabs or claim.get("status") != "removed" or not entries or entries[0].get("status") != "released":
            raise AssertionError("empty managed tab cleanup did not remove claim and release label")


def _advance_generation_during_close(root):
    parent, context = fixtures()
    store = StateStore(Path(root), "stale-generation")
    store.establish_baseline(set())
    proxy = FakeProxy()
    provider = FakeProvider(proxy)
    runtime = FakeRuntime(provider)
    coordinator = Coordinator(store, runtime)
    child = Session(context, "parent", "child", Path("/tmp"), Lifecycle.RUNNING,
                    True, 1.0, ("parent",), None, "subagent", "t1", "t1")
    proxy.turns = [{"id": "t1", "status": "inProgress", "itemsView": "notLoaded", "items": []}]
    coordinator.handle(parent, child)
    key = context.key()
    original_close = runtime.close_owned_pane
    def advance(*args):
        store.generation(key)
        store.begin_generation(key, "t2", turn_id="t2")
        return original_close(*args)
    runtime.close_owned_pane = advance
    provider.status = {"type": "idle"}
    proxy.turns = [{"id": "t1", "status": "completed", "itemsView": "notLoaded", "items": []}]
    coordinator.handle(parent, Session(context, "parent", "child", Path("/tmp"),
        Lifecycle.FINISHED, False, 1.0, ("parent",), None, "subagent", "t1", "t1"))
    record = store.record(key)
    if record.get("generation") != "t2" or record.get("cleanup", {}).get("outcome") == "closed":
        raise AssertionError("stale terminal cleanup overwrote new generation")


def _compete_for_managed_tab(root, busy_seen, continue_event, result):
    """Try operations in another process while managed cleanup owns both locks."""
    from harness_herdr_hooks.tabs import OperationBusy, SubagentTabManager
    parent, _context = fixtures()
    store = StateStore(Path(root), "real-close")
    manager = SubagentTabManager(store, parent.context, "server", "w1",
                                 _workspace_anchor=Path(root) / "canonical")
    try:
        with manager.operations():
            result.put("unexpectedly-acquired-during-cleanup")
            return
    except OperationBusy:
        busy_seen.set()
    if not continue_event.wait(4):
        result.put("competitor-timeout")
        return
    class CreateClient:
        def create_subagent_tab(self, _workspace, _cwd, _label, env=None):
            return "managed-tab-next", "pane-next"
    with manager.operations() as token:
        destination = manager.select_create(token, CreateClient(), Path("/tmp"),
                                            "Root", "parent", "root-next")
    result.put((destination.tab_id, destination.generation))


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

    def test_real_native_close_chain_completes_without_state_lock_deadlock(self):
        # A subprocess watchdog turns the former flock self-deadlock into a
        # bounded failure instead of hanging the entire suite.
        ctx = multiprocessing.get_context("fork")
        process = ctx.Process(target=_real_close_chain, args=(self.tmp.name,))
        process.start()
        process.join(4)
        if process.is_alive():
            process.terminate()
            process.join(2)
            self.fail("NativeRuntime.close_owned_pane deadlocked reentering StateStore.generation")
        self.assertEqual(process.exitcode, 0)

    def test_real_native_close_chain_closes_proven_empty_exited_display(self):
        ctx = multiprocessing.get_context("fork")
        process = ctx.Process(target=_real_close_chain, args=(self.tmp.name, True))
        process.start()
        process.join(4)
        if process.is_alive():
            process.terminate()
            process.join(2)
            self.fail("exited-display NativeRuntime close exceeded watchdog")
        self.assertEqual(process.exitcode, 0)

    def test_real_native_close_revalidates_generation_and_suppression_after_snapshot(self):
        for mutation in ("generation", "suppressed"):
            with self.subTest(mutation=mutation):
                ctx = multiprocessing.get_context("fork")
                process = ctx.Process(target=_real_close_chain, args=(self.tmp.name, False, mutation))
                process.start()
                process.join(4)
                if process.is_alive():
                    process.terminate()
                    process.join(2)
                    self.fail(f"NativeRuntime {mutation} revalidation exceeded watchdog")
                self.assertEqual(process.exitcode, 0)

    def test_real_managed_close_removes_empty_claim_and_releases_label(self):
        ctx = multiprocessing.get_context("fork")
        process = ctx.Process(target=_real_close_chain, args=(self.tmp.name, False, None, True, False))
        process.start(); process.join(4)
        if process.is_alive():
            process.terminate(); process.join(2)
            self.fail("managed NativeRuntime close exceeded watchdog")
        self.assertEqual(process.exitcode, 0)

    def test_real_managed_close_preserves_user_occupied_tab(self):
        ctx = multiprocessing.get_context("fork")
        process = ctx.Process(target=_real_close_chain, args=(self.tmp.name, False, None, True, True))
        process.start(); process.join(4)
        if process.is_alive():
            process.terminate(); process.join(2)
            self.fail("occupied managed NativeRuntime close exceeded watchdog")
        self.assertEqual(process.exitcode, 0)

    def test_managed_cleanup_serializes_cross_process_create(self):
        ctx = multiprocessing.get_context("fork")
        cleanup_entered, release_cleanup = ctx.Event(), ctx.Event()
        busy_seen, continue_competitor = ctx.Event(), ctx.Event()
        results = ctx.Queue()
        closer = ctx.Process(target=_real_close_chain,
                             args=(self.tmp.name, False, None, True, False,
                                   (cleanup_entered, release_cleanup)))
        closer.start()
        competitor = None
        try:
            self.assertTrue(cleanup_entered.wait(3), "managed cleanup did not reach the close while holding operation locks")
            competitor = ctx.Process(target=_compete_for_managed_tab,
                                     args=(self.tmp.name, busy_seen, continue_competitor, results))
            competitor.start()
            self.assertTrue(busy_seen.wait(3), "concurrent process acquired the managed operation lock")
            release_cleanup.set()
            closer.join(3)
            self.assertFalse(closer.is_alive(), "managed cleanup exceeded watchdog")
            self.assertEqual(closer.exitcode, 0)
            continue_competitor.set()
            competitor.join(3)
            self.assertFalse(competitor.is_alive(), "post-cleanup create exceeded watchdog")
            self.assertEqual(competitor.exitcode, 0)
            self.assertEqual(results.get(timeout=1), ("managed-tab-next", "root-next"))
        finally:
            release_cleanup.set()
            continue_competitor.set()
            for process in (closer, competitor):
                if process is not None and process.is_alive():
                    process.terminate()
                    process.join(1)

    def test_successful_close_is_monotonic_across_repeated_terminal_polls(self):
        self.proxy.turns = [self.turn("t1", "inProgress")]
        self.coordinator.handle(self.parent, self.child("t1"))
        self.proxy.turns = [self.turn("t1", "completed")]
        self.provider.status = {"type": "idle"}
        self.store.mark_generation_terminal(self.context.key(), "t1", "t1", "completed")
        child = self.child("t1", Lifecycle.FINISHED)
        self.coordinator.handle(self.parent, child)
        self.provider.status = {"type": "unknown"}
        self.coordinator.handle(self.parent, child)
        self.assertEqual(len(self.runtime.closed), 1)
        self.assertEqual(self.store.record(self.context.key())["cleanup"],
                         {"outcome": "closed", "generation": "t1"})

    def test_resumed_generation_closes_and_remains_monotonic(self):
        self.proxy.turns = [self.turn("t1", "inProgress")]
        self.coordinator.handle(self.parent, self.child("t1"))
        self.proxy.turns = [self.turn("t1", "completed")]
        self.provider.status = {"type": "idle"}
        self.coordinator.handle(self.parent, self.child("t1", Lifecycle.FINISHED))
        self.assertTrue(self.store.begin_generation(self.context.key(), "t2", turn_id="t2"))
        self.proxy.turns = [self.turn("t2", "inProgress")]
        self.coordinator.handle(self.parent, self.child("t2"))
        self.proxy.turns = [self.turn("t2", "completed")]
        resumed = self.child("t2", Lifecycle.FINISHED)
        self.coordinator.handle(self.parent, resumed)
        self.assertEqual(self.store.record(self.context.key())["cleanup"],
                         {"outcome": "closed", "generation": "t2"})
        close_count = len(self.runtime.closed)
        self.coordinator.handle(self.parent, resumed)
        self.assertEqual(len(self.runtime.closed), close_count)
        self.assertEqual(close_count, 2)

    def test_terminal_close_runs_without_state_lock_and_preserves_new_generation(self):
        # Keep the lock-reentry regression bounded even against old code.
        ctx = multiprocessing.get_context("fork")
        process = ctx.Process(target=_advance_generation_during_close, args=(self.tmp.name,))
        process.start()
        process.join(4)
        if process.is_alive():
            process.terminate()
            process.join(2)
            self.fail("terminal close held state lock during generation change")
        self.assertEqual(process.exitcode, 0)

    def test_concurrent_terminal_observation_claims_only_one_close(self):
        self.proxy.turns = [self.turn("t1", "inProgress")]
        self.coordinator.handle(self.parent, self.child("t1"))
        self.proxy.turns = [self.turn("t1", "completed")]
        self.provider.status = {"type": "idle"}
        self.store.mark_generation_terminal(self.context.key(), "t1", "t1", "completed")
        entered, release = threading.Event(), threading.Event()
        original_close = self.runtime.close_owned_pane
        def blocked_close(*args):
            entered.set()
            if not release.wait(2):
                return False
            return original_close(*args)
        self.runtime.close_owned_pane = blocked_close
        results = []
        first = threading.Thread(target=lambda: results.append(
            self.coordinator._handle_terminal(self.parent, self.child("t1", Lifecycle.FINISHED),
                                              self.context.key(), "t1", "completed")))
        first.start()
        self.assertTrue(entered.wait(2), "first close did not reach runtime")
        second = self.coordinator._handle_terminal(self.parent, self.child("t1", Lifecycle.FINISHED),
                                                   self.context.key(), "t1", "completed")
        self.assertEqual(second.decision, Decision.WAIT)
        release.set()
        first.join(2)
        self.assertFalse(first.is_alive(), "claimed close did not finish")
        self.assertEqual(len(self.runtime.closed), 1)
        self.assertNotIn("cleanup_claim", self.store.record(self.context.key()))

    def test_manual_suppression_during_unlocked_close_is_preserved(self):
        self.proxy.turns = [self.turn("t1", "inProgress")]
        self.coordinator.handle(self.parent, self.child("t1"))
        self.proxy.turns = [self.turn("t1", "completed")]
        self.provider.status = {"type": "idle"}
        original_close = self.runtime.close_owned_pane
        def suppress(*args):
            self.store.mark_suppressed(self.context.key(), "manual close observed")
            return original_close(*args)
        self.runtime.close_owned_pane = suppress
        self.coordinator.handle(self.parent, self.child("t1", Lifecycle.FINISHED))
        record = self.store.record(self.context.key())
        self.assertEqual(record["status"], "suppressed")
        self.assertNotEqual(record.get("cleanup", {}).get("outcome"), "closed")

    def test_abandoned_cleanup_claim_is_reclaimed_after_owner_exit(self):
        self.proxy.turns = [self.turn("t1", "inProgress")]
        self.coordinator.handle(self.parent, self.child("t1"))
        self.proxy.turns = [self.turn("t1", "completed")]
        self.provider.status = {"type": "idle"}
        with self.store.locked() as state:
            state["records"][self.context.key()]["cleanup_claim"] = {
                "token": "abandoned", "generation": "t1",
                "binding_id": self.runtime.attached[0][1],
                "owner_pid": 2147483647, "owner_start_ticks": 1}
        result = self.coordinator.handle(self.parent, self.child("t1", Lifecycle.FINISHED))
        self.assertEqual(result.decision, Decision.SKIP)
        self.assertEqual(len(self.runtime.closed), 1)
        self.assertNotIn("cleanup_claim", self.store.record(self.context.key()))

    def test_runtime_close_exception_releases_claim(self):
        self.proxy.turns = [self.turn("t1", "inProgress")]
        self.coordinator.handle(self.parent, self.child("t1"))
        self.proxy.turns = [self.turn("t1", "completed")]
        self.provider.status = {"type": "idle"}
        def fail(*_args):
            raise RuntimeError("provider failure")
        self.runtime.close_owned_pane = fail
        self.coordinator.handle(self.parent, self.child("t1", Lifecycle.FINISHED))
        self.assertNotIn("cleanup_claim", self.store.record(self.context.key()))

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

    def test_initial_snapshot_failure_does_not_seed_baseline_and_recovery_excludes_existing_child(self):
        store = StateStore(Path(self.tmp.name) / "startup", "test")
        child = self.child("existing")
        class Runtime:
            checks = 0
            def verify_parent(inner, _parent): return True
            def sessions(inner, _parent):
                inner.checks += 1
                if inner.checks == 1:
                    def broken():
                        yield child
                        raise RuntimeError("provider iterator failed")
                    return broken()
                return [child]
        runtime = Runtime()
        coordinator = Coordinator(store, runtime)
        self.assertEqual(coordinator.observe_initial(self.parent).decision, Decision.WAIT)
        self.assertFalse(store.baseline_ready())
        self.assertEqual(coordinator.observe_initial(self.parent).decision, Decision.BASELINE)
        self.assertTrue(store.baseline_ready())
        self.assertEqual(coordinator.handle(self.parent, child).decision, Decision.SKIP)

    def test_failed_startup_snapshot_cannot_be_accepted_on_restart_with_old_baseline(self):
        store = StateStore(Path(self.tmp.name) / "restart", "test")
        store.establish_baseline({"previous"})
        class Runtime:
            def verify_parent(self, _parent): return True
            def sessions(self, _parent):
                def broken():
                    yield self.child("partial")
                    raise RuntimeError("provider iterator failed")
                return broken()
        result = Coordinator(store, Runtime()).observe_initial(self.parent)
        self.assertEqual(result.decision, Decision.WAIT)
        with store.locked() as state:
            self.assertEqual(set(state["baseline"]), {"previous"})

    def test_successful_empty_startup_snapshot_is_valid(self):
        store = StateStore(Path(self.tmp.name) / "empty", "test")
        class Runtime:
            def verify_parent(self, _parent): return True
            def sessions(self, _parent): return iter(())
        self.assertEqual(Coordinator(store, Runtime()).observe_initial(self.parent).decision,
                         Decision.BASELINE)
        self.assertTrue(store.baseline_ready())

    def test_parent_verification_change_during_initial_snapshot_rejects_baseline(self):
        store = StateStore(Path(self.tmp.name) / "parent-change", "test")
        class Runtime:
            checks = 0
            def verify_parent(inner, _parent):
                inner.checks += 1
                return inner.checks == 1
            def sessions(self, _parent): return iter(())
        self.assertEqual(Coordinator(store, Runtime()).observe_initial(self.parent).decision,
                         Decision.WAIT)
        self.assertFalse(store.baseline_ready())

    def test_lock_owning_observer_publishes_running_then_ended(self):
        calls = []
        class Runtime:
            checks = 0
            def __init__(self, *_args): pass
            def verify_parent(self, _parent):
                self.checks += 1
                # Observer startup verifies the parent before and after the
                # initial provider snapshot, then once more before polling.
                return self.checks <= 3
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
