"""Idempotent lifecycle coordinator; effects are supplied by provider adapters."""
from __future__ import annotations
import json
import hashlib
import os
import secrets
import time
from dataclasses import replace
from pathlib import Path
from typing import Iterable, Protocol
from .model import (Context, Decision, Lifecycle, Outcome, ParentBinding, Session,
                    parent_to_dict, parent_from_dict, session_to_dict, session_from_dict,
                    matches_agent_session_ref)
from .state import (StateStore, binding_is_close_owned, load_existing_binding,
                    save_binding, update_binding_outcome)

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
        # A discovered standalone task is never a native pre-existing session.
        keys = {s.context.key() for s in sessions if s.kind != "standalone"}
        self.store.establish_baseline(keys)
        return Outcome(Decision.BASELINE, "existing sessions excluded")

    def handle(self, parent: ParentBinding, child: Session) -> Outcome:
        if not self.runtime.verify_parent(parent):
            return Outcome(Decision.SKIP, "parent context is not verified")
        pc, cc = parent.context, child.context
        if (cc.harness != pc.harness or cc.backend_id != pc.backend_id or cc.backend_instance != pc.backend_instance or
            cc.profile != pc.profile or cc.config_root.resolve() != pc.config_root.resolve() or
            cc.data_root.resolve() != pc.data_root.resolve() or cc.state_root.resolve() != pc.state_root.resolve()):
            return Outcome(Decision.SKIP, "provider/profile/backend mismatch")
        if child.kind == "standalone":
            proof = child.creation_proof
            if (proof is None or proof.parent_id != pc.session_id or
                    proof.child_id != cc.session_id or child.parent_session_id != pc.session_id):
                return Outcome(Decision.SKIP, "standalone creation proof does not prove this parent")
            key = hashlib.sha256(json.dumps([proof.parent_id, proof.turn_id, proof.item_id],
                                            separators=(",", ":")).encode()).hexdigest()
        elif child.parent_session_id != pc.session_id and pc.session_id not in child.ancestry:
            return Outcome(Decision.SKIP, "child ancestry does not prove this parent")
        if child.kind == "standalone":
            return self._handle_standalone(parent, child, key)
        with self.store.observing():
            return self._handle_serialized(parent, child)

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
                    association_hash = hashlib.sha256(json.dumps(
                        {"authority": authority, "candidate": candidate}, sort_keys=True,
                        separators=(",", ":")).encode()).hexdigest()
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
        try:
            if not newly_claimed:
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
        if not newly_claimed:
            return Outcome(Decision.WAIT, "stale claim ownership is unknown; fail closed", binding, attempts)
        try:
            existing = self.runtime.find_existing_pane(parent, child)
            if existing:
                binding = existing
            live = child.attachable and self.runtime.can_attach_now(parent, child)
            ok = bool(live and (existing or self.runtime.open_and_attach(parent, child, binding)))
        except Exception:
            ok = False
        if ok:
            if not self.store.reconcile_standalone(key, event_key, claim_binding, "attached", title=child.title,
                                                   binding_id=binding,
                                                   ownership="reused" if existing else "created"):
                return Outcome(Decision.WAIT, "standalone association changed during attachment", binding, attempts)
            self.store.update_task_candidate(event_key, status="attached", now=time.time())
            return Outcome(Decision.ATTACHED, binding_id=binding, attempts=attempts)
        if not self.store.reconcile_standalone(key, event_key, claim_binding, "pending", attempts=attempts + 1):
            return Outcome(Decision.WAIT, "standalone association changed during attachment", binding, attempts)
        return Outcome(Decision.WAIT if attempts + 1 < MAX_RETRIES else Decision.FAILED,
                       "child not yet attachable", binding, attempts + 1)

    def _handle_serialized(self, parent: ParentBinding, child: Session) -> Outcome:
        if not self.runtime.verify_parent(parent):
            return Outcome(Decision.SKIP, "parent context is not verified")
        key = child.context.key()
        generation = child.generation or child.turn_id
        if generation:
            self.store.begin_generation(key, generation, turn_id=child.turn_id or generation,
                                        kind=child.kind, parent_id=child.parent_session_id)
        lifecycle = child.lifecycle
        terminal_status = None
        if child.kind == "subagent" and generation:
            terminal_status = self._confirmed_terminal(child, generation)
            if terminal_status:
                self.store.mark_generation_terminal(key, generation, child.turn_id or generation,
                                                    terminal_status)
        if lifecycle == Lifecycle.FINISHED or terminal_status:
            return self._handle_terminal(parent, child, key, generation, terminal_status)
        with self.store.locked() as state:
            if not state.get("baseline_ready"):
                return Outcome(Decision.SKIP, "initial baseline is not established")
            records = state["records"]
            pending = set(state.get("pending_created", ()))
            rec = records.get(key, {})
            if key in pending:
                # This is the verified serialized observation that consumes a
                # creation marker.  Retain an empty nonterminal record so a
                # later restart cannot rebuild this key into the baseline.
                pending.remove(key)
                state["pending_created"] = sorted(pending)
                if not rec:
                    rec = {"status": "pending", "attempts": 0}
                    records[key] = rec
            if key in state.get("baseline", ()):
                return Outcome(Decision.SKIP, "pre-existing session")
            if rec.get("status") == "suppressed": return Outcome(Decision.SKIP, "pane was manually closed")
            if rec.get("status") == "attached":
                pane_state = self.runtime.owned_pane_state(parent, child, rec["binding_id"])
                if pane_state == "closed":
                    rec.update(status="suppressed", reason="verified pane closure",
                               cleanup={"outcome": "manual-close", "generation": generation})
                    state["records"][key] = rec
                    return Outcome(Decision.SKIP, "pane was manually closed", rec.get("binding_id"))
                if pane_state != "live":
                    return Outcome(Decision.WAIT, "owned pane state is unknown", rec.get("binding_id"))
                if child.title and rec.get("title") != child.title:
                    self.runtime.update_title(rec["binding_id"], child.title)
                    rec["title"] = child.title
                return Outcome(Decision.ATTACHED, binding_id=rec.get("binding_id"))
            if rec.get("status") == "claimed":
                binding_id = rec.get("binding_id")
                pane_state = self.runtime.owned_pane_state(parent, child, binding_id) if binding_id else "unknown"
                if pane_state == "live":
                    rec.update(status="attached", title=child.title)
                    state["records"][key] = rec
                    return Outcome(Decision.ATTACHED, "reconciled owned pane", binding_id, rec.get("attempts", 0))
                if pane_state == "closed":
                    rec.update(status="suppressed", reason="verified pane closure",
                               cleanup={"outcome": "manual-close", "generation": generation})
                    state["records"][key] = rec
                    return Outcome(Decision.SKIP, "pane was manually closed", binding_id)
                return Outcome(Decision.WAIT, "stale claim ownership is unknown; fail closed", binding_id, rec.get("attempts", 0))
            if rec.get("status") == "failed" and int(rec.get("attempts", 0)) >= MAX_RETRIES:
                return Outcome(Decision.FAILED, "retry budget exhausted", rec.get("binding_id"), MAX_RETRIES)
            if child.lifecycle == Lifecycle.UNKNOWN: return Outcome(Decision.SKIP, "child liveness unknown")
            existing = self.runtime.find_existing_pane(parent, child)
            binding = existing or hashlib.sha256(f"{key}:{generation or 'legacy'}".encode()).hexdigest()[:24]
            attempts = int(rec.get("attempts", 0))
            state["records"][key] = {**rec, "status": "claimed", "binding_id": binding,
                                      "attempts": attempts, "generation": generation,
                                      "turn_id": child.turn_id or generation,
                                      "kind": child.kind,
                                      "ownership": "reused" if existing else "created"}
        # Claim lock is released for the bounded external operation. Claim prevents duplicate callers.
        try:
            live = child.lifecycle == Lifecycle.RUNNING and child.attachable and self.runtime.can_attach_now(parent, child)
        except Exception:
            live = False
        if not live:
            self._retry(key, binding, attempts + 1)
            return Outcome(Decision.WAIT if attempts + 1 < MAX_RETRIES else Decision.FAILED,
                           "child not yet attachable", binding, attempts + 1)
        try:
            ok = bool(existing) or self.runtime.open_and_attach(parent, child, binding)
        except Exception:
            ok = False
        capture = getattr(self.runtime, "capture_owned_process", None)
        process_pin = None
        if ok and not existing and callable(capture):
            try:
                process_pin = capture(parent, child, binding)
            except Exception:
                process_pin = None
        with self.store.locked() as state:
            rec = state["records"].get(key, {})
            if ok:
                rec.update(status="attached", title=child.title,
                           ownership="reused" if existing else "created")
                if process_pin is not None:
                    rec["process_pin"] = process_pin
                state["records"][key] = rec
                return Outcome(Decision.ATTACHED, binding_id=binding, attempts=attempts)
            next_attempt = attempts + 1
            rec.update(status="failed" if next_attempt >= MAX_RETRIES else "pending", attempts=next_attempt)
            state["records"][key] = rec
        return Outcome(Decision.FAILED if next_attempt >= MAX_RETRIES else Decision.WAIT,
                       "attach failed", binding, next_attempt)

    def _handle_terminal(self, parent: ParentBinding, child: Session, key: str,
                         generation: str, terminal_status: str | None) -> Outcome:
        """Snapshot under lock, perform provider/Herdr checks unlocked, then persist safely."""
        with self.store.locked() as state:
            if not state.get("baseline_ready"):
                return Outcome(Decision.SKIP, "initial baseline is not established")
            records = state["records"]
            pending = set(state.get("pending_created", ()))
            rec = records.get(key, {})
            if key in pending:
                pending.remove(key)
                state["pending_created"] = sorted(pending)
                if not rec:
                    rec = {"status": "pending", "attempts": 0}
                    records[key] = rec
            if key in state.get("baseline", ()):
                return Outcome(Decision.SKIP, "pre-existing session")
            if rec.get("status") == "suppressed":
                return Outcome(Decision.SKIP, "pane was manually closed")
            binding_id = rec.get("binding_id")
            cleanup = rec.get("cleanup")
            if (isinstance(cleanup, dict) and cleanup.get("outcome") == "closed"
                    and cleanup.get("generation") == generation):
                return Outcome(Decision.SKIP, "confirmed task completed; owned pane already closed", binding_id)
            claim = rec.get("cleanup_claim")
            if (isinstance(claim, dict) and claim.get("generation") == generation
                    and claim.get("binding_id") == binding_id):
                if self._cleanup_claim_live(claim):
                    return Outcome(Decision.WAIT, "terminal cleanup is already claimed", binding_id)
            claim_token = secrets.token_hex(16)
            rec["cleanup_claim"] = {"token": claim_token, "generation": generation,
                                    "binding_id": binding_id, "owner_pid": os.getpid(),
                                    "owner_start_ticks": self._process_start_ticks(os.getpid())}
            snapshot = dict(rec)
        # All native/provider/Herdr calls run without state.lock. In particular,
        # NativeRuntime.close_owned_pane rechecks persisted generation metadata.
        outcome = "retained-unverified"
        pane_state = "unknown"
        if binding_id and terminal_status and child.kind == "subagent":
            try:
                pane_state = self.runtime.owned_pane_state(parent, child, binding_id)
            except Exception:
                pane_state = "unknown"
            if pane_state == "closed":
                outcome = "manual-close"
            else:
                close = getattr(self.runtime, "close_owned_pane", None)
                process_pin = snapshot.get("process_pin")
                try:
                    if (callable(close) and (child.context.harness.value != "codex" or process_pin)
                            and close(parent, child, binding_id, generation, terminal_status, process_pin)):
                        outcome = "closed"
                    elif snapshot.get("ownership") == "reused":
                        outcome = "reused"
                except Exception:
                    outcome = "retained-unverified"
        with self.store.locked() as state:
            rec = state["records"].get(key, {})
            # Do not let a slow close/check overwrite manual suppression or a
            # newer generation/binding installed while the lock was released.
            identity_fields = ("generation", "turn_id", "binding_id", "kind",
                               "ownership", "process_pin")
            current_claim = rec.get("cleanup_claim")
            if (rec.get("status") == "suppressed" and isinstance(current_claim, dict)
                    and current_claim.get("token") == claim_token):
                rec.pop("cleanup_claim", None)
                state["records"][key] = rec
                return Outcome(Decision.SKIP, "pane was manually closed", binding_id)
            if (any(rec.get(field) != snapshot.get(field) for field in identity_fields) or
                    rec.get("status") == "suppressed" or
                    not isinstance(rec.get("cleanup_claim"), dict) or
                    rec["cleanup_claim"].get("token") != claim_token or
                    (isinstance(rec.get("cleanup"), dict) and
                     rec["cleanup"] != snapshot.get("cleanup") and
                     rec["cleanup"].get("outcome") == "closed" and
                     rec["cleanup"].get("generation") == rec.get("generation"))):
                return Outcome(Decision.SKIP, "task state changed during terminal cleanup", binding_id)
            rec.pop("cleanup_claim", None)
            if outcome == "closed":
                rec.update(status="finished", terminal_status=terminal_status,
                           cleanup={"outcome": "closed", "generation": generation})
                reason = "confirmed task completed; owned pane closed"
            else:
                if outcome == "manual-close":
                    rec.update(status="suppressed", reason="verified pane closure")
                rec.update(cleanup={"outcome": outcome, "generation": generation})
                reason = "pane was manually closed" if outcome == "manual-close" else "task terminal or state unknown; pane retained"
            state["records"][key] = rec
        return Outcome(Decision.SKIP, reason, binding_id)

    @staticmethod
    def _process_start_ticks(pid: int) -> int | None:
        try:
            stat_text = Path(f"/proc/{pid}/stat").read_text(encoding="ascii")
            fields = stat_text.rsplit(")", 1)[1].split()
            return int(fields[19])  # Linux stat field 22, process start time.
        except (OSError, ValueError, IndexError):
            return None

    @classmethod
    def _cleanup_claim_live(cls, claim: dict) -> bool:
        pid, started = claim.get("owner_pid"), claim.get("owner_start_ticks")
        if not isinstance(pid, int) or pid <= 0 or not isinstance(started, int):
            return True  # malformed/legacy claim: fail closed
        return cls._process_start_ticks(pid) == started

    def _retry(self, key: str, binding: str, attempts: int) -> None:
        with self.store.locked() as state:
            rec = state["records"].get(key, {})
            rec.update(status="failed" if attempts >= MAX_RETRIES else "pending", binding_id=binding, attempts=attempts)
            state["records"][key] = rec

    def _confirmed_terminal(self, child: Session, generation: str) -> str | None:
        """Require the exact latest persisted terminal turn and a known safe thread state."""
        provider = getattr(self.runtime, "provider", None)
        reader = getattr(provider, "_read_thread", None)
        proxy = getattr(provider, "proxy", None)
        if not callable(reader) or proxy is None:
            return None
        try:
            from .adapters.codex import list_turn_metadata
            turns = list_turn_metadata(proxy, child.context.session_id)
            expected_turn = child.turn_id or generation
            if not turns or turns[0].turn_id != expected_turn or not turns[0].terminal:
                return None
            persisted = self.store.generation(child.context.key())
            if not isinstance(persisted, dict) or (persisted.get("generation"), persisted.get("turn_id")) != (generation, expected_turn):
                return None
            hints = persisted.get("stop_hints", [])
            if not isinstance(hints, list) or any(
                    not isinstance(h, dict) or
                    (h.get("generation"), h.get("turn_id")) != (generation, expected_turn)
                    for h in hints):
                return None
            thread = reader(child.context.session_id)
            status = thread.get("status")
            # A successfully read unloaded thread is known not to be running;
            # active/systemError/unknown status remains ambiguous.
            if not isinstance(status, dict) or status.get("type") not in {"idle", "notLoaded"}:
                return None
            return turns[0].status
        except Exception:
            return None


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
            return (parent.context == self.provider.context and self._registration_valid(parent) and
                    self.herdr.verify_parent(parent, self.backend_pid))
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
            if child.context.harness.value == "codex" and child.kind == "subagent":
                try:
                    from .adapters.codex import list_turn_metadata
                    turns = list_turn_metadata(self.provider.proxy, child.context.session_id)
                    if turns:
                        latest = turns[0]
                        thread = self.provider._read_thread(child.context.session_id)
                        status = thread.get("status")
                        active = isinstance(status, dict) and status.get("type") == "active"
                        child = replace(child, turn_id=latest.turn_id, generation=latest.turn_id,
                                        lifecycle=(Lifecycle.RUNNING if active else
                                                   Lifecycle.FINISHED if latest.terminal else Lifecycle.UNKNOWN),
                                        attachable=bool(active and child.attachable))
                except Exception:
                    child = replace(child, lifecycle=Lifecycle.UNKNOWN, attachable=False)
            normalized.append(child)
            seen.add(child.context.key())
        # Discovery can omit a child after it finishes. Reconcile only a
        # positively created, persisted binding for the same parent and exact
        # recorded generation; this is not an input to new-generation adoption.
        for key, lifecycle in self.store.pending_cleanup_records().items():
            if key in seen or lifecycle.get("continuation_requested"):
                continue
            binding_id = lifecycle.get("binding_id")
            try:
                binding = load_existing_binding(self.state_root, binding_id)
                child = session_from_dict(binding["child"])
                stored_parent = parent_from_dict(binding["parent"])
                if (not binding_is_close_owned(binding) or stored_parent != parent
                        or child.context.key() != key
                        or binding.get("generation") != lifecycle.get("generation")
                        or binding.get("turn_id") != lifecycle.get("turn_id")
                        or binding.get("close_suppressed") is True):
                    continue
                child = replace(child, context=replace(child.context,
                                                       backend_instance=parent.context.backend_instance),
                                generation=lifecycle["generation"], turn_id=lifecycle["turn_id"],
                                lifecycle=Lifecycle.FINISHED, attachable=False)
                normalized.append(child)
                seen.add(key)
            except Exception:
                continue
        return normalized

    def initial_sessions(self, parent: ParentBinding) -> list[Session] | None:
        """Return a complete startup snapshot, or None when discovery failed."""
        if not self.verify_parent(parent):
            return None
        try:
            sessions = list(self.provider.sessions(parent))
            sessions = [replace(child, context=replace(
                child.context, backend_instance=parent.context.backend_instance))
                for child in sessions]
        except Exception:
            return None
        if not self.verify_parent(parent):
            return None
        return sessions

    def can_attach_now(self, parent: ParentBinding, child: Session) -> bool:
        return self.verify_parent(parent) and bool(self.provider.can_attach_now(parent, child))

    def _argv_matches(self, actual: object, child: Session) -> bool:
        # Herdr owns executable and explicit backend-alias canonicalization.
        # Lazy lookup permits coordinated integration while the adapter lands.
        try:
            from .herdr import attachment_argv_matches
        except ImportError:
            return False
        try:
            return bool(attachment_argv_matches(actual, self.provider.attach_argv(child), child.context))
        except Exception:
            return False

    def find_existing_pane(self, parent: ParentBinding, child: Session) -> str | None:
        if not self.verify_parent(parent) or not self.can_attach_now(parent, child): return None
        try: snap = self.herdr.snapshot()
        except Exception: return None
        for pane in snap.get("panes", []):
            if not isinstance(pane, dict) or pane.get("workspace_id") != parent.workspace_id or pane.get("tab_id") != parent.tab_id: continue
            ref = pane.get("agent_session")
            if not matches_agent_session_ref(ref, child.context.session_id, child.session_path): continue
            if child.context.harness.value not in (str(ref.get("agent", "")) + " " + str(ref.get("source", ""))).lower(): continue
            try: info = self.herdr.process_info(pane.get("pane_id", ""))
            except Exception: continue
            procs = info.get("foreground_processes", [])
            if (len(procs) == 1 and isinstance(procs[0], dict)
                    and self._process_matches(procs[0], child)):
                binding = self._opaque_id(child)
                save_binding(self.state_root, binding, {"parent": parent_to_dict(parent),
                    "child": session_to_dict(child), "pane_id": pane.get("pane_id"),
                    "backend_pid": self.backend_pid, "server_socket": str(self.herdr.socket_path),
                    "entrypoint": str(self.entrypoint), "shell_pid": None,
                    "ownership": "reused", "kind": child.kind,
                    "generation": child.generation or child.turn_id,
                    "turn_id": child.turn_id or child.generation})
                self.herdr.rename(pane["pane_id"], self.herdr.safe_label(child.title, child.context.harness.value, child.context.session_id))
                return binding
        return None

    @staticmethod
    def _opaque_id(child: Session) -> str:
        value = f"{child.context.key()}:{child.generation or child.turn_id or 'legacy'}"
        return hashlib.sha256(value.encode()).hexdigest()[:24]

    def _process_matches(self, process: dict, child: Session) -> bool:
        try:
            from .herdr import process_matches_attachment
            return process_matches_attachment(process, self.provider.attach_argv(child), child.context)
        except Exception:
            return False

    def owned_pane_state(self, parent: ParentBinding, child: Session, binding_id: str) -> str:
        try:
            record = load_existing_binding(self.state_root, binding_id)
            if (parent_from_dict(record["parent"]) != parent or
                    session_from_dict(record["child"]).context != child.context or
                    record.get("server_socket") != str(self.herdr.socket_path)):
                return "unknown"
            if not self.verify_parent(parent): return "unknown"
            if not record.get("pane_id"): return "unknown"
            snap = self.herdr.snapshot()
            pane = next((p for p in snap.get("panes", []) if isinstance(p, dict) and p.get("pane_id") == record.get("pane_id")), None)
            if pane is None: return "closed"
            if pane.get("workspace_id") != parent.workspace_id or pane.get("tab_id") != parent.tab_id: return "unknown"
            ref = pane.get("agent_session")
            if not matches_agent_session_ref(ref, child.context.session_id, child.session_path): return "unknown"
            info = self.herdr.process_info(record["pane_id"])
            procs = info.get("foreground_processes", [])
            return "live" if len(procs) == 1 and isinstance(procs[0], dict) and self._process_matches(procs[0], child) else "unknown"
        except FileNotFoundError: return "unknown"
        except Exception: return "unknown"

    @staticmethod
    def _pinned_display_state(pin: dict[str, object], *, proc_root: Path = Path("/proc")) -> str:
        """Return live/exited/unknown without treating a reused PID as an exit proof."""
        pid, started = pin.get("pid"), pin.get("start_ticks")
        if not isinstance(pid, int) or pid <= 0 or not isinstance(started, int):
            return "unknown"
        root = proc_root / str(pid)
        try:
            raw = (root / "stat").read_text(encoding="ascii")
        except FileNotFoundError:
            return "exited"
        except OSError:
            return "unknown"
        try:
            fields = raw[raw.rfind(")") + 2:].split()
            if len(fields) < 20:
                return "unknown"
            return "live" if int(fields[19]) == started else "unknown"
        except (ValueError, IndexError):
            return "unknown"

    @staticmethod
    def _empty_display_pty(info: dict[str, object]) -> bool:
        # Herdr must report no foreground process and a concrete PTY; then the
        # existing bounded /proc scan proves that no process owns that PTY.
        if info.get("foreground_processes") != []:
            return False
        tty = info.get("tty")
        if not isinstance(tty, str):
            return False
        from .attach import _tty_has_no_processes
        return _tty_has_no_processes(tty)

    def update_title(self, binding_id: str, title: str) -> None:
        record = load_existing_binding(self.state_root, binding_id)
        parent, child = parent_from_dict(record["parent"]), session_from_dict(record["child"])
        if self.owned_pane_state(parent, child, binding_id) != "live": return
        self.herdr.rename(record["pane_id"], self.herdr.safe_label(title, child.context.harness.value, child.context.session_id))

    def capture_owned_process(self, parent: ParentBinding, child: Session,
                              binding_id: str) -> dict[str, object] | None:
        """Capture the sole attached Codex client PID and kernel start identity."""
        try:
            record = load_existing_binding(self.state_root, binding_id)
            if (not binding_is_close_owned(record) or not self.verify_parent(parent)
                    or not record.get("pane_id")):
                return None
            info = self.herdr.process_info(record["pane_id"])
            processes = info.get("foreground_processes", [])
            if len(processes) != 1 or not isinstance(processes[0], dict):
                return None
            process = processes[0]
            if not self._process_matches(process, child):
                return None
            tty = info.get("tty")
            from .herdr import _codex_proc_proof
            proof = _codex_proc_proof(process)
            pin = {"pid": proof.pid, "uid": proof.uid, "start_ticks": proof.start_ticks,
                   "executable": str(proof.executable), "cwd": str(proof.cwd)}
            # Legacy/live cleanup needs only the original process pin. Exited
            # cleanup additionally requires a PTY incarnation captured now.
            if isinstance(tty, str):
                from .attach import _tty_identity
                tty_identity = _tty_identity(tty)
                if tty_identity is not None:
                    pin.update(tty=tty, tty_identity=list(tty_identity))
            return pin
        except Exception:
            return None

    def close_owned_pane(self, parent: ParentBinding, child: Session, binding_id: str,
                         generation: str, terminal_status: str,
                         process_pin: dict[str, object] | None) -> bool:
        """Close only the integration-created pane for the confirmed generation."""
        try:
            record = load_existing_binding(self.state_root, binding_id)
            if (not binding_is_close_owned(record) or record.get("generation") != generation
                    or record.get("turn_id") != (child.turn_id or generation)
                    or record.get("kind") != "subagent"
                    or not isinstance(process_pin, dict)
                    or parent_from_dict(record["parent"]) != parent
                    or session_from_dict(record["child"]).context != child.context
                    or record.get("server_socket") != str(self.herdr.socket_path)
                    or not record.get("pane_id") or not self.verify_parent(parent)):
                return False
            lifecycle = self.store.record(child.context.key())
            claim = lifecycle.get("cleanup_claim") if isinstance(lifecycle, dict) else None
            if (not isinstance(lifecycle, dict) or lifecycle.get("status") == "suppressed"
                    or lifecycle.get("generation") != generation
                    or lifecycle.get("binding_id") != binding_id
                    or not isinstance(claim, dict)
                    or claim.get("generation") != generation
                    or claim.get("binding_id") != binding_id):
                return False
            claim_identity = dict(claim)
            # Requery the latest native turn immediately before the close.
            if Coordinator(self.store, self)._confirmed_terminal(child, generation) != terminal_status:
                return False
            info = self.herdr.process_info(record["pane_id"])
            processes = info.get("foreground_processes", [])
            display_state = self._pinned_display_state(process_pin)
            if display_state == "live":
                if (self.owned_pane_state(parent, child, binding_id) != "live"
                        or len(processes) != 1 or not isinstance(processes[0], dict)
                        or processes[0].get("pid") != process_pin.get("pid")
                        or not self._process_matches(processes[0], child)):
                    return False
                from .herdr import _codex_proc_proof
                current = _codex_proc_proof(processes[0])
                if (current.start_ticks != process_pin.get("start_ticks")
                        or current.uid != process_pin.get("uid")
                        or str(current.executable) != process_pin.get("executable")
                        or str(current.cwd) != process_pin.get("cwd")):
                    return False
            elif display_state == "exited":
                from .attach import _tty_identity
                if (not isinstance(process_pin.get("tty"), str)
                        or not isinstance(process_pin.get("tty_identity"), list)
                        or info.get("tty") != process_pin.get("tty")
                        or list(_tty_identity(info.get("tty")) or ()) != process_pin.get("tty_identity")
                        or not self._empty_display_pty(info)):
                    return False
            else:
                return False
            latest = self.herdr.snapshot()
            pane = next((p for p in latest.get("panes", [])
                         if isinstance(p, dict) and p.get("pane_id") == record["pane_id"]), None)
            if (not pane or pane.get("workspace_id") != parent.workspace_id
                    or pane.get("tab_id") != parent.tab_id
                    or not matches_agent_session_ref(pane.get("agent_session"),
                                                     child.context.session_id, child.session_path)):
                return False
            # Re-read the sole foreground process after the final pane snapshot;
            # same session text alone cannot grant close rights after replacement.
            final_info = self.herdr.process_info(record["pane_id"])
            refreshed = final_info.get("foreground_processes", [])
            if display_state == "live":
                if (len(refreshed) != 1 or not isinstance(refreshed[0], dict)
                        or refreshed[0].get("pid") != process_pin.get("pid")
                        or not self._process_matches(refreshed[0], child)):
                    return False
                current = _codex_proc_proof(refreshed[0])
                if (current.start_ticks != process_pin.get("start_ticks")
                        or current.uid != process_pin.get("uid")
                        or str(current.executable) != process_pin.get("executable")
                        or str(current.cwd) != process_pin.get("cwd")):
                    return False
            elif (final_info.get("tty") != process_pin.get("tty")
                  or list(_tty_identity(final_info.get("tty")) or ()) != process_pin.get("tty_identity")
                  or not self._empty_display_pty(final_info)
                  or self._pinned_display_state(process_pin) != "exited"):
                return False
            # External Herdr/process calls above can race with a resumed turn,
            # suppression, or claim replacement. Revalidate the exact persisted
            # authority and backend terminal state immediately before close.
            final_terminal = Coordinator(self.store, self)._confirmed_terminal(child, generation)
            final_lifecycle = self.store.generation(child.context.key())
            final_claim = (final_lifecycle.get("cleanup_claim")
                           if isinstance(final_lifecycle, dict) else None)
            if (not isinstance(final_lifecycle, dict)
                    or final_lifecycle.get("status") == "suppressed"
                    or final_lifecycle.get("generation") != generation
                    or final_lifecycle.get("turn_id") != (child.turn_id or generation)
                    or final_lifecycle.get("binding_id") != binding_id
                    or final_lifecycle.get("kind") != "subagent"
                    or final_lifecycle.get("ownership") != lifecycle.get("ownership")
                    or final_lifecycle.get("process_pin") != process_pin
                    or final_claim != claim_identity
                    or generation not in final_lifecycle.get("terminal_generations", [])
                    or final_lifecycle.get("turn_status") != terminal_status
                    or final_terminal != terminal_status):
                return False
            self.herdr.close(record["pane_id"])
            return True
        except Exception:
            return False

    def open_and_attach(self, parent: ParentBinding, child: Session, binding_id: str) -> bool:
        if not self.can_attach_now(parent, child): return False
        try:
            # A prior split/launch may have raced with a crash. Never overwrite
            # its evidence or create another pane when its outcome is unknown.
            load_existing_binding(self.state_root, binding_id)
            return False
        except FileNotFoundError:
            pass
        record = {"parent": parent_to_dict(parent), "child": session_to_dict(child),
                  "pane_id": None, "backend_pid": self.backend_pid,
                  "server_socket": str(self.herdr.socket_path), "entrypoint": str(self.entrypoint),
                  "shell_pid": None, "ownership": "created", "kind": child.kind,
                  "generation": child.generation or child.turn_id,
                  "turn_id": child.turn_id or child.generation}
        save_binding(self.state_root, binding_id, record)
        from .attach import attach_in_new_pane
        def created(pane_id: str, process_info: dict) -> None:
            record["pane_id"] = pane_id
            shell_pid = process_info.get("shell_pid")
            record["shell_pid"] = shell_pid if isinstance(shell_pid, int) else None
            save_binding(self.state_root, binding_id, record)
        try:
            pane_id = attach_in_new_pane(self.herdr, self, parent, child, self.entrypoint,
                                         binding_id, self.state_root, self.backend_pid,
                                         on_pane_created=created)
            attached = bool(pane_id and record.get("pane_id") == pane_id and self.owned_pane_state(parent, child, binding_id) == "live")
            if attached:
                update_binding_outcome(self.state_root, binding_id, "attached", record.get("shell_pid"))
                self.herdr.rename(pane_id, self.herdr.safe_label(child.title, child.context.harness.value, child.context.session_id))
            return attached
        except Exception: return False


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
