import io
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from harness_herdr_hooks import cli
from harness_herdr_hooks.model import Context, Harness, ParentBinding, parent_to_dict


class RuntimeStatusTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "state"
        self.profile = Path(self.tmp.name) / "profile"
        self.profile.mkdir()
        context = Context(Harness.CODEX, str(self.profile), self.profile, self.profile,
                          self.profile, "/private/socket", "thread", "backend-instance")
        self.parent = ParentBinding(context, "server-id", "workspace", "tab", "pane")

    def tearDown(self):
        self.tmp.cleanup()

    def test_absent_status_is_unknown_and_does_not_create_state(self):
        self.assertEqual(cli._runtime_status(self.root, str(self.profile)), {
            "native_hook_loading": "unknown", "last_verified_binding": "unknown", "observer": "unknown",
            "task_discovery": {"recognition": "unknown", "verification": "unknown", "attachment": "unknown"},
            "attachment": {"known": False, "observed_counts": {}},
            "cleanup": {"known": False, "outcomes": {}}, "ownership": {"known": False, "counts": {}},
        })
        self.assertFalse(self.root.exists())

    def test_task_discovery_status_is_bounded_and_retained(self):
        cli._runtime_write(self.root, str(self.profile), lambda d: d.update(task_discovery={
            "recognition": "recognized", "verification": "verified",
            "attachment": "pending", "reason": "attachment_pending", "raw": "discard"}))
        status = cli._runtime_status(self.root, str(self.profile))["task_discovery"]
        self.assertEqual(status, {"recognition": "recognized", "verification": "verified",
                                  "attachment": "pending", "reason": "attachment_pending"})
        cli._runtime_write(self.root, str(self.profile), lambda d: d.update(task_discovery={
            "recognition": "unknown", "verification": "unknown", "attachment": "unknown"}))
        self.assertEqual(cli._runtime_status(self.root, str(self.profile))["task_discovery"], {
            "recognition": "unknown", "verification": "unknown", "attachment": "unknown"})

    def test_unsupported_creation_envelope_reason_survives_bounded_status(self):
        cli._runtime_write(self.root, str(self.profile), lambda d: d.update(task_discovery={
            "recognition": "recognized", "verification": "unknown",
            "attachment": "unknown", "reason": "unsupported_envelope",
            "raw": "discard"}))
        self.assertEqual(cli._runtime_status(self.root, str(self.profile))["task_discovery"], {
            "recognition": "recognized", "verification": "unknown",
            "attachment": "unknown", "reason": "unsupported_envelope"})

    def test_pending_limit_reason_survives_without_exposing_untrusted_text(self):
        cli._runtime_write(self.root, str(self.profile), lambda d: d.update(task_discovery={
            "recognition": "recognized", "verification": "pending",
            "attachment": "unknown", "reason": "pending_limit",
            "current_health": {"state": "deferred", "reason": "pending_limit"},
            "raw": "private event payload"}))
        task = cli._runtime_status(self.root, str(self.profile))["task_discovery"]
        self.assertEqual(task, {"recognition": "recognized", "verification": "pending",
                                "attachment": "unknown", "reason": "pending_limit",
                                "current_health": {"state": "deferred", "reason": "pending_limit"}})
        cli._runtime_write(self.root, str(self.profile), lambda d: d.update(task_discovery={
            "recognition": "recognized", "verification": "pending",
            "attachment": "unknown", "reason": "private event payload",
            "current_health": {"state": "deferred", "reason": "private event payload"}}))
        task = cli._runtime_status(self.root, str(self.profile))["task_discovery"]
        self.assertNotIn("reason", task)
        self.assertEqual(task["current_health"], {"state": "deferred"})

    def test_current_task_failure_replaces_stale_success_and_exposes_only_reason_code(self):
        adapter = object.__new__(__import__("harness_herdr_hooks.adapters.codex", fromlist=["CodexRuntimeAdapter"]).CodexRuntimeAdapter)
        adapter.context = type("C", (), {"profile": str(self.profile)})()
        adapter.task_store_root = self.root
        adapter._standalone_status("recognized", "verified", "attached")
        adapter._standalone_status("deferred", "deferred", "unknown", "unsafe_parent_file")
        task = cli._runtime_status(self.root, str(self.profile))["task_discovery"]
        self.assertEqual(task, {"recognition": "recognized", "verification": "verified",
                                "attachment": "attached", "reason": "unsafe_parent_file",
                                "current_health": {"state": "deferred", "reason": "unsafe_parent_file"}})
        self.assertNotIn("exception", json.dumps(task))
        adapter._standalone_status("observing", "unknown", "unknown")
        self.assertEqual(cli._runtime_status(self.root, str(self.profile))["task_discovery"], {
            "recognition": "recognized", "verification": "verified", "attachment": "attached",
            "reason": "unsafe_parent_file", "current_health": {"state": "healthy"}})

    def test_verified_codex_hook_records_bounded_profile_evidence(self):
        env = {"HERDR_ENV": "1", "HERDR_SOCKET_PATH": "/private/socket",
               "HERDR_PANE_ID": "pane", "HERDR_TAB_ID": "tab",
               "HERDR_WORKSPACE_ID": "workspace"}
        with patch.dict(os.environ, env, clear=False), \
             patch("harness_herdr_hooks.cli._state_root", return_value=self.root), \
             patch("harness_herdr_hooks.cli._herdr_client"), \
             patch("harness_herdr_hooks.cli._parent_from_event", return_value=(self.parent, 42, self.profile, None)), \
             patch("harness_herdr_hooks.cli._start_observer"), \
             patch("sys.stdin", io.TextIOWrapper(io.BytesIO(b'{"hook_event_name":"SessionStart"}'))):
            self.assertEqual(cli.main(["codex-hook"]), 0)
        status = cli._runtime_status(self.root, str(self.profile))
        self.assertEqual(status["native_hook_loading"], "observed")
        self.assertEqual(status["last_verified_binding"]["backend_instance"], "backend-instance")
        record = json.loads(cli._runtime_path(self.root, str(self.profile)).read_text())
        self.assertEqual(record["hook"]["backend_instance"], "backend-instance")
        self.assertNotIn("payload", record)
        self.assertNotIn("argv", record)

    def test_synthetic_router_verification_does_not_claim_hook_observed(self):
        router = cli._HerdrLaunchRouter({"config_root": str(self.profile)})
        router.client = object()
        with patch("harness_herdr_hooks.cli._herdr_client", return_value=router.client), \
             patch("harness_herdr_hooks.cli._parent_from_event", return_value=(self.parent, 42, self.profile, None)):
            self.assertTrue(router.verify_parent("thread", str(self.profile), self.profile))
        self.assertEqual(cli._runtime_status(self.root, str(self.profile))["native_hook_loading"], "unknown")

    def test_stale_observer_pid_is_ended(self):
        cli._runtime_write(self.root, str(self.profile), lambda d: d.update(
            observer={"state": "running", "pid": 99999999, "pin": {"start_ticks": 1, "exe": "/x", "uid": os.getuid()}}))
        self.assertEqual(cli._runtime_status(self.root, str(self.profile))["observer"], "unknown")

    def test_observer_requires_matching_loaded_revision_and_command(self):
        record={"state":"running","pid":42,"pin":{"start_ticks":1,"exe":"/python","uid":os.getuid()},
                "source_sha256":cli._LOADED_SOURCE_SHA256,"binding_id":"binding"}
        cli._runtime_write(self.root,str(self.profile),lambda d:d.update(observer=record))
        with patch.object(cli,"_process_pin",return_value=record["pin"]), \
             patch.object(cli,"_observer_command_matches",return_value=True):
            self.assertEqual(cli._runtime_status(self.root,str(self.profile))["observer"],"running")
        record["source_sha256"]="old-revision"
        cli._runtime_write(self.root,str(self.profile),lambda d:d.update(observer=record))
        with patch.object(cli,"_process_pin",return_value=record["pin"]), \
             patch.object(cli,"_observer_command_matches",return_value=True):
            self.assertEqual(cli._runtime_status(self.root,str(self.profile))["observer"],"stale")

    def test_retirement_requires_announcement_exact_parent_and_command(self):
        binding=self.parent.context.key()[:64]
        observer={"state":"running","pid":42,"pin":{"start_ticks":1,"exe":"/python","uid":os.getuid()},
                  "server_id":"server-id","pane_id":"pane","binding_id":binding,
                  "context_key":self.parent.context.key(),"source_path":"/repo/src/harness_herdr_hooks",
                  "source_root":"/repo/src","source_sha256":"old"}
        cli._runtime_write(self.root,str(self.profile),lambda d:d.update(observer=observer))
        record={"parent":parent_to_dict(self.parent),"entrypoint":"/repo/bin/harness-herdr-hooks"}
        kill=__import__("unittest.mock",fromlist=["Mock"]).Mock()
        with patch("harness_herdr_hooks.cli.load_existing_binding",return_value=record), \
             patch.object(cli,"_process_pin",side_effect=[observer["pin"],None]), \
             patch.object(cli,"_observer_command_matches",return_value=True):
            self.assertEqual(cli._retire_observer(self.root,str(self.profile),self.parent,announced=False,kill=kill),"announcement-required")
            self.assertEqual(cli._retire_observer(self.root,str(self.profile),self.parent,announced=True,kill=kill),"ended")
        kill.assert_called_once_with(42,cli.signal.SIGTERM)

    def test_retirement_never_signals_foreign_or_unverified_command(self):
        binding=self.parent.context.key()[:64]
        observer={"state":"running","pid":42,"pin":{"start_ticks":1,"exe":"/python","uid":os.getuid()},
                  "server_id":"server-id","pane_id":"another-pane","binding_id":binding,
                  "context_key":self.parent.context.key()}
        cli._runtime_write(self.root,str(self.profile),lambda d:d.update(observer=observer))
        kill=__import__("unittest.mock",fromlist=["Mock"]).Mock()
        self.assertEqual(cli._retire_observer(self.root,str(self.profile),self.parent,announced=True,kill=kill),"foreign-or-ambiguous")
        self.assertFalse(kill.called)

    def test_old_observer_end_cannot_replace_newer_owner(self):
        newer = {"state": "running", "pid": 123, "pin": {"start_ticks": 4, "exe": "/new", "uid": os.getuid()}}
        cli._runtime_write(self.root, str(self.profile), lambda d: d.update(observer=newer))
        original_pid = os.getpid
        try:
            os.getpid = lambda: 456
            cli._publish_observer(self.root, self.parent, "ended",
                                  {"start_ticks": 3, "exe": "/old", "uid": os.getuid()})
        finally:
            os.getpid = original_pid
        self.assertEqual(cli._runtime_read(cli._runtime_path(self.root, str(self.profile)))["observer"], newer)

    def test_stale_dead_observer_is_replaced_by_new_lock_owner(self):
        cli._runtime_write(self.root, str(self.profile), lambda d: d.update(observer={
            "state": "running", "pid": 2147483647,
            "pin": {"start_ticks": 1, "exe": "/gone", "uid": os.getuid()}}))
        pin = cli._process_pin(os.getpid())
        self.assertIsNotNone(pin)
        cli._publish_observer(self.root, self.parent, "running", pin)
        observer = cli._runtime_read(cli._runtime_path(self.root, str(self.profile)))["observer"]
        self.assertEqual(observer["pid"], os.getpid())
        self.assertEqual(observer["pin"], pin)

    def test_real_module_launcher_environment_matches_published_source_root(self):
        source_root = str(cli._PACKAGE_ROOT)
        binding_id = self.parent.context.key()[:64]
        isolated = self.root / "isolated"; isolated.mkdir(parents=True)
        env = {**os.environ, "PYTHONPATH": source_root,
               "HARNESS_HERDR_STATE_ROOT": str(isolated), "XDG_STATE_HOME": str(isolated)}
        process = subprocess.Popen([sys.executable, "-m", "harness_herdr_hooks", "observe", binding_id],
                                   env=env, cwd=str(isolated), stdout=subprocess.DEVNULL,
                                   stderr=subprocess.DEVNULL, start_new_session=True)
        matched = False
        try:
            deadline = time.monotonic() + 1.0
            while time.monotonic() < deadline and process.poll() is None:
                pin = cli._process_pin(process.pid)
                if pin:
                    # Exercise the production publisher so the matcher consumes
                    # its effective source_root, rather than a test-computed value.
                    with patch.object(cli.os, "getpid", return_value=process.pid):
                        cli._publish_observer(self.root, self.parent, "running", pin)
                    record = cli._runtime_read(cli._runtime_path(self.root, str(self.profile)))
                    observer = record.get("observer", {})
                else:
                    observer = {}
                if observer.get("pin") and cli._observer_command_matches(process.pid, observer):
                    matched = True
                    break
                time.sleep(0.005)
        finally:
            if process.poll() is None:
                process.terminate()
            process.wait(timeout=2)
        self.assertTrue(matched, "actual module launcher argv/PYTHONPATH did not match source root")

    def test_lifecycle_outcomes_do_not_claim_cleanup_success(self):
        cli._record_hook(self.root, self.parent)
        self.assertEqual(cli._runtime_status(self.root, str(self.profile))["cleanup"],
                         {"known": False, "outcomes": {}})

    def test_cleanup_counts_only_explicit_confirmed_close_records_read_only(self):
        cli._record_hook(self.root, self.parent)
        namespace = self.parent.context.key()[:32]
        state_dir = self.root / "harness-herdr-hooks" / namespace
        state_dir.mkdir(mode=0o700, parents=True)
        state_path = state_dir / "state.json"
        state_path.write_text(json.dumps({"schema": 2, "records": {
            "closed": {"cleanup": {"outcome": "closed", "generation": "t1"}},
            "failed": {"status": "finished"},
            "reused": {"cleanup": {"outcome": "reused"}},
            "retained": {"cleanup": {"outcome": "retained-unverified"}},
            "manual": {"cleanup": {"outcome": "manual-close"}},
            "unknown": {"cleanup": {"outcome": "unknown"}},
        }}))
        os.chmod(state_path, 0o600)
        before = state_path.read_bytes()
        self.assertEqual(cli._runtime_status(self.root, str(self.profile))["cleanup"], {
            "known": True, "outcomes": {"closed": 1, "manual-close": 1,
                                         "retained-unverified": 1, "reused": 1, "unknown": 1}})
        self.assertEqual(state_path.read_bytes(), before)

    def test_corrupt_or_oversized_runtime_record_is_unknown(self):
        path = cli._runtime_path(self.root, str(self.profile))
        path.parent.mkdir(mode=0o700, parents=True)
        path.write_text("x" * (cli._RUNTIME_MAX_BYTES + 1))
        os.chmod(path, 0o600)
        self.assertEqual(cli._runtime_status(self.root, str(self.profile))["native_hook_loading"], "unknown")


if __name__ == "__main__":
    unittest.main()
