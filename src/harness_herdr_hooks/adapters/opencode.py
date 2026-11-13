"""Strict OpenCode 1.19.5 adapter primitives.

This module deliberately does not infer identity from event payloads. The caller
must supply values resolved from the selected OpenCode server/session API.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
import ipaddress
import shutil
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlsplit

from ..model import Context, Event, Harness, Lifecycle, Session


@dataclass(frozen=True, slots=True)
class OpenCodeIdentity:
    """Values proven by the native OpenCode client/server, not ambient env vars."""

    profile: str
    config_root: Path
    data_root: Path
    state_root: Path
    server_url: str
    session_id: str
    process_id: int

    def context(self) -> Context:
        if not all((self.profile, self.session_id)) or self.process_id <= 0:
            raise ValueError("OpenCode profile and session identity are required")
        parsed = urlsplit(self.server_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.username or parsed.password:
            raise ValueError("OpenCode server URL must be an authenticated-free HTTP(S) origin")
        if parsed.query or parsed.fragment:
            raise ValueError("OpenCode server URL cannot include query or fragment data")
        return Context(Harness.OPENCODE, self.profile, self.config_root, self.data_root,
                       self.state_root, self.server_url.rstrip("/"), self.session_id)


class OpenCodeAdapter:
    """Maps already-resolved native session records into common records."""

    @staticmethod
    def event(identity: OpenCodeIdentity, kind: str, *, title: str | None = None,
              cwd: Path | None = None, parent_session_id: str | None = None) -> Event:
        if kind not in {"session.created", "session.updated", "session.status", "session.idle"}:
            raise ValueError("unsupported OpenCode lifecycle event")
        context = identity.context()
        return Event(context, kind, title, cwd, parent_session_id)

    @staticmethod
    def session(identity: OpenCodeIdentity, *, parent_session_id: str | None,
                title: str | None, cwd: Path, running: bool | None,
                attachable: bool, observed_at: float, ancestry: tuple[str, ...] = ()) -> Session:
        # Unknown native status is not treated as running.
        lifecycle = Lifecycle.RUNNING if running is True else (
            Lifecycle.FINISHED if running is False else Lifecycle.UNKNOWN)
        return Session(identity.context(), parent_session_id, title, cwd, lifecycle,
                       bool(attachable), observed_at, ancestry)

    @staticmethod
    def attach_argv(server_url: str, session_id: str) -> list[str]:
        """Return the pinned existing-session command, without a prompt or auth."""
        parsed = urlsplit(server_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.username or parsed.password:
            raise ValueError("verified OpenCode server URL required")
        if parsed.query or parsed.fragment or not session_id or any(c.isspace() for c in session_id):
            raise ValueError("invalid OpenCode URL or session ID")
        return ["opencode", "attach", server_url, "--session", session_id, "--mini"]

    @staticmethod
    def parse_bridge(payload: str | bytes | Mapping[str, Any]) -> tuple[Event, Session | None, Mapping[str, str] | None]:
        """Parse the plugin's allowlisted v1 envelope; never treats hints as proof."""
        obj = json.loads(payload) if isinstance(payload, (str, bytes)) else dict(payload)
        if not isinstance(obj, dict) or obj.get("schema_version") != 1 or obj.get("harness") != "opencode":
            raise ValueError("unsupported OpenCode bridge envelope")
        backend, roots = obj.get("backend"), obj.get("roots")
        native = obj.get("session")
        kind = obj.get("event_kind")
        if not isinstance(backend, dict) or not isinstance(roots, dict) or not isinstance(native, dict):
            raise ValueError("incomplete OpenCode bridge envelope")
        server_url, process_id = backend.get("server_url"), backend.get("pid")
        session_id = native.get("id")
        if not isinstance(server_url, str) or not isinstance(process_id, int) or isinstance(process_id, bool):
            raise ValueError("OpenCode backend identity hint is unavailable")
        if not isinstance(session_id, str) or not session_id or kind not in {
            "session.created", "session.updated", "session.status", "session.idle"
        }:
            raise ValueError("OpenCode event identity is unavailable")
        config_root, data_root, state_root = (roots.get(key) for key in ("config_dir", "data_dir", "state_dir"))
        if not all(isinstance(path, str) and path for path in (config_root, data_root, state_root)):
            raise ValueError("OpenCode native root hints are incomplete")
        identity = OpenCodeIdentity(str(config_root), Path(config_root), Path(data_root), Path(state_root),
                                    server_url, session_id, process_id)
        title = native.get("title") if isinstance(native.get("title"), str) else None
        directory = native.get("directory") if isinstance(native.get("directory"), str) else None
        if not directory:
            raise ValueError("OpenCode session directory is unavailable")
        parent_id = native.get("parent_id") if isinstance(native.get("parent_id"), str) else None
        event = OpenCodeAdapter.event(identity, kind, title=title,
                                      cwd=Path(directory) if directory else None,
                                      parent_session_id=parent_id)
        session = None
        if directory:
            status = obj.get("status")
            status_kind = status.get("type") if isinstance(status, dict) else None
            # OpenCode idle means no active turn, not a finished session.
            running = True if status_kind == "busy" else None
            session = OpenCodeAdapter.session(
                identity, parent_session_id=parent_id, title=title, cwd=Path(directory),
                running=running, attachable=running is True,
                observed_at=float(native.get("created_at", 0) or 0),
            )
        return event, session, roots


class _NoBackendRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        # Backend identity authorizes this endpoint, never a redirect target.
        return None


class OpenCodeRuntimeAdapter:
    """Bounded, read-only client for the pinned OpenCode legacy session API."""

    MAX_RESPONSE = 1_048_576
    MAX_SESSIONS = 10_000

    def __init__(self, context: Context, backend_pid: int, *, herdr_client: Any = None,
                 timeout: float = 5.0):
        if context.harness != Harness.OPENCODE or not isinstance(backend_pid, int) or backend_pid <= 0:
            raise ValueError("OpenCode context and backend PID are required")
        try:
            url = context.backend_id
            parsed = urlsplit(url)
            if (parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password
                    or parsed.query or parsed.fragment):
                raise ValueError
            host = parsed.hostname
            if host != "localhost" and not ipaddress.ip_address(host).is_loopback:
                raise ValueError
        except (ValueError, TypeError):
            raise ValueError("OpenCode backend must be the bound loopback server and matching PID") from None
        self.context, self.backend_pid, self.server_url = context, backend_pid, url.rstrip("/")
        self.herdr_client = herdr_client
        self.timeout = min(max(float(timeout), 0.1), 5.0)
        self._opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoBackendRedirect())

    def close(self) -> None:
        """No persistent socket or helper is owned by this read-only adapter."""
        return None

    def _get(self, route: str, query: Mapping[str, str] | None = None) -> Any:
        url = self.server_url + route
        if query:
            url += "?" + urllib.parse.urlencode(query)
        request = urllib.request.Request(url, method="GET", headers={"Accept": "application/json"})
        try:
            with self._opener.open(request, timeout=self.timeout) as response:
                data = response.read(self.MAX_RESPONSE + 1)
            if len(data) > self.MAX_RESPONSE:
                raise ValueError("OpenCode response exceeds limit")
            return json.loads(data)
        except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
            raise RuntimeError("OpenCode native API unavailable") from exc

    @staticmethod
    def _record(value: Any, expected_id: str | None = None) -> dict[str, Any]:
        if not isinstance(value, dict) or not isinstance(value.get("id"), str):
            raise ValueError("invalid OpenCode session record")
        if expected_id is not None and value["id"] != expected_id:
            raise ValueError("OpenCode returned a different session")
        if not isinstance(value.get("directory"), str) or not value["directory"]:
            raise ValueError("OpenCode session directory unavailable")
        if not isinstance(value.get("title"), str):
            raise ValueError("OpenCode session title unavailable")
        return value

    def _get_session(self, session_id: str) -> dict[str, Any]:
        return self._record(self._get("/session/" + urllib.parse.quote(session_id, safe="")), session_id)

    @staticmethod
    def _status(value: Any) -> str | None:
        if not isinstance(value, dict):
            return None
        kind = value.get("type")
        return kind if kind in {"busy", "idle", "retry"} else None

    def _list_directory(self, directory: str) -> tuple[list[dict[str, Any]], dict[str, str]]:
        query = {"directory": directory}
        raw = self._get("/session", query)
        statuses = self._get("/session/status", query)
        if (not isinstance(raw, list) or len(raw) > self.MAX_SESSIONS or not isinstance(statuses, dict)
                or len(statuses) > self.MAX_SESSIONS):
            raise ValueError("invalid or oversized OpenCode session list")
        records = [self._record(item) for item in raw]
        # Guard against a server ignoring the directory query.
        if any(item["directory"] != directory for item in records):
            raise ValueError("OpenCode returned sessions outside the selected directory")
        return records, {key: status for key, value in statuses.items()
                         if isinstance(key, str) and (status := self._status(value)) is not None}

    @staticmethod
    def _ancestors(record: Mapping[str, Any], by_id: Mapping[str, Mapping[str, Any]]) -> tuple[str, ...]:
        chain: list[str] = []
        current = record
        seen = {str(record.get("id"))}
        for _ in range(32):
            parent_id = current.get("parentID")
            if not isinstance(parent_id, str) or not parent_id or parent_id in seen:
                break
            chain.append(parent_id)
            seen.add(parent_id)
            current = by_id.get(parent_id, {})
            if not current:
                break
        return tuple(chain)

    def _session_model(self, record: Mapping[str, Any], status: str | None,
                       ancestry: tuple[str, ...] = ()) -> Session:
        running = status == "busy"
        lifecycle = Lifecycle.RUNNING if running else Lifecycle.UNKNOWN
        sid = str(record["id"])
        child_context = Context(self.context.harness, self.context.profile, self.context.config_root,
                                self.context.data_root, self.context.state_root, self.context.backend_id, sid,
                                self.context.backend_instance)
        observed_at = time.time()
        return Session(child_context, record.get("parentID") if isinstance(record.get("parentID"), str) else None,
                       record["title"], Path(record["directory"]), lifecycle, running, observed_at, ancestry)

    def sessions(self, parent: Any) -> list[Session]:
        if not self.verify_parent(parent):
            raise RuntimeError("OpenCode parent is not bound to the verified Herdr pane")
        parent_record = self._get_session(parent.context.session_id)
        records, statuses = self._list_directory(parent_record["directory"])
        by_id = {record["id"]: record for record in records}
        result = []
        for record in records:
            if record["id"] == parent.context.session_id:
                continue
            ancestry = self._ancestors(record, by_id)
            if parent.context.session_id not in ancestry:
                continue
            result.append(self._session_model(record, statuses.get(record["id"]), ancestry))
        return result

    def verify_parent(self, parent: Any, *, backend_pid: int | None = None) -> bool:
        return bool(self.herdr_client and self.herdr_client.verify_parent(
            parent, self.backend_pid if backend_pid is None else backend_pid))

    def can_attach_now(self, parent: Any, child: Session) -> bool:
        try:
            if self._native_executable() is None:
                return False
            if not self.verify_parent(parent):
                return False
            parent_record = self._get_session(parent.context.session_id)
            current = self._get_session(child.context.session_id)
            if current["directory"] != parent_record["directory"]:
                return False
            records, statuses = self._list_directory(parent_record["directory"])
            by_id = {record["id"]: record for record in records}
            record = by_id.get(current["id"])
            if not record or parent.context.session_id not in self._ancestors(record, by_id):
                return False
            return statuses.get(current["id"]) == "busy"
        except (RuntimeError, ValueError, OSError):
            return False

    def attach_argv(self, child: Session) -> list[str]:
        executable = self._native_executable()
        if executable is None:
            raise ValueError("OpenCode executable is unavailable")
        return [executable, "attach", self.server_url, "--session", child.context.session_id, "--mini"]

    @staticmethod
    def _native_executable() -> str | None:
        """Resolve the selected native CLI without reading or changing its config."""
        found = shutil.which("opencode")
        if not found:
            return None
        try:
            resolved = Path(found).resolve(strict=True)
        except (OSError, RuntimeError):
            return None
        return str(resolved) if resolved.is_file() else None
