from __future__ import annotations

import os
import pty
import select
import subprocess
import sys
import termios
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from harness_herdr_hooks.coordinator import NativeRuntime
from harness_herdr_hooks.model import Context, CreationProof, Harness, Lifecycle, ParentBinding, Session


class StandaloneShellTests(unittest.TestCase):
    def test_standalone_runtime_uses_durable_session_attachment_only(self):
        context = Context(Harness.CODEX, "/tmp/profile", Path("/tmp/profile"),
                          Path("/tmp/profile"), Path("/tmp/profile"), "/tmp/codex.sock",
                          "child", "instance")
        parent_context = Context(Harness.CODEX, "/tmp/profile", Path("/tmp/profile"),
                                 Path("/tmp/profile"), Path("/tmp/profile"), "/tmp/codex.sock",
                                 "parent", "instance")
        parent = ParentBinding(parent_context, "server", "workspace", "tab", "pane")
        child = Session(context, "parent", "standalone", Path("/tmp/work"),
                        Lifecycle.RUNNING, True, 0, kind="standalone",
                        creation_proof=CreationProof("parent", "turn", "item", "child"))
        runtime = object.__new__(NativeRuntime)
        runtime.state_root = Path("/tmp/state")
        runtime.verify_parent = lambda _parent: True
        calls = []

        def attach(client, state_root, **kwargs):
            calls.append((client, state_root, kwargs))
            return "pane-child"

        runtime.herdr = SimpleNamespace(pane_has_session=lambda *args, **kwargs: True)
        with patch("harness_herdr_hooks.attach.attach_standalone_session", side_effect=attach), \
             patch("harness_herdr_hooks.coordinator.update_binding_outcome"):
            self.assertTrue(runtime.open_and_attach(parent, child, "binding-id"))
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][2]["backend_socket"], Path("/tmp/codex.sock"))
        self.assertEqual(calls[0][2]["parent_session_id"], "parent")
        self.assertEqual(calls[0][2]["child_session_id"], "child")

    def test_native_child_open_callback_is_inert(self):
        runtime = object.__new__(NativeRuntime)
        calls = []
        runtime.can_attach_now = lambda *_: calls.append("attach") or True
        context = Context(Harness.CODEX, "/tmp/profile", Path("/tmp/profile"),
                          Path("/tmp/profile"), Path("/tmp/profile"), "/tmp/socket",
                          "child", "instance")
        parent = ParentBinding(context, "server", "workspace", "tab", "pane")
        child = Session(context, "parent", "native", Path("/tmp"),
                        Lifecycle.RUNNING, True, 0, kind="subagent")
        self.assertFalse(runtime.open_and_attach(parent, child, "legacy-binding"))
        self.assertEqual(calls, [])



if __name__ == "__main__":
    unittest.main()
