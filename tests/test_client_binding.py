import os
import json
import pty
import fcntl
import threading
import time
import tempfile
import unittest
from pathlib import Path

from harness_herdr_hooks.client_binding import (
    BindingError, ClientBindingStore, admit_from_herdr, admit_terminal, validate_report,
)

PARENT = "123e4567-e89b-42d3-a456-426614174000"
CHILD = "123e4567-e89b-42d3-a456-426614174001"


class ClientBindingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)

    def test_report_protocol_strict_monotonic_and_clear_before_active(self):
        active = {"version": 1, "sequence": 1, "event": "active", "thread_id": PARENT, "source": "startup"}
        self.assertEqual(validate_report(active, 0)["thread_id"], PARENT)
        for bad, last in (
            ({**active, "extra": True}, 0),
            ({**active, "thread_id": "not-a-uuid"}, 0),
            ({**active, "sequence": 1}, 1),
            ({"version": 1, "sequence": 2, "event": "clear", "thread_id": PARENT}, 1),
            ({"version": 1, "sequence": 2, "event": "created", "thread_id": PARENT,
             "child_id": CHILD, "turn_id": "x" * 129, "view_sequence": 1}, 1),
        ):
            with self.assertRaises(BindingError):
                validate_report(bad, last)
        lease, master, slave = self._lease()
        self.addCleanup(os.close, master); self.addCleanup(os.close, slave)
        self.addCleanup(lease.close)
        lease.accept(active)
        with self.assertRaises(BindingError):
            lease.accept({"version": 1, "sequence": 2, "event": "active", "thread_id": CHILD, "source": "resume"})
        lease.accept({"version": 1, "sequence": 2, "event": "clear", "thread_id": None})
        lease.accept({"version": 1, "sequence": 3, "event": "active", "thread_id": CHILD, "source": "resume"})

    def test_terminal_admission_requires_exact_unique_pane(self):
        master, slave = pty.openpty()
        self.addCleanup(os.close, master); self.addCleanup(os.close, slave)
        tty = os.ttyname(slave)
        pane = {"pane_id": "p1", "workspace_id": "w1", "tab_id": "t1", "process_info": {"tty": tty}}
        accepted = admit_terminal(slave, {"protocol": 22, "panes": [pane]}, server_id="server",
                                  workspace_id="w1", tab_id="t1", pane_id="p1")
        self.assertEqual(accepted.pane_id, "p1")
        for snapshot in (
            {"protocol": 22, "panes": [pane, pane]},
            {"protocol": 22, "panes": [{**pane, "process_info": {"tty": "/dev/null"}}]},
            {"protocol": 22, "panes": [pane, {"pane_id": "p2", "workspace_id": "w1", "tab_id": "t1", "process_info": {}}]},
            {"protocol": 22, "panes": [pane] * 129},
        ):
            with self.assertRaises(BindingError):
                admit_terminal(slave, snapshot, server_id="server", workspace_id="w1", tab_id="t1", pane_id="p1")

    def test_herdr_admission_rejects_missing_tty_on_any_candidate(self):
        master, slave = pty.openpty()
        self.addCleanup(os.close, master); self.addCleanup(os.close, slave)
        panes = [{"pane_id": "p1", "workspace_id": "w1", "tab_id": "t1"},
                 {"pane_id": "p2", "workspace_id": "w2", "tab_id": "t2"}]
        class FakeHerdr:
            def snapshot(self): return {"protocol": 22, "panes": panes}
            def server_identity(self): return "server"
            def process_info(self, pane_id):
                return {"pane_id": pane_id, "tty": os.ttyname(slave)} if pane_id == "p1" else {"pane_id": pane_id}
        with self.assertRaises(BindingError):
            admit_from_herdr(slave, FakeHerdr(), workspace_id="w1", tab_id="t1", pane_id="p1")

    def test_lease_receipt_single_use_exact_effect_and_revocation(self):
        lease, master, slave = self._lease()
        self.addCleanup(os.close, master); self.addCleanup(os.close, slave)
        self.addCleanup(lease.close)
        store = lease.store
        self.assertEqual(store.read_live(lease.key)["generation"], lease.record["generation"])
        lease.accept({"version": 1, "sequence": 1, "event": "active", "thread_id": PARENT, "source": "startup"})
        lease.accept({"version": 1, "sequence": 2, "event": "created", "thread_id": PARENT,
                      "child_id": CHILD, "turn_id": "turn-1", "view_sequence": 1})
        receipt = store.consume_matching_receipt(PARENT, "turn-1", CHILD)
        self.assertIsNotNone(receipt)
        self.assertIsNone(store.consume_matching_receipt(PARENT, "turn-1", CHILD))
        effect = {"stage": "split", "event_key": "event-a", "view_sequence": 1, "pane_id": "p2"}
        with store.guard(lease.key, lease.record["generation"]) as guard:
            guard.set_unresolved(effect)
            with self.assertRaises(BindingError):
                guard.set_unresolved(None, expected={**effect, "event_key": "other"})
        with self.assertRaises(BindingError):
            lease.accept({"version": 1, "sequence": 3, "event": "clear", "thread_id": None})
        with store.guard(lease.key, lease.record["generation"]) as guard:
            guard.set_unresolved(None, expected=effect)
        lease.accept({"version": 1, "sequence": 3, "event": "clear", "thread_id": None})
        lease.close()
        self.assertTrue(store.assert_revoked(lease.key, lease.record["generation"]))

    def test_duplicate_json_keys_are_rejected_and_lease_expires(self):
        lease, master, slave = self._lease()
        self.addCleanup(os.close, master); self.addCleanup(os.close, slave)
        with self.assertRaises(BindingError):
            lease.serve(__import__("io").BytesIO(b'{"version":1,"version":1,"sequence":1,"event":"clear","thread_id":null}\n'),
                        __import__("io").BytesIO())
        self.assertIsNone(lease.store.read_live(lease.key))

    def test_lock_replacement_invalidates_live_lease_and_revocation_probe(self):
        lease, master, slave = self._lease()
        self.addCleanup(os.close, master); self.addCleanup(os.close, slave)
        path = lease.lifetime_path
        replacement = lease.store.root / "replacement"
        replacement.write_bytes(b""); replacement.chmod(0o600); os.replace(replacement, path)
        with self.assertRaises(BindingError):
            with lease.effect_guard():
                pass
        with self.assertRaises(BindingError):
            lease.store.assert_revoked(lease.key, lease.record["generation"])
        lease.close()

    def test_nonce_revocation_requires_exact_dead_generation_and_does_not_restore_authority(self):
        nonce = "a7f8c1a2-ffac-4b56-9a91-3c6aef681234"
        lease, master, slave = self._lease(client_nonce=nonce)
        self.addCleanup(os.close, master); self.addCleanup(os.close, slave)
        display = self._display(lease)
        lease.accept({"version": 1, "sequence": 1, "event": "active", "thread_id": PARENT, "source": "startup"})
        with self.assertRaises(BindingError):
            lease.store.assert_revoked_client(display, "p", {"incarnation": "b"}, nonce)
        self.assertEqual(lease.store.read_live(lease.key)["active_thread_id"], PARENT)
        with self.assertRaises(BindingError):
            lease.store.assert_revoked_client(display, "p", {"incarnation": "wrong"}, nonce)
        with self.assertRaises(BindingError):
            lease.store.assert_revoked_client(display, "p", {"incarnation": "b"},
                                              "a7f8c1a2-ffac-4b56-9a91-3c6aef681235")
        lease.close()
        self.assertTrue(lease.store.assert_revoked_client(display, "p", {"incarnation": "b"}, nonce))
        self.assertIsNone(lease.store.read_live(lease.key))
        self.assertIsNone(lease.store.consume_matching_receipt(PARENT, "turn", CHILD))
        with self.assertRaises(BindingError):
            lease.store.open_lease(profile="p", backend={"incarnation": "b"}, server_id="s",
                workspace_id="w", tab_id="t", pane_id="p", terminal_device=display.terminal_device,
                terminal_inode=display.terminal_inode, client_nonce=nonce)

    def test_nonce_revocation_rejects_live_replaced_and_unresolved_effects(self):
        for stage in ("split", "start"):
            nonce = "b7f8c1a2-ffac-4b56-9a91-3c6aef681234" if stage == "split" else "c7f8c1a2-ffac-4b56-9a91-3c6aef681234"
            lease, master, slave = self._lease(client_nonce=nonce)
            self.addCleanup(os.close, master); self.addCleanup(os.close, slave)
            display = self._display(lease)
            with lease.store.guard(lease.key, lease.record["generation"]) as guard:
                guard.set_unresolved({"stage": stage, "event_key": "event-1", "view_sequence": 1})
            with self.assertRaises(BindingError):
                lease.store.assert_revoked_client(display, "p", {"incarnation": "b"}, nonce)
            lease.close()
            with self.assertRaises(BindingError):
                lease.store.assert_revoked_client(display, "p", {"incarnation": "b"}, nonce)

        nonce = "d7f8c1a2-ffac-4b56-9a91-3c6aef681234"
        lease, master, slave = self._lease(client_nonce=nonce)
        self.addCleanup(os.close, master); self.addCleanup(os.close, slave)
        display = self._display(lease)
        effect = lease.effect_path
        replacement = lease.store.root / "replacement-effect"
        replacement.write_bytes(b""); replacement.chmod(0o600); os.replace(replacement, effect)
        lease.close()
        with self.assertRaises(BindingError):
            lease.store.assert_revoked_client(display, "p", {"incarnation": "b"}, nonce)

    def test_nonce_is_generation_specific_and_missing_effect_lock_fails_closed(self):
        old_nonce = "e7f8c1a2-ffac-4b56-9a91-3c6aef681234"
        old, master, slave = self._lease(client_nonce=old_nonce)
        self.addCleanup(os.close, master); self.addCleanup(os.close, slave)
        display = self._display(old)
        old.close()
        new_nonce = "f7f8c1a2-ffac-4b56-9a91-3c6aef681234"
        row = old.record
        new = old.store.open_lease(profile="p", backend={"incarnation": "b"}, server_id="s",
            workspace_id="w", tab_id="t", pane_id="p", terminal_device=row["terminal_device"],
            terminal_inode=row["terminal_inode"], client_nonce=new_nonce)
        with self.assertRaises(BindingError):
            new.store.assert_revoked_client(display, "p", {"incarnation": "b"}, old_nonce)
        new.effect_path.unlink()
        new.close()
        with self.assertRaises(BindingError):
            new.store.assert_revoked_client(display, "p", {"incarnation": "b"}, new_nonce)

    def test_close_drops_live_authority_before_waiting_for_admitted_effect(self):
        lease, master, slave = self._lease()
        self.addCleanup(os.close, master); self.addCleanup(os.close, slave)
        fd = os.open(lease.effect_path, os.O_RDWR)
        fcntl.flock(fd, fcntl.LOCK_EX)
        closed = threading.Thread(target=lease.close)
        closed.start()
        deadline = time.monotonic() + 1
        while lease.store.read_live(lease.key) is not None and time.monotonic() < deadline:
            time.sleep(0.005)
        self.assertIsNone(lease.store.read_live(lease.key))
        self.assertTrue(closed.is_alive())
        fcntl.flock(fd, fcntl.LOCK_UN); os.close(fd)
        closed.join(timeout=1)
        self.assertFalse(closed.is_alive())

    def test_incoming_generation_waits_on_old_gate_without_old_liveness_resurrection(self):
        old, master, slave = self._lease()
        self.addCleanup(os.close, master); self.addCleanup(os.close, slave)
        row = old.record
        gate = os.open(old.effect_path, os.O_RDWR)
        fcntl.flock(gate, fcntl.LOCK_EX)
        close_thread = threading.Thread(target=old.close)
        close_thread.start()
        deadline = time.monotonic() + 1
        while old.store.read_live(old.key, row["generation"]) is not None and time.monotonic() < deadline:
            time.sleep(0.005)
        self.assertIsNone(old.store.read_live(old.key, row["generation"]))
        result, failures = [], []
        def replace_generation():
            try:
                result.append(old.store.open_lease(profile="p", backend={"incarnation": "b"}, server_id="s",
                    workspace_id="w", tab_id="t", pane_id="p", terminal_device=row["terminal_device"],
                    terminal_inode=row["terminal_inode"]))
            except BaseException as exc:
                failures.append(exc)
        incoming = threading.Thread(target=replace_generation)
        incoming.start()
        time.sleep(0.03)
        self.assertTrue(incoming.is_alive())
        for _ in range(5):
            self.assertIsNone(old.store.read_live(old.key, row["generation"]))
            time.sleep(0.005)
        fcntl.flock(gate, fcntl.LOCK_UN); os.close(gate)
        close_thread.join(timeout=1); incoming.join(timeout=1)
        self.assertFalse(close_thread.is_alive()); self.assertFalse(incoming.is_alive())
        self.assertEqual(failures, [])
        self.assertEqual(len(result), 1)
        new = result[0]
        self.assertNotEqual(new.record["generation"], row["generation"])
        current = old.store.read_live(old.key, new.record["generation"])
        self.assertEqual(current["active_thread_id"], None)
        self.assertEqual(current["last_sequence"], 0)
        new.close()

    def test_generation_replacement_is_serialized_and_rejects_old_uncertainty(self):
        lease, master, slave = self._lease()
        self.addCleanup(os.close, master); self.addCleanup(os.close, slave)
        row = lease.record
        with lease.store.guard(lease.key, row["generation"]) as guard:
            guard.set_unresolved({"stage": "split", "event_key": "split-e", "view_sequence": 1})
        lease.close()
        with self.assertRaises(BindingError):
            lease.store.open_lease(profile="p", backend={"incarnation": "b"}, server_id="s",
                workspace_id="w", tab_id="t", pane_id="p", terminal_device=row["terminal_device"],
                terminal_inode=row["terminal_inode"])

    def test_state_root_mode_is_preserved_and_private_directory_modes_fail_closed(self):
        root = Path(self.temp.name)
        root.chmod(0o755)
        ClientBindingStore(root)
        self.assertEqual(root.stat().st_mode & 0o777, 0o755)
        private = root / "bad-state" / "harness-herdr-hooks"
        private.mkdir(parents=True, mode=0o755)
        private.chmod(0o755)
        with self.assertRaises(BindingError):
            ClientBindingStore(root / "bad-state")
        self.assertEqual(private.stat().st_mode & 0o777, 0o755)

    def test_revocation_reconciles_only_an_exact_uncertain_start(self):
        nonce = "a8f8c1a2-ffac-4b56-9a91-3c6aef681234"
        lease, master, slave = self._lease(client_nonce=nonce)
        self.addCleanup(os.close, master); self.addCleanup(os.close, slave)
        display = self._display(lease)
        unresolved = {"stage": "start", "event_key": "start-e", "view_sequence": 1,
                      "parent_id": PARENT}
        with lease.store.guard(lease.key, lease.record["generation"]) as guard:
            guard.set_unresolved(unresolved)
        lease.close()
        observed = []
        with self.assertRaises(BindingError):
            lease.store.assert_revoked_client(display, "p", {"incarnation": "b"}, nonce,
                                              reconcile_start=lambda _r, _e: False)
        self.assertEqual(json.loads((lease.store.root / f"{lease.key}.json").read_text())["unresolved_effect"], unresolved)
        def reconcile(record, effect):
            self.assertIsNone(lease.store.read_live(lease.key, lease.record["generation"]))
            observed.append((record["generation"], effect))
            return True
        self.assertTrue(lease.store.assert_revoked_client(display, "p", {"incarnation": "b"}, nonce,
                                                          reconcile_start=reconcile))
        self.assertEqual(observed, [(lease.record["generation"], unresolved)])
        self.assertIsNone(lease.store.read_live(lease.key))

    def _lease(self, client_nonce=None):
        master, slave = pty.openpty()
        st = os.fstat(slave)
        store = ClientBindingStore(Path(self.temp.name))
        lease = store.open_lease(profile="p", backend={"incarnation": "b"}, server_id="s",
            workspace_id="w", tab_id="t", pane_id="p", terminal_device=st.st_dev,
            terminal_inode=st.st_ino, client_nonce=client_nonce)
        return lease, master, slave

    @staticmethod
    def _display(lease):
        from harness_herdr_hooks.client_binding import PaneDisplay
        row = lease.record
        return PaneDisplay(row["server_id"], row["workspace_id"], row["tab_id"], row["pane_id"],
                           row["terminal_device"], row["terminal_inode"])


if __name__ == "__main__":
    unittest.main()
