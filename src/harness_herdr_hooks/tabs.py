"""Durable, provider-neutral claims for one managed subagent tab per root."""
from __future__ import annotations

import hashlib
import json
import os
import pwd
import re
import stat
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Iterator

from .model import Context, SubagentDestination
from .state import StateStore


def _resolve_workspace_anchor() -> Any:
    """Resolve a private account-home state anchor without following links."""
    uid = os.getuid()
    try:
        account = pwd.getpwuid(uid)
    except (KeyError, OSError) as exc:
        raise RuntimeError("canonical workspace state unavailable: account home not found") from exc
    home = account.pw_dir
    if not isinstance(home, str) or not home.startswith("/"):
        raise RuntimeError("canonical workspace state unavailable: invalid account home")
    parts = [part for part in home.split("/") if part]
    if len(parts) > 128 or any(part in {".", ".."} for part in parts):
        raise RuntimeError("canonical workspace state unavailable: invalid account home path")

    if not getattr(os, "O_NOFOLLOW", 0) or not getattr(os, "O_DIRECTORY", 0):
        raise RuntimeError("canonical workspace state unavailable: no-follow directory opens unsupported")
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    # Walk every existing component. Above home, only root/current-user owned
    # directories are accepted, except the standard root-owned sticky temp dirs.
    current = "/"
    fds: list[int] = []
    try:
        fd = os.open("/", flags)
        fds.append(fd)
        st = os.fstat(fd)
        if not stat.S_ISDIR(st.st_mode):
            raise RuntimeError("canonical workspace state unavailable: unsafe path ancestor")
        root_uid = st.st_uid
        if stat.S_IMODE(st.st_mode) & 0o022:
            raise RuntimeError("canonical workspace state unavailable: unsafe root ancestor")
        for index, part in enumerate(parts):
            current = os.path.join(current, part)
            try:
                child = os.open(part, flags, dir_fd=fds[-1])
            except FileNotFoundError as exc:
                raise RuntimeError("canonical workspace state unavailable: account home missing") from exc
            fds.append(child)
            st = os.fstat(child)
            mode = stat.S_IMODE(st.st_mode)
            if not stat.S_ISDIR(st.st_mode):
                raise RuntimeError("canonical workspace state unavailable: unsafe path ancestor")
            if index < len(parts) - 1:
                sticky_root_tmp = st.st_uid == root_uid and bool(mode & stat.S_ISVTX) and bool(mode & 0o002)
                if st.st_uid not in {root_uid, uid} or (mode & 0o022 and not sticky_root_tmp):
                    raise RuntimeError("canonical workspace state unavailable: unsafe path ancestor")
            elif st.st_uid != uid or mode & 0o022:
                raise RuntimeError("canonical workspace state unavailable: unsafe account home")

        # Create only the final two private components; each parent has already
        # been verified and creation is relative to an open, no-follow fd.
        parent_fd = fds[-1]
        for name in (".local", "state"):
            try:
                os.mkdir(name, 0o700, dir_fd=parent_fd)
            except FileExistsError:
                pass
            child = os.open(name, flags, dir_fd=parent_fd)
            fds.append(child)
            st = os.fstat(child)
            mode = stat.S_IMODE(st.st_mode)
            if not stat.S_ISDIR(st.st_mode) or st.st_uid != uid or mode & 0o022:
                raise RuntimeError(f"canonical workspace state unavailable: unsafe {name} directory")
            parent_fd = child
        return __import__("pathlib").Path(home) / ".local" / "state"
    except OSError as exc:
        raise RuntimeError("canonical workspace state unavailable: no-follow directory access failed") from exc
    finally:
        for fd in reversed(fds):
            os.close(fd)


class OperationBusy(RuntimeError):
    """An observer already owns this workspace/root operation; defer this tick."""


@dataclass(slots=True)
class OperationToken:
    root_key: str
    workspace_key: str
    root_store: StateStore
    workspace_store: StateStore
    active: bool = True


@dataclass(frozen=True, slots=True)
class LabelReservation:
    root_key: str
    label: str
    generation: str
    reservation_id: str


@dataclass(frozen=True, slots=True)
class CreateClaim:
    root_key: str
    generation: str
    label: str
    claim_id: str


class SubagentTabManager:
    """Coordinate durable ownership; callers hold ``operations`` around I/O."""

    _MAX_RESERVATIONS = 256
    _MAX_ROOT_OWNERS = 1024

    def __init__(self, state: StateStore, root: Context, server_id: str, workspace_id: str,
                 *, _workspace_anchor: Any = None):
        if not isinstance(server_id, str) or not server_id or not isinstance(workspace_id, str) or not workspace_id:
            raise ValueError("server and workspace identity required")
        self.state, self.root = state, root
        self.server_id, self.workspace_id = server_id, workspace_id
        self.root_key = root.key()
        self.workspace_key = self._digest([server_id, workspace_id])
        root_ns = self._digest([self.root_key, server_id, workspace_id])
        self.root_store = StateStore(state.root.parents[1], "tabs-root-" + root_ns[:32])
        try:
            physical = self.root_store.root.stat()
        except OSError as exc:
            raise RuntimeError("canonical root state namespace unavailable") from exc
        self._root_namespace = self._digest([physical.st_dev, physical.st_ino])
        self._workspace_anchor = _workspace_anchor
        self._workspace_store = None

    @property
    def workspace_store(self) -> StateStore:
        if self._workspace_store is None:
            anchor = _resolve_workspace_anchor() if self._workspace_anchor is None else self._workspace_anchor
            self._workspace_store = StateStore(anchor, "tabs-workspace-" + self.workspace_key[:32])
        return self._workspace_store

    @staticmethod
    def _digest(value: Any) -> str:
        return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

    @contextmanager
    def operations(self) -> Iterator[OperationToken]:
        token = None; workspace_lock = self.workspace_store.operation("workspace")
        root_lock = self.root_store.operation("root")
        try:
            try: workspace_lock.__enter__()
            except BlockingIOError as exc: raise OperationBusy("tab operation deferred due to workspace lock contention") from exc
            try: root_lock.__enter__()
            except BlockingIOError as exc:
                workspace_lock.__exit__(None, None, None)
                raise OperationBusy("tab operation deferred due to root lock contention") from exc
            token = OperationToken(self.root_key, self.workspace_key, self.root_store, self.workspace_store)
            self._check_root_owner(token)
            yield token
        finally:
            if token is not None:
                token.active = False
                root_lock.__exit__(None, None, None)
                workspace_lock.__exit__(None, None, None)

    def _token(self, token: OperationToken) -> None:
        if (not isinstance(token, OperationToken) or not token.active or token.root_key != self.root_key
                or token.workspace_key != self.workspace_key or token.root_store is not self.root_store
                or token.workspace_store is not self.workspace_store):
            raise ValueError("operation token is not active for this tab manager")
        self._check_root_owner(token)

    def _check_root_owner(self, token: OperationToken, *, register: bool = False) -> None:
        """Pin a full logical root to one physical root state namespace."""
        with token.workspace_store.locked() as data:
            registry = data.setdefault("subagent_tabs", {"reservations": {}})
            if not isinstance(registry, dict):
                raise ValueError("invalid tab reservation state")
            owners = registry.setdefault("root_owners", {})
            if not isinstance(owners, dict):
                raise ValueError("invalid tab root owner state")
            owner = owners.get(self.root_key)
            if owner is not None and owner != self._root_namespace:
                raise ValueError("logical root is bound to a different physical state namespace")
            if register and owner is None:
                if len(owners) >= self._MAX_ROOT_OWNERS:
                    raise ValueError("managed tab root owner history exhausted")
                owners[self.root_key] = self._root_namespace

    @staticmethod
    def _clean_title(title: str | None, fallback: str) -> str:
        if title is not None and not isinstance(title, str):
            raise ValueError("title must be text or missing")
        clean = re.sub(r"[\x00-\x1f\x7f-\x9f]", " ", title or fallback)
        clean = re.sub(r"\s+", " ", clean).strip()
        return clean or fallback

    def format_label(self, title: str | None, session_id: str, *, id_length: int = 8, limit: int = 64) -> str:
        if not isinstance(session_id, str) or not session_id or len(session_id) > 512:
            raise ValueError("root session ID required")
        display_id = re.sub(r"[^A-Za-z0-9._-]", "", session_id)
        if not display_id:
            raise ValueError("root session ID has no safe display characters")
        if not isinstance(limit, int) or limit < 1 or not isinstance(id_length, int) or id_length < 1:
            raise ValueError("invalid label budget")
        prefix = "Subagents: "
        length = min(id_length, len(display_id))
        suffix = f" [{display_id[:length]}]"
        if limit < len(prefix) + len(suffix):
            raise ValueError("label budget cannot preserve identity")
        clean = self._clean_title(title, self.root.harness.value)
        return prefix + clean[:limit - len(prefix) - len(suffix)].rstrip() + suffix

    @staticmethod
    def _reservations(data: dict) -> dict:
        registry = data.setdefault("subagent_tabs", {"reservations": {}})
        if not isinstance(registry, dict):
            raise ValueError("invalid tab reservation state")
        reservations = registry.setdefault("reservations", {})
        if not isinstance(reservations, dict):
            raise ValueError("invalid tab reservation state")
        return reservations

    def reserve_label(self, token: OperationToken, title: str | None, session_id: str,
                      generation: str = "pending", *, limit: int = 64) -> LabelReservation:
        self._token(token)
        if not isinstance(generation, str) or not generation or len(generation) > 256:
            raise ValueError("invalid generation")
        clean = self._clean_title(title, self.root.harness.value)
        display_id = re.sub(r"[^A-Za-z0-9._-]", "", session_id)
        if not display_id: raise ValueError("root session ID has no safe display characters")
        with token.workspace_store.locked() as data:
            reservations = self._reservations(data)
            rid = self._digest([self.root_key, generation, self._digest([clean, session_id])])
            existing = reservations.get(rid)
            if (isinstance(existing, dict) and existing.get("status") != "released"
                    and existing.get("root_key") == self.root_key and existing.get("generation") == generation):
                label = existing.get("label")
                if isinstance(label, str) and label:
                    return LabelReservation(self.root_key, label, generation, rid)
            # Released history carries no collision authority. Prune it before
            # adding a new entry, and fail closed if unresolved history fills
            # the bounded registry.
            for old_id, old in list(reservations.items()):
                if isinstance(old, dict) and old.get("status") == "released":
                    del reservations[old_id]
            if rid not in reservations and len(reservations) >= self._MAX_RESERVATIONS:
                raise ValueError("managed tab reservation history exhausted")
            used = {v.get("label") for v in reservations.values() if isinstance(v, dict)
                    and isinstance(v.get("label"), str) and v.get("status") != "released"}
            label = None
            for n in range(min(8, len(display_id)), min(len(display_id), 512) + 1):
                candidate = self.format_label(clean, session_id, id_length=n, limit=limit)
                if candidate not in used:
                    label = candidate
                    break
            if label is None:
                raise ValueError("managed tab label space exhausted")
            reservations[rid] = {"root_key": self.root_key, "generation": generation,
                                 "label": label, "status": "reserved"}
        return LabelReservation(self.root_key, label, generation, rid)

    def begin_create(self, token: OperationToken, reservation: LabelReservation, generation: str) -> CreateClaim:
        self._token(token)
        if (not isinstance(reservation, LabelReservation) or reservation.root_key != self.root_key
                or reservation.generation != generation or not generation):
            raise ValueError("reservation identity mismatch")
        with token.workspace_store.locked() as data:
            reservations = self._reservations(data)
            saved = reservations.get(reservation.reservation_id)
            if not isinstance(saved, dict) or saved.get("root_key") != self.root_key or saved.get("label") != reservation.label:
                raise ValueError("label reservation is no longer valid")
            # Keep creation suppression in the shared workspace index as well
            # as in root state, so a missing local claim cannot permit a retry.
            if any(isinstance(item, dict) and item.get("root_key") == self.root_key
                   and item.get("status") in {"possible", "live", "unknown"}
                   for item in reservations.values()):
                raise ValueError("prior tab claim is unresolved, still live, or has a possible creation reservation")
        claim_id = self._digest([self.root_key, self.server_id, self.workspace_id, generation])
        with token.root_store.locked() as data:
            prior = data.get("subagent_tab")
            # Do not claim a physical namespace unless this is eligible to be
            # the first/new creation claim for the logical root.
            if isinstance(prior, dict) and (prior.get("status") != "removed" or prior.get("generation") == generation):
                raise ValueError("prior tab claim is unresolved, still live, or repeats a generation")
        # An owner is sticky even if the following root-state write is
        # interrupted. That prevents a second profile from taking over after
        # an uncertain first claim.
        self._check_root_owner(token, register=True)
        with token.root_store.locked() as data:
            prior = data.get("subagent_tab")
            # Only exact confirmed removal permits a later generation. Intent,
            # unknown and live generations all fail closed against duplication.
            if isinstance(prior, dict) and (prior.get("status") != "removed" or prior.get("generation") == generation):
                raise ValueError("prior tab claim is unresolved, still live, or repeats a generation")
            data["subagent_tab"] = {"generation": generation, "claim_id": claim_id,
                                   "label": reservation.label, "status": "intent",
                                   "server_id": self.server_id, "workspace_id": self.workspace_id}
        with token.workspace_store.locked() as data:
            saved = self._reservations(data)[reservation.reservation_id]
            saved["status"] = "possible"
        return CreateClaim(self.root_key, generation, reservation.label, claim_id)

    def mark_unknown(self, token: OperationToken, claim: CreateClaim) -> None:
        self._token(token)
        with token.root_store.locked() as data:
            self._claim(data, claim)["status"] = "unknown"

    def commit_create(self, token: OperationToken, claim: CreateClaim, *, tab_id: str,
                      initial_pane_id: str) -> SubagentDestination:
        self._token(token)
        if not self._valid_id(tab_id) or not self._valid_id(initial_pane_id):
            raise ValueError("invalid tab creation acknowledgement")
        with token.root_store.locked() as data:
            state = self._claim(data, claim)
            if state.get("status") != "intent":
                raise ValueError("create acknowledgement has no live intent")
            state.update(status="created", tab_id=tab_id, initial_pane_id=initial_pane_id)
        return SubagentDestination(self.root, self.server_id, self.workspace_id, tab_id,
                                   claim.generation, initial_pane_id)

    @staticmethod
    def _valid_id(value: Any) -> bool:
        return isinstance(value, str) and 0 < len(value) <= 512 and not any(ord(c) < 32 or ord(c) == 127 for c in value)

    def destination(self, token: OperationToken) -> SubagentDestination | None:
        """Return the exact currently committed association, if one exists."""
        self._token(token)
        with token.root_store.locked() as data:
            state = data.get("subagent_tab")
            if (not isinstance(state, dict) or state.get("status") != "created"
                    or state.get("server_id") != self.server_id or state.get("workspace_id") != self.workspace_id
                    or not self._valid_id(state.get("tab_id")) or not self._valid_id(state.get("initial_pane_id"))):
                return None
            return SubagentDestination(self.root, self.server_id, self.workspace_id, state["tab_id"],
                                       state["generation"], state["initial_pane_id"])

    def select_create(self, token: OperationToken, client: Any, cwd: Any, title: str | None,
                      session_id: str, generation: str, *, env: dict[str, str] | None = None) -> SubagentDestination:
        """Persist intent, then perform one create; any transport error is unknown."""
        self._token(token)
        existing = self.destination(token)
        if existing is not None:
            return existing
        reservation = self.reserve_label(token, title, session_id, generation)
        claim = self.begin_create(token, reservation, generation)
        try:
            tab_id, pane_id = client.create_subagent_tab(self.workspace_id, cwd, reservation.label, env=env)
        except BaseException:
            self.mark_unknown(token, claim)
            raise
        return self.commit_create(token, claim, tab_id=tab_id, initial_pane_id=pane_id)

    def reconcile(self, token: OperationToken, client: Any) -> str:
        """Reconcile only a previously acknowledged exact tab; never adopt by label."""
        self._token(token)
        destination = self.destination(token)
        if destination is None:
            with token.root_store.locked() as data:
                state = data.get("subagent_tab")
                return "unresolved" if isinstance(state, dict) and state.get("status") in {"intent", "unknown"} else "absent"
        snapshot = client.snapshot()
        if client.server_identity() != self.server_id:
            return "unresolved"
        if not isinstance(snapshot, dict) or not isinstance(snapshot.get("tabs"), list):
            return "unresolved"
        tab = next((t for t in snapshot["tabs"] if isinstance(t, dict) and t.get("tab_id") == destination.tab_id), None)
        if tab is None:
            panes = snapshot.get("panes")
            if not isinstance(panes, list) or any(isinstance(p, dict) and p.get("tab_id") == destination.tab_id for p in panes):
                return "unresolved"
            self.release_after_removed(token, tab_id=destination.tab_id)
            return "removed"
        if tab.get("workspace_id") != self.workspace_id:
            return "unresolved"
        panes = snapshot.get("panes")
        if not isinstance(panes, list):
            return "unresolved"
        # Existing/moved/user panes keep the association reserved and occupied.
        owned_ids = {destination.initial_pane_id}
        with token.root_store.locked() as data:
            state = data.get("subagent_tab", {})
            raw = state.get("pane_ids", []) if isinstance(state, dict) else []
            if isinstance(raw, list): owned_ids.update(x for x in raw if isinstance(x, str))
        occupants = [p for p in panes if isinstance(p, dict) and p.get("tab_id") == destination.tab_id]
        if not occupants:
            return "unresolved"  # Herdr snapshot is inconsistent; await another tick.
        if any(p.get("pane_id") not in owned_ids for p in occupants):
            return "occupied"
        return "live"

    def bind_child(self, token: OperationToken, destination: SubagentDestination, *, child_pane_id: str) -> SubagentDestination:
        self._token(token)
        if (destination.root_context.key() != self.root_key or destination.herdr_server_id != self.server_id
                or destination.workspace_id != self.workspace_id or not self._valid_id(child_pane_id)):
            raise ValueError("destination authority mismatch")
        with self.root_store.locked() as data:
            state = data.get("subagent_tab")
            if (not isinstance(state, dict) or state.get("status") != "created" or state.get("tab_id") != destination.tab_id
                    or state.get("generation") != destination.generation or state.get("initial_pane_id") != destination.initial_pane_id):
                raise ValueError("destination is no longer current")
            panes = state.setdefault("pane_ids", [destination.initial_pane_id])
            if child_pane_id not in panes:
                if len(panes) >= 1024: raise ValueError("tab pane binding limit reached")
                panes.append(child_pane_id)
            return SubagentDestination(self.root, self.server_id, self.workspace_id, destination.tab_id,
                                       destination.generation, destination.initial_pane_id, child_pane_id)

    def sync_title(self, token: OperationToken, client: Any, title: str | None, session_id: str) -> bool:
        """Reserve before rename; release the old label only after strict acknowledgement."""
        self._token(token)
        destination = self.destination(token)
        if destination is None or not isinstance(title, str) or not title.strip():
            return False
        # A user-created pane may occupy the tab without invalidating our tab
        # ownership. Revalidate server incarnation and exact tab/workspace just
        # before rename; occupancy only prevents cleanup.
        snapshot = client.snapshot()
        if client.server_identity() != self.server_id or not isinstance(snapshot, dict) or not isinstance(snapshot.get("tabs"), list):
            return False
        tab = next((t for t in snapshot["tabs"] if isinstance(t, dict) and t.get("tab_id") == destination.tab_id), None)
        if tab is None or tab.get("workspace_id") != self.workspace_id:
            return False
        with self.root_store.locked() as data:
            state = data.get("subagent_tab", {})
            generation = state.get("generation") if isinstance(state, dict) else None
            old = state.get("label") if isinstance(state, dict) else None
        reservation = self.reserve_label(token, title, session_id, generation)
        if reservation.label == old: return True
        client.rename_subagent_tab(destination.tab_id, self.workspace_id, reservation.label)
        with self.root_store.locked() as data:
            state = data.get("subagent_tab")
            if not isinstance(state, dict) or state.get("tab_id") != destination.tab_id or state.get("generation") != generation:
                raise ValueError("tab association changed during rename")
            state["label"] = reservation.label
        if old:
            self._release_prior_labels(token, generation, reservation.label)
        return True

    def _release_prior_labels(self, token: OperationToken, generation: str, current_label: str) -> None:
        with token.workspace_store.locked() as data:
            for reservation in self._reservations(data).values():
                if (isinstance(reservation, dict) and reservation.get("root_key") == self.root_key
                        and reservation.get("generation") == generation
                        and reservation.get("label") != current_label):
                    reservation["status"] = "released"

    def release_after_removed(self, token: OperationToken, *, tab_id: str) -> bool:
        self._token(token)
        with token.root_store.locked() as data:
            state = data.get("subagent_tab")
            if (not isinstance(state, dict) or state.get("status") != "created" or state.get("tab_id") != tab_id
                    or state.get("server_id") != self.server_id or state.get("workspace_id") != self.workspace_id):
                return False
            generation = state.get("generation")
            label = state.get("label")
            state["status"] = "removed"
        if isinstance(generation, str) and isinstance(label, str):
            with token.workspace_store.locked() as data:
                for reservation in self._reservations(data).values():
                    if (isinstance(reservation, dict) and reservation.get("root_key") == self.root_key
                            and reservation.get("generation") == generation):
                        reservation["status"] = "released"
        return True

    def _claim(self, data: dict, claim: CreateClaim) -> dict:
        if claim.root_key != self.root_key: raise ValueError("create claim root mismatch")
        state = data.get("subagent_tab")
        if (not isinstance(state, dict) or state.get("claim_id") != claim.claim_id
                or state.get("generation") != claim.generation):
            raise ValueError("stale create claim")
        return state
