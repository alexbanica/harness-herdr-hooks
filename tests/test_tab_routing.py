import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

from harness_herdr_hooks.coordinator import NativeRuntime
from harness_herdr_hooks.coordinator import Coordinator
from harness_herdr_hooks.model import Context, Harness, Lifecycle, ParentBinding, Session
from harness_herdr_hooks.state import StateStore, load_existing_binding


class FakeProvider:
    def __init__(self, root): self.root = root
    def main_metadata(self, parent): return self.root, "Main"
    def can_attach_now(self, parent, child): return True
    def attach_argv(self, child): return ["codex" if child.context.harness == Harness.CODEX else "opencode", "--session", child.context.session_id]


class FakeHerdr:
    """Transport boundary fake: snapshots, shell evidence and wrapper acknowledgement are real-shaped."""
    socket_path = Path("/tmp/fake-herdr.sock")
    def __init__(self):
        self.tabs, self.panes = [], []
        self.creates, self.splits, self.sent, self.renames = [], [], [], []
        self.next_id = 0
    def server_identity(self): return "server"
    def snapshot(self): return {"tabs": list(self.tabs), "panes": list(self.panes)}
    def create_subagent_tab(self, workspace, cwd, label, env=None):
        self.creates.append((workspace, cwd, label, env)); self.next_id += 1
        tab, pane = f"tab{self.next_id}", f"pane{self.next_id}"
        self.tabs.append({"tab_id": tab, "workspace_id": workspace, "title": label})
        self.panes.append({"pane_id": pane, "tab_id": tab, "workspace_id": workspace,
                           "cwd": str(Path(cwd).resolve()), "agent_session": None})
        return tab, pane
    def split_subagent_tab(self, target, workspace, tab, cwd, env=None):
        self.splits.append(target); self.next_id += 1; pane = f"pane{self.next_id}"
        self.panes.append({"pane_id": pane, "tab_id": tab, "workspace_id": workspace,
                           "cwd": str(Path(cwd).resolve()), "agent_session": None})
        return pane
    def process_info(self, pane):
        return {"shell_pid": 10, "foreground_processes": [{"pid": 10, "argv0": "bash", "argv": ["bash"],
                "cwd": next(p["cwd"] for p in self.panes if p["pane_id"] == pane)}]}
    def rename(self, pane, label): self.renames.append((pane, label))
    def close(self, pane):
        self.panes = [row for row in self.panes if row["pane_id"] != pane]
        tabs = {row["tab_id"] for row in self.panes}
        self.tabs = [row for row in self.tabs if row["tab_id"] in tabs]
    def safe_label(self, title, harness, session): return f"{title} [{session}]"
    def send_text(self, pane, text):
        self.sent.append((pane, text))
        row = next(p for p in self.panes if p["pane_id"] == pane)
        row["agent_session"] = {"kind": "id", "value": "attached"}
    def send_keys(self, pane, keys): pass
    def wait_for_attachment(self, pane, context, backend_pid, expected_argv=None, session_path=None):
        row = next(p for p in self.panes if p["pane_id"] == pane)
        row["agent_session"] = {"kind": "id", "value": context.session_id}
        return expected_argv == ["codex" if context.harness == Harness.CODEX else "opencode", "--session", context.session_id]


class TabRoutingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.root = Path(self.tmp.name)
        self.anchor_patch = patch("harness_herdr_hooks.tabs._resolve_workspace_anchor",
                                  return_value=self.root / "canonical")
        self.anchor_patch.start()
    def tearDown(self):
        self.anchor_patch.stop()
        self.tmp.cleanup()
    def fixture(self, harness=Harness.CODEX, root_id="main"):
        backend = "/tmp/codex.sock" if harness == Harness.CODEX else "http://127.0.0.1:1234"
        ctx = Context(harness, "p", self.root, self.root, self.root, backend, root_id, "instance")
        workspace = f"workspace-{harness.value}"
        parent = ParentBinding(ctx, "server", workspace, "root-tab", "root-pane")
        provider, herdr = FakeProvider(ctx), FakeHerdr()
        runtime = NativeRuntime(StateStore(self.root, f"routing-{harness.value}-{root_id}"), provider, herdr,
                                Path("/bin/true"), state_root=self.root)
        runtime.verify_parent = lambda _parent: True
        runtime._process_matches = lambda _proc, child: True
        childctx = Context(harness, "p", self.root, self.root, self.root, backend, "child", "instance")
        child = Session(childctx, root_id, "child", self.root, Lifecycle.RUNNING, True, 1.0,
                        kind="subagent", generation="turn-1")
        return ctx, parent, child, runtime, herdr
    def test_full_open_reuses_initial_tab_pane_then_targets_owned_sibling(self):
        for harness in (Harness.CODEX, Harness.OPENCODE):
            with self.subTest(harness=harness):
                _, parent, child, runtime, herdr = self.fixture(harness)
                runtime.can_attach_now = lambda *_: True
                first_id, second_id = f"{harness.value}-one", f"{harness.value}-two"
                self.assertTrue(runtime.open_and_attach(parent, child, first_id))
                first = load_existing_binding(self.root, first_id)
                tab, initial = first["destination"]["tab_id"], first["destination"]["initial_pane_id"]
                self.assertEqual(first["pane_id"], initial)
                self.assertEqual(herdr.creates.__len__(), 1)
                self.assertEqual(herdr.splits, [])
                self.assertTrue(runtime.open_and_attach(parent, child, second_id))
                second = load_existing_binding(self.root, second_id)
                self.assertEqual(second["destination"]["tab_id"], tab)
                self.assertEqual(herdr.splits, [initial])
                self.assertEqual(second["destination"]["child_pane_id"], second["pane_id"])
                self.assertEqual(len(herdr.creates), 1)

    def test_user_pane_is_safe_split_anchor_after_owned_child_disappears(self):
        for harness in (Harness.CODEX, Harness.OPENCODE):
            with self.subTest(harness=harness):
                _, parent, first, runtime, herdr = self.fixture(harness)
                runtime.can_attach_now = lambda *_: True
                self.assertTrue(runtime.open_and_attach(parent, first, f"first-{harness.value}"))
                owned = load_existing_binding(self.root, f"first-{harness.value}")["pane_id"]
                tab_id = load_existing_binding(self.root, f"first-{harness.value}")["destination"]["tab_id"]
                user = {"pane_id": f"user-{harness.value}", "tab_id": tab_id,
                        "workspace_id": parent.workspace_id, "cwd": str(self.root),
                        "agent_session": None}
                herdr.panes.append(user)
                herdr.panes = [p for p in herdr.panes if p["pane_id"] != owned]
                # Keep the managed tab present after its owned child pane exits.
                self.assertTrue(any(t["tab_id"] == tab_id for t in herdr.tabs))
                ctx = Context(harness, "p", self.root, self.root, self.root,
                              first.context.backend_id, "different-child", "instance")
                child = Session(ctx, "main", "Second", self.root, Lifecycle.RUNNING,
                                True, 2.0, kind="subagent", generation="turn-2")
                self.assertTrue(runtime.open_and_attach(parent, child, f"second-{harness.value}"))
                self.assertEqual(len(herdr.tabs), 1)
                self.assertEqual(herdr.splits, [user["pane_id"]])
                self.assertIn(user, herdr.panes)
                second = load_existing_binding(self.root, f"second-{harness.value}")
                self.assertNotEqual(second["pane_id"], user["pane_id"])

    def test_bindings_are_persisted_before_wrapper_and_distinct_roots_do_not_coalesce(self):
        _, parent, child, runtime, herdr = self.fixture()
        runtime.can_attach_now = lambda *_: True
        original = herdr.send_text
        def assert_saved(pane, text):
            if " bind" in text:
                self.assertTrue(load_existing_binding(self.root, "bind")["pane_id"] == pane)
            original(pane, text)
        herdr.send_text = assert_saved
        self.assertTrue(runtime.open_and_attach(parent, child, "bind"))
        _, parent2, child2, runtime2, _herdr2 = self.fixture(root_id="other-main")
        runtime2.herdr = herdr
        runtime2.can_attach_now = lambda *_: True
        self.assertTrue(runtime2.open_and_attach(parent2, child2, "other-bind"))
        self.assertNotEqual(load_existing_binding(self.root, "bind")["destination"]["tab_id"],
                            load_existing_binding(self.root, "other-bind")["destination"]["tab_id"])

    def test_missing_metadata_and_unknown_create_never_fallback_or_retry_create(self):
        _, parent, child, runtime, herdr = self.fixture()
        runtime.provider.main_metadata = lambda _parent: (None, None)
        self.assertFalse(runtime.open_and_attach(parent, child, "missing"))
        self.assertEqual(herdr.creates, [])
        _, parent, child, runtime, herdr = self.fixture(root_id="unknown")
        runtime.can_attach_now = lambda *_: True
        attempts = []
        def uncertain(*_args, **_kwargs):
            attempts.append(1)
            raise TimeoutError("create acknowledgement lost")
        herdr.create_subagent_tab = uncertain
        with self.assertRaises(TimeoutError): runtime.open_and_attach(parent, child, "unknown")
        # The unresolved create intent blocks a second create.
        with self.assertRaises(ValueError): runtime.open_and_attach(parent, child, "unknown-2")
        self.assertEqual(len(attempts), 1)

    def test_confirmed_manual_tab_removal_suppresses_old_child_binding(self):
        _, parent, child, runtime, herdr = self.fixture()
        runtime.can_attach_now = lambda *_: True
        self.assertTrue(runtime.open_and_attach(parent, child, "removed-binding"))
        herdr.tabs.clear(); herdr.panes.clear()
        manager = runtime._tabs(parent)
        with manager.operations() as token:
            self.assertEqual(manager.reconcile(token, herdr), "removed")
        self.assertEqual(runtime.owned_pane_state(parent, child, "removed-binding"), "closed")
        newer_context = Context(child.context.harness, child.context.profile, child.context.config_root,
                                child.context.data_root, child.context.state_root, child.context.backend_id,
                                "child-new", child.context.backend_instance)
        newer = Session(newer_context, "main", "New child", self.root, Lifecycle.RUNNING,
                        True, 2.0, kind="subagent", generation="turn-2")
        self.assertTrue(runtime.open_and_attach(parent, newer, "new-generation"))
        self.assertEqual(len(herdr.creates), 2)

    def test_preflight_failure_removes_only_proven_unused_initial_shell(self):
        _, parent, child, runtime, herdr = self.fixture()
        alive = {"value": True}
        create = herdr.create_subagent_tab
        def create_then_exit(*args, **kwargs):
            result = create(*args, **kwargs)
            alive["value"] = False
            return result
        herdr.create_subagent_tab = create_then_exit
        runtime.can_attach_now = lambda *_: alive["value"]
        self.assertFalse(runtime.open_and_attach(parent, child, "lost-child"))
        self.assertEqual(herdr.sent, [])
        self.assertEqual(herdr.panes, [])
        self.assertEqual(herdr.tabs, [])
        alive["value"] = True
        herdr.create_subagent_tab = create
        self.assertTrue(runtime.open_and_attach(parent, child, "next-child"))
        self.assertEqual(len(herdr.creates), 2)
        self.assertEqual(len(herdr.panes), 1)

    def test_preflight_failure_retains_shell_when_pid_changes_after_capture(self):
        _, parent, child, runtime, herdr = self.fixture()
        alive = {"value": True}
        create = herdr.create_subagent_tab
        def create_then_exit(*args, **kwargs):
            result = create(*args, **kwargs)
            alive["value"] = False
            return result
        herdr.create_subagent_tab = create_then_exit
        runtime.can_attach_now = lambda *_: alive["value"]
        process_info = herdr.process_info
        calls = {"count": 0}
        def changed_pid(pane):
            calls["count"] += 1
            info = process_info(pane)
            if calls["count"] > 1:
                info = dict(info, shell_pid=99,
                            foreground_processes=[dict(info["foreground_processes"][0], pid=99)])
            return info
        herdr.process_info = changed_pid
        self.assertFalse(runtime.open_and_attach(parent, child, "pid-changed"))
        self.assertEqual(len(herdr.tabs), 1)
        self.assertEqual(len(herdr.panes), 1)
        self.assertEqual(herdr.sent, [])

    def test_coordinator_routes_nested_and_sibling_sessions_into_one_root_tab(self):
        _, parent, first, runtime, herdr = self.fixture()
        runtime.can_attach_now = lambda *_: True
        coordinator = Coordinator(runtime.store, runtime)
        runtime.store.establish_baseline(set())
        first_outcome = coordinator.handle(parent, first)
        self.assertEqual(first_outcome.decision.value, "attached", first_outcome.reason)
        sibling_ctx = Context(first.context.harness, first.context.profile, first.context.config_root,
                              first.context.data_root, first.context.state_root, first.context.backend_id,
                              "sibling", first.context.backend_instance)
        sibling = Session(sibling_ctx, "main", "Sibling", self.root, Lifecycle.RUNNING,
                          True, 2.0, kind="subagent", generation="turn-1")
        self.assertEqual(coordinator.handle(parent, sibling).decision.value, "attached")
        nested_ctx = Context(first.context.harness, first.context.profile, first.context.config_root,
                             first.context.data_root, first.context.state_root, first.context.backend_id,
                             "grandchild", first.context.backend_instance)
        nested = Session(nested_ctx, "child", "Grandchild", self.root, Lifecycle.RUNNING,
                         True, 3.0, kind="subagent", generation="turn-1", ancestry=("main", "child"))
        self.assertEqual(coordinator.handle(parent, nested).decision.value, "attached")
        splits_before_duplicate = len(herdr.splits)
        self.assertEqual(coordinator.handle(parent, nested).decision.value, "attached")
        self.assertEqual(len(herdr.splits), splits_before_duplicate)
        self.assertEqual(len(herdr.tabs), 1)
        self.assertEqual(len(herdr.splits), 2)


if __name__ == "__main__": unittest.main()
