"""Idempotent lifecycle coordinator; effects are supplied by provider adapters."""
from __future__ import annotations
import json
import hashlib
import os
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
        keys = {s.context.key() for s in self.runtime.sessions(parent)}
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
        if child.parent_session_id != pc.session_id and pc.session_id not in child.ancestry:
            return Outcome(Decision.SKIP, "child ancestry does not prove this parent")
        with self.store.observing():
            return self._handle_serialized(parent, child)

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
            if lifecycle == Lifecycle.FINISHED or terminal_status:
                binding_id = rec.get("binding_id")
                cleanup = rec.get("cleanup")
                if (isinstance(cleanup, dict) and cleanup.get("outcome") == "closed"
                        and cleanup.get("generation") == generation):
                    return Outcome(Decision.SKIP, "confirmed task completed; owned pane already closed", binding_id)
                if binding_id and terminal_status and child.kind == "subagent":
                    try:
                        pane_state = self.runtime.owned_pane_state(parent, child, binding_id)
                    except Exception:
                        pane_state = "unknown"
                    if pane_state == "closed":
                        rec.update(cleanup={"outcome": "manual-close", "generation": generation})
                        state["records"][key] = rec
                        return Outcome(Decision.SKIP, "pane was manually closed", binding_id)
                    close = getattr(self.runtime, "close_owned_pane", None)
                    process_pin = rec.get("process_pin")
                    if (callable(close) and (child.context.harness.value != "codex" or process_pin)
                            and close(parent, child, binding_id, generation, terminal_status,
                                      process_pin)):
                        rec.update(status="finished", terminal_status=terminal_status,
                                   cleanup={"outcome": "closed", "generation": generation})
                        state["records"][key] = rec
                        return Outcome(Decision.SKIP, "confirmed task completed; owned pane closed", binding_id)
                    outcome = "reused" if rec.get("ownership") == "reused" else "retained-unverified"
                else:
                    outcome = "retained-unverified"
                rec.update(cleanup={"outcome": outcome, "generation": generation})
                state["records"][key] = rec
                return Outcome(Decision.SKIP, "task terminal or state unknown; pane retained", binding_id)
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

    def _retry(self, key: str, binding: str, attempts: int) -> None:
        with self.store.locked() as state:
            rec = state["records"].get(key, {})
            rec.update(status="failed" if attempts >= MAX_RETRIES else "pending", binding_id=binding, attempts=attempts)
            state["records"][key] = rec

    def _confirmed_terminal(self, child: Session, generation: str) -> str | None:
        """Require exact persisted turn metadata plus an inactive thread status."""
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
            # Only a known idle native thread plus its latest terminal persisted
            # turn proves quiescence. Missing/unknown status remains ambiguous.
            if not isinstance(status, dict) or status.get("type") != "idle":
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
        sessions = self.provider.sessions(parent)
        normalized = []
        for child in sessions:
            # Provider records identify the native backend; the bootstrap adds
            # the pinned backend incarnation to the selected parent context.
            c = replace(child.context, backend_instance=parent.context.backend_instance)
            child = replace(child, context=c)
            if child.context.harness.value == "codex":
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
        return normalized

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
            from .herdr import _codex_proc_proof
            proof = _codex_proc_proof(process)
            return {"pid": proof.pid, "uid": proof.uid, "start_ticks": proof.start_ticks,
                    "executable": str(proof.executable), "cwd": str(proof.cwd)}
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
            # Requery the latest native turn immediately before the close.
            if Coordinator(self.store, self)._confirmed_terminal(child, generation) != terminal_status:
                return False
            if self.owned_pane_state(parent, child, binding_id) != "live":
                return False
            info = self.herdr.process_info(record["pane_id"])
            processes = info.get("foreground_processes", [])
            if (len(processes) != 1 or not isinstance(processes[0], dict)
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
            refreshed = self.herdr.process_info(record["pane_id"]).get("foreground_processes", [])
            if (len(refreshed) != 1 or not isinstance(refreshed[0], dict)
                    or refreshed[0].get("pid") != process_pin.get("pid")
                    or not self._process_matches(refreshed[0], child)):
                return False
            current = _codex_proc_proof(refreshed[0])
            if current.start_ticks != process_pin.get("start_ticks"):
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
                    coordinator.handle(parent, child)
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
