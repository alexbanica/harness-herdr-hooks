import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from harness_herdr_hooks.adapters.codex import CodexRuntimeAdapter
from harness_herdr_hooks.model import Context, Harness, ParentBinding, Lifecycle
from harness_herdr_hooks.state import StateStore
from harness_herdr_hooks.model import CreationProof, Session
from harness_herdr_hooks.coordinator import Coordinator, discovery_namespace
from types import SimpleNamespace
import hashlib


class Proxy:
    def __init__(self, rows):
        self.rows = {row['id']: row for row in rows}
        self.calls = []

    def request(self, method, params):
        self.calls.append((method, dict(params)))
        if method == 'thread/loaded/list':
            return {'data': list(self.rows), 'nextCursor': None}
        if method == 'thread/list':
            return {'data': [], 'nextCursor': None}
        if method == 'thread/read':
            return {'thread': self.rows[params['threadId']]}
        raise AssertionError(method)


def event(parent='parent', child='standalone', turn='turn', item='item'):
    return {'type': 'event_msg', 'payload': {'type': 'item_completed', 'thread_id': parent,
        'turn_id': turn, 'item': {'type': 'McpToolCall', 'id': item, 'server': 'codex_tui',
        'tool': 'create_thread', 'status': 'completed', 'result': {'isError': False,
        'content': [{'type': 'text', 'text': json.dumps({'threadId': child})}]}}}}


class StandaloneDiscoveryTests(unittest.TestCase):
    def test_simultaneous_displays_keep_independent_rollout_cursors(self):
        for first_pane in ("left", "right"):
            with self.subTest(first_pane=first_pane), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                profile = root / "profile"
                rollout = profile / "sessions" / "parent.jsonl"
                rollout.parent.mkdir(parents=True)
                rollout.write_text(json.dumps({"type": "session_meta", "payload": {"id": "parent"}}) + "\n")
                context = Context(Harness.CODEX, str(profile), profile, profile, profile,
                                  "/socket", "parent", "1:2:3")
                proxy = Proxy([{"id": "parent", "path": str(rollout)}])
                displays = {}
                for pane_id in ("left", "right"):
                    parent = ParentBinding(context, "server", "work", pane_id + "-tab", pane_id,
                                           session_path=rollout, backend_proof={"client_generation": pane_id})
                    adapter = object.__new__(CodexRuntimeAdapter)
                    adapter.context, adapter.task_store_root, adapter.proxy = context, root / "state", proxy
                    adapter.task_store_namespace = discovery_namespace(parent)
                    displays[pane_id] = (parent, adapter)
                    self.assertEqual(list(adapter.sessions(parent)), [])
                with rollout.open("a") as stream:
                    stream.write(json.dumps(event()) + "\n")
                proxy.rows["standalone"] = {"id": "standalone", "cwd": "/work",
                                             "status": {"type": "active", "activeFlags": []}}
                for pane_id in (first_pane, "right" if first_pane == "left" else "left"):
                    parent, adapter = displays[pane_id]
                    discovered = list(adapter.sessions(parent))
                    self.assertEqual([child.context.session_id for child in discovered], ["standalone"])
                    store = StateStore(adapter.task_store_root, adapter.task_store_namespace)
                    self.assertEqual(store.task_discovery()["authority"]["destination"]["pane_id"], pane_id)

    def test_reader_adapter_poll_bounds_overflow_and_resumes_after_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); profile = root / 'profile'; sessions = profile / 'sessions'
            sessions.mkdir(parents=True); parent_file = sessions / 'parent.jsonl'
            parent_file.write_text(json.dumps({'type': 'session_meta', 'payload': {'id': 'parent'}}) + '\n')
            context = Context(Harness.CODEX, str(profile), profile, profile, profile,
                              '/socket', 'parent', '1:2:3')
            parent = ParentBinding(context, 'server', 'ws', 'tab', 'pane', session_path=parent_file)
            state_root = root / 'state'
            proxy = Proxy([{'id': 'parent', 'path': str(parent_file)}])

            def adapter():
                value = object.__new__(CodexRuntimeAdapter)
                value.context = context; value.task_store_root = state_root; value.proxy = proxy
                return value

            first = adapter()
            self.assertEqual(list(first.sessions(parent)), [])  # Bind at parent-file EOF.
            with parent_file.open('a') as out:
                for index in range(129):
                    out.write(json.dumps(event(child=f'child-{index}', turn=f'turn-{index}',
                                               item=f'item-{index}')) + '\n')
            for index in range(129):
                proxy.rows[f'child-{index}'] = {
                    'id': f'child-{index}', 'cwd': '/work',
                    'status': {'type': 'active', 'activeFlags': []}}

            self.assertEqual(len(list(first.sessions(parent))), 128)
            store = StateStore(state_root, context.key()[:32])
            first_state = store.task_discovery()
            self.assertEqual(len(first_state['pending']), 128)
            self.assertEqual(first_state['cursor']['offset'], parent_file.stat().st_size)
            self.assertEqual(len({item['item_id'] for item in first_state['pending']}), 128)
            self.assertEqual(first_state['outcomes'][-1]['child_id'], 'bounded-overflow')
            # The retained evidence is the bounded discovery cursor and outcome,
            # not a user-facing runtime status projection.
            self.assertEqual(first_state['outcomes'][-1]['status'], 'rejected')
            self.assertNotIn('content', json.dumps(first_state))

            restarted = adapter()
            self.assertEqual(len(list(restarted.sessions(parent))), 128)
            second_state = store.task_discovery()
            self.assertEqual(len(second_state['pending']), 128)
            self.assertEqual({item['item_id'] for item in second_state['pending']},
                             {f'item-{index}' for index in range(128)})
            self.assertEqual(second_state['cursor'], first_state['cursor'])

            # Drain the deferred batch, then prove a later append is read and
            # verified through the same adapter path.
            for candidate in list(second_state['pending']):
                store.update_task_candidate(candidate['event_key'], status='rejected', now=10)
            proxy.rows['later-child'] = {
                'id': 'later-child', 'cwd': '/work',
                'status': {'type': 'active', 'activeFlags': []}}
            with parent_file.open('a') as out:
                out.write(json.dumps(event(child='later-child', turn='later-turn',
                                           item='later-item')) + '\n')
            later_sessions = list(restarted.sessions(parent))
            self.assertEqual(len(later_sessions), 1)
            self.assertEqual(later_sessions[0].context.session_id, 'later-child')
            self.assertEqual(later_sessions[0].lifecycle, Lifecycle.RUNNING)
            final_state = store.task_discovery()
            self.assertEqual([item['item_id'] for item in final_state['pending']], ['later-item'])
            self.assertGreater(final_state['cursor']['offset'], second_state['cursor']['offset'])

    def _attached_replay_fixture(self, root, creation_cwd=None):
        root = Path(root); profile = root / 'profile'; sessions = profile / 'sessions'
        sessions.mkdir(parents=True); parent_file = sessions / 'parent.jsonl'
        parent_file.write_text(json.dumps({'type': 'session_meta', 'payload': {'id': 'parent'}}) + '\n')
        context = Context(Harness.CODEX, str(profile), profile, profile, profile,
                          '/socket', 'parent', '1:2:3')
        parent = ParentBinding(context, 'server', 'ws', 'tab', 'pane', session_path=parent_file)
        child_file = sessions / 'standalone.jsonl'; child_file.write_text('')
        proxy = Proxy([{'id': 'parent', 'path': str(parent_file)},
                       {'id': 'standalone', 'path': str(child_file), 'cwd': '/work/dir',
                        'name': 'saved title', 'status': {'type': 'active', 'activeFlags': []}}])
        adapter = object.__new__(CodexRuntimeAdapter); adapter.context = context
        adapter.task_store_root = root / 'state'; adapter.proxy = proxy
        list(adapter.sessions(parent))  # initial EOF bind
        record = event()
        if creation_cwd is not None:
            record['payload']['item']['result']['content'][0]['text'] = json.dumps(
                {'threadId': 'standalone', 'cwd': creation_cwd})
        with parent_file.open('a') as out: out.write(json.dumps(record) + '\n')
        child, = list(adapter.sessions(parent))
        store = StateStore(root / 'state', context.key()[:32]); store.establish_baseline(set())
        from harness_herdr_hooks.model import parent_to_dict, session_to_dict
        from harness_herdr_hooks.state import save_binding
        class Runtime:
            opened = 0
            closed = False
            title_updates = []
            def verify_parent(self, p): return p == parent
            def find_existing_pane(self, p, c): return None
            def can_attach_now(self, p, c): return True
            def open_and_attach(self, p, c, binding):
                self.opened += 1
                save_binding(adapter.task_store_root, binding, {
                    'parent': parent_to_dict(p), 'child': session_to_dict(c),
                    'pane_id': 'pane', 'backend_pid': None, 'server_socket': None,
                    'entrypoint': None, 'shell_pid': None, 'kind': 'standalone',
                    'ownership': 'created', 'generation': c.creation_proof.turn_id + ':' + c.creation_proof.item_id,
                    'turn_id': c.creation_proof.turn_id,
                    'outcome': {'status': 'attached', 'pid': None}})
                return True
            def owned_pane_state(self, p, c, binding):
                if self.closed: return 'closed'
                return 'live' if self.opened else 'unknown'
            def update_title(self, binding, title): self.title_updates.append((binding, title))

        runtime = Runtime(); coordinator = Coordinator(store, runtime)
        self.assertEqual(coordinator.handle(parent, child).decision.value, 'attached')
        return context, parent, child, adapter, proxy, store, runtime, coordinator

    def test_attached_replay_preserves_id_only_and_normalized_optional_cwd_pins(self):
        for creation_cwd in (None, '/work/./dir'):
            with self.subTest(creation_cwd=creation_cwd), tempfile.TemporaryDirectory() as tmp:
                context, parent, original, adapter, _proxy, store, runtime, coordinator = \
                    self._attached_replay_fixture(tmp, creation_cwd)
                replayed = list(adapter.sessions(parent))
                self.assertEqual(len(replayed), 1)
                child = replayed[0]
                self.assertEqual(child.context.session_id, original.context.session_id)
                self.assertEqual(child.title, 'saved title')
                self.assertEqual(child.creation_proof.cwd_sha256, original.creation_proof.cwd_sha256)
                binding_id = store.record(child.context.key())['binding_id']
                from harness_herdr_hooks.state import load_existing_binding
                saved = load_existing_binding(adapter.task_store_root, binding_id)
                self.assertEqual(saved['child']['creation_proof'].get('cwd_sha256'),
                                 original.creation_proof.cwd_sha256)
                self.assertEqual(coordinator.handle(parent, child).decision.value, 'attached')
                runtime.closed = True
                self.assertEqual(coordinator.handle(parent, child).decision.value, 'skip')
                self.assertEqual(store.record(child.context.key())['status'], 'suppressed')
                self.assertEqual(runtime.opened, 1)

    def test_reused_binding_without_wrapper_outcome_replays_and_updates_title(self):
        with tempfile.TemporaryDirectory() as tmp:
            context, parent, original, adapter, proxy, store, runtime, coordinator = \
                self._attached_replay_fixture(tmp)
            record = store.record(original.context.key())
            binding_id = record['binding_id']
            event_key = record['standalone_event_key']
            from harness_herdr_hooks.state import load_existing_binding, binding_is_close_owned
            saved = load_existing_binding(adapter.task_store_root, binding_id)
            saved.pop('outcome', None)
            saved['ownership'] = 'reused'
            binding_path = adapter.task_store_root / 'harness-herdr-hooks' / 'bindings' / (binding_id + '.json')
            binding_path.write_text(json.dumps(saved))  # NativeRuntime reuse bindings have no wrapper outcome.
            self.assertTrue(store.reconcile_standalone(
                original.context.key(), event_key, binding_id, 'attached', ownership='reused'))
            self.assertFalse(binding_is_close_owned(
                load_existing_binding(adapter.task_store_root, binding_id)))

            proxy.rows['standalone']['name'] = 'updated native title'
            replayed, = list(adapter.sessions(parent))
            self.assertEqual(replayed.title, 'updated native title')
            self.assertEqual(coordinator.handle(parent, replayed).decision.value, 'attached')
            self.assertEqual(store.record(original.context.key())['status'], 'attached')
            self.assertEqual(store.record(original.context.key())['ownership'], 'reused')
            self.assertEqual(load_existing_binding(adapter.task_store_root, binding_id)['ownership'], 'reused')
            self.assertEqual(runtime.title_updates[-1], (binding_id, 'updated native title'))
            self.assertEqual(runtime.opened, 1)

            runtime.closed = True
            self.assertEqual(coordinator.handle(parent, replayed).decision.value, 'skip')
            self.assertEqual(store.record(original.context.key())['status'], 'suppressed')

    def test_created_binding_without_attached_outcome_does_not_replay(self):
        with tempfile.TemporaryDirectory() as tmp:
            _context, parent, original, adapter, _proxy, store, _runtime, _coordinator = \
                self._attached_replay_fixture(tmp)
            record = store.record(original.context.key())
            binding_id = record['binding_id']
            from harness_herdr_hooks.state import load_existing_binding
            saved = load_existing_binding(adapter.task_store_root, binding_id)
            saved.pop('outcome', None)
            binding_path = adapter.task_store_root / 'harness-herdr-hooks' / 'bindings' / (binding_id + '.json')
            binding_path.write_text(json.dumps(saved))
            self.assertEqual(list(adapter.sessions(parent)), [])

    def test_replay_rejects_changed_binding_context_and_foreign_native_ids(self):
        for mutation in ('binding', 'context', 'native_child', 'native_parent'):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as tmp:
                context, parent, child, adapter, proxy, store, _runtime, _coordinator = \
                    self._attached_replay_fixture(tmp)
                binding_id = store.record(child.context.key())['binding_id']
                from harness_herdr_hooks.state import load_existing_binding, save_binding
                if mutation == 'binding':
                    saved = load_existing_binding(adapter.task_store_root, binding_id)
                    saved['child']['context']['session_id'] = 'foreign'
                    saved['child']['creation_proof']['child_id'] = 'foreign'
                    save_binding(adapter.task_store_root, binding_id,
                                 {k: v for k, v in saved.items() if k != 'schema'})
                elif mutation == 'context':
                    saved = load_existing_binding(adapter.task_store_root, binding_id)
                    saved['child']['context']['backend_instance'] = 'other'
                    save_binding(adapter.task_store_root, binding_id,
                                 {k: v for k, v in saved.items() if k != 'schema'})
                elif mutation == 'native_child':
                    proxy.rows['standalone']['id'] = 'foreign'
                else:
                    proxy.rows['parent']['id'] = 'foreign'
                self.assertEqual(list(adapter.sessions(parent)), [])

    def test_parent_file_failures_publish_bounded_runtime_reasons(self):
        for mode, expected in (("missing", "parent_file_missing"),
                               ("mismatch", "parent_file_mismatch"),
                               ("provider", "metadata_unavailable")):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp); profile = root / "profile"; sessions = profile / "sessions"
                sessions.mkdir(parents=True)
                actual_file = sessions / "parent.jsonl"
                actual_file.write_text(json.dumps({"type": "session_meta", "payload": {"id": "parent"}}) + "\n")
                context = Context(Harness.CODEX, str(profile), profile, profile, profile,
                                  "/socket", "parent", "1:2:3")
                parent = ParentBinding(context, "server", "ws", "tab", "pane",
                                       session_path=None if mode == "missing" else actual_file)
                path = sessions / "gone.jsonl" if mode == "missing" else actual_file
                if mode == "mismatch":
                    path = sessions / "other.jsonl"
                    path.write_text(json.dumps({"type": "session_meta", "payload": {"id": "parent"}}) + "\n")
                adapter = object.__new__(CodexRuntimeAdapter); adapter.context = context
                adapter.task_store_root = root / "state"
                adapter.proxy = Proxy([{"id": "parent", "path": str(path)}])
                if mode == "provider":
                    adapter._read_thread = lambda _ident: (_ for _ in ()).throw(OSError("private provider detail"))
                list(adapter.sessions(parent))
                discovery = StateStore(root / "state", context.key()[:32]).task_discovery()
                self.assertEqual(discovery["pending"], [])
                self.assertEqual(discovery["outcomes"], [])

    def test_missing_native_cwd_defers_and_relative_native_cwd_rejects_candidate(self):
        for cwd in (None, 'relative/work'):
            with self.subTest(cwd=cwd), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp); profile = root / 'profile'; sessions = profile / 'sessions'
                sessions.mkdir(parents=True); parent_file = sessions / 'parent.jsonl'
                parent_file.write_text(json.dumps({'type': 'session_meta', 'payload': {'id': 'parent'}}) + '\n')
                context = Context(Harness.CODEX, str(profile), profile, profile, profile,
                                  '/socket', 'parent', '1:2:3')
                parent = ParentBinding(context, 'server', 'ws', 'tab', 'pane', session_path=parent_file)
                row = {'id': 'standalone', 'status': {'type': 'active', 'activeFlags': []}}
                if cwd is not None: row['cwd'] = cwd
                adapter = object.__new__(CodexRuntimeAdapter); adapter.context = context
                adapter.task_store_root = root / 'state'; adapter.proxy = Proxy([
                    {'id': 'parent', 'path': str(parent_file)}, row])
                list(adapter.sessions(parent))
                with parent_file.open('a') as out: out.write(json.dumps(event()) + '\n')
                self.assertEqual(list(adapter.sessions(parent)), [])
                discovery = StateStore(root / 'state', context.key()[:32]).task_discovery()
                if cwd is None:
                    self.assertEqual(len(discovery['pending']), 1)
                else:
                    self.assertEqual(discovery['pending'], [])
                    self.assertEqual(discovery['outcomes'][-1]['status'], 'rejected')

    def test_current_native_parent_path_binding_is_required(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); profile = root / 'profile'; sessions = profile / 'sessions'
            sessions.mkdir(parents=True); parent_file = sessions / 'parent.jsonl'
            parent_file.write_text(json.dumps({'type': 'session_meta', 'payload': {'id': 'parent'}}) + '\n')
            other_file = sessions / 'other.jsonl'
            other_file.write_text(json.dumps({'type': 'session_meta', 'payload': {'id': 'parent'}}) + '\n')
            context = Context(Harness.CODEX, str(profile), profile, profile, profile,
                              '/socket', 'parent', '1:2:3')
            parent = ParentBinding(context, 'server', 'ws', 'tab', 'pane', session_path=parent_file)
            adapter = object.__new__(CodexRuntimeAdapter); adapter.context = context
            adapter.task_store_root = root / 'state'; adapter.proxy = Proxy([
                {'id': 'parent', 'path': str(other_file)},
                {'id': 'standalone', 'cwd': '/work', 'status': {'type': 'active', 'activeFlags': []}}])
            self.assertEqual(list(adapter.sessions(parent)), [])
            with parent_file.open('a') as out: out.write(json.dumps(event()) + '\n')
            self.assertEqual(list(adapter.sessions(parent)), [])
            self.assertEqual(StateStore(root / 'state', context.key()[:32]).task_discovery()['pending'], [])

    def test_coordinator_attaches_verified_id_only_candidate(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); profile = root / 'profile'; sessions = profile / 'sessions'
            sessions.mkdir(parents=True); parent_file = sessions / 'parent.jsonl'
            parent_file.write_text(json.dumps({'type': 'session_meta', 'payload': {'id': 'parent'}}) + '\n')
            context = Context(Harness.CODEX, str(profile), profile, profile, profile,
                              '/socket', 'parent', '1:2:3')
            parent = ParentBinding(context, 'server', 'ws', 'tab', 'pane', session_path=parent_file)
            store = StateStore(root / 'state', context.key()[:32])
            store.commit_task_records({'device': 1, 'inode': 2, 'offset': 10,
                'parent_id': 'parent', 'path': str(parent_file), 'observed_size': 10,
                'skip_to_newline': False}, [SimpleNamespace(parent_id='parent', turn_id='turn',
                item_id='item', child_id='standalone', cwd_sha256=None)],
                parent={'parent_id': 'parent', 'path': str(parent_file), 'owner_uid': __import__('os').getuid()},
                context={'profile': context.profile, 'backend_id': context.backend_id,
                         'backend_instance': context.backend_instance, 'session_id': 'parent'},
                destination={'server_id': 'server', 'workspace_id': 'ws', 'tab_id': 'tab', 'pane_id': 'pane'}, now=1)
            event_key = hashlib.sha256(json.dumps(['parent', 'turn', 'item'], separators=(',', ':')).encode()).hexdigest()
            store.update_task_candidate(event_key, status='verified', now=2)
            store.establish_baseline(set())
            proof = CreationProof('parent', 'turn', 'item', 'standalone')
            child_context = Context(Harness.CODEX, context.profile, context.config_root, context.data_root,
                                    context.state_root, context.backend_id, 'standalone', context.backend_instance)
            child = Session(child_context, 'parent', None, Path('/work'), Lifecycle.RUNNING,
                            True, 3, kind='standalone', creation_proof=proof)
            class Runtime:
                def verify_parent(self, p): return p == parent
                def find_existing_pane(self, p, c): return None
                def can_attach_now(self, p, c): return True
                def open_and_attach(self, p, c, binding): return True
                def owned_pane_state(self, p, c, binding): return 'live'
                def update_title(self, binding, title): pass
            outcome = Coordinator(store, Runtime()).handle(parent, child)
            self.assertEqual(outcome.decision.value, 'attached')
            self.assertEqual(store.task_discovery()['outcomes'][-1]['status'], 'attached')

    def test_new_typed_event_is_bound_and_independently_verified(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); profile = root / 'profile'; sessions = profile / 'sessions'
            sessions.mkdir(parents=True); state = root / 'state'
            parent_file = sessions / 'parent.jsonl'
            parent_file.write_text(json.dumps({'type': 'session_meta', 'payload': {'id': 'parent'}}) + '\n')
            context = Context(Harness.CODEX, str(profile), profile, profile, profile,
                              '/socket', 'parent', '1:2:3')
            parent = ParentBinding(context, 'server', 'ws', 'tab', 'pane', session_path=parent_file)
            child_file = sessions / 'standalone.jsonl'
            child_file.write_text('')
            rows = [{'id': 'parent', 'path': str(parent_file)},
                    {'id': 'standalone', 'path': str(child_file), 'cwd': '/work', 'status': {'type': 'active', 'activeFlags': []}}]
            adapter = object.__new__(CodexRuntimeAdapter)
            adapter.context = context; adapter.task_store_root = state; adapter.proxy = Proxy(rows)
            self.assertEqual(list(adapter.sessions(parent)), [])  # first observation starts at EOF
            with parent_file.open('a') as out:
                out.write(json.dumps(event()) + '\n')
            found = list(adapter.sessions(parent))
            self.assertEqual(len(found), 1)
            child = found[0]
            self.assertEqual(child.context.session_id, 'standalone')
            self.assertEqual(child.parent_session_id, 'parent')
            self.assertEqual(child.kind, 'standalone')
            self.assertEqual(child.lifecycle, Lifecycle.RUNNING)
            self.assertEqual(child.cwd, Path('/work'))
            self.assertEqual(child.session_path, child_file)
            self.assertEqual(child.creation_proof.item_id, 'item')
            state_snapshot = StateStore(state, context.key()[:32]).task_discovery()
            self.assertEqual(state_snapshot['pending'][0]['status'], 'verified')
            self.assertNotIn('content', json.dumps(state_snapshot))
            store = StateStore(state, context.key()[:32]); store.establish_baseline(set())
            class Runtime:
                opened = 0
                def verify_parent(self, p): return p == parent
                def find_existing_pane(self, p, c): return None
                def can_attach_now(self, p, c): return True
                def open_and_attach(self, p, c, binding): self.opened += 1; return True
                def owned_pane_state(self, p, c, binding): return 'live'
                def update_title(self, binding, title): pass
            runtime = Runtime(); coordinator = Coordinator(store, runtime)
            self.assertEqual(coordinator.handle(parent, child).decision.value, 'attached')
            self.assertEqual(coordinator.handle(parent, child).decision.value, 'attached')
            self.assertEqual(runtime.opened, 1)

    def test_future_candidate_defers_without_rejection(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); profile = root / 'profile'; sessions = profile / 'sessions'
            sessions.mkdir(parents=True); parent_file = sessions / 'parent.jsonl'
            parent_file.write_text(json.dumps({'type': 'session_meta', 'payload': {'id': 'parent'}}) + '\n')
            context = Context(Harness.CODEX, str(profile), profile, profile, profile, '/socket', 'parent', '1:2:3')
            parent = ParentBinding(context, 'server', 'ws', 'tab', 'pane', session_path=parent_file)
            adapter = object.__new__(CodexRuntimeAdapter); adapter.context = context
            adapter.task_store_root = root / 'state'; adapter.proxy = Proxy([
                {'id': 'parent', 'path': str(parent_file)},
                {'id': 'standalone', 'cwd': '/work', 'status': {'type': 'active', 'activeFlags': []}}])
            list(adapter.sessions(parent))
            with parent_file.open('a') as out: out.write(json.dumps(event()) + '\n')
            # Persisting a future first_seen models a clock skew across restart.
            list(adapter.sessions(parent))
            store = StateStore(root / 'state', context.key()[:32])
            candidate = store.task_discovery()['pending'][0]
            with store.locked() as data:
                data['task_discovery']['pending'][0]['first_seen'] = __import__('time').time() + 60
            self.assertEqual(list(adapter.sessions(parent)), [])
            self.assertEqual(store.task_discovery()['pending'], [])
            self.assertEqual(store.task_discovery()['outcomes'][-1]['status'], 'rejected')

    def test_missing_metadata_defers_and_retries_after_adapter_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); profile = root / 'profile'; sessions = profile / 'sessions'
            sessions.mkdir(parents=True); parent_file = sessions / 'parent.jsonl'
            parent_file.write_text(json.dumps({'type': 'session_meta', 'payload': {'id': 'parent'}}) + '\n')
            context = Context(Harness.CODEX, str(profile), profile, profile, profile, '/socket', 'parent', '1:2:3')
            parent = ParentBinding(context, 'server', 'ws', 'tab', 'pane', session_path=parent_file)
            proxy = Proxy([{'id': 'parent', 'path': str(parent_file)}])
            adapter = object.__new__(CodexRuntimeAdapter); adapter.context = context
            adapter.task_store_root = root / 'state'; adapter.proxy = proxy
            list(adapter.sessions(parent))
            with parent_file.open('a') as out: out.write(json.dumps(event()) + '\n')
            self.assertEqual(list(adapter.sessions(parent)), [])
            store = StateStore(root / 'state', context.key()[:32])
            self.assertEqual(store.task_discovery()['pending'][0]['attempts'], 1)
            # A fresh adapter has no process-local retry history; durable state
            # still permits the second bounded lookup when metadata appears.
            proxy.rows['standalone'] = {'id': 'standalone', 'cwd': '/work',
                                        'status': {'type': 'active', 'activeFlags': []}}
            restarted = object.__new__(CodexRuntimeAdapter); restarted.context = context
            restarted.task_store_root = root / 'state'; restarted.proxy = proxy
            found = list(restarted.sessions(parent))
            self.assertEqual(len(found), 1)
            self.assertEqual(store.task_discovery()['pending'][0]['attempts'], 2)

    def test_unknown_status_and_missing_cwd_defer_then_attach_when_metadata_arrives(self):
        for initial in ({'id': 'standalone', 'cwd': '/work', 'status': {'type': 'mystery'}},
                        {'id': 'standalone', 'status': {'type': 'active', 'activeFlags': []}}):
            with self.subTest(initial=initial), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp); profile = root / 'profile'; sessions = profile / 'sessions'
                sessions.mkdir(parents=True); parent_file = sessions / 'parent.jsonl'
                parent_file.write_text(json.dumps({'type': 'session_meta', 'payload': {'id': 'parent'}}) + '\n')
                context = Context(Harness.CODEX, str(profile), profile, profile, profile, '/socket', 'parent', '1:2:3')
                parent = ParentBinding(context, 'server', 'ws', 'tab', 'pane', session_path=parent_file)
                proxy = Proxy([{'id': 'parent', 'path': str(parent_file)}, initial])
                adapter = object.__new__(CodexRuntimeAdapter); adapter.context = context
                adapter.task_store_root = root / 'state'; adapter.proxy = proxy
                list(adapter.sessions(parent))
                with parent_file.open('a') as out: out.write(json.dumps(event()) + '\n')
                self.assertEqual(list(adapter.sessions(parent)), [])
                store = StateStore(root / 'state', context.key()[:32])
                self.assertEqual(len(store.task_discovery()['pending']), 1)
                proxy.rows['standalone'] = {'id': 'standalone', 'cwd': '/work',
                                            'status': {'type': 'active', 'activeFlags': []}}
                self.assertEqual(len(list(adapter.sessions(parent))), 1)

    def test_retry_budget_exhaustion_has_bounded_public_reason(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); profile = root / 'profile'; sessions = profile / 'sessions'
            sessions.mkdir(parents=True); parent_file = sessions / 'parent.jsonl'
            parent_file.write_text(json.dumps({'type': 'session_meta', 'payload': {'id': 'parent'}}) + '\n')
            context = Context(Harness.CODEX, str(profile), profile, profile, profile, '/socket', 'parent', '1:2:3')
            parent = ParentBinding(context, 'server', 'ws', 'tab', 'pane', session_path=parent_file)
            proxy = Proxy([{'id': 'parent', 'path': str(parent_file)},
                           {'id': 'standalone', 'cwd': '/work', 'status': {'type': 'unknown'}}])
            adapter = object.__new__(CodexRuntimeAdapter); adapter.context = context
            adapter.task_store_root = root / 'state'; adapter.proxy = proxy
            list(adapter.sessions(parent))
            with parent_file.open('a') as out: out.write(json.dumps(event()) + '\n')
            for _ in range(4): list(adapter.sessions(parent))
            store = StateStore(root / 'state', context.key()[:32])
            self.assertEqual(store.task_discovery()['pending'], [])
            self.assertEqual(store.task_discovery()['outcomes'][-1]['status'], 'rejected')

    def test_invalid_cwd_and_creation_cwd_mismatch_publish_fixed_reasons(self):
        for native_cwd, creation_cwd, expected in (('relative/work', None, 'invalid_cwd'),
                                                  ('/different', '/expected', 'cwd_mismatch')):
            with self.subTest(native_cwd=native_cwd), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp); profile = root / 'profile'; sessions = profile / 'sessions'
                sessions.mkdir(parents=True); parent_file = sessions / 'parent.jsonl'
                parent_file.write_text(json.dumps({'type': 'session_meta', 'payload': {'id': 'parent'}}) + '\n')
                context = Context(Harness.CODEX, str(profile), profile, profile, profile, '/socket', 'parent', '1:2:3')
                parent = ParentBinding(context, 'server', 'ws', 'tab', 'pane', session_path=parent_file)
                proxy = Proxy([{'id': 'parent', 'path': str(parent_file)},
                               {'id': 'standalone', 'cwd': native_cwd,
                                'status': {'type': 'active', 'activeFlags': []}}])
                adapter = object.__new__(CodexRuntimeAdapter); adapter.context = context
                adapter.task_store_root = root / 'state'; adapter.proxy = proxy
                list(adapter.sessions(parent))
                record = event()
                if creation_cwd is not None:
                    record['payload']['item']['result']['content'][0]['text'] = json.dumps(
                        {'threadId': 'standalone', 'cwd': creation_cwd})
                with parent_file.open('a') as out: out.write(json.dumps(record) + '\n')
                self.assertEqual(list(adapter.sessions(parent)), [])
                discovery = StateStore(root / 'state', context.key()[:32]).task_discovery()
                self.assertEqual(discovery['pending'], [])
                self.assertEqual(discovery['outcomes'][-1]['status'], 'rejected')

    def test_attached_replay_empty_poll_and_file_failure_preserve_history(self):
        with tempfile.TemporaryDirectory() as tmp:
            context, parent, original, adapter, _proxy, store, _runtime, _coordinator = \
                self._attached_replay_fixture(tmp)
            before = store.task_discovery()
            replay = list(adapter.sessions(parent))
            self.assertEqual(len(replay), 1)
            self.assertEqual(replay[0].context.session_id, original.context.session_id)
            self.assertEqual(store.task_discovery(), before)
            adapter.proxy.rows['standalone']['status'] = {'type': 'completed'}
            self.assertEqual(list(adapter.sessions(parent)), [])
            self.assertEqual(store.task_discovery(), before)
            parent.session_path.unlink()
            self.assertEqual(list(adapter.sessions(parent)), [])
            self.assertEqual(store.task_discovery(), before)

    def test_established_candidate_deadline_ignores_later_wall_clock_jumps(self):
        for wall_delta in (10000, -500):
            with self.subTest(wall_delta=wall_delta), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp); profile = root / 'profile'; sessions = profile / 'sessions'
                sessions.mkdir(parents=True); parent_file = sessions / 'parent.jsonl'
                parent_file.write_text(json.dumps({'type': 'session_meta', 'payload': {'id': 'parent'}}) + '\n')
                context = Context(Harness.CODEX, str(profile), profile, profile, profile, '/socket', 'parent', '1:2:3')
                parent = ParentBinding(context, 'server', 'ws', 'tab', 'pane', session_path=parent_file)
                proxy = Proxy([{'id': 'parent', 'path': str(parent_file)}])
                adapter = object.__new__(CodexRuntimeAdapter); adapter.context = context
                adapter.task_store_root = root / 'state'; adapter.proxy = proxy
                list(adapter.sessions(parent))
                with parent_file.open('a') as out: out.write(json.dumps(event()) + '\n')
                clock = {'wall': 1000.0, 'mono': 20.0}
                real_read = adapter._read_thread
                first = {'child': True}
                def read_thread(thread_id):
                    if thread_id == 'standalone' and first['child']:
                        first['child'] = False
                        raise LookupError('temporarily unavailable')
                    return real_read(thread_id)
                adapter._read_thread = read_thread
                with patch('harness_herdr_hooks.adapters.codex.time.time', side_effect=lambda: clock['wall']), \
                     patch('harness_herdr_hooks.adapters.codex.time.monotonic', side_effect=lambda: clock['mono']):
                    self.assertEqual(list(adapter.sessions(parent)), [])
                    clock['wall'] += wall_delta
                    clock['mono'] += 2
                    proxy.rows['standalone'] = {'id': 'standalone', 'cwd': '/work',
                                                'status': {'type': 'active', 'activeFlags': []}}
                    self.assertEqual(len(list(adapter.sessions(parent))), 1)

    def test_slow_native_metadata_lookup_crossing_deadline_is_not_yielded(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); profile = root / 'profile'; sessions = profile / 'sessions'
            sessions.mkdir(parents=True); parent_file = sessions / 'parent.jsonl'
            parent_file.write_text(json.dumps({'type': 'session_meta', 'payload': {'id': 'parent'}}) + '\n')
            context = Context(Harness.CODEX, str(profile), profile, profile, profile, '/socket', 'parent', '1:2:3')
            parent = ParentBinding(context, 'server', 'ws', 'tab', 'pane', session_path=parent_file)
            proxy = Proxy([{'id': 'parent', 'path': str(parent_file)},
                           {'id': 'standalone', 'cwd': '/work',
                            'status': {'type': 'active', 'activeFlags': []}}])
            adapter = object.__new__(CodexRuntimeAdapter); adapter.context = context
            adapter.task_store_root = root / 'state'; adapter.proxy = proxy
            list(adapter.sessions(parent))
            with parent_file.open('a') as out: out.write(json.dumps(event()) + '\n')
            tick = {'mono': 40.0}
            real_read = adapter._read_thread
            def slow_read(thread_id):
                if thread_id == 'standalone': tick['mono'] += 31.0
                return real_read(thread_id)
            adapter._read_thread = slow_read
            with patch('harness_herdr_hooks.adapters.codex.time.monotonic',
                       side_effect=lambda: tick['mono']):
                self.assertEqual(list(adapter.sessions(parent)), [])
            discovery = StateStore(root / 'state', context.key()[:32]).task_discovery()
            self.assertEqual(discovery['pending'], [])
            self.assertEqual(discovery['outcomes'][-1]['status'], 'rejected')

    def test_expired_and_finished_candidates_are_rejected(self):
        for status, age in (({'type': 'active', 'activeFlags': []}, 31),
                            ({'type': 'completed'}, 0)):
            with self.subTest(status=status, age=age), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp); profile = root / 'profile'; sessions = profile / 'sessions'
                sessions.mkdir(parents=True); parent_file = sessions / 'parent.jsonl'
                parent_file.write_text(json.dumps({'type': 'session_meta', 'payload': {'id': 'parent'}}) + '\n')
                context = Context(Harness.CODEX, str(profile), profile, profile, profile, '/socket', 'parent', '1:2:3')
                parent = ParentBinding(context, 'server', 'ws', 'tab', 'pane', session_path=parent_file)
                adapter = object.__new__(CodexRuntimeAdapter); adapter.context = context
                adapter.task_store_root = root / 'state'; adapter.proxy = Proxy([
                    {'id': 'parent', 'path': str(parent_file)},
                    {'id': 'standalone', 'cwd': '/work', 'status': status}])
                list(adapter.sessions(parent))
                with parent_file.open('a') as out: out.write(json.dumps(event()) + '\n')
                list(adapter.sessions(parent))
                store = StateStore(root / 'state', context.key()[:32])
                if age:
                    with store.locked() as data:
                        data['task_discovery']['pending'][0]['first_seen'] -= age
                self.assertEqual(list(adapter.sessions(parent)), [])
                self.assertEqual(store.task_discovery()['pending'], [])
                self.assertEqual(store.task_discovery()['outcomes'][-1]['status'], 'rejected')

    def test_native_cwd_mismatch_rejects_optional_creation_cwd_pin(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); profile = root / 'profile'; sessions = profile / 'sessions'
            sessions.mkdir(parents=True); parent_file = sessions / 'parent.jsonl'
            parent_file.write_text(json.dumps({'type': 'session_meta', 'payload': {'id': 'parent'}}) + '\n')
            context = Context(Harness.CODEX, str(profile), profile, profile, profile,
                              '/socket', 'parent', '1:2:3')
            parent = ParentBinding(context, 'server', 'ws', 'tab', 'pane', session_path=parent_file)
            adapter = object.__new__(CodexRuntimeAdapter)
            adapter.context = context; adapter.task_store_root = root / 'state'
            adapter.proxy = Proxy([{'id': 'parent', 'path': str(parent_file)},
                                   {'id': 'standalone', 'cwd': '/different',
                                    'status': {'type': 'active', 'activeFlags': []}}])
            list(adapter.sessions(parent))
            pinned = event()
            pinned['payload']['item']['result']['content'][0]['text'] = json.dumps(
                {'threadId': 'standalone', 'cwd': '/expected'})
            with parent_file.open('a') as out: out.write(json.dumps(pinned) + '\n')
            self.assertEqual(list(adapter.sessions(parent)), [])
            discovery = StateStore(root / 'state', context.key()[:32]).task_discovery()
            self.assertEqual(discovery['pending'], [])
            self.assertEqual(discovery['outcomes'][-1]['status'], 'rejected')


if __name__ == '__main__':
    unittest.main()
