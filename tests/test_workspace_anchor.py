import os
import stat
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from harness_herdr_hooks import tabs


class WorkspaceAnchorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.home = self.base / 'account'
        self.home.mkdir(mode=0o700)
        os.chmod(self.home, 0o700)

    def tearDown(self):
        self.tmp.cleanup()

    def resolve(self):
        return tabs._resolve_workspace_anchor()

    def account(self):
        return SimpleNamespace(pw_dir=str(self.home))

    def test_uses_uid_account_home_and_ignores_home_and_xdg(self):
        with patch.object(tabs.os, 'getuid', return_value=os.getuid()), \
             patch.object(tabs.pwd, 'getpwuid', return_value=self.account()), \
             patch.dict(os.environ, {'HOME': str(self.base / 'wrong-home'), 'XDG_STATE_HOME': str(self.base / 'wrong-state')}):
            anchor = self.resolve()
        self.assertEqual(anchor, self.home / '.local' / 'state')
        self.assertEqual(stat.S_IMODE(anchor.stat().st_mode), 0o700)
        self.assertFalse((self.base / 'wrong-home').exists())
        self.assertFalse((self.base / 'wrong-state').exists())

    def test_rejects_missing_account_and_symlink_components(self):
        with patch.object(tabs.os, 'getuid', return_value=os.getuid()), \
             patch.object(tabs.pwd, 'getpwuid', side_effect=KeyError):
            with self.assertRaisesRegex(RuntimeError, 'account home not found'):
                self.resolve()
        (self.home / '.local').symlink_to(self.base, target_is_directory=True)
        with patch.object(tabs.pwd, 'getpwuid', return_value=self.account()):
            with self.assertRaisesRegex(RuntimeError, 'no-follow|unsafe'):
                self.resolve()

    def test_rejects_unsafe_existing_anchor_without_chmod(self):
        local = self.home / '.local'
        local.mkdir(mode=0o700)
        os.chmod(local, 0o777)
        with patch.object(tabs.pwd, 'getpwuid', return_value=self.account()):
            with self.assertRaisesRegex(RuntimeError, r'unsafe \.local'):
                self.resolve()
        self.assertEqual(stat.S_IMODE(local.stat().st_mode), 0o777)

    def test_accepts_non_writable_existing_components_and_rejects_writable(self):
        for mode in (0o755, 0o750):
            with self.subTest(mode=oct(mode)):
                local = self.home / '.local'
                local.mkdir(mode=mode)
                os.chmod(local, mode)
                state = local / 'state'
                state.mkdir(mode=mode)
                os.chmod(state, mode)
                with patch.object(tabs.pwd, 'getpwuid', return_value=self.account()):
                    self.assertEqual(self.resolve(), state)
                state.rmdir(); local.rmdir()
        for component in ('.local', 'state'):
            for mode in (0o775, 0o777):
                with self.subTest(component=component, mode=oct(mode)):
                    local = self.home / '.local'
                    local.mkdir(mode=0o700)
                    os.chmod(local, mode if component == '.local' else 0o700)
                    state = local / 'state'
                    state.mkdir(mode=mode if component == 'state' else 0o700)
                    os.chmod(state, mode if component == 'state' else 0o700)
                    with patch.object(tabs.pwd, 'getpwuid', return_value=self.account()), \
                         self.assertRaisesRegex(RuntimeError, f'unsafe {component}'):
                        self.resolve()
                    os.chmod(state, 0o700); state.rmdir(); os.chmod(local, 0o700); local.rmdir()

    def test_rejects_unsafe_home_and_unsupported_nofollow(self):
        os.chmod(self.home, 0o777)
        with patch.object(tabs.pwd, 'getpwuid', return_value=self.account()):
            with self.assertRaisesRegex(RuntimeError, 'unsafe account home'):
                self.resolve()
        os.chmod(self.home, 0o700)
        with patch.object(tabs.os, 'O_NOFOLLOW', 0):
            with self.assertRaisesRegex(RuntimeError, 'unsupported'):
                self.resolve()

    def test_rejects_unbounded_or_parent_traversing_home(self):
        with patch.object(tabs.pwd, 'getpwuid', return_value=SimpleNamespace(pw_dir='/' + '../' * 130)):
            with self.assertRaisesRegex(RuntimeError, 'invalid account home path'):
                self.resolve()


if __name__ == '__main__':
    unittest.main()
