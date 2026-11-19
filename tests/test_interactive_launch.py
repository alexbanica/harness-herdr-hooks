import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from harness_herdr_hooks.launch import LaunchError, LaunchStore, classify_command, route_interactive


class ClassifierTests(unittest.TestCase):
    def test_native_modes_and_bypasses(self):
        self.assertEqual(classify_command([], herdr=True), "interactive")
        self.assertEqual(classify_command(["-p", "foo", "resume", "id"], herdr=True), "native")
        self.assertEqual(classify_command(["--", "resume", "please"], herdr=True), "interactive")
        self.assertEqual(classify_command(["-p", "resume", "make app"], herdr=True), "interactive")
        for args in (["--help"], ["--version"], ["exec", "echo hi"], ["resume", "abc"], ["app-server", "proxy"]):
            self.assertEqual(classify_command(args, herdr=True), "native")
        self.assertEqual(classify_command(["build a resume app"], herdr=True), "interactive")
        self.assertEqual(classify_command(["anything"], herdr=False), "native")
        self.assertEqual(classify_command(["anything"], herdr=True, display=True), "native")
        self.assertEqual(classify_command(["anything"], herdr=True, absolute_exec=True), "native")


class LaunchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.store = LaunchStore(self.root / "launch")

    def tearDown(self):
        self.tmp.cleanup()

    def test_payload_is_private_one_shot_and_metadata_omits_prompt(self):
        prompt = "please run `touch /tmp/should-not-run`"
        request = self.store.create([prompt], native_executable=Path("/usr/bin/codex"),
                                    cwd=self.root, profile="/profile")
        payload = self.store.claim(request)
        self.assertEqual(payload["argv"], [prompt])
        self.assertTrue((self.store.root / "payloads" / f"{request}.json").exists())
        record = json.loads((self.store.root / "records" / f"{request}.json").read_text())
        self.assertNotIn(prompt, json.dumps(record))
        with self.assertRaises(LaunchError):
            self.store.claim(request)
        self.store.acknowledge(request)
        self.assertEqual(json.loads((self.store.root / "records" / f"{request}.json").read_text())["status"], "acknowledged")
        self.assertFalse((self.store.root / "payloads" / f"{request}.json").exists())

    def test_unverified_parent_fails_before_payload_or_launch(self):
        router = Mock()
        router.verify_parent.return_value = False
        with self.assertRaises(LaunchError):
            route_interactive(["hello"], native_executable=Path("/usr/bin/codex"),
                              config_root=self.root, cwd=self.root, state_root=self.root,
                              environ={"HERDR_ENV": "1", "CODEX_THREAD_ID": "thread"}, router=router)
        router.split_and_launch.assert_not_called()

    def test_ack_timeout_does_not_retry_or_relaunch(self):
        router = Mock()
        router.verify_parent.return_value = True
        router.split_and_launch.return_value = True
        router.wait_for_ack.return_value = False
        scheduled = Mock()
        with self.assertRaises(LaunchError):
            route_interactive(["one prompt"], native_executable=Path("/usr/bin/codex"),
                              config_root=self.root, cwd=self.root, state_root=self.root,
                              environ={"HERDR_ENV": "1", "CODEX_THREAD_ID": "thread"}, router=router,
                              expiry_scheduler=scheduled)
        router.split_and_launch.assert_called_once()
        request = router.split_and_launch.call_args.args[0]
        store_root = self.root / "harness-herdr-hooks" / "launches"
        record = json.loads((store_root / "records" / f"{request}.json").read_text())
        self.assertEqual(record["status"], "failed")
        self.assertFalse((store_root / "payloads" / f"{request}.json").exists())

    def test_definitive_split_failure_removes_payload_and_never_retries(self):
        router = Mock()
        router.verify_parent.return_value = True
        router.split_and_launch.return_value = False
        scheduled = Mock()
        with self.assertRaises(LaunchError):
            route_interactive(["secret prompt"], native_executable=Path("/usr/bin/codex"),
                              config_root=self.root, cwd=self.root, state_root=self.root,
                              environ={"HERDR_ENV": "1", "CODEX_THREAD_ID": "thread"},
                              router=router, expiry_scheduler=scheduled)
        request, payload_path, _ = router.split_and_launch.call_args.args
        self.assertEqual(scheduled.call_args.args, (payload_path.parent.parent, request, 120))
        self.assertFalse(payload_path.exists())
        store_root = self.root / "harness-herdr-hooks" / "launches"
        self.assertEqual(json.loads((store_root / "records" / f"{request}.json").read_text())["status"], "failed")
        router.split_and_launch.assert_called_once()

    def test_expired_claim_is_terminal_and_deletes_prompt_payload(self):
        request = self.store.create(["secret"], native_executable=Path("/usr/bin/codex"),
                                    cwd=self.root, profile="/profile")
        record_path = self.store.root / "records" / f"{request}.json"
        record = json.loads(record_path.read_text())
        record["created_at"] -= 121
        self.store._atomic(record_path, record)
        with self.assertRaises(LaunchError):
            self.store.claim(request)
        self.assertFalse((self.store.root / "payloads" / f"{request}.json").exists())
        self.assertEqual(json.loads(record_path.read_text())["status"], "expired")
        with self.assertRaises(LaunchError):
            self.store.claim(request)

    def test_claimed_process_can_finish_once_without_overwriting_expiry_tombstone(self):
        from harness_herdr_hooks.launch import run_claimed_launch
        executable = Path(os.sys.executable).resolve()
        request = self.store.create(["prompt"], native_executable=executable,
                                    cwd=self.root, profile="/profile")
        spawn = Mock(side_effect=lambda *a, **kw: (self.store.expire(request), Mock(wait=Mock(return_value=0)))[1])
        self.assertEqual(run_claimed_launch(
            request, store=self.store,
            verify_destination=lambda rid, cwd, profile: {"HERDR_ENV": "1"},
            environ={"PATH": "/bin"}, popen=spawn), 0)
        spawn.assert_called_once()
        record_path = self.store.root / "records" / f"{request}.json"
        self.assertEqual(json.loads(record_path.read_text())["status"], "expired")
        self.assertFalse((self.store.root / "payloads" / f"{request}.json").exists())
        with self.assertRaises(LaunchError):
            run_claimed_launch(request, store=self.store,
                               verify_destination=lambda *a: {"HERDR_ENV": "1"},
                               environ={"PATH": "/bin"}, popen=Mock())

    def test_harness_state_root_precedes_xdg_for_producer_and_router(self):
        from harness_herdr_hooks.launch import main
        shim = self.root / "codex"
        shim.write_text("shim")
        native = Path(os.sys.executable).resolve()
        source = Path(__file__).resolve().parents[1]
        metadata = shim.with_name("adapter.json")
        metadata.write_text(json.dumps({"schema": 1, "source_root": str(source),
                                        "native_executable": str(native), "config_root": str(self.root)}))
        os.chmod(metadata, 0o600)
        chosen = self.root / "chosen-state"
        other = self.root / "other-state"
        router = Mock()
        router.verify_parent.return_value = True
        router.split_and_launch.return_value = False
        env = {"HERDR_ENV": "1", "CODEX_THREAD_ID": "parent",
               "HARNESS_HERDR_STATE_ROOT": str(chosen), "XDG_STATE_HOME": str(other)}
        with self.assertRaises(LaunchError):
            main(["prompt"], shim_path=shim, environ=env,
                 router_factory=lambda meta: router, execv=Mock())
        request, payload_path, cwd = router.split_and_launch.call_args.args
        self.assertEqual(payload_path, chosen / "harness-herdr-hooks" / "launches" / "payloads" / f"{request}.json")
        self.assertEqual(cwd, Path.cwd())
        self.assertFalse((other / "harness-herdr-hooks" / "launches").exists())


    def test_claimed_launch_uses_argv_without_shell_and_cleans_payload_after_spawn(self):
        executable = Path(os.sys.executable).resolve()
        request = self.store.create([], native_executable=executable, cwd=self.root, profile="/profile")
        spawn = Mock(return_value=Mock(wait=Mock(return_value=0)))
        result = __import__("harness_herdr_hooks.launch", fromlist=["run_claimed_launch"]).run_claimed_launch(
            request, store=self.store,
            verify_destination=lambda rid, cwd, profile: {"HERDR_ENV": "1", "HERDR_PANE_ID": "p2"},
            environ={"PATH": "/bin", "CODEX_THREAD_ID": "parent", "HARNESS_HERDR_DISPLAY": "1"},
            popen=spawn)
        self.assertEqual(result, 0)
        args, kwargs = spawn.call_args
        self.assertEqual(args[0], [str(executable)])
        self.assertEqual(kwargs["cwd"], str(self.root))
        self.assertEqual(kwargs["env"]["CODEX_HOME"], "/profile")
        self.assertNotIn("CODEX_THREAD_ID", kwargs["env"])
        self.assertNotIn("HARNESS_HERDR_DISPLAY", kwargs["env"])
        self.assertEqual(kwargs["env"]["HERDR_PANE_ID"], "p2")
        self.assertFalse((self.store.root / "payloads" / f"{request}.json").exists())

    def test_claimed_launch_preserves_selected_state_root_without_forwarding_environment(self):
        from harness_herdr_hooks.launch import _state_root, run_claimed_launch
        executable = Path(os.sys.executable).resolve()
        for overrides in (
            {"HARNESS_HERDR_STATE_ROOT": str(self.root / "harness-state")},
            {"XDG_STATE_HOME": str(self.root / "xdg-state")},
            ({"HARNESS_HERDR_STATE_ROOT": str(self.root / "harness-state"),
              "XDG_STATE_HOME": str(self.root / "xdg-state")}),
        ):
            with self.subTest(overrides=overrides):
                selected = Path(overrides.get("HARNESS_HERDR_STATE_ROOT") or overrides["XDG_STATE_HOME"])
                store = LaunchStore(selected / "harness-herdr-hooks" / "launches")
                request = store.create(["prompt"], native_executable=executable,
                                       cwd=self.root, profile="/profile")
                spawn = Mock(return_value=Mock(wait=Mock(return_value=0)))
                run_claimed_launch(
                    request, store=store,
                    verify_destination=lambda *a: {"HERDR_ENV": "1", "HERDR_PANE_ID": "p2"},
                    environ={"PATH": "/bin", **overrides,
                             "API_SECRET": "do-not-forward", "CODEX_THREAD_ID": "parent",
                             "HARNESS_HERDR_DISPLAY": "1"}, popen=spawn)
                child_env = spawn.call_args.kwargs["env"]
                self.assertEqual(_state_root(child_env), selected.resolve())
                self.assertEqual(child_env["HARNESS_HERDR_STATE_ROOT"], str(selected))
                if "XDG_STATE_HOME" in overrides:
                    self.assertEqual(child_env["XDG_STATE_HOME"], overrides["XDG_STATE_HOME"])
                else:
                    self.assertNotIn("XDG_STATE_HOME", child_env)
                self.assertNotIn("API_SECRET", child_env)
                self.assertNotIn("CODEX_THREAD_ID", child_env)
                self.assertNotIn("HARNESS_HERDR_DISPLAY", child_env)
                self.assertEqual(spawn.call_count, 1)

    def test_outside_and_display_bypass_router(self):
        router = Mock()
        for env in ({}, {"HERDR_ENV": "1", "HARNESS_HERDR_DISPLAY": "1"}):
            self.assertEqual(route_interactive(["hello"], native_executable=Path("/usr/bin/codex"),
                                               config_root=self.root, cwd=self.root, state_root=self.root,
                                               environ=env, router=router), "native")
        router.verify_parent.assert_not_called()


if __name__ == "__main__":
    unittest.main()
