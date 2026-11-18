"""Ownership-tracked, serialized per-user harness registrations."""
from __future__ import annotations
import fcntl, json, os, shlex, stat, tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

class InstallError(RuntimeError): pass

def _root(override: str | None, harness: str) -> Path:
    if override: return Path(override).expanduser().resolve()
    if harness == "codex": return Path(os.environ.get("CODEX_HOME", "~/.codex")).expanduser().resolve()
    if os.environ.get("OPENCODE_CONFIG_DIR"): return Path(os.environ["OPENCODE_CONFIG_DIR"]).expanduser().resolve()
    xdg=os.environ.get("XDG_CONFIG_HOME")
    return (Path(xdg).expanduser() if xdg else Path.home()/".config").resolve()/"opencode"

def _manifest(root: Path) -> Path: return root/".harness-herdr-hooks.json"

@contextmanager
def _locked(root: Path, *, create: bool = True) -> Iterator[None]:
    if create:
        root.mkdir(mode=0o700,parents=True,exist_ok=True)
    lock=root/".harness-herdr-hooks.lock"
    try:
        fd=os.open(lock,(os.O_CREAT|os.O_RDWR if create else os.O_RDONLY)|getattr(os,"O_NOFOLLOW",0),0o600)
    except FileNotFoundError:
        if create:
            raise
        yield
        return
    try:
        st=os.fstat(fd)
        if st.st_uid!=os.getuid() or not stat.S_ISREG(st.st_mode): raise InstallError("unsafe installer lock")
        if create:
            os.fchmod(fd,0o600)
        fcntl.flock(fd,fcntl.LOCK_EX if create else fcntl.LOCK_SH); yield
    finally:
        fcntl.flock(fd,fcntl.LOCK_UN); os.close(fd)

def _read_manifest(path: Path) -> dict[str,Any]:
    try:
        if path.is_symlink(): raise InstallError("managed manifest is a symlink")
        st=path.stat()
        if st.st_uid!=os.getuid() or not stat.S_ISREG(st.st_mode) or st.st_mode&0o077: raise InstallError("managed manifest is not private and user-owned")
        data=json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError: return {"schema":1,"entries":{}}
    except (OSError,json.JSONDecodeError) as exc: raise InstallError(f"cannot read managed manifest: {exc}") from exc
    if not isinstance(data,dict) or data.get("schema")!=1 or not isinstance(data.get("entries"),dict): raise InstallError("unsupported or malformed managed manifest")
    return data

def _atomic_json(path: Path, data: dict[str,Any], *, mode: int=0o600) -> None:
    path.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
    fd,tmp=tempfile.mkstemp(prefix=f".{path.name}.",suffix=".tmp",dir=path.parent)
    try:
        os.fchmod(fd,mode)
        with os.fdopen(fd,"w",encoding="utf-8") as stream:
            json.dump(data,stream,indent=2,sort_keys=True); stream.write("\n"); stream.flush(); os.fsync(stream.fileno())
        os.replace(tmp,path)
    finally:
        try: os.unlink(tmp)
        except FileNotFoundError: pass

def _write_manifest(root:Path,data:dict[str,Any])->None: _atomic_json(_manifest(root),data,mode=0o600)

def _read_hooks(path:Path)->tuple[dict[str,Any],int,bool]:
    try:
        if path.is_symlink(): raise InstallError("Codex hooks.json symlink is not managed")
        st=path.stat(); mode=stat.S_IMODE(st.st_mode)
        if st.st_uid!=os.getuid() or not stat.S_ISREG(st.st_mode): raise InstallError("Codex hooks.json is not a user-owned regular file")
        value=json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value,dict) or not isinstance(value.get("hooks",{}),dict): raise InstallError("Codex hooks.json must contain a hooks object")
        value.setdefault("hooks",{}); return value,mode,True
    except FileNotFoundError: return {"hooks":{}},0o600,False
    except (OSError,json.JSONDecodeError) as exc: raise InstallError(f"cannot read Codex hooks.json: {exc}") from exc

def _groups(data:dict[str,Any],event:str)->list[Any]:
    value=data["hooks"].setdefault(event,[])
    if not isinstance(value,list): raise InstallError(f"unsupported existing Codex hook structure for {event}")
    return value

def _owned_group_matches(groups:list[Any],owned:dict[str,Any])->list[int]: return [i for i,g in enumerate(groups) if g==owned]

def _codex_install(root:Path,source:Path,manifest:dict[str,Any])->dict[str,str]:
    path=root/"hooks.json"; data,mode,existed=_read_hooks(path); entry=manifest["entries"].get("codex")
    command=shlex.quote(str(source))+" codex-hook"
    handler={"type":"command","command":command,"timeout":5,"async":True}
    for event in ("SessionStart","SubagentStart"):
        groups=_groups(data,event); owned=(entry or {}).get("handlers",{}).get(event)
        if entry:
            matches=_handler_locations(groups,owned) if isinstance(owned,dict) else []
            if len(matches)!=1: raise InstallError(f"managed Codex registration changed or is ambiguous for {event}; preserving it")
            gi,hi=matches[0]; groups[gi]["hooks"].pop(hi)
            if not groups[gi]["hooks"] and set(groups[gi])=={"hooks"}:groups.pop(gi)
        # Refuse an identical unmanaged command; only manifest provenance grants ownership.
        if any(_group_has_command(g,command) for g in groups): raise InstallError(f"unmanaged Codex handler conflicts for {event}")
        groups.append({"hooks":[handler]})
    _atomic_json(path,data,mode=mode)
    manifest["entries"]["codex"]={"source":str(source),"destination":str(path),"command":command,"handlers":{"SessionStart":handler,"SubagentStart":handler}}
    _write_manifest(root,manifest)
    return {"harness":"codex","config_root":str(root),"hooks":str(path),"action":"linked"}

def _group_has_command(group:Any,command:str)->bool:
    return isinstance(group,dict) and isinstance(group.get("hooks"),list) and any(isinstance(h,dict) and h.get("type")=="command" and h.get("command")==command for h in group["hooks"])

def _handler_locations(groups:list[Any],handler:dict[str,Any])->list[tuple[int,int]]:
    return [(gi,hi) for gi,g in enumerate(groups) if isinstance(g,dict) and isinstance(g.get("hooks"),list)
            for hi,h in enumerate(g["hooks"]) if h==handler]

def install(harness:str,*,source_root:Path,config_dir:str|None=None)->dict[str,str]:
    source_root=source_root.resolve(); root=_root(config_dir,harness)
    with _locked(root):
        manifest=_read_manifest(_manifest(root))
        if harness=="codex":
            source=source_root/"bin/harness-herdr-hooks"
            if not source.is_file(): raise InstallError(f"entrypoint is missing: {source}")
            return _codex_install(root,source,manifest)
        if harness!="opencode": raise InstallError("unsupported harness")
        source=source_root/"integrations/opencode/plugin.js"
        if not source.is_file(): raise InstallError(f"plugin source is missing: {source}")
        destination=root/"plugins/harness-herdr-hooks.js"; old=manifest["entries"].get("opencode")
        destination.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
        if destination.is_symlink():
            current=str(destination.resolve())
            if old is None: raise InstallError(f"unmanaged plugin symlink conflict: {destination}")
            if current!=old.get("source") or str(destination)!=old.get("destination"): raise InstallError(f"managed plugin changed; preserving: {destination}")
            if current!=str(source):
                tmp=destination.with_name(f".{destination.name}.{os.getpid()}.tmp")
                if tmp.exists() or tmp.is_symlink(): raise InstallError("temporary plugin link path already exists")
                tmp.symlink_to(source); os.replace(tmp,destination)
        elif destination.exists(): raise InstallError(f"unmanaged plugin path conflict: {destination}")
        else: destination.symlink_to(source)
        manifest["entries"]["opencode"]={"source":str(source),"destination":str(destination)}; _write_manifest(root,manifest)
        return {"harness":harness,"config_root":str(root),"plugin":str(destination),"source":str(source),"action":"linked" if not old or old.get("source")!=str(source) else "already-linked"}

def status(harness:str,*,config_dir:str|None=None)->dict[str,str]:
    root=_root(config_dir,harness)
    with _locked(root,create=False):
        manifest=_read_manifest(_manifest(root)); entry=manifest["entries"].get(harness)
        if not entry:return {"harness":harness,"config_root":str(root),"status":"not-installed"}
        source=Path(entry.get("source",""))
        if harness=="opencode":
            dest=root/"plugins/harness-herdr-hooks.js"; good=dest.is_symlink() and str(dest.resolve())==str(source) and source.is_file()
        else:
            data,_,_=_read_hooks(root/"hooks.json"); good=True
            for event,handler in entry.get("handlers",{}).items():
                if len(_handler_locations(_groups(data,event),handler))!=1: good=False
        return {"harness":harness,"config_root":str(root),"status":"installed" if good and source.is_file() else "moved-or-changed-source","source":str(source)}

def uninstall(harness:str,*,config_dir:str|None=None)->dict[str,str]:
    root=_root(config_dir,harness)
    with _locked(root):
        manifest=_read_manifest(_manifest(root)); entry=manifest["entries"].get(harness)
        if not entry:return {"harness":harness,"config_root":str(root),"action":"not-installed"}
        if harness=="opencode":
            dest=root/"plugins/harness-herdr-hooks.js"
            if str(dest)!=entry.get("destination") or not dest.is_symlink() or str(dest.resolve())!=entry.get("source"):
                raise InstallError("managed OpenCode link changed; preserving path")
            dest.unlink()
        elif harness=="codex":
            path=root/"hooks.json"; data,mode,existed=_read_hooks(path)
            # Validate every owned entry before changing any event.
            for event,owned in entry.get("handlers",{}).items():
                if len(_handler_locations(_groups(data,event),owned))!=1: raise InstallError(f"managed Codex handler changed or ambiguous for {event}; preserving configuration")
            for event,owned in entry["handlers"].items():
                groups=_groups(data,event); gi,hi=_handler_locations(groups,owned)[0]; groups[gi]["hooks"].pop(hi)
                if not groups[gi]["hooks"] and set(groups[gi])=={"hooks"}:groups.pop(gi)
                if not groups:data["hooks"].pop(event,None)
            if existed:_atomic_json(path,data,mode=mode)
            else:path.unlink(missing_ok=True)
        else: raise InstallError("unsupported harness")
        del manifest["entries"][harness]
        if manifest["entries"]:_write_manifest(root,manifest)
        else:_manifest(root).unlink(missing_ok=True)
        return {"harness":harness,"config_root":str(root),"action":"unlinked"}
