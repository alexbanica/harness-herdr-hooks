"""Session-only Herdr transport and one-shot pane effect regressions."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
import os
import hashlib
import json
import pty
import shutil
import threading
import time
from types import SimpleNamespace

from harness_herdr_hooks.attach import AttachmentUnavailable, attach_standalone_session
from harness_herdr_hooks.herdr import AgentPaneBusy, HerdrClient, HerdrError
from harness_herdr_hooks.state import StateStore
from harness_herdr_hooks.client_binding import ClientBindingStore, BindingError
from harness_herdr_hooks.coordinator import ManagedPlacement
from harness_herdr_hooks.model import Context, CreationProof, Harness, Lifecycle, ParentBinding, Session


def pane(pane_id, tab="tab", session="parent"):
    return {"pane_id": pane_id, "workspace_id": "work", "tab_id": tab,
            "focused": False, "agent_session": {
                "source": "native", "agent": "codex", "kind": "id", "value": session}}


class StandaloneTransportTests(unittest.TestCase):
    def _managed_fixture(self, root, *, delayed=None):
        root=Path(root); profile=root/"profile"; profile.mkdir(mode=0o700)
        alias_dir=profile/"app-server-control"; alias_dir.mkdir(mode=0o700)
        pin=SimpleNamespace(target=Path("/private/codex.sock"),instance="1:2:3")
        adapter=profile/"harness-herdr-hooks"/"codex-adapter"; adapter.mkdir(parents=True,mode=0o700)
        shim=adapter/"codex"; shim.write_bytes(b"managed shim"); shim.chmod(0o700)
        metadata=adapter/"adapter.json"; metadata.write_bytes(b"{}"); metadata.chmod(0o600)
        path_value=str(adapter)+os.pathsep+"/usr/bin"
        manifest={"entries":{"codex":{"source":"/opt/herdr/bin/harness-herdr-hooks",
            "client_binding":{"reporting_helper":"/opt/herdr/bin/harness-herdr-hooks"},"adapter_dir":str(adapter),
            "adapter_sha256":hashlib.sha256(shim.read_bytes()).hexdigest(),
            "metadata_sha256":hashlib.sha256(metadata.read_bytes()).hexdigest(),
            "path":{"installed_path":path_value}}}}
        manifest_path=profile/".harness-herdr-hooks.json"; manifest_path.write_text(json.dumps(manifest)); manifest_path.chmod(0o600)
        state_root=root/"state"; store=ClientBindingStore(state_root)
        parent_id="123e4567-e89b-42d3-a456-426614174000"; child_id="123e4567-e89b-42d3-a456-426614174001"
        master,slave=pty.openpty(); self.addCleanup(os.close,master); self.addCleanup(os.close,slave)
        st=os.fstat(slave)
        lease=store.open_lease(profile=str(profile),backend={"endpoint":str(pin.target),"instance":pin.instance},
            server_id="server",workspace_id="work",tab_id="tab",pane_id="parent-pane",
            terminal_device=st.st_dev,terminal_inode=st.st_ino,
            initial_report={"version":1,"sequence":1,"event":"active","thread_id":parent_id,"source":"startup"})
        self.addCleanup(lease.close)
        lease.accept({"version":1,"sequence":2,"event":"created","thread_id":parent_id,
                      "child_id":child_id,"turn_id":"turn-1","view_sequence":1})
        context=Context(Harness.CODEX,str(profile),profile,profile,state_root,str(pin.target),parent_id,pin.instance)
        parent=ParentBinding(context,"server","work","tab","parent-pane",
            backend_proof={"client_key":lease.key,"client_generation":lease.record["generation"],"client_view_sequence":1})
        child_context=Context(Harness.CODEX,str(profile),profile,profile,state_root,str(pin.target),child_id,pin.instance)
        child=Session(child_context,parent_id,"child",root,Lifecycle.RUNNING,True,1,kind="standalone",
                      creation_proof=CreationProof(parent_id,"turn-1","item-1",child_id))
        class FakeHerdr:
            def __init__(self): self.started=False; self.split_calls=0; self.start_calls=0; self.child_lease=None; self.child_fds=None
            def server_identity(self): return "server"
            def pane_has_session(self,pane_id,session_id,**kw):
                return (pane_id=="parent-pane" and session_id==parent_id) or (pane_id=="child-pane" and self.started and session_id==child_id)
            def split_standalone(self,workspace,anchor,cwd,*,env):
                self.split_calls+=1; self.env=env
                if delayed=="split":
                    split_entered.set(); release.wait(2); raise HerdrError("split response timed out")
                return {"pane_id":"child-pane","workspace_id":workspace,"tab_id":"tab","focused":False}
            def snapshot(self):
                return {"panes":[{"pane_id":"child-pane","workspace_id":"work","tab_id":"tab",
                                  "focused":False,"agent":None,"agent_session":None}]}
            def start_agent(self,pane_id,binding,args):
                self.start_calls+=1
                self.assert_managed_args=(pane_id,binding,args)
                if delayed=="start":
                    start_entered.set(); release.wait(2); raise HerdrError("start response timed out")
                self.started=True
                c_master,c_slave=pty.openpty(); self.child_fds=(c_master,c_slave); child_st=os.fstat(c_slave)
                self.child_lease=store.open_lease(profile=str(profile),backend={"endpoint":str(pin.target),"instance":pin.instance},
                    server_id="server",workspace_id="work",tab_id="tab",pane_id="child-pane",
                    terminal_device=child_st.st_dev,terminal_inode=child_st.st_ino,
                    initial_report={"version":1,"sequence":1,"event":"active","thread_id":child_id,"source":"startup"})
                return pane_id
        split_entered=threading.Event(); start_entered=threading.Event(); release=threading.Event()
        herdr=FakeHerdr()
        runtime=type("Runtime",(),{})(); runtime.state_root=state_root; runtime.herdr=herdr
        placement=ManagedPlacement(runtime,parent,child)
        kwargs=dict(event_key=hashlib.sha256(json.dumps([parent_id,"turn-1","item-1"],separators=(",",":")).encode()).hexdigest(),
            binding_id="binding-1",parent_session_id=parent_id,state_namespace=context.key()[:32],child_session_id=child_id,
            backend_socket=Path(pin.target),cwd=root,profile_home=profile,managed=placement)
        return lease,herdr,placement,kwargs,split_entered,start_entered,release

    def test_unique_destination_uses_lexical_anchor_and_rejects_ambiguity(self):
        h = HerdrClient("/unused")
        h.peer_identity = (os.getuid(), 1)
        snapshot = {"panes": [pane("z"), pane("a"), pane("other", session="different")]}
        with patch.object(h, "snapshot", return_value=snapshot), patch.object(h, "server_identity", return_value="server"):
            self.assertEqual(h.session_destination("parent")["anchor_pane_id"], "a")
            self.assertIsNone(h.session_destination("missing"))
            self.assertTrue(h.pane_has_session("a", "parent", workspace_id="work", tab_id="tab"))
            snapshot["panes"].append(pane("conflict", tab="another"))
            self.assertIsNone(h.session_destination("parent"))

    def test_managed_start_requires_canonical_typed_acknowledgement(self):
        h = HerdrClient("/unused")
        args = ["resume", "--remote", "unix:///profile/socket", "child"]
        with patch.object(h, "request", return_value={
                "type": "agent_started", "agent": {"pane_id": "child-pane"}, "argv": ["codex", *args]}) as request:
            self.assertEqual(h.start_agent("child-pane", "binding", args), "child-pane")
            method, params = request.call_args.args
            self.assertEqual(method, "agent.start")
            self.assertRegex(params["name"], r"\A[a-z][a-z0-9_-]{0,31}\Z")
            self.assertEqual(params["args"], args)
            self.assertEqual(params["timeout_ms"], 4000)
            self.assertEqual(params["kind"], "codex")
            request.return_value = {"type": "agent_started", "pane_id": "child-pane"}
            with self.assertRaises(HerdrError):
                h.start_agent("child-pane", "binding", args)

    def test_positive_split_claim_start_and_exact_session_ack(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            h = Mock(spec=["server_identity", "session_destination", "split_standalone",
                           "start_agent", "pane_has_session", "snapshot"])
            h.server_identity.return_value = "server"
            h.session_destination.return_value = {
                "server_id": "server", "workspace_id": "work", "tab_id": "tab", "anchor_pane_id": "anchor"}
            h.split_standalone.return_value = pane("new")
            h.snapshot.return_value = {"panes": [{**pane("new"), "agent_session": None}]}
            store = StateStore(root, "parent")

            def start(pane_id, binding, args):
                self.assertEqual(store.standalone_effect("event")["pane_id"], "new")
                self.assertEqual(store.standalone_effect("event", "start")["status"], "intent")
                self.assertEqual((pane_id, binding, args[-1]), ("new", "binding", "child"))
                if h.start_agent.call_count == 1:
                    raise AgentPaneBusy("shell is starting")
                return pane_id

            h.start_agent.side_effect = start
            h.pane_has_session.side_effect = [False, True]
            with patch("harness_herdr_hooks.attach.time.sleep"):
                self.assertEqual(attach_standalone_session(
                    h, root, event_key="event", binding_id="binding", parent_session_id="parent",
                    state_namespace="parent", child_session_id="child", backend_socket=root/"socket",
                    cwd=root, profile_home=root), "new")
            self.assertEqual(store.standalone_effect("event", "start")["status"], "attached")
            self.assertEqual(h.pane_has_session.call_args.args, ("new", "child"))
            self.assertEqual(h.start_agent.call_count, 2)
            h.split_standalone.assert_called_once()
            self.assertEqual(h.split_standalone.call_args.kwargs["env"]["CODEX_HOME"], str(root))

    def test_real_managed_lease_authorizes_split_start_and_exact_child_attach(self):
        from harness_herdr_hooks.attach import attach_standalone_session
        tmp=tempfile.mkdtemp(); self.addCleanup(shutil.rmtree,tmp)
        lease,h,placement,kwargs,*_=self._managed_fixture(tmp)
        with patch("harness_herdr_hooks.codex_backend.select_endpoint",return_value=SimpleNamespace(target=Path("/private/codex.sock"),instance="1:2:3")), \
             patch("harness_herdr_hooks.attach.time.sleep"):
            result=attach_standalone_session(h,Path(tmp)/"state",**kwargs)
        self.assertEqual(result,"child-pane")
        self.assertEqual((h.split_calls,h.start_calls),(1,1))
        self.assertEqual(h.env["PATH"],placement.split_path)
        self.assertEqual(h.assert_managed_args[2],
            ["resume","--remote",f"unix://{kwargs['backend_socket']}",kwargs["child_session_id"]])
        self.assertEqual(lease.store.read_live(lease.key,lease.record["generation"])["unresolved_effect"],None)
        self.assertIsNotNone(h.child_lease)
        h.child_lease.close()
        for fd in h.child_fds: os.close(fd)
        lease.close()

    def test_managed_clear_race_does_not_acknowledge_during_delayed_split_or_start(self):
        from harness_herdr_hooks.attach import attach_standalone_session
        for delayed,entered in (("split","split"),("start","start")):
            with self.subTest(stage=delayed):
                tmp=tempfile.mkdtemp(); self.addCleanup(shutil.rmtree,tmp)
                lease,h,placement,kwargs,split_entered,start_entered,release=self._managed_fixture(tmp,delayed=delayed)
                endpoint_pin=patch("harness_herdr_hooks.codex_backend.select_endpoint",
                    return_value=SimpleNamespace(target=Path("/private/codex.sock"),instance="1:2:3"))
                endpoint_pin.start(); self.addCleanup(endpoint_pin.stop)
                rpc_entered=split_entered if entered=="split" else start_entered
                attach_error=[]
                def run_attach():
                    try: attach_standalone_session(h,Path(tmp)/"state",**kwargs)
                    except Exception as exc: attach_error.append(exc)
                worker=threading.Thread(target=run_attach); worker.start()
                self.assertTrue(rpc_entered.wait(1),f"{delayed} RPC did not start")
                clear_error=[]; clear_done=threading.Event(); clear_started=threading.Event()
                def clear_view():
                    clear_started.set()
                    try: lease.accept({"version":1,"sequence":3,"event":"clear","thread_id":None})
                    except Exception as exc: clear_error.append(exc)
                    finally: clear_done.set()
                clearer=threading.Thread(target=clear_view); clearer.start()
                self.assertTrue(clear_started.wait(1))
                time.sleep(.03)
                self.assertFalse(clear_done.is_set(),"clear must wait for the in-flight managed effect guard")
                release.set(); worker.join(2); clearer.join(2)
                self.assertTrue(attach_error)
                self.assertTrue(clear_error)
                self.assertEqual(lease.store.read_live(lease.key,lease.record["generation"])["unresolved_effect"]["stage"],delayed)
                self.assertEqual(h.split_calls,1)
                self.assertEqual(h.start_calls,int(delayed=="start"))
                lease.close()

    def test_uncertain_effects_are_not_repeated_after_restart(self):
        for failure in ("split-reply", "before-claim", "after-claim", "start-reply"):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                h = Mock(spec=["server_identity", "session_destination", "split_standalone",
                               "start_agent", "pane_has_session", "snapshot"])
                h.server_identity.return_value = "server"
                h.session_destination.return_value = {"server_id": "server", "workspace_id": "work",
                    "tab_id": "tab", "anchor_pane_id": "anchor"}
                h.split_standalone.return_value = pane("child-pane")
                h.start_agent.return_value = "child-pane"
                h.snapshot.return_value = {"panes": [{**pane("child-pane"), "agent_session": None}]}
                kwargs = dict(event_key="event", binding_id="binding", parent_session_id="parent",
                              state_namespace="parent", child_session_id="child",
                              backend_socket=root/"socket", cwd=root, profile_home=root)
                if failure == "split-reply":
                    h.split_standalone.side_effect = HerdrError("lost split response")
                if failure == "start-reply":
                    h.start_agent.side_effect = HerdrError("lost start response")
                if failure == "before-claim":
                    with patch.object(StateStore, "record_standalone_pane_claim", side_effect=RuntimeError("crash")):
                        with self.assertRaises(RuntimeError):
                            attach_standalone_session(h, root, **kwargs)
                elif failure == "after-claim":
                    claim = Mock(side_effect=RuntimeError("crash before start intent"))
                    with self.assertRaises(RuntimeError):
                        attach_standalone_session(h, root, on_pane_claim=claim, **kwargs)
                    self.assertEqual(StateStore(root, "parent").standalone_effect("event")["pane_id"], "child-pane")
                else:
                    with self.assertRaises(HerdrError):
                        attach_standalone_session(h, root, **kwargs)
                with self.assertRaises(AttachmentUnavailable):
                    attach_standalone_session(h, root, **kwargs)
                self.assertEqual(h.split_standalone.call_count, 1)
                self.assertEqual(h.start_agent.call_count, int(failure == "start-reply"))
