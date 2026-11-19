"""Private, context-scoped state with advisory locking and atomic writes."""
from __future__ import annotations
import fcntl
import json
import os
import stat
import tempfile
import re
import math
import hashlib
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator
from .model import (context_to_dict, context_from_dict, parent_to_dict,
                    parent_from_dict, session_to_dict, session_from_dict)


class UnsafeState(RuntimeError):
    pass


class StateStore:
    def __init__(self, root: Path, namespace: str):
        if not namespace or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_" for c in namespace):
            raise ValueError("invalid state namespace")
        self.root = root / "harness-herdr-hooks" / namespace
        self._prepare()

    def _prepare(self) -> None:
        state_root = self.root.parent.parent
        if state_root.is_symlink():
            raise UnsafeState("user state root is a symlink")
        state_root.mkdir(mode=0o700, parents=True, exist_ok=True)
        st = state_root.stat()
        if st.st_uid != os.getuid() or not stat.S_ISDIR(st.st_mode):
            raise UnsafeState("user state root is not owner controlled")
        for path in (self.root.parent, self.root):
            if path.is_symlink():
                raise UnsafeState(f"symlink state path: {path}")
            path.mkdir(mode=0o700, exist_ok=True)
            st = path.stat()
            if st.st_uid != os.getuid() or not stat.S_ISDIR(st.st_mode):
                raise UnsafeState(f"state directory is not owner controlled: {path}")
            os.chmod(path, 0o700)

    @contextmanager
    def observing(self) -> Iterator[None]:
        """Exclusive process-lifetime lock for one observer in this context."""
        fd = self._open_private_lock("observer.lock")
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            yield
        finally:
            try: fcntl.flock(fd, fcntl.LOCK_UN)
            finally: os.close(fd)

    @contextmanager
    def task_observing(self) -> Iterator[None]:
        """Serialize local rollout snapshot/read/commit without provider calls."""
        fd = self._open_private_lock("task-observer.lock")
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            yield
        finally:
            try: fcntl.flock(fd, fcntl.LOCK_UN)
            finally: os.close(fd)

    def _open_private_lock(self, name: str) -> int:
        fd = os.open(self.root / name, os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0), 0o600)
        st = os.fstat(fd)
        if st.st_uid != os.getuid() or not stat.S_ISREG(st.st_mode) or stat.S_IMODE(st.st_mode) & 0o077:
            os.close(fd)
            raise UnsafeState(f"unsafe lock ownership or mode: {name}")
        return fd

    @contextmanager
    def locked(self) -> Iterator[dict[str, Any]]:
        lock = self.root / "state.lock"
        fd = self._open_private_lock("state.lock")
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            state_file = self.root / "state.json"
            if state_file.exists():
                if state_file.is_symlink() or state_file.stat().st_uid != os.getuid():
                    raise UnsafeState("unsafe state file ownership")
                if stat.S_IMODE(state_file.stat().st_mode) & 0o077:
                    raise UnsafeState("state file permissions are not private")
                data = json.loads(state_file.read_text(encoding="utf-8"))
                if not isinstance(data, dict) or data.get("schema") not in {1, 2}:
                    raise UnsafeState("unknown state schema")
                # Schema 1 records predate lifecycle generations. Preserve their
                # status/baseline history while marking ownership as unknown.
                if data["schema"] == 1:
                    data["schema"] = 2
                    data.setdefault("pending_created", [])
                    for record in data.get("records", {}).values():
                        if isinstance(record, dict):
                            record.setdefault("ownership", "unknown")
                            record.setdefault("kind", "subagent")
                            record.setdefault("generation", None)
                            record.setdefault("stop_hints", [])
                # Validate only the optional HHH-004 state owned by this
                # feature. Unknown predecessor fields remain untouched.
                if "task_discovery" in data:
                    _validate_task_discovery(data["task_discovery"])
            else:
                data = {"schema": 2, "baseline": [], "records": {}, "pending_created": []}
            yield data
            self._write(data)
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)

    def _write(self, data: dict[str, Any]) -> None:
        fd, tmp = tempfile.mkstemp(prefix=".state-", dir=self.root)
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, sort_keys=True, separators=(",", ":"))
                f.flush(); os.fsync(f.fileno())
            os.replace(tmp, self.root / "state.json")
            dfd = os.open(self.root, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
            try: os.fsync(dfd)
            finally: os.close(dfd)
        finally:
            try: os.unlink(tmp)
            except FileNotFoundError: pass

    def establish_baseline(self, session_keys: set[str]) -> None:
        with self.locked() as data:
            records = data.setdefault("records", {})
            pending = set(data.setdefault("pending_created", []))
            old = set(data.get("baseline", []))
            # A verified creation can arrive after an observer's first snapshot.
            # Keep it eligible until the coordinator has durably recorded it, so
            # a restart cannot turn that new session back into a baseline member.
            old.difference_update(pending)
            old.update(session_keys - set(records) - pending)
            data["baseline"] = sorted(old)
            data["pending_created"] = sorted(pending - set(records))
            data["baseline_ready"] = True

    def note_creation(self, session_key: str) -> None:
        """Keep a verified native creation eligible until it is recorded."""
        with self.locked() as data:
            records = data.setdefault("records", {})
            pending = set(data.setdefault("pending_created", []))
            if session_key in records:
                pending.discard(session_key)
            elif session_key not in pending:
                if len(pending) >= 1024: raise UnsafeState("pending creation limit reached")
                pending.add(session_key)
            data["pending_created"] = sorted(pending)
            baseline = set(data.get("baseline", []))
            if session_key in baseline:
                baseline.remove(session_key)
                data["baseline"] = sorted(baseline)

    def baseline_ready(self) -> bool:
        with self.locked() as data:
            return bool(data.get("baseline_ready"))

    def mark_suppressed(self, session_key: str, reason: str = "closed") -> None:
        with self.locked() as data:
            record = data["records"].setdefault(session_key, {})
            record.update(status="suppressed", reason=reason)

    def begin_generation(self, session_key: str, generation: str, *, turn_id: str,
                         kind: str = "subagent", parent_id: str | None = None) -> bool:
        """Record one explicit work generation; duplicate/old starts are no-ops.

        Generation IDs are native turn IDs. A caller must establish that a
        later generation is explicitly current before calling this method.
        """
        if not session_key or not generation or not turn_id or kind not in {"subagent", "independent", "standalone"}:
            raise ValueError("invalid lifecycle generation identity")
        with self.locked() as data:
            records = data.setdefault("records", {})
            record = records.setdefault(session_key, {})
            current = record.get("generation")
            if current == generation:
                return False
            terminal = record.get("terminal_generations", [])
            if generation in terminal:
                return False
            history = list(record.get("prior_generations", []))
            # Superseded native IDs stay in durable bounded history. Forgetting
            # one would let a delayed hook roll the record back to stale state.
            if any(isinstance(previous, dict) and previous.get("generation") == generation
                   for previous in history):
                return False
            if current is not None:
                previous = {k: record[k] for k in ("generation", "turn_id", "status", "turn_status", "binding_id", "ownership", "kind") if k in record}
                if previous not in history:
                    if len(history) >= 64:
                        raise UnsafeState("generation history limit reached")
                    history.append(previous)
            # A new generation is permitted only after caller observed a
            # distinct native turn. Reset pane status but retain old evidence.
            record.update(status="pending", generation=generation, turn_id=turn_id,
                          kind=kind, parent_id=parent_id, stop_hints=[],
                          ownership="unknown", prior_generations=history,
                          stop_reentered=False)
            record.pop("continuation_requested", None)
            record.pop("binding_id", None)
            return True

    def note_stop_hint(self, session_key: str, generation: str, turn_id: str,
                       *, stop_hook_active: bool) -> bool:
        """Persist a stop hint only for the currently recorded generation."""
        if not session_key or not generation or not turn_id or not isinstance(stop_hook_active, bool):
            raise ValueError("invalid stop hint")
        with self.locked() as data:
            record = data.setdefault("records", {}).get(session_key)
            if not isinstance(record, dict) or record.get("generation") != generation or record.get("turn_id") != turn_id:
                return False
            hints = record.setdefault("stop_hints", [])
            hint = {"generation": generation, "turn_id": turn_id,
                    "stop_hook_active": stop_hook_active}
            if hint not in hints:
                if len(hints) >= 64: raise UnsafeState("stop hint limit reached")
                hints.append(hint)
            record["stop_reentered"] = stop_hook_active
            record.pop("continuation_requested", None)
            return True

    def mark_generation_terminal(self, session_key: str, generation: str,
                                 turn_id: str, status: str) -> bool:
        """Persist backend-confirmed terminal metadata for the exact current turn."""
        if status not in {"completed", "interrupted", "failed"}:
            return False
        with self.locked() as data:
            record = data.setdefault("records", {}).get(session_key)
            if not isinstance(record, dict) or (record.get("generation"), record.get("turn_id")) != (generation, turn_id):
                return False
            terminal = list(record.get("terminal_generations", []))
            if generation not in terminal:
                if len(terminal) >= 64: terminal = terminal[-63:]
                terminal.append(generation)
            record["terminal_generations"] = terminal
            record["turn_status"] = status
            # Terminal metadata can arrive after an explicit manual suppression.
            # Keep suppression authoritative while retaining the backend result.
            if record.get("status") != "suppressed":
                record["status"] = "finished"
            return True

    def generation(self, session_key: str) -> dict[str, Any] | None:
        """Read a shallow snapshot of the persisted lifecycle record."""
        with self.locked() as data:
            value = data.setdefault("records", {}).get(session_key)
            return dict(value) if isinstance(value, dict) else None

    def record(self, session_key: str) -> dict[str, Any] | None:
        with self.locked() as data:
            return data["records"].get(session_key)

    def reconcile_standalone(self, session_key: str, event_key: str,
                             expected_binding: str, status: str, **fields: Any) -> bool:
        """Apply an external observation only to its unchanged durable claim."""
        if status not in {"claimed", "attached", "suppressed", "pending"}:
            raise ValueError("invalid standalone reconciliation status")
        allowed = {"title", "ownership", "binding_id", "reason", "attempts"}
        if set(fields) - allowed:
            raise ValueError("invalid standalone reconciliation fields")
        with self.locked() as data:
            record = data.setdefault("records", {}).get(session_key)
            discovery = data.get("task_discovery", {})
            authority = discovery.get("authority") or {}
            candidate = next((item for item in discovery.get("pending", [])
                              if item.get("event_key") == event_key and item.get("status") == "verified"), None)
            terminal = next((item for item in discovery.get("outcomes", [])
                             if item.get("event_key") == event_key and item.get("status") == "attached"), None)
            current_association = (hashlib.sha256(json.dumps(
                {"authority": authority, "candidate": candidate}, sort_keys=True,
                separators=(",", ":")).encode()).hexdigest() if candidate is not None
                else record.get("standalone_association_sha256") if terminal is not None and isinstance(record, dict)
                else None)
            authority_hash = hashlib.sha256(json.dumps(
                authority, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
            if (not isinstance(record, dict)
                    or record.get("standalone_event_key") != event_key
                    or record.get("standalone_association_sha256") != current_association
                    or record.get("standalone_authority_sha256") != authority_hash
                    or (candidate or terminal or {}).get("child_id") != record.get("standalone_child_id")
                    or record.get("binding_id") != expected_binding
                    or record.get("status") not in {"claimed", "attached"}):
                return False
            record.update(fields)
            record["status"] = status
            return True

    def task_discovery(self) -> dict[str, Any]:
        """Return a deep JSON snapshot of the bounded private discovery state."""
        with self.locked() as data:
            value = data.get("task_discovery", _empty_task_discovery())
            return json.loads(json.dumps(value))

    def commit_task_records(self, cursor: dict[str, Any], events: list[Any], *,
                            parent: dict[str, Any], context: dict[str, Any],
                            destination: dict[str, Any], now: float) -> tuple[int, bool]:
        """Atomically advance a reader cursor with its validated ID-only events.

        The caller supplies already-validated U10 events and bounded authority
        pins. Event objects are read by attributes to avoid coupling to parser
        internals. No transcript payload is accepted or persisted.
        """
        _validate_safe_object(cursor, "cursor", max_keys=7)
        _validate_authority(parent, context, destination)
        if not isinstance(now, (int, float)) or isinstance(now, bool) or not math.isfinite(now) or now < 0:
            raise ValueError("invalid task discovery timestamp")
        with self.locked() as data:
            state = data.setdefault("task_discovery", _empty_task_discovery())
            _validate_task_discovery(state)
            # Pin changes revoke pending candidates; they cannot migrate to a
            # different parent, backend incarnation, or pane destination.
            authority = {"parent": parent, "context": context,
                         "destination": destination}
            old = state.get("authority")
            if old is not None and old != authority:
                state["pending"] = []
            pending = state.setdefault("pending", [])
            outcomes = state.setdefault("outcomes", [])
            keys = {x["event_key"] for x in pending} | {x["event_key"] for x in outcomes}
            added = 0
            overflow = False
            for event in events:
                ep = getattr(event, "parent_id", None) or getattr(event, "parent_thread_id", None)
                turn = getattr(event, "turn_id", None)
                item = getattr(event, "item_id", None)
                child = getattr(event, "child_id", None)
                cwd_hash = getattr(event, "cwd_sha256", None)
                # Parser output is an input boundary too: skip one malformed
                # association without preventing valid siblings or poisoning
                # future state reads.
                if (any(not isinstance(x, str) or not x or len(x) > 512
                        for x in (ep, turn, item, child))
                        or ep != parent.get("parent_id") or child == ep):
                    continue
                if cwd_hash is not None and (not isinstance(cwd_hash, str) or not re.fullmatch(r"[0-9a-f]{64}", cwd_hash)):
                    continue
                key = hashlib.sha256(json.dumps([ep, turn, item], separators=(",", ":")).encode()).hexdigest()
                if key in keys:
                    continue
                if len(pending) >= 128:
                    # The read cursor and bounded queue must commit together. A
                    # burst beyond capacity is skipped explicitly, without
                    # retaining event payloads or rolling the cursor back.
                    overflow = True
                    continue
                pending.append({"event_key": key, "parent_id": ep,
                                "turn_id": turn, "item_id": item,
                                "child_id": child, "cwd_sha256": cwd_hash,
                                "context": context, "destination": destination,
                                "status": "pending", "attempts": 0,
                                "first_seen": float(now), "retry_after": float(now)})
                keys.add(key); added += 1
            if overflow:
                diagnostic_key = hashlib.sha256(json.dumps(
                    ["bounded-overflow", cursor], sort_keys=True,
                    separators=(",", ":")).encode()).hexdigest()
                state["outcomes"] = [x for x in outcomes if x["event_key"] != diagnostic_key]
                if len(state["outcomes"]) >= 256:
                    state["outcomes"] = state["outcomes"][-255:]
                state["outcomes"].append({"event_key": diagnostic_key,
                                          "child_id": "bounded-overflow",
                                          "status": "rejected"})
            state.update(cursor=cursor, authority=authority)
            _validate_task_discovery(state)
            return added, overflow

    def update_task_candidate(self, event_key: str, *, status: str,
                              now: float, retry: bool = False,
                              reason: str = "") -> bool:
        """Persist bounded retry/outcome state; never stores external text."""
        if status not in {"pending", "verified", "claimed", "attached", "rejected", "failed"}:
            raise ValueError("invalid task candidate status")
        if not isinstance(now, (int, float)) or isinstance(now, bool) or not math.isfinite(now) or now < 0:
            raise ValueError("invalid task discovery timestamp")
        if reason not in {"", "metadata unavailable", "not attachable", "context changed", "attachment failed"}:
            raise ValueError("invalid task candidate reason")
        with self.locked() as data:
            state = data.setdefault("task_discovery", _empty_task_discovery())
            _validate_task_discovery(state)
            pending = state["pending"]
            for candidate in pending:
                if candidate["event_key"] != event_key:
                    continue
                candidate["status"] = status
                candidate["reason"] = reason
                if retry:
                    attempts = candidate["attempts"] + 1
                    if attempts >= 3 or float(now) - candidate["first_seen"] >= 30:
                        status = candidate["status"] = "rejected"
                        candidate["reason"] = "metadata unavailable"
                    candidate["attempts"] = min(attempts, 3)
                    candidate["retry_after"] = float(now)
                if status in {"attached", "rejected", "failed"}:
                    outcome = {"event_key": event_key,
                               "child_id": candidate["child_id"],
                               "status": status}
                    state["outcomes"] = [x for x in state["outcomes"] if x["event_key"] != event_key]
                    if len(state["outcomes"]) >= 256:
                        state["outcomes"] = state["outcomes"][-255:]
                    state["outcomes"].append(outcome)
                    pending.remove(candidate)
                return True
            return False

    def reserve_task_verification(self, event_key: str, *, now: float) -> bool:
        """Reserve one bounded metadata lookup; the third reservation may succeed."""
        if not isinstance(now, (int, float)) or isinstance(now, bool) or not math.isfinite(now) or now < 0:
            raise ValueError("invalid task verification timestamp")
        with self.locked() as data:
            state = data.setdefault("task_discovery", _empty_task_discovery())
            _validate_task_discovery(state)
            for candidate in state["pending"]:
                if candidate["event_key"] != event_key or candidate["status"] not in {"pending", "verified"}:
                    continue
                if candidate["attempts"] >= 3 or float(now) - candidate["first_seen"] >= 30:
                    candidate["status"] = "rejected"
                    candidate["reason"] = "metadata unavailable"
                    outcome = {"event_key": event_key, "child_id": candidate["child_id"], "status": "rejected"}
                    state["outcomes"] = [x for x in state["outcomes"] if x["event_key"] != event_key]
                    if len(state["outcomes"]) >= 256: state["outcomes"] = state["outcomes"][-255:]
                    state["outcomes"].append(outcome)
                    state["pending"].remove(candidate)
                    return False
                candidate["attempts"] += 1
                candidate["retry_after"] = float(now)
                return True
            return False
    def pending_cleanup_records(self) -> dict[str, dict[str, Any]]:
        """Snapshot persisted attached generations that may need terminal reconciliation."""
        with self.locked() as data:
            return {key: dict(value) for key, value in data.get("records", {}).items()
                    if isinstance(value, dict) and value.get("status") in {"attached", "finished"}
                    and value.get("ownership") == "created"
                    and value.get("kind", "subagent") == "subagent"
                    and value.get("generation") and value.get("turn_id")
                    and value.get("binding_id") and value.get("status") != "suppressed"
                    and not (isinstance(value.get("cleanup"), dict)
                             and value["cleanup"].get("outcome") in {"closed", "manual-close"})}


def _binding_path(root: Path, opaque_id: str, *, create: bool) -> Path:
    if not opaque_id or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_" for c in opaque_id):
        raise ValueError("invalid opaque binding ID")
    directory = root / "harness-herdr-hooks" / "bindings"
    if create:
        store = StateStore(root, "bindings")
        return store.root / (opaque_id + ".json")
    # Reads must not create directories/files and reject symlinked components.
    for p in (root, directory.parent, directory):
        if p.is_symlink(): raise UnsafeState("symlink binding state path")
    path = directory / (opaque_id + ".json")
    if not path.exists(): raise FileNotFoundError(path)
    st = path.lstat()
    if not stat.S_ISREG(st.st_mode) or st.st_uid != os.getuid() or stat.S_IMODE(st.st_mode) & 0o077:
        raise UnsafeState("unsafe binding record")
    return path


def save_binding(root: Path, opaque_id: str, record: dict[str, Any]) -> None:
    allowed = {"parent", "child", "pane_id", "backend_pid", "server_socket", "entrypoint", "shell_pid"}
    optional = {"outcome", "ownership", "kind", "generation", "turn_id", "stop_hints", "close_suppressed"}
    if not allowed <= set(record) or set(record) - allowed - optional: raise ValueError("binding fields do not match schema")
    if not isinstance(record["parent"], dict) or not isinstance(record["child"], dict): raise ValueError("binding identity missing")
    from .model import parent_from_dict, session_from_dict
    parent_from_dict(record["parent"]); session_from_dict(record["child"])
    for key in ("pane_id", "server_socket", "entrypoint"):
        value = record[key]
        if value is not None and not isinstance(value, str): raise ValueError("invalid binding field")
    for key in ("backend_pid", "shell_pid"):
        if record[key] is not None and (not isinstance(record[key], int) or record[key] <= 0): raise ValueError("invalid binding process ID")
    if record["entrypoint"] is not None and not Path(record["entrypoint"]).is_absolute(): raise ValueError("entrypoint must be absolute")
    if "outcome" in record: _validate_outcome(record["outcome"])
    ownership = record.get("ownership", "unknown")
    if ownership not in {"created", "reused", "unknown"}: raise ValueError("invalid pane ownership provenance")
    kind = record.get("kind", "subagent")
    if kind not in {"subagent", "independent", "standalone"}: raise ValueError("invalid binding kind")
    for field in ("generation", "turn_id"):
        if record.get(field) is not None and (not isinstance(record[field], str) or not record[field]):
            raise ValueError("invalid binding generation")
    if "stop_hints" in record:
        hints = record["stop_hints"]
        if not isinstance(hints, list) or len(hints) > 64 or any(
            not isinstance(h, dict) or set(h) != {"generation", "turn_id", "stop_hook_active"}
            or not all(isinstance(h[k], str) and h[k] for k in ("generation", "turn_id"))
            or not isinstance(h["stop_hook_active"], bool) for h in hints
        ): raise ValueError("invalid stop hint records")
    if "close_suppressed" in record and not isinstance(record["close_suppressed"], bool):
        raise ValueError("invalid close suppression flag")
    path = _binding_path(root, opaque_id, create=True)
    if path.exists():
        st = path.lstat()
        if not stat.S_ISREG(st.st_mode) or st.st_uid != os.getuid() or stat.S_IMODE(st.st_mode) & 0o077:
            raise UnsafeState("unsafe existing binding record")
        prior = json.loads(path.read_text(encoding="utf-8"))
        if "outcome" in prior and "outcome" not in record: record = {**record, "outcome": prior["outcome"]}
        # Ownership is monotonic: a record already proven reused/unknown cannot
        # become close-owned through a later rewrite of the same binding ID.
        if prior.get("ownership", "unknown") != "created" and record.get("ownership") == "created":
            record = {**record, "ownership": prior.get("ownership", "unknown")}
        if prior.get("outcome", {}).get("status") == "attached" and record.get("outcome", {}).get("status") != "attached":
            record = {**record, "outcome": prior["outcome"]}
    fd, tmp = tempfile.mkstemp(prefix=".binding-", dir=path.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump({"schema": 2, "ownership": "unknown", "kind": "subagent",
                       "generation": None, "turn_id": None, "stop_hints": [],
                       "close_suppressed": False, **record}, f, sort_keys=True, separators=(",", ":")); f.flush(); os.fsync(f.fileno())
        os.replace(tmp, path)
        dfd = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try: os.fsync(dfd)
        finally: os.close(dfd)
    finally:
        try: os.unlink(tmp)
        except FileNotFoundError: pass


def load_existing_binding(root: Path, opaque_id: str) -> dict[str, Any]:
    path = _binding_path(root, opaque_id, create=False)
    data = json.loads(path.read_text(encoding="utf-8"))
    required = {"schema", "parent", "child", "pane_id", "backend_pid", "server_socket", "entrypoint", "shell_pid"}
    allowed = required | {"outcome", "ownership", "kind", "generation", "turn_id", "stop_hints", "close_suppressed"}
    if not isinstance(data, dict) or data.get("schema") not in {1, 2} or not required <= set(data) or set(data) - allowed:
        raise UnsafeState("invalid binding record schema")
    if data["schema"] == 1:
        data.update(ownership="unknown", kind="subagent", generation=None,
                    turn_id=None, stop_hints=[], close_suppressed=False)
    if data.get("ownership") not in {"created", "reused", "unknown"} or data.get("kind") not in {"subagent", "independent", "standalone"}:
        raise UnsafeState("invalid binding ownership metadata")
    if "outcome" in data: _validate_outcome(data["outcome"])
    return data


def binding_is_close_owned(record: dict[str, Any]) -> bool:
    """Only a positive, unsuppressed subagent creation grants pane close rights."""
    return (record.get("schema") == 2 and record.get("ownership") == "created"
            and record.get("kind", "subagent") == "subagent"
            and record.get("close_suppressed") is not True)


def _validate_outcome(outcome: object) -> None:
    if not isinstance(outcome, dict) or set(outcome) != {"status", "pid"} or outcome.get("status") not in {"verifying", "failed-before-exec", "exec-started", "attached"}:
        raise ValueError("invalid attachment outcome")
    if outcome["pid"] is not None and (not isinstance(outcome["pid"], int) or outcome["pid"] <= 0): raise ValueError("invalid attachment process ID")


def update_binding_outcome(root: Path, opaque_id: str, status: str, pid: int | None = None) -> None:
    _validate_outcome({"status": status, "pid": pid})
    path = _binding_path(root, opaque_id, create=False)
    lock = path.with_suffix(".lock")
    fd = os.open(lock, os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0), 0o600)
    try:
        st = os.fstat(fd)
        if st.st_uid != os.getuid() or not stat.S_ISREG(st.st_mode) or stat.S_IMODE(st.st_mode) & 0o077: raise UnsafeState("unsafe binding lock")
        fcntl.flock(fd, fcntl.LOCK_EX)
        data = load_existing_binding(root, opaque_id)
        old = data.get("outcome", {}).get("status")
        if old == "attached" and status != "attached": return
        data["outcome"] = {"status": status, "pid": pid}
        save_binding(root, opaque_id, {k: v for k, v in data.items() if k != "schema"})
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN); os.close(fd)


def _empty_task_discovery() -> dict[str, Any]:
    return {"cursor": None, "authority": None, "pending": [], "outcomes": []}


def _validate_safe_object(value: object, name: str, *, max_keys: int) -> None:
    if not isinstance(value, dict) or len(value) > max_keys:
        raise ValueError(f"invalid {name} object")
    for key, item in value.items():
        if not isinstance(key, str) or not key or len(key) > 64: raise ValueError(f"invalid {name} key")
        if isinstance(item, str):
            if len(item) > 512: raise ValueError(f"oversized {name} value")
        elif isinstance(item, bool) or item is None: continue
        elif isinstance(item, int) and 0 <= item <= 2**63 - 1: continue
        elif isinstance(item, dict): _validate_safe_object(item, name, max_keys=24)
        elif isinstance(item, list) and len(item) <= 16 and all(isinstance(x, (str, int)) and not isinstance(x, bool) for x in item):
            if any(isinstance(x, str) and len(x) > 512 for x in item): raise ValueError(f"oversized {name} value")
        else: raise ValueError(f"invalid {name} value")


def _validate_task_discovery(value: object) -> None:
    if not isinstance(value, dict) or set(value) != {"cursor", "authority", "pending", "outcomes"}:
        raise UnsafeState("invalid task discovery state fields")
    if value["cursor"] is not None:
        _validate_safe_object(value["cursor"], "cursor", max_keys=7)
        if set(value["cursor"]) != {"device", "inode", "offset", "parent_id", "path", "observed_size", "skip_to_newline"}:
            raise UnsafeState("invalid task cursor fields")
        c = value["cursor"]
        if not all(isinstance(c[k], int) and not isinstance(c[k], bool) and c[k] >= 0 for k in ("device", "inode", "offset", "observed_size")) or c["observed_size"] < c["offset"] or not isinstance(c["skip_to_newline"], bool) or not isinstance(c["parent_id"], str) or not isinstance(c["path"], str) or not Path(c["path"]).is_absolute():
            raise UnsafeState("invalid task cursor values")
    authority = value["authority"]
    if authority is not None:
        if not isinstance(authority, dict) or set(authority) != {"parent", "context", "destination"}: raise UnsafeState("invalid task discovery authority")
        _validate_authority(authority["parent"], authority["context"], authority["destination"])
    pending, outcomes = value["pending"], value["outcomes"]
    if not isinstance(pending, list) or len(pending) > 128 or not isinstance(outcomes, list) or len(outcomes) > 256: raise UnsafeState("task discovery state limit exceeded")
    seen: set[str] = set()
    required = {"event_key", "parent_id", "turn_id", "item_id", "child_id", "cwd_sha256", "context", "destination", "status", "attempts", "first_seen", "retry_after"}
    for c in pending:
        if not isinstance(c, dict) or set(c) - required - {"reason"} or not required <= set(c): raise UnsafeState("invalid pending task candidate")
        for key in ("event_key", "parent_id", "turn_id", "item_id", "child_id"):
            if not isinstance(c[key], str) or not c[key] or len(c[key]) > 512: raise UnsafeState("invalid pending task identity")
        if c["event_key"] in seen: raise UnsafeState("duplicate pending task event")
        seen.add(c["event_key"])
        digest = c["cwd_sha256"]
        if digest is not None and (not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest)): raise UnsafeState("invalid pending cwd digest")
        if c["status"] not in {"pending", "verified", "claimed"} or not isinstance(c["attempts"], int) or isinstance(c["attempts"], bool) or not 0 <= c["attempts"] <= 3: raise UnsafeState("invalid pending task state")
        if any(not isinstance(c[x], (int, float)) or isinstance(c[x], bool) or not math.isfinite(c[x]) or c[x] < 0 for x in ("first_seen", "retry_after")): raise UnsafeState("invalid pending task retry time")
        _validate_safe_object(c["context"], "context", max_keys=24)
        _validate_safe_object(c["destination"], "destination", max_keys=24)
        if "reason" in c and c["reason"] not in {"", "metadata unavailable", "not attachable", "context changed", "attachment failed"}: raise UnsafeState("invalid task candidate reason")
    for o in outcomes:
        if not isinstance(o, dict) or set(o) != {"event_key", "child_id", "status"} or o.get("status") not in {"attached", "rejected", "failed"} or not all(isinstance(o[k], str) and o[k] for k in o): raise UnsafeState("invalid task discovery outcome")


def _validate_authority(parent: object, context: object, destination: object) -> None:
    shapes = ((parent, {"parent_id", "path", "device", "inode", "owner_uid"}),
              (context, {"profile", "backend_id", "backend_instance", "session_id"}),
              (destination, {"server_id", "workspace_id", "tab_id", "pane_id"}))
    for value, allowed in shapes:
        if not isinstance(value, dict) or set(value) - allowed or not value:
            raise ValueError("invalid task discovery authority fields")
        if any(not isinstance(k, str) for k in value): raise ValueError("invalid task discovery authority")
        for k, item in value.items():
            if k in {"device", "inode", "owner_uid"}:
                if not isinstance(item, int) or isinstance(item, bool) or item < 0: raise ValueError("invalid task discovery authority pin")
            elif not isinstance(item, str) or not item or len(item) > 512: raise ValueError("invalid task discovery authority pin")
    if "path" in parent and not Path(parent["path"]).is_absolute(): raise ValueError("parent binding path must be absolute")
