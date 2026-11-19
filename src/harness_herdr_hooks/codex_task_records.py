"""Strict, bounded reader for qualified Codex task-creation rollout records.

Only identifiers and an optional normalized cwd digest leave this module; no
transcript text is returned or retained in cursor state.
"""

from __future__ import annotations

import hashlib
import json
import os
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any


DEFAULT_MAX_BYTES = 1024 * 1024
DEFAULT_MAX_LINE_BYTES = 1024 * 1024
DEFAULT_MAX_RECORDS = 256
MAX_JSON_DEPTH = 12
MAX_IDENTIFIER_LENGTH = 512


@dataclass(frozen=True)
class TaskCreationEvent:
    parent_id: str
    turn_id: str
    item_id: str
    child_id: str
    cwd_sha256: str | None = None


@dataclass(frozen=True)
class ParentFileBinding:
    path: str
    sessions_dir: str
    parent_id: str
    owner_uid: int


@dataclass(frozen=True)
class Cursor:
    device: int
    inode: int
    offset: int
    parent_id: str
    path: str
    observed_size: int
    skip_to_newline: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {"device": self.device, "inode": self.inode, "offset": self.offset,
                "parent_id": self.parent_id, "path": self.path,
                "observed_size": self.observed_size,
                "skip_to_newline": self.skip_to_newline}

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "Cursor":
        if not isinstance(value, dict):
            raise ValueError("invalid cursor")
        try:
            required = {"device", "inode", "offset", "observed_size", "parent_id", "path"}
            allowed = required | {"skip_to_newline"}
            if not required.issubset(value) or not set(value).issubset(allowed):
                raise ValueError("invalid cursor fields")
            keys = ("device", "inode", "offset", "observed_size")
            if any(not isinstance(value[k], int) or isinstance(value[k], bool) for k in keys):
                raise ValueError("invalid cursor integers")
            if not isinstance(value.get("skip_to_newline", False), bool):
                raise ValueError("invalid cursor flag")
            if not isinstance(value["parent_id"], str) or not isinstance(value["path"], str):
                raise ValueError("invalid cursor identity")
            result = cls(value["device"], value["inode"], value["offset"],
                         value["parent_id"], value["path"], value["observed_size"],
                         value.get("skip_to_newline", False))
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("invalid cursor") from exc
        if (result.device < 0 or result.inode < 0 or result.offset < 0 or
                result.observed_size < result.offset or not result.parent_id or
                not os.path.isabs(result.path)):
            raise ValueError("invalid cursor bounds")
        return result


@dataclass(frozen=True)
class ReadResult:
    cursor: Cursor
    events: tuple[TaskCreationEvent, ...]
    initialized: bool = False
    reason: str | None = None


def _object_no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    obj: dict[str, Any] = {}
    for key, value in pairs:
        if key in obj:
            raise ValueError("duplicate JSON key")
        obj[key] = value
    return obj


def _decode(text: str) -> Any:
    try:
        value = json.loads(text, object_pairs_hook=_object_no_duplicates)
    except RecursionError as exc:
        raise ValueError("JSON nesting exceeds parser bound") from exc
    def depth(node: Any, level: int) -> None:
        if level > MAX_JSON_DEPTH:
            raise ValueError("JSON nesting exceeds bound")
        if isinstance(node, dict):
            for child in node.values(): depth(child, level + 1)
        elif isinstance(node, list):
            for child in node: depth(child, level + 1)
    depth(value, 0)
    return value


def _nonempty(value: Any) -> bool:
    return (isinstance(value, str) and bool(value.strip()) and
            len(value) <= MAX_IDENTIFIER_LENGTH)


def _cwd_digest(value: Any) -> str | None:
    # cwd is transient and is reduced to a digest; the identifier length bound
    # applies to IDs, not to a valid absolute path.
    if not isinstance(value, str) or not value.strip():
        raise ValueError("invalid cwd")
    if not os.path.isabs(value):
        raise ValueError("cwd must be absolute")
    normalized = os.path.normpath(value)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def parse_creation_record(line: str | bytes, parent_id: str) -> TaskCreationEvent | None:
    """Return a sanitized event iff one exact qualified completion is present."""
    try:
        if not _nonempty(parent_id):
            return None
        if isinstance(line, bytes):
            line = line.decode("utf-8")
        record = _decode(line)
        if not isinstance(record, dict) or record.get("type") != "event_msg":
            return None
        payload = record.get("payload")
        if not isinstance(payload, dict) or payload.get("type") != "item_completed":
            return None
        item = payload.get("item")
        if (not _nonempty(payload.get("thread_id")) or payload.get("thread_id") != parent_id or
                not _nonempty(payload.get("turn_id")) or
                not isinstance(item, dict) or item.get("type") != "McpToolCall" or
                item.get("server") != "codex_tui" or item.get("tool") != "create_thread" or
                item.get("status") != "completed" or not _nonempty(item.get("id"))):
            return None
        result = item.get("result")
        if not isinstance(result, dict) or result.get("isError") is not False:
            return None
        content = result.get("content")
        if not isinstance(content, list):
            return None
        child_ids: set[str] = set()
        cwd_hashes: set[str | None] = set()
        for block in content:
            if not isinstance(block, dict):
                return None
            block_type = block.get("type")
            if block_type != "text":
                # Ignore extension blocks only when their discriminator is a
                # usable string. Missing or malformed discriminators are not
                # safely distinguishable from truncated known content.
                if not isinstance(block_type, str) or not block_type.strip():
                    return None
                continue
            if not isinstance(block.get("text"), str):
                return None
            decoded = _decode(block["text"])
            if not isinstance(decoded, dict):
                return None
            if "threadId" not in decoded:
                # A cwd without an associated child cannot be bound to this
                # event and must not bypass cwd validation.
                if "cwd" in decoded:
                    return None
                continue
            child = decoded["threadId"]
            if not _nonempty(child):
                return None
            child_ids.add(child)
            if "cwd" in decoded:
                cwd_hashes.add(_cwd_digest(decoded["cwd"]))
        if len(child_ids) != 1 or len(cwd_hashes) > 1:
            return None
        child_id = next(iter(child_ids))
        if child_id == parent_id:
            return None
        cwd_hash = next(iter(cwd_hashes)) if cwd_hashes else None
        return TaskCreationEvent(parent_id, payload["turn_id"], item["id"], child_id, cwd_hash)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError, TypeError):
        return None


def _is_unsupported_creation_candidate(line: bytes, parent_id: str) -> bool:
    """Identify only successful create_thread completions rejected by our schema."""
    try:
        record = _decode(line.decode("utf-8"))
        payload = record.get("payload") if isinstance(record, dict) else None
        item = payload.get("item") if isinstance(payload, dict) else None
        result = item.get("result") if isinstance(item, dict) else None
        return (isinstance(record, dict) and record.get("type") == "event_msg" and
                isinstance(payload, dict) and payload.get("type") == "item_completed" and
                payload.get("thread_id") == parent_id and isinstance(item, dict) and
                item.get("type") == "McpToolCall" and item.get("server") == "codex_tui" and
                item.get("tool") == "create_thread" and item.get("status") == "completed" and
                isinstance(result, dict) and
                result.get("isError") is False)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError, TypeError):
        return False


def _open_verified(binding: ParentFileBinding) -> tuple[int, os.stat_result]:
    sessions = Path(binding.sessions_dir).resolve(strict=True)
    path = Path(binding.path)
    if not path.is_absolute() or not path.is_relative_to(sessions):
        raise ValueError("parent rollout is outside selected sessions directory")
    relative = path.relative_to(sessions)
    if not relative.parts:
        raise ValueError("parent rollout path is invalid")
    directory_flags = (os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) |
                       getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0))
    # O_NONBLOCK ensures an unexpected FIFO cannot stall before fstat rejects
    # the final component as non-regular. It has no effect on regular files.
    flags = (os.O_RDONLY | getattr(os, "O_NONBLOCK", 0) |
             getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0))
    root_fd = os.open(sessions, directory_flags)
    parent_fd = root_fd
    try:
        for component in relative.parts[:-1]:
            next_fd = os.open(component, directory_flags, dir_fd=parent_fd)
            if parent_fd != root_fd:
                os.close(parent_fd)
            parent_fd = next_fd
        fd = os.open(relative.parts[-1], flags, dir_fd=parent_fd)
    except OSError as exc:
        raise ValueError("parent rollout path contains an unsafe or missing component") from exc
    finally:
        if parent_fd != root_fd:
            os.close(parent_fd)
        os.close(root_fd)
    info = os.fstat(fd)
    if not stat.S_ISREG(info.st_mode) or info.st_uid != binding.owner_uid:
        os.close(fd)
        raise ValueError("parent rollout identity or ownership rejected")
    try:
        with os.fdopen(os.dup(fd), "rb") as stream:
            header = stream.readline(DEFAULT_MAX_LINE_BYTES + 1)
        if len(header) > DEFAULT_MAX_LINE_BYTES:
            raise ValueError("parent rollout header exceeds bound")
        try:
            meta = _decode(header.decode("utf-8"))
            identity = (meta["payload"]["id"]
                        if isinstance(meta, dict) and meta.get("type") == "session_meta"
                        else None)
        except (UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError, ValueError):
            identity = None
        if identity != binding.parent_id:
            raise ValueError("parent rollout session identity mismatch")
    except BaseException:
        os.close(fd)
        raise
    return fd, info


def bind_parent_file(path: str | os.PathLike[str], sessions_dir: str | os.PathLike[str],
                     parent_id: str, owner_uid: int | None = None) -> ParentFileBinding:
    binding = ParentFileBinding(str(Path(os.path.abspath(path))),
                                str(Path(sessions_dir).resolve(strict=True)), parent_id,
                                os.getuid() if owner_uid is None else owner_uid)
    fd, _ = _open_verified(binding)
    os.close(fd)
    return binding


def _empty_cursor(binding: ParentFileBinding, info: os.stat_result, offset: int,
                  reason: str | None = None, initialized: bool = False,
                  skip: bool = False) -> ReadResult:
    cursor = Cursor(info.st_dev, info.st_ino, offset, binding.parent_id, binding.path,
                    info.st_size, skip)
    return ReadResult(cursor, (), initialized, reason)


def _eof_is_partial(fd: int, size: int) -> bool:
    if size <= 0:
        return False
    os.lseek(fd, size - 1, os.SEEK_SET)
    return os.read(fd, 1) != b"\n"


def read_new_records(binding: ParentFileBinding, cursor: Cursor | dict[str, Any] | None = None,
                     *, max_bytes: int = DEFAULT_MAX_BYTES,
                     max_line_bytes: int = DEFAULT_MAX_LINE_BYTES) -> ReadResult:
    """Read only a bounded append window; cursor=None establishes the EOF boundary."""
    if max_bytes <= 0 or max_line_bytes <= 0 or max_line_bytes > max_bytes:
        raise ValueError("invalid reader bounds")
    if isinstance(cursor, dict):
        cursor = Cursor.from_dict(cursor)
    fd, info = _open_verified(binding)
    try:
        if cursor is None:
            os.lseek(fd, max(0, info.st_size - 1), os.SEEK_SET)
            mid_line = info.st_size > 0 and os.read(fd, 1) != b"\n"
            return _empty_cursor(binding, info, info.st_size, initialized=True, skip=mid_line)
        if cursor.parent_id != binding.parent_id or cursor.path != binding.path:
            return _empty_cursor(binding, info, info.st_size, "cursor identity changed",
                                 skip=_eof_is_partial(fd, info.st_size))
        if (cursor.device, cursor.inode) != (info.st_dev, info.st_ino):
            return _empty_cursor(binding, info, info.st_size, "parent rollout replaced",
                                 skip=_eof_is_partial(fd, info.st_size))
        if info.st_size < cursor.offset or info.st_size < cursor.observed_size:
            return _empty_cursor(binding, info, info.st_size, "parent rollout truncated",
                                 skip=_eof_is_partial(fd, info.st_size))
        if cursor.offset == info.st_size:
            return _empty_cursor(binding, info, cursor.offset, skip=cursor.skip_to_newline)
        os.lseek(fd, cursor.offset, os.SEEK_SET)
        chunk = os.read(fd, min(max_bytes, info.st_size - cursor.offset))
        consumed_end = cursor.offset + len(chunk)
        last_newline = chunk.rfind(b"\n")
        if last_newline < 0:
            if len(chunk) >= max_line_bytes:
                return _empty_cursor(binding, info, consumed_end, "oversized record skipped", skip=True)
            c = Cursor(info.st_dev, info.st_ino, cursor.offset, binding.parent_id, binding.path,
                       info.st_size, cursor.skip_to_newline)
            return ReadResult(c, ())
        complete = chunk[:last_newline + 1]
        start = 0
        events: list[TaskCreationEvent] = []
        skip = cursor.skip_to_newline
        records_seen = 0
        consumed_through = 0
        unsupported = False
        for end, byte in enumerate(complete):
            if byte != 10:
                continue
            record = complete[start:end]
            records_seen += 1
            if skip:
                skip = False
            elif records_seen <= DEFAULT_MAX_RECORDS and record:
                if len(record) <= max_line_bytes:
                    event = parse_creation_record(record, binding.parent_id)
                    if event is not None:
                        events.append(event)
                    elif _is_unsupported_creation_candidate(record, binding.parent_id):
                        unsupported = True
            start = end + 1
            if records_seen >= DEFAULT_MAX_RECORDS:
                consumed_through = start
                break
        if consumed_through:
            complete = complete[:consumed_through]
        else:
            complete = complete[:start]
        next_offset = cursor.offset + len(complete)
        next_cursor = Cursor(info.st_dev, info.st_ino, next_offset, binding.parent_id,
                             binding.path, info.st_size, skip)
        return ReadResult(next_cursor, tuple(events), reason=("unsupported record format"
                                                              if unsupported else None))
    finally:
        os.close(fd)
