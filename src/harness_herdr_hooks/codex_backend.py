"""Proofs for selecting and revalidating a native Codex app-server endpoint.

This module deliberately treats Herdr process metadata as an identity hint. It
pins the Linux process start time and executable, and pins both the advertised
socket alias and its protected physical socket target.
"""
from __future__ import annotations

import os
import shlex
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
from urllib.parse import urlsplit


class BackendProofError(ValueError):
    """Endpoint or process evidence is missing, unsafe, or has changed."""


@dataclass(frozen=True, slots=True)
class SocketPin:
    alias: Path
    target: Path
    alias_identity: tuple[int, int, int, int, int]
    socket_identity: tuple[int, int, int, int, int]
    directory_identity: tuple[int, int, int, int, int]

    @property
    def instance(self) -> str:
        dev, ino, uid, _mode, _kind = self.socket_identity
        return f"{dev}:{ino}:{uid}"

    def revalidate(self, *, uid: int | None = None, lstat: Callable[[Path], os.stat_result] = Path.lstat,
                   stat_fn: Callable[[Path], os.stat_result] = Path.stat,
                   resolve: Callable[..., Path] = Path.resolve) -> None:
        current = inspect_endpoint(self.alias, uid=uid, lstat=lstat, stat_fn=stat_fn, resolve=resolve)
        if current != self:
            raise BackendProofError("Codex socket alias or endpoint incarnation changed")


def _identity(info: os.stat_result) -> tuple[int, int, int, int, int]:
    return info.st_dev, info.st_ino, info.st_uid, stat.S_IMODE(info.st_mode), stat.S_IFMT(info.st_mode)


def _socket_path(value: str | Path) -> Path:
    raw = str(value)
    if raw == "unix://":
        return Path()
    if raw.startswith("unix://"):
        parsed = urlsplit(raw)
        if parsed.scheme != "unix" or parsed.netloc not in ("", "localhost") or not parsed.path:
            raise BackendProofError("invalid explicit Codex Unix endpoint")
        raw = parsed.path
    path = Path(raw).expanduser()
    if not path.is_absolute():
        raise BackendProofError("Codex endpoint must be an absolute Unix socket path")
    return path


def default_socket_alias(config_home: Path) -> Path:
    """Return the only socket alias permitted for the selected Codex profile."""
    home = Path(config_home).expanduser()
    if not home.is_absolute():
        raise BackendProofError("selected CODEX_HOME must be absolute")
    return home / "app-server-control" / "app-server-control.sock"


def inspect_endpoint(alias: str | Path, *, uid: int | None = None,
                     lstat: Callable[[Path], os.stat_result] = Path.lstat,
                     stat_fn: Callable[[Path], os.stat_result] = Path.stat,
                     resolve: Callable[..., Path] = Path.resolve) -> SocketPin:
    """Validate advertised alias, target socket, and private containing directory."""
    owner = os.getuid() if uid is None else uid
    alias_path = _socket_path(alias)
    try:
        alias_info = lstat(alias_path)
        target_path = resolve(alias_path, strict=True)
        socket_info = stat_fn(target_path)
        directory = target_path.parent
        dir_info = stat_fn(directory)
    except (OSError, RuntimeError) as exc:
        raise BackendProofError("Codex app-server endpoint cannot be resolved") from exc
    if not stat.S_ISSOCK(socket_info.st_mode):
        raise BackendProofError("Codex endpoint target is not a Unix socket")
    if socket_info.st_uid != owner or stat.S_IMODE(socket_info.st_mode) & 0o077:
        raise BackendProofError("Codex socket ownership or permissions are unsafe")
    if (not stat.S_ISDIR(dir_info.st_mode) or dir_info.st_uid != owner
            or stat.S_IMODE(dir_info.st_mode) & 0o077):
        raise BackendProofError("Codex socket directory is not private and user-owned")
    if (alias_info.st_uid != owner or (not stat.S_ISLNK(alias_info.st_mode)
            and stat.S_IMODE(alias_info.st_mode) & 0o022)):
        raise BackendProofError("Codex advertised socket alias is not safely owned")
    return SocketPin(alias_path, target_path, _identity(alias_info),
                     _identity(socket_info), _identity(dir_info))


def select_endpoint(config_home: Path, explicit_endpoint: str | Path | None = None,
                    *, uid: int | None = None,
                    lstat: Callable[[Path], os.stat_result] = Path.lstat,
                    stat_fn: Callable[[Path], os.stat_result] = Path.stat,
                    resolve: Callable[..., Path] = Path.resolve) -> SocketPin:
    """Explicit native selection wins; otherwise inspect only CODEX_HOME alias."""
    selected = (_socket_path(explicit_endpoint) if explicit_endpoint else default_socket_alias(config_home))
    if not selected.is_absolute():
        selected = default_socket_alias(config_home)
    return inspect_endpoint(selected, uid=uid, lstat=lstat, stat_fn=stat_fn, resolve=resolve)


@dataclass(frozen=True, slots=True)
class ProcessProof:
    pid: int
    uid: int
    name: str
    executable: Path
    cwd: Path
    start_ticks: int
    argv: tuple[str, ...] | None

    @property
    def launch_mode(self) -> str:
        """Return default, explicit, no_daemon, or unknown from observed argv."""
        if self.argv is None:
            return "unknown"
        args = self.argv[1:]
        if "--no-daemon" in args:
            return "no_daemon"
        if any(arg == "--remote" or arg.startswith("--remote=") for arg in args):
            return "explicit"
        # `resume --remote ...` is also explicit; --remote covered above.
        return "default"


def inspect_process(pid: int, *, expected_name: str, expected_cwd: Path | None = None,
                    proc_root: Path = Path("/proc"), uid: int | None = None,
                    read_bytes: Callable[[Path], bytes] | None = None,
                    resolve: Callable[..., Path] = Path.resolve) -> ProcessProof:
    """Read bounded Linux /proc identity; Herdr argv is never required.

    `expected_name` and `expected_cwd` come from the already verified Herdr pane
    binding. Kernel start ticks are retained to detect PID reuse at revalidation.
    """
    owner = os.getuid() if uid is None else uid
    if not isinstance(pid, int) or pid <= 0 or not expected_name:
        raise BackendProofError("invalid Herdr process identity")
    root = Path(proc_root) / str(pid)
    read = read_bytes or (lambda p: p.read_bytes())
    try:
        status_raw = read(root / "status")
        stat_raw = read(root / "stat")
        try:
            cmdline_raw = read(root / "cmdline")
        except OSError:
            cmdline_raw = None
        if len(status_raw) > 65536 or len(stat_raw) > 65536 or (cmdline_raw is not None and len(cmdline_raw) > 65536):
            raise BackendProofError("Codex process metadata exceeds its size limit")
        status = status_raw.decode("ascii", "strict")
        uid_line = next(line for line in status.splitlines() if line.startswith("Uid:"))
        real_uid = int(uid_line.split()[1])
        stat_text = stat_raw.decode("ascii", "strict")
        # comm is parenthesized and may itself contain spaces or ')'.
        close = stat_text.rfind(")")
        fields = stat_text[close + 2:].split()
        start_ticks = int(fields[19])  # field 22, after pid and comm
        exe = resolve(root / "exe", strict=True)
        cwd = resolve(root / "cwd", strict=True)
        argv = (tuple(part.decode("utf-8", "surrogateescape") for part in cmdline_raw.split(b"\0") if part)
                if cmdline_raw is not None else None) or None
    except (OSError, ValueError, StopIteration, IndexError, UnicodeError, RuntimeError) as exc:
        raise BackendProofError("Codex foreground process identity is unavailable") from exc
    expected = Path(expected_name).name.lower()
    executable_name = exe.name.lower()
    if real_uid != owner:
        raise BackendProofError("Codex foreground process belongs to another user")
    if expected not in {"codex", "codex-cli"} or "codex" not in executable_name:
        raise BackendProofError("Herdr foreground process is not the expected Codex executable")
    if expected_cwd is not None and cwd != resolve(Path(expected_cwd), strict=True):
        raise BackendProofError("Codex foreground process working directory changed")
    # If argv is readable it can strengthen identity, but missing argv does not
    # invalidate the independent Herdr PID/name/cwd and kernel process proof.
    if argv and "codex" not in Path(argv[0]).name.lower():
        raise BackendProofError("Codex process argv does not match its executable")
    return ProcessProof(pid, real_uid, expected, exe, cwd, start_ticks, argv)


def verify_process_pin(pin: ProcessProof, *, proc_root: Path = Path("/proc"),
                       uid: int | None = None) -> ProcessProof:
    """Re-read a process and reject PID reuse or changed executable/cwd."""
    current = inspect_process(pin.pid, expected_name=pin.name, expected_cwd=pin.cwd,
                              proc_root=proc_root, uid=uid)
    if (current.start_ticks, current.executable, current.uid) != (pin.start_ticks, pin.executable, pin.uid):
        raise BackendProofError("Codex foreground process identity changed")
    return current


__all__ = ["BackendProofError", "ProcessProof", "SocketPin", "default_socket_alias",
           "inspect_endpoint", "inspect_process", "select_endpoint", "verify_process_pin"]
