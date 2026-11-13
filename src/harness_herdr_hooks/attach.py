"""Verified wrapper launch and native acknowledgement for owned Herdr panes."""
from __future__ import annotations
import os, shlex, shutil, stat, time
from pathlib import Path
from typing import Callable, Any
from .herdr import HerdrClient, HerdrError
from .environment import child_environment
from .model import Harness, parent_from_dict, session_from_dict

class AttachmentUnavailable(RuntimeError): pass
class AttachError(AttachmentUnavailable):
    def __init__(self,message:str,pane_id:str,*,retryable:bool=False):
        super().__init__(message); self.pane_id=pane_id; self.retryable=retryable
_SUPPORTED_SHELLS={'sh','bash','zsh','dash','ksh'}

def wrapper_command(entrypoint:Path,binding_id:str)->str:
    if not entrypoint.is_absolute() or not binding_id or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_' for c in binding_id):
        raise ValueError('expected absolute entrypoint and opaque binding ID')
    return 'exec '+shlex.quote(str(entrypoint))+' attach '+shlex.quote(binding_id)

def shell_is_ready(process_info:dict)->bool:
    shell_pid=process_info.get('shell_pid'); fg=process_info.get('foreground_processes')
    if not isinstance(shell_pid,int) or not isinstance(fg,list) or len(fg)!=1: return False
    proc=fg[0]
    if not isinstance(proc,dict) or proc.get('pid')!=shell_pid: return False
    name=Path(str(proc.get('argv0') or proc.get('name') or '')).name.lower().lstrip('-')
    argv=proc.get('argv') or []
    return name in _SUPPORTED_SHELLS and (not argv or Path(str(argv[0])).name.lower() in _SUPPORTED_SHELLS)


def _outcome(root:Path,binding_id:str,status:str,pid:int|None=None)->None:
    from .state import update_binding_outcome
    update_binding_outcome(root,binding_id,status,pid)

def _argv_matches(actual:object,expected:list[str])->bool:
    if not isinstance(actual,list) or len(actual)!=len(expected): return False
    def canon(x:str)->str:
        found=shutil.which(x) if not Path(x).is_absolute() else x
        return str(Path(found).resolve()) if found else x
    return canon(actual[0])==canon(expected[0]) and actual[1:]==expected[1:]

def _tty_has_no_processes(tty:str)->bool:
    """Linux-only bounded /proc scan; any uncertainty retains the pane."""
    if not tty.startswith('/dev/') or not Path('/proc').is_dir(): return False
    try: dev=os.stat(tty).st_rdev
    except OSError: return False
    try:
        entries=list(os.scandir('/proc'))
        if len(entries)>20000: return False
        stats=[]
        for entry in entries:
            if not entry.name.isdigit(): continue
            try: stats.append(Path(entry.path,'stat').read_text())
            except FileNotFoundError: continue
            except OSError: return False
        from .herdr import _tty_stats_empty
        return _tty_stats_empty(stats,dev)
    except OSError: return False

def _runtime(parent:Any,child:Any,client:HerdrClient,backend_pid:int|None):
    if child.context.harness==Harness.CODEX:
        from .adapters.codex import CodexRuntimeAdapter
        return CodexRuntimeAdapter(parent.context, executable=shutil.which('codex') or 'codex')
    from .adapters.opencode import OpenCodeRuntimeAdapter
    if not backend_pid: raise AttachmentUnavailable('OpenCode backend PID missing')
    return OpenCodeRuntimeAdapter(parent.context,backend_pid,herdr_client=client)

def exec_binding(binding_id:str,environment:dict[str,str]|None=None)->None:
    """Load and verify one binding, then exec its existing native child session."""
    if not binding_id or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_' for c in binding_id):
        raise AttachmentUnavailable('invalid opaque binding ID')
    env=os.environ if environment is None else environment
    root_value=env.get('HARNESS_HERDR_STATE_ROOT'); socket_value=env.get('HERDR_SOCKET_PATH')
    markers=('HERDR_PANE_ID','HERDR_TAB_ID','HERDR_WORKSPACE_ID','HERDR_BIN_PATH')
    if (env.get('HERDR_ENV')!='1' or not all(env.get(k) for k in markers)
            or not root_value or not Path(root_value).is_absolute() or not socket_value or not Path(socket_value).is_absolute()):
        raise AttachmentUnavailable('integration state or pane socket marker unavailable')
    from .state import load_existing_binding
    root=Path(root_value); record=load_existing_binding(root,binding_id)
    required={'parent','child','pane_id','server_socket','entrypoint','shell_pid'}
    if not required<=record.keys() or not record.get('pane_id'): raise AttachmentUnavailable('binding record incomplete')
    parent=parent_from_dict(record['parent']); child=session_from_dict(record['child'])
    socket_path=Path(record['server_socket'])
    if socket_path!=Path(socket_value) or not socket_path.is_absolute(): raise AttachmentUnavailable('binding socket differs from pane marker')
    pane_id=record['pane_id']; client=HerdrClient(socket_path); snap=client.snapshot()
    pane=next((p for p in snap.get('panes',[]) if p.get('pane_id')==pane_id),None)
    if (pane_id!=env.get('HERDR_PANE_ID') or not pane or pane.get('tab_id')!=parent.tab_id
            or pane.get('workspace_id')!=parent.workspace_id or pane.get('tab_id')!=env.get('HERDR_TAB_ID')
            or pane.get('workspace_id')!=env.get('HERDR_WORKSPACE_ID')
            or client.server_identity()!=parent.herdr_server_id):
        raise AttachmentUnavailable('new pane/server binding does not match stored authority')
    if pane.get('agent_session') is not None or not isinstance(pane.get('cwd'),str) or Path(pane['cwd']).resolve()!=child.cwd.resolve():
        raise AttachmentUnavailable('target pane has unexpected native session or working directory')
    info=client.process_info(pane_id); procs=info.get('foreground_processes',[])
    if not isinstance(record.get('entrypoint'),str) or not Path(record['entrypoint']).is_absolute(): raise AttachmentUnavailable('binding entrypoint unavailable')
    argv=next((p.get('argv') or [] for p in procs if p.get('pid')==os.getpid()),[])
    python_executable=bool(argv) and Path(argv[0]).name.lower().startswith('python')
    module_argv=python_executable and argv[1:]==['-m','harness_herdr_hooks','attach',binding_id]
    script_argv=python_executable and argv[1:]==[record['entrypoint'],'attach',binding_id]
    if info.get('shell_pid')!=record.get('shell_pid') or not (module_argv or script_argv):
        raise AttachmentUnavailable('current PID/argv does not match this binding wrapper')
    backend_pid=record.get('backend_pid')
    if not client.verify_parent(parent,backend_pid): raise AttachmentUnavailable('original parent/backend binding no longer verifies')
    _outcome(root,binding_id,'verifying',os.getpid())
    adapter=None; started=False
    try:
        adapter=_runtime(parent,child,client,backend_pid)
        if not adapter.can_attach_now(parent,child): raise AttachmentUnavailable('child is no longer attachable')
        native_argv=adapter.attach_argv(child)
        markers={k:v for k,v in env.items() if k.startswith('HERDR_')}
        clean=child_environment(child.context,source=env,pane_markers=markers)
        clean['HARNESS_HERDR_STATE_ROOT']=str(root.resolve()); clean['HARNESS_HERDR_DISPLAY']='1'
        if not native_argv or not shutil.which(native_argv[0],path=clean.get('PATH')):
            raise AttachmentUnavailable('native harness executable unavailable')
        adapter.close(); adapter=None
        _outcome(root,binding_id,'exec-started',os.getpid()); started=True
        os.execvpe(native_argv[0],native_argv,clean)
        raise AttachmentUnavailable('native exec unexpectedly returned')
    except BaseException:
        if adapter is not None:
            try: adapter.close()
            except Exception: pass
        if not started:
            try: _outcome(root,binding_id,'failed-before-exec',os.getpid())
            except Exception: pass
        raise

def _close_failed_before_exec(client:HerdrClient,state_root:Path,binding_id:str,parent:Any)->bool:
    """Close only a proven failed-before-exec pane whose PTY has no live process."""
    try:
        from .state import load_existing_binding
        record=load_existing_binding(state_root,binding_id)
        if (record.get('outcome',{}).get('status')!='failed-before-exec'
                or not record.get('pane_id') or not isinstance(record.get('shell_pid'),int)
                or record.get('server_socket')!=str(client.socket_path)
                or not client.verify_parent(parent,record.get('backend_pid'))): return False
        snap=client.snapshot(); pane=next((p for p in snap.get('panes',[]) if p.get('pane_id')==record['pane_id']),None)
        if (not pane or pane.get('workspace_id')!=parent.workspace_id or pane.get('tab_id')!=parent.tab_id
                or pane.get('agent_session') is not None): return False
        info=client.process_info(record['pane_id'])
        if info.get('shell_pid')!=record['shell_pid'] or info.get('foreground_processes') not in ([],None): return False
        tty=info.get('tty')
        if not isinstance(tty,str) or not _tty_has_no_processes(tty): return False
        client.close(record['pane_id']); return True
    except Exception: return False

def attach_in_new_pane(client:HerdrClient,runtime:Any,parent:object,child:object,entrypoint:Path,
                       binding_id:str,state_root:Path,backend_pid:int|None=None,
                       on_pane_created:Callable[[str,dict],None]|None=None)->str:
    """Revalidate before splitting; persist ownership before sending wrapper text."""
    if not state_root.is_absolute(): raise AttachmentUnavailable('state root must be absolute')
    try: parent_verified=runtime.verify_parent(parent)
    except (TypeError,AttributeError) as exc: raise AttachmentUnavailable('runtime cannot verify selected parent binding') from exc
    if not parent_verified: raise AttachmentUnavailable('parent pane/backend binding is unverified; no pane created')
    if not runtime.can_attach_now(parent,child): raise AttachmentUnavailable('child is no longer attachable; no pane created')
    pane=client.split(parent,child.cwd,env={'HARNESS_HERDR_STATE_ROOT':str(state_root)})
    info=None; initial_shell_pid=None
    for _ in range(3):
        info=client.process_info(pane)
        fg=info.get('foreground_processes',[])
        if len(fg)==1 and isinstance(fg[0],dict) and fg[0].get('pid')==info.get('shell_pid') and fg[0].get('cwd')==str(child.cwd.resolve()):
            initial_shell_pid=info.get('shell_pid')
        if shell_is_ready(info): break
        time.sleep(.1)
    if not info or not shell_is_ready(info):
        raise AttachError('shell readiness unproven; new pane retained because absence of user activity cannot be proven',pane,retryable=False)
    if on_pane_created is None: raise AttachError('binding persistence callback required; pane retained without launch',pane,retryable=False)
    try: on_pane_created(pane,info)
    except Exception as exc: raise AttachError('binding persistence failed before launch; pane retained',pane,retryable=False) from exc
    try:
        # Check immediately before writing to ensure shell is still the same sole foreground process.
        latest=client.process_info(pane)
        if not shell_is_ready(latest) or latest.get('shell_pid')!=info.get('shell_pid'):
            raise AttachmentUnavailable('shell changed before wrapper launch')
        client.send_text(pane,wrapper_command(entrypoint,binding_id))
        client.send_keys(pane,['enter'])
        provider=getattr(runtime,'provider',None)
        if provider is None or not callable(getattr(provider,'attach_argv',None)):
            raise AttachmentUnavailable('native provider attach argv unavailable for acknowledgement')
        expected_argv=provider.attach_argv(child)
        if not client.wait_for_attachment(pane,child.context,backend_pid,expected_argv=expected_argv,session_path=getattr(child,'session_path',None)):
            _close_failed_before_exec(client,state_root,binding_id,parent)
            raise AttachmentUnavailable('native attachment was not acknowledged; pane retained unless failed-before-exec and PTY-empty proof passed')
        _outcome(state_root,binding_id,'attached',None)
        return pane
    except (HerdrError,AttachmentUnavailable) as exc:
        _close_failed_before_exec(client,state_root,binding_id,parent)
        raise AttachError(str(exc),pane,retryable=False) from exc
