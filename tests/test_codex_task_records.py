import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from harness_herdr_hooks.codex_task_records import (
    Cursor, TaskCreationEvent, bind_parent_file, parse_creation_record, read_new_records,
)


PARENT = "parent-123"
CHILD = "child-456"


def event_record(child=CHILD, *, parent=PARENT, cwd=None):
    answer = {"threadId": child}
    if cwd is not None:
        answer["cwd"] = cwd
    return {"type": "event_msg", "payload": {"type": "item_completed",
        "thread_id": parent, "turn_id": "turn-1", "item": {
            "type": "McpToolCall", "id": "item-1", "server": "codex_tui",
            "tool": "create_thread", "status": "completed",
            "result": {"isError": False, "content": [
                {"type": "text", "text": json.dumps(answer)}]}}}}


class TaskRecordsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.sessions = Path(self.tmp.name) / "sessions"
        self.sessions.mkdir()
        self.path = self.sessions / "parent.jsonl"
        self.path.write_text(json.dumps({"type": "session_meta", "payload": {"id": PARENT}}) + "\n")

    def test_strict_parser_and_optional_cwd_digest(self):
        line = json.dumps(event_record(cwd="/tmp/a/../b"))
        event = parse_creation_record(line, PARENT)
        self.assertEqual(event.cwd_sha256,
                         parse_creation_record(json.dumps(event_record(cwd="/tmp/b")), PARENT).cwd_sha256)
        self.assertNotEqual(event.cwd_sha256,
                            parse_creation_record(json.dumps(event_record(cwd="/b")), PARENT).cwd_sha256)
        long_cwd = "/" + "a" * 600
        self.assertIsNotNone(parse_creation_record(json.dumps(event_record(cwd=long_cwd)), PARENT))
        self.assertIsNone(parse_creation_record(json.dumps(event_record(parent="other")), PARENT))
        self.assertIsNone(parse_creation_record(json.dumps({"type": "message", "text": line}), PARENT))
        self.assertIsNone(parse_creation_record(json.dumps(event_record(child=PARENT)), PARENT))
        bad = event_record(); bad["payload"]["item"]["result"]["isError"] = True
        self.assertIsNone(parse_creation_record(json.dumps(bad), PARENT))
        self.assertIsNone(parse_creation_record('{"type":"event_msg","type":"event_msg"}', PARENT))
        conflict = event_record(); conflict["payload"]["item"]["result"]["content"].append(
            {"type": "text", "text": json.dumps({"threadId": "other-child"})})
        self.assertIsNone(parse_creation_record(json.dumps(conflict), PARENT))
        self.assertIsNone(parse_creation_record(json.dumps(event_record(cwd="relative")), PARENT))
        nested = "[" * 13 + "0" + "]" * 13
        self.assertIsNone(parse_creation_record(nested, PARENT))

    def test_identifier_bounds_and_present_null_fields_are_rejected(self):
        limit = 512
        overlong = "x" * (limit + 1)
        for field, mutate in (
            ("parent", lambda record: None),
            ("turn", lambda record: record["payload"].update(turn_id=overlong)),
            ("item", lambda record: record["payload"]["item"].update(id=overlong)),
            ("child", lambda record: record["payload"]["item"]["result"]["content"][0].update(
                text=json.dumps({"threadId": overlong}))),
        ):
            record = event_record()
            mutate(record)
            parent_id = overlong if field == "parent" else PARENT
            self.assertIsNone(parse_creation_record(json.dumps(record), parent_id), field)
        self.assertIsNone(parse_creation_record(json.dumps(event_record()), overlong))
        for answer in ({"threadId": None}, {"threadId": CHILD, "cwd": None}):
            record = event_record()
            record["payload"]["item"]["result"]["content"][0]["text"] = json.dumps(answer)
            self.assertIsNone(parse_creation_record(json.dumps(record), PARENT), answer)

    def test_content_entries_are_structurally_valid_and_unknown_fields_are_harmless(self):
        for invalid in (7, None, {"type": "text"}, {"type": "text", "text": 7}):
            record = event_record()
            record["payload"]["item"]["result"]["content"].append(invalid)
            self.assertIsNone(parse_creation_record(json.dumps(record), PARENT), invalid)
        record = event_record()
        record["payload"]["item"]["result"]["content"][0]["extra"] = "ignored"
        record["payload"]["item"]["result"]["content"].append({"type": "image", "data": "ignored"})
        record["payload"]["item"]["result"]["content"].append({"type": "x" * 600})
        self.assertEqual(parse_creation_record(json.dumps(record), PARENT).child_id, CHILD)

    def test_malformed_content_discriminators_and_text_json_are_rejected(self):
        malformed_blocks = (
            {},
            {"type": 7},
            {"type": None},
            {"type": ""},
        )
        for invalid in malformed_blocks:
            record = event_record()
            record["payload"]["item"]["result"]["content"].append(invalid)
            with self.subTest(block=invalid):
                self.assertIsNone(parse_creation_record(json.dumps(record), PARENT))

        for text in ("[]", "7", "null"):
            record = event_record()
            record["payload"]["item"]["result"]["content"].append(
                {"type": "text", "text": text})
            with self.subTest(text=text):
                self.assertIsNone(parse_creation_record(json.dumps(record), PARENT))

    def test_unbound_cwd_is_rejected_even_without_thread_id(self):
        record = event_record()
        record["payload"]["item"]["result"]["content"].append(
            {"type": "text", "text": json.dumps({"cwd": None})})
        self.assertIsNone(parse_creation_record(json.dumps(record), PARENT))

    def test_unsupported_successful_creation_has_bounded_reader_diagnostic(self):
        binding = bind_parent_file(self.path, self.sessions, PARENT)
        initial = read_new_records(binding)
        malformed = event_record()
        malformed["payload"]["item"]["result"]["content"].append(7)
        unrelated = {"type": "event_msg", "payload": {"type": "item_completed",
            "thread_id": PARENT, "item": {"type": "McpToolCall", "server": "other",
            "tool": "create_thread", "status": "completed", "id": "x",
            "result": {"isError": False, "content": [7]}}}}
        failed = event_record()
        failed["payload"]["item"]["result"]["isError"] = True
        with self.path.open("a") as stream:
            stream.write(json.dumps(malformed) + "\n")
            stream.write(json.dumps(unrelated) + "\n")
            stream.write(json.dumps(failed) + "\n")
        result = read_new_records(binding, initial.cursor)
        self.assertEqual(result.reason, "unsupported record format")
        self.assertFalse(result.events)
        self.assertNotIn("threadId", repr(result))
        with self.path.open("a") as stream:
            stream.write(json.dumps(unrelated) + "\n")
            stream.write(json.dumps(failed) + "\n")
        result = read_new_records(binding, result.cursor)
        self.assertIsNone(result.reason)

    def test_initial_boundary_partial_tail_and_serializable_cursor(self):
        binding = bind_parent_file(self.path, self.sessions, PARENT)
        initial = read_new_records(binding)
        self.assertTrue(initial.initialized)
        self.assertFalse(initial.events)
        encoded = json.dumps(event_record())
        with self.path.open("a") as stream: stream.write(encoded[:45])
        partial = read_new_records(binding, initial.cursor)
        self.assertFalse(partial.events)
        with self.path.open("a") as stream: stream.write(encoded[45:] + "\n")
        result = read_new_records(binding, partial.cursor)
        self.assertEqual(result.events, (TaskCreationEvent(PARENT, "turn-1", "item-1", CHILD),))
        self.assertEqual(Cursor.from_dict(result.cursor.to_dict()), result.cursor)
        self.assertNotIn("threadId", repr(result))

    def test_replacement_truncation_and_bounds_fail_closed(self):
        binding = bind_parent_file(self.path, self.sessions, PARENT)
        initial = read_new_records(binding)
        replacement = self.sessions / "replacement.jsonl"
        replacement.write_text(json.dumps({"type": "session_meta", "payload": {"id": PARENT}}) + "\n" +
                               json.dumps(event_record()) + "\n")
        os.replace(replacement, self.path)
        result = read_new_records(binding, initial.cursor)
        self.assertFalse(result.events)
        self.assertEqual(result.reason, "parent rollout replaced")
        current = read_new_records(binding)
        with self.path.open("a") as stream: stream.write("x" * 80)
        grown = read_new_records(binding, current.cursor)
        self.assertIsNone(grown.reason)
        self.path.write_text(json.dumps({"type": "session_meta", "payload": {"id": PARENT}}) + "\n")
        truncated = read_new_records(binding, grown.cursor)
        self.assertEqual(truncated.reason, "parent rollout truncated")
        with self.assertRaises(ValueError): read_new_records(binding, result.cursor, max_bytes=8, max_line_bytes=9)

    def test_symlink_and_foreign_session_are_rejected(self):
        link = self.sessions / "link.jsonl"
        link.symlink_to(self.path)
        with self.assertRaises((OSError, ValueError)): bind_parent_file(link, self.sessions, PARENT)
        with self.assertRaises(ValueError): bind_parent_file(self.path, self.sessions, "different")

    def test_nested_symlink_parent_and_nonregular_are_rejected(self):
        sub = self.sessions / "sub"
        sub.mkdir()
        (sub / "link.jsonl").symlink_to(self.path)
        with self.assertRaises(ValueError): bind_parent_file(sub / "link.jsonl", self.sessions, PARENT)
        with self.assertRaises(ValueError): bind_parent_file(sub, self.sessions, PARENT)

    @unittest.skipUnless(hasattr(os, "mkfifo") and os.name == "posix", "requires POSIX FIFO")
    def test_fifo_without_writer_is_rejected_without_blocking(self):
        fifo = self.sessions / "parent.fifo"
        os.mkfifo(fifo)
        code = (
            "from harness_herdr_hooks.codex_task_records import bind_parent_file; "
            f"bind_parent_file({str(fifo)!r}, {str(self.sessions)!r}, {PARENT!r})"
        )
        child = subprocess.Popen([sys.executable, "-c", code], cwd=Path(__file__).resolve().parents[1],
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            try:
                stdout, stderr = child.communicate(timeout=1.5)
            except subprocess.TimeoutExpired:
                child.kill()
                child.communicate()
                self.fail("binding a FIFO without a writer blocked beyond the watchdog")
            self.assertNotEqual(child.returncode, 0, (stdout, stderr))
            self.assertIn(b"ValueError", stderr)
        finally:
            if child.poll() is None:
                child.kill()
                child.communicate()

    def test_non_object_session_meta_fails_closed_without_leaking_descriptors(self):
        fd_dir = Path("/proc/self/fd")
        if not fd_dir.is_dir():
            self.skipTest("descriptor count requires /proc/self/fd")
        baseline = len(list(fd_dir.iterdir()))
        for malformed in ("[]", "null", '"metadata"'):
            self.path.write_text(malformed + "\n")
            with self.subTest(meta=malformed), self.assertRaises(ValueError):
                bind_parent_file(self.path, self.sessions, PARENT)
            self.assertEqual(len(list(fd_dir.iterdir())), baseline)

    def test_cursor_is_strict_and_preserves_eof_partial_skip_after_restart(self):
        binding = bind_parent_file(self.path, self.sessions, PARENT)
        # Initial observation at a non-newline EOF must skip the eventual tail.
        with self.path.open("a") as stream: stream.write('{"unfinished":')
        initial = read_new_records(binding)
        self.assertTrue(initial.cursor.skip_to_newline)
        encoded = json.dumps(event_record())
        with self.path.open("a") as stream: stream.write('null}\n' + encoded + "\n")
        result = read_new_records(binding, Cursor.from_dict(initial.cursor.to_dict()))
        self.assertEqual([event.child_id for event in result.events], [CHILD])
        invalid = initial.cursor.to_dict(); invalid["offset"] = "12"
        with self.assertRaises(ValueError): Cursor.from_dict(invalid)
        invalid = initial.cursor.to_dict(); invalid["unknown"] = 1
        with self.assertRaises(ValueError): Cursor.from_dict(invalid)

    def test_empty_complete_records_count_toward_per_read_limit(self):
        binding = bind_parent_file(self.path, self.sessions, PARENT)
        initial = read_new_records(binding)
        encoded = json.dumps(event_record())
        with self.path.open("a") as stream:
            stream.write("\n" * 256 + encoded + "\n")
        first = read_new_records(binding, initial.cursor)
        self.assertFalse(first.events)
        second = read_new_records(binding, first.cursor)
        self.assertEqual([event.child_id for event in second.events], [CHILD])

    def test_size_and_line_bounds_and_partial_resume(self):
        binding = bind_parent_file(self.path, self.sessions, PARENT)
        initial = read_new_records(binding)
        with self.path.open("a") as stream: stream.write("x" * 20)
        partial = read_new_records(binding, initial.cursor, max_bytes=32, max_line_bytes=16)
        self.assertIn("oversized", partial.reason)
        self.assertTrue(partial.cursor.skip_to_newline)
        with self.path.open("a") as stream: stream.write("\n" + json.dumps(event_record()) + "\n")
        resumed = read_new_records(binding, partial.cursor, max_bytes=1024, max_line_bytes=512)
        self.assertEqual([event.child_id for event in resumed.events], [CHILD])


if __name__ == "__main__":
    unittest.main()
