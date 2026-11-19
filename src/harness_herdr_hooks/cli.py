"""Public install commands and bounded, context-scoped runtime entrypoints."""
from __future__ import annotations
import argparse, fcntl, hashlib, json, os, re, shutil, socket, stat, subprocess, sys, time
import shlex
import signal
from dataclasses import replace
from pathlib import Path
from typing import Sequence
from . import install as installer
from .adapters.codex import parse_hook, CodexRuntimeAdapter
from .adapters.opencode import OpenCodeAdapter, OpenCodeRuntimeAdapter
from .attach import exec_binding
from .coordinator import run_observer
from .environment import child_environment
from .herdr import HerdrClient, HerdrError, codex_backend_proof, codex_remote_socket
from .model import Context, Harness, Lifecycle, ParentBinding, Session, parent_from_dict, parent_to_dict, session_to_dict
from .state import StateStore, load_existing_binding, save_binding
from .launch import LaunchStore, run_claimed_launch

_RUNTIME_MAX_AGE=30*24*60*60
_RUNTIME_MAX_BYTES=16384

# This value belongs to the interpreter that imported this module.  A status
# command compares it with the revision published by the long lived observer;
# it never hashes source on disk and attributes that value to another process.
try:
    _PACKAGE_ROOT=Path(__file__).resolve(strict=True).parents[1]
    _revision=hashlib.sha256()
    for _source in sorted(_PACKAGE_ROOT.rglob("*.py")):
        _revision.update(str(_source.relative_to(_PACKAGE_ROOT)).encode()+b"\0")
        _revision.update(_source.read_bytes()+b"\0")
    _LOADED_SOURCE_SHA256=_revision.hexdigest()
except OSError:
    _PACKAGE_ROOT=None; _LOADED_SOURCE_SHA256=None

def _runtime_path(root:Path,profile:str)->Path:
    key=hashlib.sha256(str(Path(profile).resolve()).encode()).hexdigest()
    return root/"harness-herdr-hooks"/"runtime"/(key+".json")

def _runtime_read(path:Path)->dict:
    try:
        if path.parent.is_symlink() or path.parent.parent.is_symlink(): return {}
        if path.is_symlink(): return {}
        st=path.lstat()
        if not stat.S_ISREG(st.st_mode) or st.st_uid!=os.getuid() or stat.S_IMODE(st.st_mode)&0o077 or st.st_size>_RUNTIME_MAX_BYTES:return {}
        data=json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data,dict) or data.get("schema")!=1 or time.time()-float(data.get("updated",0))>_RUNTIME_MAX_AGE:return {}
        return data
    except (OSError,ValueError,TypeError): return {}

def _runtime_write(root:Path,profile:str,mutate)->None:
    """Store only bounded runtime evidence in a private profile namespace."""
    path=_runtime_path(root,profile); directory=path.parent; parent=directory.parent
    for folder in (root,parent,directory):
        if folder.is_symlink(): raise ValueError("unsafe runtime state directory")
        folder.mkdir(mode=0o700,parents=True,exist_ok=True)
        st=folder.stat()
        if st.st_uid!=os.getuid() or not stat.S_ISDIR(st.st_mode): raise ValueError("runtime state directory is not owner controlled")
        if folder!=root: os.chmod(folder,0o700)
    lockfd=os.open(directory/"runtime.lock",os.O_CREAT|os.O_RDWR|getattr(os,"O_NOFOLLOW",0),0o600)
    lockst=os.fstat(lockfd)
    if lockst.st_uid!=os.getuid() or not stat.S_ISREG(lockst.st_mode) or stat.S_IMODE(lockst.st_mode)&0o077:
        os.close(lockfd); raise ValueError("unsafe runtime state lock")
    fcntl.flock(lockfd,fcntl.LOCK_EX)
    try:
        data=_runtime_read(path); data={k:v for k,v in data.items() if k in {"schema","updated","hook","observer"}}
        data.setdefault("schema",1); mutate(data); data["updated"]=time.time()
        raw=json.dumps(data,sort_keys=True,separators=(",",":" )).encode()
        if len(raw)>_RUNTIME_MAX_BYTES: raise ValueError("runtime evidence exceeds bound")
        fd,tmp=__import__("tempfile").mkstemp(prefix=".runtime-",dir=directory)
        try:
            os.fchmod(fd,0o600)
            with os.fdopen(fd,"wb") as f:f.write(raw);f.flush();os.fsync(f.fileno())
            os.replace(tmp,path)
        finally:
            try:os.unlink(tmp)
            except FileNotFoundError:pass
    finally:
        fcntl.flock(lockfd,fcntl.LOCK_UN); os.close(lockfd)

def _record_hook(root:Path,parent:ParentBinding)->None:
    def update(data):
        data["hook"]={"observed":True,"backend":"codex","backend_instance":parent.context.backend_instance,
            "lifecycle_namespace":parent.context.key()[:32],
            "server_id":parent.herdr_server_id,"pane_id":parent.pane_id,"tab_id":parent.tab_id,
            "workspace_id":parent.workspace_id,"at":time.time()}
    _runtime_write(root,str(parent.context.config_root),update)

def _runtime_status(root:Path,profile:str)->dict:
    data=_runtime_read(_runtime_path(root,profile)); hook=data.get("hook",{})
    result={"native_hook_loading":"observed" if hook.get("observed") is True else "unknown",
            "last_verified_binding":"unknown","observer":"unknown",
            "attachment":{"known":False,"observed_counts":{}},
            "cleanup":{"known":False,"outcomes":{}},"ownership":{"known":False,"counts":{}}}
    if hook.get("observed") is True:
        result["last_verified_binding"]={k:hook.get(k) for k in ("backend","backend_instance","server_id","pane_id","tab_id","workspace_id","at")}
    observer=data.get("observer",{})
    if observer:
        pid=observer.get("pid"); pin=observer.get("pin")
        current=_process_pin(pid,expected=pin)
        if observer.get("state")=="ended": result["observer"]="ended"
        elif not current: result["observer"]="unknown" if _process_pin(pid) is None else "stale"
        elif (observer.get("source_sha256")==_LOADED_SOURCE_SHA256
              and observer.get("source_sha256") and observer.get("binding_id")
              and _observer_command_matches(pid, observer)):
            result["observer"]="running"
        else: result["observer"]="stale"
    binding_dir=root/"harness-herdr-hooks"/"bindings"
    counts={}; ownership={}
    try:
        if binding_dir.is_symlink(): raise ValueError("unsafe")
        import itertools
        for p in itertools.islice(binding_dir.glob("*.json"),512):
            if p.is_symlink() or p.stat().st_size>65536:continue
            rec=load_existing_binding(root,p.stem); parent=parent_from_dict(rec["parent"])
            if (str(parent.context.config_root)!=str(Path(profile).resolve()) or parent.context.harness!=Harness.CODEX
                or parent.context.backend_instance!=hook.get("backend_instance")
                or parent.herdr_server_id!=hook.get("server_id") or parent.pane_id!=hook.get("pane_id")):continue
            outcome=rec.get("outcome",{}).get("status")
            if outcome:counts[outcome]=counts.get(outcome,0)+1
            owner=rec.get("ownership","unknown")
            ownership[owner]=ownership.get(owner,0)+1
    except (OSError,ValueError,KeyError,TypeError): pass
    if counts:result["attachment"]={"known":True,"observed_counts":counts}
    if ownership:result["ownership"]={"known":True,"counts":ownership}
    # Lifecycle evidence is read-only here: status must not initialize a
    # missing context store or rewrite its schema during inspection.
    namespace=hook.get("lifecycle_namespace")
    lifecycle_path=root/"harness-herdr-hooks"/namespace/"state.json" if isinstance(namespace,str) and re.fullmatch(r"[a-f0-9]{32}",namespace) else None
    try:
        if lifecycle_path is not None and not lifecycle_path.is_symlink():
            st=lifecycle_path.lstat()
            if (stat.S_ISREG(st.st_mode) and st.st_uid==os.getuid()
                    and stat.S_IMODE(st.st_mode)&0o077==0 and st.st_size<=1_048_576):
                lifecycle=json.loads(lifecycle_path.read_text(encoding="utf-8"))
                if isinstance(lifecycle,dict) and lifecycle.get("schema") in {1,2}:
                    outcomes={}
                    for rec in lifecycle.get("records",{}).values():
                        if not isinstance(rec,dict):continue
                        cleanup=rec.get("cleanup")
                        outcome=cleanup.get("outcome") if isinstance(cleanup,dict) else None
                        if outcome in {"closed","unknown","failed","reused","retained-unverified","manual-close"}:
                            outcomes[outcome]=outcomes.get(outcome,0)+1
                    result["cleanup"]={"known":True,"outcomes":outcomes}
    except (OSError,ValueError,TypeError):pass
    return result

def _publish_observer(root:Path,parent:ParentBinding,state:str,pin:dict|None)->None:
    if not pin:return
    def update(data):
        old=data.get("observer",{})
        if (old.get("pid"),old.get("pin"))!=(os.getpid(),pin):
            # A running record may outlive a crashed observer. Replace it only
            # when its kernel process identity is demonstrably gone; a live but
            # unverifiable owner remains protected as ambiguous.
            if state=="ended":return
            if old.get("state")=="running" and _process_pin(old.get("pid"),expected=old.get("pin")) is not None:return
        data["observer"]={"state":state,"pid":os.getpid(),"pin":pin,
            "server_id":parent.herdr_server_id,"pane_id":parent.pane_id,"at":time.time()}
        data["observer"].update(source_sha256=_LOADED_SOURCE_SHA256,
            source_path=str(_PACKAGE_ROOT), source_root=str(_PACKAGE_ROOT), binding_id=parent.context.key()[:64],
            context_key=parent.context.key())
    _runtime_write(root,str(parent.context.config_root),update)

def _native_codex_executable(config_root:Path)->Path:
    """Use only the adapter selected and owned by this private profile manifest."""
    metadata=config_root/"harness-herdr-hooks"/"codex-adapter"/"adapter.json"
    data=LaunchStore._read_private(metadata)
    if data.get("schema")!=1 or data.get("config_root")!=str(config_root): raise ValueError("selected Codex adapter metadata is invalid")
    from .install import _manifest, _read_manifest
    manifest=_read_manifest(_manifest(config_root))
    entry=manifest.get("entries",{}).get("codex",{})
    shim=metadata.with_name("codex")
    if (entry.get("adapter_dir")!=str(metadata.parent)
            or entry.get("source_root")!=data.get("source_root")
            or entry.get("metadata_sha256")!=hashlib.sha256(metadata.read_bytes()).hexdigest()
            or entry.get("adapter_sha256")!=hashlib.sha256(shim.read_bytes()).hexdigest()):
        raise ValueError("selected Codex adapter is not owned by the profile install manifest")
    path=Path(data.get("native_executable",""))
    if not path.is_absolute() or not path.is_file() or not os.access(path,os.X_OK): raise ValueError("recorded native Codex executable is unavailable")
    return path.resolve(strict=True)

def _launch_router_factory(meta):
    return _HerdrLaunchRouter(meta)

class _HerdrLaunchRouter:
    def __init__(self,meta): self.meta=meta; self.parent=None; self.client=None; self.cwd=None
    def verify_parent(self,thread_id,profile,cwd):
        if profile!=self.meta["config_root"]: return False
        client=_herdr_client(); synthetic={"hook_event_name":"SessionStart","session_id":thread_id,
            "cwd":str(cwd),"transcript_path":None}
        parent,_,parent_cwd,_=_parent_from_event("codex-hook",json.dumps(synthetic).encode(),client)
        if parent.context.config_root.resolve()!=Path(profile).resolve() or parent.context.session_id!=thread_id: return False
        self.parent,self.client,self.cwd=parent,client,parent_cwd
        return True
    def split_and_launch(self,request_id,payload_path,cwd):
        if not self.parent or not self.client or not LaunchStore._valid_id(request_id): return False
        root=_state_root()/"harness-herdr-hooks"/"launches"; store=LaunchStore(root); store._prepare()
        # The intent is durable before the non-idempotent Herdr split RPC. An
        # uncertain outcome is terminal and a repeated caller cannot split again.
        lock_path=root/"records"/f"{request_id}.route.lock"
        fd=os.open(lock_path,os.O_CREAT|os.O_RDWR|getattr(os,"O_NOFOLLOW",0),0o600)
        try:
            st=os.fstat(fd)
            if st.st_uid!=os.getuid() or not stat.S_ISREG(st.st_mode) or stat.S_IMODE(st.st_mode)&0o077: return False
            fcntl.flock(fd,fcntl.LOCK_EX)
            intent=root/"records"/f"{request_id}.route.json"
            if intent.exists(): return False
            markers={"HERDR_ENV":"1","HERDR_SOCKET_PATH":str(self.client.socket_path),
                "HERDR_PANE_ID":self.parent.pane_id,"HERDR_TAB_ID":self.parent.tab_id,
                "HERDR_WORKSPACE_ID":self.parent.workspace_id}
            if any(os.environ.get(k)!=v for k,v in markers.items()): return False
            store._atomic(intent,{"schema":1,"request_id":request_id,"status":"split-intent"})
            if not self.client.verify_parent(self.parent): return False
            source_info=self.client.process_info(self.parent.pane_id)
            source_shell=source_info.get("shell_pid")
            source_pin=_process_pin(source_shell) if isinstance(source_shell,int) else None
            if not source_pin: return False
            pane=self.client.split(self.parent,cwd,env={"HARNESS_HERDR_STATE_ROOT":str(_state_root())})
            from .attach import shell_is_ready
            deadline=time.monotonic()+2.0; info=None; shell_pin=None
            while time.monotonic()<deadline:
                try:
                    info=self.client.process_info(pane)
                    shell=next((proc for proc in info.get("foreground_processes",[])
                                if isinstance(proc,dict) and proc.get("pid")==info.get("shell_pid")),None)
                    if shell and shell.get("cwd")==str(cwd.resolve()) and shell_is_ready(info):
                        shell_pin=_process_pin(info["shell_pid"])
                        if shell_pin: break
                except HerdrError: pass
                time.sleep(.05)
            if not info or not shell_pin: return False
            binding={"schema":1,"request_id":request_id,"server_socket":str(self.client.socket_path),
                "server_identity":self.parent.herdr_server_id,"workspace_id":self.parent.workspace_id,
                "tab_id":self.parent.tab_id,"pane_id":pane,"cwd":str(cwd.resolve()),
                "profile":str(self.parent.context.config_root),"origin_pane":self.parent.pane_id,
                "shell_pid":info["shell_pid"],"shell_pin":shell_pin,"parent":parent_to_dict(self.parent)}
            store._atomic(root/"records"/f"{request_id}.destination.json",binding)
            # Revalidate both bindings immediately before sending the one command.
            if not self.client.verify_parent(self.parent) or not _process_pin(info["shell_pid"],expected=shell_pin): return False
            current=self.client.process_info(pane)
            current_shell=next((proc for proc in current.get("foreground_processes",[])
                                if isinstance(proc,dict) and proc.get("pid")==current.get("shell_pid")),None)
            if (not shell_is_ready(current) or current.get("shell_pid")!=info["shell_pid"]
                    or not current_shell or current_shell.get("cwd")!=str(cwd.resolve())): return False
            current_source=self.client.process_info(self.parent.pane_id)
            if (current_source.get("shell_pid")!=source_shell
                    or not _process_pin(source_shell,expected=source_pin)): return False
            self.client.send_text(pane," "+shlex.quote(str(_entrypoint()))+" launch-run "+shlex.quote(request_id))
            self.client.send_keys(pane,["enter"])
            return True
        finally:
            fcntl.flock(fd,fcntl.LOCK_UN); os.close(fd)
    def wait_for_ack(self,request_id,timeout):
        root=_state_root()/"harness-herdr-hooks"/"launches"; deadline=time.monotonic()+min(timeout,5.0)
        while time.monotonic()<deadline:
            try:
                record=LaunchStore._read_private(root/"records"/f"{request_id}.json")
                if record.get("status")=="acknowledged": return True
            except (OSError,ValueError): return False
            time.sleep(.05)
        return False

def _verify_launch_destination(request_id,cwd,profile):
    root=_state_root()/"harness-herdr-hooks"/"launches"; binding=LaunchStore._read_private(root/"records"/f"{request_id}.destination.json")
    if binding.get("request_id")!=request_id or binding.get("cwd")!=str(cwd.resolve()) or binding.get("profile")!=profile: return None
    client=HerdrClient(binding["server_socket"]); snap=client.snapshot()
    if client.server_identity()!=binding["server_identity"]: return None
    parent=parent_from_dict(binding["parent"])
    if not client.verify_parent(parent): return None
    pane=next((p for p in snap.get("panes",[]) if p.get("pane_id")==binding["pane_id"]),None)
    if not pane or pane.get("workspace_id")!=binding["workspace_id"] or pane.get("tab_id")!=binding["tab_id"] or pane.get("cwd")!=str(cwd): return None
    info=client.process_info(binding["pane_id"]); procs=info.get("foreground_processes",[])
    foreground=[p for p in procs if isinstance(p,dict) and p.get("pid")==os.getpid()]
    if len(procs)!=1 or len(foreground)!=1: return None
    argv=_proc_argv(os.getpid(),expected_cwd=cwd)
    executable=_process_pin(os.getpid())
    try:
        argv_path=(argv[0] if argv and os.path.isabs(argv[0]) else shutil.which(argv[0]) if argv else None)
        argv_executable=str(Path(argv_path).resolve(strict=True)) if argv_path else ""
    except (OSError,RuntimeError):
        return None
    if (not executable or argv_executable!=executable.get("exe")
            or argv[1:]!="-m harness_herdr_hooks launch-run ".split()+[request_id]): return None
    if (info.get("shell_pid")!=binding.get("shell_pid")
            or not _process_pin(info.get("shell_pid"),expected=binding.get("shell_pin"))): return None
    markers={"HERDR_ENV":"1","HERDR_SOCKET_PATH":binding["server_socket"],"HERDR_PANE_ID":binding["pane_id"],"HERDR_TAB_ID":binding["tab_id"],"HERDR_WORKSPACE_ID":binding["workspace_id"]}
    if any(os.environ.get(k)!=v for k,v in markers.items()): return None
    return markers

def _entrypoint()->Path:
    return Path(__file__).resolve().parents[2]/"bin/harness-herdr-hooks"

def _process_pin(pid:int,*,expected:dict|None=None,proc_root:Path=Path("/proc"))->dict|None:
    """Bounded Linux process identity: kernel start time, executable and uid."""
    if not isinstance(pid,int) or pid<=0: return None
    root=proc_root/str(pid)
    try:
        def start():
            raw=(root/"stat").read_bytes()
            if len(raw)>65536: raise ValueError("process stat exceeds bound")
            fields=raw.decode("ascii").rsplit(")",1)[1].split()
            return int(fields[19])
        first=start()
        status=(root/"status").read_bytes()
        if len(status)>65536:return None
        uid=next(x for x in status.decode("ascii").splitlines() if x.startswith("Uid:" )).split()[1]
        exe=str((root/"exe").resolve(strict=True))
        pin={"start_ticks":first,"exe":exe,"uid":int(uid)}
        if start()!=first or int(uid)!=os.getuid() or (expected is not None and pin!=expected): return None
        return pin
    except (OSError,ValueError,StopIteration,IndexError,RuntimeError): return None

def _observer_command_matches(pid:int, observer:dict, *, proc_root:Path=Path("/proc"))->bool:
    """Prove argv still identifies this exact helper and binding."""
    pin=_process_pin(pid,expected=observer.get("pin"),proc_root=proc_root)
    if not pin:return False
    try:
        root=proc_root/str(pid)
        raw=(root/"cmdline").read_bytes()
        if len(raw)>65536:return False
        argv=[x.decode("utf-8","surrogateescape") for x in raw.split(b"\0") if x]
        envraw=(root/"environ").read_bytes()
        if len(envraw)>65536:return False
        env=dict(item.split(b"=",1) for item in envraw.split(b"\0") if b"=" in item)
        rootpath=observer.get("source_root") or observer.get("source_path")
        expected_pythonpath=str(Path(rootpath).resolve())
        interpreter=shutil.which(argv[0]) if argv and not os.path.isabs(argv[0]) else (argv[0] if argv else None)
        interpreter_ok=bool(interpreter and Path(interpreter).resolve(strict=True)==Path(pin["exe"]).resolve(strict=True))
        module_form=(len(argv)==5 and interpreter_ok
                     and argv[1:]==["-m","harness_herdr_hooks","observe",observer["binding_id"]]
                     and env.get(b"PYTHONPATH",b"").decode("utf-8","surrogateescape").split(os.pathsep)[0]==expected_pythonpath)
        script_form=(len(argv)>=3 and Path(argv[0]).resolve()==Path(observer.get("entrypoint", "")).resolve()
                     and argv[-2:]==["observe",observer["binding_id"]])
        return _process_pin(pid,expected=pin,proc_root=proc_root)==pin and (module_form or script_form)
    except (OSError,KeyError,ValueError,RuntimeError):return False

def _retire_observer(root:Path,profile:str,parent:ParentBinding,*,announced:bool,
                     kill=os.kill)->str:
    """Parent-invoked, fail-closed retirement for one precisely owned helper."""
    if not announced:return "announcement-required"
    data=_runtime_read(_runtime_path(root,profile)); observer=data.get("observer",{})
    binding_id=parent.context.key()[:64]
    legacy=not observer.get("binding_id") and not observer.get("context_key")
    if ((not legacy and (observer.get("binding_id")!=binding_id or observer.get("context_key")!=parent.context.key()))
            or observer.get("server_id")!=parent.herdr_server_id
            or observer.get("pane_id")!=parent.pane_id):return "foreign-or-ambiguous"
    try:
        record=load_existing_binding(root,binding_id); recorded=parent_from_dict(record["parent"])
        if (recorded.context.key()!=parent.context.key() or recorded.herdr_server_id!=parent.herdr_server_id
                or recorded.pane_id!=parent.pane_id or recorded.tab_id!=parent.tab_id
                or recorded.workspace_id!=parent.workspace_id):return "foreign-or-ambiguous"
    except (OSError,ValueError,KeyError,TypeError):return "binding-unavailable"
    pid=observer.get("pid"); pin=observer.get("pin")
    if (not isinstance(pin,dict) or not isinstance(pin.get("start_ticks"),int)
            or pin.get("uid")!=os.getuid() or not isinstance(pin.get("exe"),str)):
        return "process-identity-unknown"
    current=_process_pin(pid,expected=pin)
    if not current:return "process-identity-unknown"
    # Legacy helper records can be retired only if argv independently proves
    # the private binding and source path recorded in its owned binding.
    expected={**observer,"binding_id":binding_id,
              "source_path":observer.get("source_path") or str(Path(record.get("entrypoint", "")).parent.parent/"src"),
              "source_root":observer.get("source_root") or str(Path(record.get("entrypoint", "")).parent.parent/"src"),
              "entrypoint":record.get("entrypoint")}
    if not _observer_command_matches(pid,expected):return "command-identity-unknown"
    try:kill(pid,signal.SIGTERM)
    except OSError:return "signal-failed"
    deadline=time.monotonic()+1.0
    while time.monotonic()<deadline:
        if _process_pin(pid,expected=current) is None:
            try: os.kill(pid,0)
            except ProcessLookupError:
                def ended(data):
                    old=data.get("observer",{})
                    if old.get("pid")==pid and old.get("pin")==current:
                        old["state"]="ended"; old["ended_at"]=time.time(); data["observer"]=old
                _runtime_write(root,profile,ended)
                return "ended"
            except OSError:return "process-state-unknown"
            # A live PID with a changed start time is reuse, not our helper.
            if _process_pin(pid) is not None:return "ended"
        time.sleep(.05)
    return "still-running"

def _proc_argv(pid:int,*,expected_cwd:Path,proc_root:Path=Path("/proc"))->list[str]|None:
    """Read bounded argv only when PID, cwd and executable remain pinned."""
    pin=_process_pin(pid,proc_root=proc_root)
    if not pin:return None
    root=proc_root/str(pid)
    try:
        cwd=(root/"cwd").resolve(strict=True)
        with (root/"cmdline").open("rb") as stream: raw=stream.read(65537)
        if len(raw)>65536 or cwd!=expected_cwd.resolve(strict=True):return None
        argv=[x.decode("utf-8","surrogateescape") for x in raw.split(b"\0") if x]
        return argv if _process_pin(pid,expected=pin,proc_root=proc_root) else None
    except (OSError,ValueError,RuntimeError,UnicodeError):return None

def _parser() -> argparse.ArgumentParser:
    parser=argparse.ArgumentParser(prog="harness-herdr-hooks"); sub=parser.add_subparsers(dest="command",required=True)
    for name in ("install","status","uninstall"):
        p=sub.add_parser(name); p.add_argument("harness",choices=("codex","opencode")); p.add_argument("--config-dir")
    for name in ("codex-hook","opencode-event","observe","attach","launch-run"):
        p=sub.add_parser(name,help=argparse.SUPPRESS); p.add_argument("binding_id",nargs="?")
    return parser

def _state_root() -> Path:
    if os.environ.get("HARNESS_HERDR_STATE_ROOT"):
        value=Path(os.environ["HARNESS_HERDR_STATE_ROOT"]).expanduser()
        if not value.is_absolute(): raise ValueError("integration state root must be absolute")
        return value.resolve()
    return Path(os.environ.get("XDG_STATE_HOME",str(Path.home()/".local/state"))).expanduser().resolve()

def _herdr_client() -> HerdrClient:
    sock=os.environ.get("HERDR_SOCKET_PATH")
    if not sock or not Path(sock).is_absolute(): raise ValueError("absolute Herdr socket marker required")
    return HerdrClient(sock,timeout=.3)

def _parent_from_event(command:str, payload:bytes, client:HerdrClient):
    snap=client.snapshot(); pane_id=os.environ["HERDR_PANE_ID"]
    pane=next((p for p in snap.get("panes",[]) if isinstance(p,dict) and p.get("pane_id")==pane_id),None)
    if not pane or pane.get("tab_id")!=os.environ["HERDR_TAB_ID"] or pane.get("workspace_id")!=os.environ["HERDR_WORKSPACE_ID"]:
        raise ValueError("caller Herdr pane does not match current snapshot")
    ref=pane.get("agent_session")
    if not isinstance(ref,dict) or ref.get("kind") not in {"id","path"} or not isinstance(ref.get("value"),str) or not ref["value"]: raise ValueError("caller pane has no supported native session reference")
    info=client.process_info(pane_id); procs=info.get("foreground_processes",[])
    if command=="opencode-event":
        event,_,roots=OpenCodeAdapter.parse_bridge(payload); envelope=json.loads(payload)
        if ref["kind"]!="id": raise ValueError("OpenCode path references are not qualified")
        pid=envelope["backend"]["pid"]; url=envelope["backend"]["server_url"].rstrip("/")
        if not any(p.get("pid")==pid and "opencode" in (str(p.get("name",""))+" "+str(p.get("argv") or "")).lower() for p in procs if isinstance(p,dict)):
            raise ValueError("OpenCode server PID is not the caller pane foreground process")
        root_paths=[Path(roots[k]) for k in ("config_dir","data_dir","state_dir")]
        if not all(path.is_absolute() for path in root_paths): raise ValueError("OpenCode roots must be absolute")
        context=Context(Harness.OPENCODE,str(root_paths[0]),root_paths[0],root_paths[1],root_paths[2],url,ref["value"],f"pid:{pid}")
        created_context=replace(event.context,backend_instance=f"pid:{pid}") if event.kind=="session.created" else None
        backend_pid=pid
    else:
        # Herdr's PID/name/cwd evidence selects the default profile daemon even
        # when argv is omitted. The backend helper pins process and socket.
        codex_home=Path(os.environ.get("CODEX_HOME","~/.codex")).expanduser().resolve()
        matches=[p for p in procs if isinstance(p,dict) and p.get("pid") is not None and
                 "codex" in str(p.get("name","")).lower()]
        if len(matches)!=1: raise ValueError("Codex foreground process is missing or ambiguous")
        proof=codex_backend_proof(matches[0],codex_home)
        sock=Path(proof["socket_target"]); backend_instance="{}:{}:{}".format(*proof["socket_identity"][:3])
        event=parse_hook(payload,profile=str(codex_home),config_root=codex_home,data_root=codex_home,state_root=codex_home,
                         verified_backend_id=str(sock),verified_backend_instance=backend_instance)
        context=Context(Harness.CODEX,str(codex_home),codex_home,codex_home,codex_home,str(sock),event.identity.session_id,backend_instance)
        provider=CodexRuntimeAdapter(context,executable=str(_native_codex_executable(codex_home)))
        try:
            root_id=_verified_pane_root(provider,ref)
            if event.event_name=="SessionStart":
                if root_id!=event.identity.session_id: raise ValueError("Codex hook root does not match pane thread")
            else:
                # Fetch the native source chain by following metadata one parent at a time.
                rows={}; current=event.identity.session_id
                for _ in range(32):
                    row=provider._read_thread(current); rows[current]=row
                    parent_id=row.get("parentThreadId")
                    if not isinstance(parent_id,str) or not parent_id: break
                    if parent_id==root_id: break
                    current=parent_id
                chain=provider._verified_chain(event.identity.session_id,rows,root_id)
                if chain is None: raise ValueError("Codex child source chain does not reach pane root")
            context=replace(context,session_id=root_id)
            session_path=Path(provider._read_thread(root_id)["path"]).resolve(strict=False) if ref["kind"]=="path" else None
        finally: provider.close()
        parent=ParentBinding(context,client.server_identity(),os.environ["HERDR_WORKSPACE_ID"],os.environ["HERDR_TAB_ID"],pane_id,
                             session_path=session_path,backend_proof=proof)
        if not client.verify_parent(parent): raise ValueError("parent/backend binding failed Herdr verification")
        created_context=event if event.event_name in {"SubagentStart","SubagentStop"} else None
        cwd=pane.get("cwd")
        if not isinstance(cwd,str) or not Path(cwd).is_absolute(): raise ValueError("verified Herdr pane working directory unavailable")
        return parent,None,Path(cwd),created_context
        backend_pid=None
    parent=ParentBinding(context,client.server_identity(),os.environ["HERDR_WORKSPACE_ID"],os.environ["HERDR_TAB_ID"],pane_id,session_path=session_path if command!="opencode-event" else None)
    if not client.verify_parent(parent,backend_pid): raise ValueError("parent/backend binding failed Herdr verification")
    cwd=pane.get("cwd")
    if not isinstance(cwd,str) or not Path(cwd).is_absolute(): raise ValueError("verified Herdr pane working directory unavailable")
    return parent,backend_pid,Path(cwd),created_context

def _verified_pane_root(provider:CodexRuntimeAdapter, ref:dict[str,str])->str:
    """Resolve the typed Herdr root reference against this exact daemon."""
    from .adapters.codex import list_loaded_threads
    loaded=list_loaded_threads(provider.proxy)
    if ref["kind"]=="id": root=ref["value"]
    else:
        found=[]
        # Resolve only loaded threads; never scan unrelated persisted history.
        for ident in loaded:
            row=provider._read_thread(ident)
            path=row.get("path")
            if isinstance(path,str) and Path(path).is_absolute() and Path(path).resolve(strict=False)==Path(ref["value"]).resolve(strict=False):
                found.append(row.get("id"))
        if len(found)!=1: raise ValueError("pane path reference does not resolve uniquely on selected backend")
        root=found[0]
    if root not in loaded: raise ValueError("pane root thread is not loaded on selected backend")
    row=provider._read_thread(root)
    if row.get("id")!=root: raise ValueError("native pane root metadata identity mismatch")
    if ref["kind"]=="path" and (not isinstance(row.get("path"),str) or Path(row["path"]).resolve(strict=False)!=Path(ref["value"]).resolve(strict=False)):
        raise ValueError("native pane root path does not match Herdr reference")
    return root

def verified_codex_parent(context:Context, requesting_thread_id:str, executable:Path|None=None):
    """Reusable no-turn bootstrap for U90B: exact loaded requester on selected home."""
    if not requesting_thread_id or not Path(context.backend_id).is_absolute(): raise ValueError("native requesting thread and backend required")
    provider=CodexRuntimeAdapter(context,executable=str(executable or _native_codex_executable(context.config_root)))
    try:
        from .adapters.codex import list_loaded_threads
        if requesting_thread_id not in list_loaded_threads(provider.proxy): raise ValueError("requesting native thread is not loaded")
        row=provider._read_thread(requesting_thread_id)
        if row.get("id")!=requesting_thread_id: raise ValueError("requesting native thread metadata identity mismatch")
        if context.profile!=str(context.config_root): raise ValueError("selected Codex profile does not match backend home")
        return provider, row
    except BaseException:
        provider.close(); raise

def _provider(parent:ParentBinding,pid:int|None,client:HerdrClient):
    if parent.context.harness==Harness.CODEX:
        proof=parent.backend_proof or {}; executable=proof.get("executable")
        if not isinstance(executable,str) or not Path(executable).is_absolute(): raise ValueError("recorded native Codex executable proof missing")
        return CodexRuntimeAdapter(parent.context,executable=executable)
    if pid is None: raise ValueError("OpenCode backend PID missing")
    return OpenCodeRuntimeAdapter(parent.context,pid,herdr_client=client)

def _start_observer(parent:ParentBinding,pid:int|None,client:HerdrClient,cwd:Path,created_context=None)->None:
    root=_state_root(); binding=parent.context.key()[:64]
    session=Session(parent.context,None,None,cwd,Lifecycle.UNKNOWN,False,time.time())
    record={"parent":parent_to_dict(parent),"child":session_to_dict(session),"pane_id":parent.pane_id,
            "backend_pid":pid,"server_socket":str(client.socket_path),"entrypoint":str(Path(__file__).resolve().parents[2]/"bin/harness-herdr-hooks"),"shell_pid":None}
    save_binding(root,binding,record)
    if isinstance(created_context,Context):
        StateStore(root,parent.context.key()[:32]).note_creation(created_context.key())
    elif created_context is not None:
        store=StateStore(root,parent.context.key()[:32]); child_context=replace(parent.context,session_id=created_context.identity.session_id)
        child_key=child_context.key()
        if created_context.event_name=="SubagentStart":
            store.note_creation(child_key)
            # Hook delivery can lag a later turn. Only the backend's current
            # native turn may replace generation, binding, or ownership state.
            try:
                provider=_provider(parent,pid,client)
                try:
                    from .adapters.codex import list_turn_metadata
                    turns=list_turn_metadata(provider.proxy,created_context.identity.session_id)
                    latest=turns[0] if turns else None
                    if latest and latest.turn_id==created_context.turn_id:
                        store.begin_generation(child_key,created_context.turn_id,turn_id=created_context.turn_id,
                                               kind="subagent",parent_id=parent.context.session_id)
                finally:
                    provider.close()
            except Exception:
                # Keep pending creation eligibility, but never infer a turn.
                pass
        else:
            current=store.generation(child_key)
            if current and current.get("generation")==created_context.turn_id and current.get("turn_id")==created_context.turn_id:
                store.note_stop_hint(child_key,created_context.turn_id,created_context.turn_id,
                                     stop_hook_active=bool(created_context.stop_hook_active))
    env=child_environment(parent.context,pane_markers={k:os.environ[k] for k in ("HERDR_ENV","HERDR_SOCKET_PATH","HERDR_PANE_ID","HERDR_TAB_ID","HERDR_WORKSPACE_ID")})
    env["HARNESS_HERDR_STATE_ROOT"]=str(root); env["XDG_STATE_HOME"]=str(root)
    entry=Path(record["entrypoint"])
    subprocess.Popen([str(entry),"observe",binding],cwd=str(cwd),env=env,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
                     close_fds=True,start_new_session=True)

def _observe(binding:str)->None:
    root=_state_root(); record=load_existing_binding(root,binding); parent=parent_from_dict(record["parent"])
    if record.get("server_socket")!=os.environ.get("HERDR_SOCKET_PATH"): raise ValueError("observer Herdr socket differs from stored binding")
    client=HerdrClient(record["server_socket"])
    client.snapshot()
    if client.server_identity()!=parent.herdr_server_id: raise ValueError("observer Herdr server identity changed")
    pid=record.get("backend_pid"); provider=_provider(parent,pid,client)
    store=StateStore(_state_root(),parent.context.key()[:32])
    pin=_process_pin(os.getpid())
    run_observer(parent,store,provider,client,Path(record["entrypoint"]),root,pid,
                 on_start=lambda:_publish_observer(root,parent,"running",pin),
                 on_end=lambda:_publish_observer(root,parent,"ended",pin))

def main(argv:Sequence[str]|None=None)->int:
    args=_parser().parse_args(argv)
    # Reject malformed opaque IDs before resolving state roots or touching disk.
    if args.command=="launch-run" and (not args.binding_id or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}",args.binding_id)):
        print("harness-herdr-hooks: ValueError: invalid launch request ID",file=sys.stderr); return 2
    try:
        if args.command=="install": result=installer.install(args.harness,source_root=Path(__file__).resolve().parents[2],config_dir=args.config_dir)
        elif args.command=="status":
            result=installer.status(args.harness,config_dir=args.config_dir)
            if args.harness=="codex": result["runtime"]=_runtime_status(_state_root(),result["config_root"])
        elif args.command=="uninstall": result=installer.uninstall(args.harness,config_dir=args.config_dir)
        elif args.command=="launch-run":
            root=_state_root()/"harness-herdr-hooks"/"launches"
            return run_claimed_launch(args.binding_id,store=LaunchStore(root),verify_destination=_verify_launch_destination,environ=os.environ)
        else:
            # Outside Herdr, or when launched as the attachment display client,
            # skip before consuming event input or touching private state.
            if os.environ.get("HERDR_ENV")!="1" or os.environ.get("HARNESS_HERDR_DISPLAY")=="1": return 0
            if args.command in {"observe","attach"}:
                if not args.binding_id or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}",args.binding_id): raise ValueError("invalid opaque binding ID")
                if args.command=="attach": exec_binding(args.binding_id)
                else: _observe(args.binding_id)
                return 0
            markers=("HERDR_SOCKET_PATH","HERDR_PANE_ID","HERDR_TAB_ID","HERDR_WORKSPACE_ID")
            if not all(os.environ.get(k) for k in markers):return 0
            limit=1_048_576 if args.command=="codex-hook" else 262_144
            payload=sys.stdin.buffer.read(limit+1)
            if len(payload)>limit:raise ValueError("event JSON exceeds size limit")
            if not payload:raise ValueError("event JSON is empty")
            client=_herdr_client()
            deadline=time.monotonic()+4.0
            for attempt in range(3):
                try:
                    parent,pid,cwd,created_context=_parent_from_event(args.command,payload,client)
                    break
                except (HerdrError,ValueError):
                    if attempt==2 or time.monotonic()+1.3>=deadline: raise
                    time.sleep(.1)
            _start_observer(parent,pid,client,cwd,created_context)
            if args.command=="codex-hook": _record_hook(_state_root(),parent)
            return 0
        print(json.dumps(result,sort_keys=True));return 0
    except Exception as exc:
        # Hook failures are bounded diagnostics and never become fake success.
        print(f"harness-herdr-hooks: {type(exc).__name__}: {exc}",file=sys.stderr);return 2

if __name__=="__main__": raise SystemExit(main())
