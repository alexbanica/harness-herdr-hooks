"""Standalone session attachment and ordinary shell readiness helpers."""
from __future__ import annotations
import time
from contextlib import nullcontext
from pathlib import Path
from typing import Callable
from .herdr import AgentPaneBusy, HerdrClient

class AttachmentUnavailable(RuntimeError):
    pass


_SUPPORTED_SHELLS={'sh','bash','zsh','dash','ksh'}
def shell_is_ready(process_info:dict)->bool:
    shell_pid=process_info.get('shell_pid'); fg=process_info.get('foreground_processes')
    if not isinstance(shell_pid,int) or not isinstance(fg,list) or len(fg)!=1: return False
    proc=fg[0]
    if not isinstance(proc,dict) or proc.get('pid')!=shell_pid: return False
    name=Path(str(proc.get('argv0') or proc.get('name') or '')).name.lower().lstrip('-')
    argv=proc.get('argv') or []
    return name in _SUPPORTED_SHELLS and (not argv or Path(str(argv[0])).name.lower() in _SUPPORTED_SHELLS)

def attach_standalone_session(client: HerdrClient, state_root: Path, *, event_key: str,
                              binding_id: str, parent_session_id: str,
                              state_namespace: str,
                              parent_session_path: Path | None = None,
                              child_session_id: str, backend_socket: Path,
                              cwd: Path, profile_home: Path,
                              session_path: Path | None = None,
                              revalidate_binding: Callable[[], bool] | None = None,
                              on_pane_claim: Callable[[str], None] | None = None,
                              managed=None) -> str:
    """One-shot same-tab split and managed start for a verified standalone child.

    The durable split intent is committed before the Herdr call; a missing
    acknowledgement therefore leaves bounded uncertainty and cannot be replayed.
    This path deliberately does not read process metadata or write shell input.
    """
    from .state import StateStore
    if not state_root.is_absolute() or not backend_socket.is_absolute() or not profile_home.is_absolute():
        raise AttachmentUnavailable("standalone paths must be absolute")
    if not all(isinstance(x, str) and x for x in (event_key, binding_id, parent_session_id, child_session_id)):
        raise AttachmentUnavailable("standalone identity is incomplete")
    if revalidate_binding is not None and not revalidate_binding():
        raise AttachmentUnavailable("standalone parent binding is stale")
    def current_destination():
        if managed is not None:
            return managed.destination
        return client.session_destination(parent_session_id, session_path=parent_session_path,
                                          harness="codex")

    def effect_guard(stage, pane_id=None):
        return managed.guard(stage, event_key=event_key, pane_id=pane_id) if managed is not None else nullcontext()

    destination = current_destination()
    if not isinstance(destination, dict) or set(destination) != {"server_id", "workspace_id", "tab_id", "anchor_pane_id"}:
        raise AttachmentUnavailable("standalone parent does not resolve to one tab")
    if client.server_identity() != destination["server_id"]:
        raise AttachmentUnavailable("standalone Herdr server changed")
    store = StateStore(state_root, state_namespace)
    env = {"CODEX_HOME": str(profile_home.resolve()), "HARNESS_HERDR_DISPLAY": "1",
           "HARNESS_HERDR_STATE_ROOT": str(state_root.resolve())}
    if managed is not None:
        env["PATH"] = managed.split_path
    client_view = managed.client_view if managed is not None else None
    with effect_guard("split") as effect:
        if revalidate_binding is not None and not revalidate_binding():
            raise AttachmentUnavailable("standalone parent binding changed before split")
        if current_destination() != destination or client.server_identity() != destination["server_id"]:
            raise AttachmentUnavailable("standalone destination changed before split")
        if not store.reserve_standalone_effect(event_key, "split", binding_id, child_session_id,
                                               destination, client_view=client_view):
            raise AttachmentUnavailable("standalone split is already claimed or unresolved")
        if effect is not None:
            effect.issue()
        ack = client.split_standalone(destination["workspace_id"], destination["anchor_pane_id"], cwd, env=env)
        if (not isinstance(ack, dict) or not isinstance(ack.get("pane_id"), str) or not ack["pane_id"]
                or ack.get("workspace_id") != destination["workspace_id"]
                or ack.get("tab_id") != destination["tab_id"] or ack.get("focused") is not False):
            raise AttachmentUnavailable("standalone split acknowledgement failed exact destination checks")
        pane_id = ack["pane_id"]
        if not store.record_standalone_pane_claim(event_key, binding_id, destination, pane_id):
            raise AttachmentUnavailable("standalone pane claim could not be persisted")
        if effect is not None:
            effect.resolve()
    if on_pane_claim is not None:
        on_pane_claim(pane_id)
    if revalidate_binding is not None and not revalidate_binding():
        raise AttachmentUnavailable("standalone destination changed before managed start")
    args = ["resume", "--remote", "unix://" + str(backend_socket), child_session_id]
    # Only Herdr's explicit pre-launch shell rejection is safe to retry.
    # Keep the same intent and pane, and recheck authority before each retry.
    delays = (0, .05, .1, .2, .4, .8)
    for attempt, delay in enumerate(delays):
        if delay:
            time.sleep(delay)
            if revalidate_binding is not None and not revalidate_binding():
                raise AttachmentUnavailable("standalone destination changed while waiting for shell")
        with effect_guard("start", pane_id) as effect:
            if attempt == 0 and not store.reserve_standalone_effect(
                    event_key, "start", binding_id, child_session_id, destination,
                    pane_id=pane_id, client_view=client_view):
                raise AttachmentUnavailable("standalone start is already claimed or unresolved")
            snapshot = client.snapshot()
            panes = [pane for pane in snapshot.get("panes", [])
                     if isinstance(pane, dict) and pane.get("pane_id") == pane_id]
            if (client.server_identity() != destination["server_id"] or len(panes) != 1
                    or panes[0].get("workspace_id") != destination["workspace_id"]
                    or panes[0].get("tab_id") != destination["tab_id"]
                    or panes[0].get("focused") is not False
                    or panes[0].get("agent") is not None
                    or panes[0].get("agent_session") is not None):
                raise AttachmentUnavailable("standalone claimed pane changed before managed start")
            if effect is not None:
                effect.issue()
            try:
                started_pane = client.start_agent(pane_id, binding_id, args)
            except AgentPaneBusy:
                if effect is not None:
                    effect.resolve()
                if attempt == len(delays) - 1:
                    raise
                continue
            if started_pane != pane_id:
                raise AttachmentUnavailable("managed standalone start acknowledgement mismatched pane")
            if effect is not None:
                if not store.mark_standalone_effect(event_key, "start", binding_id, pane_id, "started"):
                    raise AttachmentUnavailable("managed start acknowledgement could not be persisted")
                effect.resolve()
            break
    # A start acknowledgement is not attachment proof. Confirm the exact native
    # child reference on the claimed pane with bounded polling only.
    for _ in range(5):
        if client.pane_has_session(pane_id, child_session_id, session_path=session_path,
                                   harness="codex", workspace_id=destination["workspace_id"],
                                   tab_id=destination["tab_id"]) and (
                managed is None or managed.child_is_live(pane_id)):
            if not store.mark_standalone_effect(event_key, "start", binding_id, pane_id, "attached"):
                raise AttachmentUnavailable("standalone attachment acknowledgement could not be persisted")
            return pane_id
        time.sleep(.1)
    raise AttachmentUnavailable("standalone start outcome is unresolved; pane and intent retained")
