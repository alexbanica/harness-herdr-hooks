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
                if not isinstance(data, dict) or data.get("schema") != 1:
                    raise UnsafeState("unknown state schema")
            else:
                data = {"schema": 1, "baseline": [], "records": {}}
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
            old.update(session_keys - set(records) - pending)
            data["baseline"] = sorted(old)
            data["pending_created"] = sorted(pending - session_keys)
            data["baseline_ready"] = True

    def note_creation(self, session_key: str) -> None:
        """Remember a verified native creation event until its first baseline."""
        with self.locked() as data:
            pending = set(data.setdefault("pending_created", []))
            if session_key not in pending:
                if len(pending) >= 1024: raise UnsafeState("pending creation limit reached")
                pending.add(session_key)
            data["pending_created"] = sorted(pending)

    def baseline_ready(self) -> bool:
        with self.locked() as data:
            return bool(data.get("baseline_ready"))

    def mark_suppressed(self, session_key: str, reason: str = "closed") -> None:
        with self.locked() as data:
            data["records"][session_key] = {"status": "suppressed", "reason": reason}

    def record(self, session_key: str) -> dict[str, Any] | None:
        with self.locked() as data:
            return data["records"].get(session_key)


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
    if set(record) not in (allowed, allowed | {"outcome"}): raise ValueError("binding fields do not match schema")
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
    path = _binding_path(root, opaque_id, create=True)
    if path.exists():
        st = path.lstat()
        if not stat.S_ISREG(st.st_mode) or st.st_uid != os.getuid() or stat.S_IMODE(st.st_mode) & 0o077:
            raise UnsafeState("unsafe existing binding record")
        prior = json.loads(path.read_text(encoding="utf-8"))
        if "outcome" in prior and "outcome" not in record: record = {**record, "outcome": prior["outcome"]}
        if prior.get("outcome", {}).get("status") == "attached" and record.get("outcome", {}).get("status") != "attached":
            record = {**record, "outcome": prior["outcome"]}
    fd, tmp = tempfile.mkstemp(prefix=".binding-", dir=path.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump({"schema": 1, **record}, f, sort_keys=True, separators=(",", ":")); f.flush(); os.fsync(f.fileno())
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
    if not isinstance(data, dict) or data.get("schema") != 1 or set(data) not in (required, required | {"outcome"}):
        raise UnsafeState("invalid binding record schema")
    if "outcome" in data: _validate_outcome(data["outcome"])
    return data


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
