"""Minimal, credential-free environment for one selected harness profile."""
from __future__ import annotations
import os
from pathlib import Path
from typing import Mapping
from .model import Context,Harness

_COMMON={'HOME','PATH','LANG','LC_ALL','LC_CTYPE','TERM','COLORTERM','TMPDIR','XDG_RUNTIME_DIR','SSH_AUTH_SOCK'}
_PANE_MARKERS={'HERDR_BIN_PATH','HERDR_ENV','HERDR_PANE_ID','HERDR_SOCKET_PATH','HERDR_TAB_ID','HERDR_WORKSPACE_ID'}

def _xdg_base(app_root:Path,app_name:str)->Path:
    root=app_root.resolve()
    return root.parent if root.name==app_name else root

def child_environment(context:Context,source:Mapping[str,str]|None=None,pane_markers:Mapping[str,str]|None=None)->dict[str,str]:
    """Copy only OS/terminal values; derive selected-profile roots from Context.

    `pane_markers` must be obtained from the newly split pane, never the parent.
    Credentials and arbitrary CODEX_/OPENCODE_ values are deliberately excluded.
    """
    env=dict(os.environ if source is None else source)
    result={k:v for k,v in env.items() if k in _COMMON}
    if context.harness==Harness.CODEX:
        result['CODEX_HOME']=str(context.config_root.resolve())
    else:
        result['OPENCODE_CONFIG_DIR']=str(context.config_root.resolve())
        result['XDG_DATA_HOME']=str(_xdg_base(context.data_root,'opencode'))
        result['XDG_STATE_HOME']=str(_xdg_base(context.state_root,'opencode'))
    if pane_markers:
        result.update({k:v for k,v in pane_markers.items() if k in _PANE_MARKERS})
    return result
