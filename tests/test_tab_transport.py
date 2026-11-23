"""Session-only Herdr transport and one-shot pane effect regressions."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
import os

from harness_herdr_hooks.attach import AttachmentUnavailable, attach_standalone_session
from harness_herdr_hooks.herdr import HerdrClient, HerdrError
from harness_herdr_hooks.state import StateStore


def pane(pane_id, tab="tab", session="parent"):
    return {"pane_id": pane_id, "workspace_id": "work", "tab_id": tab,
            "focused": False, "agent_session": {
                "source": "native", "agent": "codex", "kind": "id", "value": session}}


class StandaloneTransportTests(unittest.TestCase):
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
            self.assertEqual(h.split_standalone.call_args.kwargs["env"]["CODEX_HOME"], str(root))

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
