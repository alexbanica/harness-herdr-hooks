import json
import unittest
from pathlib import Path

from harness_herdr_hooks.adapters.codex import (
    AppServerProxy, CodexRuntimeAdapter, list_turn_metadata, parse_hook,
)


def hook(name="SubagentStart", **extra):
    value = {
        "hook_event_name": name, "session_id": "child-1", "transcript_path": "/tmp/child.jsonl",
        "cwd": "/tmp", "agent_id": "child-1", "agent_type": "explorer", "turn_id": "turn-1",
    }
    value.update(extra)
    return value


class HookTests(unittest.TestCase):
    def parse(self, payload):
        return parse_hook(payload, profile="default", config_root=Path("/tmp/codex"),
                          data_root=Path("/tmp/codex"), state_root=Path("/tmp/codex"),
                          verified_backend_id="/tmp/backend.sock", verified_backend_instance="1:2:3")

    def test_child_identity_and_additional_fields_are_preserved_safely(self):
        event = self.parse({"hook_event_name":"SessionStart", "session_id":"thread",
                            "cwd":"/tmp", "transcript_path":None,
                            "secret_message":"ignored", "future_field":{"ignored":True}})
        self.assertEqual(event.identity.session_id, "thread")
        self.assertFalse(hasattr(event, "secret_message"))

    def test_stop_and_session_start_shapes(self):
        with self.assertRaisesRegex(ValueError, "unsupported"):
            self.parse(hook("SubagentStop", stop_hook_active=True, last_assistant_message="ignored"))
        start = self.parse({"hook_event_name": "SessionStart", "session_id": "parent",
                            "transcript_path": None, "cwd": "/tmp", "new_native_field": 1})
        self.assertEqual(start.identity.session_id, "parent")

    def test_old_or_unknown_hook_shapes_fail_closed(self):
        with self.assertRaises(ValueError):
            self.parse({"hook_event_name": "SubagentStart", "session_id": "parent"})
        with self.assertRaises(ValueError):
            self.parse(hook("Stop"))
        with self.assertRaises(ValueError):
            self.parse(hook(session_id=7))
        with self.assertRaises(ValueError):
            self.parse(hook("SubagentStart", agent_id="parent-session"))
        with self.assertRaises(ValueError):
            self.parse(hook("SubagentStop", stop_hook_active="false"))

    def test_legacy_subagent_events_are_rejected(self):
        for name in ("SubagentStart", "SubagentStop"):
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, "unsupported"):
                self.parse(hook(name, stop_hook_active=(name == "SubagentStop")))

    def test_initialize_accepts_known_future_unknown_and_missing_versions(self):
        for agent, expected in (
            ("codex-tui/0.170.0 (Ubuntu 24.4.0; x86_64)", "0.170.0"),
            ("codex-tui/0.171.0 (Ubuntu 24.4.0; x86_64)", "0.171.0"),
            ("codex-tui/9.99.0 (Ubuntu 24.4.0; x86_64)", "9.99.0"),
            ("codex-tui/not-a-version (Ubuntu 24.4.0; x86_64)", None),
            (None, None),
        ):
            response = {"codexHome": "/tmp"}
            if agent is not None:
                response["userAgent"] = agent
            with self.subTest(agent=agent):
                self.assertEqual(AppServerProxy._reported_version(response), expected)

    def test_request_failure_names_method_and_version_without_echoing_payload(self):
        proxy = object.__new__(AppServerProxy)
        proxy.server_version = "0.171.0"
        proxy._proc = type("Proc", (), {"stdin": object(), "stdout": object(), "poll": lambda _self: None})()
        proxy._verify_socket = lambda: None
        proxy._next_id = 0
        proxy.timeout = 1
        proxy._in_startup = False
        proxy._send_frame = lambda *_args: None
        message = "SECRET TRANSCRIPT " + "a" * 10000
        payload = json.dumps({"jsonrpc": "2.0", "id": 1, "error": {"message": message}}).encode()
        proxy._recv_message = lambda *_args: (1, payload)
        with self.assertRaisesRegex(RuntimeError, "thread/read.*0.171.0") as caught:
            proxy.request("thread/read", {"token": "SECRET"})
        diagnostic = str(caught.exception)
        self.assertNotIn("SECRET", diagnostic)
        self.assertNotIn("TRANSCRIPT", diagnostic)
        self.assertNotIn(message, diagnostic)
        self.assertLess(len(diagnostic), 160)

    def test_turn_contents_are_rejected_even_if_server_ignores_not_loaded(self):
        proxy = FakeProxy([{"data": [{"id": "turn-1", "status": "completed",
                                     "itemsView": "full", "items": [{"text": "private"}]}]}])
        with self.assertRaises(RuntimeError):
            list_turn_metadata(proxy, "child")


class FakeProxy:
    def __init__(self, pages):
        self.pages = list(pages)
        self.calls = []

    def request(self, method, params):
        self.calls.append((method, dict(params)))
        return self.pages.pop(0)


class TurnMetadataTests(unittest.TestCase):
    def test_thread_read_requests_metadata_without_turn_items(self):
        class Proxy:
            calls = []
            def request(inner, method, params):
                inner.calls.append((method, params))
                return {"thread": {"id": "child"}}
        adapter = object.__new__(CodexRuntimeAdapter)
        adapter.proxy = Proxy()
        self.assertEqual(adapter._read_thread("child"), {"id": "child"})
        self.assertEqual(Proxy.calls, [("thread/read", {"threadId": "child", "includeTurns": False})])

    def test_metadata_only_turn_pages_and_continuation_generation(self):
        proxy = FakeProxy([
            {"data": [{"id": "turn-2", "status": "inProgress", "items": []}], "nextCursor": "next"},
            {"data": [{"id": "turn-1", "status": "interrupted", "items": []}], "nextCursor": None},
        ])
        turns = list_turn_metadata(proxy, "child", page_size=10)
        self.assertEqual([(t.turn_id, t.status, t.terminal) for t in turns],
                         [("turn-2", "inProgress", False), ("turn-1", "interrupted", True)])
        self.assertEqual([call[1]["cursor"] for call in proxy.calls[1:]], ["next"])
        self.assertTrue(all(call[0] == "thread/turns/list" and call[1]["itemsView"] == "notLoaded"
                            and call[1]["threadId"] == "child" for call in proxy.calls))

    def test_cyclic_or_excessive_pages_rejected(self):
        with self.assertRaises(RuntimeError):
            list_turn_metadata(FakeProxy([{"data": [], "nextCursor": "a"},
                                          {"data": [], "nextCursor": "a"}]), "child")
        with self.assertRaises(RuntimeError):
            list_turn_metadata(FakeProxy([{"data": [], "nextCursor": "a"}]), "child", max_pages=1)


if __name__ == "__main__":
    unittest.main()
