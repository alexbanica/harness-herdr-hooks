"""Managed Codex command adapter and private, idempotent launch payloads.

The profile-owned ``codex`` shim delegates here. Routing is injected by the
integration bootstrap so this module never guesses Herdr or backend identity.
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
import secrets
import stat
import sys
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol, Sequence


class LaunchError(RuntimeError):
    """A launch could not be proven safe or acknowledged."""


_TOOL_COMMANDS = {"exec", "resume", "fork", "apply", "review", "login", "logout",
                  "mcp", "completion", "debug", "features", "update", "cloud", "app-server"}
_PAYLOAD_TTL = 120


def _state_root(environ: Mapping[str, str]) -> Path:
    """Match the CLI's override order without importing the CLI module."""
    value = environ.get("HARNESS_HERDR_STATE_ROOT") or environ.get("XDG_STATE_HOME") or str(Path.home() / ".local/state")
    root = Path(value).expanduser()
    if not root.is_absolute():
        raise LaunchError("launch state root must be absolute")
    return root.resolve()


def _schedule_expiry(root: Path, request_id: str, scheduler: Callable[..., Any] | None = None) -> None:
    """Arrange bounded cleanup even if the routing parent exits unexpectedly."""
    if scheduler is not None:
        scheduler(root, request_id, _PAYLOAD_TTL)
        return
    code = (
        "import sys,time; from pathlib import Path; "
        "from harness_herdr_hooks.launch import LaunchStore; "
        "s=LaunchStore(Path(sys.argv[1])); rid=sys.argv[2]; end=time.monotonic()+int(sys.argv[3]); "
        "p=s.root/'payloads'/f'{rid}.json'; "
        "exec('while time.monotonic()<end and p.exists():\\n time.sleep(min(1,max(0,end-time.monotonic())))'); "
        "s.expire(rid)"
    )
    env = {"PATH": os.environ.get("PATH", ""), "PYTHONPATH": os.pathsep.join(sys.path)}
    actions = ((os.POSIX_SPAWN_OPEN, 0, os.devnull, os.O_RDONLY, 0),
               (os.POSIX_SPAWN_OPEN, 1, os.devnull, os.O_WRONLY, 0),
               (os.POSIX_SPAWN_OPEN, 2, os.devnull, os.O_WRONLY, 0))
    os.posix_spawn(sys.executable, [sys.executable, "-c", code, str(root), request_id,
                                    str(_PAYLOAD_TTL)], env, file_actions=actions, setsid=True)


def classify_command(argv: Sequence[str], *, display: bool = False,
                     herdr: bool = False, absolute_exec: bool = False) -> str:
    """Return ``native`` or ``interactive`` without interpreting prompt text."""
    args = list(argv)
    if absolute_exec or display or not herdr:
        return "native"
    # Parse only leading native options and their declared values. Once the
    # prompt boundary or first positional word is reached, never inspect it.
    takes_value = {"-c", "--config", "-p", "--profile", "-m", "--model", "-C", "--cd",
                   "-s", "--sandbox", "-a", "--ask-for-approval", "--remote",
                   "--remote-auth-token-env", "--local-provider", "--image", "--add-dir"}
    i = 0
    while i < len(args):
        token = args[i]
        if token == "--":
            return "interactive"
        if token in {"--help", "-h", "--version", "-V", "--no-daemon"}:
            return "native"
        if token.startswith("--") and "=" in token:
            name = token.split("=", 1)[0]
            if name in {"--help", "--version", "--no-daemon"}:
                return "native"
            i += 1
            continue
        if token in takes_value:
            i += 2
            continue
        if token.startswith("-"):
            i += 1
            continue
        return "native" if token in _TOOL_COMMANDS else "interactive"
    return "interactive"


def _private_directory(path: Path) -> None:
    if path.is_symlink():
        raise LaunchError("launch state directory is a symlink")
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    st = path.stat()
    if not stat.S_ISDIR(st.st_mode) or st.st_uid != os.getuid() or stat.S_IMODE(st.st_mode) & 0o077:
        raise LaunchError("launch state directory is not private and user-owned")


class LaunchStore:
    """Owner-only atomic payload store; metadata never contains prompt text."""
    def __init__(self, root: Path):
        if not root.is_absolute():
            raise ValueError("launch state root must be absolute")
        self.root = root

    def _prepare(self) -> None:
        _private_directory(self.root)
        _private_directory(self.root / "payloads")
        _private_directory(self.root / "records")

    @contextmanager
    def _locked(self, request_id: str):
        self._prepare()
        lock_path = self.root / "records" / f"{request_id}.lock"
        fd = os.open(lock_path, os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0), 0o600)
        try:
            st = os.fstat(fd)
            if st.st_uid != os.getuid() or not stat.S_ISREG(st.st_mode) or stat.S_IMODE(st.st_mode) & 0o077:
                raise LaunchError("unsafe launch request lock")
            fcntl.flock(fd, fcntl.LOCK_EX)
            yield
        finally:
            try:
                fcntl.flock(fd, fcntl.LOCK_UN)
            finally:
                os.close(fd)

    def _remove_payload(self, request_id: str) -> None:
        try:
            (self.root / "payloads" / f"{request_id}.json").unlink()
        except FileNotFoundError:
            pass

    def terminate(self, request_id: str, status: str) -> None:
        """Remove prompt text and retain an opaque terminal record, under claim lock."""
        if status not in {"failed", "expired"} or not self._valid_id(request_id):
            raise LaunchError("invalid terminal launch state")
        with self._locked(request_id):
            record_path = self.root / "records" / f"{request_id}.json"
            try:
                record = self._read_private(record_path)
            except FileNotFoundError:
                self._remove_payload(request_id)
                return
            if record.get("request_id") == request_id and record.get("status") not in {"acknowledged", "failed", "expired"}:
                record["status"] = status
                self._atomic(record_path, record)
            self._remove_payload(request_id)

    def expire(self, request_id: str) -> None:
        self.terminate(request_id, "expired")

    @staticmethod
    def _valid_id(value: str) -> bool:
        return bool(value) and all(c in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_" for c in value)

    def create(self, argv: Sequence[str], *, native_executable: Path,
               cwd: Path, profile: str) -> str:
        if len(argv) > 256 or not native_executable.is_absolute() or not cwd.is_absolute() or not profile:
            raise ValueError("launch argv, native executable, cwd, and profile are invalid")
        if any(not isinstance(x, str) or "\0" in x or len(x.encode("utf-8", "surrogateescape")) > 65536 for x in argv):
            raise ValueError("launch arguments exceed safe bounds")
        self._prepare()
        request_id = secrets.token_urlsafe(18).replace("=", "")
        payload = {"schema": 1, "argv": list(argv), "native_executable": str(native_executable),
                   "cwd": str(cwd), "profile": profile}
        encoded = json.dumps(payload, separators=(",", ":")).encode("utf-8", "surrogateescape")
        if len(encoded) > 1024 * 1024:
            raise ValueError("launch payload exceeds 1 MiB")
        self._atomic(self.root / "payloads" / f"{request_id}.json", payload)
        # Record only opaque identity and state. Never persist prompt/argv here.
        self._atomic(self.root / "records" / f"{request_id}.json",
                     {"schema": 1, "request_id": request_id, "status": "prepared",
                      "created_at": int(time.time())})
        return request_id

    def claim(self, request_id: str) -> dict[str, Any]:
        if not self._valid_id(request_id):
            raise LaunchError("invalid launch request ID")
        self._prepare()
        with self._locked(request_id):
            record_path = self.root / "records" / f"{request_id}.json"
            payload_path = self.root / "payloads" / f"{request_id}.json"
            record = self._read_private(record_path)
            if record.get("status") != "prepared" or record.get("request_id") != request_id:
                raise LaunchError("launch request was already claimed or acknowledged")
            if not isinstance(record.get("created_at"), int) or time.time() - record["created_at"] > 120:
                record["status"] = "expired"
                self._atomic(record_path, record)
                self._remove_payload(request_id)
                raise LaunchError("launch request expired")
            payload = self._read_private(payload_path)
            if payload.get("schema") != 1 or not isinstance(payload.get("argv"), list):
                raise LaunchError("launch payload is malformed")
            record["status"] = "claimed"
            self._atomic(record_path, record)
            return payload

    def acknowledge(self, request_id: str) -> None:
        if not self._valid_id(request_id):
            raise LaunchError("invalid launch request ID")
        with self._locked(request_id):
            path = self.root / "records" / f"{request_id}.json"
            record = self._read_private(path)
            if record.get("request_id") != request_id:
                raise LaunchError("launch acknowledgement does not match request")
            if record.get("status") in {"expired", "failed"}:
                self._remove_payload(request_id)
                return
            if record.get("status") != "claimed":
                raise LaunchError("launch acknowledgement does not match a claimed request")
            record["status"] = "acknowledged"
            self._atomic(path, record)
            self._remove_payload(request_id)

    @staticmethod
    def _read_private(path: Path) -> dict[str, Any]:
        st = path.lstat()
        if (not stat.S_ISREG(st.st_mode) or st.st_uid != os.getuid()
                or stat.S_IMODE(st.st_mode) & 0o077 or st.st_size > 1024 * 1024):
            raise LaunchError("launch state file is not private, bounded, and user-owned")
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise LaunchError("launch state record is malformed")
        return value

    @staticmethod
    def _atomic(path: Path, value: Mapping[str, Any]) -> None:
        fd, tmp = tempfile.mkstemp(prefix=".launch-", dir=path.parent)
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(value, stream, sort_keys=True, separators=(",", ":"))
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(tmp, path)
        finally:
            try:
                os.unlink(tmp)
            except FileNotFoundError:
                pass


class LaunchRouter(Protocol):
    def verify_parent(self, thread_id: str, profile: str, cwd: Path) -> bool: ...
    def split_and_launch(self, request_id: str, payload_path: Path, cwd: Path) -> bool: ...
    def wait_for_ack(self, request_id: str, timeout: float) -> bool: ...


def route_interactive(argv: Sequence[str], *, native_executable: Path,
                      config_root: Path, cwd: Path, state_root: Path,
                      environ: Mapping[str, str], router: LaunchRouter,
                      timeout: float = 5.0,
                      expiry_scheduler: Callable[..., Any] | None = None) -> str:
    """Route once after parent proof; uncertain launch outcomes are never retried."""
    if environ.get("HERDR_ENV") != "1" or environ.get("HARNESS_HERDR_DISPLAY") == "1":
        return "native"
    thread_id = environ.get("CODEX_THREAD_ID")
    if not thread_id or not router.verify_parent(thread_id, str(config_root), cwd):
        raise LaunchError("requesting Codex parent pane/backend could not be verified")
    store = LaunchStore(state_root / "harness-herdr-hooks" / "launches")
    request_id = store.create(argv, native_executable=native_executable,
                              cwd=cwd, profile=str(config_root))
    payload_path = store.root / "payloads" / f"{request_id}.json"
    try:
        _schedule_expiry(store.root, request_id, expiry_scheduler)
    except Exception:
        store.terminate(request_id, "failed")
        raise
    # A failed/uncertain RPC is terminal for this request. Never retry a launch.
    try:
        if not router.split_and_launch(request_id, payload_path, cwd):
            store.terminate(request_id, "failed")
            raise LaunchError("launch request was not acknowledged by Herdr")
        if not router.wait_for_ack(request_id, min(max(timeout, 0.1), 5.0)):
            store.terminate(request_id, "failed")
            raise LaunchError("launch acknowledgement timed out; request will not be retried")
    except LaunchError:
        raise
    except Exception:
        store.terminate(request_id, "failed")
        raise
    return request_id



def run_claimed_launch(request_id: str, *, store: LaunchStore,
                       verify_destination: Callable[[str, Path, str], Mapping[str, str] | None],
                       environ: Mapping[str, str], popen: Callable[..., Any] | None = None,
                       wait: bool = True) -> int:
    """Start one claimed session in its verified destination and retain the shell."""
    import subprocess
    payload_path = store.root / "payloads" / f"{request_id}.json"
    # Read only enough metadata to verify where this request belongs before the
    # prompt-bearing payload becomes visible to the pane helper.
    claimed_once = False
    try:
        record = store._read_private(store.root / "records" / f"{request_id}.json")
        if record.get("status") != "prepared":
            raise LaunchError("launch request is already claimed")
        payload = store._read_private(payload_path)
        cwd = Path(payload.get("cwd", ""))
        profile = payload.get("profile")
        if not cwd.is_absolute() or not isinstance(profile, str):
            raise LaunchError("launch destination metadata is invalid")
        child_markers = verify_destination(request_id, cwd, profile)
        if not isinstance(child_markers, Mapping):
            raise LaunchError("launch destination could not be verified")
        claimed = store.claim(request_id)
        claimed_once = True
        native = Path(claimed["native_executable"])
        if not native.is_absolute() or not native.is_file() or not os.access(native, os.X_OK):
            raise LaunchError("native Codex executable is unavailable")
    except Exception:
        store.terminate(request_id, "failed")
        raise
    child_env = {k: v for k, v in environ.items()
                 if k in {"HOME", "PATH", "LANG", "LC_ALL", "LC_CTYPE", "TERM", "COLORTERM", "TMPDIR", "XDG_RUNTIME_DIR", "SSH_AUTH_SOCK"}
                 or k.startswith("HERDR_")}
    # The native client starts from the destination pane's environment, so
    # carry the exact state root selected by this verified launch store.
    # Preserve XDG_STATE_HOME independently for native client behavior; the
    # explicit HARNESS override keeps nested integration work on this store.
    state_root = store.root.parent.parent.resolve()
    child_env["HARNESS_HERDR_STATE_ROOT"] = str(state_root)
    if "XDG_STATE_HOME" in environ:
        child_env["XDG_STATE_HOME"] = environ["XDG_STATE_HOME"]
    child_env["CODEX_HOME"] = profile
    child_env.pop("CODEX_THREAD_ID", None)
    child_env.pop("HARNESS_HERDR_DISPLAY", None)
    child_env.update({k: v for k, v in child_markers.items() if k.startswith("HERDR_")})
    spawn = popen or subprocess.Popen
    try:
        proc = spawn([str(native), *claimed["argv"]], cwd=str(cwd), env=child_env,
                     stdin=None, stdout=None, stderr=None, close_fds=True)
    except OSError as exc:
        store.terminate(request_id, "failed")
        raise LaunchError("native Codex launch failed after request claim") from exc
    store.acknowledge(request_id)
    return int(proc.wait()) if wait else 0


def _metadata(shim_path: Path) -> dict[str, Any]:
    path = shim_path.with_name("adapter.json")
    data = LaunchStore._read_private(path)
    required = {"schema", "source_root", "native_executable", "config_root"}
    if set(data) != required or data.get("schema") != 1:
        raise LaunchError("Codex adapter metadata is missing or unsupported")
    for key in ("source_root", "native_executable", "config_root"):
        if not isinstance(data[key], str) or not Path(data[key]).is_absolute():
            raise LaunchError("Codex adapter metadata path is invalid")
    return data


def main(argv: Sequence[str] | None = None, *, shim_path: Path | None = None,
         environ: Mapping[str, str] | None = None,
         router_factory: Callable[[Mapping[str, Any]], LaunchRouter] | None = None,
         execv: Callable[..., Any] = os.execv) -> int:
    """Managed shim entry point with verified Herdr routing by default."""
    args = list(sys.argv[1:] if argv is None else argv)
    env = os.environ if environ is None else environ
    path = (shim_path or Path(sys.argv[0])).resolve(strict=True)
    meta = _metadata(path)
    source = Path(meta["source_root"]).resolve(strict=True)
    native = Path(meta["native_executable"]).resolve(strict=True)
    config_root = Path(meta["config_root"]).resolve(strict=True)
    if not native.is_file() or not os.access(native, os.X_OK):
        raise LaunchError("recorded native Codex executable is unavailable")
    mode = classify_command(args, display=env.get("HARNESS_HERDR_DISPLAY") == "1",
                            herdr=env.get("HERDR_ENV") == "1",
                            absolute_exec=False)
    if mode == "interactive":
        if router_factory is None and env.get("HERDR_ENV") == "1" and env.get("HARNESS_HERDR_DISPLAY") != "1":
            from .cli import _launch_router_factory
            router_factory = _launch_router_factory
        if router_factory is None and env.get("HERDR_ENV") == "1" and env.get("HARNESS_HERDR_DISPLAY") != "1":
            raise LaunchError("verified Herdr launch routing is unavailable")
        if router_factory is None:
            execv(str(native), [str(native), *args])
            return 0
        router = router_factory(meta)
        result = route_interactive(args, native_executable=native, config_root=config_root,
                                   cwd=Path.cwd(), state_root=_state_root(env),
                                   environ=env, router=router)
        if result != "native":
            return 0
    sys.path.insert(0, str(source / "src"))
    execv(str(native), [str(native), *args])
    return 0
