from __future__ import annotations

import os
import stat
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from harness_herdr_hooks.codex_backend import (
    BackendProofError, ProcessProof, default_socket_alias, inspect_endpoint,
    inspect_process, select_endpoint, verify_process_pin,
)


def info(dev, ino, uid, mode):
    return SimpleNamespace(st_dev=dev, st_ino=ino, st_uid=uid, st_mode=mode)


class EndpointTests(unittest.TestCase):
    def setUp(self):
        self.root = Path("/profiles/alex")
        self.home = self.root / "selected"
        self.alias = default_socket_alias(self.home)
        self.target = Path("/run/user/1000/codex/server.sock")
        self.alias_inode = 1
        self.socket_inode = 2
        self.uid = 1000

    def probes(self, *, uid=None, private=True):
        owner = self.uid if uid is None else uid
        def lstat(path): return info(1, self.alias_inode, owner, stat.S_IFLNK | 0o777)
        def stat_fn(path):
            if path == self.target:
                return info(2, self.socket_inode, self.uid, stat.S_IFSOCK | 0o600)
            return info(2, 3, self.uid, stat.S_IFDIR | (0o700 if private else 0o755))
        return lstat, stat_fn, lambda path, strict=False: self.target

    def test_default_uses_only_selected_home_alias_and_pins_target(self):
        self.assertEqual(default_socket_alias(self.home), self.alias)
        lstat, stat_fn, resolve = self.probes()
        pin = select_endpoint(self.home, uid=self.uid, lstat=lstat, stat_fn=stat_fn, resolve=resolve)
        self.assertEqual(pin.target, self.target)
        pin.revalidate(uid=self.uid, lstat=lstat, stat_fn=stat_fn, resolve=resolve)

    def test_explicit_unix_endpoint_is_authoritative(self):
        lstat, stat_fn, resolve = self.probes()
        pin = select_endpoint(self.home, "unix://", uid=self.uid,
                              lstat=lstat, stat_fn=stat_fn, resolve=resolve)
        self.assertEqual(pin.alias, self.alias)
        self.assertEqual(select_endpoint(self.home, "unix://", uid=self.uid, lstat=lstat,
                              stat_fn=stat_fn, resolve=resolve).target, self.target)
        with self.assertRaises(BackendProofError):
            select_endpoint(self.home, "unix://remote.example/tmp/socket", uid=self.uid)

    def test_alias_replacement_foreign_owner_and_public_directory_fail_closed(self):
        lstat, stat_fn, resolve = self.probes()
        pin = inspect_endpoint(self.alias, uid=self.uid, lstat=lstat, stat_fn=stat_fn, resolve=resolve)
        self.alias_inode += 1
        with self.assertRaises(BackendProofError):
            pin.revalidate(uid=self.uid, lstat=lstat, stat_fn=stat_fn, resolve=resolve)
        lstat, stat_fn, resolve = self.probes(uid=1001)
        with self.assertRaises(BackendProofError):
            inspect_endpoint(self.alias, uid=1001, lstat=lstat, stat_fn=stat_fn, resolve=resolve)
        lstat, stat_fn, resolve = self.probes(private=False)
        with self.assertRaises(BackendProofError):
            inspect_endpoint(self.alias, uid=self.uid, lstat=lstat, stat_fn=stat_fn, resolve=resolve)


class ProcessTests(unittest.TestCase):
    def test_optional_herdr_argv_does_not_invalidate_process_proof(self):
        root = Path("/proc") / "88"
        values = {
            root / "status": b"Name:\tcodex\nUid:\t1000\t1000\t1000\t1000\n",
            root / "stat": b"88 (codex) R 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 987654 20\n",
            root / "cmdline": b"",
        }
        def read(path): return values[path]
        def resolve(path, strict=False):
            if str(path).endswith("/exe"): return Path("/usr/bin/codex")
            if str(path).endswith("/cwd"): return Path("/workspace")
            return Path(path)
        proof = inspect_process(88, expected_name="codex", expected_cwd=Path("/workspace"),
                                proc_root=Path("/proc"), uid=1000, read_bytes=read, resolve=resolve)
        self.assertIsNone(proof.argv)
        self.assertEqual(proof.launch_mode, "unknown")
        self.assertEqual(proof.start_ticks, 987654)

    def test_foreign_process_and_pid_reuse_are_rejected(self):
        with self.assertRaises(BackendProofError):
            inspect_process(88, expected_name="codex", uid=1001)
        pin = ProcessProof(88, 1000, "codex", Path("/usr/bin/codex"), Path("/workspace"), 5, None)
        with patch("harness_herdr_hooks.codex_backend.inspect_process", return_value=ProcessProof(
                88, 1000, "codex", Path("/usr/bin/codex"), Path("/workspace"), 6, None)):
            with self.assertRaises(BackendProofError):
                verify_process_pin(pin)


if __name__ == "__main__":
    unittest.main()
