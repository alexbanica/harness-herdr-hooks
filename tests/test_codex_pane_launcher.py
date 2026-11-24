"""Public launcher contract tests with a protocol-22 Herdr executable fake."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPT = Path(__file__).parents[1] / "skills/codex-pane/scripts/codex-pane"
THIS_FILE = Path(__file__).resolve()
THREAD = "12345678-1234-1234-1234-123456789abc"


def _fake_herdr():
    """CLI entry point executed by the temporary `herdr` wrapper."""
    args = sys.argv[2:]
    env = os.environ
    calls = Path(env["CALLS"])
    prior = [json.loads(line) for line in calls.read_text().splitlines()] if calls.exists() else []
    prior.append(args)
    calls.write_text("".join(json.dumps(call) + "\n" for call in prior))

    def ok(result):
        print(json.dumps({"id": "fixture-request", "result": result}))

    def rejected(code="fixture_rejected"):
        print(json.dumps({"error": {"code": code, "message": "fixture rejected request"}}), file=sys.stderr)
        raise SystemExit(2)

    def source_ref():
        kind = env.get("SOURCE_KIND", "id")
        value = THREAD if kind == "id" else str(Path(env["HOME"]) / f".codex/sessions/2026/11/24/rollout-2026-11-24T12-00-00-{THREAD}.jsonl")
        if env.get("SOURCE_VALUE"):
            value = env["SOURCE_VALUE"]
        reporter = env.get("SOURCE_REPORTER", "herdr:codex")
        if env.get("SOURCE_REPORTER_MISSING"):
            return {"agent": "codex", "kind": kind, "value": value}
        return {"agent": "codex", "source": reporter, "kind": kind, "value": value}

    def pane(pid, ws, tab, *, cwd=None, agent=None, session=None, focused=False):
        result = {"pane_id": pid, "workspace_id": ws, "tab_id": tab, "focused": focused,
                  "agent_status": "idle", "revision": 1}
        if cwd is not None:
            result["cwd"] = cwd
        if agent is not None:
            result["agent"] = agent
        if session is not None:
            result["agent_session"] = session
        return result

    def snapshot():
        mode = env.get("CASE", "")
        panes = [pane("source-1", "w1", "t1", agent="codex", session=source_ref(), focused=True),
                 pane("other-1", "w2", "t2", agent="codex", session={"agent": "codex", "source": "inherited", "kind": "id", "value": "foreign-thread"})]
        if mode == "forged-preexisting":
            panes.append(pane("preexisting", "w1", "t1", cwd=env.get("EXPECTED_CWD")))
        if mode == "duplicate-same-tab":
            panes.append(pane("source-2", "w1", "t1", agent="codex", session=source_ref()))
        if mode == "duplicate-cross-tab":
            panes.append(pane("source-2", "w8", "t8", agent="codex", session=source_ref()))
        # A destination appears only after split. Identity and occupancy are driven by
        # the returned ID, so tests do not bake in a particular pane identifier.
        split_calls = [c for c in prior if c[:2] == ["pane", "split"]]
        dest_id = env.get("DEST_ID", "dest-dynamic")
        if split_calls:
            if mode == "forged-preexisting":
                pass
            else:
                src = next((p for p in panes if p["pane_id"] == split_calls[-1][split_calls[-1].index("--pane") + 1]), None)
                panes.append(pane(dest_id, src["workspace_id"] if src else "w1", src["tab_id"] if src else "t1", cwd=env.get("EXPECTED_CWD"), focused=False))
        if mode == "changed-occupant" and any(c[:2] == ["agent", "start"] for c in prior):
            for p in panes:
                if p["pane_id"] == dest_id:
                    p["agent"] = "opencode"
        return {"protocol": 22, "panes": panes, "focused_pane_id": "source-1"}

    fault = env.get("FAULT", "")
    if args == ["api", "snapshot"]:
        if fault == "snapshot-reject": rejected("snapshot_denied")
        if fault == "snapshot-malformed":
            print("{malformed")
        elif fault == "snapshot-wrong":
            ok({"type": "session_snapshot", "snapshot": {"protocol": 21, "panes": []}})
        else:
            ok({"type": "session_snapshot", "snapshot": snapshot()})
    elif args[:2] == ["pane", "split"]:
        if fault == "split-reject": rejected("split_denied")
        if fault == "split-malformed":
            print("{malformed")
        elif fault == "split-wrong":
            ok({"type": "pane_info", "pane": {"pane_id": "source-1", "workspace_id": "w1", "tab_id": "t1", "focused": False}})
        elif env.get("CASE") == "forged-preexisting":
            ok({"type": "pane_info", "pane": {"pane_id": "preexisting", "workspace_id": "w1", "tab_id": "t1", "cwd": env.get("EXPECTED_CWD"), "focused": False}})
        else:
            src = args[args.index("--pane") + 1]
            ws, tab = ("w2", "t2") if src == "other-1" else ("w1", "t1")
            if env.get("CASE") == "split-placement-mismatch":
                ws, tab = "w9", "t9"
            ok({"type": "pane_info", "pane": {"pane_id": env.get("DEST_ID", "dest-dynamic"), "workspace_id": ws, "tab_id": tab,
                   "cwd": args[args.index("--cwd") + 1], "focused": False}})
    elif args[:2] == ["pane", "process-info"]:
        ok({"type": "pane_process_info", "process_info": {"pane_id": args[args.index("--pane") + 1], "shell_pid": 4102,
             "foreground_processes": [{"pid": 4102, "name": "bash", "argv0": "bash", "argv": ["bash"]}]}})
    elif args[:2] == ["agent", "start"]:
        if fault == "start-reject": rejected("start_denied")
        if fault == "start-not-ready": rejected("agent_not_ready")
        if fault == "start-malformed":
            print("{malformed")
        elif fault == "start-wrong":
            ok({"type": "agent_started", "argv": ["codex"], "agent": {"pane_id": "wrong", "interactive_ready": False}})
        else:
            pane_id = args[args.index("--pane") + 1]
            source_id = next((c[c.index("--pane") + 1] for c in prior if c[:2] == ["pane", "split"]), "source-1")
            ws, tab = ("w2", "t2") if source_id == "other-1" else ("w1", "t1")
            ok({"type": "agent_started", "argv": ["codex"], "agent": {"name": args[2], "workspace_id": ws, "tab_id": tab,
               "pane_id": pane_id, "agent": "codex", "interactive_ready": True, "agent_status": "idle"}})
    elif args[:2] == ["agent", "get"]:
        pane_id = args[2]
        if fault == "get-changed" or env.get("CASE") == "changed-occupant":
            occupant = {"name": "replacement", "workspace_id": "w1", "tab_id": "t1", "pane_id": pane_id, "agent": "opencode", "interactive_ready": False, "agent_status": "running"}
        else:
            start = next((c for c in prior if c[:2] == ["agent", "start"]), None)
            source_id = next((c[c.index("--pane") + 1] for c in prior if c[:2] == ["pane", "split"]), "source-1")
            ws, tab = ("w2", "t2") if source_id == "other-1" else ("w1", "t1")
            occupant = {"name": start[2] if start else "codex-fixture", "workspace_id": ws, "tab_id": tab, "pane_id": pane_id,
                        "agent": "codex", "interactive_ready": True, "agent_status": "idle"}
        ok({"type": "agent_info", "agent": occupant})
    elif args[:2] == ["agent", "prompt"]:
        if fault == "prompt-reject": rejected("agent_blocked")
        if fault == "prompt-timeout": rejected("timeout")
        if fault == "prompt-malformed":
            print("{malformed")
        elif fault == "prompt-wrong":
            ok({"type": "agent_prompted", "agent": {"pane_id": "wrong"}})
        else:
            start = next((c for c in prior if c[:2] == ["agent", "start"]), None)
            source_id = next((c[c.index("--pane") + 1] for c in prior if c[:2] == ["pane", "split"]), "source-1")
            ws, tab = ("w2", "t2") if source_id == "other-1" else ("w1", "t1")
            ok({"type": "agent_prompted", "agent": {"name": start[2] if start else "codex-fixture", "workspace_id": ws, "tab_id": tab, "pane_id": args[2],
               "agent": "codex", "interactive_ready": True, "agent_status": "idle"}})
    else:
        print("unexpected Herdr command: " + repr(args), file=sys.stderr)
        raise SystemExit(9)


class LauncherTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.calls = self.root / "calls.jsonl"
        self.fake = self.root / "herdr"
        self.fake.write_text(f"#!/bin/sh\nexec {sys.executable} {THIS_FILE} --fake-herdr \"$@\"\n")
        self.fake.chmod(0o755)
        self.cwd = self.root / "work"
        self.cwd.mkdir()
        self.env = dict(os.environ, PATH=str(self.root) + os.pathsep + os.environ["PATH"], HOME=str(self.root), CALLS=str(self.calls), CODEX_THREAD_ID=THREAD)

    def tearDown(self):
        self.tmp.cleanup()

    def call(self, *args, data=None, raw=False):
        self.env["EXPECTED_CWD"] = str(Path(args[args.index("--cwd") + 1]).resolve()) if "--cwd" in args else os.getcwd()
        return subprocess.run([str(SCRIPT), *args], input=data, text=not raw, capture_output=True, env=self.env)

    def calls_read(self):
        return [json.loads(line) for line in self.calls.read_text().splitlines()] if self.calls.exists() else []

    def effects(self):
        return [c for c in self.calls_read() if c[:2] in (["pane", "split"], ["agent", "start"], ["agent", "prompt"])]

    def assert_mutations(self, expected):
        self.assertEqual([c[:2] for c in self.effects()], expected)

    def test_known_native_id_and_canonical_path_exact_order_and_literal_message(self):
        for kind in ("id", "path"):
            with self.subTest(kind=kind):
                self.calls.unlink(missing_ok=True)
                self.env["SOURCE_KIND"] = kind
                self.env["DEST_ID"] = "destination-from-split"
                msg = '-literal $HOME; "quoted"\nsecond\tline\nnormal ending'
                p = self.call("--cwd", str(self.cwd), "--message-stdin", data=msg)
                self.assertEqual(p.returncode, 0, p.stderr)
                calls = self.calls_read()
                self.assert_mutations([["pane", "split"], ["agent", "start"], ["agent", "prompt"]])
                self.assertEqual(calls[0], ["api", "snapshot"])
                self.assertEqual(calls[1], ["pane", "split", "--pane", "source-1", "--direction", "right", "--cwd", str(self.cwd), "--no-focus"])
                self.assertIn(["pane", "process-info", "--pane", "destination-from-split"], calls)
                self.assertIn(["agent", "get", "destination-from-split"], calls)
                self.assertEqual(calls[-1], ["agent", "prompt", "destination-from-split", msg])
                start = next(c for c in calls if c[:2] == ["agent", "start"])
                self.assertEqual(start[1], "start")
                self.assertEqual(start[3:], ["--kind", "codex", "--pane", "destination-from-split", "--timeout", "30000"])

    def test_duplicate_matches_including_same_tab_and_stale_inherited_marker(self):
        for case in ("duplicate-same-tab", "duplicate-cross-tab"):
            with self.subTest(case=case):
                self.calls.unlink(missing_ok=True)
                self.env["CASE"] = case
                p = self.call("--cwd", str(self.cwd))
                self.assertNotEqual(p.returncode, 0)
                self.assertEqual(self.effects(), [])
        self.calls.unlink(missing_ok=True)
        self.env["CASE"] = ""
        self.env["CODEX_THREAD_ID"] = "forged"
        p = self.call("--cwd", str(self.cwd))
        self.assertNotEqual(p.returncode, 0)
        self.assertEqual(self.effects(), [])

    def test_same_thread_requires_stock_native_reporter_and_valid_timestamp(self):
        for reporter, missing, value in (("unknown:codex", False, None), ("", True, None),
                                         ("herdr:codex", False, "rollout-2026-11-24T25-00-00-12345678-1234-1234-1234-123456789abc.jsonl")):
            with self.subTest(reporter=reporter, missing=missing, value=value):
                self.calls.unlink(missing_ok=True)
                self.env["SOURCE_KIND"] = "path" if value else "id"
                self.env["SOURCE_REPORTER"] = reporter
                self.env.pop("SOURCE_REPORTER_MISSING", None)
                if missing:
                    self.env["SOURCE_REPORTER_MISSING"] = "1"
                if value:
                    self.env["SOURCE_VALUE"] = str(Path(self.env["HOME"]) / ".codex/sessions" / value)
                else:
                    self.env.pop("SOURCE_VALUE", None)
                p = self.call("--cwd", str(self.cwd))
                self.assertNotEqual(p.returncode, 0)
                self.assertEqual(self.effects(), [])
        for key in ("SOURCE_KIND", "SOURCE_REPORTER", "SOURCE_REPORTER_MISSING", "SOURCE_VALUE"):
            self.env.pop(key, None)

    def test_explicit_source_selects_other_workspace_and_validates_returned_destination(self):
        self.env["CASE"] = ""
        self.env["DEST_ID"] = "w2-destination"
        p = self.call("--pane", "other-1", "--cwd", str(self.cwd))
        self.assertEqual(p.returncode, 0, p.stderr)
        calls = self.calls_read()
        self.assertEqual(calls[1][3], "other-1")
        start = next(c for c in calls if c[:2] == ["agent", "start"])
        self.assertEqual(start[start.index("--pane") + 1], "w2-destination")

    def test_invalid_or_forged_split_ack_never_starts_codex(self):
        for fault, case in (("split-reject", ""), ("split-malformed", ""), ("split-wrong", ""), ("", "forged-preexisting")):
            with self.subTest(fault=fault, case=case):
                self.calls.unlink(missing_ok=True)
                self.env["FAULT"] = fault
                self.env["CASE"] = case
                p = self.call("--cwd", str(self.cwd))
                self.assertNotEqual(p.returncode, 0)
                self.assert_mutations([["pane", "split"]])
                self.assertFalse(any(c[:2] == ["agent", "start"] for c in self.calls_read()))

    def test_snapshot_failures_and_missing_thread_have_no_effect(self):
        for fault in ("snapshot-reject", "snapshot-malformed", "snapshot-wrong"):
            with self.subTest(fault=fault):
                self.calls.unlink(missing_ok=True)
                self.env["FAULT"] = fault
                p = self.call("--cwd", str(self.cwd))
                self.assertNotEqual(p.returncode, 0)
                self.assertEqual(self.effects(), [])
        self.env.pop("FAULT", None)
        self.env.pop("CODEX_THREAD_ID", None)
        self.calls.unlink(missing_ok=True)
        p = self.call("--cwd", str(self.cwd))
        self.assertNotEqual(p.returncode, 0)
        self.assertEqual(self.effects(), [])

    def test_message_preflight_rejects_unrepresentable_text_before_any_herdr_call(self):
        cases = [("", False), ("  \n", False), (" leading", False), ("trailing ", False), ("line\r\n", False),
                 (b"\xff", True), (b"hello\0world", True), ("!printf QA", False), ("/status", False), ("/unknownword", False),
                 (b"\x1b", True), (b"\x7f", True), (b"\xc2\x85", True), (b"line1\r\nline2", True)]
        for data, raw in cases:
            with self.subTest(data=data):
                self.calls.unlink(missing_ok=True)
                p = self.call("--message-stdin", "--cwd", str(self.cwd), data=data, raw=raw)
                self.assertNotEqual(p.returncode, 0)
                self.assertEqual(self.calls_read(), [])

    def test_oversized_stdin_is_rejected_before_any_herdr_call(self):
        p = self.call("--message-stdin", "--cwd", str(self.cwd), data=b"x" * (32 * 4096), raw=True)
        self.assertNotEqual(p.returncode, 0)
        self.assertEqual(self.calls_read(), [])

    def test_split_placement_mismatch_reports_actual_and_never_starts(self):
        self.env["CASE"] = "split-placement-mismatch"
        result = self.call("--cwd", str(self.cwd))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("expected workspace 'w1', tab 't1'", result.stderr)
        self.assertIn("current exact-pane placement is workspace 'w1', tab 't1'", result.stderr)
        self.assert_mutations([["pane", "split"]])

    def test_idle_session_does_not_prompt_and_uses_default_cwd(self):
        p = self.call()
        self.assertEqual(p.returncode, 0, p.stderr)
        calls = self.calls_read()
        self.assertEqual([c[:2] for c in self.effects()], [["pane", "split"], ["agent", "start"]])
        self.assertFalse(any(c[:2] == ["agent", "prompt"] for c in calls))
        split = next(c for c in calls if c[:2] == ["pane", "split"])
        self.assertEqual(split[split.index("--cwd") + 1], str(Path.cwd().resolve()))
        self.assertIn("omitted", p.stdout.lower())

    def test_structured_rejection_and_malformed_unknown_have_no_duplicate_mutations(self):
        for fault, expected in (("start-reject", [["pane", "split"], ["agent", "start"]]),
                                ("start-not-ready", [["pane", "split"], ["agent", "start"]]),
                                ("start-malformed", [["pane", "split"], ["agent", "start"]]),
                                ("prompt-reject", [["pane", "split"], ["agent", "start"], ["agent", "prompt"]]),
                                ("prompt-malformed", [["pane", "split"], ["agent", "start"], ["agent", "prompt"]])):
            with self.subTest(fault=fault):
                self.calls.unlink(missing_ok=True)
                self.env["FAULT"] = fault
                p = self.call("--cwd", str(self.cwd), "--message-stdin", data="safe literal")
                self.assertNotEqual(p.returncode, 0)
                self.assertEqual([c[:2] for c in self.effects()], expected)
                calls = self.calls_read()
                for effect in ("split", "start", "prompt"):
                    self.assertLessEqual(sum(c[:2] == ["pane", effect] for c in calls), 1)
                    self.assertLessEqual(sum(c[:2] == ["agent", effect] for c in calls), 1)
                # Recovery after uncertain start/prompt is read-only.
                mutation_indices = [i for i, c in enumerate(calls) if c[:2] in (["pane", "split"], ["agent", "start"], ["agent", "prompt"])]
                self.assertEqual([calls[i][:2] for i in mutation_indices], [c[:2] for c in expected])
                if "reject" in fault or fault == "start-not-ready":
                    self.assertIn("agent_blocked" if fault == "prompt-reject" else "agent_not_ready" if fault == "start-not-ready" else "start_denied", p.stderr)
                if fault == "prompt-malformed":
                    self.assertIn("unknown", p.stderr.lower())
                    self.assertTrue(any(c[:2] == ["agent", "get"] for c in calls))
                    self.assertGreaterEqual(sum(c[:2] == ["api", "snapshot"] for c in calls), 3)

    def test_start_ack_identity_and_current_occupant_are_verified_before_prompt(self):
        for fault, case in (("start-wrong", ""), ("", "changed-occupant")):
            with self.subTest(fault=fault, case=case):
                self.calls.unlink(missing_ok=True)
                self.env["FAULT"] = fault
                self.env["CASE"] = case
                p = self.call("--cwd", str(self.cwd), "--message-stdin", data="safe literal")
                self.assertNotEqual(p.returncode, 0)
                self.assert_mutations([["pane", "split"], ["agent", "start"]])
                self.assertFalse(any(c[:2] == ["agent", "prompt"] for c in self.calls_read()))
                self.assertIn("dest-dynamic", p.stderr)

    def test_reported_prompt_timeout_preserves_destination_and_only_inspects_afterward(self):
        self.env["FAULT"] = "prompt-timeout"
        result = self.call("--message-stdin", data="literal message")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("unknown", result.stderr)
        self.assertIn("dest-dynamic", result.stderr)
        self.assert_mutations([["pane", "split"], ["agent", "start"], ["agent", "prompt"]])
        calls = self.calls_read()
        prompt = next(i for i, call in enumerate(calls) if call[:2] == ["agent", "prompt"])
        self.assertIn(["api", "snapshot"], calls[prompt + 1:])

    def test_absolute_path_text_is_transmitted_verbatim(self):
        message = "/tmp/qa-literal-path Reply only OK."
        result = self.call("--message-stdin", data=message)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.effects()[-1], ["agent", "prompt", "dest-dynamic", message])

    def test_unusable_directory_is_rejected_before_split(self):
        result = self.call("--cwd", str(self.root / "missing"))
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.effects(), [])

    def test_prompt_ack_identity_verified_and_never_retried(self):
        self.env["FAULT"] = "prompt-wrong"
        p = self.call("--cwd", str(self.cwd), "--message-stdin", data="safe literal")
        self.assertNotEqual(p.returncode, 0)
        self.assert_mutations([["pane", "split"], ["agent", "start"], ["agent", "prompt"]])


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--fake-herdr":
        _fake_herdr()
    else:
        unittest.main()
