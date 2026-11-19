from __future__ import annotations

import unittest
import shutil
import tempfile
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from harness_herdr_hooks.herdr import (
    codex_backend_proof, process_matches_attachment, revalidate_codex_backend_proof,
)
from harness_herdr_hooks.codex_backend import ProcessProof
from harness_herdr_hooks.model import Context, Harness
from harness_herdr_hooks.attach import _wrapper_process_argv
from harness_herdr_hooks.coordinator import NativeRuntime
from harness_herdr_hooks.state import binding_is_close_owned


class PaneOwnershipTests(unittest.TestCase):
    def setUp(self):
        self.home = Path('/tmp/profile')
        self.target = Path('/tmp/private/codex.sock')
        self.argv = (shutil.which('codex') or '/usr/bin/codex', 'resume', '--remote', f'unix://{self.target}', 'child')
        self.proc = ProcessProof(42,1000,'codex',Path('/usr/bin/codex'),Path('/tmp'),123,self.argv)

    def process(self, argv=None):
        row = {'pid': 42, 'name': 'codex', 'cwd': '/tmp'}
        if argv is not None:
            row['argv'] = argv
        return row

    def test_parent_pin_uses_os_argv_when_herdr_omits_it(self):
        with patch('harness_herdr_hooks.herdr._codex_proc_proof', return_value=self.proc), \
             patch('harness_herdr_hooks.codex_backend.select_endpoint') as select:
            select.return_value = SimpleNamespace(alias=self.home/'explicit.sock', target=self.target,
                socket_identity=(1,2,1000,0o600,0o140000), alias_identity=(1,3,1000,0o777,0o120000),
                directory_identity=(1,4,1000,0o700,0o040000))
            proof = codex_backend_proof(self.process(), self.home)
        self.assertEqual(proof['pid'], 42)
        self.assertEqual(proof['socket_target'], str(self.target))
        self.assertEqual(proof['start_ticks'], 123)
        self.assertEqual(select.call_args.args, (self.home, self.target))

    def test_attachment_matches_from_os_argv_when_herdr_omits_it(self):
        context = Context(Harness.CODEX, str(self.home), self.home, self.home, self.home,
                          str(self.target), 'child', '1:2:3')
        expected = [shutil.which('codex') or '/usr/bin/codex', 'resume', '--remote', f'unix://{self.target}', 'child']
        with patch('harness_herdr_hooks.herdr._codex_proc_proof', return_value=self.proc):
            self.assertTrue(process_matches_attachment(self.process(), expected, context))

    def test_changed_foreground_pid_and_changed_command_fail(self):
        context = Context(Harness.CODEX, str(self.home), self.home, self.home, self.home,
                          str(self.target), 'child', '1:2:3')
        expected = [shutil.which('codex') or '/usr/bin/codex', 'resume', '--remote', f'unix://{self.target}', 'child']
        wrong = self.process(list(self.argv[:-1]) + ['other'])
        self.assertFalse(process_matches_attachment(wrong, expected, context))
        with patch('harness_herdr_hooks.herdr._codex_proc_proof', side_effect=ValueError('PID reused')):
            self.assertFalse(process_matches_attachment(self.process(), expected, context))

    def test_revalidation_rejects_changed_generation_of_process_or_endpoint(self):
        proof = {'socket_alias': str(self.home/'app-server-control/app-server-control.sock'),
                 'socket_target': str(self.target), 'socket_identity': [1,2,1000,384,49152],
                 'alias_identity': [1,3,1000,511,40960], 'directory_identity': [1,4,1000,448,16384],
                 'pid':42, 'uid':1000, 'executable':'/usr/bin/codex', 'cwd':'/tmp', 'start_ticks':123}
        with patch('harness_herdr_hooks.herdr.codex_backend_proof', return_value=dict(proof)):
            self.assertTrue(revalidate_codex_backend_proof(proof, [self.process()], self.home))
        changed = dict(proof, start_ticks=124)
        with patch('harness_herdr_hooks.herdr.codex_backend_proof', return_value=changed):
            self.assertFalse(revalidate_codex_backend_proof(proof, [self.process()], self.home))

    def test_wrapper_uses_pinned_proc_argv_when_herdr_omits_it(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary); proc=root/'42'; proc.mkdir()
            (proc/'status').write_text(f'Name:\tpython3\nUid:\t{os.getuid()}\t{os.getuid()}\t{os.getuid()}\t{os.getuid()}\n')
            (proc/'stat').write_text('42 (python3) R 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 12345 20\n')
            (proc/'cwd').symlink_to('/tmp',target_is_directory=True)
            executable=Path(shutil.which('python3'))
            (proc/'exe').symlink_to(executable)
            (proc/'cmdline').write_bytes(b'/usr/bin/python3\0/tmp/hook.py\0attach\0bound\0')
            row={'pid':42}
            argv=_wrapper_process_argv(row,Path('/tmp'),proc_root=root)
            self.assertEqual(argv,['/usr/bin/python3','/tmp/hook.py','attach','bound'])
            self.assertIsNone(_wrapper_process_argv(row,Path('/other'),proc_root=root))

    def test_exited_display_requires_exact_process_incarnation_absence(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary); proc=root/'42'; proc.mkdir()
            (proc/'stat').write_text('42 (codex) R 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 123 20\n')
            pin={'pid':42,'start_ticks':123}
            self.assertEqual(NativeRuntime._pinned_display_state(pin,proc_root=root),'live')
            (proc/'stat').write_text('42 (codex) R 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 124 20\n')
            self.assertEqual(NativeRuntime._pinned_display_state(pin,proc_root=root),'unknown')
            (proc/'stat').unlink(); proc.rmdir()
            self.assertEqual(NativeRuntime._pinned_display_state(pin,proc_root=root),'exited')

    def test_empty_display_requires_no_foreground_or_foreign_pty_process(self):
        with patch('harness_herdr_hooks.attach._tty_has_no_processes',return_value=True):
            self.assertTrue(NativeRuntime._empty_display_pty({'foreground_processes':[],'tty':'/dev/pts/4'}))
            self.assertFalse(NativeRuntime._empty_display_pty({'foreground_processes':[{'pid':99}],'tty':'/dev/pts/4'}))
        with patch('harness_herdr_hooks.attach._tty_has_no_processes',return_value=False):
            self.assertFalse(NativeRuntime._empty_display_pty({'foreground_processes':[],'tty':'/dev/pts/4'}))

    def test_independent_and_reused_bindings_never_grant_close_ownership(self):
        base={'schema':2,'ownership':'created','kind':'subagent','close_suppressed':False}
        self.assertTrue(binding_is_close_owned(base))
        self.assertFalse(binding_is_close_owned(dict(base,kind='independent')))
        self.assertFalse(binding_is_close_owned(dict(base,ownership='reused')))


if __name__ == '__main__':
    unittest.main()
