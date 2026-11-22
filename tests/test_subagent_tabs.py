import unittest
import subprocess
import sys
from pathlib import Path

from harness_herdr_hooks.model import Context, Harness, SubagentDestination
from harness_herdr_hooks.tabs import SubagentTabManager, OperationBusy
from harness_herdr_hooks.state import StateStore


class SubagentTabManagerTests(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.context = Context(Harness.CODEX, 'p', self.root, self.root, self.root, 'b', 'main', 'inc')
        self.store = StateStore(self.root, 'child-state')
        self.anchor = self.root / 'canonical'
        self.manager = SubagentTabManager(self.store, self.context, 'server', 'workspace', _workspace_anchor=self.anchor)

    def tearDown(self): self.tmp.cleanup()

    def test_label_is_bounded_sanitized_and_keeps_identity_suffix(self):
        label = self.manager.format_label('Root\n\x1b[31m' + 'x' * 200, self.context.session_id)
        self.assertTrue(label.startswith('Subagents: Root'))
        self.assertTrue(label.endswith('[main]'))
        self.assertLessEqual(len(label), 64)
        self.assertNotIn('\n', label)
        self.assertNotIn('\x1b', label)

    def test_claim_requires_explicit_ack_and_persists_unknown_creation(self):
        with self.manager.operations() as token:
            reservation = self.manager.reserve_label(token, 'Root', 'main', 'gen-1')
            claim = self.manager.begin_create(token, reservation, 'gen-1')
            self.manager.mark_unknown(token, claim)
        with self.manager.root_store.locked() as state:
            self.assertEqual(state['subagent_tab']['status'], 'unknown')
        with self.manager.operations() as token:
            reservation2 = self.manager.reserve_label(token, 'Root', 'main', 'gen-1')
            self.assertEqual(reservation2.label, reservation.label)
            with self.assertRaises(ValueError): self.manager.begin_create(token, reservation2, 'gen-1')

    def test_released_label_is_reallocated_only_after_collision_check(self):
        with self.manager.operations() as token:
            first = self.manager.reserve_label(token, 'Root', 'abcdefgh-one', 'gen-1')
            self.manager._release_prior_labels(token, 'gen-1', 'renamed')
        other_ctx = Context(Harness.CODEX, 'p', self.root, self.root, self.root, 'b', 'main-2', 'inc')
        other = SubagentTabManager(self.store, other_ctx, 'server', 'workspace', _workspace_anchor=self.anchor)
        with other.operations() as other_token:
            occupied = other.reserve_label(other_token, 'Root', 'abcdefgh-two', 'gen-2')
        with self.manager.operations() as token:
            again = self.manager.reserve_label(token, 'Root', 'abcdefgh-one', 'gen-1')
        self.assertNotEqual(again.label, occupied.label)
        self.assertNotEqual(again.label, first.label)

    def test_missing_or_empty_title_preserves_current_label(self):
        class Client:
            def snapshot(self): raise AssertionError('must not inspect transport')
        with self.manager.operations() as token:
            reservation = self.manager.reserve_label(token, 'Root', 'main', 'gen-1')
            claim = self.manager.begin_create(token, reservation, 'gen-1')
            self.manager.commit_create(token, claim, tab_id='tab', initial_pane_id='pane')
            self.assertFalse(self.manager.sync_title(token, Client(), None, 'main'))
            self.assertFalse(self.manager.sync_title(token, Client(), '  ', 'main'))
        with self.manager.root_store.locked() as data:
            self.assertEqual(data['subagent_tab']['label'], reservation.label)

    def test_label_budget_exhaustion_fails_closed(self):
        with self.manager.operations() as token:
            with self.assertRaisesRegex(ValueError, 'cannot preserve identity'):
                self.manager.format_label('title', 'main', limit=10)

    def test_identical_full_session_ids_in_distinct_contexts_get_distinct_labels(self):
        other_ctx = Context(Harness.CODEX, 'other-project', self.root, self.root, self.root, 'b', 'main', 'inc')
        other = SubagentTabManager(self.store, other_ctx, 'server', 'workspace', _workspace_anchor=self.anchor)
        with self.manager.operations() as a:
            first = self.manager.reserve_label(a, 'Same', 'identical-session', 'g1')
        with other.operations() as b:
            second = other.reserve_label(b, 'Same', 'identical-session', 'g2')
        self.assertNotEqual(first.label, second.label)

    def test_cross_profile_roots_and_harnesses_share_label_registry(self):
        for harness in (Harness.CODEX, Harness.OPENCODE):
            first_root = Context(harness, 'one', self.root, self.root, self.root, 'b1', 'same-root', 'i1')
            second_root = Context(harness, 'two', self.root, self.root, self.root, 'b2', 'same-root', 'i2')
            first = SubagentTabManager(StateStore(self.root / 'profile-one', 'state'), first_root,
                                       'server', 'workspace', _workspace_anchor=self.anchor)
            second = SubagentTabManager(StateStore(self.root / 'profile-two', 'state'), second_root,
                                        'server', 'workspace', _workspace_anchor=self.anchor)
            with first.operations() as token:
                a = first.reserve_label(token, 'Identical', 'abcdefgh-full-id', 'one')
            with second.operations() as token:
                b = second.reserve_label(token, 'Identical', 'abcdefgh-full-id', 'two')
            self.assertNotEqual(a.label, b.label)
            self.assertTrue(a.label.startswith('Subagents: Identical [abcdefgh'))
            self.assertTrue(b.label.startswith('Subagents: Identical [abcdefgh'))

    def test_same_logical_root_cannot_split_across_physical_state_roots(self):
        first = SubagentTabManager(StateStore(self.root / 'profile-a', 'state'), self.context,
                                   'server', 'workspace', _workspace_anchor=self.anchor)
        second = SubagentTabManager(StateStore(self.root / 'profile-b', 'state'), self.context,
                                    'server', 'workspace', _workspace_anchor=self.anchor)
        with first.operations() as token:
            reservation = first.reserve_label(token, 'Root', 'main', 'g1')
            claim = first.begin_create(token, reservation, 'g1')
            first.commit_create(token, claim, tab_id='tab-1', initial_pane_id='pane-1')
        # Confirmed removal releases the label, but never transfers root
        # ownership to a different physical root-state namespace.
        with first.operations() as token:
            first.release_after_removed(token, tab_id='tab-1')
        with self.assertRaisesRegex(ValueError, 'different physical state namespace'):
            with second.operations():
                pass

    def test_same_physical_state_namespace_allows_root_reuse(self):
        first = SubagentTabManager(StateStore(self.root / 'profile-a', 'state-one'), self.context,
                                   'server', 'workspace', _workspace_anchor=self.anchor)
        second = SubagentTabManager(StateStore(self.root / 'profile-a', 'state-two'), self.context,
                                    'server', 'workspace', _workspace_anchor=self.anchor)
        with first.operations() as token:
            reservation = first.reserve_label(token, 'Root', 'main', 'g1')
            claim = first.begin_create(token, reservation, 'g1')
            first.commit_create(token, claim, tab_id='tab-1', initial_pane_id='pane-1')
        with second.operations() as token:
            self.assertEqual(second.destination(token).tab_id, 'tab-1')

    def test_workspace_possible_creation_blocks_when_local_root_claim_is_missing(self):
        with self.manager.operations() as token:
            reservation = self.manager.reserve_label(token, 'Root', 'main', 'g1')
            with token.workspace_store.locked() as data:
                data['subagent_tabs']['reservations'][reservation.reservation_id]['status'] = 'possible'
            with self.assertRaisesRegex(ValueError, 'possible creation reservation'):
                self.manager.begin_create(token, reservation, 'g1')

    def test_failed_rename_retains_old_and_new_possible_labels(self):
        class Client:
            def snapshot(self): return {'tabs':[{'tab_id':'tab','workspace_id':'workspace'}]}
            def server_identity(self): return 'server'
            def rename_subagent_tab(self, *args): raise RuntimeError('lost rename acknowledgement')
        with self.manager.operations() as token:
            original = self.manager.reserve_label(token, 'Root', 'main', 'gen-1')
            claim = self.manager.begin_create(token, original, 'gen-1')
            self.manager.commit_create(token, claim, tab_id='tab', initial_pane_id='pane')
            with self.assertRaisesRegex(RuntimeError, 'lost rename'):
                self.manager.sync_title(token, Client(), 'Renamed', 'main')
        with self.manager.workspace_store.locked() as data:
            active = {v['label'] for v in data['subagent_tabs']['reservations'].values()
                      if v.get('root_key') == self.manager.root_key and v.get('status') != 'released'}
        self.assertIn(original.label, active)
        self.assertGreaterEqual(len(active), 2)

    def test_ack_and_child_binding_pins_destination_without_parent_rewrite(self):
        with self.manager.operations() as token:
            reservation = self.manager.reserve_label(token, 'Root', 'main', 'gen-1')
            claim = self.manager.begin_create(token, reservation, 'gen-1')
            destination = self.manager.commit_create(token, claim, tab_id='tab', initial_pane_id='pane')
            child = self.manager.bind_child(token, destination, child_pane_id='child-pane')
        self.assertEqual(child.tab_id, 'tab')
        self.assertEqual(child.initial_pane_id, 'pane')
        self.assertEqual(child.child_pane_id, 'child-pane')
        self.assertEqual(child.root_context, self.context)

    def test_workspace_then_root_locks_are_nonblocking(self):
        with self.manager.operations():
            with self.assertRaises(OperationBusy):
                with self.manager.operations(): pass

    def test_old_token_is_invalid_after_operation(self):
        with self.manager.operations() as token: pass
        with self.assertRaises(ValueError): self.manager.destination(token)

    def test_new_generation_cannot_replace_live_or_unknown_claim(self):
        with self.manager.operations() as token:
            reservation = self.manager.reserve_label(token, 'Root', 'main', 'gen-1')
            claim = self.manager.begin_create(token, reservation, 'gen-1')
            self.manager.mark_unknown(token, claim)
            second = self.manager.reserve_label(token, 'Root two', 'main', 'gen-2')
            with self.assertRaisesRegex(ValueError, 'unresolved, still live'):
                self.manager.begin_create(token, second, 'gen-2')

    def test_collision_reserves_full_labels_and_grows_id(self):
        # Same context with independently persisted roots is represented in
        # labels by a distinct generation reservation, so use a separate full
        # root identity sharing the first eight session-ID characters.
        root3 = Context(Harness.CODEX, 'p', self.root, self.root, self.root, 'b', 'main-2', 'inc')
        other = SubagentTabManager(self.store, root3, 'server', 'workspace', _workspace_anchor=self.anchor)
        with self.manager.operations() as a:
            first = self.manager.reserve_label(a, 'Same', 'abcdefgh111', 'g1')
        with other.operations() as b:
            second = other.reserve_label(b, 'Same', 'abcdefgh222', 'g2')
        self.assertNotEqual(first.label, second.label)
        self.assertTrue(second.label.endswith('[abcdefgh2]'))

    def test_lock_contention_is_real_across_processes(self):
        with self.manager.operations():
            code = "from pathlib import Path; from harness_herdr_hooks.state import StateStore; from harness_herdr_hooks.model import Context,Harness; from harness_herdr_hooks.tabs import SubagentTabManager; import sys; root=Path(sys.argv[1]); ctx=Context(Harness.CODEX,'other',root,root,root,'b','main','inc'); m=SubagentTabManager(StateStore(root,'child-state'),ctx,'server','workspace',_workspace_anchor=Path(sys.argv[2]));\ntry:\n  with m.operations(): pass\nexcept Exception as e:\n  from harness_herdr_hooks.tabs import OperationBusy\n  if isinstance(e,OperationBusy): raise SystemExit(7)\n  raise\nraise SystemExit(0)"
            env = dict(__import__('os').environ, PYTHONPATH=str(Path(__file__).resolve().parents[1] / 'src'))
            proc = subprocess.run([sys.executable, '-c', code, str(self.root / 'other-profile'), str(self.anchor)], env=env,
                                  timeout=3, capture_output=True)
            self.assertEqual(proc.returncode, 7, proc.stderr.decode())

    def test_multiprocess_create_create_race_calls_transport_once(self):
        import os, tempfile
        count_file = self.root / 'create-count'
        barrier = self.root / 'barrier'
        code = r'''import fcntl, os, sys, time
from pathlib import Path
from harness_herdr_hooks.model import Context, Harness
from harness_herdr_hooks.state import StateStore
from harness_herdr_hooks.tabs import SubagentTabManager, OperationBusy
root=Path(sys.argv[1]); count=Path(sys.argv[2]); barrier=Path(sys.argv[3]); anchor=Path(sys.argv[4])
ctx=Context(Harness.CODEX,'p',root,root,root,'b','main','inc')
manager=SubagentTabManager(StateStore(root,'child-state'),ctx,'server','workspace',_workspace_anchor=anchor)
with open(barrier,'a') as f:
 fcntl.flock(f,fcntl.LOCK_EX); f.write('x'); f.flush(); fcntl.flock(f,fcntl.LOCK_UN)
deadline=time.time()+3
while time.time()<deadline and (not barrier.exists() or len(barrier.read_text())<2): time.sleep(.01)
class Client:
 def create_subagent_tab(self,*args,**kwargs):
  with open(count,'a') as f:
   fcntl.flock(f,fcntl.LOCK_EX); f.write('create\n'); f.flush(); fcntl.flock(f,fcntl.LOCK_UN)
  return 'tab','pane'
deadline=time.time()+3
while True:
 try:
  with manager.operations() as token: manager.select_create(token,Client(),root,'Root','main','generation')
  break
 except OperationBusy:
  if time.time()>deadline: raise
  time.sleep(.01)
'''
        env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1] / 'src'))
        args = [sys.executable, '-c', code, str(self.root), str(count_file), str(barrier), str(self.anchor)]
        procs = [subprocess.Popen(args, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE) for _ in range(2)]
        for proc in procs:
            out, err = proc.communicate(timeout=5)
            self.assertEqual(proc.returncode, 0, (out + err).decode())
        self.assertEqual(count_file.read_text().splitlines(), ['create'])


if __name__ == '__main__': unittest.main()
