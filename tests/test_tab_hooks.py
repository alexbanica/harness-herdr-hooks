import tempfile
import unittest
import json
import os
from pathlib import Path
from unittest.mock import patch

from harness_herdr_hooks import cli
from harness_herdr_hooks.model import Context, Harness, ParentBinding, Session, Lifecycle, parent_to_dict, session_to_dict
from harness_herdr_hooks.state import save_binding
from harness_herdr_hooks.adapters.codex import CodexRuntimeAdapter


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


if __name__ == "__main__":
    unittest.main()
