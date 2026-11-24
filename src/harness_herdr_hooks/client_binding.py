"""Authenticated, short-lived Codex client display bindings.

This module deliberately keeps placement authority in an owner-only lease held
open by the reporting helper. Server inherited coordinates are never inputs.
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import stat
import tempfile
import time
import uuid
from contextlib import contextmanager, nullcontext
from dataclasses import dataclass
from pathlib import Path
from typing import Any, BinaryIO, Iterator

MAX_LINE = 4096
MAX_RECORD = 65536
MAX_RECEIPTS = 128
RECEIPT_TTL = 60.0
_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\Z")


class BindingError(RuntimeError):
    """Malformed, unauthenticated, or stale client binding."""


def _uuid(value: Any) -> bool:
    return isinstance(value, str) and _UUID.fullmatch(value) is not None


def _uuid4(value: Any) -> bool:
    return _uuid(value) and value[14] == "4"


def _private_dir(path: Path, *, strict_mode: bool = True) -> None:
    if path.is_symlink():
        raise BindingError("binding state path is a symlink")
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    st = path.stat()
    if not stat.S_ISDIR(st.st_mode) or st.st_uid != os.getuid():
        raise BindingError("binding state directory is not owner controlled")
    if strict_mode and stat.S_IMODE(st.st_mode) != 0o700:
        raise BindingError("binding-private directory has nonprivate mode")


def _open_private(path: Path, *, create: bool = False) -> int:
    flags = os.O_RDWR | getattr(os, "O_NOFOLLOW", 0)
    if create:
        flags |= os.O_CREAT | os.O_EXCL
    try:
        fd = os.open(path, flags, 0o600)
    except FileExistsError:
        fd = os.open(path, os.O_RDWR | getattr(os, "O_NOFOLLOW", 0))
    st = os.fstat(fd)
    if not stat.S_ISREG(st.st_mode) or st.st_uid != os.getuid() or stat.S_IMODE(st.st_mode) != 0o600:
        os.close(fd)
        raise BindingError("binding record or lock is not private and owner controlled")
    return fd


def _canonical_json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def _read_record(path: Path) -> dict[str, Any]:
    st = path.lstat()
    if (not stat.S_ISREG(st.st_mode) or st.st_uid != os.getuid()
            or stat.S_IMODE(st.st_mode) != 0o600 or st.st_size > MAX_RECORD):
        raise BindingError("unsafe or oversized lease record")
    raw = path.read_bytes()
    after = path.lstat()
    if (st.st_dev, st.st_ino, st.st_size) != (after.st_dev, after.st_ino, after.st_size):
        raise BindingError("lease record changed while reading")
    value = json.loads(raw, object_pairs_hook=_strict_object)
    if not isinstance(value, dict): raise BindingError("lease record is not an object")
    return value


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise BindingError("duplicate JSON object key")
        result[key] = value
    return result


def _update_unresolved(record: dict[str, Any], value: dict[str, Any] | bool | None,
                      expected: dict[str, Any] | None = None) -> None:
    current = record.get("unresolved_effect")
    legacy = {"stage": "start", "event_key": "legacy", "view_sequence": record.get("active_sequence") or 1}
    if isinstance(current, bool):
        current = legacy if current else None
        record["unresolved_effect"] = current
    if isinstance(value, bool):
        if value:
            value = legacy
        else:
            if current is None:
                return
            if current != legacy:
                raise BindingError("legacy resolution cannot clear a different effect")
            value = None
            expected = legacy
    if value is not None:
        if (not isinstance(value, dict) or set(value) - {"stage", "event_key", "view_sequence", "pane_id", "parent_id"}
                or value.get("stage") not in {"split", "start", "title"}
                or not isinstance(value.get("event_key"), str) or not value["event_key"]
                or isinstance(value.get("view_sequence"), bool)
                or not isinstance(value.get("view_sequence"), int) or value["view_sequence"] <= 0
                or ("pane_id" in value and not isinstance(value.get("pane_id"), str))
                or ("parent_id" in value and not _uuid(value.get("parent_id")))):
            raise BindingError("invalid unresolved effect identity")
        if current not in (None, value): raise BindingError("a different effect is unresolved")
        record["unresolved_effect"] = dict(value)
    else:
        if current is None: return
        if expected is None or current != expected:
            raise BindingError("unresolved effect identity does not match")
        record["unresolved_effect"] = None


def validate_report(obj: Any, last_sequence: int) -> dict[str, Any]:
    """Validate one strict v1 report. Return a normalized copy or fail closed."""
    if not isinstance(obj, dict) or obj.get("version") != 1:
        raise BindingError("unsupported report")
    seq = obj.get("sequence")
    if isinstance(seq, bool) or not isinstance(seq, int) or seq <= last_sequence or seq <= 0:
        raise BindingError("report sequence is not strictly increasing")
    event = obj.get("event")
    if event == "clear":
        if set(obj) != {"version", "sequence", "event", "thread_id"} or obj.get("thread_id") is not None:
            raise BindingError("malformed clear report")
        return {"version": 1, "sequence": seq, "event": event, "thread_id": None}
    if event == "active":
        if set(obj) != {"version", "sequence", "event", "thread_id", "source"}:
            raise BindingError("malformed active report")
        if not _uuid(obj.get("thread_id")) or obj.get("source") not in {"startup", "resume", "fork"}:
            raise BindingError("invalid active view")
        return {"version": 1, "sequence": seq, "event": event,
                "thread_id": obj["thread_id"], "source": obj["source"]}
    if event == "created":
        if set(obj) != {"version", "sequence", "event", "thread_id", "child_id", "turn_id", "view_sequence"}:
            raise BindingError("malformed creation report")
        turn = obj.get("turn_id")
        view_seq = obj.get("view_sequence")
        if (not _uuid(obj.get("thread_id")) or not _uuid(obj.get("child_id"))
                or not isinstance(turn, str) or not turn or len(turn.encode()) > 128
                or isinstance(view_seq, bool) or not isinstance(view_seq, int) or view_seq <= 0):
            raise BindingError("invalid creation receipt")
        return {"version": 1, "sequence": seq, "event": event,
                "thread_id": obj["thread_id"], "child_id": obj["child_id"],
                "turn_id": turn, "view_sequence": view_seq}
    raise BindingError("unknown report event")


def _read_line(reader: BinaryIO) -> bytes:
    line = reader.readline(MAX_LINE + 1)
    if not line or len(line) > MAX_LINE or not line.endswith(b"\n"):
        raise BindingError("report line missing or exceeds limit")
    return line[:-1]


@dataclass(frozen=True)
class PaneDisplay:
    server_id: str
    workspace_id: str
    tab_id: str
    pane_id: str
    terminal_device: int
    terminal_inode: int


def admit_terminal(terminal_fd: int, snapshot: dict[str, Any], *, server_id: str,
                   workspace_id: str, tab_id: str, pane_id: str) -> PaneDisplay:
    """Match duplicated client tty identity to one exact protocol-22 pane."""
    try:
        st = os.fstat(terminal_fd)
        if not stat.S_ISCHR(st.st_mode) or not os.isatty(terminal_fd):
            raise BindingError("client descriptor is not a terminal")
    except OSError as exc:
        raise BindingError("client terminal descriptor unavailable") from exc
    panes = snapshot.get("panes") if isinstance(snapshot, dict) and snapshot.get("protocol") == 22 else None
    if not isinstance(panes, list) or len(panes) > 128:
        raise BindingError("invalid bounded Herdr snapshot")
    matches: list[dict[str, Any]] = []
    for pane in panes:
        if not isinstance(pane, dict) or not isinstance(pane.get("pane_id"), str) or not pane["pane_id"]:
            raise BindingError("Herdr snapshot contains an incomplete pane")
        proc = pane.get("process_info")
        tty = proc.get("tty") if isinstance(proc, dict) else None
        try:
            candidate = os.stat(tty) if isinstance(tty, str) and tty.startswith("/") else None
        except OSError:
            candidate = None
        if candidate is None or not stat.S_ISCHR(candidate.st_mode):
            raise BindingError("Herdr pane tty identity is missing or invalid")
        if (candidate is not None and stat.S_ISCHR(candidate.st_mode)
                and (candidate.st_dev, candidate.st_ino) == (st.st_dev, st.st_ino)):
            matches.append(pane)
    if (len(matches) != 1 or matches[0].get("workspace_id") != workspace_id
            or matches[0].get("tab_id") != tab_id or matches[0].get("pane_id") != pane_id):
        raise BindingError("client terminal does not uniquely match claimed Herdr pane")
    return PaneDisplay(server_id, workspace_id, tab_id, pane_id, st.st_dev, st.st_ino)


def admit_from_herdr(terminal_fd: int, herdr: Any, *, workspace_id: str,
                    tab_id: str, pane_id: str) -> PaneDisplay:
    """Take one authenticated bounded snapshot from a HerdrClient and admit it."""
    if not hasattr(herdr, "snapshot") or not hasattr(herdr, "server_identity"):
        raise BindingError("Herdr client does not provide authenticated protocol-22 access")
    try:
        snapshot = herdr.snapshot()
        server_id = herdr.server_identity()
        panes = snapshot.get("panes") if isinstance(snapshot, dict) else None
        if snapshot.get("protocol") != 22 or not isinstance(panes, list) or len(panes) > 128:
            raise BindingError("invalid bounded Herdr snapshot")
        enriched = []
        for pane in panes:
            if not isinstance(pane, dict) or not isinstance(pane.get("pane_id"), str) or not pane["pane_id"]:
                raise BindingError("Herdr snapshot contains an incomplete pane")
            info = herdr.process_info(pane["pane_id"])
            if (not isinstance(info, dict) or info.get("pane_id") != pane["pane_id"]
                    or not isinstance(info.get("tty"), str) or not info["tty"].startswith("/")):
                raise BindingError("Herdr pane process info has no verified tty")
            enriched.append({**pane, "process_info": info})
        snapshot = {"protocol": 22, "panes": enriched}
    except Exception as exc:
        if isinstance(exc, BindingError): raise
        raise BindingError("Herdr admission snapshot failed") from exc
    return admit_terminal(terminal_fd, snapshot, server_id=server_id,
                          workspace_id=workspace_id, tab_id=tab_id, pane_id=pane_id)


class ClientBindingStore:
    """Private binding records and lock files under the supplied state root."""
    def __init__(self, state_root: Path):
        self.root = Path(state_root) / "harness-herdr-hooks" / "client-bindings"
        _private_dir(self.root.parent.parent, strict_mode=False)
        _private_dir(self.root.parent)
        _private_dir(self.root)

    @staticmethod
    def _key(server_id: str, terminal_device: int, terminal_inode: int) -> str:
        return hashlib.sha256(f"{server_id}\0{terminal_device}\0{terminal_inode}".encode()).hexdigest()

    def _terminal_lock_path(self, key: str) -> Path:
        return self.root / f"{key}.terminal.lock"

    def _lifetime_lock_path(self, key: str, generation: str) -> Path:
        return self.root / f"{key}.{generation}.lifetime.lock"

    def open_lease(self, *, profile: str, backend: dict[str, Any], server_id: str,
                   workspace_id: str, tab_id: str, pane_id: str,
                   terminal_device: int, terminal_inode: int,
                   before_publish: Any = None, after_publish: Any = None,
                   initial_report: dict[str, Any] | None = None,
                   client_nonce: str | None = None) -> "ClientLease":
        values = (profile, server_id, workspace_id, tab_id, pane_id)
        if not all(isinstance(v, str) and v and len(v) <= 1024 for v in values):
            raise BindingError("invalid lease identity")
        if not isinstance(backend, dict):
            raise BindingError("invalid backend identity")
        if client_nonce is not None and not _uuid4(client_nonce):
            raise BindingError("client nonce must be a canonical UUID v4")
        if client_nonce is not None:
            for path in self.root.glob("*.json"):
                try: existing = _read_record(path)
                except (OSError, ValueError, json.JSONDecodeError) as exc:
                    raise BindingError("cannot safely check client nonce uniqueness") from exc
                if existing.get("client_nonce") == client_nonce:
                    raise BindingError("client nonce was already used")
        if initial_report is not None:
            initial_report = validate_report(initial_report, 0)
            if initial_report["event"] != "active":
                raise BindingError("initial lease report must activate a primary view")
        generation = str(uuid.uuid4())
        key = self._key(server_id, terminal_device, terminal_inode)
        terminal_fd = _open_private(self._terminal_lock_path(key), create=True)
        try:
            fcntl.flock(terminal_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            os.close(terminal_fd)
            raise BindingError("terminal already has a live client lease") from exc
        terminal_st = os.fstat(terminal_fd)
        lifetime_path = self._lifetime_lock_path(key, generation)
        try: fd = _open_private(lifetime_path, create=True)
        except BaseException:
            fcntl.flock(terminal_fd, fcntl.LOCK_UN); os.close(terminal_fd)
            raise
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            os.close(fd); os.close(terminal_fd)
            raise BindingError("generation lifetime lock is already held") from exc
        lock_st = os.fstat(fd)
        effect_path = self.root / f"{key}.{generation}.effect.lock"
        try: effect_fd = _open_private(effect_path, create=True)
        except BaseException:
            fcntl.flock(fd, fcntl.LOCK_UN); fcntl.flock(terminal_fd, fcntl.LOCK_UN)
            os.close(fd); os.close(terminal_fd)
            raise
        effect_st = os.fstat(effect_fd)
        record = {"version": 1, "generation": generation, "profile": profile,
                  "backend": backend, "server_id": server_id, "workspace_id": workspace_id,
                  "tab_id": tab_id, "pane_id": pane_id,
                  "lifetime_lock": [lock_st.st_dev, lock_st.st_ino],
                  "terminal_lock": [terminal_st.st_dev, terminal_st.st_ino],
                  "effect_lock": [effect_st.st_dev, effect_st.st_ino],
                  "client_nonce": client_nonce,
                  "terminal_device": terminal_device, "terminal_inode": terminal_inode,
                  "last_sequence": 0, "active_thread_id": None, "active_sequence": None,
                  "receipts": [], "unresolved_effect": None}
        if initial_report is not None:
            record["last_sequence"] = initial_report["sequence"]
            record["active_thread_id"] = initial_report["thread_id"]
            record["active_sequence"] = initial_report["sequence"]
        lease_path = self.root / f"{key}.json"
        prior_effect_fd = None
        prior_lifetime_fd = None
        try:
            for lock_fd, path, label in ((fd, lifetime_path, "generation lifetime"),
                                         (terminal_fd, self._terminal_lock_path(key), "terminal"),
                                         (effect_fd, effect_path, "effect")):
                opened, current_path = os.fstat(lock_fd), path.lstat()
                if (opened.st_dev, opened.st_ino) != (current_path.st_dev, current_path.st_ino):
                    raise BindingError(f"new {label} lock was replaced before publication")
            if lease_path.exists() or lease_path.is_symlink():
                prior = _read_record(lease_path)
                prior_generation = prior.get("generation")
                if not _uuid(prior_generation):
                    raise BindingError("previous client generation is malformed")
                prior_lifetime_path = self._lifetime_lock_path(key, prior_generation)
                prior_lifetime_fd = _open_private(prior_lifetime_path)
                prior_lifetime_st = os.fstat(prior_lifetime_fd)
                prior_life_actual = prior_lifetime_path.lstat()
                if ((prior_lifetime_st.st_dev, prior_lifetime_st.st_ino) != (prior_life_actual.st_dev, prior_life_actual.st_ino)
                        or prior.get("lifetime_lock") != [prior_lifetime_st.st_dev, prior_lifetime_st.st_ino]):
                    raise BindingError("previous generation lifetime proof was replaced")
                try: fcntl.flock(prior_lifetime_fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
                except BlockingIOError as exc: raise BindingError("previous generation is still live") from exc
                else:
                    # Probe only: holding this lock while waiting for the old
                    # effect gate would make the old generation look live.
                    fcntl.flock(prior_lifetime_fd, fcntl.LOCK_UN)
                os.close(prior_lifetime_fd); prior_lifetime_fd = None
                prior_effect_path = self.root / f"{key}.{prior_generation}.effect.lock"
                prior_effect_fd = _open_private(prior_effect_path)
                prior_effect_st = os.fstat(prior_effect_fd)
                prior_actual = prior_effect_path.lstat()
                if ((prior_effect_st.st_dev, prior_effect_st.st_ino) != (prior_actual.st_dev, prior_actual.st_ino)
                        or prior.get("effect_lock") != [prior_effect_st.st_dev, prior_effect_st.st_ino]):
                    raise BindingError("previous generation effect gate was replaced")
                fcntl.flock(prior_effect_fd, fcntl.LOCK_EX)
                current_prior = _read_record(lease_path)
                if (current_prior.get("generation") != prior_generation
                        or current_prior.get("effect_lock") != prior.get("effect_lock")
                        or current_prior.get("lifetime_lock") != prior.get("lifetime_lock")
                        or current_prior.get("terminal_lock") != [terminal_st.st_dev, terminal_st.st_ino]
                        or prior.get("terminal_lock") != [terminal_st.st_dev, terminal_st.st_ino]):
                    raise BindingError("previous generation changed during replacement")
                if current_prior.get("unresolved_effect") not in (None, False):
                    raise BindingError("previous generation has an unresolved effect")
            if before_publish is not None:
                before_publish(dict(record), initial_report)
            self._atomic_record(lease_path, record)
        except BaseException:
            if prior_effect_fd is not None:
                try: fcntl.flock(prior_effect_fd, fcntl.LOCK_UN)
                finally: os.close(prior_effect_fd)
            if prior_lifetime_fd is not None:
                try: fcntl.flock(prior_lifetime_fd, fcntl.LOCK_UN)
                finally: os.close(prior_lifetime_fd)
            fcntl.flock(fd, fcntl.LOCK_UN); fcntl.flock(terminal_fd, fcntl.LOCK_UN)
            os.close(fd); os.close(terminal_fd); os.close(effect_fd); raise
        if prior_effect_fd is not None:
            fcntl.flock(prior_effect_fd, fcntl.LOCK_UN); os.close(prior_effect_fd)
        if prior_lifetime_fd is not None:
            fcntl.flock(prior_lifetime_fd, fcntl.LOCK_UN); os.close(prior_lifetime_fd)
        try:
            lease = ClientLease(self, key, fd, terminal_fd, effect_fd, lock_st.st_dev, lock_st.st_ino,
                                terminal_st.st_dev, terminal_st.st_ino,
                                effect_st.st_dev, effect_st.st_ino, record)
        except BaseException:
            fcntl.flock(fd, fcntl.LOCK_UN); fcntl.flock(terminal_fd, fcntl.LOCK_UN)
            os.close(fd); os.close(terminal_fd); os.close(effect_fd)
            raise
        try:
            if after_publish is not None:
                after_publish(dict(record), initial_report)
        except BaseException:
            lease.close()
            raise
        return lease

    def _atomic_record(self, path: Path, record: dict[str, Any]) -> None:
        payload = _canonical_json(record)
        if len(payload) > MAX_RECORD:
            raise BindingError("lease record exceeds size bound")
        fd, name = tempfile.mkstemp(prefix=".lease-", dir=self.root)
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "wb") as stream:
                stream.write(payload); stream.flush(); os.fsync(stream.fileno())
            os.replace(name, path)
            dfd = os.open(self.root, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
            try: os.fsync(dfd)
            finally: os.close(dfd)
        finally:
            try: os.unlink(name)
            except FileNotFoundError: pass

    def read_live(self, key: str, generation: str | None = None) -> dict[str, Any] | None:
        if not re.fullmatch(r"[0-9a-f]{64}", key):
            raise BindingError("invalid lease key")
        path = self.root / f"{key}.json"
        record = _read_record(path)
        if record.get("version") != 1 or not _uuid(record.get("generation")):
            raise BindingError("malformed lease record")
        if generation is not None and record["generation"] != generation:
            return None
        lifetime_path = self._lifetime_lock_path(key, record["generation"])
        terminal_path = self._terminal_lock_path(key)
        life_fd = _open_private(lifetime_path)
        try: terminal_fd = _open_private(terminal_path)
        except BaseException:
            os.close(life_fd); raise
        effect_path = self.root / f"{key}.{record['generation']}.effect.lock"
        try: effect_fd = _open_private(effect_path)
        except BaseException:
            os.close(life_fd); os.close(terminal_fd); raise
        try:
            effect_st = os.fstat(effect_fd)
            if (not isinstance(record.get("profile"), str) or not isinstance(record.get("backend"), dict)
                    or not isinstance(record.get("server_id"), str)
                    or not isinstance(record.get("workspace_id"), str)
                    or not isinstance(record.get("tab_id"), str) or not isinstance(record.get("pane_id"), str)
                    or isinstance(record.get("last_sequence"), bool) or not isinstance(record.get("last_sequence"), int)
                    or not isinstance(record.get("receipts"), list) or len(record["receipts"]) > MAX_RECEIPTS
                    or (record.get("unresolved_effect") is not None
                        and not isinstance(record.get("unresolved_effect"), (dict, bool)))):
                raise BindingError("malformed lease fields")
            if record.get("client_nonce") is not None and not _uuid4(record.get("client_nonce")):
                raise BindingError("malformed client nonce")
            for lock_field, actual in (("lifetime_lock", os.fstat(life_fd)),
                                       ("terminal_lock", os.fstat(terminal_fd)),
                                       ("effect_lock", effect_st)):
                if record.get(lock_field) != [actual.st_dev, actual.st_ino]:
                    raise BindingError(f"{lock_field} identity changed")
            active, active_seq = record.get("active_thread_id"), record.get("active_sequence")
            if ((active is None) != (active_seq is None)
                    or (active is not None and not _uuid(active))
                    or (active_seq is not None and (isinstance(active_seq, bool) or not isinstance(active_seq, int)
                                                    or active_seq <= 0 or active_seq > record["last_sequence"]))):
                raise BindingError("malformed active view in lease")
            for receipt in record["receipts"]:
                if (not isinstance(receipt, dict) or not _uuid(receipt.get("parent_id"))
                        or not _uuid(receipt.get("child_id")) or not isinstance(receipt.get("turn_id"), str)
                        or not receipt["turn_id"] or len(receipt["turn_id"].encode()) > 128
                        or isinstance(receipt.get("view_sequence"), bool)
                        or not isinstance(receipt.get("view_sequence"), int)
                        or isinstance(receipt.get("sequence"), bool) or not isinstance(receipt.get("sequence"), int)
                        or not isinstance(receipt.get("expires_at"), (int, float))):
                    raise BindingError("malformed creation receipt")
            if isinstance(record.get("unresolved_effect"), dict):
                probe_record = dict(record); probe_record["unresolved_effect"] = None
                _update_unresolved(probe_record, record["unresolved_effect"])
            # Requiring the generation lock prevents an incoming helper's
            # stable terminal lock from making the old generation look live.
            for probe in (life_fd, terminal_fd):
                try: fcntl.flock(probe, fcntl.LOCK_SH | fcntl.LOCK_NB)
                except BlockingIOError: continue
                else:
                    fcntl.flock(probe, fcntl.LOCK_UN)
                    return None
            latest = _read_record(path)
            if (latest.get("generation") != record["generation"]
                    or latest.get("lifetime_lock") != record.get("lifetime_lock")
                    or latest.get("terminal_lock") != record.get("terminal_lock")):
                return None
            return record
        finally:
            os.close(life_fd); os.close(terminal_fd); os.close(effect_fd)

    @contextmanager
    def guard(self, key: str, generation: str) -> Iterator["EffectGuard"]:
        """Acquire an observer's effect lock and recheck the exact live lease."""
        if not re.fullmatch(r"[0-9a-f]{64}", key) or not _uuid(generation):
            raise BindingError("invalid lease key or generation")
        lock_path = self._lifetime_lock_path(key, generation)
        life_fd = _open_private(lock_path)
        terminal_path = self._terminal_lock_path(key)
        try: terminal_fd = _open_private(terminal_path)
        except BaseException:
            os.close(life_fd); raise
        effect_path = self.root / f"{key}.{generation}.effect.lock"
        try: effect_fd = _open_private(effect_path)
        except BaseException:
            os.close(life_fd); os.close(terminal_fd); raise
        try:
            for fd, path, label in ((life_fd, lock_path, "generation lifetime"),
                                    (terminal_fd, terminal_path, "terminal"),
                                    (effect_fd, effect_path, "effect")):
                fst = os.fstat(fd); pst = path.lstat()
                if (fst.st_dev, fst.st_ino) != (pst.st_dev, pst.st_ino):
                    raise BindingError(f"{label} lock was replaced")
            st = os.fstat(effect_fd); pst = effect_path.lstat()
            if (st.st_dev, st.st_ino) != (pst.st_dev, pst.st_ino):
                raise BindingError("effect lock was replaced")
            fcntl.flock(effect_fd, fcntl.LOCK_EX)
            path = self.root / f"{key}.json"
            record = _read_record(path)
            if (not isinstance(record, dict) or record.get("generation") != generation
                    or not isinstance(record.get("receipts"), list) or len(record["receipts"]) > MAX_RECEIPTS):
                raise BindingError("lease generation changed")
            if (record.get("lifetime_lock") != [os.fstat(life_fd).st_dev, os.fstat(life_fd).st_ino]
                    or record.get("terminal_lock") != [os.fstat(terminal_fd).st_dev, os.fstat(terminal_fd).st_ino]
                    or record.get("effect_lock") != [os.fstat(effect_fd).st_dev, os.fstat(effect_fd).st_ino]):
                raise BindingError("lease lock inode identity changed")
            for path_probe in (lock_path, terminal_path):
                probe = _open_private(path_probe)
                try:
                    try: fcntl.flock(probe, fcntl.LOCK_SH | fcntl.LOCK_NB)
                    except BlockingIOError: pass
                    else:
                        fcntl.flock(probe, fcntl.LOCK_UN)
                        raise BindingError("client disconnected before effect admission")
                finally: os.close(probe)
            checked = self.read_live(key, generation)
            if checked is None:
                raise BindingError("client lease ended before guard admission")
            record = checked
            guard = EffectGuard(self, path, record)
            yield guard
        finally:
            try: fcntl.flock(effect_fd, fcntl.LOCK_UN)
            finally:
                os.close(effect_fd); os.close(life_fd); os.close(terminal_fd)

    def live_records(self) -> list[tuple[str, dict[str, Any]]]:
        """Return lease records whose lifetime lock is currently held."""
        out = []
        for path in self.root.glob("*.json"):
            key = path.stem
            try:
                record = self.read_live(key)
                if record is not None: out.append((key, record))
            except (OSError, BindingError, ValueError, json.JSONDecodeError):
                continue
        return out

    @contextmanager
    def selecting_receipt(self) -> Iterator[None]:
        """Serialize receipt publication with cross-client receipt selection."""
        fd = _open_private(self.root / "receipt-selection.lock", create=True)
        try:
            st = os.fstat(fd); pst = (self.root / "receipt-selection.lock").lstat()
            if (st.st_dev, st.st_ino) != (pst.st_dev, pst.st_ino):
                raise BindingError("receipt selection lock was replaced")
            fcntl.flock(fd, fcntl.LOCK_EX)
            yield
        finally:
            try: fcntl.flock(fd, fcntl.LOCK_UN)
            finally: os.close(fd)

    def assert_revoked(self, key: str, generation: str) -> bool:
        """Prove an exact generation is inactive, unlocked and effect-resolved."""
        if not re.fullmatch(r"[0-9a-f]{64}", key) or not _uuid(generation):
            raise BindingError("invalid lease key or generation")
        life_path = self._lifetime_lock_path(key, generation)
        life_fd = _open_private(life_path)
        terminal_path = self._terminal_lock_path(key)
        try: terminal_fd = _open_private(terminal_path)
        except BaseException:
            os.close(life_fd); raise
        effect_path = self.root / f"{key}.{generation}.effect.lock"
        try: effect_fd = _open_private(effect_path)
        except BaseException as exc:
            os.close(life_fd); os.close(terminal_fd)
            if isinstance(exc, OSError): raise BindingError("effect lock is unavailable") from exc
            raise
        try:
            life_st = os.fstat(life_fd); actual = life_path.lstat()
            if (life_st.st_dev, life_st.st_ino) != (actual.st_dev, actual.st_ino):
                raise BindingError("lifetime lock was replaced")
            try: fcntl.flock(life_fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
            except BlockingIOError as exc: raise BindingError("old client lease remains live") from exc
            else: fcntl.flock(life_fd, fcntl.LOCK_UN)
            try: fcntl.flock(terminal_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc: raise BindingError("terminal is owned by a live or incoming generation") from exc
            effect_st = os.fstat(effect_fd); actual_effect = effect_path.lstat()
            if (effect_st.st_dev, effect_st.st_ino) != (actual_effect.st_dev, actual_effect.st_ino):
                raise BindingError("effect lock was replaced")
            fcntl.flock(effect_fd, fcntl.LOCK_EX)
            record_path = self.root / f"{key}.json"
            record = _read_record(record_path)
            if (not isinstance(record, dict) or record.get("generation") != generation
                    or record.get("lifetime_lock") != [life_st.st_dev, life_st.st_ino]
                    or record.get("terminal_lock") != [os.fstat(terminal_fd).st_dev, os.fstat(terminal_fd).st_ino]
                    or record.get("effect_lock") != [effect_st.st_dev, effect_st.st_ino]):
                raise BindingError("revoked lease record was replaced")
            if record.get("unresolved_effect") is not None:
                raise BindingError("old client effect remains unresolved")
            return True
        finally:
            try: fcntl.flock(effect_fd, fcntl.LOCK_UN)
            finally:
                try: fcntl.flock(life_fd, fcntl.LOCK_UN)
                finally: os.close(effect_fd); os.close(life_fd); os.close(terminal_fd)

    def consume_matching_receipt(self, parent_id: str, turn_id: str,
                                 child_id: str) -> tuple[str, dict[str, Any]] | None:
        """Consume an exact receipt only when exactly one live client owns it."""
        with self.selecting_receipt():
            matches = []
            for key, record in self.live_records():
                if record.get("active_thread_id") != parent_id:
                    continue
                for receipt in record.get("receipts", []):
                    if (receipt.get("expires_at", 0) > time.time()
                            and (receipt.get("parent_id"), receipt.get("turn_id"), receipt.get("child_id"))
                            == (parent_id, turn_id, child_id)):
                        matches.append((key, record["generation"]))
            if len(matches) != 1: return None
            key, generation = matches[0]
            with self.guard(key, generation) as guard:
                receipt = guard.consume_receipt(parent_id, turn_id, child_id)
                return (key, receipt) if receipt is not None else None

    def assert_revoked_client(self, display: PaneDisplay, profile: str,
                              backend: dict[str, Any], client_nonce: str,
                              reconcile_start: Any = None) -> bool:
        """Verify revocation of the exact prior client generation by its nonce."""
        if not isinstance(display, PaneDisplay) or not isinstance(profile, str) or not isinstance(backend, dict):
            raise BindingError("invalid client revocation identity")
        if not _uuid4(client_nonce):
            raise BindingError("client nonce must be a canonical UUID v4")
        candidates = []
        try:
            paths = list(self.root.glob("*.json"))
            if len(paths) > 4096: raise BindingError("too many client lease records")
            for path in paths:
                record = _read_record(path)
                if record.get("client_nonce") == client_nonce:
                    candidates.append((path.stem, record))
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            raise BindingError("client lease records are unavailable or malformed") from exc
        if len(candidates) != 1:
            raise BindingError("client nonce does not identify exactly one prior lease")
        key, record = candidates[0]
        expected = (record.get("profile"), record.get("backend"), record.get("server_id"),
                    record.get("workspace_id"), record.get("tab_id"), record.get("pane_id"),
                    record.get("terminal_device"), record.get("terminal_inode"))
        actual = (profile, backend, display.server_id, display.workspace_id, display.tab_id,
                  display.pane_id, display.terminal_device, display.terminal_inode)
        if expected != actual:
            raise BindingError("client nonce record does not match this display and profile")
        generation = record.get("generation")
        if not _uuid(generation): raise BindingError("prior lease generation is malformed")
        life_path = self._lifetime_lock_path(key, generation)
        terminal_path = self._terminal_lock_path(key)
        effect_path = self.root / f"{key}.{generation}.effect.lock"
        life_fd = _open_private(life_path)
        try: terminal_fd = _open_private(terminal_path)
        except BaseException:
            os.close(life_fd); raise
        try: effect_fd = _open_private(effect_path)
        except BaseException as exc:
            os.close(life_fd); os.close(terminal_fd)
            if isinstance(exc, OSError): raise BindingError("prior effect lock is unavailable") from exc
            raise
        try:
            life_st = os.fstat(life_fd); life_actual = life_path.lstat()
            if ((life_st.st_dev, life_st.st_ino) != (life_actual.st_dev, life_actual.st_ino)
                    or record.get("lifetime_lock") != [life_st.st_dev, life_st.st_ino]):
                raise BindingError("prior lifetime lock was replaced")
            try: fcntl.flock(life_fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
            except BlockingIOError as exc: raise BindingError("prior client lease is still live") from exc
            else: fcntl.flock(life_fd, fcntl.LOCK_UN)
            terminal_st = os.fstat(terminal_fd); terminal_actual = terminal_path.lstat()
            if ((terminal_st.st_dev, terminal_st.st_ino) != (terminal_actual.st_dev, terminal_actual.st_ino)
                    or record.get("terminal_lock") != [terminal_st.st_dev, terminal_st.st_ino]):
                raise BindingError("prior terminal lock was replaced")
            try: fcntl.flock(terminal_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc: raise BindingError("terminal is owned by another generation") from exc
            effect_st = os.fstat(effect_fd); effect_actual = effect_path.lstat()
            if ((effect_st.st_dev, effect_st.st_ino) != (effect_actual.st_dev, effect_actual.st_ino)
                    or record.get("effect_lock") != [effect_st.st_dev, effect_st.st_ino]):
                raise BindingError("prior effect lock was replaced")
            fcntl.flock(effect_fd, fcntl.LOCK_EX)
            current = _read_record(self.root / f"{key}.json")
            if (current.get("generation") != generation or current.get("client_nonce") != client_nonce
                    or current.get("lifetime_lock") != record.get("lifetime_lock")
                    or current.get("terminal_lock") != record.get("terminal_lock")
                    or current.get("effect_lock") != record.get("effect_lock")):
                raise BindingError("prior client record changed during verification")
            current_identity = (current.get("profile"), current.get("backend"), current.get("server_id"),
                                current.get("workspace_id"), current.get("tab_id"), current.get("pane_id"),
                                current.get("terminal_device"), current.get("terminal_inode"))
            if current_identity != actual:
                raise BindingError("prior client identity changed during verification")
            unresolved = current.get("unresolved_effect")
            if unresolved not in (None, False):
                if (not isinstance(unresolved, dict) or unresolved.get("stage") != "start"
                        or reconcile_start is None):
                    raise BindingError("prior client has an unresolved pane effect")
                if reconcile_start(dict(current), dict(unresolved)) is not True:
                    raise BindingError("prior start effect could not be definitively reconciled")
                checked = _read_record(self.root / f"{key}.json")
                if (checked.get("generation") != generation or checked.get("client_nonce") != client_nonce
                        or checked.get("unresolved_effect") != unresolved):
                    raise BindingError("prior effect changed during reconciliation")
                checked["unresolved_effect"] = None
                self._atomic_record(self.root / f"{key}.json", checked)
            return True
        finally:
            try: fcntl.flock(effect_fd, fcntl.LOCK_UN)
            finally:
                try: fcntl.flock(life_fd, fcntl.LOCK_UN)
                finally: os.close(effect_fd); os.close(life_fd); os.close(terminal_fd)


class EffectGuard:
    def __init__(self, store: ClientBindingStore, path: Path, record: dict[str, Any]):
        self.store, self.path, self.record = store, path, record

    def persist(self) -> None:
        self.store._atomic_record(self.path, self.record)

    def set_unresolved(self, value: dict[str, Any] | bool | None, *, expected: dict[str, Any] | None = None) -> None:
        _update_unresolved(self.record, value, expected)
        self.persist()

    def consume_receipt(self, parent_id: str, turn_id: str, child_id: str) -> dict[str, Any] | None:
        receipts = self.record.get("receipts")
        if not isinstance(receipts, list): raise BindingError("malformed receipt list")
        live = [r for r in receipts if isinstance(r, dict) and r.get("expires_at", 0) > time.time()]
        matches = [r for r in live if (r.get("parent_id"), r.get("turn_id"), r.get("child_id"))
                   == (parent_id, turn_id, child_id)]
        self.record["receipts"] = live
        if len(matches) != 1:
            self.persist()
            return None
        receipt = dict(matches[0]); self.record["receipts"].remove(matches[0]); self.persist()
        return receipt


class ClientLease:
    def __init__(self, store: ClientBindingStore, key: str, lifetime_fd: int, terminal_fd: int,
                 effect_fd: int, lock_dev: int, lock_ino: int, terminal_dev: int,
                 terminal_ino: int, effect_dev: int, effect_ino: int,
                 record: dict[str, Any]):
        self.store, self.key, self.fd = store, key, lifetime_fd
        self.terminal_fd = terminal_fd
        self.terminal_dev, self.terminal_ino = terminal_dev, terminal_ino
        self.lock_dev, self.lock_ino, self.record = lock_dev, lock_ino, record
        self.lifetime_path = store._lifetime_lock_path(key, record["generation"])
        self.terminal_path = store._terminal_lock_path(key)
        self.effect_path = store.root / f"{key}.{record['generation']}.effect.lock"
        self.effect_fd = effect_fd
        self.effect_dev, self.effect_ino = effect_dev, effect_ino
        self._closed = False

    def _check(self) -> None:
        if self._closed:
            raise BindingError("lease is closed")
        st = os.fstat(self.fd)
        path_st = self.lifetime_path.lstat()
        if (st.st_dev, st.st_ino) != (self.lock_dev, self.lock_ino) or (path_st.st_dev, path_st.st_ino) != (self.lock_dev, self.lock_ino):
            raise BindingError("lifetime lock was replaced")
        for path, dev, ino in ((self.lifetime_path, self.lock_dev, self.lock_ino),
                               (self.terminal_path, self.terminal_dev, self.terminal_ino)):
            probe = _open_private(path)
            try:
                pst = os.fstat(probe)
                if (pst.st_dev, pst.st_ino) != (dev, ino):
                    raise BindingError("client lock identity was replaced")
                try: fcntl.flock(probe, fcntl.LOCK_SH | fcntl.LOCK_NB)
                except BlockingIOError: pass
                else:
                    fcntl.flock(probe, fcntl.LOCK_UN)
                    raise BindingError("client lease is no longer held")
            finally: os.close(probe)

    @contextmanager
    def effect_guard(self) -> Iterator[None]:
        self._check()
        st = os.fstat(self.effect_fd)
        pst = self.effect_path.lstat()
        if ((st.st_dev, st.st_ino) != (pst.st_dev, pst.st_ino)
                or (st.st_dev, st.st_ino) != (self.effect_dev, self.effect_ino)):
            raise BindingError("effect lock was replaced")
        fcntl.flock(self.effect_fd, fcntl.LOCK_EX)
        try:
            self._check()
            path = self.store.root / f"{self.key}.json"
            current = _read_record(path)
            if (not isinstance(current, dict) or current.get("generation") != self.record["generation"]
                    or current.get("lifetime_lock") != [self.lock_dev, self.lock_ino]
                    or current.get("terminal_lock") != [self.terminal_dev, self.terminal_ino]
                    or current.get("effect_lock") != [self.effect_dev, self.effect_ino]):
                raise BindingError("lease generation changed")
            self.record = current
            yield
        finally:
            fcntl.flock(self.effect_fd, fcntl.LOCK_UN)

    def set_unresolved(self, value: dict[str, Any] | bool | None, *, expected: dict[str, Any] | None = None) -> None:
        with self.effect_guard():
            _update_unresolved(self.record, value, expected)
            self.store._atomic_record(self.store.root / f"{self.key}.json", self.record)

    def accept(self, message: Any, *, before_active: Any = None,
               after_active: Any = None) -> dict[str, Any]:
        self._check()
        report = validate_report(message, self.record["last_sequence"])
        selection = self.store.selecting_receipt() if report["event"] == "created" else nullcontext()
        with selection:
            return self._accept_report(report, before_active=before_active, after_active=after_active)

    def _accept_report(self, report: dict[str, Any], *, before_active: Any = None,
                       after_active: Any = None) -> dict[str, Any]:
        with self.effect_guard():
            if report["event"] == "active":
                if self.record.get("active_thread_id") is not None:
                    raise BindingError("clear the current view before activating another")
                if before_active is not None:
                    before_active(dict(self.record), report)
            if report["event"] == "clear":
                if self.record.get("unresolved_effect"):
                    raise BindingError("unresolved effect prevents view revocation")
                self.record["active_thread_id"] = None
                self.record["active_sequence"] = None
                self.record["receipts"] = []
            elif report["event"] == "active":
                self.record["active_thread_id"] = report["thread_id"]
                self.record["active_sequence"] = report["sequence"]
                self.record["receipts"] = []
            else:
                if (report["thread_id"] != self.record.get("active_thread_id")
                        or report["view_sequence"] != self.record.get("active_sequence")):
                    raise BindingError("creation does not match acknowledged active view")
                self._expire_receipts()
                if len(self.record["receipts"]) >= MAX_RECEIPTS:
                    raise BindingError("creation receipt limit reached")
                self.record["receipts"].append({"parent_id": report["thread_id"],
                    "turn_id": report["turn_id"], "child_id": report["child_id"],
                    "view_sequence": report["view_sequence"], "sequence": report["sequence"],
                    "expires_at": time.time() + RECEIPT_TTL})
            self.record["last_sequence"] = report["sequence"]
            self.store._atomic_record(self.store.root / f"{self.key}.json", self.record)
            if report["event"] == "active" and after_active is not None:
                after_active(dict(self.record), report)
        return {"version": 1, "sequence": report["sequence"], "status": "ok"}

    def _expire_receipts(self) -> None:
        now = time.time()
        self.record["receipts"] = [r for r in self.record["receipts"] if r.get("expires_at", 0) > now]

    def consume_receipt(self, parent_id: str, turn_id: str, child_id: str) -> dict[str, Any] | None:
        with self.effect_guard():
            self._expire_receipts()
            matches = [r for r in self.record["receipts"] if (r["parent_id"], r["turn_id"], r["child_id"]) == (parent_id, turn_id, child_id)]
            if len(matches) != 1:
                return None
            receipt = matches[0]
            self.record["receipts"].remove(receipt)
            self.store._atomic_record(self.store.root / f"{self.key}.json", self.record)
            return dict(receipt)

    def serve(self, reader: BinaryIO, writer: BinaryIO, *, before_active: Any = None,
              after_active: Any = None) -> None:
        try:
            while True:
                line = _read_line(reader)
                try:
                    request = json.loads(line, object_pairs_hook=_strict_object)
                except (UnicodeDecodeError, json.JSONDecodeError, BindingError) as exc:
                    try: seq = json.loads(line).get("sequence")
                    except Exception: seq = 1
                    if isinstance(seq, bool) or not isinstance(seq, int) or seq < 1: seq = 1
                    writer.write(_canonical_json({"version": 1, "sequence": seq, "status": "rejected"}) + b"\n")
                    writer.flush()
                    raise BindingError("invalid JSON report") from exc
                try:
                    report = validate_report(request, self.record["last_sequence"])
                    reply = self.accept(report, before_active=before_active, after_active=after_active)
                except Exception:
                    seq = request.get("sequence") if isinstance(request, dict) else None
                    if isinstance(seq, bool) or not isinstance(seq, int) or seq < 1: seq = 1
                    writer.write(_canonical_json({"version": 1, "sequence": seq, "status": "rejected"}) + b"\n")
                    writer.flush()
                    raise
                writer.write(_canonical_json(reply) + b"\n"); writer.flush()
        finally:
            self.close()

    def close(self) -> None:
        if self._closed: return
        self._closed = True
        try:
            # Drop lease authority immediately. An already admitted RPC holds
            # this generation's effect gate and may finish before replacement.
            fcntl.flock(self.fd, fcntl.LOCK_UN)
            fcntl.flock(self.terminal_fd, fcntl.LOCK_UN)
            fcntl.flock(self.effect_fd, fcntl.LOCK_EX)
            try:
                path = self.store.root / f"{self.key}.json"
                current = _read_record(path)
                if (current.get("generation") == self.record["generation"]
                        and current.get("lifetime_lock") == [self.lock_dev, self.lock_ino]
                        and current.get("terminal_lock") == [self.terminal_dev, self.terminal_ino]
                        and current.get("effect_lock") == [self.effect_dev, self.effect_ino]):
                    current["active_thread_id"] = None
                    current["active_sequence"] = None
                    current["receipts"] = []
                    self.store._atomic_record(path, current)
            finally:
                fcntl.flock(self.effect_fd, fcntl.LOCK_UN)
        finally:
            os.close(self.fd); os.close(self.terminal_fd); os.close(self.effect_fd)

    def __enter__(self) -> "ClientLease": return self
    def __exit__(self, *_: Any) -> None: self.close()
