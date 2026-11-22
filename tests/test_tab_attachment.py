import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

from harness_herdr_hooks.attach import binding_tab_id, attach_in_new_pane, AttachmentUnavailable
from harness_herdr_hooks.model import (Context, Harness, Lifecycle, ParentBinding,
    Session, SubagentDestination, destination_to_dict, parent_to_dict, session_to_dict)
from harness_herdr_hooks.state import StateStore
from harness_herdr_hooks.tabs import SubagentTabManager


class BindingTabResolutionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.anchor_patch = patch("harness_herdr_hooks.tabs._resolve_workspace_anchor",
                                  return_value=self.root / "canonical")
        self.anchor_patch.start()
        self.ctx = Context(Harness.CODEX, "p", self.root, self.root, self.root, "backend", "main", "inc")
        self.parent = ParentBinding(self.ctx, "server", "workspace", "original", "main-pane")
        child_ctx = Context(Harness.CODEX, "p", self.root, self.root, self.root, "backend", "child", "inc")
        self.child = Session(child_ctx, "main", None, self.root, Lifecycle.RUNNING, True, 1.0)
        self.manager = SubagentTabManager(StateStore(self.root, "base"), self.ctx, "server", "workspace",
                                          _workspace_anchor=self.root / "canonical")

    def tearDown(self):
        self.anchor_patch.stop()
        self.tmp.cleanup()

    def binding(self, kind="subagent", server="server", tab="managed", generation="g1"):
        record = {"parent": parent_to_dict(self.parent), "child": session_to_dict(self.child),
                  "pane_id": "child-pane", "kind": kind, "generation": "turn",
                  "destination": destination_to_dict(SubagentDestination(
                      self.ctx, server, "workspace", tab, generation, "initial-pane", "child-pane"))}
        return record

    def commit(self):
        with self.manager.operations() as token:
            reservation = self.manager.reserve_label(token, "Root", "main", "g1")
            claim = self.manager.begin_create(token, reservation, "g1")
            destination = self.manager.commit_create(token, claim, tab_id="managed", initial_pane_id="initial-pane")
            self.manager.bind_child(token, destination, child_pane_id="child-pane")
            self.manager.bind_child(token, destination, child_pane_id="child-one")

    def test_legacy_has_no_destination_and_independent_is_rejected(self):
        self.assertIsNone(binding_tab_id(self.root, {}, self.parent))
        self.commit()
        record = self.binding(kind="independent")
        self.assertIsNone(binding_tab_id(self.root, record, self.parent))

    def test_exact_current_destination_resolves_without_operation_lock(self):
        self.commit()
        with self.manager.operations():
            self.assertEqual(binding_tab_id(self.root, self.binding(), self.parent), "managed")

    def test_wrong_server_and_stale_generation_fail_closed(self):
        self.commit()
        self.assertIsNone(binding_tab_id(self.root, self.binding(server="other"), self.parent))
        self.assertIsNone(binding_tab_id(self.root, self.binding(generation="old"), self.parent))

    def test_initial_reuses_first_pane_and_later_child_targets_split(self):
        destination = SubagentDestination(self.ctx, "server", "workspace", "managed", "g1", "initial-pane")
        cwd = str(self.root)
        class Client:
            def __init__(self): self.split_calls=[]; self.sent=[]; self.hide_initial=False
            def snapshot(self): return {"panes":([{"pane_id":"initial-pane","workspace_id":"workspace","tab_id":"managed","cwd":cwd,"agent_session":None}] if not self.hide_initial else [])+[{"pane_id":"child-one","workspace_id":"workspace","tab_id":"managed"}]}
            def server_identity(self): return "server"
            def process_info(self, pane): return {"shell_pid":10,"foreground_processes":[{"pid":10,"argv0":"bash","argv":["bash"]}]}
            def split_subagent_tab(self,*args,**kwargs): self.split_calls.append(args); return "child-two"
            def send_text(self,*args): self.sent.append(args)
            def send_keys(self,*args): pass
            def wait_for_attachment(self,*args,**kwargs): return True
        class Provider:
            def attach_argv(self, child): return ["codex","resume",child.context.session_id]
        class Runtime:
            provider=Provider()
            def verify_parent(self,parent): return True
            def can_attach_now(self,parent,child): return True
        self.commit()
        client=Client(); callback_calls=[]
        def callback(pane,info,dest): callback_calls.append((pane,dest))
        with patch("harness_herdr_hooks.attach._outcome"):
            first=attach_in_new_pane(client,Runtime(),self.parent,self.child,Path("/tmp/hook"),"b1",self.root,
                on_pane_created=callback,destination=destination,initial_pane_id="initial-pane")
        self.assertEqual(first,"initial-pane")
        self.assertEqual(client.split_calls,[])
        with patch("harness_herdr_hooks.attach._outcome"):
            same_target=attach_in_new_pane(client,Runtime(),self.parent,self.child,Path("/tmp/hook"),"b2",self.root,
                on_pane_created=callback,destination=destination,initial_pane_id="initial-pane",target_pane_id="initial-pane")
        self.assertEqual(same_target,"child-two")
        self.assertEqual(client.split_calls[-1][0],"initial-pane")
        client.hide_initial=True
        with patch("harness_herdr_hooks.attach._outcome"):
            second=attach_in_new_pane(client,Runtime(),self.parent,self.child,Path("/tmp/hook"),"b3",self.root,
                on_pane_created=callback,destination=destination,initial_pane_id="initial-pane",target_pane_id="child-one")
        self.assertEqual(second,"child-two")
        self.assertEqual(client.split_calls[-1][0],"child-one")
        self.assertEqual([row[0] for row in callback_calls],["initial-pane","child-two","child-two"])
        # A user pane in the exact claimed destination is a valid split
        # anchor, even though it is intentionally absent from owned pane_ids.
        user_pane = "user-pane"
        client.snapshot = lambda: {"panes": [
            {"pane_id": user_pane, "workspace_id": "workspace", "tab_id": "managed",
             "cwd": cwd, "agent_session": None},
        ]}
        with patch("harness_herdr_hooks.attach._outcome"):
            split_from_user = attach_in_new_pane(
                client, Runtime(), self.parent, self.child, Path("/tmp/hook"), "b-user", self.root,
                on_pane_created=callback, destination=destination, initial_pane_id="initial-pane",
                target_pane_id=user_pane)
        self.assertEqual(split_from_user, "child-two")
        self.assertEqual(client.split_calls[-1][0], user_pane)
        stale=SubagentDestination(self.ctx,"server","workspace","managed","stale-generation","initial-pane")
        before=(len(client.split_calls),len(client.sent))
        with self.assertRaises(AttachmentUnavailable):
            attach_in_new_pane(client,Runtime(),self.parent,self.child,Path("/tmp/hook"),"b4",self.root,
                on_pane_created=callback,destination=stale,initial_pane_id="initial-pane",target_pane_id="child-one")
        self.assertEqual((len(client.split_calls),len(client.sent)),before)


if __name__ == "__main__": unittest.main()
