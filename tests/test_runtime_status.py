import contextlib
import io
import json
import unittest
from unittest.mock import patch

from harness_herdr_hooks import cli


class RuntimeStatusRetirementTests(unittest.TestCase):
    def test_status_reports_only_standalone_diagnostics(self):
        output = io.StringIO()
        task = {"recognition": "recognized", "verification": "verified",
                "attachment": "pending", "reason": "attachment_pending"}
        with patch.object(cli.installer, "status", return_value={"config_root": "/profile"}), \
             patch.object(cli, "_runtime_read", return_value={"task_discovery": task, "observer": {"pid": 42}}), \
             contextlib.redirect_stdout(output):
            self.assertEqual(cli.main(["status", "codex"]), 0)
        self.assertEqual(json.loads(output.getvalue()), {
            "config_root": "/profile", "runtime": {"task_discovery": task}})
