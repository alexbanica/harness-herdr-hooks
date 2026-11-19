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
        event = self.parse(hook(secret_message="ignored", future_field={"ignored": True}))
        self.assertEqual(event.identity.session_id, "child-1")
        self.assertEqual(event.agent_id, "child-1")
        self.assertEqual(event.turn_id, "turn-1")
        self.assertFalse(hasattr(event, "secret_message"))

    def test_stop_and_session_start_shapes(self):
        stop = self.parse(hook("SubagentStop", stop_hook_active=True, last_assistant_message="ignored"))
        self.assertEqual(stop.event_name, "SubagentStop")
        self.assertTrue(stop.stop_hook_active)  # continuation hint, never terminal authority
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

    def test_initialize_qualifies_native_server_version_fail_closed(self):
        self.assertEqual(AppServerProxy._qualified_version(
            {"userAgent": "codex-tui/0.170.0 (Ubuntu 24.4.0; x86_64) herdr/0.9.5 (harness-herdr-hooks; 0.1.0)",
             "codexHome": "/tmp"}), "0.170.0")
        for response in (
            {"codexHome": "/tmp"},
            {"userAgent": "codex-tui/0.169.0 (Ubuntu 24.4.0; x86_64)", "codexHome": "/tmp"},
            {"userAgent": {"version": "0.170.0"}, "codexHome": "/tmp"},
            {"userAgent": "codex-tui/not-a-version (Ubuntu 24.4.0; x86_64)", "codexHome": "/tmp"},
            {"userAgent": "codex-tui/0.170.0oops (Ubuntu 24.4.0; x86_64)", "codexHome": "/tmp"},
            {"userAgent": "codex-tui/0.170.0 (Ubuntu 24.4.0; x86_64) ignored", "codexHome": "/tmp"},
            [],
        ):
            with self.subTest(response=response), self.assertRaises(ValueError):
                AppServerProxy._qualified_version(response)

    def test_turn_contents_are_rejected_even_if_server_ignores_not_loaded(self):
        proxy = FakeProxy([{"data": [{"id": "turn-1", "status": "completed",
                                     "itemsView": "full", "items": [{"text": "private"}]}]}])
        with self.assertRaises(RuntimeError):
            list_turn_metadata(proxy, "child")

    def test_ancestry_accepts_extra_metadata_but_requires_native_parent(self):
        rows = {
            "child": {"parentThreadId": "parent", "source": {"future": 1, "subAgent": {
                "other": 2, "thread_spawn": {"parent_thread_id": "parent", "future": 3}}}},
        }
        self.assertEqual(CodexRuntimeAdapter._verified_chain("child", rows, "parent"), ("parent",))
        rows["child"]["source"]["subAgent"]["thread_spawn"]["parent_thread_id"] = "other"
        self.assertIsNone(CodexRuntimeAdapter._verified_chain("child", rows, "parent"))


class FakeProxy:
    def __init__(self, pages):
        self.pages = list(pages)
        self.calls = []

    def request(self, method, params):
        self.calls.append((method, dict(params)))
        return self.pages.pop(0)


class TurnMetadataTests(unittest.TestCase):
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
