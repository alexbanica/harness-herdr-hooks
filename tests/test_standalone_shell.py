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

from harness_herdr_hooks.attach import wrapper_command
from harness_herdr_hooks.coordinator import NativeRuntime
from harness_herdr_hooks.model import Context, Harness, Lifecycle, ParentBinding, Session


class StandaloneShellTests(unittest.TestCase):
    def test_standalone_wrapper_returns_to_usable_shell_after_exec_helper_exits(self):
        with tempfile.TemporaryDirectory() as temporary:
            helper = Path(temporary) / "harmless helper"
            helper.write_text(
                f"#!{sys.executable}\n"
                "import os, sys\n"
                "os.execvpe(sys.executable, [sys.executable, '-c', 'pass'], os.environ)\n"
            )
            helper.chmod(0o755)
            command = wrapper_command(helper, "standalone-1", preserve_shell=True)
            self.assertFalse(command.startswith("exec "))

            master, slave = pty.openpty()
            tty = termios.tcgetattr(slave)
            tty[3] &= ~termios.ECHO
            termios.tcsetattr(slave, termios.TCSANOW, tty)
            shell = subprocess.Popen(
                ["/bin/sh", "-i"], stdin=slave, stdout=slave, stderr=slave,
                close_fds=True, start_new_session=True,
            )
            os.close(slave)
            try:
                os.write(master, (command + "\necho SHELL_READY\n").encode())
                output = bytearray()
                deadline = time.monotonic() + 4
                while b"SHELL_READY" not in output and time.monotonic() < deadline:
                    ready, _, _ = select.select([master], [], [], .1)
                    if ready:
                        try:
                            output.extend(os.read(master, 4096))
                        except OSError:
                            break
                self.assertIn(b"SHELL_READY", output)
                self.assertIsNone(shell.poll(), "interactive shell should remain available")
            finally:
                shell.terminate()
                try:
                    shell.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    shell.kill()
                    shell.wait(timeout=1)
                os.close(master)

            # The native wrapper's shell-level exec would consume the shell;
            # verify the prompt assertion above depends on preserving it.
            master, slave = pty.openpty()
            tty = termios.tcgetattr(slave)
            tty[3] &= ~termios.ECHO
            termios.tcsetattr(slave, termios.TCSANOW, tty)
            shell = subprocess.Popen(
                ["/bin/sh", "-i"], stdin=slave, stdout=slave, stderr=slave,
                close_fds=True, start_new_session=True,
            )
            os.close(slave)
            try:
                native_command = wrapper_command(helper, "standalone-1")
                os.write(master, (native_command + "\necho MUST_NOT_RETURN\n").encode())
                shell.wait(timeout=2)
                ready, _, _ = select.select([master], [], [], .1)
                output = os.read(master, 4096) if ready else b""
                self.assertNotIn(b"MUST_NOT_RETURN", output)
            finally:
                if shell.poll() is None:
                    shell.terminate()
                    shell.wait(timeout=1)
                os.close(master)

    def test_native_wrapper_keeps_shell_level_exec(self):
        command = wrapper_command(Path("/tmp/harness-herdr-hooks"), "native-1")
        self.assertTrue(command.startswith("exec "))
        self.assertEqual(
            wrapper_command(Path("/tmp/harness-herdr-hooks"), "standalone-1", preserve_shell=True),
            "/tmp/harness-herdr-hooks attach standalone-1",
        )

    def test_runtime_selects_shell_preserving_wrapper_only_for_standalone(self):
        context = Context(Harness.CODEX, "/tmp/profile", Path("/tmp/profile"),
                          Path("/tmp/profile"), Path("/tmp/profile"), "/tmp/socket",
                          "child", "instance")
        parent = ParentBinding(context, "server", "workspace", "tab", "pane")
        runtime = object.__new__(NativeRuntime)
        runtime.state_root = Path("/tmp/state")
        runtime.entrypoint = Path("/tmp/harness-herdr-hooks")
        runtime.backend_pid = None
        runtime.provider = SimpleNamespace()
        runtime.herdr = SimpleNamespace(socket_path=Path("/tmp/socket"), rename=lambda *_: None,
                                        safe_label=lambda *args: "standalone")
        runtime.can_attach_now = lambda *_: True
        runtime.owned_pane_state = lambda *_: "live"
        calls = []

        def attach(*args, **kwargs):
            calls.append(kwargs["preserve_shell"])
            kwargs["on_pane_created"]("pane-created", {"shell_pid": 123})
            return "pane-created"

        children = [
            Session(context, "parent", "standalone", Path("/tmp"), Lifecycle.RUNNING,
                    True, 0, kind="standalone"),
            Session(context, "parent", "subagent", Path("/tmp"), Lifecycle.RUNNING,
                    True, 0, kind="subagent"),
        ]
        with patch("harness_herdr_hooks.coordinator.load_existing_binding", side_effect=FileNotFoundError), \
             patch("harness_herdr_hooks.coordinator.save_binding"), \
             patch("harness_herdr_hooks.coordinator.update_binding_outcome"), \
             patch("harness_herdr_hooks.attach.attach_in_new_pane", side_effect=attach):
            self.assertTrue(runtime.open_and_attach(parent, children[0], "standalone-binding"))
            self.assertFalse(runtime.open_and_attach(parent, children[1], "metadata-less-native-binding"))
        self.assertEqual(calls, [True])


if __name__ == "__main__":
    unittest.main()
