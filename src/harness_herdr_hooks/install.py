"""Ownership-tracked, serialized per-user harness registrations."""
from __future__ import annotations
import fcntl, hashlib, json, os, shlex, stat, tempfile
import re
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

def _atomic_json(path: Path, data: dict[str,Any], *, mode: int=0o600,
                 expected: bytes|None=None, expected_exists: bool|None=None,
                 expected_identity: tuple[int,int,int,int]|None=None) -> None:
    path.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
    fd,tmp=tempfile.mkstemp(prefix=f".{path.name}.",suffix=".tmp",dir=path.parent)
    try:
        os.fchmod(fd,mode)
        with os.fdopen(fd,"w",encoding="utf-8") as stream:
            json.dump(data,stream,indent=2,sort_keys=True); stream.write("\n"); stream.flush(); os.fsync(stream.fileno())
        try: st=path.lstat(); exists=True
        except FileNotFoundError: st=None; exists=False
        if exists and (not stat.S_ISREG(st.st_mode) or st.st_uid!=os.getuid()):
            raise InstallError(f"{path.name} is not a user-owned regular file")
        identity=(st.st_dev,st.st_ino,st.st_uid,stat.S_IMODE(st.st_mode)) if exists else None
        current=path.read_bytes() if exists else None
        if expected_exists is not None and exists!=expected_exists:
            raise InstallError(f"{path.name} changed during managed update")
        if expected is not None and current!=expected:
            raise InstallError(f"{path.name} changed during managed update")
        if expected_identity is not None and identity!=expected_identity:
            raise InstallError(f"{path.name} object changed during managed update")
        os.replace(tmp,path)
    finally:
        try: os.unlink(tmp)
        except FileNotFoundError: pass

def _write_manifest(root:Path,data:dict[str,Any])->None: _atomic_json(_manifest(root),data,mode=0o600)

def _transaction_path(root: Path) -> Path: return root/".harness-herdr-hooks-transaction.json"

def _safe_owned_file(path: Path) -> tuple[int,int,int,int] | None:
    try: st=path.lstat()
    except FileNotFoundError: return None
    if not stat.S_ISREG(st.st_mode) or st.st_uid!=os.getuid() or stat.S_IMODE(st.st_mode)&0o022:
        raise InstallError(f"unsafe or replaced managed file: {path}")
    return st.st_dev,st.st_ino,st.st_uid,stat.S_IMODE(st.st_mode)

def _write_transaction(root: Path, records: dict[str, Any]) -> None:
    _atomic_json(_transaction_path(root), {"schema":1,"records":records}, mode=0o600)

def _recover_transaction(root: Path) -> None:
    """CAS-recover a crashed Codex publication; preserve any concurrent edit."""
    journal=_transaction_path(root)
    if not journal.exists(): return
    try:
        if journal.is_symlink(): raise InstallError("Codex transaction journal is a symlink")
        st=journal.stat()
        if st.st_uid!=os.getuid() or not stat.S_ISREG(st.st_mode) or st.st_mode&0o077:
            raise InstallError("unsafe Codex transaction journal")
        data=json.loads(journal.read_text(encoding="utf-8"))
        if data.get("schema")!=1 or not isinstance(data.get("records"),dict): raise ValueError
        records=data["records"]
        manifest_record=records.get(str(_manifest(root)),{})
        _safe_owned_file(_manifest(root))
        current_manifest=_manifest(root).read_bytes() if _manifest(root).exists() else None
        current_hash=hashlib.sha256(current_manifest).hexdigest() if current_manifest is not None else None
        # Manifest ownership is the commit point. A crash after its atomic rename
        # commits success and must not roll back files the manifest now owns.
        committed=(manifest_record.get("after_sha256") is not None and manifest_record.get("after_sha256")==current_hash)
        committed=committed or (manifest_record.get("after_absent") is True and current_manifest is None)
        if committed:
            config_record=records.get(str(root/"config.toml"))
            if config_record:
                config=root/"config.toml"
                _safe_owned_file(config)
                config_bytes=config.read_bytes() if config.exists() else None
                config_hash=hashlib.sha256(config_bytes).hexdigest() if config_bytes is not None else None
                if config_hash!=config_record.get("after_sha256"):
                    raise InstallError("committed Codex install has a concurrent config change; preserving it")
                (root/".harness-herdr-hooks-path-journal.json").unlink(missing_ok=True)
            journal.unlink(); return
        for name,record in records.items():
            target=Path(name); identity=_safe_owned_file(target); current=target.read_bytes() if identity is not None else None
            digest=hashlib.sha256(current).hexdigest() if current is not None else None
            before=record.get("before")
            before_bytes=bytes.fromhex(before) if before is not None else None
            before_hash=hashlib.sha256(before_bytes).hexdigest() if before_bytes is not None else None
            before_exists=record.get("before_exists",before is not None)
            if (current is not None)==before_exists and digest == before_hash: continue
            after_matches=(record.get("after_absent") is True and current is None) or digest==record.get("after_sha256")
            if not after_matches:
                raise InstallError(f"interrupted Codex install conflicts with concurrent change at {target}; preserving it")
            if not before_exists:
                if target.is_symlink(): raise InstallError(f"interrupted Codex install conflicts with replacement at {target}; preserving it")
                target.unlink(missing_ok=True)
            else:
                target.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
                # Recheck immediately before replacement so a symlink or new object
                # installed after the content comparison is preserved.
                if _safe_owned_file(target)!=identity:
                    raise InstallError(f"interrupted Codex install conflicts with replacement at {target}; preserving it")
                tmp=target.with_name(".recover-"+target.name)
                tmp.write_bytes(before_bytes); os.chmod(tmp,int(record["mode"])); os.replace(tmp,target)
        config_record=records.get(str(root/"config.toml"))
        if config_record:
            config=root/"config.toml"
            config_bytes=config.read_bytes() if config.exists() else None
            config_hash=hashlib.sha256(config_bytes).hexdigest() if config_bytes is not None else None
            if config_hash==config_record.get("before_sha256"):
                (root/".harness-herdr-hooks-path-journal.json").unlink(missing_ok=True)
        journal.unlink()
    except InstallError: raise
    except (OSError,ValueError,KeyError,TypeError,json.JSONDecodeError) as exc:
        raise InstallError("Codex transaction journal is malformed or unrecoverable") from exc

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

def _codex_install(root:Path,source_root:Path,manifest:dict[str,Any],manifest_pre:bytes|None)->dict[str,str]:
    from .codex_config import (_check_file, _parse, _path_value, _edit, _find_native,
        install_path, commit_path_journal, recover_path_journal,
                               _check_root)
    source=source_root/"bin/harness-herdr-hooks"
    if not source.is_file(): raise InstallError(f"entrypoint is missing: {source}")
    path=root/"hooks.json"; hooks_identity=_safe_owned_file(path); hooks_pre=path.read_bytes() if hooks_identity is not None else None
    data,mode,existed=_read_hooks(path); entry=manifest["entries"].get("codex")
    if (path.read_bytes() if path.exists() else None)!=hooks_pre:
        raise InstallError("Codex hooks.json changed during preflight")
    adapter_dir=root/"harness-herdr-hooks"/"codex-adapter"
    shim_source=source_root/"integrations/codex/codex"
    if not shim_source.is_file(): raise InstallError(f"Codex adapter source missing: {shim_source}")
    shim=adapter_dir/"codex"; metadata=adapter_dir/"adapter.json"
    # Validate the complete installation before creating/chmodding a profile path
    # or publishing its PATH value. Existing directory metadata is never changed.
    _check_root(root)
    for directory in (adapter_dir.parent, adapter_dir):
        if directory.is_symlink(): raise InstallError(f"Codex adapter directory is a symlink: {directory}")
        try: dst=directory.lstat()
        except FileNotFoundError: continue
        if not stat.S_ISDIR(dst.st_mode) or dst.st_uid!=os.getuid() or stat.S_IMODE(dst.st_mode)&0o022:
            raise InstallError(f"Codex adapter directory is not private and user-owned: {directory}")
    old_shim=old_meta=None
    for target in (shim, metadata):
        if target.is_symlink(): raise InstallError("Codex adapter file is a symlink")
        if target.exists() and (not target.is_file() or target.stat().st_uid != os.getuid()):
            raise InstallError("Codex adapter file is not a user-owned regular file")
    old_shim=shim.read_bytes() if shim.exists() else None
    old_meta=metadata.read_bytes() if metadata.exists() else None
    if not entry and (old_shim is not None or old_meta is not None):
        raise InstallError("unmanaged Codex adapter path already exists; preserving it")
    if entry:
        for target,key in ((shim,"adapter_sha256"),(metadata,"metadata_sha256")):
            expected=entry.get(key)
            if expected and (not target.is_file() or hashlib.sha256(target.read_bytes()).hexdigest()!=expected):
                raise InstallError("managed Codex adapter changed; preserving profile")
    old_path=entry.get("path") if entry else None
    # Validate hooks in memory. This catches every handler conflict before the
    # adapter directory or profile config can be changed.
    handlers={}
    command=shlex.quote(str(source))+" codex-hook"
    handler={"type":"command","command":command,"timeout":5,"async":True}
    for event in ("SessionStart","SubagentStart","SubagentStop"):
        groups=_groups(data,event); owned=(entry or {}).get("handlers",{}).get(event)
        if entry:
            matches=_handler_locations(groups,owned) if isinstance(owned,dict) else []
            if len(matches)>1 or (event in entry.get("handlers",{}) and len(matches)!=1):
                raise InstallError(f"managed Codex registration changed or is ambiguous for {event}; preserving it")
            if matches:
                gi,hi=matches[0]; groups[gi]["hooks"].pop(hi)
                if not groups[gi]["hooks"] and set(groups[gi])=={"hooks"}: groups.pop(gi)
        if any(_group_has_command(g,command) for g in groups): raise InstallError(f"unmanaged Codex handler conflicts for {event}")
        groups.append({"hooks":[handler]}); handlers[event]=handler
    hooks_after=(json.dumps(data,indent=2,sort_keys=True)+"\n").encode()
    # Preflight the native config and PATH calculation without publishing it.
    try:
        _check_root(root)
        config_path=root/"config.toml"; config_raw,config_mode,config_existed=_check_file(config_path)
        config_data=_parse(config_raw); current_path=_path_value(config_data)
        if old_path:
            if old_path.get("config_root")!=str(root) or old_path.get("adapter_dir")!=str(adapter_dir):
                raise InstallError("managed PATH ownership belongs to another profile")
            if current_path!=old_path.get("installed_path"):
                raise InstallError("managed Codex PATH changed; preserving configuration")
            original_path=old_path.get("original_path")
        else: original_path=current_path
        tail=original_path if original_path is not None else os.environ.get("PATH","")
        if not isinstance(tail,str) or "\n" in tail or "\r" in tail: raise InstallError("original PATH is invalid")
        installed_path=str(adapter_dir)+(os.pathsep+tail if tail else "")
        _find_native(tail,os.environ.get("PATH"))
        _edit(config_raw,installed_path)
    except InstallError: raise
    except Exception as exc: raise InstallError(f"managed Codex PATH setup failed: {exc}") from exc
    hooks_mode=stat.S_IMODE(path.stat().st_mode) if path.exists() else mode
    manifest_path=_manifest(root)
    manifest_mode=stat.S_IMODE(manifest_path.stat().st_mode) if manifest_path.exists() else 0o600
    # No conflict remains: only now create the adapter path. Preserve existing
    # parent and adapter directory ownership and modes exactly.
    adapter_dir.parent.mkdir(mode=0o700,parents=False,exist_ok=True)
    adapter_dir.mkdir(mode=0o700,exist_ok=True)
    meta={"schema":1,"source_root":str(source_root.resolve()),
          "native_executable":_find_native(tail,os.environ.get("PATH")),"config_root":str(root)}
    # Snapshot adapter state after the validated directory creation.
    shim_mode=stat.S_IMODE(shim.stat().st_mode) if shim.exists() else 0o700
    meta_mode=stat.S_IMODE(metadata.stat().st_mode) if metadata.exists() else 0o600
    published={}
    transaction={}
    for target,pre,old_mode in ((path,hooks_pre,hooks_mode),(manifest_path,manifest_pre,manifest_mode),
                                (shim,old_shim,shim_mode),(metadata,old_meta,meta_mode),
                                (config_path,config_raw,config_mode)):
        transaction[str(target)]={"before":pre.hex() if pre is not None else None,"before_exists":pre is not None,"mode":old_mode}
    transaction[str(config_path)]["before_sha256"]=hashlib.sha256(config_raw).hexdigest()
    transaction[str(config_path)]["before_exists"]=config_existed
    transaction[str(config_path)]["after_sha256"]=hashlib.sha256(_edit(config_raw,installed_path)).hexdigest()
    transaction[str(shim)]["after_sha256"]=hashlib.sha256(shim_source.read_bytes()).hexdigest()
    transaction[str(metadata)]["after_sha256"]=hashlib.sha256(json.dumps(meta,sort_keys=True,separators=(",",":")).encode()).hexdigest()
    _write_transaction(root,transaction)
    try:
        try:
            path_ownership=install_path(root,adapter_dir,env_path=os.environ.get("PATH"),
                                        ownership=old_path,retain_journal=True)
        except Exception as exc:
            raise InstallError(f"managed Codex PATH setup failed: {exc}") from exc
        shim_tmp=shim.with_name(".codex-stage"); meta_tmp=metadata.with_name(".adapter-stage")
        shim_tmp.write_bytes(shim_source.read_bytes()); os.chmod(shim_tmp,0o700)
        meta_tmp.write_text(json.dumps(meta,sort_keys=True,separators=(",",":")),encoding="utf-8"); os.chmod(meta_tmp,0o600)
        # Parse every staged metadata/config artifact before publishing.
        json.loads(meta_tmp.read_text(encoding="utf-8"))
        os.replace(shim_tmp,shim); os.replace(meta_tmp,metadata)
        published[shim]=hashlib.sha256(shim.read_bytes()).hexdigest()
        published[metadata]=hashlib.sha256(metadata.read_bytes()).hexdigest()
        transaction[str(shim)]["after_sha256"]=published[shim]
        transaction[str(metadata)]["after_sha256"]=published[metadata]
        _write_transaction(root,transaction)
        transaction[str(path)]["after_sha256"]=hashlib.sha256(hooks_after).hexdigest()
        _write_transaction(root,transaction)
        _atomic_json(path,data,mode=mode,expected=hooks_pre,expected_exists=existed,expected_identity=hooks_identity)
        published[path]=hashlib.sha256(path.read_bytes()).hexdigest()
        manifest["entries"]["codex"]={"source":str(source),"source_root":str(source_root),"destination":str(path),"command":command,
            "handlers":handlers,"adapter_dir":str(adapter_dir),"adapter_sha256":hashlib.sha256(shim.read_bytes()).hexdigest(),
            "metadata_sha256":hashlib.sha256(metadata.read_bytes()).hexdigest(),"path":path_ownership,
            "trust":"unknown","backend_qualification":"unknown","observer":"unknown","attachment":"unknown"}
        manifest_after=(json.dumps(manifest,indent=2,sort_keys=True)+"\n").encode()
        transaction[str(manifest_path)]["after_sha256"]=hashlib.sha256(manifest_after).hexdigest()
        _write_transaction(root,transaction)
        _atomic_json(manifest_path,manifest,mode=0o600,expected=manifest_pre,expected_exists=manifest_pre is not None)
        published[manifest_path]=hashlib.sha256(manifest_path.read_bytes()).hexdigest()
        commit_path_journal(root)
        _transaction_path(root).unlink(missing_ok=True)
    except BaseException:
        manifest_record=transaction.get(str(manifest_path),{})
        current_manifest=manifest_path.read_bytes() if manifest_path.exists() else None
        if (manifest_record.get("after_sha256") is not None and current_manifest is not None
                and hashlib.sha256(current_manifest).hexdigest()==manifest_record["after_sha256"]):
            # The durable manifest is the commit point. Leave both journals for
            # next-run recognition if cleanup itself was interrupted.
            raise
        staged=((path,hooks_pre,hooks_mode),(manifest_path,manifest_pre,manifest_mode),
                (shim,old_shim,shim_mode),(metadata,old_meta,meta_mode))
        for target,pre,old_mode in staged:
            try: current=target.read_bytes() if target.exists() else None
            except OSError: continue
            current_hash=hashlib.sha256(current).hexdigest() if current is not None else None
            prior_hash=hashlib.sha256(pre).hexdigest() if pre is not None else None
            if current_hash in {prior_hash,published.get(target)}:
                if pre is None: target.unlink(missing_ok=True)
                else:
                    tmp=target.with_name(".restore-"+target.name); tmp.write_bytes(pre); os.chmod(tmp,old_mode); os.replace(tmp,target)
        recover_path_journal(root)
        raise
    return {"harness":"codex","config_root":str(root),"hooks":str(path),"adapter":str(shim),"action":"linked"}

def _group_has_command(group:Any,command:str)->bool:
    return isinstance(group,dict) and isinstance(group.get("hooks"),list) and any(isinstance(h,dict) and h.get("type")=="command" and h.get("command")==command for h in group["hooks"])

def _handler_locations(groups:list[Any],handler:dict[str,Any])->list[tuple[int,int]]:
    return [(gi,hi) for gi,g in enumerate(groups) if isinstance(g,dict) and isinstance(g.get("hooks"),list)
            for hi,h in enumerate(g["hooks"]) if h==handler]

def install(harness:str,*,source_root:Path,config_dir:str|None=None)->dict[str,str]:
    source_root=source_root.resolve(); root=_root(config_dir,harness)
    with _locked(root):
        if harness=="codex":
            # Recover our interrupted publication before trusting the ownership
            # manifest that recovery may have committed or restored.
            _recover_transaction(root)
        manifest_path=_manifest(root)
        manifest_pre=manifest_path.read_bytes() if manifest_path.exists() else None
        manifest=_read_manifest(manifest_path)
        if (manifest_path.read_bytes() if manifest_path.exists() else None)!=manifest_pre:
            raise InstallError("managed manifest changed during preflight")
        if harness=="codex":
            source=source_root/"bin/harness-herdr-hooks"
            if not source.is_file(): raise InstallError(f"entrypoint is missing: {source}")
            return _codex_install(root,source_root,manifest,manifest_pre)
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
            adapter=Path(entry.get("adapter_dir","")); shim=adapter/"codex"; meta=adapter/"adapter.json"
            try:
                adapter_good=(hashlib.sha256(shim.read_bytes()).hexdigest()==entry.get("adapter_sha256")
                              and hashlib.sha256(meta.read_bytes()).hexdigest()==entry.get("metadata_sha256"))
            except OSError: adapter_good=False
            path_state="unknown"
            try:
                from .codex_config import _parse, _path_value
                current=(root/"config.toml").read_bytes()
                path_state="configured" if _path_value(_parse(current))==entry.get("path",{}).get("installed_path") else "changed"
            except Exception: path_state="unknown"
        result={"harness":harness,"config_root":str(root),"status":"installed" if good and source.is_file() else "moved-or-changed-source","source":str(source)}
        if harness=="codex": result.update(adapter="configured" if adapter_good else "changed-or-missing",path=path_state,
                                             trust=entry.get("trust","unknown"),backend_qualification=entry.get("backend_qualification","unknown"),
                                             observer=entry.get("observer","unknown"),attachment=entry.get("attachment","unknown"))
        return result

def uninstall(harness:str,*,config_dir:str|None=None)->dict[str,str]:
    root=_root(config_dir,harness)
    with _locked(root):
        if harness=="codex": _recover_transaction(root)
        manifest=_read_manifest(_manifest(root)); entry=manifest["entries"].get(harness)
        if not entry:return {"harness":harness,"config_root":str(root),"action":"not-installed"}
        if harness=="opencode":
            dest=root/"plugins/harness-herdr-hooks.js"
            if str(dest)!=entry.get("destination") or not dest.is_symlink() or str(dest.resolve())!=entry.get("source"):
                raise InstallError("managed OpenCode link changed; preserving path")
            dest.unlink()
        elif harness=="codex":
            path=root/"hooks.json"; data,mode,existed=_read_hooks(path)
            hooks_identity=_safe_owned_file(path); hooks_pre=path.read_bytes() if existed else None
            # Validate every owned entry before changing any event.
            for event,owned in entry.get("handlers",{}).items():
                if len(_handler_locations(_groups(data,event),owned))!=1: raise InstallError(f"managed Codex handler changed or ambiguous for {event}; preserving configuration")
            adapter=Path(entry["adapter_dir"]) if entry.get("adapter_dir") else None
            config_path=root/"config.toml"; config_pre=None; config_mode=0o600; config_after=None; config_identity=None
            if adapter:
                shim=adapter/"codex"; metadata=adapter/"adapter.json"
                if (shim.is_symlink() or metadata.is_symlink() or not shim.is_file() or not metadata.is_file()
                        or hashlib.sha256(shim.read_bytes()).hexdigest()!=entry.get("adapter_sha256")
                        or hashlib.sha256(metadata.read_bytes()).hexdigest()!=entry.get("metadata_sha256")):
                    raise InstallError("managed Codex adapter changed; preserving profile")
                if entry.get("path"):
                    from .codex_config import _check_file, _identity, _parse, _path_value, _edit
                    try:
                        config_pre,config_mode,config_exists=_check_file(config_path)
                        if not config_exists: raise InstallError("managed Codex config is unavailable; preserving profile")
                        config_identity=_identity(config_path)
                        current_path=_path_value(_parse(config_pre))
                    except Exception as exc: raise InstallError("managed Codex config is unavailable or invalid; preserving profile") from exc
                    if current_path!=entry["path"].get("installed_path"):
                        raise InstallError("managed Codex PATH changed; preserving profile")
                    original=entry["path"].get("original_path")
                    if original is None:
                        lines=config_pre.splitlines(keepends=True); active=False; out=[]
                        for line in lines:
                            stripped=line.strip()
                            if stripped.startswith(b"["): active=(stripped==b"[shell_environment_policy.set]"); out.append(line); continue
                            if active and re.match(rb"^\s*(?:PATH|\"PATH\"|'PATH')\s*=",line): continue
                            out.append(line)
                        config_after=b"".join(out)
                    else: config_after=_edit(config_pre,original)
            # Build a complete rollback journal before the first profile or adapter write.
            manifest_path=_manifest(root); manifest_identity=_safe_owned_file(manifest_path); manifest_pre=manifest_path.read_bytes()
            hooks_after=None
            for event,owned in entry["handlers"].items():
                groups=_groups(data,event); gi,hi=_handler_locations(groups,owned)[0]; groups[gi]["hooks"].pop(hi)
                if not groups[gi]["hooks"] and set(groups[gi])=={"hooks"}:groups.pop(gi)
                if not groups:data["hooks"].pop(event,None)
            hooks_after=(json.dumps(data,indent=2,sort_keys=True)+"\n").encode() if existed else None
            del manifest["entries"][harness]
            manifest_after=(json.dumps(manifest,indent=2,sort_keys=True)+"\n").encode() if manifest["entries"] else None
            records={}
            def add_record(target:Path,before:bytes|None,old_mode:int,after:bytes|None,*,absent=False,before_exists:bool|None=None):
                rec={"before":before.hex() if before is not None else None,"before_exists":before is not None if before_exists is None else before_exists,"mode":old_mode}
                rec["after_sha256"]=hashlib.sha256(after).hexdigest() if after is not None else None
                if absent: rec["after_absent"]=True
                records[str(target)]=rec
            add_record(path,hooks_pre,mode,hooks_after)
            if config_pre is not None: add_record(config_path,config_pre,config_mode,config_after)
            if adapter:
                adapter_pre={}
                for target in (adapter/"codex",adapter/"adapter.json"):
                    before=target.read_bytes(); adapter_pre[target]=before
                    add_record(target,before,stat.S_IMODE(target.stat().st_mode),None)
            add_record(manifest_path,manifest_pre,stat.S_IMODE(manifest_path.stat().st_mode),manifest_after,absent=manifest_after is None)
            _write_transaction(root,records)
            try:
                if hooks_after is not None:
                    _atomic_json(path,data,mode=mode,expected=hooks_pre,expected_exists=existed,expected_identity=hooks_identity)
                else:
                    if path.exists() or path.is_symlink(): raise InstallError("Codex hooks changed during uninstall")
                    path.unlink(missing_ok=True)
                if config_pre is not None:
                    from .codex_config import _atomic
                    _atomic(config_path,config_after,config_mode,expected=config_pre,expected_exists=True,expected_identity=config_identity)
                if adapter:
                    for target,before in adapter_pre.items():
                        if target.read_bytes()!=before: raise InstallError(f"managed Codex adapter changed during uninstall; preserving profile")
                        target.unlink()
                    try: adapter.rmdir()
                    except OSError: pass
                if manifest_after is not None:
                    _atomic_json(manifest_path,manifest,mode=0o600,expected=manifest_pre,expected_exists=True,expected_identity=manifest_identity)
                else:
                    if manifest_path.read_bytes()!=manifest_pre: raise InstallError("managed manifest changed during uninstall")
                    manifest_path.unlink()
                _transaction_path(root).unlink(missing_ok=True)
            except BaseException:
                # Roll back this failed call when possible; retain the journal if
                # an external edit prevents a safe compare-and-swap recovery.
                _recover_transaction(root)
                raise
            return {"harness":harness,"config_root":str(root),"action":"unlinked"}
        else: raise InstallError("unsupported harness")
        del manifest["entries"][harness]
        if manifest["entries"]:_write_manifest(root,manifest)
        else:_manifest(root).unlink(missing_ok=True)
        return {"harness":harness,"config_root":str(root),"action":"unlinked"}
