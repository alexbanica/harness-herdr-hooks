import contextlib
import io
import tempfile
import unittest
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

    def test_independent_display_is_its_own_verified_root(self):
        class Provider:
            def main_metadata(self, parent): return parent.context, "independent"
            def close(self): pass
        client = type("Client", (), {"verify_parent": lambda self, *_: True})()
        with patch.object(cli, "_provider", return_value=Provider()):
            parent, cwd = cli._normalize_display_parent(self.parent, client, {"cwd": self.tmp.name}, None)
        self.assertEqual(parent, self.parent)
        self.assertEqual(cwd, Path(self.tmp.name))

    def test_nested_display_without_owned_root_binding_fails_closed(self):
        root_context = Context(Harness.CODEX, "profile", Path(self.tmp.name), Path(self.tmp.name),
                               Path(self.tmp.name), "backend", "main", "incarnation")
        class Provider:
            def main_metadata(self, parent): return root_context, "root"
            def close(self): pass
        with patch.object(cli, "_provider", return_value=Provider()), \
             patch.object(cli, "_state_root", return_value=Path(self.tmp.name)):
            with self.assertRaisesRegex(ValueError, "missing or ambiguous owned main binding"):
                cli._normalize_display_parent(self.parent, object(), {"cwd": self.tmp.name}, None)

    def test_display_marker_without_current_pane_identity_fails_closed(self):
        root_context = Context(Harness.CODEX, "profile", Path(self.tmp.name), Path(self.tmp.name),
                               Path(self.tmp.name), "backend", "main", "incarnation")
        class Provider:
            def main_metadata(self, parent): return root_context, "root"
            def close(self): pass
        class Client:
            def verify_parent(self, *_): return True
        pane = {"cwd": self.tmp.name, "pane_id": "foreign", "tab_id": "managed-tab",
                "workspace_id": "workspace"}
        with patch.object(cli, "_provider", return_value=Provider()), \
             patch.object(cli, "_state_root", return_value=Path(self.tmp.name)):
            with self.assertRaisesRegex(ValueError, "missing or ambiguous owned main binding"):
                cli._normalize_display_parent(self.parent, Client(), pane, None)

    def test_display_binding_scan_overflow_fails_closed(self):
        root_context = Context(Harness.CODEX, "profile", Path(self.tmp.name), Path(self.tmp.name),
                               Path(self.tmp.name), "backend", "main", "incarnation")
        class Provider:
            def main_metadata(self, parent): return root_context, "root"
            def close(self): pass
        with patch.object(cli, "_provider", return_value=Provider()), \
             patch.object(cli, "_state_root", return_value=Path(self.tmp.name)), \
             patch("pathlib.Path.glob", return_value=iter(Path(str(i)) for i in range(513))):
            with self.assertRaisesRegex(ValueError, "scan overflow"):
                cli._normalize_display_parent(self.parent, object(), {"cwd": self.tmp.name}, None)

    def test_nested_codex_and_opencode_use_owned_same_tab_binding(self):
        for harness in (Harness.CODEX, Harness.OPENCODE):
            with self.subTest(harness=harness):
                root = Path(self.tmp.name) / harness.value
                root.mkdir()
                incarnation = "pid:55" if harness == Harness.OPENCODE else "incarnation"
                main_context = Context(harness, "profile", root, root, root, "backend", "main", incarnation)
                child_context = Context(harness, "profile", root, root, root, "backend", "child", incarnation)
                main = ParentBinding(main_context, "server", "workspace", "managed-tab", "main-pane",
                                     backend_proof={"executable": "/bin/main"})
                child_parent = ParentBinding(child_context, "server", "workspace", "managed-tab", "child-pane",
                                             backend_proof={"executable": "/bin/attached"})
                child = Session(child_context, "main", "child", root, Lifecycle.UNKNOWN, True, 1.0)
                save_binding(root, "owned", {"parent": parent_to_dict(main), "child": session_to_dict(child),
                    "pane_id": "child-pane", "backend_pid": 55 if harness == Harness.OPENCODE else None,
                    "server_socket": "/tmp/herdr.sock", "entrypoint": "/bin/entry", "shell_pid": None,
                    "ownership": "reused"})
                pane = {"pane_id": "child-pane", "tab_id": "managed-tab", "workspace_id": "workspace",
                        "agent_session": {"kind": "id", "value": "child",
                                          "agent": harness.value, "source": "native-plugin"}, "cwd": self.tmp.name}
                test_cwd = self.tmp.name
                class Client:
                    def verify_parent(self, candidate, backend_pid=None):
                        return candidate == main and (harness != Harness.OPENCODE or backend_pid == 55)
                    def snapshot(self):
                        current=dict(pane,revision=32,scroll=900,focus=True)
                        return {"panes": [current, {"pane_id": "main-pane", "cwd": test_cwd}]}
                    def process_info(self, _pane): return {"foreground_processes": [{"pid": 55 if _pane=="main-pane" else 77, "name": "opencode",
                        "argv": ["opencode","attach","http://127.0.0.1:4096","--session","child","--mini"]}]}
                metadata_inputs=[]
                class Provider:
                    def main_metadata(self, _parent):
                        metadata_inputs.append(_parent.context.session_id)
                        return main_context, "root"
                    def attach_argv(self, _child): return ["opencode","attach","http://127.0.0.1:4096","--session","child","--mini"]
                    def close(self): pass
                matcher=__import__("unittest.mock",fromlist=["Mock"]).Mock(return_value=True)
                with patch.object(cli, "_provider", return_value=Provider()), \
                     patch.object(cli, "_state_root", return_value=root), \
                     patch("harness_herdr_hooks.herdr.process_matches_attachment", matcher):
                    normalized, cwd = cli._normalize_display_parent(child_parent, Client(), pane,
                                                                    55 if harness == Harness.OPENCODE else None)
                self.assertEqual(normalized, main)
                if harness == Harness.OPENCODE:
                    self.assertIn("child", metadata_inputs)
                self.assertEqual(cwd, Path(self.tmp.name))
                matcher.assert_called_once_with(__import__("unittest.mock",fromlist=["ANY"]).ANY,
                                                ["opencode","attach","http://127.0.0.1:4096","--session","child","--mini"], child.context)

    def test_opencode_event_uses_owned_original_server_for_attached_client_pid(self):
        root=Path(self.tmp.name)/"opencode-event"; root.mkdir()
        main_context=Context(Harness.OPENCODE,str(root),root,root,root,"http://127.0.0.1:4096","main","pid:55")
        child_context=Context(Harness.OPENCODE,str(root),root,root,root,"http://127.0.0.1:4096","child","pid:55")
        main=ParentBinding(main_context,"server","workspace","managed-tab","main-pane")
        child=Session(child_context,"main","child",root,Lifecycle.UNKNOWN,True,1.0)
        save_binding(root,"owned",{"parent":parent_to_dict(main),"child":session_to_dict(child),
            "pane_id":"child-pane","backend_pid":55,"server_socket":"/tmp/herdr.sock",
            "entrypoint":"/bin/entry","shell_pid":None,"ownership":"created"})
        pane={"pane_id":"child-pane","tab_id":"managed-tab","workspace_id":"workspace",
              "agent_session":{"kind":"id","value":"child","agent":"opencode","source":"plugin"},
              "cwd":self.tmp.name}
        test_cwd=self.tmp.name
        class Client:
            socket_path=Path("/tmp/herdr.sock")
            def snapshot(self): return {"panes":[dict(pane,revision=12),{"pane_id":"main-pane","cwd":test_cwd}]}
            def process_info(self,pane_id):
                pid=55 if pane_id=="main-pane" else 77
                return {"foreground_processes":[{"pid":pid,"name":"opencode",
                    "argv":["opencode","attach","http://127.0.0.1:4096","--session","child","--mini"]}]}
            def verify_parent(self,candidate,backend_pid=None): return candidate==main and backend_pid==55
            def server_identity(self): return "server"
        envelope={"schema_version":1,"harness":"opencode",
            "backend":{"server_url":"http://127.0.0.1:4096","pid":77},
            "roots":{"config_dir":str(root),"data_dir":str(root),"state_dir":str(root)},
            "session":{"id":"child","directory":self.tmp.name,"title":"child"},
            "event_kind":"session.updated"}
        provider=type("Provider",(),{
            "main_metadata":lambda _self,_parent:(main_context,"root"),
            "attach_argv":lambda _self,_child:["opencode","attach","http://127.0.0.1:4096","--session","child","--mini"],
            "close":lambda _self:None})()
        with patch.dict(os.environ,{"HERDR_PANE_ID":"child-pane","HERDR_TAB_ID":"managed-tab",
                "HERDR_WORKSPACE_ID":"workspace","HARNESS_HERDR_DISPLAY":"1"},clear=False), \
             patch.object(cli,"_state_root",return_value=root), patch.object(cli,"_provider",return_value=provider), \
             patch("harness_herdr_hooks.herdr.process_matches_attachment",return_value=True):
            normalized,backend_pid,cwd,_=cli._parent_from_event("opencode-event",json.dumps(envelope).encode(),Client())
        self.assertEqual(normalized,main)
        self.assertEqual(backend_pid,55)
        self.assertEqual(cwd,Path(self.tmp.name))

    def test_opencode_display_rejects_forged_server_pid_and_incarnation(self):
        for forged_pid, forged_instance in ((77, "pid:55"), (55, "pid:77")):
            with self.subTest(pid=forged_pid, instance=forged_instance):
                root=Path(self.tmp.name)/f"opencode-forged-{forged_pid}-{forged_instance}"; root.mkdir()
                main_context=Context(Harness.OPENCODE,str(root),root,root,root,"http://127.0.0.1:4096","main","pid:55")
                child_context=Context(Harness.OPENCODE,str(root),root,root,root,"http://127.0.0.1:4096","child","pid:55")
                main=ParentBinding(main_context,"server","workspace","managed-tab","main-pane")
                child=Session(child_context,"main","child",root,Lifecycle.UNKNOWN,True,1.0)
                save_binding(root,"owned",{"parent":parent_to_dict(main),"child":session_to_dict(child),
                    "pane_id":"child-pane","backend_pid":forged_pid,"server_socket":"/tmp/herdr.sock",
                    "entrypoint":"/bin/entry","shell_pid":None,"ownership":"created"})
                pane={"pane_id":"child-pane","tab_id":"managed-tab","workspace_id":"workspace",
                      "agent_session":{"kind":"id","value":"child","agent":"opencode","source":"plugin"},
                      "cwd":self.tmp.name}
                test_cwd=self.tmp.name
                class Client:
                    socket_path=Path("/tmp/herdr.sock")
                    def snapshot(self): return {"panes":[pane,{"pane_id":"main-pane","cwd":test_cwd}]}
                    def process_info(self,pane_id):
                        pid=55 if pane_id=="main-pane" else 77
                        return {"foreground_processes":[{"pid":pid,"name":"opencode","argv":["opencode","attach"]}]}
                    def verify_parent(self,candidate,backend_pid=None): return candidate==main and backend_pid==55
                    def server_identity(self): return "server"
                envelope={"schema_version":1,"harness":"opencode","backend":{"server_url":"http://127.0.0.1:4096","pid":55},
                    "roots":{"config_dir":str(root),"data_dir":str(root),"state_dir":str(root)},
                    "session":{"id":"child","directory":self.tmp.name,"title":"child"},"event_kind":"session.updated"}
                with patch.dict(os.environ,{"HERDR_PANE_ID":"child-pane","HERDR_TAB_ID":"managed-tab",
                        "HERDR_WORKSPACE_ID":"workspace","HARNESS_HERDR_DISPLAY":"1"},clear=False), \
                     patch.object(cli,"_state_root",return_value=root):
                    with self.assertRaisesRegex(ValueError,"missing or ambiguous owned main binding"):
                        cli._parent_from_event("opencode-event",json.dumps(envelope).encode(),Client())

    def test_codex_session_start_gateway_accepts_real_shaped_root_reference(self):
        root=Path(self.tmp.name)/"codex-event"; root.mkdir()
        pane={"pane_id":"root-pane","tab_id":"tab","workspace_id":"workspace",
              "agent_session":{"kind":"id","value":"thread","agent":"codex","source":"native",
                                "path":"/sessions/thread.json"},"cwd":str(root)}
        class Client:
            socket_path=Path("/tmp/herdr.sock")
            def snapshot(self): return {"panes":[pane]}
            def process_info(self,_pane): return {"foreground_processes":[{"pid":41,"name":"codex"}]}
            def server_identity(self): return "server"
            def verify_parent(self,parent,*_args): return parent.context.session_id=="thread"
        class Provider:
            def __init__(self,*_args,**_kwargs): self.context=_args[0]
            def _read_thread(self,_ident): return {"id":"thread","path":str(root/"thread.json")}
            def close(self): pass
            def main_metadata(self,parent): return parent.context,"root"
        payload=json.dumps({"hook_event_name":"SessionStart","session_id":"thread","cwd":str(root),
                            "transcript_path":None})
        with patch.dict(os.environ,{"HERDR_PANE_ID":"root-pane","HERDR_TAB_ID":"tab",
                "HERDR_WORKSPACE_ID":"workspace","HARNESS_HERDR_DISPLAY":"1","CODEX_HOME":str(root)},clear=False), \
             patch.object(cli,"_native_codex_executable",return_value=Path("/bin/codex")), \
             patch.object(cli,"_verified_pane_root",return_value="thread"), \
             patch("harness_herdr_hooks.cli.CodexRuntimeAdapter",Provider), \
             patch("harness_herdr_hooks.cli.codex_backend_proof",return_value={
                 "executable":"/bin/codex","socket_target":str(root/"socket"),"socket_identity":[1,2,3]}):
            parent,backend_pid,cwd,_=cli._parent_from_event("codex-hook",payload.encode(),Client())
        self.assertEqual(parent.context.session_id,"thread")
        self.assertIsNone(backend_pid)
        self.assertEqual(cwd,root)

    def test_codex_subagent_start_from_attached_child_resolves_original_main(self):
        root=Path(self.tmp.name)/"codex-nested-event"; root.mkdir()
        socket_path=root/"main.sock"
        main_context=Context(Harness.CODEX,str(root),root,root,root,str(socket_path),"main","1:2:3")
        child_context=Context(Harness.CODEX,str(root),root,root,root,str(socket_path),"child","1:2:3")
        main=ParentBinding(main_context,"server","workspace","managed-tab","main-pane",
                           backend_proof={"executable":"/bin/codex"})
        child=Session(child_context,"main","child",root,Lifecycle.UNKNOWN,True,1.0)
        save_binding(root,"owned",{"parent":parent_to_dict(main),"child":session_to_dict(child),
            "pane_id":"child-pane","backend_pid":None,"server_socket":"/tmp/herdr.sock",
            "entrypoint":"/bin/entry","shell_pid":None,"ownership":"reused"})
        pane={"pane_id":"child-pane","tab_id":"managed-tab","workspace_id":"workspace",
              "agent_session":{"kind":"id","value":"child","agent":"codex","source":"native-plugin",
                               "path":"/sessions/child.json"},"cwd":str(root)}
        class Client:
            socket_path=Path("/tmp/herdr.sock")
            def snapshot(self): return {"panes":[dict(pane,revision=4),{"pane_id":"main-pane","cwd":str(root)}]}
            def process_info(self,pane_id):
                return {"foreground_processes":[{"pid":201 if pane_id=="main-pane" else 202,"name":"codex"}]}
            def server_identity(self): return "server"
            def verify_parent(self,parent,*_args): return True
        class Provider:
            def __init__(self,context,*_args,**_kwargs): self.context=context
            def _read_thread(self,ident):
                return {"id":ident,"path":str(root/f"{ident}.json"),
                        "parentThreadId":{"grandchild":"child","child":"main"}.get(ident),
                        "source":{"subAgent":{"thread_spawn":{"parent_thread_id":
                            {"grandchild":"child","child":"main"}.get(ident)}}}}
            _verified_chain=staticmethod(CodexRuntimeAdapter._verified_chain)
            def attach_argv(self,_child): return ["codex","resume","child"]
            def main_metadata(self,_parent): return main_context,"main"
            def close(self): pass
        payload=json.dumps({"hook_event_name":"SubagentStart","session_id":"grandchild","agent_id":"grandchild",
                            "agent_type":"worker","turn_id":"turn-1","cwd":str(root),"transcript_path":None})
        with patch.dict(os.environ,{"HERDR_PANE_ID":"child-pane","HERDR_TAB_ID":"managed-tab",
                "HERDR_WORKSPACE_ID":"workspace","HARNESS_HERDR_DISPLAY":"1","CODEX_HOME":str(root)},clear=False), \
             patch.object(cli,"_state_root",return_value=root), patch.object(cli,"_native_codex_executable",return_value=Path("/bin/codex")), \
             patch.object(cli,"_verified_pane_root",return_value="child"), patch("harness_herdr_hooks.cli.CodexRuntimeAdapter",Provider), \
             patch("harness_herdr_hooks.cli.codex_backend_proof",return_value={"executable":"/bin/codex","socket_target":str(socket_path),"socket_identity":[1,2,3]}), \
             patch("harness_herdr_hooks.herdr.process_matches_attachment",return_value=True):
            parent,backend_pid,cwd,created=cli._parent_from_event("codex-hook",payload.encode(),Client())
        self.assertEqual(parent,main)
        self.assertEqual(parent.context.session_id,"main")
        self.assertIsNone(backend_pid)
        self.assertEqual(cwd,root)
        self.assertEqual(created.event_name,"SubagentStart")
        self.assertEqual(created.identity.session_id,"grandchild")


class CodexGatewayCompatibilityTests(unittest.TestCase):
    """Exercise the CLI gateway with an in-memory app-server transport only."""

    def _run_gateway(self, failure, version="codex-tui/0.171.0", event_name="SessionStart",
                     *, owned=True, expect_success=False):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        socket_path = root / "codex.sock"
        socket_path.touch(exist_ok=True)
        payload = {"hook_event_name": event_name, "session_id": "thread", "cwd": str(root),
                   "transcript_path": None}
        if event_name == "SubagentStart":
            payload.update(session_id="child", agent_id="child", agent_type="worker", turn_id="turn")
        pane = {"pane_id": "pane", "tab_id": "tab", "workspace_id": "workspace",
                "agent_session": {"kind": "id", "value": "thread", "agent": "codex", "source": "native"},
                "cwd": str(root)}

        class Client:
            socket_path = root / "herdr.sock"
            def snapshot(self): return {"panes": [pane]}
            def process_info(self, _pane):
                return {"foreground_processes": [{"pid": 41, "name": "codex"}]}
            def server_identity(self): return "server"
            def verify_parent(self, parent, *_args):
                return parent.herdr_server_id == "server"

        add_cleanup = self.addCleanup

        class FakeProxy(AppServerProxy):
            def __init__(self, executable, socket, *, context):
                # Supply the frame-boundary transport while retaining initialize,
                # profile verification, and JSON-RPC handling from the adapter.
                process = Mock()
                read_fd, write_fd = os.pipe()
                process.stdin = os.fdopen(write_fd, "wb")
                process.stdout = os.fdopen(read_fd, "rb")
                add_cleanup(process.stdin.close)
                add_cleanup(process.stdout.close)
                process.poll.return_value = None
                super().__init__(executable, socket, context=context, popen=lambda *_a, **_kw: process)

            def _inspect_socket(self):
                changed = failure == "endpoint" and getattr(self, "initialized", False)
                return (1, 99 if changed else 2, 3, 0o600)

            def _handshake(self, _deadline):
                if failure == "transport":
                    raise RuntimeError("invalid transport")

            def _send_frame(self, _opcode, payload, _deadline):
                self.outgoing = json.loads(payload)
                if self.outgoing["method"] == "initialized":
                    self.initialized = True

            def _recv_message(self, _deadline):
                method = self.outgoing["method"]
                reply = {"jsonrpc": "2.0", "id": self.outgoing["id"], "futureEnvelopeField": True}
                if method == "thread/loaded/list" and failure == "invalid-json":
                    return 1, b"credential-sentinel transcript-sentinel " + b"x" * 10000
                if method == "thread/loaded/list" and failure == "invalid-id":
                    reply["id"] = float(self.outgoing["id"])
                if failure == "method" and method == "thread/loaded/list":
                    reply["error"] = {"code": -32601, "message": "method unavailable"}
                else:
                    reply["result"] = self._result(method, self.outgoing["params"])
                return 1, json.dumps(reply).encode()

            def _result(self, method, params):
                if method == "initialize":
                    response = {"codexHome": str(root / "other" if failure == "profile" else root),
                                "futureField": {"value": True}}
                    if version is not None:
                        response["userAgent"] = version
                    return response
                if method == "thread/loaded/list":
                    if failure == "response": return {"data": "malformed"}
                    if failure == "cursor": return {"data": ["thread"], "nextCursor": False}
                    return {"data": ["thread"], "futureField": True}
                if method == "thread/read":
                    ident = params["threadId"]
                    row = {"id": "wrong" if failure == "wrong-thread" else ident,
                           "path": str(root / f"{ident}.json")}
                    if ident == "thread" and owned is not True:
                        row.update(parentThreadId="main", source={
                            "subAgent": {"thread_spawn": {"parent_thread_id": "main"}}})
                    if event_name == "SubagentStart" and ident == "child":
                        row["parentThreadId"] = "thread"
                        if failure != "ancestry":
                            row["source"] = {"subAgent": {"thread_spawn": {"parent_thread_id": "thread"}}}
                    return {"thread": row}
                raise AssertionError(f"unexpected RPC method {method}")

        executable = Path("/usr/bin/python3")
        effects = {name: Mock() for name in ("observer", "popen", "attach", "cleanup", "create_tab")}
        env = {"HERDR_ENV": "1", "HERDR_SOCKET_PATH": str(Client.socket_path),
               "HERDR_PANE_ID": "pane", "HERDR_TAB_ID": "tab", "HERDR_WORKSPACE_ID": "workspace",
               "CODEX_HOME": str(root), "HARNESS_HERDR_STATE_ROOT": str(root),
               "HARNESS_HERDR_DISPLAY": "0" if owned is True else "1"}
        client = Client()
        client.create_tab = effects["create_tab"]
        if owned == "foreign":
            thread = Context(Harness.CODEX, str(root), root, root, root, str(socket_path), "thread", "1:2:3")
            main = Context(Harness.CODEX, str(root), root, root, root, str(socket_path), "main", "1:2:3")
            parent = ParentBinding(main, "foreign-server", "workspace", "tab", "root-pane")
            child = Session(thread, "main", "thread", root, Lifecycle.UNKNOWN, True, 1.0)
            save_binding(root, "foreign", {"parent": parent_to_dict(parent), "child": session_to_dict(child),
                "pane_id": "pane", "server_socket": str(client.socket_path), "entrypoint": "/bin/entry",
                "shell_pid": None, "backend_pid": None, "ownership": "created"})
        diagnostic = io.StringIO()
        with contextlib.redirect_stderr(diagnostic), patch.dict(os.environ, env, clear=False), \
             patch("sys.stdin", type("Input", (), {"buffer": io.BytesIO(json.dumps(payload).encode())})()), \
             patch.object(cli, "_herdr_client", return_value=client), \
             patch.object(cli, "_native_codex_executable", return_value=executable), \
             patch("harness_herdr_hooks.adapters.codex.shutil.which", return_value=str(executable)), \
             patch("harness_herdr_hooks.cli.codex_backend_proof", return_value={
                 "executable": str(executable), "socket_target": str(socket_path),
                 "socket_identity": [1, 2, 3]}), \
             patch.object(cli, "_start_observer", effects["observer"]), \
             patch.object(cli, "_record_hook"), \
             patch("harness_herdr_hooks.cli.subprocess.Popen", effects["popen"]), \
             patch.object(cli, "exec_binding", effects["attach"]), \
             patch.object(cli, "_retire_observer", effects["cleanup"]), \
             patch.object(cli.time, "sleep"):
            with patch("harness_herdr_hooks.cli.CodexRuntimeAdapter",
                       side_effect=lambda context, executable=str(executable), **_kwargs:
                           CodexRuntimeAdapter(context, executable=executable, proxy_factory=FakeProxy)):
                result = cli.main(["codex-hook"])
        if expect_success:
            effects["observer"].assert_called_once()
            for key in ("popen", "attach", "cleanup", "create_tab"):
                effects[key].assert_not_called()
        else:
            for effect in effects.values():
                effect.assert_not_called()
        return result, diagnostic.getvalue()

    def test_incompatible_transport_profile_method_and_response_fail_before_effects(self):
        for failure, stage in (
            ("transport", "transport failed for initialize"),
            ("profile", "profile check failed for initialize"),
            ("method", "method failed for thread/loaded/list"),
            ("response", "response failed for thread/loaded/list"),
            ("cursor", "invalid or cyclic pagination cursor"),
            ("invalid-id", "invalid JSON-RPC response ID"),
            ("invalid-json", "invalid JSON-RPC message"),
        ):
            with self.subTest(failure=failure):
                result, diagnostic = self._run_gateway(failure)
                self.assertEqual(result, 2)
                self.assertIn(stage, diagnostic)
                self.assertIn("version unknown" if failure == "transport" else "0.171.0", diagnostic)
                self.assertNotIn("credential-sentinel", diagnostic)
                self.assertNotIn("transcript-sentinel", diagnostic)
                self.assertLess(len(diagnostic), 200)

    def test_new_and_unknown_release_metadata_do_not_bypass_gateway_checks(self):
        # The accepted adapter handshake reaches the gateway; each independent
        # identity/ownership denial must still prevent observer/effect startup.
        for version in ("codex-tui/99.0.0", None):
            for failure, event, message in (
                ("endpoint", "SessionStart", "socket identity check failed"),
                ("wrong-thread", "SessionStart", "metadata identity mismatch"),
                ("ancestry", "SubagentStart", "source chain does not reach pane root"),
            ):
                with self.subTest(version=version, failure=failure):
                    result, diagnostic = self._run_gateway(failure, version, event)
                    self.assertEqual(result, 2)
                    self.assertIn(message, diagnostic)
            for ownership in (False, "foreign"):
                with self.subTest(version=version, failure="ownership", marker=ownership):
                    result, diagnostic = self._run_gateway(None, version, owned=ownership)
                    self.assertEqual(result, 2)
                    self.assertIn("missing or ambiguous owned main binding", diagnostic)

    def test_compatible_handshakes_reach_observer_start(self):
        for version in ("codex-tui/0.170.0", "codex-tui/0.171.0", "codex-tui/99.0.0",
                        "unfamiliar agent", None):
            with self.subTest(version=version):
                result, diagnostic = self._run_gateway("success", version, expect_success=True)
                self.assertEqual(result, 0, diagnostic)


if __name__ == "__main__":
    unittest.main()
