import json
import tempfile
import unittest
from pathlib import Path
from harness_herdr_hooks.model import Context, Harness, ParentBinding, SubagentDestination, destination_from_dict, destination_to_dict
from harness_herdr_hooks.state import StateStore, save_binding, load_existing_binding
from harness_herdr_hooks.model import Session, Lifecycle, session_to_dict, parent_to_dict

class SubagentDestinationStateTests(unittest.TestCase):
    def test_binding_destination_optional_and_strict(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); ctx=Context(Harness.CODEX,'p',root,root,root,'b','main','inc')
            parent=ParentBinding(ctx,'server','ws','original','mainpane')
            child_ctx=Context(Harness.CODEX,'p',root,root,root,'b','child','inc')
            child=Session(child_ctx,'main',None,root,Lifecycle.RUNNING,True,1.0)
            record={'parent':parent_to_dict(parent),'child':session_to_dict(child),'pane_id':'p1','backend_pid':None,'server_socket':None,'entrypoint':None,'shell_pid':None}
            save_binding(root,'b1',record)
            self.assertNotIn('destination',load_existing_binding(root,'b1'))
            destination=SubagentDestination(ctx,'server','ws','managed','g1','initial','p1')
            record['destination']=destination_to_dict(destination)
            save_binding(root,'b2',record)
            self.assertEqual(destination_from_dict(load_existing_binding(root,'b2')['destination']),destination)
            record['destination']['tab_id']=''
            with self.assertRaises(ValueError): save_binding(root,'b3',record)

    def test_destination_requires_original_root_and_subagent_only(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); ctx=Context(Harness.CODEX,'p',root,root,root,'b','main','inc')
            parent=ParentBinding(ctx,'server','ws','original','mainpane')
            child=Session(Context(Harness.CODEX,'p',root,root,root,'b','child','inc'), 'main',None,root,Lifecycle.RUNNING,True,1.0)
            base={'parent':parent_to_dict(parent),'child':session_to_dict(child),'pane_id':'childpane','backend_pid':None,'server_socket':None,'entrypoint':None,'shell_pid':None,'kind':'subagent','generation':'child-turn'}
            dest=destination_to_dict(SubagentDestination(ctx,'server','ws','managed','g1','rootpane','childpane'))
            save_binding(root,'good',{**base,'destination':dest})
            for field,value in [('workspace_id','elsewhere'),('herdr_server_id','other'),('child_pane_id','otherpane')]:
                bad={**dest,field:value}
                with self.subTest(field=field), self.assertRaises(ValueError): save_binding(root,'bad'+field,{**base,'destination':bad})
            independent={**base,'kind':'independent','destination':dest}
            with self.assertRaises(ValueError): save_binding(root,'independent',independent)
            standalone_child = {**base, 'child': session_to_dict(Session(
                child.context, 'main', None, root, Lifecycle.RUNNING, True, 1.0,
                kind='standalone'))}
            with self.assertRaises(ValueError): save_binding(root,'standalone-child',{**standalone_child,'destination':dest})
            foreign_root={**dest,'root_context':{**dest['root_context'],'session_id':'nested'}}
            with self.assertRaises(ValueError): save_binding(root,'nestedroot',{**base,'destination':foreign_root})
            control={**dest,'generation':'g\n1'}
            with self.assertRaises(ValueError): destination_from_dict(control)

class OperationLockTests(unittest.TestCase):
    def test_state_operation_lock_is_nonblocking_and_distinct(self):
        with tempfile.TemporaryDirectory() as d:
            store=StateStore(Path(d),'x')
            with store.operation('root-op'):
                with self.assertRaises(BlockingIOError):
                    with store.operation('root-op'): pass
            with store.operation('other-op'): pass
