"""Codex app-server hook and existing-app-server adapter primitives.

Hook values are treated only as event identity hints. Backend identity must be
independently established by the caller before any routing or attachment.
"""
from __future__ import annotations

import base64
import hashlib
import json
import math
import os
import re
import secrets
import selectors
import shutil
import stat
import struct
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterator, Mapping

from ..environment import child_environment
from ..model import Context, Harness, Lifecycle, ParentBinding, Session


_HOOK_FIELDS = {
    "SessionStart": {
        "required": {"cwd", "hook_event_name", "session_id", "transcript_path"},
        "strings": {"cwd", "hook_event_name", "session_id"},
        "enums": {"hook_event_name": {"SessionStart"}},
    },
    "SubagentStart": {
        "required": {"agent_id", "agent_type", "cwd", "hook_event_name", "session_id", "transcript_path", "turn_id"},
        "strings": {"agent_id", "agent_type", "cwd", "hook_event_name", "session_id", "turn_id"},
        "enums": {"hook_event_name": {"SubagentStart"}},
    },
    "SubagentStop": {
        "required": {"agent_id", "agent_type", "cwd", "hook_event_name", "session_id", "stop_hook_active", "transcript_path", "turn_id"},
        "strings": {"agent_id", "agent_type", "cwd", "hook_event_name", "session_id", "turn_id"},
        "enums": {"hook_event_name": {"SubagentStop"}},
        "booleans": {"stop_hook_active"},
    },
}


@dataclass(frozen=True, slots=True)
class CodexIdentity:
    profile: str
    config_root: Path
    data_root: Path
    state_root: Path
    backend_id: str
    session_id: str
    backend_instance: str

    def context(self) -> Context:
        if not all((self.profile, self.backend_id, self.session_id, self.backend_instance)):
            raise ValueError("verified Codex profile, backend and session identity are required")
        return Context(Harness.CODEX, self.profile, self.config_root, self.data_root,
                       self.state_root, self.backend_id, self.session_id, self.backend_instance)


@dataclass(frozen=True, slots=True)
class HookEvent:
    event_name: str
    identity: CodexIdentity
    cwd: Path
    turn_id: str | None = None
    agent_id: str | None = None
    agent_type: str | None = None
    stop_hook_active: bool | None = None


@dataclass(frozen=True, slots=True)
class TurnMetadata:
    """Message-free persisted turn status correlated to its native thread."""
    thread_id: str
    turn_id: str
    status: str

    @property
    def terminal(self) -> bool:
        return self.status in {"completed", "interrupted", "failed"}


def parse_hook(payload: str | bytes | Mapping[str, Any], *, profile: str,
               config_root: Path, data_root: Path, state_root: Path,
               verified_backend_id: str | None,
               verified_backend_instance: str | None) -> HookEvent:
    """Parse only released required hook fields; never trust model/permission values."""
    obj = json.loads(payload) if isinstance(payload, (str, bytes)) else dict(payload)
    if not isinstance(obj, dict):
        raise ValueError("hook input must be a JSON object")
    name = obj.get("hook_event_name")
    schema = _HOOK_FIELDS.get(name)
    if schema is None or not schema["required"] <= set(obj):
        raise ValueError("unsupported or incomplete Codex hook input")
    if any(not isinstance(obj[k], str) or not obj[k] for k in schema["strings"]):
        raise ValueError("invalid Codex hook string field")
    if any(obj[k] not in allowed for k, allowed in schema["enums"].items()):
        raise ValueError("unsupported Codex hook enum value")
    if any(not isinstance(obj[k], bool) for k in schema.get("booleans", ())):
        raise ValueError("invalid Codex hook boolean field")
    if name in {"SubagentStart", "SubagentStop"} and obj["session_id"] != obj["agent_id"]:
        raise ValueError("Codex subagent hook identity does not match child session")
    if obj["transcript_path"] is not None and (not isinstance(obj["transcript_path"], str) or not obj["transcript_path"]):
        raise ValueError("invalid transcript path field")
    if not isinstance(obj["transcript_path"], (str, type(None))):
        raise ValueError("invalid transcript path field")
    if not verified_backend_id or not verified_backend_instance:
        raise ValueError("Codex backend identity and socket incarnation have not been independently verified")
    ident = CodexIdentity(profile, config_root, data_root, state_root,
                          verified_backend_id, obj["session_id"], verified_backend_instance)
    return HookEvent(name, ident, Path(obj["cwd"]), obj.get("turn_id"),
                     obj.get("agent_id"), obj.get("agent_type"), obj.get("stop_hook_active"))


def _backend_failure(proxy: AppServerProxy, stage: str, method: str, reason: str) -> str:
    version = getattr(proxy, "server_version", None)
    suffix = f" (daemon {version})" if version else " (daemon version unknown)"
    return f"Codex app-server {stage} failed for {method}: {reason}{suffix}"


class AppServerProxy:
    """Small JSON-RPC client over Codex's stdio proxy to an existing socket."""
    _USER_AGENT_VERSION = re.compile(r"^codex-tui/(\d{1,9}\.\d{1,9}\.\d{1,9}(?:[-+][A-Za-z0-9.-]{1,32})?)(?:\s|$)")

    def __init__(self, executable: str, socket_path: Path, *, context: Context, timeout: float = 5.0,
                 popen: Callable[..., subprocess.Popen[bytes]] = subprocess.Popen,
                 lstat: Callable[[Path], os.stat_result] = Path.lstat):
        if not socket_path.is_absolute():
            raise ValueError("existing Codex app-server socket is required")
        if (context.harness is not Harness.CODEX or context.backend_id == ""
                or Path(context.backend_id).resolve(strict=True) != socket_path.resolve(strict=True)):
            raise ValueError("verified Codex context is required")
        self.socket_path = socket_path
        self._lstat = lstat
        self._socket_identity = self._inspect_socket()
        if context.backend_instance != self._instance_pin(self._socket_identity):
            raise ValueError("Codex socket incarnation does not match the selected backend")
        self.timeout = min(max(float(timeout), 0.1), 5.0)
        self._startup_deadline = time.monotonic() + self.timeout
        allowed = {"HOME", "PATH", "LANG", "LC_ALL", "LC_CTYPE", "TERM", "COLORTERM", "TMPDIR", "XDG_RUNTIME_DIR", "SSH_AUTH_SOCK"}
        safe_env = child_environment(context, source={k: v for k, v in os.environ.items() if k in allowed})
        self._proc = popen([executable, "app-server", "proxy", "--sock", str(socket_path)],
                           stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                           env=safe_env)
        self._next_id = 0
        self._raw_buffer = bytearray()
        self._selector = selectors.DefaultSelector()
        if self._proc.stdin is None or self._proc.stdout is None:
            raise RuntimeError("Codex proxy pipes unavailable")
        self._selector.register(self._proc.stdout.fileno(), selectors.EVENT_READ)
        os.set_blocking(self._proc.stdin.fileno(), False)
        self._write_fd = self._proc.stdin.fileno()
        self._in_startup = True
        self.server_version: str | None = None
        try:
            try:
                self._handshake(self._startup_deadline)
            except TimeoutError as exc:
                raise TimeoutError(_backend_failure(
                    self, "transport", "initialize", "WebSocket handshake timed out")) from exc
            except (RuntimeError, OSError) as exc:
                raise self._failure("transport", "initialize", "WebSocket handshake failed") from exc
            initialized = self.request("initialize", {"clientInfo": {"name": "harness-herdr-hooks", "version": "0.1.0"},
                                                       "capabilities": {"experimentalApi": True}})
            self.server_version = self._reported_version(initialized)
            if initialized.get("codexHome") != str(context.config_root.resolve()):
                raise ValueError(_backend_failure(
                    self, "profile check", "initialize", "home does not match selected profile"))
            try:
                self.notify("initialized", {})
            except TimeoutError as exc:
                raise TimeoutError(_backend_failure(
                    self, "transport", "initialized", "notification timed out")) from exc
            except (OSError, RuntimeError, ValueError) as exc:
                raise type(exc)(_backend_failure(self, "transport", "initialized", "notification failed")) from exc
            self._in_startup = False
        except BaseException:
            self.close()
            raise

    @classmethod
    def _reported_version(cls, initialized: Mapping[str, Any]) -> str | None:
        """Return the daemon release when its diagnostic format is recognized."""
        user_agent = initialized.get("userAgent")
        if not isinstance(user_agent, str):
            return None
        match = cls._USER_AGENT_VERSION.match(user_agent)
        return match.group(1) if match else None

    def _failure(self, stage: str, method: str, reason: str) -> RuntimeError:
        return RuntimeError(_backend_failure(self, stage, method, reason))

    def _inspect_socket(self) -> tuple[int, int, int, int]:
        info = self._lstat(self.socket_path)
        if (not stat.S_ISSOCK(info.st_mode) or info.st_uid != os.getuid()
                or stat.S_IMODE(info.st_mode) & 0o077):
            raise ValueError("Codex app-server socket ownership or permissions are unsafe")
        return info.st_dev, info.st_ino, info.st_uid, stat.S_IMODE(info.st_mode)

    @staticmethod
    def _instance_pin(identity: tuple[int, int, int, int]) -> str:
        dev, ino, uid, _mode = identity
        return f"{dev}:{ino}:{uid}"

    def _verify_socket(self) -> None:
        if self._inspect_socket() != self._socket_identity:
            raise RuntimeError("Codex app-server socket identity changed")

    def _write(self, wire: bytes, deadline: float) -> None:
        offset = 0
        with selectors.DefaultSelector() as writer:
            writer.register(self._write_fd, selectors.EVENT_WRITE)
            while offset < len(wire):
                remaining = deadline - time.monotonic()
                if remaining <= 0 or not writer.select(remaining):
                    raise TimeoutError("Codex app-server write timed out")
                try:
                    offset += os.write(self._write_fd, wire[offset:])
                except BlockingIOError:
                    continue

    def _read_more(self, deadline: float) -> None:
        remaining = deadline - time.monotonic()
        if remaining <= 0 or not self._selector.select(remaining):
            raise TimeoutError("Codex app-server read timed out")
        chunk = os.read(self._proc.stdout.fileno(), 65536)
        if not chunk:
            raise RuntimeError("Codex proxy closed its WebSocket stream")
        self._raw_buffer.extend(chunk)
        if len(self._raw_buffer) > 1024 * 1024 + 16384:
            raise RuntimeError("Codex WebSocket input exceeds the bounded buffer")

    def _read_exact(self, count: int, deadline: float) -> bytes:
        while len(self._raw_buffer) < count:
            self._read_more(deadline)
        out = bytes(self._raw_buffer[:count])
        del self._raw_buffer[:count]
        return out

    def _handshake(self, deadline: float) -> None:
        nonce = base64.b64encode(secrets.token_bytes(16)).decode("ascii")
        request = ("GET / HTTP/1.1\r\nHost: localhost\r\nUpgrade: websocket\r\n"
                   "Connection: Upgrade\r\nSec-WebSocket-Version: 13\r\n"
                   f"Sec-WebSocket-Key: {nonce}\r\n\r\n").encode("ascii")
        self._write(request, deadline)
        while b"\r\n\r\n" not in self._raw_buffer:
            self._read_more(deadline)
            if len(self._raw_buffer) > 16384:
                raise RuntimeError("Codex WebSocket handshake headers exceed limit")
        end = self._raw_buffer.index(b"\r\n\r\n") + 4
        header = bytes(self._raw_buffer[:end])
        del self._raw_buffer[:end]
        lines = header.decode("iso-8859-1").split("\r\n")
        if not lines or not lines[0].startswith("HTTP/1.1 101 "):
            raise RuntimeError("Codex app-server rejected WebSocket upgrade")
        headers: dict[str, str] = {}
        for line in lines[1:]:
            if ":" in line:
                key, value = line.split(":", 1)
                headers[key.strip().lower()] = value.strip()
        expected = base64.b64encode(hashlib.sha1((nonce + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode("ascii")).digest()).decode("ascii")
        if (headers.get("upgrade", "").lower() != "websocket"
                or "upgrade" not in {x.strip().lower() for x in headers.get("connection", "").split(",")}
                or headers.get("sec-websocket-accept") != expected):
            raise RuntimeError("invalid Codex WebSocket handshake response")

    def _send_frame(self, opcode: int, payload: bytes, deadline: float, *, fin: bool = True) -> None:
        if len(payload) > 1024 * 1024 or (opcode >= 8 and (not fin or len(payload) > 125)):
            raise ValueError("invalid or oversized Codex WebSocket control frame")
        first = (0x80 if fin else 0) | opcode
        length = len(payload)
        if length < 126:
            head = bytes((first, 0x80 | length))
        elif length <= 0xFFFF:
            head = bytes((first, 0x80 | 126)) + struct.pack("!H", length)
        else:
            head = bytes((first, 0x80 | 127)) + struct.pack("!Q", length)
        mask = secrets.token_bytes(4)
        masked = bytes(value ^ mask[i % 4] for i, value in enumerate(payload))
        self._write(head + mask + masked, deadline)

    def _recv_message(self, deadline: float) -> tuple[int, bytes]:
        fragments = bytearray()
        message_opcode: int | None = None
        while True:
            first, second = self._read_exact(2, deadline)
            fin, rsv, opcode, masked = bool(first & 0x80), first & 0x70, first & 0x0F, bool(second & 0x80)
            if rsv or masked or opcode not in {0, 1, 2, 8, 9, 10}:
                raise RuntimeError("invalid Codex WebSocket frame")
            length = second & 0x7F
            if length == 126:
                length = struct.unpack("!H", self._read_exact(2, deadline))[0]
            elif length == 127:
                length = struct.unpack("!Q", self._read_exact(8, deadline))[0]
                if length >> 63:
                    raise RuntimeError("invalid Codex WebSocket frame length")
            if length > 1024 * 1024 or (opcode >= 8 and (not fin or length > 125)):
                raise RuntimeError("oversized Codex WebSocket frame")
            payload = self._read_exact(length, deadline)
            if opcode == 9:
                self._send_frame(10, payload, deadline)
                continue
            if opcode == 10:
                continue
            if opcode == 8:
                self._send_frame(8, payload[:125], deadline)
                raise RuntimeError("Codex WebSocket closed")
            if opcode in {1, 2}:
                if message_opcode is not None:
                    raise RuntimeError("nested Codex WebSocket data message")
                message_opcode = opcode
            elif message_opcode is None:
                raise RuntimeError("unexpected Codex WebSocket continuation")
            fragments.extend(payload)
            if len(fragments) > 1024 * 1024:
                raise RuntimeError("Codex WebSocket message exceeds 1 MiB")
            if fin:
                if message_opcode is None:
                    raise RuntimeError("invalid Codex WebSocket message")
                return message_opcode, bytes(fragments)

    def notify(self, method: str, params: Mapping[str, Any]) -> None:
        if self._proc.stdin is None or self._proc.poll() is not None:
            raise RuntimeError("Codex proxy is unavailable")
        self._verify_socket()
        wire = json.dumps({"jsonrpc": "2.0", "method": method, "params": dict(params)}, separators=(",", ":")).encode()
        deadline = min(time.monotonic() + self.timeout, self._startup_deadline) if self._in_startup else time.monotonic() + self.timeout
        self._send_frame(1, wire, deadline)

    def request(self, method: str, params: Mapping[str, Any]) -> Mapping[str, Any]:
        if self._proc.stdin is None or self._proc.stdout is None or self._proc.poll() is not None:
            raise self._failure("transport", method, "proxy unavailable")
        try:
            self._verify_socket()
        except (OSError, RuntimeError, ValueError) as exc:
            raise type(exc)(_backend_failure(self, "transport", method, "socket identity check failed")) from exc
        self._next_id += 1
        request_id = self._next_id
        wire = json.dumps({"jsonrpc": "2.0", "id": request_id, "method": method,
                           "params": dict(params)}, separators=(",", ":")).encode()
        if len(wire) > 1024 * 1024:
            raise ValueError("Codex request exceeds 1 MiB")
        deadline = min(time.monotonic() + self.timeout, self._startup_deadline) if self._in_startup else time.monotonic() + self.timeout
        try:
            self._send_frame(1, wire, deadline)
        except TimeoutError as exc:
            raise TimeoutError(_backend_failure(self, "transport", method, "request timed out")) from exc
        except (OSError, RuntimeError, ValueError) as exc:
            raise type(exc)(_backend_failure(self, "transport", method, "request send failed")) from exc
        while True:
            try:
                opcode, payload = self._recv_message(deadline)
            except TimeoutError as exc:
                raise TimeoutError(_backend_failure(self, "transport", method, "request timed out")) from exc
            except (OSError, RuntimeError, ValueError) as exc:
                raise type(exc)(_backend_failure(self, "transport", method, "response exchange failed")) from exc
            if opcode != 1:
                raise self._failure("transport", method, "non-text response")
            try:
                msg = json.loads(payload)
            except ValueError:
                raise ValueError(_backend_failure(self, "response", method, "invalid JSON-RPC message")) from None
            except RecursionError:
                raise self._failure("response", method, "invalid JSON-RPC message") from None
            if not isinstance(msg, dict) or msg.get("id") != request_id:
                continue
            if type(msg["id"]) is not int:
                raise self._failure("response", method, "invalid JSON-RPC response ID")
            if "error" in msg:
                raise self._failure("method", method, "server rejected request")
            result = msg.get("result")
            if not isinstance(result, dict):
                raise self._failure("response", method, "required result object missing")
            return result

    def close(self) -> None:
        self._selector.close()
        if self._proc.poll() is None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=1)
            except subprocess.TimeoutExpired:
                self._proc.kill()
                self._proc.wait(timeout=1)


def list_threads(proxy: AppServerProxy, *, parent_id: str | None = None,
                 ancestor_id: str | None = None) -> Iterator[Mapping[str, Any]]:
    if bool(parent_id) and bool(ancestor_id):
        raise ValueError("parentThreadId and ancestorThreadId are mutually exclusive")
    params: dict[str, Any] = {"limit": 100}
    if parent_id:
        params["parentThreadId"] = parent_id
    if ancestor_id:
        params["ancestorThreadId"] = ancestor_id
    if parent_id or ancestor_id:
        params["sourceKinds"] = ["subAgentThreadSpawn"]
    cursor = None
    seen: set[str] = set()
    for _ in range(100):
        if cursor:
            params["cursor"] = cursor
        result = proxy.request("thread/list", params)
        data = result.get("data")
        if not isinstance(data, list):
            raise RuntimeError(_backend_failure(proxy, "response", "thread/list", "invalid data"))
        for thread in data:
            if not isinstance(thread, dict):
                raise RuntimeError(_backend_failure(proxy, "response", "thread/list", "invalid thread record"))
            yield thread
        cursor = result.get("nextCursor")
        if cursor is None:
            return
        if not isinstance(cursor, str) or not cursor or cursor in seen:
            raise RuntimeError(_backend_failure(proxy, "response", "thread/list", "invalid or cyclic pagination cursor"))
        seen.add(cursor)
    raise RuntimeError(_backend_failure(proxy, "response", "thread/list", "pagination limit exceeded"))


def list_loaded_threads(proxy: AppServerProxy) -> set[str]:
    cursor = None
    seen: set[str] = set()
    loaded: set[str] = set()
    for _ in range(100):
        params = {"limit": 100}
        if cursor:
            params["cursor"] = cursor
        result = proxy.request("thread/loaded/list", params)
        data = result.get("data")
        if not isinstance(data, list) or any(not isinstance(item, str) for item in data):
            raise RuntimeError(_backend_failure(proxy, "response", "thread/loaded/list", "invalid data"))
        loaded.update(data)
        cursor = result.get("nextCursor")
        if cursor is None:
            return loaded
        if not isinstance(cursor, str) or not cursor or cursor in seen:
            raise RuntimeError(_backend_failure(proxy, "response", "thread/loaded/list", "invalid or cyclic pagination cursor"))
        seen.add(cursor)
    raise RuntimeError(_backend_failure(proxy, "response", "thread/loaded/list", "pagination limit exceeded"))


def list_turn_metadata(proxy: AppServerProxy, thread_id: str, *, page_size: int = 100,
                       max_pages: int = 10) -> tuple[TurnMetadata, ...]:
    """Read bounded turn IDs/status only; never request transcript items."""
    if not isinstance(thread_id, str) or not thread_id:
        raise ValueError("Codex thread ID is required")
    if not 1 <= page_size <= 100 or not 1 <= max_pages <= 10:
        raise ValueError("Codex turn pagination bounds are invalid")
    cursor: str | None = None
    seen: set[str] = set()
    result: list[TurnMetadata] = []
    for _ in range(max_pages):
        params: dict[str, Any] = {"threadId": thread_id, "itemsView": "notLoaded",
                                  "limit": page_size, "sortDirection": "desc"}
        if cursor:
            params["cursor"] = cursor
        page = proxy.request("thread/turns/list", params)
        rows = page.get("data")
        if not isinstance(rows, list):
            raise RuntimeError(_backend_failure(proxy, "response", "thread/turns/list", "invalid data"))
        for row in rows:
            if not isinstance(row, dict) or not isinstance(row.get("id"), str) or row.get("status") not in ("completed", "interrupted", "failed", "inProgress"):
                raise RuntimeError(_backend_failure(proxy, "response", "thread/turns/list", "invalid turn metadata"))
            # A proxy/server violating itemsView=notLoaded is not allowed to
            # make transcript contents enter lifecycle state.
            if row.get("itemsView", "notLoaded") != "notLoaded" or row.get("items") not in (None, []):
                raise RuntimeError(_backend_failure(proxy, "response", "thread/turns/list", "response included transcript items"))
            result.append(TurnMetadata(thread_id, row["id"], row["status"]))
        cursor = page.get("nextCursor")
        if cursor is None:
            return tuple(result)
        if not isinstance(cursor, str) or not cursor or cursor in seen:
            raise RuntimeError(_backend_failure(proxy, "response", "thread/turns/list", "invalid or cyclic pagination cursor"))
        seen.add(cursor)
    if cursor is not None:
        raise RuntimeError(_backend_failure(proxy, "response", "thread/turns/list", "pagination limit exceeded"))
    return tuple(result)


def lifecycle(status: Mapping[str, Any] | str | None, *, loaded: bool,
              attachable: bool) -> tuple[Lifecycle, bool]:
    """Only active + loaded + verified attachable metadata qualifies for display."""
    kind = status if isinstance(status, str) else (status or {}).get("type")
    if kind == "active" and loaded and attachable:
        return Lifecycle.RUNNING, True
    return Lifecycle.UNKNOWN, False


class CodexRuntimeAdapter:
    """Maps one verified Codex backend into the coordinator Runtime interface."""
    def __init__(self, context: Context, executable: str = "codex", *,
                 proxy_factory: Callable[..., AppServerProxy] = AppServerProxy,
                 task_store_root: Path | None = None):
        if context.harness is not Harness.CODEX:
            raise ValueError("Codex runtime requires a Codex context")
        raw_socket_path = Path(context.backend_id)
        if not raw_socket_path.is_absolute():
            raise ValueError("Codex backend identity must be an absolute existing socket path")
        try:
            socket_path = raw_socket_path.resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise ValueError("Codex backend socket path cannot be resolved") from exc
        resolved = shutil.which(executable)
        if not resolved:
            raise ValueError("Codex executable is not available on PATH")
        executable = str(Path(resolved).resolve(strict=True))
        if not os.path.isfile(executable) or not os.access(executable, os.X_OK):
            raise ValueError("Codex executable is not an executable file")
        if not context.backend_instance:
            raise ValueError("Codex socket incarnation pin is required")
        self.context = context
        self.task_store_root = task_store_root or context.state_root
        self.executable = executable
        self.socket_path = socket_path
        self.proxy = proxy_factory(executable, socket_path, context=context)
        self._task_retry_monotonic: dict[str, tuple[float, float, float]] = {}

    def _check_parent(self, parent: ParentBinding) -> None:
        if parent.context != self.context:
            raise ValueError("Codex parent context does not match selected backend")

    @staticmethod
    def _is_native_child(thread: Mapping[str, Any], parent_id: str) -> bool:
        source = thread.get("source")
        if not isinstance(source, dict) or "subAgent" not in source:
            return False
        sub = source["subAgent"]
        if not isinstance(sub, dict) or "thread_spawn" not in sub:
            return False
        spawn = sub["thread_spawn"]
        return isinstance(spawn, dict) and spawn.get("parent_thread_id") == parent_id

    @staticmethod
    def _active_status(status: object) -> bool:
        return (isinstance(status, dict) and status.get("type") == "active"
                and isinstance(status.get("activeFlags"), list)
                and all(isinstance(flag, str) and flag in {"waitingOnApproval", "waitingOnUserInput"}
                        for flag in status["activeFlags"]))

    def _session(self, thread: Mapping[str, Any], ancestry: tuple[str, ...], loaded: set[str]) -> Session:
        ident = thread.get("id")
        if not isinstance(ident, str) or not ident:
            raise RuntimeError("Codex thread metadata has no identity")
        status = thread.get("status")
        active = self._active_status(status)
        # canAcceptDirectInput governs turn input; it is not evidence about the
        # separate UI attach path. Require native spawn ownership + active load.
        attachable = ident in loaded and active and bool(ancestry)
        state, allowed = lifecycle(status, loaded=ident in loaded, attachable=attachable)
        cwd = thread.get("cwd")
        if not isinstance(cwd, str) or not Path(cwd).is_absolute():
            raise RuntimeError("Codex thread metadata has invalid working directory")
        child_context = Context(Harness.CODEX, self.context.profile, self.context.config_root,
                                self.context.data_root, self.context.state_root,
                                self.context.backend_id, ident, self.context.backend_instance)
        direct_parent = thread.get("parentThreadId")
        session_path = None
        raw_path = thread.get("path")
        if isinstance(raw_path, str) and raw_path and Path(raw_path).is_absolute():
            try:
                canonical_path = Path(raw_path).resolve(strict=False)
                if canonical_path.is_absolute():
                    session_path = canonical_path
            except (OSError, RuntimeError):
                session_path = None
        return Session(child_context, direct_parent if isinstance(direct_parent, str) else None,
                       thread.get("name") if isinstance(thread.get("name"), str) else None,
                       Path(cwd), state, allowed, time.time(), ancestry, session_path)

    @staticmethod
    def _verified_chain(thread_id: str, rows: Mapping[str, Mapping[str, Any]],
                        root_id: str, *, max_depth: int = 32) -> tuple[str, ...] | None:
        chain: list[str] = []
        seen = {thread_id}
        current_id = thread_id
        for _ in range(max_depth):
            current = rows.get(current_id)
            if current is None:
                return None
            parent_id = current.get("parentThreadId")
            if not isinstance(parent_id, str) or not parent_id:
                return None
            if not CodexRuntimeAdapter._is_native_child(current, parent_id):
                return None
            chain.append(parent_id)
            if parent_id == root_id:
                return tuple(chain)
            if parent_id in seen:
                return None
            seen.add(parent_id)
            current_id = parent_id
        return None

    def sessions(self, parent: ParentBinding) -> Iterator[Session]:
        self._check_parent(parent)
        loaded = list_loaded_threads(self.proxy)
        rows = {item.get("id"): item for item in list_threads(self.proxy, ancestor_id=parent.context.session_id)
                if isinstance(item.get("id"), str)}
        for ident, thread in rows.items():
            chain = self._verified_chain(ident, rows, parent.context.session_id)
            if chain is not None:
                yield self._session(thread, chain, loaded)
        try:
            yield from self._standalone_sessions(parent)
        except Exception:
            # Malformed or unavailable rollout files disable only this
            # optional discovery path; native ancestry discovery stays live.
            self._standalone_status("deferred", "deferred", "unknown", "metadata_unavailable")

    def _standalone_status(self, recognition: str, verification: str,
                           attachment: str, reason: str | None = None) -> None:
        try:
            from ..cli import _runtime_write
            def update(data):
                current = data.get("task_discovery", {})
                if not isinstance(current, dict): current = {}
                # Stage fields describe the last meaningful discovery result.
                # Empty reads and capture failures update health only.
                for key, value in (("recognition", recognition),
                                   ("verification", verification),
                                   ("attachment", attachment)):
                    if value not in {"unknown", "observing", "deferred"}:
                        current[key] = value
                if reason in {"parent_file_missing", "parent_file_mismatch", "unsafe_parent_file",
                              "metadata_unavailable", "candidate_expired", "future_timestamp",
                              "task_finished", "task_mismatch", "unsupported_envelope",
                              "unsupported_record_format", "retry_exhausted", "attachment_pending",
                              "invalid_cwd", "cwd_mismatch", "status_deferred", "pending_limit"}:
                    current["reason"] = reason
                elif reason is None and any(value not in {"unknown", "observing", "deferred"}
                                            for value in (recognition, verification, attachment)):
                    current.pop("reason", None)
                health = {"state": "deferred" if reason in {
                    "parent_file_missing", "parent_file_mismatch", "unsafe_parent_file",
                    "metadata_unavailable", "candidate_expired", "future_timestamp",
                    "unsupported_envelope", "unsupported_record_format", "retry_exhausted",
                    "invalid_cwd", "cwd_mismatch", "status_deferred", "pending_limit"} else "healthy"}
                if health["state"] == "deferred" and reason in {
                    "parent_file_missing", "parent_file_mismatch", "unsafe_parent_file",
                    "metadata_unavailable", "candidate_expired", "future_timestamp",
                    "unsupported_envelope", "unsupported_record_format", "retry_exhausted",
                    "invalid_cwd", "cwd_mismatch", "status_deferred", "pending_limit"}:
                    health["reason"] = reason
                current["current_health"] = health
                data["task_discovery"] = current
            _runtime_write(self.task_store_root, self.context.profile, update)
        except Exception:
            pass

    def _standalone_sessions(self, parent: ParentBinding) -> Iterator[Session]:
        """Observe only new typed create_thread results in the exact bound parent file."""
        import os
        from ..codex_task_records import bind_parent_file, read_new_records
        from ..model import CreationProof
        from ..state import StateStore

        try:
            native_parent = self._read_thread(parent.context.session_id)
        except Exception:
            self._standalone_status("deferred", "deferred", "unknown", "metadata_unavailable")
            return
        if not isinstance(native_parent, dict):
            self._standalone_status("deferred", "deferred", "unknown", "metadata_unavailable")
            return
        raw_parent_path = native_parent.get("path")
        if not isinstance(raw_parent_path, str) or not Path(raw_parent_path).is_absolute():
            self._standalone_status("deferred", "deferred", "unknown", "parent_file_missing")
            return
        if native_parent.get("id") != parent.context.session_id:
            self._standalone_status("deferred", "deferred", "unknown", "parent_file_mismatch")
            return
        native_path = Path(raw_parent_path)
        if parent.session_path is not None and os.path.abspath(native_path) != os.path.abspath(parent.session_path):
            self._standalone_status("deferred", "deferred", "unknown", "parent_file_mismatch")
            return
        sessions_dir = self.context.data_root / "sessions"
        store = StateStore(self.task_store_root, self.context.key()[:32])
        try:
            binding = bind_parent_file(native_path, sessions_dir, parent.context.session_id)
        except FileNotFoundError:
            self._standalone_status("deferred", "deferred", "unknown", "parent_file_missing")
            return
        except ValueError as exc:
            missing_component = isinstance(exc.__cause__, OSError) and getattr(exc.__cause__, "errno", None) == 2
            reason = "parent_file_missing" if missing_component else "unsafe_parent_file"
            self._standalone_status("deferred", "deferred", "unknown", reason)
            return
        except OSError as exc:
            reason = "parent_file_missing" if getattr(exc, "errno", None) == 2 else "unsafe_parent_file"
            self._standalone_status("deferred", "deferred", "unknown", reason)
            return
        # Pair the cursor snapshot with the local read and commit. No provider
        # request is made while this separate task-observer lock is held.
        with store.task_observing():
            snapshot = store.task_discovery()
            read = read_new_records(binding, snapshot.get("cursor"))
            authority = {"parent_id": parent.context.session_id,
                         "path": binding.path, "owner_uid": binding.owner_uid}
            context_pin = {"profile": parent.context.profile,
                           "backend_id": parent.context.backend_id,
                           "backend_instance": parent.context.backend_instance,
                           "session_id": parent.context.session_id}
            destination = {"server_id": parent.herdr_server_id,
                           "workspace_id": parent.workspace_id,
                           "tab_id": parent.tab_id, "pane_id": parent.pane_id}
            _added, overflow = store.commit_task_records(
                read.cursor.to_dict(), list(read.events), parent=authority,
                context=context_pin, destination=destination, now=time.time())
        reasons = {"unsupported record format": "unsupported_envelope",
                   "parent rollout replaced": "parent_file_mismatch",
                   "parent rollout truncated": "parent_file_mismatch",
                   "cursor identity changed": "parent_file_mismatch",
                   "oversized record skipped": "unsupported_envelope"}
        reason = reasons.get(read.reason or "")
        if overflow:
            reason = "pending_limit"
        self._standalone_status("recognized" if read.events else "observing",
                                "pending" if read.events else "unknown", "unknown", reason)
        discovery = store.task_discovery()
        candidates = list(discovery.get("pending", []))
        retry_map = getattr(self, "_task_retry_monotonic", None)
        if retry_map is None:
            retry_map = self._task_retry_monotonic = {}
        live_keys = {item.get("event_key") for item in candidates if isinstance(item, dict)}
        for key in tuple(retry_map):
            if key not in live_keys:
                retry_map.pop(key, None)
        # Re-observe attached work only through its durable exact task record
        # and owned binding. Bound this path; never enumerate arbitrary threads.
        from ..state import load_existing_binding
        from ..model import context_to_dict, parent_from_dict, session_from_dict
        for outcome in discovery.get("outcomes", [])[-128:]:
            if outcome.get("status") != "attached" or not isinstance(outcome.get("child_id"), str):
                continue
            child_id = outcome["child_id"]
            child_context = Context(Harness.CODEX, parent.context.profile, parent.context.config_root,
                                    parent.context.data_root, parent.context.state_root,
                                    parent.context.backend_id, child_id, parent.context.backend_instance)
            record = store.record(child_context.key())
            if not isinstance(record, dict) or record.get("status") != "attached":
                continue
            generation, turn_id = record.get("generation"), record.get("turn_id")
            if not isinstance(generation, str) or not isinstance(turn_id, str) or not generation.startswith(turn_id + ":"):
                continue
            item_id = generation[len(turn_id) + 1:]
            event_key = hashlib.sha256(json.dumps([parent.context.session_id, turn_id, item_id], separators=(",", ":")).encode()).hexdigest()
            if outcome.get("event_key") != event_key:
                continue
            try:
                binding = load_existing_binding(self.task_store_root, record.get("binding_id"))
            except Exception:
                continue
            try:
                bound_parent = parent_from_dict(binding.get("parent"))
                bound_child = session_from_dict(binding.get("child"))
            except Exception:
                continue
            proof = bound_child.creation_proof
            attached_outcome = binding.get("outcome", {}).get("status") == "attached"
            verified_reuse = (binding.get("ownership") == "reused"
                              and record.get("ownership") == "reused")
            if (binding.get("kind") != "standalone" or not (attached_outcome or verified_reuse)
                    or context_to_dict(bound_child.context) != context_to_dict(child_context)
                    or context_to_dict(bound_parent.context) != context_to_dict(parent.context)
                    or bound_parent.session_path != parent.session_path
                    or proof is None or proof.parent_id != parent.context.session_id
                    or proof.turn_id != turn_id or proof.item_id != item_id or proof.child_id != child_id):
                continue
            candidates.append({"event_key": event_key, "child_id": child_id,
                               "parent_id": parent.context.session_id, "turn_id": turn_id,
                               "item_id": item_id, "cwd_sha256": proof.cwd_sha256,
                               "status": "attached_replay", "context": context_pin,
                               "destination": destination, "proof": proof})
        if not candidates:
            return
        loaded = list_loaded_threads(self.proxy)
        for candidate in candidates:
            if (candidate.get("context") != context_pin or candidate.get("destination") != destination
                    or candidate.get("parent_id") != parent.context.session_id):
                store.update_task_candidate(candidate["event_key"], status="rejected",
                                            now=time.time(), reason="context changed")
                continue
            wall_now = time.time()
            mono_now = time.monotonic()
            first_seen = candidate.get("first_seen")
            # Persisted wall-clock timestamps are trusted only inside the bounded
            # retry window. Use monotonic time for the rest of this process so a
            # clock adjustment cannot extend the candidate's lifetime.
            replay = candidate.get("status") == "attached_replay"
            if not replay and (not isinstance(first_seen, (int, float)) or isinstance(first_seen, bool)
                    or not math.isfinite(first_seen)):
                store.update_task_candidate(candidate["event_key"], status="rejected",
                                            now=wall_now, reason="metadata unavailable")
                self._standalone_status("recognized", "rejected", "unknown", "candidate_expired")
                continue
            if replay:
                logical_now, deadline = wall_now, float("inf")
            else:
                stamp = retry_map.get(candidate["event_key"])
                if stamp is None or stamp[0] != float(first_seen):
                    age = wall_now - float(first_seen)
                    if age < 0:
                        store.update_task_candidate(candidate["event_key"], status="rejected", now=wall_now,
                                                    reason="metadata unavailable")
                        self._standalone_status("recognized", "rejected", "unknown", "future_timestamp")
                        continue
                    started = mono_now - age
                    deadline = started + 30.0
                    stamp = (float(first_seen), started, deadline)
                    if len(retry_map) >= 128:
                        retry_map.pop(next(iter(retry_map)))
                    retry_map[candidate["event_key"]] = stamp
                _saved_first, started, deadline = stamp
                logical_now = float(first_seen) + max(0.0, mono_now - started)
            if not replay and mono_now >= deadline:
                store.update_task_candidate(candidate["event_key"], status="rejected",
                                            now=logical_now, reason="metadata unavailable")
                self._standalone_status("recognized", "rejected", "unknown", "candidate_expired")
                retry_map.pop(candidate["event_key"], None)
                continue
            if not replay and not store.reserve_task_verification(candidate["event_key"], now=logical_now):
                outcomes = store.task_discovery().get("outcomes", [])
                if any(item.get("event_key") == candidate["event_key"] and item.get("status") == "rejected"
                       for item in outcomes if isinstance(item, dict)):
                    self._standalone_status("recognized", "rejected", "unknown", "retry_exhausted")
                continue
            try:
                row = self._read_thread(candidate["child_id"])
                if row.get("id") != candidate["child_id"]:
                    store.update_task_candidate(candidate["event_key"], status="rejected",
                                                now=logical_now, reason="context changed")
                    self._standalone_status("recognized", "rejected", "unknown", "task_mismatch")
                    continue
                if candidate["child_id"] not in loaded:
                    raise LookupError("metadata unavailable")
                cwd = row.get("cwd")
                if cwd is None:
                    raise LookupError("metadata unavailable")
                if not isinstance(cwd, str) or not Path(cwd).is_absolute():
                    store.update_task_candidate(candidate["event_key"], status="rejected",
                                                now=logical_now, reason="not attachable")
                    self._standalone_status("recognized", "rejected", "unknown", "invalid_cwd")
                    continue
                digest = candidate.get("cwd_sha256")
                if digest is not None:
                    if hashlib.sha256(os.path.normpath(cwd).encode("utf-8")).hexdigest() != digest:
                        store.update_task_candidate(candidate["event_key"], status="rejected",
                                                    now=logical_now, reason="context changed")
                        self._standalone_status("recognized", "rejected", "unknown", "cwd_mismatch")
                        continue
                native_status = row.get("status")
                status_type = native_status.get("type") if isinstance(native_status, dict) else None
                if status_type in {"completed", "interrupted", "failed"}:
                    # Existing attached replays remain historical attachment evidence.
                    store.update_task_candidate(candidate["event_key"], status="rejected",
                                                now=logical_now, reason="not attachable")
                    if not replay:
                        self._standalone_status("recognized", "rejected", "unknown", "task_finished")
                    continue
                if not self._active_status(native_status):
                    if replay:
                        continue
                    store.update_task_candidate(candidate["event_key"], status="pending",
                                                now=logical_now, reason="metadata unavailable")
                    self._standalone_status("recognized", "deferred", "unknown", "status_deferred")
                    continue
                proof = candidate.get("proof") or CreationProof(candidate["parent_id"], candidate["turn_id"],
                                      candidate["item_id"], candidate["child_id"], digest)
                context = Context(Harness.CODEX, self.context.profile, self.context.config_root,
                                  self.context.data_root, self.context.state_root,
                                  self.context.backend_id, candidate["child_id"],
                                  self.context.backend_instance)
                if not replay:
                    store.update_task_candidate(candidate["event_key"], status="verified", now=logical_now)
                    self._standalone_status("recognized", "verified", "pending")
                    finished_mono = time.monotonic()
                    if finished_mono >= deadline:
                        store.update_task_candidate(candidate["event_key"], status="rejected",
                                                    now=logical_now + finished_mono - mono_now,
                                                    reason="metadata unavailable")
                        self._standalone_status("recognized", "rejected", "unknown", "candidate_expired")
                        retry_map.pop(candidate["event_key"], None)
                        continue
                raw_path = row.get("path")
                session_path = Path(raw_path).resolve(strict=False) if isinstance(raw_path, str) and Path(raw_path).is_absolute() else None
                yield Session(context, parent.context.session_id,
                              row.get("name") if isinstance(row.get("name"), str) else None,
                              Path(cwd), Lifecycle.RUNNING, True, time.time(), (),
                              session_path, "standalone", None, None, proof)
            except Exception:
                if not replay:
                    store.update_task_candidate(candidate["event_key"], status="pending",
                                                now=logical_now + max(0.0, time.monotonic() - mono_now),
                                                reason="metadata unavailable")
                    self._standalone_status("recognized", "deferred", "unknown", "metadata_unavailable")
        if overflow:
            # Candidate processing may replace the capture reason with a retry
            # result. Preserve the aggregate bounded-skip health after the pass.
            self._standalone_status("observing", "unknown", "unknown", "pending_limit")

    def _read_thread(self, thread_id: str) -> Mapping[str, Any]:
        result = self.proxy.request("thread/read", {"threadId": thread_id, "includeTurns": False})
        thread = result.get("thread")
        if not isinstance(thread, dict):
            raise RuntimeError(_backend_failure(self.proxy, "response", "thread/read", "required thread object missing"))
        return thread

    def main_metadata(self, parent: ParentBinding) -> tuple[Context, str | None]:
        """Resolve the provider-native main conversation and its current title.

        A Codex parent link is ancestry only when the child is independently
        marked as a native subagent. This deliberately stops at standalone or
        other independent conversations even when they carry parent metadata.
        """
        self._check_parent(parent)
        current_id = parent.context.session_id
        seen: set[str] = set()
        for depth in range(33):
            if current_id in seen:
                raise ValueError("Codex conversation ancestry contains a cycle")
            seen.add(current_id)
            row = self._read_thread(current_id)
            if row.get("id") != current_id:
                raise ValueError(_backend_failure(self.proxy, "response", "thread/read", "returned a different conversation"))
            parent_id = row.get("parentThreadId")
            source = row.get("source")
            subagent = source.get("subAgent") if isinstance(source, dict) else None
            if parent_id is not None and not (
                    isinstance(source, str) and source in {"cli", "exec"}):
                if not isinstance(source, dict) or "subAgent" not in source:
                    raise ValueError(_backend_failure(self.proxy, "response", "thread/read", "conversation source classification is unknown or malformed"))
            if isinstance(source, dict) and "subAgent" in source:
                if (set(source) != {"subAgent"} or not isinstance(subagent, dict)
                        or set(subagent) != {"thread_spawn"}):
                    raise ValueError(_backend_failure(self.proxy, "response", "thread/read", "native subagent classification is malformed"))
            spawn_marker = isinstance(subagent, dict) and "thread_spawn" in subagent
            if spawn_marker:
                spawn = subagent.get("thread_spawn")
                if (not isinstance(spawn, dict)
                        or not isinstance(spawn.get("parent_thread_id"), str)
                        or not spawn.get("parent_thread_id")
                        or not isinstance(parent_id, str)
                        or spawn["parent_thread_id"] != parent_id):
                    raise ValueError(_backend_failure(self.proxy, "response", "thread/read", "native subagent ancestry is malformed"))
            if parent_id is not None and not isinstance(parent_id, str):
                raise ValueError(_backend_failure(self.proxy, "response", "thread/read", "conversation ancestry is malformed"))
            if not parent_id or not self._is_native_child(row, parent_id):
                title = row.get("name")
                return (Context(Harness.CODEX, self.context.profile, self.context.config_root,
                                self.context.data_root, self.context.state_root,
                                self.context.backend_id, current_id, self.context.backend_instance),
                        title.strip() or None if isinstance(title, str) else None)
            if depth == 32:
                raise ValueError("Codex conversation ancestry exceeds 32 hops")
            current_id = parent_id
        raise ValueError("Codex conversation ancestry is invalid")

    def can_attach_now(self, parent: ParentBinding, child: Session) -> bool:
        self._check_parent(parent)
        if child.kind == "standalone":
            pc, cc = parent.context, child.context
            proof = child.creation_proof
            if (cc.harness != pc.harness or cc.backend_id != pc.backend_id or
                    cc.backend_instance != pc.backend_instance or cc.profile != pc.profile or
                    cc.config_root.resolve() != pc.config_root.resolve() or
                    cc.data_root.resolve() != pc.data_root.resolve() or
                    cc.state_root.resolve() != pc.state_root.resolve() or
                    proof is None or proof.parent_id != parent.context.session_id or
                    proof.child_id != child.context.session_id or child.parent_session_id != proof.parent_id):
                return False
            try:
                native_parent = self._read_thread(pc.session_id)
            except Exception:
                return False
            native_path = native_parent.get("path")
            if (native_parent.get("id") != pc.session_id or
                    not isinstance(native_path, str) or not Path(native_path).is_absolute()):
                return False
            if parent.session_path is None or Path(native_path).resolve(strict=False) != parent.session_path.resolve(strict=False):
                return False
            try:
                from ..codex_task_records import bind_parent_file
                bind_parent_file(Path(native_path), pc.data_root / "sessions", pc.session_id)
            except (OSError, ValueError):
                return False
            loaded = list_loaded_threads(self.proxy)
            if child.context.session_id not in loaded:
                return False
            try:
                thread = self._read_thread(child.context.session_id)
            except Exception:
                return False
            cwd = thread.get("cwd")
            if (thread.get("id") != child.context.session_id or not isinstance(cwd, str)
                    or not Path(cwd).is_absolute() or Path(cwd) != child.cwd
                    or not self._active_status(thread.get("status"))):
                return False
            if proof.cwd_sha256 is not None:
                import hashlib
                import os
                if hashlib.sha256(os.path.normpath(cwd).encode("utf-8")).hexdigest() != proof.cwd_sha256:
                    return False
            return True
        if (child.context.harness is not Harness.CODEX
                or child.context.backend_id != self.context.backend_id
                or child.context.backend_instance != self.context.backend_instance):
            return False
        loaded = list_loaded_threads(self.proxy)
        if child.context.session_id not in loaded:
            return False
        rows: dict[str, Mapping[str, Any]] = {}
        current_id = child.context.session_id
        seen: set[str] = set()
        for _ in range(32):
            if current_id in seen:
                return False
            seen.add(current_id)
            current = self._read_thread(current_id)
            if current.get("id") != current_id:
                return False
            rows[current_id] = current
            parent_id = current.get("parentThreadId")
            if not isinstance(parent_id, str) or not self._is_native_child(current, parent_id):
                return False
            if parent_id == parent.context.session_id:
                chain = self._verified_chain(child.context.session_id, rows, parent.context.session_id)
                break
            current_id = parent_id
        else:
            return False
        if chain is None or tuple(child.ancestry) != chain:
            return False
        thread = rows[child.context.session_id]
        status = thread.get("status")
        return self._active_status(status)

    def attach_argv(self, child: Session) -> list[str]:
        if child.context.harness is not Harness.CODEX or child.context.backend_id != self.context.backend_id:
            raise ValueError("child does not belong to the selected Codex backend")
        return attach_argv(self.executable, self.socket_path, child.context.session_id)

    def close(self) -> None:
        self.proxy.close()


def attach_argv(executable: str, socket_path: Path, child_id: str) -> list[str]:
    if not socket_path.is_absolute() or not child_id:
        raise ValueError("verified socket path and child ID are required")
    return [executable, "resume", "--remote", f"unix://{socket_path}", child_id]


__all__ = ["AppServerProxy", "CodexIdentity", "HookEvent", "TurnMetadata", "attach_argv", "lifecycle", "list_loaded_threads", "list_threads", "list_turn_metadata", "parse_hook"]
