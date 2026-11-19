import unittest
import json
import os
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import Mock, patch

from harness_herdr_hooks.cli import (_HerdrLaunchRouter, _native_codex_executable, _process_pin,
                                     _observer_command_matches, _verify_launch_destination, _verified_pane_root)
from harness_herdr_hooks.adapters.codex import CodexRuntimeAdapter
from harness_herdr_hooks.launch import LaunchStore
from harness_herdr_hooks.model import Context, Harness, ParentBinding, parent_to_dict
from harness_herdr_hooks.state import StateStore


class FakeProxy:
    def __init__(self, rows):
        self.rows = rows
        self.calls = []

    def request(self, method, params):
        self.calls.append((method, params))
        if method == "thread/loaded/list":
            return {"data": [row["id"] for row in self.rows], "nextCursor": None}
        if method == "thread/read":
            ident = params["threadId"]
            return {"thread": next(row for row in self.rows if row["id"] == ident)}
        if method == "thread/list":
            return {"data": self.rows, "nextCursor": None}
        raise AssertionError(method)


class FakeProvider:
    def __init__(self, rows):
        self.proxy = FakeProxy(rows)

    def _read_thread(self, ident):
        return self.proxy.request("thread/read", {"threadId": ident})["thread"]


class BootstrapIntegrationTests(unittest.TestCase):
    def test_id_reference_requires_loaded_exact_native_thread(self):
        provider = FakeProvider([{"id": "root", "path": "/runs/root.jsonl"}])
        self.assertEqual(_verified_pane_root(provider, {"kind": "id", "value": "root"}), "root")
        with self.assertRaises(ValueError):
            _verified_pane_root(provider, {"kind": "id", "value": "foreign"})

    def test_path_reference_resolves_through_native_metadata(self):
        provider = FakeProvider([{"id": "root", "path": "/runs/root.jsonl"}])
        with patch("harness_herdr_hooks.adapters.codex.list_threads", return_value=iter(provider.proxy.rows)):
            self.assertEqual(_verified_pane_root(provider, {"kind": "path", "value": "/runs/root.jsonl"}), "root")
            with self.assertRaises(ValueError):
                _verified_pane_root(provider, {"kind": "path", "value": "/runs/foreign.jsonl"})


class NativeHookBootstrapTests(unittest.TestCase):
    """Exercise the real event boundary with only native/Herdr transports mocked."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.env = {"HERDR_ENV": "1", "HERDR_SOCKET_PATH": "/herdr.sock",
                    "HERDR_PANE_ID": "pane-root", "HERDR_TAB_ID": "tab-root",
                    "HERDR_WORKSPACE_ID": "workspace-root", "CODEX_HOME": str(self.root / "codex")}
        (self.root / "codex").mkdir()
        self.rows = [
            {"id": "root-thread", "path": "/runs/root.jsonl"},
            {"id": "child-thread", "path": "/runs/child.jsonl", "parentThreadId": "root-thread",
             "source": {"subAgent": {"thread_spawn": {"parent_thread_id": "root-thread"}}}},
        ]

    def tearDown(self):
        self.tmp.cleanup()

    def _run_parent_event(self, ref):
        from harness_herdr_hooks.cli import _parent_from_event

        class Provider(FakeProvider):
            closed = False
            def close(provider_self):
                provider_self.closed = True
            _verified_chain = staticmethod(CodexRuntimeAdapter._verified_chain)

        provider = Provider(self.rows)
        pane = {"pane_id": "pane-root", "tab_id": "tab-root", "workspace_id": "workspace-root",
                "agent_session": ref, "cwd": str(self.root)}
        client = Mock()
        client.snapshot.return_value = {"panes": [pane]}
        client.server_identity.return_value = "server-root"
        client.process_info.return_value = {"foreground_processes": [{"pid": 71, "name": "codex"}]}
        event = {"hook_event_name": "SubagentStart", "session_id": "child-thread",
                 "agent_id": "child-thread", "agent_type": "explorer", "turn_id": "turn-1",
                 "cwd": str(self.root), "transcript_path": None, "extra_native_field": "ignored"}
        proof = {"socket_target": "/tmp/codex.sock", "socket_identity": [1, 2, 3],
                 "executable": "/usr/bin/codex", "pid": 71, "uid": os.getuid(), "start_ticks": 2}
        with patch.dict(os.environ, self.env, clear=False), \
             patch("harness_herdr_hooks.cli.codex_backend_proof", return_value=proof), \
             patch("harness_herdr_hooks.cli._native_codex_executable", return_value="/usr/bin/codex"), \
             patch("harness_herdr_hooks.cli.CodexRuntimeAdapter", return_value=provider), \
             patch("harness_herdr_hooks.cli._verified_pane_root", side_effect=lambda p, r: _verified_pane_root(p, r)):
            result = _parent_from_event("codex-hook", json.dumps(event).encode(), client)
        return result, client, provider

    def test_default_daemon_child_event_accepts_missing_argv_and_id_or_path_root(self):
        for ref in ({"kind": "id", "value": "root-thread"},
                    {"kind": "path", "value": "/runs/root.jsonl"}):
            with self.subTest(ref=ref):
                (result, client, provider) = self._run_parent_event(ref)
                parent, pid, cwd, created = result
                self.assertEqual(parent.context.session_id, "root-thread")
                self.assertEqual(parent.context.backend_id, "/tmp/codex.sock")
                self.assertEqual(parent.session_path, Path("/runs/root.jsonl") if ref["kind"] == "path" else None)
                self.assertIsNone(pid)
                self.assertEqual(cwd, self.root)
                self.assertEqual(created.identity.session_id, "child-thread")
                self.assertNotEqual(created.identity.session_id, parent.context.session_id)
                self.assertTrue(provider.closed)
                self.assertEqual(client.verify_parent.call_count, 1)

    def test_missing_loaded_root_and_mismatched_child_ancestry_fail_before_parent_verification(self):
        from harness_herdr_hooks.cli import _parent_from_event
        for mutate in ("unloaded", "bad-ancestry"):
            with self.subTest(mutate=mutate):
                rows = [dict(row) for row in self.rows]
                if mutate == "unloaded": rows = [rows[1]]
                else:
                    rows[1] = {**rows[1], "parentThreadId": "other-thread",
                               "source": {"subAgent": {"thread_spawn": {"parent_thread_id": "other-thread"}}}}
                    rows.append({"id": "other-thread", "path": "/runs/other.jsonl"})
                class Provider(FakeProvider):
                    def close(self): pass
                    _verified_chain = staticmethod(CodexRuntimeAdapter._verified_chain)
                provider = Provider(rows)
                pane = {"pane_id": "pane-root", "tab_id": "tab-root", "workspace_id": "workspace-root",
                        "agent_session": {"kind": "id", "value": "root-thread"}, "cwd": str(self.root)}
                client = Mock()
                client.snapshot.return_value = {"panes": [pane]}
                client.process_info.return_value = {"foreground_processes": [{"pid": 71, "name": "codex"}]}
                proof = {"socket_target": "/tmp/codex.sock", "socket_identity": [1, 2, 3],
                         "executable": "/usr/bin/codex", "pid": 71, "uid": os.getuid(), "start_ticks": 2}
                event = {"hook_event_name": "SubagentStart", "session_id": "child-thread", "agent_id": "child-thread",
                         "agent_type": "explorer", "turn_id": "turn-1", "cwd": str(self.root), "transcript_path": None}
                with patch.dict(os.environ, self.env, clear=False), \
                     patch("harness_herdr_hooks.cli.codex_backend_proof", return_value=proof), \
                     patch("harness_herdr_hooks.cli._native_codex_executable", return_value="/usr/bin/codex"), \
                     patch("harness_herdr_hooks.cli.CodexRuntimeAdapter", return_value=provider):
                    with self.assertRaises(ValueError):
                        _parent_from_event("codex-hook", json.dumps(event).encode(), client)
                client.verify_parent.assert_not_called()


class ObserverBootstrapTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.context = Context(Harness.CODEX, "/profile", Path("/profile"), Path("/profile"),
                               Path("/profile"), "/socket", "root", "backend")
        self.parent = ParentBinding(self.context, "server", "ws", "tab", "pane")
        self.client = Mock(socket_path=Path("/herdr.sock"))
        self.cwd = self.root

    def tearDown(self):
        self.tmp.cleanup()

    def test_child_creation_and_generation_are_durable_before_observer_spawn(self):
        from harness_herdr_hooks.adapters.codex import parse_hook
        from harness_herdr_hooks.cli import _start_observer
        child = parse_hook({"hook_event_name": "SubagentStart", "session_id": "child", "agent_id": "child",
                            "agent_type": "explorer", "turn_id": "turn-7", "cwd": str(self.root),
                            "transcript_path": None}, profile="/profile", config_root=Path("/profile"),
                           data_root=Path("/profile"), state_root=Path("/profile"),
                           verified_backend_id="/socket", verified_backend_instance="backend")
        key = Context(Harness.CODEX, "/profile", Path("/profile"), Path("/profile"),
                      Path("/profile"), "/socket", "child", "backend").key()
        def spawn(argv, **kwargs):
            store = StateStore(self.root, self.context.key()[:32])
            record = store.generation(key)
            self.assertIsNotNone(record)
            self.assertEqual(record["generation"], "turn-7")
            self.assertEqual(record["turn_id"], "turn-7")
            self.assertEqual(record["kind"], "subagent")
            self.assertEqual(record["parent_id"], "root")
            self.assertIn("observe", argv)
            self.assertNotIn("turn", argv)
            return Mock()
        with patch("harness_herdr_hooks.cli._state_root", return_value=self.root), \
             patch("harness_herdr_hooks.cli._provider", return_value=Mock(proxy=Mock(), close=Mock())), \
             patch("harness_herdr_hooks.adapters.codex.list_turn_metadata", return_value=(Mock(turn_id="turn-7"),)), \
             patch("harness_herdr_hooks.cli.subprocess.Popen", side_effect=spawn):
            _start_observer(self.parent, None, self.client, self.cwd, child)

    def test_matching_stop_hint_is_persisted_without_attachment_or_session_launch(self):
        from harness_herdr_hooks.adapters.codex import parse_hook
        from harness_herdr_hooks.cli import _start_observer
        key = Context(Harness.CODEX, "/profile", Path("/profile"), Path("/profile"),
                      Path("/profile"), "/socket", "child", "backend").key()
        store = StateStore(self.root, self.context.key()[:32])
        store.note_creation(key)
        store.begin_generation(key, "turn-7", turn_id="turn-7", parent_id="root")
        child = parse_hook({"hook_event_name": "SubagentStop", "session_id": "child", "agent_id": "child",
                            "agent_type": "explorer", "turn_id": "turn-7", "cwd": str(self.root),
                            "transcript_path": None, "stop_hook_active": True}, profile="/profile",
                           config_root=Path("/profile"), data_root=Path("/profile"), state_root=Path("/profile"),
                           verified_backend_id="/socket", verified_backend_instance="backend")
        calls = []
        with patch("harness_herdr_hooks.cli._state_root", return_value=self.root), \
             patch("harness_herdr_hooks.cli.subprocess.Popen", side_effect=lambda argv, **kwargs: calls.append(argv)):
            _start_observer(self.parent, None, self.client, self.cwd, child)
        record = store.generation(key)
        self.assertEqual(record["stop_hints"], [{"generation": "turn-7", "turn_id": "turn-7", "stop_hook_active": True}])
        self.assertFalse(record.get("status") == "finished")
        self.assertEqual(len(calls), 1)
        self.assertIn("observe", calls[0])
        self.assertNotIn("attach", calls[0])
        self.assertNotIn("codex", calls[0])

    def test_opencode_creation_context_keeps_legacy_pending_creation_semantics(self):
        from harness_herdr_hooks.cli import _start_observer
        child_context = Context(Harness.OPENCODE, "/oc", Path("/oc"), Path("/oc-data"),
                                Path("/oc-state"), "http://127.0.0.1:1", "session", "pid:3")
        store = StateStore(self.root, self.context.key()[:32])
        with patch("harness_herdr_hooks.cli._state_root", return_value=self.root), \
             patch("harness_herdr_hooks.cli.subprocess.Popen") as popen:
            _start_observer(self.parent, 3, self.client, self.cwd, child_context)
        self.assertIn(child_context.key(), (store.root / "state.json").read_text())
        popen.assert_called_once()

    def test_delayed_start_hook_cannot_rewind_attached_later_generation(self):
        from harness_herdr_hooks.adapters.codex import parse_hook
        from harness_herdr_hooks.cli import _start_observer
        key = Context(Harness.CODEX, "/profile", Path("/profile"), Path("/profile"),
                      Path("/profile"), "/socket", "child", "backend").key()
        store = StateStore(self.root, self.context.key()[:32])
        store.note_creation(key)
        store.begin_generation(key, "turn-2", turn_id="turn-2", parent_id="root")
        with store.locked() as data:
            data["records"][key].update(binding_id="attached-binding", ownership="owned")
        before = store.generation(key)
        child = parse_hook({"hook_event_name": "SubagentStart", "session_id": "child", "agent_id": "child",
                            "agent_type": "explorer", "turn_id": "turn-1", "cwd": str(self.root),
                            "transcript_path": None}, profile="/profile", config_root=Path("/profile"),
                           data_root=Path("/profile"), state_root=Path("/profile"),
                           verified_backend_id="/socket", verified_backend_instance="backend")
        provider = Mock(proxy=Mock(), close=Mock())
        with patch("harness_herdr_hooks.cli._state_root", return_value=self.root), \
             patch("harness_herdr_hooks.cli._provider", return_value=provider), \
             patch("harness_herdr_hooks.adapters.codex.list_turn_metadata", return_value=(Mock(turn_id="turn-2"),)), \
             patch("harness_herdr_hooks.cli.subprocess.Popen"):
            _start_observer(self.parent, None, self.client, self.cwd, child)
        after = store.generation(key)
        self.assertEqual(after["generation"], "turn-2")
        self.assertEqual(after["binding_id"], "attached-binding")
        self.assertEqual(after["ownership"], "owned")
        self.assertEqual(after["prior_generations"], before["prior_generations"])
        provider.close.assert_called_once()


class LaunchRouterProofTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.cwd = self.root
        self.context = Context(Harness.CODEX, "/profile", Path("/profile"), Path("/profile"),
                              Path("/profile"), "/socket", "thread", "backend")
        self.parent = ParentBinding(self.context, "server", "ws", "tab", "source")
        self.markers = {"HERDR_ENV": "1", "HERDR_SOCKET_PATH": "/socket",
                        "HERDR_PANE_ID": "source", "HERDR_TAB_ID": "tab",
                        "HERDR_WORKSPACE_ID": "ws"}

    def tearDown(self):
        self.tmp.cleanup()

    def test_routing_intent_prevents_duplicate_split(self):
        root = self.root / "harness-herdr-hooks" / "launches"
        store = LaunchStore(root)
        store._prepare()
        store._atomic(root / "records" / "request.route.json",
                      {"schema": 1, "request_id": "request", "status": "split-intent"})
        client = Mock()
        router = _HerdrLaunchRouter({"config_root": "/profile"})
        router.parent, router.client = self.parent, client
        with patch("harness_herdr_hooks.cli._state_root", return_value=self.root), \
             patch.dict(os.environ, self.markers, clear=False):
            self.assertFalse(router.split_and_launch("request", Path("/payload"), self.cwd))
        client.split.assert_not_called()

    def test_markers_must_match_parent_before_split(self):
        client = Mock()
        router = _HerdrLaunchRouter({"config_root": "/profile"})
        router.parent, router.client = self.parent, client
        with patch("harness_herdr_hooks.cli._state_root", return_value=self.root), \
             patch.dict(os.environ, {**self.markers, "HERDR_PANE_ID": "other"}, clear=False):
            self.assertFalse(router.split_and_launch("request", Path("/payload"), self.cwd))
        client.split.assert_not_called()

    def test_successful_route_revalidates_both_shells_before_send(self):
        source = {"shell_pid": 11}
        destination = {"shell_pid": 22,
                       "foreground_processes": [{"pid": 22, "name": "bash", "cwd": str(self.cwd)}]}
        client = Mock()
        client.socket_path = Path("/socket")
        client.verify_parent.return_value = True
        client.process_info.side_effect = [source, destination, destination, source]
        client.split.return_value = "dest"
        with patch("harness_herdr_hooks.cli._state_root", return_value=self.root), \
             patch("harness_herdr_hooks.cli._process_pin", side_effect=lambda pid, expected=None: expected or {"start_ticks": pid, "exe": "/bin/bash", "uid": os.getuid()}), \
             patch.dict(os.environ, self.markers, clear=False):
            router = _HerdrLaunchRouter({"config_root": "/profile"})
            router.parent, router.client = self.parent, client
            self.assertTrue(router.split_and_launch("request", Path("/payload"), self.cwd))
        self.assertEqual(client.send_text.call_count, 1)
        self.assertEqual(client.send_keys.call_count, 1)
        self.assertGreaterEqual(client.verify_parent.call_count, 2)

    def test_launch_run_rejects_bad_id_before_resolving_state(self):
        from harness_herdr_hooks.cli import main
        with patch("harness_herdr_hooks.cli._state_root", side_effect=AssertionError("state touched")):
            self.assertEqual(main(["launch-run", "../bad"]), 2)

    def test_destination_requires_self_foreground_python_module_and_exact_markers(self):
        launch_root = self.root / "harness-herdr-hooks" / "launches"
        store = LaunchStore(launch_root)
        store._prepare()
        binding = {"request_id": "req", "cwd": str(self.cwd), "profile": "/profile",
                   "server_socket": "/socket", "server_identity": "server", "parent": parent_to_dict(self.parent),
                   "pane_id": "dest", "workspace_id": "ws", "tab_id": "tab",
                   "shell_pid": 7, "shell_pin": {"start_ticks": 3, "exe": "/bin/bash", "uid": os.getuid()}}
        destination_markers={**self.markers,"HERDR_PANE_ID":"dest"}
        store._atomic(launch_root / "records" / "req.destination.json", binding)
        client = Mock()
        client.snapshot.return_value = {"panes": [{"pane_id": "dest", "workspace_id": "ws",
                                  "tab_id": "tab", "cwd": str(self.cwd)}]}
        client.server_identity.return_value = "server"
        client.verify_parent.return_value = True
        client.process_info.return_value = {"shell_pid": 7,
            "foreground_processes": [{"pid": os.getpid(), "name": "python3", "cwd": str(self.cwd)}]}
        with patch("harness_herdr_hooks.cli._state_root", return_value=self.root), \
             patch("harness_herdr_hooks.cli.HerdrClient", return_value=client), \
             patch("harness_herdr_hooks.cli._process_pin", side_effect=lambda pid, expected=None: expected or
                   ({"start_ticks": 1, "exe": str(Path(sys.executable).resolve()), "uid": os.getuid()}
                    if pid == os.getpid() else binding["shell_pin"])), \
             patch("harness_herdr_hooks.cli._proc_argv", return_value=[sys.executable, "-m", "harness_herdr_hooks", "launch-run", "req"]), \
             patch.dict(os.environ, destination_markers, clear=False):
            self.assertIsNotNone(_verify_launch_destination("req", self.cwd, "/profile"))
            with patch("harness_herdr_hooks.cli._process_pin", return_value=None):
                self.assertIsNone(_verify_launch_destination("req", self.cwd, "/profile"))
            client.process_info.return_value["foreground_processes"][0]["pid"] = os.getpid() + 100
            self.assertIsNone(_verify_launch_destination("req", self.cwd, "/profile"))
            client.process_info.return_value["foreground_processes"][0]["pid"] = os.getpid()
            with patch("harness_herdr_hooks.cli._proc_argv", return_value=["/tmp/harness-herdr-hooks", "launch-run", "req"]):
                self.assertIsNone(_verify_launch_destination("req", self.cwd, "/profile"))
            py313 = self.root / "python3.13"
            py313.write_text("python test executable")
            with patch("harness_herdr_hooks.cli._proc_argv", return_value=[str(py313), "-m", "harness_herdr_hooks", "launch-run", "req"]):
                with patch("harness_herdr_hooks.cli._process_pin", side_effect=lambda pid, expected=None: expected or
                           ({"start_ticks": 1, "exe": str(py313.resolve()), "uid": os.getuid()}
                            if pid == os.getpid() else binding["shell_pin"])):
                    self.assertIsNotNone(_verify_launch_destination("req", self.cwd, "/profile"))
            with patch.dict(os.environ, {**destination_markers, "HERDR_TAB_ID": "wrong"}, clear=False):
                self.assertIsNone(_verify_launch_destination("req", self.cwd, "/profile"))

    def test_native_executable_requires_matching_private_profile_manifest(self):
        from harness_herdr_hooks.install import _manifest
        config = self.root / "profile"
        adapter = config / "harness-herdr-hooks" / "codex-adapter"
        adapter.mkdir(parents=True)
        native = self.root / "native-codex"
        native.write_text("#!/bin/sh\nexit 0\n")
        native.chmod(0o700)
        shim = adapter / "codex"
        shim.write_text("managed shim\n")
        metadata = adapter / "adapter.json"
        meta = {"schema": 1, "config_root": str(config), "source_root": str(self.root),
                "native_executable": str(native)}
        metadata.write_text(json.dumps(meta, sort_keys=True, separators=(",", ":")))
        metadata.chmod(0o600)
        manifest = {"schema": 1, "entries": {"codex": {"adapter_dir": str(adapter),
            "source_root": str(self.root), "metadata_sha256": __import__("hashlib").sha256(metadata.read_bytes()).hexdigest(),
            "adapter_sha256": __import__("hashlib").sha256(shim.read_bytes()).hexdigest()}}}
        _manifest(config).write_text(json.dumps(manifest))
        _manifest(config).chmod(0o600)
        self.assertEqual(_native_codex_executable(config), native.resolve())
        manifest["entries"]["codex"]["source_root"] = str(self.root / "other")
        _manifest(config).write_text(json.dumps(manifest))
        _manifest(config).chmod(0o600)
        with self.assertRaises(ValueError):
            _native_codex_executable(config)

    def test_process_pin_rejects_changed_start_executable_or_foreign_uid(self):
        proc = self.root / "proc" / "42"
        proc.mkdir(parents=True)
        # Fields after ')' begin with state (field 3); starttime is field 22.
        fields = ["S"] + ["0"] * 18 + ["123"] + ["0"] * 5
        (proc / "stat").write_text("42 (fake process) " + " ".join(fields))
        (proc / "status").write_text(f"Uid:\t{os.getuid()}\t{os.getuid()}\t{os.getuid()}\t{os.getuid()}\n")
        (proc / "exe").symlink_to("/bin/sh")
        pin = _process_pin(42, proc_root=self.root / "proc")
        self.assertEqual(pin, {"start_ticks": 123, "exe": str(Path("/bin/sh").resolve()), "uid": os.getuid()})
        self.assertIsNone(_process_pin(42, expected={**pin, "start_ticks": 124}, proc_root=self.root / "proc"))
        (proc / "status").write_text("Uid:\t99999\t99999\t99999\t99999\n")
        self.assertIsNone(_process_pin(42, proc_root=self.root / "proc"))

    def test_observer_command_binds_private_source_and_exact_binding(self):
        proc = self.root / "proc" / "42"
        proc.mkdir(parents=True)
        fields=["S"]+["0"]*18+["123"]+["0"]*5
        (proc/"stat").write_text("42 (observer) "+" ".join(fields))
        (proc/"status").write_text(f"Uid:\t{os.getuid()}\t{os.getuid()}\t{os.getuid()}\t{os.getuid()}\n")
        (proc/"exe").symlink_to(sys.executable)
        (proc/"cmdline").write_bytes((sys.executable+"\0-m\0harness_herdr_hooks\0observe\0owned-binding\0").encode())
        (proc/"environ").write_bytes(b"PYTHONPATH=/owned/src\0")
        pin=_process_pin(42,proc_root=self.root/"proc")
        observer={"source_root":"/owned/src","binding_id":"owned-binding","pin":pin}
        self.assertTrue(_observer_command_matches(42,observer,proc_root=self.root/"proc"))
        observer["binding_id"]="foreign-binding"
        self.assertFalse(_observer_command_matches(42,observer,proc_root=self.root/"proc"))
        fields[19]="124"
        (proc/"stat").write_text("42 (observer) "+" ".join(fields))
        self.assertFalse(_observer_command_matches(42,observer,proc_root=self.root/"proc"))

    def test_acknowledgement_poll_observes_claimed_then_acknowledged(self):
        root = self.root / "harness-herdr-hooks" / "launches"
        store = LaunchStore(root)
        store._prepare()
        record = root / "records" / "req.json"
        store._atomic(record, {"status": "claimed"})
        router = _HerdrLaunchRouter({})
        def update():
            time.sleep(.04)
            store._atomic(record, {"status": "acknowledged"})
        import threading
        thread = threading.Thread(target=update)
        thread.start()
        with patch("harness_herdr_hooks.cli._state_root", return_value=self.root):
            self.assertTrue(router.wait_for_ack("req", .5))
        thread.join()


if __name__ == "__main__":
    unittest.main()
