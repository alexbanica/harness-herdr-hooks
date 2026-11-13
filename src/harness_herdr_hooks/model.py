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
    return {"context": context_to_dict(p.context), "herdr_server_id": p.herdr_server_id,
            "workspace_id": p.workspace_id, "tab_id": p.tab_id, "pane_id": p.pane_id,
            "ancestry": list(p.ancestry),
            "session_path": str(p.session_path.resolve(strict=False)) if p.session_path else None}


def parent_from_dict(v: object) -> ParentBinding:
    old_keys = {"context", "herdr_server_id", "workspace_id", "tab_id", "pane_id", "ancestry"}
    new_keys = old_keys | {"session_path"}
    if not isinstance(v, dict) or set(v) not in (old_keys, new_keys): raise ValueError("serialized record has unknown or missing fields")
    d = v
    if any(not isinstance(d[k], str) or not d[k] for k in ("herdr_server_id", "workspace_id", "tab_id", "pane_id")) or not isinstance(d["ancestry"], list) or not all(isinstance(x, str) for x in d["ancestry"]): raise ValueError("invalid serialized parent")
    path = _canonical_optional_path(d.get("session_path"))
    return ParentBinding(context_from_dict(d["context"]), d["herdr_server_id"], d["workspace_id"], d["tab_id"], d["pane_id"], tuple(d["ancestry"]), path)


def session_to_dict(s: Session) -> dict[str, object]:
    return {"context": context_to_dict(s.context), "parent_session_id": s.parent_session_id,
            "title": s.title, "cwd": str(s.cwd), "lifecycle": s.lifecycle.value,
            "attachable": s.attachable, "observed_at": s.observed_at, "ancestry": list(s.ancestry),
            "session_path": str(s.session_path.resolve(strict=False)) if s.session_path else None}


def session_from_dict(v: object) -> Session:
    old_keys = {"context", "parent_session_id", "title", "cwd", "lifecycle", "attachable", "observed_at", "ancestry"}
    new_keys = old_keys | {"session_path"}
    if not isinstance(v, dict) or set(v) not in (old_keys, new_keys): raise ValueError("serialized record has unknown or missing fields")
    d = v
    if not isinstance(d["cwd"], str) or not Path(d["cwd"]).is_absolute() or not isinstance(d["attachable"], bool) or not isinstance(d["observed_at"], (int, float)) or not isinstance(d["ancestry"], list) or not all(isinstance(x, str) for x in d["ancestry"]): raise ValueError("invalid serialized session")
    if d["parent_session_id"] is not None and not isinstance(d["parent_session_id"], str): raise ValueError("invalid parent session ID")
    if d["title"] is not None and not isinstance(d["title"], str): raise ValueError("invalid session title")
    path = _canonical_optional_path(d.get("session_path"))
    return Session(context_from_dict(d["context"]), d["parent_session_id"], d["title"], Path(d["cwd"]), Lifecycle(d["lifecycle"]), d["attachable"], float(d["observed_at"]), tuple(d["ancestry"]), path)


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
