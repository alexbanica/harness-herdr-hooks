import contextlib
import io
import tempfile
import unittest
from types import SimpleNamespace
import json
import os
from pathlib import Path
from unittest.mock import Mock, patch

from harness_herdr_hooks import cli
from harness_herdr_hooks.model import Context, Harness, ParentBinding, Session, Lifecycle, parent_to_dict, session_to_dict
from harness_herdr_hooks.state import save_binding
from harness_herdr_hooks.adapters.codex import AppServerProxy, CodexRuntimeAdapter


class DisplayHookNormalizationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.context = Context(Harness.CODEX, "profile", root, root, root, "backend", "child", "incarnation")
        self.parent = ParentBinding(self.context, "server", "workspace", "managed-tab", "child-pane",
                                    backend_proof={"executable": "/bin/codex"})

    def tearDown(self):
        self.tmp.cleanup()

    def test_verified_pane_root_is_the_current_child_pane_thread(self):
        class Provider:
            proxy = object()
            def _read_thread(self, ident):
                return {"id": ident, "path": f"/sessions/{ident}.json"}
        provider = Provider()
        with patch("harness_herdr_hooks.adapters.codex.list_loaded_threads", return_value=["main", "child"]):
            self.assertEqual(cli._verified_pane_root(provider, {"kind": "id", "value": "child"}), "child")

    def test_standalone_session_start_ignores_stale_partial_markers_and_uses_authenticated_destination(self):
        root=Path(self.tmp.name)
        socket=root/"app.sock"
        class Pin:
            alias=root/"app-server-control"/"app-server-control.sock"
            target=socket
            instance="1:2:3"
            socket_identity=(1,2,3,0,1)
            alias_identity=(1,4,5,0,2)
            directory_identity=(1,6,7,0,4)
        class Client:
            socket_path=root/"herdr.sock"
            def session_destination(self,session_id,*,session_path,harness):
                self.args=(session_id,session_path,harness)
                return {"server_id":"server","workspace_id":"workspace","tab_id":"tab",
                        "anchor_pane_id":"pane"}
            def server_identity(self):return "server"
        class Provider:
            proxy=object()
            def __init__(self,context,**_):self.context=context
            def _read_thread(self,ident):return {"id":ident,"path":str(root/"session.json"),"cwd":str(root)}
            def close(self):pass
        payload={"hook_event_name":"SessionStart","session_id":"exact-thread","cwd":str(root),
                 "transcript_path":str(root/"session.json")}
        client=Client()
        with patch.dict(os.environ,{"CODEX_HOME":str(root),"HERDR_SOCKET_PATH":str(root/"herdr.sock"),
                "HERDR_PANE_ID":"stale-pane","HERDR_TAB_ID":"stale-tab"},clear=True), \
             patch.object(cli,"_state_root",return_value=root/"state"), \
             patch("harness_herdr_hooks.codex_backend.select_endpoint",return_value=Pin()), \
             patch.object(cli,"_native_codex_executable",return_value=Path("/bin/codex")), \
             patch("harness_herdr_hooks.cli.CodexRuntimeAdapter",Provider), \
             patch("harness_herdr_hooks.adapters.codex.list_loaded_threads",return_value=["exact-thread"]):
            parent,pid,cwd,created=cli._parent_from_event("codex-hook",json.dumps(payload).encode(),client)
        self.assertEqual(parent.context.session_id,"exact-thread")
        self.assertEqual(parent.context.backend_id,str(socket))
        self.assertEqual((parent.workspace_id,parent.tab_id,parent.pane_id),("workspace","tab","pane"))
        self.assertIsNone(pid)
        self.assertEqual(cwd,root)
        self.assertIsNone(created)
        self.assertEqual(client.args[0],"exact-thread")

    def test_display_marker_suppresses_observer_bootstrap(self):
        root = Path(self.tmp.name)
        raw = {"hook_event_name": "SessionStart", "session_id": "exact-thread", "cwd": str(root), "transcript_path": None}
        pin = SimpleNamespace(target=root/"socket", instance="1:2:3")
        with patch.dict(os.environ, {"CODEX_HOME": str(root), "HARNESS_HERDR_DISPLAY": "1"}, clear=True), \
             patch("harness_herdr_hooks.codex_backend.select_endpoint", return_value=pin), \
             patch.object(cli, "CodexRuntimeAdapter") as provider:
            self.assertEqual(cli._standalone_session_parent(raw, object()), (None, None, None, None))
        provider.assert_not_called()

    def test_durable_display_claim_suppresses_markerless_reentry(self):
        root = Path(self.tmp.name)
        target = root / "codex.sock"
        child_context = Context(Harness.CODEX, str(root), root, root, root, str(target), "child", "1:2:3")
        child = Session(child_context, "parent", None, root, Lifecycle.RUNNING, True, 0)
        socket = root / "herdr.sock"
        save_binding(root, "display-" + child_context.key(), {
            "parent": parent_to_dict(self.parent), "child": session_to_dict(child),
            "pane_id": "child-pane", "backend_pid": None, "shell_pid": None,
            "server_socket": str(socket), "entrypoint": "/unused/entry",
            "kind": "standalone", "ownership": "created"})
        client = Mock(spec=["socket_path", "snapshot", "server_identity"])
        client.socket_path = socket
        client.server_identity.return_value = "server"
        client.snapshot.return_value = {"panes": [
            {"pane_id": "child-pane", "workspace_id": "workspace", "tab_id": "managed-tab"}]}
        raw = {"hook_event_name": "SessionStart", "session_id": "child",
               "cwd": str(root), "transcript_path": None}
        with patch.dict(os.environ, {"CODEX_HOME": str(root), "HARNESS_HERDR_STATE_ROOT": str(root)}, clear=True), \
             patch("harness_herdr_hooks.codex_backend.select_endpoint",
                   return_value=SimpleNamespace(target=target, instance="1:2:3")), \
             patch.object(cli, "CodexRuntimeAdapter") as provider:
            self.assertEqual(cli._standalone_session_parent(raw, client), (None, None, None, None))
        provider.assert_not_called()

    def test_legacy_cli_callbacks_are_inert_before_input_or_state_access(self):
        root = Path(self.tmp.name)
        child = Session(self.context, "parent", None, root, Lifecycle.RUNNING, True, 0)
        save_binding(root, "old-binding", {
            "parent": parent_to_dict(self.parent), "child": session_to_dict(child),
            "pane_id": "child-pane", "backend_pid": 20, "shell_pid": 21,
            "server_socket": "/unused", "entrypoint": "/unused/entry",
            "ownership": "created", "kind": "subagent"})
        original = root / "harness-herdr-hooks" / "bindings" / "old-binding.json"
        before = original.read_bytes()
        for command in (["observe", "old-binding"], ["attach", "old-binding"],
                        ["opencode-event"], ["codex-hook"]):
            with self.subTest(command=command), patch.dict(os.environ, {"HERDR_ENV": "1", "HERDR_SOCKET_PATH": "/unused", "HARNESS_HERDR_STATE_ROOT": str(root)}, clear=True), \
                 patch.object(cli, "_observe", side_effect=AssertionError("legacy observe reached")), \
                 patch.object(cli, "_herdr_client", side_effect=AssertionError("legacy event reached")):
                payload = ({"hook_event_name":"SubagentStart","session_id":"child",
                            "agent_id":"child","agent_type":"worker","turn_id":"turn"}
                           if command == ["codex-hook"] else {})
                stream = type("Input", (), {"buffer": io.BytesIO(json.dumps(payload).encode())})()
                with patch("sys.stdin", stream):
                    self.assertEqual(cli.main(command), 0)
        self.assertEqual(original.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
