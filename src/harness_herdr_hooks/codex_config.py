"""Owned, byte-preserving Codex shell PATH configuration edits."""
from __future__ import annotations
import hashlib, json, os, re, shutil, stat, tempfile, tomllib
from pathlib import Path
from typing import Any

class ConfigError(RuntimeError): pass

_TABLE = b"[shell_environment_policy.set]"
_KEY = b"PATH"

def _check_root(root: Path) -> None:
    if root.is_symlink(): raise ConfigError("Codex profile directory is a symlink")
    try: st=root.stat()
    except OSError as exc: raise ConfigError("Codex profile directory is unavailable") from exc
    if not stat.S_ISDIR(st.st_mode) or st.st_uid!=os.getuid() or stat.S_IMODE(st.st_mode)&0o022:
        raise ConfigError("Codex profile directory is not user-controlled")

def _check_file(path: Path) -> tuple[bytes, int, bool]:
    if path.is_symlink(): raise ConfigError("Codex config symlink is not managed")
    try:
        st=path.lstat()
        if not stat.S_ISREG(st.st_mode) or st.st_uid!=os.getuid(): raise ConfigError("Codex config is not a user-owned regular file")
        if stat.S_IMODE(st.st_mode)&0o022: raise ConfigError("Codex config is writable by another user")
        raw=path.read_bytes()
        return raw,stat.S_IMODE(st.st_mode),True
    except FileNotFoundError: return b"",0o600,False

def _identity(path: Path) -> tuple[int, int, int, int] | None:
    try: st=path.lstat()
    except FileNotFoundError: return None
    if not stat.S_ISREG(st.st_mode) or st.st_uid!=os.getuid():
        raise ConfigError("Codex config is not a user-owned regular file")
    if stat.S_IMODE(st.st_mode)&0o022:
        raise ConfigError("Codex config is writable by another user")
    return st.st_dev,st.st_ino,st.st_uid,stat.S_IMODE(st.st_mode)

def _parse(raw: bytes) -> dict[str, Any]:
    try: return tomllib.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError,tomllib.TOMLDecodeError) as e: raise ConfigError("Codex config TOML is invalid") from e

def _path_value(data: dict[str,Any]) -> str|None:
    policy=data.get("shell_environment_policy")
    if policy is None: return None
    if not isinstance(policy,dict): raise ConfigError("shell_environment_policy has unsupported shape")
    setting=policy.get("set")
    if setting is None: return None
    if not isinstance(setting,dict): raise ConfigError("shell_environment_policy.set has unsupported shape")
    value=setting.get("PATH")
    if value is not None and not isinstance(value,str): raise ConfigError("shell_environment_policy.set.PATH must be a string")
    return value

def _quote(value: str) -> bytes:
    return json.dumps(value,ensure_ascii=False).encode("utf-8")

def _comment_at(line: bytes, start: int=0) -> int:
    quote=None; escaped=False
    for i,ch in enumerate(line[start:],start):
        if escaped: escaped=False; continue
        if ch==92 and quote==34: escaped=True; continue
        if quote is not None:
            if ch==quote: quote=None
        elif ch in (34,39): quote=ch
        elif ch==35: return i
    return -1

def _edit(raw: bytes, installed: str) -> bytes:
    data=_parse(raw); current=_path_value(data)
    policy=data.get("shell_environment_policy",{})
    semantic_table=isinstance(policy,dict) and isinstance(policy.get("set"),dict)
    lines=raw.splitlines(keepends=True)
    table_spans=[]; active=False; key_lines=[]; has_table=False
    for i,line in enumerate(lines):
        stripped=line.strip()
        if stripped.startswith(b"["):
            if stripped==_TABLE: active=True; has_table=True; table_spans.append(i)
            else: active=False
            continue
        if active:
            # Match exactly PATH, allowing quoted keys and indentation.
            if re.match(rb"^\s*(?:PATH|\"PATH\"|'PATH')\s*=",line): key_lines.append(i)
    if len(table_spans)>1 or len(key_lines)>1: raise ConfigError("duplicate PATH table or key")
    if current is not None and not key_lines: raise ConfigError("PATH is defined through an unsupported TOML layout")
    if semantic_table and not has_table: raise ConfigError("PATH table uses an unsupported TOML spelling")
    if key_lines:
        i=key_lines[0]; line=lines[i]
        eq=line.find(b"="); comment=_comment_at(line,eq+1)
        newline=line[len(line.rstrip(b"\r\n")):]
        end=comment if comment>=0 else len(line)-len(newline)
        suffix=line[end:len(line)-len(newline) if newline else len(line)]
        lines[i]=line[:eq+1]+b" "+_quote(installed)+(b" "+suffix.lstrip() if suffix else b"")+newline
        return b"".join(lines)
    if has_table:
        table_index=table_spans[0]
        next_header=next((i for i in range(table_index+1,len(lines)) if lines[i].lstrip().startswith(b"[")),len(lines))
        insert=b"PATH = "+_quote(installed)+b"\n"
        lines.insert(next_header,insert)
        return b"".join(lines)
    addition=(_TABLE+b"\nPATH = "+_quote(installed)+b"\n")
    separator=b"" if not raw or raw.endswith((b"\n",b"\r")) else b"\n"
    return raw+separator+(b"\n" if raw else b"")+addition

def _atomic(path:Path,raw:bytes,mode:int,*,expected:bytes|None=None,
            expected_exists:bool|None=None,expected_identity:tuple[int,int,int,int]|None=None)->None:
    path.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
    fd,tmp=tempfile.mkstemp(prefix=".codex-config-",dir=path.parent)
    try:
        os.fchmod(fd,mode)
        with os.fdopen(fd,"wb") as f: f.write(raw); f.flush(); os.fsync(f.fileno())
        # Validate staged TOML and compare-and-swap against concurrent edits.
        _parse(Path(tmp).read_bytes())
        identity=_identity(path)
        exists=identity is not None
        current=path.read_bytes() if exists else b""
        if expected_exists is not None and exists!=expected_exists:
            raise ConfigError("Codex config object changed during managed update")
        if expected is not None and current!=expected: raise ConfigError("Codex config changed during managed update")
        if expected_identity is not None and identity!=expected_identity:
            raise ConfigError("Codex config object changed during managed update")
        os.replace(tmp,path)
        dfd=os.open(path.parent,os.O_RDONLY|getattr(os,"O_DIRECTORY",0))
        try: os.fsync(dfd)
        finally: os.close(dfd)
    finally:
        try: os.unlink(tmp)
        except FileNotFoundError: pass

def _find_native(path_tail: str, fallback_path: str|None=None) -> str:
    found=shutil.which("codex",path=path_tail) or (shutil.which("codex",path=fallback_path) if fallback_path else None)
    if not found: raise ConfigError("native Codex executable cannot be resolved from original PATH")
    native=Path(found).resolve(strict=True)
    if not native.is_file() or not os.access(native,os.X_OK): raise ConfigError("resolved Codex executable is not executable")
    return str(native)

def _write_journal(config_root: Path, data: dict[str,Any]) -> Path:
    journal=config_root/".harness-herdr-hooks-path-journal.json"
    fd,tmp=tempfile.mkstemp(prefix=".path-journal-",dir=config_root)
    try:
        os.fchmod(fd,0o600)
        with os.fdopen(fd,"w",encoding="utf8") as f: json.dump(data,f,separators=(",",":")); f.flush(); os.fsync(f.fileno())
        os.replace(tmp,journal)
    finally:
        try: os.unlink(tmp)
        except FileNotFoundError: pass
    return journal

def recover_path_journal(config_root: Path) -> str:
    """Recover an interrupted write only when current bytes match its staged after-image."""
    _check_root(Path(config_root))
    journal=config_root/".harness-herdr-hooks-path-journal.json"
    if not journal.exists(): return "clean"
    data=None
    try:
        st=journal.lstat()
        if not stat.S_ISREG(st.st_mode) or st.st_uid!=os.getuid() or stat.S_IMODE(st.st_mode)&0o077: raise ConfigError("unsafe Codex path journal")
        data=json.loads(journal.read_text(encoding="utf8"))
        path=Path(config_root)/"config.toml"; identity=_identity(path); current=path.read_bytes() if identity is not None else b""
        current_hash=hashlib.sha256(current).hexdigest()
        if current_hash==data.get("before_sha256"):
            journal.unlink(); return "clean"
        if current_hash!=data.get("after_sha256"): return "conflict-preserved"
        before=bytes.fromhex(data["before_bytes"]); mode=int(data["before_mode"])
        if data.get("before_exists"):
            _atomic(path,before,mode,expected=current,expected_exists=True,expected_identity=identity)
        else:
            if identity is not None:
                if current != bytes.fromhex(data["after_bytes"]): raise ConfigError("Codex config object changed during recovery")
                if _identity(path)!=identity: raise ConfigError("Codex config object changed during recovery")
                path.unlink()
        journal.unlink(); return "recovered"
    except (OSError,ValueError,KeyError,json.JSONDecodeError) as exc: raise ConfigError("Codex path journal is malformed") from exc

def install_path(config_root: Path, adapter_dir: Path, *, env_path: str|None=None,
                 ownership: dict[str,Any]|None=None, retain_journal: bool=False) -> dict[str,Any]:
    """Prepend one concrete adapter path and return exact restoration ownership."""
    config_root=Path(config_root); adapter_dir=Path(adapter_dir)
    if not config_root.is_absolute() or not adapter_dir.is_absolute(): raise ConfigError("Codex config and adapter paths must be absolute")
    _check_root(config_root)
    if recover_path_journal(config_root)=="conflict-preserved": raise ConfigError("unreconciled Codex PATH journal conflict")
    path=config_root/"config.toml"; raw,mode,existed=_check_file(path); identity=_identity(path); parsed=_parse(raw)
    current=_path_value(parsed)
    if ownership:
        if ownership.get("config_root")!=str(config_root) or ownership.get("adapter_dir")!=str(adapter_dir): raise ConfigError("managed PATH ownership belongs to another profile")
        if current==ownership.get("installed_path"):
            original=ownership.get("original_path")
        else: raise ConfigError("managed Codex PATH changed; preserving configuration")
    else: original=current
    tail=original if original is not None else (env_path if env_path is not None else os.environ.get("PATH",""))
    if not isinstance(tail,str) or "\n" in tail or "\r" in tail: raise ConfigError("original PATH is invalid")
    installed=str(adapter_dir)+(os.pathsep+tail if tail else "")
    # Avoid interpreting a literal prior adapter prefix as part of original tail.
    native=_find_native(tail,env_path)
    updated=_edit(raw,installed)
    # Persist a private compare-and-swap preimage before changing Codex config.
    journal_data={"schema":1,"before_sha256":hashlib.sha256(raw).hexdigest(),"before_exists":existed,"after_exists":True,"before_mode":mode,"before_bytes":raw.hex(),"after_bytes":updated.hex(),"after_sha256":hashlib.sha256(updated).hexdigest(),
                  "before_exists":existed,"before_mode":mode,"before_bytes":raw.hex(),"after_bytes":updated.hex()}
    journal=_write_journal(config_root,journal_data)
    try: _atomic(path,updated,mode,expected=raw,expected_exists=existed,expected_identity=identity)
    except BaseException:
        journal.unlink(missing_ok=True); raise
    if not retain_journal: journal.unlink(missing_ok=True)
    return {"config_root":str(config_root),"config_path":str(path),"adapter_dir":str(adapter_dir),
            "original_path":original,"installed_path":installed,"native_executable":native,
            "config_existed":existed,"original_mode":mode,"before_sha256":hashlib.sha256(raw).hexdigest(),
            "installed_sha256":hashlib.sha256(updated).hexdigest()}

def restore_path(ownership: dict[str,Any]) -> str:
    """Restore only the exact still-owned PATH value; preserve changed files."""
    root=Path(ownership["config_root"]); path=Path(ownership["config_path"])
    _check_root(root)
    if path!=root/"config.toml": raise ConfigError("managed Codex config path mismatch")
    raw,mode,exists=_check_file(path); current=_path_value(_parse(raw))
    if current!=ownership.get("installed_path"): raise ConfigError("managed Codex PATH changed; preserving configuration")
    original=ownership.get("original_path")
    if original is None:
        # Remove only PATH assignment, preserving every other byte and table content.
        lines=raw.splitlines(keepends=True); active=False; out=[]
        for line in lines:
            stripped=line.strip()
            if stripped.startswith(b"["): active=(stripped==_TABLE); out.append(line); continue
            if active and re.match(rb"^\s*(?:PATH|\"PATH\"|'PATH')\s*=",line): continue
            out.append(line)
        restored=b"".join(out)
    else: restored=_edit(raw,original)
    identity=_identity(path)
    if exists: _atomic(path,restored,mode,expected=raw,expected_exists=True,expected_identity=identity)
    elif restored: _atomic(path,restored,0o600)
    return "restored"


def commit_path_journal(config_root: Path) -> None:
    """Finalize managed config edit after caller publishes its ownership manifest."""
    (Path(config_root)/".harness-herdr-hooks-path-journal.json").unlink(missing_ok=True)
