"""Coordinator for verified standalone Codex creation events."""
from __future__ import annotations
import json
import hashlib
import os
import time
from dataclasses import replace
from pathlib import Path
from typing import Iterable, Protocol
from .model import parent_from_dict, parent_to_dict, session_from_dict, session_to_dict
from .model import Decision, Lifecycle, Outcome, ParentBinding, Session
from .state import (StateStore, load_existing_binding, save_binding,
                    standalone_association_digest, update_binding_outcome)

MAX_RETRIES = 3

class Runtime(Protocol):
    def verify_parent(self, parent: ParentBinding) -> bool: ...
    def sessions(self, parent: ParentBinding) -> Iterable[Session]: ...
    def find_existing_pane(self, parent: ParentBinding, child: Session) -> str | None: ...
    def open_and_attach(self, parent: ParentBinding, child: Session, binding_id: str) -> bool: ...
    def update_title(self, binding_id: str, title: str) -> None: ...
    def can_attach_now(self, parent: ParentBinding, child: Session) -> bool: ...
    def owned_pane_state(self, parent: ParentBinding, child: Session, binding_id: str) -> str: ...

class Coordinator:
    def __init__(self, store: StateStore, runtime: Runtime):
        self.store, self.runtime = store, runtime

    def observe_initial(self, parent: ParentBinding) -> Outcome:
        if not self.runtime.verify_parent(parent):
            return Outcome(Decision.SKIP, "parent context is not verified")
        snapshotter = getattr(self.runtime, "initial_sessions", None)
        try:
            sessions = snapshotter(parent) if snapshotter else list(self.runtime.sessions(parent))
        except Exception:
            sessions = None
        # Recheck after the provider call: parent identity may change while
        # discovery is in flight, in which case this snapshot proves nothing.
        if sessions is None or not self.runtime.verify_parent(parent):
            return Outcome(Decision.WAIT, "initial session discovery is incomplete")
        # Standalone candidates have durable creation associations, so a task
        # already present when observation starts may still be newly created.
        # Baseline only legacy/native sessions; standalone adoption is gated by
        # the verified discovery record in handle().
        keys = {s.context.key() for s in sessions if s.kind != "standalone"}
        self.store.establish_baseline(keys)
        return Outcome(Decision.BASELINE, "existing sessions excluded")

    def handle(self, parent: ParentBinding, child: Session) -> Outcome:
        # This observer has one authority: a verified standalone creation
        # association. Legacy native child records never reach pane effects.
        if child.kind != "standalone":
            return Outcome(Decision.SKIP, "native child handling is retired")
        if not self.runtime.verify_parent(parent):
            return Outcome(Decision.SKIP, "parent context is not verified")
        pc, cc = parent.context, child.context
        if (cc.harness != pc.harness or cc.backend_id != pc.backend_id or cc.backend_instance != pc.backend_instance or
            cc.profile != pc.profile or cc.config_root.resolve() != pc.config_root.resolve() or
            cc.data_root.resolve() != pc.data_root.resolve() or cc.state_root.resolve() != pc.state_root.resolve()):
            return Outcome(Decision.SKIP, "provider/profile/backend mismatch")
        proof = child.creation_proof
        if (proof is None or proof.parent_id != pc.session_id or
                proof.child_id != cc.session_id or child.parent_session_id != pc.session_id):
            return Outcome(Decision.SKIP, "standalone creation proof does not prove this parent")
        key = hashlib.sha256(json.dumps([proof.parent_id, proof.turn_id, proof.item_id],
                                        separators=(",", ":")).encode()).hexdigest()
        return self._handle_standalone(parent, child, key)

    def _handle_standalone(self, parent: ParentBinding, child: Session, event_key: str) -> Outcome:
        """Claim a verified standalone creation under locks, then call runtime unlocked."""
        proof = child.creation_proof
        pc = parent.context
        # The observer lock serializes candidate verification and initial claim.
        # No provider/Herdr operation is permitted while either lock is held.
        with self.store.observing():
            with self.store.locked() as state:
                # Match the exact persisted association while serialized with
                # other observer claims; no provider/native calls occur here.
                candidate_context = {"profile": pc.profile, "backend_id": pc.backend_id,
                                     "backend_instance": pc.backend_instance,
                                     "session_id": pc.session_id}
                candidate_destination = {"server_id": parent.herdr_server_id,
                                         "workspace_id": parent.workspace_id,
                                         "tab_id": parent.tab_id, "pane_id": parent.pane_id}
                expected_path = str(Path(parent.session_path).absolute()) if parent.session_path else None
                digest = hashlib.sha256(os.path.normpath(str(child.cwd)).encode("utf-8")).hexdigest() if child.cwd else None
                discovery = state.get("task_discovery", {})
                authority = discovery.get("authority") or {}
                bound_parent = authority.get("parent", {})
                if (not expected_path or bound_parent.get("parent_id") != pc.session_id
                        or bound_parent.get("path") != expected_path
                        or authority.get("context") != candidate_context
                        or authority.get("destination") != candidate_destination):
                    return Outcome(Decision.SKIP, "standalone parent file is not exactly bound")
                candidate = next((x for x in discovery.get("pending", [])
                                  if x.get("event_key") == event_key and x.get("status") == "verified"
                           and x.get("child_id") == proof.child_id
                           and x.get("parent_id") == pc.session_id
                           and x.get("context") == candidate_context
                           and x.get("destination") == candidate_destination
                           and x.get("cwd_sha256") == proof.cwd_sha256
                           and (proof.cwd_sha256 is None or proof.cwd_sha256 == digest)), None)
                terminal_outcome = next((x for x in discovery.get("outcomes", [])
                                         if x.get("event_key") == event_key
                                         and x.get("child_id") == proof.child_id
                                         and x.get("status") == "attached"), None)
                replay_record = state["records"].get(child.context.key(), {})
                replay = candidate is None and terminal_outcome is not None \
                    and replay_record.get("standalone_event_key") == event_key
                if candidate is None:
                    if not replay:
                        return Outcome(Decision.SKIP, "standalone creation association is not verified")
                    association_hash = replay_record.get("standalone_association_sha256")
                else:
                    association_hash = standalone_association_digest(authority, candidate)
                if child.lifecycle != Lifecycle.RUNNING:
                    return Outcome(Decision.SKIP, "standalone task is not positively running")
                key = child.context.key()
                records = state["records"]
                rec = records.get(key, {})
                if not state.get("baseline_ready"):
                    return Outcome(Decision.SKIP, "initial baseline is not established")
                if key in state.get("baseline", ()):
                    return Outcome(Decision.SKIP, "pre-existing session")
                if rec.get("status") == "suppressed":
                    return Outcome(Decision.SKIP, "pane was manually closed", rec.get("binding_id"))
                generation = proof.turn_id + ":" + proof.item_id
                authority_hash = hashlib.sha256(json.dumps(
                    authority, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
                if rec.get("standalone_event_key") not in (None, event_key):
                    return Outcome(Decision.SKIP, "standalone association changed")
                if rec.get("status") in {"attached", "claimed"} and rec.get(
                        "standalone_association_sha256") != association_hash:
                    return Outcome(Decision.SKIP, "standalone association changed")
                if rec.get("status") not in {"attached", "claimed"}:
                    attempts = int(rec.get("attempts", 0))
                    if attempts >= MAX_RETRIES:
                        return Outcome(Decision.FAILED, "retry budget exhausted", rec.get("binding_id"), attempts)
                    binding = hashlib.sha256(f"{key}:{event_key}".encode()).hexdigest()[:24]
                    rec = {**rec, "status": "claimed", "binding_id": binding,
                           "attempts": attempts, "generation": generation,
                           "turn_id": proof.turn_id, "kind": "standalone",
                           "ownership": "created", "standalone_event_key": event_key,
                           "standalone_association_sha256": association_hash,
                           "standalone_authority_sha256": authority_hash,
                           "standalone_child_id": proof.child_id}
                    records[key] = rec
                    newly_claimed = True
                else:
                    newly_claimed = False
                claim = dict(rec)
                binding = claim.get("binding_id")
                attempts = int(claim.get("attempts", 0))

        # Claim is durable before external inspection/attachment. Concurrent
        # observers see it and can only reconcile, never launch a duplicate.
        claim_binding = binding
        effect = None
        try:
            effect = self.store.standalone_effect(event_key)
            if not newly_claimed or effect is not None:
                pane_state = self.runtime.owned_pane_state(parent, child, binding)
            else:
                pane_state = "new-claim"
        except Exception:
            pane_state = "unknown"
        if pane_state == "closed":
            if not self.store.reconcile_standalone(key, event_key, binding, "suppressed",
                                                   reason="verified pane closure"):
                return Outcome(Decision.WAIT, "standalone association changed during pane inspection", binding, attempts)
            return Outcome(Decision.SKIP, "pane was manually closed", binding)
        if pane_state == "live":
            if not self.store.reconcile_standalone(key, event_key, claim_binding, "attached", title=child.title):
                return Outcome(Decision.WAIT, "standalone association changed during pane inspection", binding, attempts)
            self.store.update_task_candidate(event_key, status="attached", now=time.time())
            if child.title and claim.get("title") != child.title:
                try: self.runtime.update_title(binding, child.title)
                except Exception: pass
            return Outcome(Decision.ATTACHED, "reconciled owned pane", binding, attempts)
        if claim.get("status") == "attached":
            return Outcome(Decision.WAIT, "owned pane state is unknown", binding, attempts)
        if effect is not None:
            return Outcome(Decision.WAIT, "standalone pane outcome is unresolved", binding, attempts)
        if not newly_claimed:
            return Outcome(Decision.WAIT, "stale claim ownership is unknown; fail closed", binding, attempts)
        try:
            existing = self.runtime.find_existing_pane(parent, child)
            live = (child.attachable and child.lifecycle == Lifecycle.RUNNING
                    and self.runtime.can_attach_now(parent, child))
            if live and existing:
                remember = getattr(self.runtime, "remember_reused", None)
                if remember is None:
                    binding = existing
                else:
                    remember(parent, child, binding, existing)
                ok = True
            else:
                ok = bool(live and self.runtime.open_and_attach(parent, child, binding))
        except Exception:
            ok = False
        if ok:
            if not self.store.reconcile_standalone(key, event_key, claim_binding, "attached", title=child.title,
                                                   binding_id=binding,
                                                   ownership="reused" if existing else "created"):
                return Outcome(Decision.WAIT, "standalone association changed during attachment", binding, attempts)
            self.store.update_task_candidate(event_key, status="attached", now=time.time())
            if child.title:
                try: self.runtime.update_title(binding, child.title)
                except Exception: pass
            return Outcome(Decision.ATTACHED, binding_id=binding, attempts=attempts)
        if self.store.standalone_effect(event_key) is not None:
            return Outcome(Decision.WAIT, "standalone pane outcome is unresolved", binding, attempts)
        if not self.store.reconcile_standalone(key, event_key, claim_binding, "pending", attempts=attempts + 1):
            return Outcome(Decision.WAIT, "standalone association changed during attachment", binding, attempts)
        return Outcome(Decision.WAIT if attempts + 1 < MAX_RETRIES else Decision.FAILED,
                       "child not yet attachable", binding, attempts + 1)

class NativeRuntime:
    """Compose a native provider adapter with a verified Herdr presentation client."""
    def __init__(self, store: StateStore, provider: object, herdr: object,
                 entrypoint: Path, backend_pid: int | None = None,
                 state_root: Path | None = None):
        if not entrypoint.is_absolute(): raise ValueError("entrypoint must be absolute")
        self.store, self.provider, self.herdr = store, provider, herdr
        self.entrypoint, self.backend_pid = entrypoint, backend_pid
        self.state_root = state_root or store.root.parent.parent


    def verify_parent(self, parent: ParentBinding) -> bool:
        try:
            if parent.context != self.provider.context or not self._registration_valid(parent):
                return False
            # Session identity and the authenticated current snapshot establish
            # placement; standalone flow does not inspect process metadata.
            destination = self.herdr.session_destination(parent.context.session_id,
                session_path=parent.session_path, harness="codex")
            return (isinstance(destination, dict)
                    and destination.get("server_id") == parent.herdr_server_id
                    and destination.get("workspace_id") == parent.workspace_id
                    and destination.get("tab_id") == parent.tab_id
                    and self.herdr.server_identity() == parent.herdr_server_id)
        except Exception: return False

    def _registration_valid(self, parent: ParentBinding) -> bool:
        manifest = parent.context.config_root / ".harness-herdr-hooks.json"
        try:
            st = manifest.lstat()
            if not manifest.is_file() or manifest.is_symlink() or st.st_uid != os.getuid() or st.st_mode & 0o077: return False
            data = json.loads(manifest.read_text(encoding="utf-8"))
            entry = data.get("entries", {}).get(parent.context.harness.value) if isinstance(data, dict) else None
            source = entry.get("source") if isinstance(entry, dict) else None
            if not isinstance(source, str): return False
            expected = self.entrypoint if parent.context.harness.value == "codex" else self.entrypoint.parent.parent / "integrations/opencode/plugin.js"
            return Path(source).resolve(strict=True) == expected.resolve(strict=True)
        except (OSError, ValueError, TypeError): return False

    def sessions(self, parent: ParentBinding) -> Iterable[Session]:
        if not self.verify_parent(parent): return ()
        try:
            # Materialize here so lazy provider failures are caught too.
            sessions = list(self.provider.sessions(parent))
        except Exception:
            # Persisted close candidates are still considered below, but a
            # failed discovery is never itself terminal evidence.
            sessions = ()
        normalized = []
        seen: set[str] = set()
        for child in sessions:
            # Provider records identify the native backend; the bootstrap adds
            # the pinned backend incarnation to the selected parent context.
            c = replace(child.context, backend_instance=parent.context.backend_instance)
            child = replace(child, context=c)
            if child.kind != "standalone":
                continue
            normalized.append(child)
            seen.add(child.context.key())
        # Discovery can omit a child after it finishes. Reconcile only a
        # positively created, persisted binding for the same parent and exact
        # recorded generation; this is not an input to new-generation adoption.
        return normalized

    def initial_sessions(self, parent: ParentBinding) -> list[Session] | None:
        """Return a complete startup snapshot, or None when discovery failed."""
        if not self.verify_parent(parent):
            return None
        try:
            sessions = list(self.provider.sessions(parent))
            sessions = [replace(child, context=replace(
                child.context, backend_instance=parent.context.backend_instance))
                for child in sessions if child.kind == "standalone"]
        except Exception:
            return None
        if not self.verify_parent(parent):
            return None
        return sessions

    def can_attach_now(self, parent: ParentBinding, child: Session) -> bool:
        return self.verify_parent(parent) and bool(self.provider.can_attach_now(parent, child))


    def find_existing_pane(self, parent: ParentBinding, child: Session) -> str | None:
        if child.kind != "standalone":
            return None
        try:
            destination = self.herdr.session_destination(child.context.session_id,
                session_path=child.session_path, harness="codex")
            if (not destination or destination.get("server_id") != parent.herdr_server_id
                    or destination.get("workspace_id") != parent.workspace_id
                    or destination.get("tab_id") != parent.tab_id):
                return None
            pane_id = destination.get("anchor_pane_id")
            return pane_id if self.herdr.pane_has_session(pane_id, child.context.session_id,
                session_path=child.session_path, harness="codex",
                workspace_id=parent.workspace_id, tab_id=parent.tab_id) else None
        except Exception:
            return None

    def owned_pane_state(self, parent: ParentBinding, child: Session, binding_id: str) -> str:
        try:
            proof = child.creation_proof
            if proof is None:
                return "unknown"
            event_key = hashlib.sha256(json.dumps(
                [proof.parent_id, proof.turn_id, proof.item_id],
                separators=(",", ":")).encode()).hexdigest()
            effect = self.store.standalone_effect(event_key)
            if effect is None:
                record = load_existing_binding(self.state_root, binding_id)
                if (record.get("kind") != "standalone" or record.get("ownership") != "reused"
                        or parent_from_dict(record["parent"]) != parent
                        or session_from_dict(record["child"]).context != child.context):
                    return "unknown"
                effect = {"binding_id": binding_id, "pane_id": record.get("pane_id")}
                reused = True
            else:
                reused = False
            if effect.get("binding_id") != binding_id or not effect.get("pane_id"):
                return "unknown"
            pane_id = effect["pane_id"]
            if self.herdr.pane_has_session(
                    pane_id, child.context.session_id, session_path=child.session_path,
                    workspace_id=parent.workspace_id, tab_id=parent.tab_id):
                if reused:
                    return "live"
                start = self.store.standalone_effect(event_key, "start")
                if start and self.store.mark_standalone_effect(event_key, "start", binding_id, pane_id, "attached"):
                    update_binding_outcome(self.state_root, binding_id, "attached")
                    return "live"
            snap = self.herdr.snapshot()
            panes = snap.get("panes") if isinstance(snap, dict) else None
            if isinstance(panes, list) and not any(
                    isinstance(row, dict) and row.get("pane_id") == effect["pane_id"]
                    for row in panes):
                return "closed"
        except Exception:
            pass
        return "unknown"

    def remember_reused(self, parent: ParentBinding, child: Session, binding_id: str, pane_id: str) -> None:
        if not self.verify_parent(parent) or not self.herdr.pane_has_session(
                pane_id, child.context.session_id, session_path=child.session_path,
                workspace_id=parent.workspace_id, tab_id=parent.tab_id):
            raise ValueError("standalone display changed before reuse")
        self._save_display(parent, child, binding_id, pane_id, "reused")

    def _save_display(self, parent: ParentBinding, child: Session, binding_id: str,
                      pane_id: str, ownership: str) -> None:
        record = {"parent": parent_to_dict(parent), "child": session_to_dict(child),
                  "pane_id": pane_id, "backend_pid": None, "shell_pid": None,
                  "server_socket": str(self.herdr.socket_path), "entrypoint": str(self.entrypoint),
                  "kind": "standalone", "ownership": ownership}
        save_binding(self.state_root, binding_id, record)
        if ownership == "created":
            save_binding(self.state_root, "display-" + child.context.key(), record)

    def update_title(self, binding_id: str, title: str) -> None:
        record = load_existing_binding(self.state_root, binding_id)
        parent, child = parent_from_dict(record["parent"]), session_from_dict(record["child"])
        if self.owned_pane_state(parent, child, binding_id) != "live": return
        self.herdr.rename(record["pane_id"], self.herdr.safe_label(title, child.context.harness.value, child.context.session_id))




    def open_and_attach(self, parent: ParentBinding, child: Session, binding_id: str) -> bool:
        proof = child.creation_proof
        if (child.kind != "standalone" or proof is None
                or proof.parent_id != parent.context.session_id
                or proof.child_id != child.context.session_id
                or not self.verify_parent(parent) or not child.attachable
                or child.lifecycle != Lifecycle.RUNNING):
            return False
        event_key = hashlib.sha256(json.dumps(
            [proof.parent_id, proof.turn_id, proof.item_id],
            separators=(",", ":")).encode()).hexdigest()
        from .attach import attach_standalone_session

        def claim_display(pane_id: str) -> None:
            self._save_display(parent, child, binding_id, pane_id, "created")

        try:
            pane_id = attach_standalone_session(
                self.herdr, self.state_root, event_key=event_key,
                binding_id=binding_id, parent_session_id=parent.context.session_id,
                state_namespace=parent.context.key()[:32],
                parent_session_path=Path(parent.session_path) if parent.session_path else None,
                child_session_id=child.context.session_id,
                backend_socket=Path(child.context.backend_id), cwd=child.cwd,
                profile_home=child.context.config_root, session_path=child.session_path,
                revalidate_binding=lambda: self.can_attach_now(parent, child),
                on_pane_claim=claim_display)
            update_binding_outcome(self.state_root, binding_id, "attached")
            return bool(pane_id)
        except Exception:
            return False


def run_observer(parent: ParentBinding, store: StateStore, provider: object,
                 herdr: object, entrypoint: Path, state_root: Path,
                 backend_pid: int | None = None, *, on_start=None, on_end=None) -> None:
    """Run one context-scoped observer; transport errors are bounded and never terminalize children."""
    import fcntl
    import time
    helper_fd = store._open_private_lock("helper.lock")
    runtime = NativeRuntime(store, provider, herdr, entrypoint, backend_pid, state_root)
    coordinator = Coordinator(store, runtime)
    failures = 0
    started = False
    try:
        fcntl.flock(helper_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if not runtime.verify_parent(parent): return
        if coordinator.observe_initial(parent).decision != Decision.BASELINE: return
        if callable(on_start): on_start()
        started = True
        while runtime.verify_parent(parent):
            try:
                for child in runtime.sessions(parent):
                    outcome = coordinator.handle(parent, child)
                    proof = child.creation_proof
                    if child.kind == "standalone" and proof is not None:
                        event_key = hashlib.sha256(json.dumps(
                            [proof.parent_id, proof.turn_id, proof.item_id],
                            separators=(",", ":")).encode()).hexdigest()
                        if outcome.decision == Decision.ATTACHED:
                            store.update_task_candidate(event_key, status="attached", now=time.time())
                            report = getattr(provider, "_standalone_status", None)
                            if callable(report):
                                report("recognized", "verified", "attached")
                        elif outcome.reason == "standalone pane outcome is unresolved":
                            report = getattr(provider, "_standalone_status", None)
                            if callable(report):
                                report("recognized", "verified", "pending", "attachment_pending")
                failures = 0
            except Exception:
                failures += 1
                if failures >= MAX_RETRIES: return
            time.sleep(1.0)
    finally:
        if started and callable(on_end):
            try: on_end()
            except Exception: pass
        try: fcntl.flock(helper_fd, fcntl.LOCK_UN)
        finally:
            os.close(helper_fd)
            close = getattr(provider, "close", None)
            if callable(close): close()
