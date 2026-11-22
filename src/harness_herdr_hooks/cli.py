"""Public install commands and bounded, context-scoped runtime entrypoints."""
from __future__ import annotations
import argparse, fcntl, hashlib, json, os, re, shutil, socket, stat, subprocess, sys, time
import shlex
from pathlib import Path
from typing import Sequence
from . import install as installer
from .adapters.codex import parse_hook, CodexRuntimeAdapter
from .coordinator import run_observer
from .environment import child_environment
from .herdr import HerdrClient, HerdrError, codex_backend_proof, codex_remote_socket
from .model import Context, Harness, Lifecycle, ParentBinding, Session, parent_from_dict, parent_to_dict, session_to_dict
from .state import StateStore, load_existing_binding, save_binding
from .launch import LaunchStore, run_claimed_launch

_RUNTIME_MAX_AGE=30*24*60*60
_RUNTIME_MAX_BYTES=16384

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
        data=_runtime_read(path); data={k:v for k,v in data.items() if k in {"schema","updated","task_discovery"}}
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

def _runtime_status(root:Path,profile:str)->dict:
    data=_runtime_read(_runtime_path(root,profile))
    task=data.get("task_discovery",{})
    if not isinstance(task,dict): task={}
    task_status={
        "recognition":task.get("recognition") if task.get("recognition") in {"unknown","observing","recognized","deferred","rejected"} else "unknown",
        "verification":task.get("verification") if task.get("verification") in {"unknown","pending","verified","deferred","rejected"} else "unknown",
        "attachment":task.get("attachment") if task.get("attachment") in {"unknown","pending","attached","deferred","rejected"} else "unknown",
    }
    reasons={"parent_file_missing","parent_file_mismatch","unsafe_parent_file","metadata_unavailable",
             "candidate_expired","future_timestamp","task_finished","task_mismatch","unsupported_envelope",
             "unsupported_record_format","retry_exhausted","attachment_pending","invalid_cwd","cwd_mismatch",
             "status_deferred","pending_limit"}
    if task.get("reason") in reasons:
        task_status["reason"]=task["reason"]
    health=task.get("current_health")
    if isinstance(health,dict) and health.get("state") in {"healthy","deferred"}:
        current_health={"state":health["state"]}
        if health.get("reason") in reasons: current_health["reason"]=health["reason"]
        task_status["current_health"]=current_health
    return {"task_discovery": task_status}

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
        parent,parent_cwd=_ordinary_launch_parent(synthetic,client)
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
    for name in ("codex-hook","opencode-event","observe","observe-standalone","attach","launch-run"):
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

def _ordinary_launch_parent(raw: dict, client: HerdrClient) -> tuple[ParentBinding, Path]:
    pane_id = os.environ["HERDR_PANE_ID"]
    workspace_id = os.environ["HERDR_WORKSPACE_ID"]
    tab_id = os.environ["HERDR_TAB_ID"]
    pane = next((p for p in client.snapshot().get("panes", [])
                 if isinstance(p, dict) and p.get("pane_id") == pane_id), None)
    if not pane or pane.get("workspace_id") != workspace_id or pane.get("tab_id") != tab_id:
        raise ValueError("caller Herdr pane does not match current snapshot")
    ref = pane.get("agent_session")
    if (not isinstance(ref, dict) or ref.get("kind") not in {"id", "path"}
            or not isinstance(ref.get("value"), str) or not ref["value"]):
        raise ValueError("caller pane has no supported native session reference")
    home = Path(os.environ.get("CODEX_HOME", "~/.codex")).expanduser().resolve()
    processes = [proc for proc in client.process_info(pane_id).get("foreground_processes", [])
                 if isinstance(proc, dict) and proc.get("pid") is not None
                 and "codex" in str(proc.get("name", "")).lower()]
    if len(processes) != 1:
        raise ValueError("Codex foreground process is missing or ambiguous")
    proof = codex_backend_proof(processes[0], home)
    socket_target = str(proof["socket_target"])
    instance = "{}:{}:{}".format(*proof["socket_identity"][:3])
    event = parse_hook(raw, profile=str(home), config_root=home, data_root=home,
                       state_root=home, verified_backend_id=socket_target,
                       verified_backend_instance=instance)
    context = event.identity.context()
    provider = CodexRuntimeAdapter(context, executable=str(_native_codex_executable(home)))
    try:
        root_id = _verified_pane_root(provider, ref)
        if root_id != context.session_id:
            raise ValueError("Codex caller session does not match pane thread")
        path = provider._read_thread(root_id).get("path")
        session_path = Path(path).resolve(strict=False) if isinstance(path, str) and Path(path).is_absolute() else None
    finally:
        provider.close()
    parent = ParentBinding(context, client.server_identity(), workspace_id, tab_id, pane_id,
                           session_path=session_path, backend_proof=proof)
    cwd = pane.get("cwd")
    if not client.verify_parent(parent) or not isinstance(cwd, str) or not Path(cwd).is_absolute():
        raise ValueError("ordinary launch caller binding is not verified")
    return parent, Path(cwd)


def _parent_from_event(command:str, payload:bytes, client:HerdrClient):
    """Route only standalone SessionStart through identity-only verification."""
    if command != "codex-hook":
        return None, None, None, None
    raw = json.loads(payload)
    if not isinstance(raw, dict) or raw.get("hook_event_name") != "SessionStart":
        return None, None, None, None
    return _standalone_session_parent(raw, client)

def _standalone_session_parent(raw:dict,client:HerdrClient):
    """Bind a new standalone SessionStart through authenticated session identity only."""
    from .codex_backend import select_endpoint
    profile=Path(os.environ.get("CODEX_HOME","~/.codex")).expanduser().resolve()
    pin=select_endpoint(profile)
    instance=pin.instance
    event=parse_hook(raw,profile=str(profile),config_root=profile,data_root=profile,state_root=profile,
                     verified_backend_id=str(pin.target),verified_backend_instance=instance)
    context=event.identity.context()
    if os.environ.get("HARNESS_HERDR_DISPLAY") == "1":
        return None, None, None, None
    try:
        claim = load_existing_binding(_state_root(), "display-" + context.key())
    except FileNotFoundError:
        claim = None
    if claim and claim.get("kind") == "standalone" and claim.get("ownership") == "created":
        owner = parent_from_dict(claim["parent"])
        from .model import session_from_dict
        child = session_from_dict(claim["child"])
        if child.context == context and claim.get("server_socket") == str(client.socket_path):
            snap = client.snapshot()
            if client.server_identity() == owner.herdr_server_id and any(
                    pane.get("pane_id") == claim.get("pane_id")
                    and pane.get("workspace_id") == owner.workspace_id
                    and pane.get("tab_id") == owner.tab_id
                    for pane in snap.get("panes", []) if isinstance(pane, dict)):
                return None, None, None, None
    executable=_native_codex_executable(profile)
    provider=CodexRuntimeAdapter(context,executable=str(executable),task_store_root=_state_root())
    try:
        from .adapters.codex import list_loaded_threads
        if event.identity.session_id not in list_loaded_threads(provider.proxy):
            raise ValueError("standalone SessionStart thread is not loaded on selected profile backend")
        row=provider._read_thread(event.identity.session_id)
        if row.get("id")!=event.identity.session_id:
            raise ValueError("standalone SessionStart thread metadata identity mismatch")
        path=row.get("path")
        session_path=Path(path).resolve(strict=False) if isinstance(path,str) and Path(path).is_absolute() else None
        transcript=raw.get("transcript_path")
        if transcript is not None and (session_path is None or not Path(transcript).is_absolute()
                                       or Path(transcript).resolve(strict=False)!=session_path):
            raise ValueError("Codex hook transcript path does not match standalone thread")
        cwd=row.get("cwd")
        if not isinstance(cwd,str) or not Path(cwd).is_absolute():
            raise ValueError("standalone thread working directory unavailable")
        destination=client.session_destination(event.identity.session_id,session_path=session_path,harness="codex")
        if destination is None:
            raise ValueError("standalone thread has no unique authenticated Herdr destination")
        if destination.get("server_id")!=client.server_identity():
            raise ValueError("standalone destination belongs to a different Herdr server")
        proof={"socket_alias":str(pin.alias),"socket_target":str(pin.target),
               "socket_identity":list(pin.socket_identity),"alias_identity":list(pin.alias_identity),
               "directory_identity":list(pin.directory_identity),"executable":str(executable)}
        parent=ParentBinding(context,destination["server_id"],destination["workspace_id"],destination["tab_id"],
                             destination["anchor_pane_id"],session_path=session_path,backend_proof=proof)
        # The current authenticated session snapshot is the authority here. Do not
        # consult pane markers, process_info, or PID based verify_parent checks.
        return parent,None,Path(cwd),None
    finally:
        provider.close()

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

def _provider(parent: ParentBinding) -> CodexRuntimeAdapter:
    proof = parent.backend_proof or {}
    executable = proof.get("executable")
    if not isinstance(executable, str) or not Path(executable).is_absolute():
        raise ValueError("recorded native Codex executable proof missing")
    return CodexRuntimeAdapter(parent.context, executable=executable, task_store_root=_state_root())


def _start_observer(parent: ParentBinding, client: HerdrClient, cwd: Path) -> None:
    root = _state_root()
    entrypoint = _entrypoint()
    session = Session(parent.context, None, None, cwd, Lifecycle.UNKNOWN, False, time.time())
    identity = [parent.context.key(), parent.herdr_server_id, parent.workspace_id, parent.tab_id]
    binding = "standalone-" + hashlib.sha256(json.dumps(identity).encode()).hexdigest()
    save_binding(root, binding, {
        "parent": parent_to_dict(parent), "child": session_to_dict(session),
        "pane_id": parent.pane_id, "backend_pid": None, "shell_pid": None,
        "server_socket": str(client.socket_path), "entrypoint": str(entrypoint),
        "kind": "standalone",
    })
    env = child_environment(parent.context, pane_markers={
        "HERDR_ENV": "1", "HERDR_SOCKET_PATH": str(client.socket_path),
    })
    env["HARNESS_HERDR_STATE_ROOT"] = str(root)
    subprocess.Popen([str(entrypoint), "observe-standalone", binding],
                     cwd=str(cwd), env=env, stdin=subprocess.DEVNULL,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     close_fds=True, start_new_session=True)


def _observe(binding: str) -> None:
    if not re.fullmatch(r"standalone-[0-9a-f]{64}", binding):
        return
    root = _state_root()
    record = load_existing_binding(root, binding)
    parent = parent_from_dict(record["parent"])
    if (record.get("kind") != "standalone" or parent.context.harness != Harness.CODEX
            or record.get("server_socket") != os.environ.get("HERDR_SOCKET_PATH")
            or record.get("entrypoint") != str(_entrypoint())):
        return
    client = HerdrClient(record["server_socket"])
    client.snapshot()
    if client.server_identity() != parent.herdr_server_id:
        return
    provider = _provider(parent)
    store = StateStore(root, parent.context.key()[:32])
    run_observer(parent, store, provider, client, _entrypoint(), root)


def main(argv:Sequence[str]|None=None)->int:
    args=_parser().parse_args(argv)
    # Reject malformed opaque IDs before resolving state roots or touching disk.
    if args.command=="launch-run" and (not args.binding_id or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}",args.binding_id)):
        print("harness-herdr-hooks: ValueError: invalid launch request ID",file=sys.stderr); return 2
    try:
        if args.command=="install": result=installer.install(args.harness,source_root=Path(__file__).resolve().parents[2],config_dir=args.config_dir)
        elif args.command=="status":
            result=installer.status(args.harness,config_dir=args.config_dir)
            if args.harness == "codex":
                result["runtime"] = _runtime_status(_state_root(), result["config_root"])
        elif args.command=="uninstall": result=installer.uninstall(args.harness,config_dir=args.config_dir)
        elif args.command=="launch-run":
            root=_state_root()/"harness-herdr-hooks"/"launches"
            return run_claimed_launch(args.binding_id,store=LaunchStore(root),verify_destination=_verify_launch_destination,environ=os.environ)
        else:
            # Outside Herdr, skip before consuming event input or touching private state.
            if os.environ.get("HERDR_ENV")!="1": return 0
            # These registered entrypoints are retained only for safe migration.
            # Native child hooks and the retired OpenCode bridge are inert even
            # when an old installation still invokes them.
            if args.command in {"opencode-event","observe","attach"}: return 0
            if args.command == "observe-standalone":
                _observe(args.binding_id or "")
                return 0
            if not os.environ.get("HERDR_SOCKET_PATH"):
                return 0
            limit=1_048_576 if args.command=="codex-hook" else 262_144
            payload=sys.stdin.buffer.read(limit+1)
            if len(payload)>limit:raise ValueError("event JSON exceeds size limit")
            if not payload:raise ValueError("event JSON is empty")
            if args.command=="codex-hook":
                try:
                    event_name=json.loads(payload).get("hook_event_name")
                except (json.JSONDecodeError,AttributeError):
                    event_name=None
                if event_name in {"SubagentStart","SubagentStop"}: return 0
                # SessionStart resolves solely through the selected profile and
                # authenticated Herdr session snapshot; inherited pane markers
                # cannot select the legacy process-bound route.
                if event_name!="SessionStart": return 0
            client=_herdr_client()
            deadline=time.monotonic()+4.0
            for attempt in range(3):
                try:
                    parent,pid,cwd,created_context=_parent_from_event(args.command,payload,client)
                    break
                except (HerdrError,ValueError):
                    if attempt==2 or time.monotonic()+1.3>=deadline: raise
                    time.sleep(.1)
            if parent is None:return 0
            _start_observer(parent, client, cwd)
            return 0
        print(json.dumps(result,sort_keys=True));return 0
    except Exception as exc:
        # Hook failures are bounded diagnostics and never become fake success.
        print(f"harness-herdr-hooks: {type(exc).__name__}: {exc}",file=sys.stderr);return 2

if __name__=="__main__": raise SystemExit(main())
