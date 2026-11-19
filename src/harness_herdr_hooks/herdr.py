"""Bounded Herdr protocol-22 Unix socket client."""
from __future__ import annotations
import itertools, json, os, shutil, socket, stat, time
from urllib.parse import urlsplit
from .model import matches_agent_session_ref
from pathlib import Path
from typing import Any
class HerdrError(RuntimeError): pass

def _canonical_executable(value:str)->str|None:
    found=value if os.path.isabs(value) else shutil.which(value)
    return os.path.realpath(found) if found else None

def attachment_argv_matches(actual:Any,expected:list[str],context:Any)->bool:
    """Match the exact provider attach command, canonicalizing endpoint/executable only."""
    if not isinstance(actual,list) or not isinstance(expected,list) or not actual or not expected:
        return False
    expected_exe=_canonical_executable(str(expected[0]))
    if expected_exe is None: return False
    args=actual[1:]
    actual_exe=_canonical_executable(str(actual[0]))
    if actual_exe!=expected_exe:
        # Some qualified CLIs execute a native script through Node/Bun. Accept
        # only an exact interpreter prefix whose script resolves to expected exe.
        if Path(str(actual[0])).name.lower() not in {'node','nodejs','bun'} or len(actual)<3:
            return False
        script=_canonical_executable(str(actual[1]))
        if script!=expected_exe: return False
        args=actual[2:]
    if context.harness.value=='codex':
        def endpoint_for(command:list[str])->Path|None:
            if len(command)==4 and command[0]=='resume' and command[1]=='--remote' and command[3]==context.session_id:
                pass
            elif len(command)==3 and command[0]=='resume' and command[1].startswith('--remote=') and command[2]==context.session_id:
                pass
            else: return None
            return codex_remote_socket(command,context.config_root)
        actual_endpoint=endpoint_for(args)
        expected_endpoint=endpoint_for(expected[1:])
        try: selected=Path(context.backend_id).resolve(strict=False)
        except (OSError,RuntimeError,TypeError): return False
        return actual_endpoint is not None and expected_endpoint==selected and actual_endpoint==selected
    if context.harness.value=='opencode':
        return len(expected)>=6 and expected[1]=='attach' and expected[-3:]==['--session',context.session_id,'--mini'] and args==expected[1:]
    return False

def _tty_nr_matches_device(tty_nr:int,device:int)->bool:
    encoded=tty_nr & 0xffffffff
    return bool(encoded) and os.major(encoded)==os.major(device) and os.minor(encoded)==os.minor(device)

def _stat_has_tty_process(raw:str,device:int)->bool:
    tail=raw[raw.rfind(')')+2:].split()
    if len(tail)<5: raise ValueError('short proc stat')
    tty_nr=int(tail[4])
    return _tty_nr_matches_device(tty_nr,device)

def _tty_stats_empty(stats:list[str],device:int)->bool:
    try: return not any(_stat_has_tty_process(raw,device) for raw in stats)
    except (TypeError,ValueError,IndexError): return False

def codex_remote_socket(argv:list[str],codex_home:Path)->Path|None:
    """Resolve one explicit Codex --remote unix URI; never infer a default daemon.

    An empty unix:// URI is Codex's explicit selected-home endpoint. Nonempty
    paths must be absolute. Symlink aliases are canonicalized without searching
    other sockets or reading socket contents.
    """
    if not isinstance(argv,list) or not codex_home.is_absolute(): return None
    values=[]; i=0
    while i<len(argv):
        arg=argv[i]
        if not isinstance(arg,str): return None
        if arg=='--remote':
            if i+1>=len(argv): return None
            values.append(argv[i+1]); i+=2; continue
        if arg.startswith('--remote='):
            values.append(arg[len('--remote='):])
        i+=1
    if len(values)!=1: return None
    uri=values[0]
    if not isinstance(uri,str) or not uri.startswith('unix://'): return None
    raw=uri[len('unix://'): ]
    path=(codex_home/'app-server-control'/'app-server-control.sock') if raw=='' else Path(raw)
    if not path.is_absolute(): return None
    try: return path.resolve(strict=False)
    except (OSError,RuntimeError): return None

def _codex_proc_proof(process:dict[str,Any], *, proc_root:Path=Path('/proc')):
    """Read independent Linux process identity when Herdr omits foreground argv."""
    from .codex_backend import inspect_process, verify_process_pin
    pid=process.get('pid'); name=process.get('name'); cwd=process.get('cwd')
    if not isinstance(pid,int) or not isinstance(name,str) or not name:
        raise ValueError('Codex process identity is incomplete')
    expected_cwd=Path(cwd) if isinstance(cwd,str) and Path(cwd).is_absolute() else None
    proof=inspect_process(pid,expected_name=name,expected_cwd=expected_cwd,proc_root=proc_root)
    return verify_process_pin(proof,proc_root=proc_root)

def codex_backend_proof(process:dict[str,Any],codex_home:Path,*,proc_root:Path=Path('/proc'))->dict[str,object]:
    """Build bounded durable endpoint/process pins from one verified pane process.

    If native argv is unreadable, OS process metadata must still establish a
    default daemon launch. Explicit selection must resolve to its own endpoint.
    """
    from .codex_backend import select_endpoint
    proc=_codex_proc_proof(process,proc_root=proc_root)
    if proc.launch_mode=='no_daemon' or proc.launch_mode=='unknown':
        raise ValueError('Codex launch mode cannot be safely qualified')
    explicit=None
    if proc.launch_mode=='explicit':
        args=list(proc.argv or ()); values=[]; index=0
        while index<len(args):
            arg=args[index]
            if arg=='--remote':
                if index+1>=len(args): raise ValueError('explicit Codex endpoint is incomplete')
                values.append(args[index+1]); index+=2; continue
            if arg.startswith('--remote='): values.append(arg[len('--remote='):])
            index+=1
        if len(values)!=1 or not values[0].startswith('unix://'):
            raise ValueError('explicit Codex endpoint is unsupported or ambiguous')
        parsed=urlsplit(values[0])
        if parsed.netloc not in ('','localhost'):
            raise ValueError('remote Codex socket host is unsupported')
        explicit=(codex_home/'app-server-control'/'app-server-control.sock') if not parsed.path else Path(parsed.path)
        if not explicit.is_absolute(): raise ValueError('explicit Codex socket path must be absolute')
    pin=select_endpoint(codex_home,explicit)
    if process.get('argv'):
        herdr_endpoint=codex_remote_socket(process['argv'],codex_home)
        if proc.launch_mode=='explicit' and herdr_endpoint!=pin.target:
            raise ValueError('Herdr and OS process endpoint evidence disagree')
    return {'socket_alias':str(pin.alias),'socket_target':str(pin.target),
            'socket_identity':list(pin.socket_identity),'alias_identity':list(pin.alias_identity),
            'directory_identity':list(pin.directory_identity),'pid':proc.pid,'uid':proc.uid,
            'executable':str(proc.executable),'cwd':str(proc.cwd),'start_ticks':proc.start_ticks}

def revalidate_codex_backend_proof(proof:dict[str,Any],processes:list[dict[str,Any]],
                                   codex_home:Path,*,proc_root:Path=Path('/proc')) -> bool:
    """Revalidate selected socket incarnation and exact foreground process pin."""
    try:
        proc=next((p for p in processes if isinstance(p,dict) and p.get('pid')==proof.get('pid')),None)
        if proc is None: return False
        current=codex_backend_proof(proc,codex_home,proc_root=proc_root)
        return current==proof
    except (KeyError,TypeError,ValueError,OSError,RuntimeError): return False

def process_matches_attachment(process:dict[str,Any],expected:list[str],context:Any,
                               *,proc_root:Path=Path('/proc')) -> bool:
    """Match native attachment using Herdr argv or independently read /proc argv."""
    argv=process.get('argv')
    if isinstance(argv,list) and argv:
        if attachment_argv_matches(argv,expected,context): return True
    if context.harness.value!='codex': return False
    try:
        proof=_codex_proc_proof(process,proc_root=proc_root)
        return bool(proof.argv and attachment_argv_matches(list(proof.argv),expected,context))
    except (ValueError,OSError,RuntimeError): return False

class HerdrClient:
    def __init__(self, socket_path: Path | str, timeout: float = 5.0):
        self.socket_path=Path(socket_path); self.timeout=min(max(float(timeout),.1),5.0); self._ids=itertools.count(1); self.peer_identity=None; self._socket_fingerprint=None
    def request(self, method: str, params: dict[str,Any]) -> dict[str,Any]:
        if not self.socket_path.is_absolute(): raise HerdrError('socket path must be absolute')
        deadline=time.monotonic()+self.timeout; before=self.socket_fingerprint(); rid=str(next(self._ids)); payload=json.dumps({'id':rid,'method':method,'params':params},separators=(',',':')).encode()+b'\n'
        try:
            with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as s:
                s.settimeout(max(.01,deadline-time.monotonic())); s.connect(str(self.socket_path)); peer=self._peer_credentials(s)
                if peer is None or peer[0]!=os.getuid(): raise HerdrError('Herdr peer credentials unavailable or foreign')
                if self.peer_identity is not None and peer!=self.peer_identity: raise HerdrError('Herdr peer identity changed')
                self.peer_identity=peer; s.settimeout(max(.01,deadline-time.monotonic())); s.sendall(payload); data=bytearray()
                while b'\n' not in data:
                    remaining=deadline-time.monotonic()
                    if remaining<=0: raise TimeoutError('Herdr request deadline exceeded')
                    s.settimeout(remaining); part=s.recv(65536)
                    if not part: break
                    data.extend(part)
                    if len(data)>1_048_576: raise HerdrError('Herdr response exceeds limit')
            reply=json.loads(bytes(data).split(b'\n',1)[0])
            if self.socket_fingerprint()!=before: raise HerdrError('Herdr socket changed during request')
            if self._socket_fingerprint is not None and before!=self._socket_fingerprint: raise HerdrError('Herdr socket identity changed')
            self._socket_fingerprint=before
        except (OSError,TimeoutError,json.JSONDecodeError) as e: raise HerdrError('Herdr request failed') from e
        if not isinstance(reply,dict) or reply.get('id')!=rid: raise HerdrError('Herdr response ID mismatch')
        if 'error' in reply: raise HerdrError('Herdr rejected request')
        result=reply.get('result')
        if not isinstance(result,dict): raise HerdrError('malformed Herdr response')
        return result
    @staticmethod
    def _peer_credentials(sock:socket.socket)->tuple[int,int|None]|None:
        if hasattr(socket,'SO_PEERCRED'):
            import struct
            raw=sock.getsockopt(socket.SOL_SOCKET,socket.SO_PEERCRED,struct.calcsize('3i')); pid,uid,_=struct.unpack('3i',raw); return uid,pid
        if hasattr(sock,'getpeereid'):
            uid,_=sock.getpeereid(); return uid,None
        return None
    def socket_fingerprint(self)->tuple[int,int,int,int]:
        st=self.socket_path.lstat()
        if not stat.S_ISSOCK(st.st_mode) or st.st_uid!=os.getuid() or st.st_mode & 0o077: raise HerdrError('Herdr socket is not private and user-owned')
        return st.st_dev,st.st_ino,st.st_uid,stat.S_IMODE(st.st_mode)
    def server_identity(self)->str:
        if self.peer_identity is None: raise HerdrError('Herdr peer has not been observed')
        return json.dumps({'socket':self.socket_fingerprint(),'peer':self.peer_identity},separators=(',',':'))
    def snapshot(self) -> dict[str,Any]:
        r=self.request('session.snapshot',{})
        if r.get('type')!='session_snapshot': raise HerdrError('unexpected snapshot response')
        snap=r.get('snapshot')
        if not isinstance(snap,dict) or snap.get('protocol')!=22: raise HerdrError('protocol 22 snapshot unavailable')
        return snap
    def split(self,parent:Any,cwd:Path,env:dict[str,str]|None=None)->str:
        params={'direction':'right','target_pane_id':parent.pane_id,'workspace_id':parent.workspace_id,'cwd':str(cwd.resolve()),'focus':False}
        if env is not None:
            if set(env)!={'HARNESS_HERDR_STATE_ROOT'} or not Path(env['HARNESS_HERDR_STATE_ROOT']).is_absolute(): raise HerdrError('split accepts only the absolute integration state hint')
            params['env']=dict(env)
        r=self.request('pane.split',params)
        pane=r.get('pane')
        pane_info=pane if r.get('type')=='pane_info' and isinstance(pane,dict) else None
        pane=pane_info.get('pane_id') if pane_info else None
        if not isinstance(pane,str) or not pane or pane_info.get('workspace_id')!=parent.workspace_id or pane_info.get('tab_id')!=parent.tab_id or pane_info.get('focused') is not False: raise HerdrError('split did not acknowledge pane ID')
        return pane
    @staticmethod
    def safe_label(title:str|None,harness:str,session_id:str,limit:int=64)->str:
        raw=title or f'{harness} {session_id[:8]}'
        clean=''.join(c for c in raw if ord(c)>=32 and not 127<=ord(c)<=159)
        return clean[:max(1,limit)] or f'{harness} {session_id[:8]}'
    def process_info(self,pane_id:str)->dict[str,Any]:
        r=self.request('pane.process_info',{'pane_id':pane_id}); info=r.get('process_info')
        if r.get('type')!='pane_process_info' or not isinstance(info,dict) or info.get('pane_id')!=pane_id: raise HerdrError('process info does not identify requested pane')
        return info
    def verify_parent(self,parent:Any,backend_pid:int|None=None)->bool:
        try:
            snap=self.snapshot()
            if self.peer_identity is None or self.peer_identity[0]!=os.getuid() or parent.herdr_server_id!=self.server_identity(): return False
            pane=next((p for p in snap.get('panes',[]) if p.get('pane_id')==parent.pane_id),None)
            if not pane or pane.get('workspace_id')!=parent.workspace_id or pane.get('tab_id')!=parent.tab_id: return False
            ref=pane.get('agent_session')
            if not matches_agent_session_ref(ref,parent.context.session_id,getattr(parent,'session_path',None)): return False
            expected=parent.context.harness.value
            if expected not in str(ref.get('agent','')).lower() and expected not in str(ref.get('source','')).lower(): return False
            info=self.process_info(parent.pane_id); processes=info.get('foreground_processes',[])
            backend=parent.context.backend_id
            if expected=='opencode':
                if not isinstance(backend_pid,int) or backend_pid<=0: return False
                return any(p.get('pid')==backend_pid and 'opencode' in (p.get('name','')+' '+str(p.get('argv') or '')).lower() for p in processes)
            expected_socket=Path(backend).resolve(strict=False)
            proof=getattr(parent,'backend_proof',None)
            candidates=[p for p in processes if isinstance(p,dict) and
                        (Path(str(p.get('name',''))).name.lower() in {'codex','codex-cli'}
                         or (isinstance(p.get('argv'),list) and p.get('argv')
                             and Path(str(p['argv'][0])).name.lower() in {'codex','codex-cli'}))]
            if proof is not None:
                return (Path(str(proof.get('socket_target','')))==expected_socket
                        and revalidate_codex_backend_proof(dict(proof),candidates,parent.context.config_root))
            # Bootstrap may construct its first proof from the selected process;
            # callers must persist it before starting an observer.
            return any(Path(codex_backend_proof(p,parent.context.config_root)['socket_target'])==expected_socket
                       for p in candidates)
        except (HerdrError,OSError,AttributeError,ValueError,RuntimeError): return False
    def wait_for_attachment(self,pane_id:str,context:Any,backend_pid:int|None=None,timeout:float=5.0,*,expected_argv:list[str]|None=None,session_path:Path|str|None=None)->bool:
        if not expected_argv: return False
        deadline=time.monotonic()+min(max(timeout,0.0),5.0)
        while time.monotonic()<deadline:
            try:
                snap=self.snapshot(); pane=next((p for p in snap.get('panes',[]) if p.get('pane_id')==pane_id),None)
                ref=pane.get('agent_session') if pane else None
                if matches_agent_session_ref(ref,context.session_id,Path(session_path) if session_path else None) and context.harness.value in (str(ref.get('agent',''))+' '+str(ref.get('source',''))).lower():
                    info=self.process_info(pane_id); procs=info.get('foreground_processes',[])
                    if any(process_matches_attachment(proc,expected_argv,context) for proc in procs if isinstance(proc,dict)): return True
            except HerdrError: pass
            time.sleep(min(.1,max(0,deadline-time.monotonic())))
        return False
    def rename(self,pane_id:str,label:str)->None: self.request('pane.rename',{'pane_id':pane_id,'label':label})
    def send_text(self,pane_id:str,text:str)->None: self.request('pane.send_text',{'pane_id':pane_id,'text':text})
    def send_keys(self,pane_id:str,keys:list[str])->None: self.request('pane.send_keys',{'pane_id':pane_id,'keys':keys})
    def close(self,pane_id:str)->None: self.request('pane.close',{'pane_id':pane_id})
