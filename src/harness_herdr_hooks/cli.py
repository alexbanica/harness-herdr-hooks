"""Public install commands and bounded, context-scoped runtime entrypoints."""
from __future__ import annotations
import argparse, json, os, re, socket, stat, subprocess, sys, time
from dataclasses import replace
from pathlib import Path
from typing import Sequence
from . import install as installer
from .adapters.codex import parse_hook, CodexRuntimeAdapter
from .adapters.opencode import OpenCodeAdapter, OpenCodeRuntimeAdapter
from .attach import exec_binding
from .coordinator import run_observer
from .environment import child_environment
from .herdr import HerdrClient, HerdrError, codex_remote_socket
from .model import Context, Harness, Lifecycle, ParentBinding, Session, parent_from_dict, parent_to_dict, session_to_dict
from .state import StateStore, load_existing_binding, save_binding

def _parser() -> argparse.ArgumentParser:
    parser=argparse.ArgumentParser(prog="harness-herdr-hooks"); sub=parser.add_subparsers(dest="command",required=True)
    for name in ("install","status","uninstall"):
        p=sub.add_parser(name); p.add_argument("harness",choices=("codex","opencode")); p.add_argument("--config-dir")
    for name in ("codex-hook","opencode-event","observe","attach"):
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
        # Derive only an explicit native --remote unix:// endpoint from the
        # verified foreground Codex process. Never guess the shared daemon.
        codex_home=Path(os.environ.get("CODEX_HOME","~/.codex")).expanduser().resolve()
        candidates=[]
        for proc in procs:
            argv=proc.get("argv",[]) if isinstance(proc,dict) else []
            if not isinstance(argv,list): continue
            if "codex" not in (str(proc.get("name",""))+str(argv)).lower(): continue
            path=codex_remote_socket(argv,codex_home)
            if path is not None and path.exists(): candidates.append(path)
        unique={str(p.resolve()) for p in candidates}
        if len(unique)!=1: raise ValueError("Codex explicit backend socket is missing or ambiguous")
        sock=Path(unique.pop()); st=sock.lstat()
        if not stat.S_ISSOCK(st.st_mode) or st.st_uid!=os.getuid(): raise ValueError("Codex backend socket is not a user-owned socket")
        backend_instance=f"{st.st_dev}:{st.st_ino}:{st.st_uid}"
        event=parse_hook(payload,profile=str(codex_home),config_root=codex_home,data_root=codex_home,state_root=codex_home,
                         verified_backend_id=str(sock),verified_backend_instance=backend_instance)
        session_path=None
        if ref["kind"]=="id":
            if event.identity.session_id!=ref["value"]: raise ValueError("Codex hook session is not the Herdr pane session")
            root_id=ref["value"]
        else:
            transcript=json.loads(payload).get("transcript_path")
            if not isinstance(transcript,str) or not Path(transcript).is_absolute() or Path(transcript).resolve()!=Path(ref["value"]).resolve(): raise ValueError("Codex transcript path does not match the pane's canonical session path")
            session_path=Path(transcript).resolve(); root_id=event.identity.session_id
        context=Context(Harness.CODEX,str(codex_home),codex_home,codex_home,codex_home,str(sock),root_id,backend_instance)
        created_context=replace(context,session_id=event.identity.session_id) if event.event_name=="SessionStart" else None
        backend_pid=None
    parent=ParentBinding(context,client.server_identity(),os.environ["HERDR_WORKSPACE_ID"],os.environ["HERDR_TAB_ID"],pane_id,session_path=session_path if command!="opencode-event" else None)
    if not client.verify_parent(parent,backend_pid): raise ValueError("parent/backend binding failed Herdr verification")
    cwd=pane.get("cwd")
    if not isinstance(cwd,str) or not Path(cwd).is_absolute(): raise ValueError("verified Herdr pane working directory unavailable")
    return parent,backend_pid,Path(cwd),created_context

def _provider(parent:ParentBinding,pid:int|None,client:HerdrClient):
    if parent.context.harness==Harness.CODEX:return CodexRuntimeAdapter(parent.context)
    if pid is None: raise ValueError("OpenCode backend PID missing")
    return OpenCodeRuntimeAdapter(parent.context,pid,herdr_client=client)

def _start_observer(parent:ParentBinding,pid:int|None,client:HerdrClient,cwd:Path,created_context:Context|None=None)->None:
    root=_state_root(); binding=parent.context.key()[:64]
    session=Session(parent.context,None,None,cwd,Lifecycle.UNKNOWN,False,time.time())
    record={"parent":parent_to_dict(parent),"child":session_to_dict(session),"pane_id":parent.pane_id,
            "backend_pid":pid,"server_socket":str(client.socket_path),"entrypoint":str(Path(__file__).resolve().parents[2]/"bin/harness-herdr-hooks"),"shell_pid":None}
    save_binding(root,binding,record)
    if created_context is not None:
        StateStore(root,parent.context.key()[:32]).note_creation(created_context.key())
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
    run_observer(parent,store,provider,client,Path(record["entrypoint"]),root,pid)

def main(argv:Sequence[str]|None=None)->int:
    args=_parser().parse_args(argv)
    try:
        if args.command=="install": result=installer.install(args.harness,source_root=Path(__file__).resolve().parents[2],config_dir=args.config_dir)
        elif args.command=="status": result=installer.status(args.harness,config_dir=args.config_dir)
        elif args.command=="uninstall": result=installer.uninstall(args.harness,config_dir=args.config_dir)
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
            return 0
        print(json.dumps(result,sort_keys=True));return 0
    except Exception as exc:
        # Hook failures are bounded diagnostics and never become fake success.
        print(f"harness-herdr-hooks: {type(exc).__name__}: {exc}",file=sys.stderr);return 2

if __name__=="__main__": raise SystemExit(main())
