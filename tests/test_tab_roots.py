import unittest
from pathlib import Path

from harness_herdr_hooks.adapters.codex import CodexRuntimeAdapter
from harness_herdr_hooks.adapters.opencode import OpenCodeRuntimeAdapter
from harness_herdr_hooks.model import Context, Harness, ParentBinding


def codex_context(session_id="child"):
    return Context(Harness.CODEX, "p", Path("/c"), Path("/d"), Path("/s"),
                   "/tmp/socket", session_id, "1:2:3")


def opencode_context(session_id="child"):
    return Context(Harness.OPENCODE, "p", Path("/c"), Path("/d"), Path("/s"),
                   "http://127.0.0.1:1234", session_id, "pid:44")


def native(parent, title):
    return {"parentThreadId": parent, "name": title,
            "source": {"subAgent": {"thread_spawn": {"parent_thread_id": parent}}}}


class CodexMainMetadataTests(unittest.TestCase):
    def adapter(self, rows, selected_id="child"):
        adapter = object.__new__(CodexRuntimeAdapter)
        adapter.context = codex_context(selected_id)
        adapter.proxy = type("Proxy", (), {
            "request": lambda _self, method, params: {"thread": {"id": params["threadId"], **rows[params["threadId"]]}}
        })()
        return adapter

    def binding(self, context=None):
        return ParentBinding(context or codex_context(), "server", "workspace", "tab", "pane")

    def test_nested_native_chain_resolves_original_main_and_title(self):
        adapter = self.adapter({"child": native("middle", "renamed child"),
                                "middle": native("root", "renamed nested"),
                                "root": {"name": "Main conversation", "parentThreadId": None}})
        context, title = adapter.main_metadata(self.binding())
        self.assertEqual((context.session_id, title), ("root", "Main conversation"))
        self.assertEqual((context.profile, context.backend_instance), ("p", "1:2:3"))

    def test_independent_conversation_stops_even_with_parent_metadata(self):
        for source in ("cli", "exec"):
            with self.subTest(source=source):
                adapter = self.adapter({"child": {"parentThreadId": "unrelated", "name": "Standalone",
                                                   "source": source}})
                context, title = adapter.main_metadata(self.binding())
                self.assertEqual((context.session_id, title), ("child", "Standalone"))

    def test_parent_link_requires_known_independent_source_classification(self):
        for source in (None, "unknown", "vscode", "appServer", {}, {"custom": "future"},
                       {"subAgent": {}}, {"subAgent": {"thread_spawn": {}}}):
            with self.subTest(source=source), self.assertRaises(ValueError):
                self.adapter({"child":{"parentThreadId":"root","source":source}}).main_metadata(self.binding())

    def test_malformed_subagent_marker_is_rejected_even_without_parent_link(self):
        for source in ({"subAgent": {}}, {"subAgent": "review"},
                       {"subAgent": {"unknown": {}}},
                       {"subAgent": {"thread_spawn": {"parent_thread_id": "root"}}, "unknown": {}},
                       {"subAgent": {"thread_spawn": {"parent_thread_id": "root"}, "unknown": {}}}):
            with self.subTest(source=source), self.assertRaises(ValueError):
                self.adapter({"child": {"source": source, "name": "not a root"}}).main_metadata(self.binding())

    def test_malformed_or_mismatched_native_marker_is_not_promoted_to_root(self):
        malformed = (
            {"name": "native", "source": {"subAgent": {"thread_spawn": {"parent_thread_id": "root"}}}},
            {"name": "native", "parentThreadId": "root",
             "source": {"subAgent": {"thread_spawn": {"parent_thread_id": "other"}}}},
        )
        for row in malformed:
            with self.subTest(row=row), self.assertRaises(ValueError):
                self.adapter({"child": row}).main_metadata(self.binding())

    def test_missing_title_is_none_and_child_rename_does_not_change_root_title(self):
        rows = {"child": native("root", "child title"), "root": {"name": "Root title"}}
        adapter = self.adapter(rows)
        self.assertEqual(adapter.main_metadata(self.binding())[1], "Root title")
        rows["child"]["name"] = "later child rename"
        self.assertEqual(adapter.main_metadata(self.binding())[1], "Root title")
        rows["root"]["name"] = "  "
        self.assertIsNone(adapter.main_metadata(self.binding())[1])
        rows["root"]["name"] = 42
        self.assertIsNone(adapter.main_metadata(self.binding())[1])

    def test_cycle_missing_parent_and_overdepth_fail_closed(self):
        with self.assertRaises(ValueError):
            self.adapter({"child": native("child", "x")}).main_metadata(self.binding())
        with self.assertRaises(ValueError):
            self.adapter({"child": {"parentThreadId": 7, "name": "x"}}).main_metadata(self.binding())
        with self.assertRaises(KeyError):
            self.adapter({"child": native("gone", "x")}).main_metadata(self.binding())
        rows = {f"n{i}": native(f"n{i+1}", "x") for i in range(34)}
        with self.assertRaises(ValueError):
            self.adapter(rows, "n0").main_metadata(self.binding(codex_context("n0")))

    def test_selected_context_must_match_adapter_profile_and_incarnation(self):
        for foreign in (
            Context(Harness.CODEX, "other", Path("/c"), Path("/d"), Path("/s"), "/tmp/socket", "child", "1:2:3"),
            Context(Harness.CODEX, "p", Path("/c"), Path("/d"), Path("/s"), "/tmp/other.sock", "child", "1:2:3"),
            Context(Harness.CODEX, "p", Path("/c"), Path("/d"), Path("/s"), "/tmp/socket", "child", "9:9:9"),
        ):
            with self.subTest(foreign=foreign), self.assertRaises(ValueError):
                self.adapter({"child": {"name": "x"}}).main_metadata(self.binding(foreign))


class OpenCodeMainMetadataTests(unittest.TestCase):
    def adapter(self, rows):
        adapter = object.__new__(OpenCodeRuntimeAdapter)
        adapter.context = opencode_context("adapter")
        adapter._get = lambda _route: rows[_route.rsplit("/", 1)[-1]]
        return adapter

    def binding(self, context=None):
        return ParentBinding(context or opencode_context(), "server", "workspace", "tab", "pane")

    def test_nested_chain_returns_root_identity_and_current_title(self):
        rows = {"child": {"id": "child", "parentID": "middle", "title": "child"},
                "middle": {"id": "middle", "parentID": "root", "title": "middle"},
                "root": {"id": "root", "title": "main title"}}
        context, title = self.adapter(rows).main_metadata(self.binding())
        self.assertEqual((context.session_id, title), ("root", "main title"))
        self.assertEqual((context.profile, context.backend_id, context.backend_instance),
                         ("p", "http://127.0.0.1:1234", "pid:44"))

    def test_missing_or_malformed_title_and_child_rename(self):
        rows = {"child": {"id": "child", "parentID": "root", "title": "child"},
                "root": {"id": "root", "title": "main"}}
        adapter = self.adapter(rows)
        self.assertEqual(adapter.main_metadata(self.binding())[1], "main")
        rows["child"]["title"] = "renamed child"
        self.assertEqual(adapter.main_metadata(self.binding())[1], "main")
        rows["root"]["title"] = []
        self.assertIsNone(adapter.main_metadata(self.binding())[1])
        rows["root"].pop("title")
        self.assertIsNone(adapter.main_metadata(self.binding())[1])

    def test_cycle_missing_parent_and_overdepth_fail_closed(self):
        with self.assertRaises(ValueError):
            self.adapter({"child": {"id": "child", "parentID": "child"}}).main_metadata(self.binding())
        with self.assertRaises(KeyError):
            self.adapter({"child": {"id": "child", "parentID": "gone"}}).main_metadata(self.binding())
        rows = {f"n{i}": {"id": f"n{i}", "parentID": f"n{i+1}"} for i in range(34)}
        rows["n34"] = {"id": "n34"}
        with self.assertRaises(ValueError):
            self.adapter(rows).main_metadata(self.binding(opencode_context("n0")))

    def test_foreign_context_or_mismatched_record_fails_closed(self):
        for foreign in (
            Context(Harness.OPENCODE, "other", Path("/c"), Path("/d"), Path("/s"), "http://127.0.0.1:1234", "child", "pid:44"),
            Context(Harness.OPENCODE, "p", Path("/c"), Path("/d"), Path("/s"), "http://127.0.0.1:5678", "child", "pid:44"),
            Context(Harness.OPENCODE, "p", Path("/c"), Path("/d"), Path("/s"), "http://127.0.0.1:1234", "child", "pid:55"),
        ):
            with self.subTest(foreign=foreign), self.assertRaises(ValueError):
                self.adapter({"child": {"id": "child"}}).main_metadata(self.binding(foreign))
        with self.assertRaises(ValueError):
            self.adapter({"child": {"id": "someone-else"}}).main_metadata(self.binding())


if __name__ == "__main__":
    unittest.main()
