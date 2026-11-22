"""Provider-neutral, deliberately minimal runtime records."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Mapping


class Harness(str, Enum):
    CODEX = "codex"
    OPENCODE = "opencode"


@dataclass(frozen=True, slots=True)
class Context:
    harness: Harness
    profile: str
    config_root: Path
    data_root: Path
    state_root: Path
    backend_id: str
    session_id: str
    backend_instance: str = ""

    def key(self) -> str:
        """Stable namespace from the full authority identity, never title/cwd."""
        import hashlib, json
        fields = [self.harness.value, self.profile, str(self.config_root.resolve()),
                  str(self.data_root.resolve()), str(self.state_root.resolve()),
                  self.backend_id, self.backend_instance, self.session_id]
        return hashlib.sha256(json.dumps(fields, separators=(",", ":")).encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class ParentBinding:
    context: Context
    herdr_server_id: str
    workspace_id: str
    tab_id: str
    pane_id: str
    ancestry: tuple[str, ...] = ()
    session_path: Path | None = None
    # Bounded native proof pins only; intentionally excludes environment and argv.
    backend_proof: Mapping[str, object] | None = None


@dataclass(frozen=True, slots=True)
class SubagentDestination:
    """Optional destination authority kept separate from the original parent proof."""
    root_context: Context
    herdr_server_id: str
    workspace_id: str
    tab_id: str
    generation: str
    initial_pane_id: str
    child_pane_id: str | None = None


def destination_to_dict(value: SubagentDestination) -> dict[str, object]:
    return {"root_context": context_to_dict(value.root_context),
            "herdr_server_id": value.herdr_server_id, "workspace_id": value.workspace_id,
            "tab_id": value.tab_id, "generation": value.generation,
            "initial_pane_id": value.initial_pane_id, "child_pane_id": value.child_pane_id}


def destination_from_dict(value: object) -> SubagentDestination:
    keys = {"root_context", "herdr_server_id", "workspace_id", "tab_id", "generation", "initial_pane_id", "child_pane_id"}
    if not isinstance(value, dict) or set(value) != keys:
        raise ValueError("invalid subagent destination fields")
    for key in ("herdr_server_id", "workspace_id", "tab_id", "generation", "initial_pane_id"):
        limit = 256 if key == "generation" else 512
        if (not isinstance(value[key], str) or not value[key] or len(value[key]) > limit
                or any(ord(c) < 32 or 127 <= ord(c) <= 159 for c in value[key])):
            raise ValueError("invalid subagent destination identity")
    child = value["child_pane_id"]
    if child is not None and (not isinstance(child, str) or not child or len(child) > 512
                              or any(ord(c) < 32 or 127 <= ord(c) <= 159 for c in child)):
        raise ValueError("invalid subagent child pane identity")
    return SubagentDestination(context_from_dict(value["root_context"]), value["herdr_server_id"],
                               value["workspace_id"], value["tab_id"], value["generation"],
                               value["initial_pane_id"], child)


def validate_binding_destination(destination: SubagentDestination, parent: ParentBinding,
                                 child: Session, *, kind: str, generation: str | None,
                                 pane_id: str | None) -> None:
    """Require an integration destination to remain rooted in the original parent proof."""
    if kind != "subagent" or child.kind != "subagent":
        raise ValueError("only subagent bindings may have a tab destination")
    root = destination.root_context
    if root != parent.context:
        raise ValueError("destination root does not match original parent context")
    if (root.session_id == child.context.session_id
            or (root.harness, root.profile, root.config_root.resolve(), root.data_root.resolve(),
                root.state_root.resolve(), root.backend_id, root.backend_instance)
            != (child.context.harness, child.context.profile, child.context.config_root.resolve(),
                child.context.data_root.resolve(), child.context.state_root.resolve(),
                child.context.backend_id, child.context.backend_instance)):
        raise ValueError("destination child is outside the root session context")
    if (destination.herdr_server_id != parent.herdr_server_id
            or destination.workspace_id != parent.workspace_id):
        raise ValueError("destination server or workspace differs from original parent")
    if destination.tab_id == parent.tab_id or destination.initial_pane_id == parent.pane_id:
        raise ValueError("destination must identify a separate managed tab")
    if generation is not None and (not isinstance(generation, str) or not generation or len(generation) > 512):
        raise ValueError("invalid binding generation")
    if pane_id is not None and destination.child_pane_id is not None and pane_id != destination.child_pane_id:
        raise ValueError("destination child pane differs from binding pane pin")


class Lifecycle(str, Enum):
    STARTING = "starting"
    RUNNING = "running"
    FINISHED = "finished"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class Session:
    context: Context
    parent_session_id: str | None
    title: str | None
    cwd: Path
    lifecycle: Lifecycle
    attachable: bool
    observed_at: float
    ancestry: tuple[str, ...] = ()
    session_path: Path | None = None
    # ``subagent`` sessions may own an integration-created pane; an
    # ``independent`` interactive session is deliberately retained.
    kind: str = "subagent"
    turn_id: str | None = None
    generation: str | None = None
    creation_proof: "CreationProof | None" = None


@dataclass(frozen=True, slots=True)
class CreationProof:
    """Minimum ID-only evidence associating a standalone task with its parent."""
    parent_id: str
    turn_id: str
    item_id: str
    child_id: str
    cwd_sha256: str | None = None

    def __post_init__(self) -> None:
        if any(not isinstance(x, str) or not x for x in
               (self.parent_id, self.turn_id, self.item_id, self.child_id)):
            raise ValueError("invalid creation proof identity")
        if self.parent_id == self.child_id:
            raise ValueError("creation proof child must differ from parent")
        if self.cwd_sha256 is not None and (not isinstance(self.cwd_sha256, str) or
                len(self.cwd_sha256) != 64 or any(c not in "0123456789abcdef" for c in self.cwd_sha256)):
            raise ValueError("invalid creation cwd digest")


class Decision(str, Enum):
    BASELINE = "baseline"
    SKIP = "skip"
    WAIT = "wait"
    CLAIM = "claim"
    ATTACHED = "attached"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class Outcome:
    decision: Decision
    reason: str = ""
    binding_id: str | None = None
    attempts: int = 0


@dataclass(frozen=True, slots=True)
class Event:
    context: Context
    kind: str
    title: str | None = None
    cwd: Path | None = None
    parent_session_id: str | None = None
    metadata: Mapping[str, object] | None = None


def context_to_dict(c: Context) -> dict[str, object]:
    return {"harness": c.harness.value, "profile": c.profile,
            "config_root": str(c.config_root), "data_root": str(c.data_root),
            "state_root": str(c.state_root), "backend_id": c.backend_id,
            "session_id": c.session_id, "backend_instance": c.backend_instance}


def context_from_dict(v: object) -> Context:
    d = _mapping(v, {"harness", "profile", "config_root", "data_root", "state_root", "backend_id", "session_id", "backend_instance"})
    if any(not isinstance(d[k], str) or (not d[k] and k != "backend_instance") for k in d): raise ValueError("invalid serialized context")
    if not all(Path(d[k]).is_absolute() for k in ("config_root", "data_root", "state_root")): raise ValueError("context paths must be absolute")
    return Context(Harness(d["harness"]), d["profile"], Path(d["config_root"]), Path(d["data_root"]), Path(d["state_root"]), d["backend_id"], d["session_id"], d["backend_instance"])


def parent_to_dict(p: ParentBinding) -> dict[str, object]:
    result = {"context": context_to_dict(p.context), "herdr_server_id": p.herdr_server_id,
            "workspace_id": p.workspace_id, "tab_id": p.tab_id, "pane_id": p.pane_id,
            "ancestry": list(p.ancestry),
            "session_path": str(p.session_path.resolve(strict=False)) if p.session_path else None}
    if p.backend_proof is not None:
        result["backend_proof"] = dict(p.backend_proof)
    return result


def parent_from_dict(v: object) -> ParentBinding:
    old_keys = {"context", "herdr_server_id", "workspace_id", "tab_id", "pane_id", "ancestry"}
    new_keys = old_keys | {"session_path"}
    pinned_keys = new_keys | {"backend_proof"}
    if not isinstance(v, dict) or set(v) not in (old_keys, new_keys, pinned_keys): raise ValueError("serialized record has unknown or missing fields")
    d = v
    if any(not isinstance(d[k], str) or not d[k] for k in ("herdr_server_id", "workspace_id", "tab_id", "pane_id")) or not isinstance(d["ancestry"], list) or not all(isinstance(x, str) for x in d["ancestry"]): raise ValueError("invalid serialized parent")
    path = _canonical_optional_path(d.get("session_path"))
    proof = d.get("backend_proof")
    if proof is not None:
        allowed = {"socket_alias", "socket_target", "socket_identity", "alias_identity", "directory_identity", "pid", "uid", "executable", "cwd", "start_ticks"}
        if not isinstance(proof, dict) or set(proof) - allowed or len(proof) > len(allowed): raise ValueError("invalid backend proof fields")
        for key in ("socket_alias", "socket_target", "executable", "cwd"):
            if key in proof and (not isinstance(proof[key], str) or not Path(proof[key]).is_absolute()): raise ValueError("backend proof paths must be absolute")
        for key in ("pid", "uid", "start_ticks"):
            if key in proof and (not isinstance(proof[key], int) or proof[key] < 0): raise ValueError("invalid backend process pin")
        for key in ("socket_identity", "alias_identity", "directory_identity"):
            if key in proof and (not isinstance(proof[key], list) or len(proof[key]) != 5 or not all(isinstance(x, int) and x >= 0 for x in proof[key])): raise ValueError("invalid backend filesystem pin")
    return ParentBinding(context_from_dict(d["context"]), d["herdr_server_id"], d["workspace_id"], d["tab_id"], d["pane_id"], tuple(d["ancestry"]), path, proof)


def session_to_dict(s: Session) -> dict[str, object]:
    result = {"context": context_to_dict(s.context), "parent_session_id": s.parent_session_id,
            "title": s.title, "cwd": str(s.cwd), "lifecycle": s.lifecycle.value,
            "attachable": s.attachable, "observed_at": s.observed_at, "ancestry": list(s.ancestry),
            "session_path": str(s.session_path.resolve(strict=False)) if s.session_path else None,
            "kind": s.kind, "turn_id": s.turn_id, "generation": s.generation}
    if s.creation_proof is not None:
        result["creation_proof"] = creation_proof_to_dict(s.creation_proof)
    return result


def session_from_dict(v: object) -> Session:
    old_keys = {"context", "parent_session_id", "title", "cwd", "lifecycle", "attachable", "observed_at", "ancestry"}
    path_keys = old_keys | {"session_path"}
    new_keys = path_keys | {"kind", "turn_id", "generation"}
    proof_keys = new_keys | {"creation_proof"}
    if not isinstance(v, dict) or set(v) not in (old_keys, path_keys, new_keys, proof_keys): raise ValueError("serialized record has unknown or missing fields")
    d = v
    if not isinstance(d["cwd"], str) or not Path(d["cwd"]).is_absolute() or not isinstance(d["attachable"], bool) or not isinstance(d["observed_at"], (int, float)) or not isinstance(d["ancestry"], list) or not all(isinstance(x, str) for x in d["ancestry"]): raise ValueError("invalid serialized session")
    if d["parent_session_id"] is not None and not isinstance(d["parent_session_id"], str): raise ValueError("invalid parent session ID")
    if d["title"] is not None and not isinstance(d["title"], str): raise ValueError("invalid session title")
    kind = d.get("kind", "subagent")
    if kind not in {"subagent", "independent", "standalone"}: raise ValueError("invalid session kind")
    if any(d.get(k) is not None and (not isinstance(d[k], str) or not d[k]) for k in ("turn_id", "generation")):
        raise ValueError("invalid session turn generation")
    path = _canonical_optional_path(d.get("session_path"))
    proof = creation_proof_from_dict(d["creation_proof"]) if "creation_proof" in d else None
    context = context_from_dict(d["context"])
    if kind == "standalone":
        if proof is None or proof.child_id != context.session_id or proof.parent_id != d["parent_session_id"]:
            raise ValueError("standalone session requires matching creation proof")
    elif proof is not None:
        raise ValueError("creation proof is only valid for standalone sessions")
    return Session(context, d["parent_session_id"], d["title"], Path(d["cwd"]), Lifecycle(d["lifecycle"]), d["attachable"], float(d["observed_at"]), tuple(d["ancestry"]), path, kind, d.get("turn_id"), d.get("generation"), proof)


def creation_proof_to_dict(p: CreationProof) -> dict[str, object]:
    result = {"parent_id": p.parent_id, "turn_id": p.turn_id,
              "item_id": p.item_id, "child_id": p.child_id}
    if p.cwd_sha256 is not None:
        result["cwd_sha256"] = p.cwd_sha256
    return result


def creation_proof_from_dict(v: object) -> CreationProof:
    required = {"parent_id", "turn_id", "item_id", "child_id"}
    if not isinstance(v, dict) or set(v) not in (required, required | {"cwd_sha256"}):
        raise ValueError("invalid creation proof fields")
    return CreationProof(v["parent_id"], v["turn_id"], v["item_id"], v["child_id"], v.get("cwd_sha256"))


def _canonical_optional_path(value: object) -> Path | None:
    if value is None: return None
    if not isinstance(value, str) or not Path(value).is_absolute(): raise ValueError("session path must be absolute")
    return Path(value).resolve(strict=False)


def matches_agent_session_ref(ref: object, session_id: str, session_path: Path | None = None) -> bool:
    """Match Herdr's typed id/path identity without reading the referenced file."""
    if not isinstance(session_id, str) or not session_id: return False
    if not isinstance(ref, dict) or not isinstance(ref.get("kind"), str) or not isinstance(ref.get("value"), str): return False
    if ref["kind"] == "id": return ref["value"] == session_id
    if ref["kind"] == "path" and session_path is not None and session_path.is_absolute():
        try: return Path(ref["value"]).is_absolute() and Path(ref["value"]).resolve(strict=False) == session_path.resolve(strict=False)
        except (OSError, RuntimeError): return False
    return False


def _mapping(value: object, keys: set[str]) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != keys: raise ValueError("serialized record has unknown or missing fields")
    return value
