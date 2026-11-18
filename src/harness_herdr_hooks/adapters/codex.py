"""Codex 0.169.0 hook and existing-app-server adapter primitives.

Hook values are treated only as event identity hints. Backend identity must be
independently established by the caller before any routing or attachment.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
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
        "required": {"cwd", "hook_event_name", "model", "permission_mode", "session_id", "source", "transcript_path"},
        "strings": {"cwd", "hook_event_name", "model", "permission_mode", "session_id", "source"},
        "enums": {"hook_event_name": {"SessionStart"}, "permission_mode": {"default", "acceptEdits", "plan", "dontAsk", "bypassPermissions"}, "source": {"startup", "resume", "clear", "compact", "fork"}},
    },
    "SubagentStart": {
        "required": {"agent_id", "agent_type", "cwd", "hook_event_name", "model", "permission_mode", "session_id", "transcript_path", "turn_id"},
        "strings": {"agent_id", "agent_type", "cwd", "hook_event_name", "model", "permission_mode", "session_id", "turn_id"},
        "enums": {"hook_event_name": {"SubagentStart"}, "permission_mode": {"default", "acceptEdits", "plan", "dontAsk", "bypassPermissions"}},
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
    if schema is None or set(obj) != schema["required"]:
        raise ValueError("unsupported or incomplete Codex hook input")
    if any(not isinstance(obj[k], str) or not obj[k] for k in schema["strings"]):
        raise ValueError("invalid Codex hook string field")
    if any(obj[k] not in allowed for k, allowed in schema["enums"].items()):
        raise ValueError("unsupported Codex hook enum value")
    if obj["transcript_path"] is not None and not isinstance(obj["transcript_path"], str):
        raise ValueError("invalid transcript path field")
    if not verified_backend_id or not verified_backend_instance:
        raise ValueError("Codex backend identity and socket incarnation have not been independently verified")
    ident = CodexIdentity(profile, config_root, data_root, state_root,
                          verified_backend_id, obj["session_id"], verified_backend_instance)
    return HookEvent(name, ident, Path(obj["cwd"]), obj.get("turn_id"),
                     obj.get("agent_id"), obj.get("agent_type"))


class AppServerProxy:
    """Small JSON-RPC client over Codex's stdio proxy to an existing socket."""
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
        try:
            self._handshake(self._startup_deadline)
            initialized = self.request("initialize", {"clientInfo": {"name": "harness-herdr-hooks", "version": "0.1.0"},
                                                       "capabilities": {"experimentalApi": True}})
            if initialized.get("codexHome") != str(context.config_root.resolve()):
                raise ValueError("Codex app-server home does not match the selected profile")
            self.notify("initialized", {})
            self._in_startup = False
        except BaseException:
            self.close()
            raise

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
            raise RuntimeError("Codex proxy is unavailable")
        self._verify_socket()
        self._next_id += 1
        request_id = self._next_id
        wire = json.dumps({"jsonrpc": "2.0", "id": request_id, "method": method,
                           "params": dict(params)}, separators=(",", ":")).encode()
        if len(wire) > 1024 * 1024:
            raise ValueError("Codex request exceeds 1 MiB")
        deadline = min(time.monotonic() + self.timeout, self._startup_deadline) if self._in_startup else time.monotonic() + self.timeout
        self._send_frame(1, wire, deadline)
        while True:
            opcode, payload = self._recv_message(deadline)
            if opcode != 1:
                raise RuntimeError("Codex app-server sent a non-text JSON-RPC message")
            msg = json.loads(payload)
            if not isinstance(msg, dict) or msg.get("id") != request_id:
                continue
            if "error" in msg:
                raise RuntimeError("Codex app-server request failed")
            result = msg.get("result")
            if not isinstance(result, dict):
                raise RuntimeError("invalid Codex app-server response")
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
            raise RuntimeError("invalid Codex thread/list data")
        for thread in data:
            if not isinstance(thread, dict):
                raise RuntimeError("invalid Codex thread record")
            yield thread
        cursor = result.get("nextCursor")
        if not cursor:
            return
        if not isinstance(cursor, str) or cursor in seen:
            raise RuntimeError("invalid or cyclic Codex pagination cursor")
        seen.add(cursor)
    raise RuntimeError("Codex pagination limit exceeded")


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
            raise RuntimeError("invalid Codex thread/loaded/list data")
        loaded.update(data)
        cursor = result.get("nextCursor")
        if not cursor:
            return loaded
        if not isinstance(cursor, str) or cursor in seen:
            raise RuntimeError("invalid or cyclic Codex pagination cursor")
        seen.add(cursor)
    raise RuntimeError("Codex loaded-thread pagination limit exceeded")


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
                 proxy_factory: Callable[..., AppServerProxy] = AppServerProxy):
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
        self.executable = executable
        self.socket_path = socket_path
        self.proxy = proxy_factory(executable, socket_path, context=context)

    def _check_parent(self, parent: ParentBinding) -> None:
        if parent.context != self.context:
            raise ValueError("Codex parent context does not match selected backend")

    @staticmethod
    def _is_native_child(thread: Mapping[str, Any], parent_id: str) -> bool:
        source = thread.get("source")
        if not isinstance(source, dict) or set(source) != {"subAgent"}:
            return False
        sub = source["subAgent"]
        if not isinstance(sub, dict) or set(sub) != {"thread_spawn"}:
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

    def _read_thread(self, thread_id: str) -> Mapping[str, Any]:
        result = self.proxy.request("thread/read", {"threadId": thread_id, "includeTurns": False})
        thread = result.get("thread")
        if not isinstance(thread, dict):
            raise RuntimeError("invalid Codex thread/read response")
        return thread

    def can_attach_now(self, parent: ParentBinding, child: Session) -> bool:
        self._check_parent(parent)
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


__all__ = ["AppServerProxy", "CodexIdentity", "HookEvent", "attach_argv", "lifecycle", "list_loaded_threads", "list_threads", "parse_hook"]
