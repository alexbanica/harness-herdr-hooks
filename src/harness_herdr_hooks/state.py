"""Private, context-scoped state with advisory locking and atomic writes."""
from __future__ import annotations
import fcntl
import json
import os
import stat
import tempfile
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
        if not session_key or not generation or not turn_id or kind not in {"subagent", "independent"}:
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
    if kind not in {"subagent", "independent"}: raise ValueError("invalid binding kind")
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
    if data.get("ownership") not in {"created", "reused", "unknown"} or data.get("kind") not in {"subagent", "independent"}:
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
