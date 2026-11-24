import json
import hashlib
import importlib
import os
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

from harness_herdr_hooks.install import InstallError, install, status, uninstall


class CodexInstallTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "profile"
        self.root.mkdir(mode=0o700)
        self.bin = Path(self.tmp.name) / "bin"
        self.bin.mkdir()
        self.native = self.bin / "codex"
        self.native.write_text("#!/bin/sh\nexit 0\n")
        self.native.chmod(0o700)
        self.source = Path(__file__).resolve().parents[1]

    def tearDown(self):
        self.tmp.cleanup()

    def test_client_binding_install_pins_capability_and_rejects_legacy_reporter(self):
        pinned=self.bin/"codex-patched"
        pinned.write_text("#!/bin/sh\nif [ \"$1\" = --version ]; then echo 'codex-cli 0.172.0 herdr-client-binding-v1'; exit 0; fi\nexit 0\n")
        pinned.chmod(0o700)
        with patch.dict(os.environ,{"PATH":str(self.bin)}):
            install("codex",source_root=self.source,config_dir=str(self.root),client_binding_codex=str(pinned))
        meta=json.loads((self.root/"harness-herdr-hooks/codex-adapter/adapter.json").read_text())
        manifest=json.loads((self.root/".harness-herdr-hooks.json").read_text())
        binding=meta["client_binding"]
        self.assertEqual(meta["native_executable"],str(self.native.resolve()))
        self.assertEqual(binding["native_executable"],str(pinned.resolve()))
        self.assertEqual(binding["capability_marker"],"herdr-client-binding-v1")
        self.assertEqual(binding["sha256"],hashlib.sha256(pinned.read_bytes()).hexdigest())
        self.assertEqual(manifest["entries"]["codex"]["client_binding"],binding)

        other=Path(self.tmp.name)/"conflicting-profile"; other.mkdir(mode=0o700)
        for command in ("herdr codex session reporter", "bash '/selected/profile/herdr-agent-state.sh'"):
            with self.subTest(command=command):
                (other/"hooks.json").write_text(json.dumps({"hooks":{"SessionStart":[{"hooks":[
                    {"type":"command","command":command}]}]}}))
                with patch.dict(os.environ,{"PATH":str(self.bin)}), self.assertRaisesRegex(InstallError,"legacy Herdr Codex"):
                    install("codex",source_root=self.source,config_dir=str(other),client_binding_codex=str(pinned))

    def test_install_registers_session_start_only_and_profile_adapter_then_uninstalls(self):
        hooks = self.root / "hooks.json"
        hooks.write_text(json.dumps({"hooks": {"UserEvent": [{"hooks": [{"type": "command", "command": "keep"}]}]}}))
        with patch.dict(os.environ, {"PATH": str(self.bin)}):
            result = install("codex", source_root=self.source, config_dir=str(self.root))
        data = json.loads(hooks.read_text())
        self.assertEqual(set(data["hooks"]) - {"UserEvent"}, {"SessionStart"})
        self.assertEqual(data["hooks"]["UserEvent"][0]["hooks"][0]["command"], "keep")
        adapter = self.root / "harness-herdr-hooks" / "codex-adapter"
        meta = json.loads((adapter / "adapter.json").read_text())
        self.assertEqual(meta["native_executable"], str(self.native.resolve()))
        self.assertEqual(os.stat(adapter / "codex").st_mode & 0o777, 0o700)
        self.assertEqual(json.loads((self.root / ".harness-herdr-hooks.json").read_text())["entries"]["codex"]["handlers"].keys(),
                         {"SessionStart"})
        self.assertEqual(status("codex", config_dir=str(self.root))["trust"], "unknown")
        uninstall("codex", config_dir=str(self.root))
        self.assertFalse((adapter / "codex").exists())
        self.assertTrue((self.root / "hooks.json").exists())

    def test_reinstall_with_managed_path_in_environment_keeps_native_and_path_stable(self):
        self.native.write_text("#!/bin/sh\nprintf 'native-codex %s\\n' \"$1\"\n")
        self.native.chmod(0o700)
        adapter=self.root/"harness-herdr-hooks"/"codex-adapter"
        with patch.dict(os.environ,{"PATH":str(self.bin)}):
            install("codex",source_root=self.source,config_dir=str(self.root))
        config=self.root/"config.toml"
        before=config.read_bytes(); own=json.loads((self.root/".harness-herdr-hooks.json").read_text())["entries"]["codex"]["path"]
        with patch.dict(os.environ,{"PATH":own["installed_path"]}):
            install("codex",source_root=self.source,config_dir=str(self.root))
        after=config.read_bytes(); own2=json.loads((self.root/".harness-herdr-hooks.json").read_text())["entries"]["codex"]["path"]
        meta=json.loads((adapter/"adapter.json").read_text())
        self.assertEqual(before,after)
        self.assertEqual(own["installed_path"],own2["installed_path"])
        self.assertEqual(meta["native_executable"],str(self.native.resolve()))
        result=subprocess.run([str(adapter/"codex"),"--version"],capture_output=True,text=True,timeout=5,check=True)
        self.assertEqual(result.stdout,"native-codex --version\n")
        uninstall("codex",config_dir=str(self.root))
        restored=config.read_text()
        self.assertNotIn("PATH =",restored)

    def test_uninstall_recognizes_commented_path_table_and_restores_absent_path(self):
        config=self.root/"config.toml"
        original=b'# keep this comment\nmodel = "x"\n\n[shell_environment_policy.set]\nOTHER = "keep" # preserve me\n'
        config.write_bytes(original); config.chmod(0o640)
        with patch.dict(os.environ, {"PATH": str(self.bin)}):
            install("codex", source_root=self.source, config_dir=str(self.root))
        installed=config.read_bytes()
        self.assertIn(b'PATH = ',installed)
        # A valid semantic-equivalent header edit must not orphan the managed PATH.
        config.write_bytes(installed.replace(b"[shell_environment_policy.set]", b"[shell_environment_policy.set] # user note"))
        expected=original.replace(b"[shell_environment_policy.set]", b"[shell_environment_policy.set] # user note")
        uninstall("codex",config_dir=str(self.root))
        self.assertEqual(config.read_bytes(),expected)
        self.assertEqual(config.stat().st_mode&0o777,0o640)
        self.assertFalse((self.root/".harness-herdr-hooks.json").exists())
        self.assertFalse((self.root/"harness-herdr-hooks/codex-adapter/codex").exists())

    def test_uninstall_unsupported_commented_path_layout_preserves_ownership(self):
        with patch.dict(os.environ, {"PATH": str(self.bin)}):
            install("codex", source_root=self.source, config_dir=str(self.root))
        config=self.root/"config.toml"; hooks=self.root/"hooks.json"
        manifest=self.root/".harness-herdr-hooks.json"; adapter=self.root/"harness-herdr-hooks/codex-adapter"
        # TOML resolves this spelling to the same table, but it is outside the
        # supported byte-preserving header layout.
        bad=config.read_bytes().replace(b"[shell_environment_policy.set]", b'["shell_environment_policy".set] # note')
        config.write_bytes(bad)
        before=(config.read_bytes(),hooks.read_bytes(),manifest.read_bytes(),(adapter/"codex").read_bytes())
        with self.assertRaises(InstallError): uninstall("codex",config_dir=str(self.root))
        self.assertEqual((config.read_bytes(),hooks.read_bytes(),manifest.read_bytes(),(adapter/"codex").read_bytes()),before)

    def test_fresh_profile_skips_another_profiles_managed_adapter_on_path(self):
        other=Path(self.tmp.name)/"other-profile"; other.mkdir(mode=0o700)
        with patch.dict(os.environ,{"PATH":str(self.bin)}):
            install("codex",source_root=self.source,config_dir=str(other))
        foreign_adapter=other/"harness-herdr-hooks"/"codex-adapter"
        with patch.dict(os.environ,{"PATH":str(foreign_adapter)+os.pathsep+str(self.bin)}):
            install("codex",source_root=self.source,config_dir=str(self.root))
        native=json.loads((self.root/"harness-herdr-hooks"/"codex-adapter"/"adapter.json").read_text())["native_executable"]
        self.assertEqual(native,str(self.native.resolve()))

    def test_uninstall_manifest_publication_failure_rolls_back_all_owned_files(self):
        module = importlib.import_module("harness_herdr_hooks.install")
        from harness_herdr_hooks.install import _atomic_json as real_atomic_json
        with patch.dict(os.environ, {"PATH": str(self.bin)}):
            install("codex", source_root=self.source, config_dir=str(self.root))
        manifest=self.root/".harness-herdr-hooks.json"
        value=json.loads(manifest.read_text()); value["entries"]["opencode"]={"source":"kept","destination":"kept"}
        manifest.write_text(json.dumps(value,indent=2,sort_keys=True)+"\n"); manifest.chmod(0o600)
        hooks=self.root/"hooks.json"; config=self.root/"config.toml"
        adapter=self.root/"harness-herdr-hooks/codex-adapter"
        before={p:(p.read_bytes(),p.stat().st_mode&0o777) for p in (hooks,config,adapter/"codex",adapter/"adapter.json")}
        def fail_manifest(path,data,**kwargs):
            if path==manifest: raise OSError("injected manifest failure")
            return real_atomic_json(path,data,**kwargs)
        with patch.object(module,"_atomic_json",side_effect=fail_manifest), self.assertRaises(OSError):
            uninstall("codex",config_dir=str(self.root))
        self.assertEqual({p:(p.read_bytes(),p.stat().st_mode&0o777) for p in before},before)
        self.assertTrue(manifest.exists())
        self.assertFalse((self.root/".harness-herdr-hooks-transaction.json").exists())

    def test_uninstall_recovery_rolls_back_interrupted_owned_writes(self):
        from harness_herdr_hooks.install import _recover_transaction
        with patch.dict(os.environ, {"PATH": str(self.bin)}):
            install("codex", source_root=self.source, config_dir=str(self.root))
        adapter=self.root/"harness-herdr-hooks/codex-adapter"
        targets=[self.root/"hooks.json",self.root/"config.toml",adapter/"codex",adapter/"adapter.json"]
        records={}
        for target in targets:
            before=target.read_bytes(); mode=target.stat().st_mode&0o777
            after=b"interrupted uninstall"; target.write_bytes(after); target.chmod(mode)
            records[str(target)]={"before":before.hex(),"mode":mode,"after_sha256":hashlib.sha256(after).hexdigest()}
        manifest=self.root/".harness-herdr-hooks.json"; mbytes=manifest.read_bytes()
        records[str(manifest)]={"before":mbytes.hex(),"mode":0o600,"after_sha256":None,"after_absent":True}
        journal=self.root/".harness-herdr-hooks-transaction.json"
        journal.write_text(json.dumps({"schema":1,"records":records})); journal.chmod(0o600)
        _recover_transaction(self.root)
        self.assertEqual([target.read_bytes() for target in targets],[bytes.fromhex(records[str(t)]["before"]) for t in targets])
        self.assertFalse(journal.exists())

    def test_committed_uninstall_recovery_accepts_absent_manifest(self):
        from harness_herdr_hooks.install import _recover_transaction
        manifest=self.root/".harness-herdr-hooks.json"
        manifest.write_bytes(b'{"schema": 1, "entries": {"codex": {}}}\n'); manifest.chmod(0o600)
        config=self.root/"config.toml"; config.write_bytes(b"# committed\n"); config.chmod(0o600)
        journal=self.root/".harness-herdr-hooks-transaction.json"
        journal.write_text(json.dumps({"schema":1,"records":{
            str(manifest):{"before":b"before".hex(),"mode":0o600,"after_sha256":None,"after_absent":True},
            str(config):{"before":b"before config".hex(),"mode":0o600,"after_sha256":hashlib.sha256(b"# committed\n").hexdigest()}
        }})); journal.chmod(0o600)
        manifest.unlink()
        _recover_transaction(self.root)
        self.assertFalse(config.read_bytes()==b"before config")
        self.assertFalse(journal.exists())

    def test_uninstall_adapter_and_path_conflicts_leave_profile_bytes_and_modes(self):
        with patch.dict(os.environ, {"PATH": str(self.bin)}):
            install("codex", source_root=self.source, config_dir=str(self.root))
        hooks=self.root/"hooks.json"; config=self.root/"config.toml"
        adapter=self.root/"harness-herdr-hooks/codex-adapter"/"codex"
        hooks.chmod(0o640); config.chmod(0o640)
        hooks_before=(hooks.read_bytes(),hooks.stat().st_mode&0o777)
        config_before=(config.read_bytes(),config.stat().st_mode&0o777)
        adapter.write_bytes(b"changed owned shim"); adapter.chmod(0o700)
        adapter_before=(adapter.read_bytes(),adapter.stat().st_mode&0o777)
        with self.assertRaises(InstallError): uninstall("codex",config_dir=str(self.root))
        self.assertEqual((hooks.read_bytes(),hooks.stat().st_mode&0o777),hooks_before)
        self.assertEqual((config.read_bytes(),config.stat().st_mode&0o777),config_before)
        self.assertEqual((adapter.read_bytes(),adapter.stat().st_mode&0o777),adapter_before)
        adapter.write_bytes((self.source/"integrations/codex/codex").read_bytes()); adapter.chmod(0o700)
        config.write_bytes(config_before[0].replace(b"codex-adapter",b"foreign-adapter")); config.chmod(0o640)
        changed_config=(config.read_bytes(),config.stat().st_mode&0o777)
        with self.assertRaises(InstallError): uninstall("codex",config_dir=str(self.root))
        self.assertEqual((hooks.read_bytes(),hooks.stat().st_mode&0o777),hooks_before)
        self.assertEqual((config.read_bytes(),config.stat().st_mode&0o777),changed_config)

    def test_uninstall_rejects_replaced_config_symlink_before_any_mutation(self):
        with patch.dict(os.environ, {"PATH": str(self.bin)}):
            install("codex", source_root=self.source, config_dir=str(self.root))
        hooks=self.root/"hooks.json"; adapter=self.root/"harness-herdr-hooks/codex-adapter"
        target=Path(self.tmp.name)/"external-config.toml"; target.write_bytes(b"external bytes\n"); target.chmod(0o640)
        config=self.root/"config.toml"; config.unlink(); config.symlink_to(target)
        hooks_before=hooks.read_bytes(); adapter_before={p:p.read_bytes() for p in adapter.iterdir()}
        with self.assertRaises(InstallError): uninstall("codex",config_dir=str(self.root))
        self.assertTrue(config.is_symlink()); self.assertEqual(config.resolve(),target)
        self.assertEqual(target.read_bytes(),b"external bytes\n"); self.assertEqual(target.stat().st_mode&0o777,0o640)
        self.assertEqual(hooks.read_bytes(),hooks_before)
        self.assertEqual({p:p.read_bytes() for p in adapter.iterdir()},adapter_before)

    def test_recovery_restores_absent_config_and_preserves_existing_empty_config(self):
        from harness_herdr_hooks.install import _recover_transaction
        config=self.root/"config.toml"; config.write_bytes(b""); config.chmod(0o600)
        after=b"published config"; config.write_bytes(after)
        journal=self.root/".harness-herdr-hooks-transaction.json"
        journal.write_text(json.dumps({"schema":1,"records":{
            str(config):{"before":None,"before_exists":False,"mode":0o600,"after_sha256":hashlib.sha256(after).hexdigest()}
        }})); journal.chmod(0o600)
        _recover_transaction(self.root)
        self.assertFalse(config.exists()); self.assertFalse(journal.exists())
        config.write_bytes(b""); config.chmod(0o600)
        after=b"published config"; config.write_bytes(after)
        journal.write_text(json.dumps({"schema":1,"records":{
            str(config):{"before":"","before_exists":True,"mode":0o600,"after_sha256":hashlib.sha256(after).hexdigest()}
        }})); journal.chmod(0o600)
        _recover_transaction(self.root)
        self.assertTrue(config.exists()); self.assertEqual(config.read_bytes(),b"")

    def test_recovery_preserves_config_symlink_replacement(self):
        from harness_herdr_hooks.install import _recover_transaction
        config=self.root/"config.toml"; target=Path(self.tmp.name)/"external.toml"
        target.write_bytes(b"after image"); config.symlink_to(target)
        journal=self.root/".harness-herdr-hooks-transaction.json"
        journal.write_text(json.dumps({"schema":1,"records":{
            str(config):{"before":b"before".hex(),"before_exists":True,"mode":0o600,"after_sha256":hashlib.sha256(b"after image").hexdigest()}
        }})); journal.chmod(0o600)
        with self.assertRaises(InstallError): _recover_transaction(self.root)
        self.assertTrue(config.is_symlink()); self.assertEqual(target.read_bytes(),b"after image")

    def test_reinstall_and_legacy_three_hook_upgrade_are_idempotent(self):
        hooks = self.root / "hooks.json"
        command = str(self.source / "bin/harness-herdr-hooks") + " codex-hook"
        old = {"type": "command", "command": command, "timeout": 5, "async": True}
        independent={"type":"command","command":"user-owned"}
        hooks.write_text(json.dumps({"hooks": {
            "SessionStart": [{"hooks": [old]}],
            "SubagentStart": [{"hooks": [old, independent]}],
            "SubagentStop": [{"hooks": [old]}],
        }}))
        manifest = self.root / ".harness-herdr-hooks.json"
        # A previous managed 3-hook install is represented by its ownership record.
        from harness_herdr_hooks.install import _read_manifest
        data = _read_manifest(manifest)
        data["entries"]["codex"] = {"handlers": {event: old for event in ("SessionStart", "SubagentStart", "SubagentStop")}}
        manifest.write_text(json.dumps(data)); manifest.chmod(0o600)
        with patch.dict(os.environ, {"PATH": str(self.bin)}):
            install("codex", source_root=self.source, config_dir=str(self.root))
            install("codex", source_root=self.source, config_dir=str(self.root))
        installed = json.loads(hooks.read_text())["hooks"]
        self.assertEqual(sum(1 for g in installed["SessionStart"] for h in g["hooks"] if h.get("command") == command), 1)
        self.assertEqual(sum(1 for group in installed.get("SubagentStart", []) for item in group["hooks"]
                             if item.get("command") == command), 0)
        self.assertNotIn("SubagentStop", installed)
        self.assertEqual(installed["SubagentStart"][0]["hooks"], [independent])

    def test_changed_owned_handler_and_unmanaged_conflict_fail_closed(self):
        install("codex", source_root=self.source, config_dir=str(self.root))
        hooks = self.root / "hooks.json"
        value = json.loads(hooks.read_text())
        value["hooks"]["SessionStart"][0]["hooks"][0]["command"] = "user edit"
        hooks.write_text(json.dumps(value))
        hooks.chmod(0o640)
        config = self.root / "config.toml"
        hook_before, config_before = hooks.read_bytes(), config.read_bytes()
        hook_mode, config_mode = hooks.stat().st_mode & 0o777, config.stat().st_mode & 0o777
        adapter = self.root / "harness-herdr-hooks/codex-adapter"
        adapter_before = {p.name: p.read_bytes() for p in adapter.iterdir() if p.is_file()}
        with self.assertRaises(InstallError):
            install("codex", source_root=self.source, config_dir=str(self.root))
        self.assertEqual(hooks.read_bytes(), hook_before)
        self.assertEqual(config.read_bytes(), config_before)
        self.assertEqual(hooks.stat().st_mode & 0o777, hook_mode)
        self.assertEqual(config.stat().st_mode & 0o777, config_mode)
        self.assertEqual({p.name: p.read_bytes() for p in adapter.iterdir() if p.is_file()}, adapter_before)

    def test_unmanaged_adapter_conflict_precedes_profile_mutation(self):
        parent = self.root / "harness-herdr-hooks"
        adapter = parent / "codex-adapter"
        adapter.mkdir(parents=True, mode=0o700)
        shim = adapter / "codex"
        shim.write_bytes(b"foreign adapter")
        shim.chmod(0o640)
        hooks = self.root / "hooks.json"
        hooks.write_bytes(b'{"hooks": {"SessionStart": [{"hooks": [{"type": "command", "command": "conflict"}]}]}}\n')
        hooks.chmod(0o640)
        before = {p: (p.read_bytes(), p.stat().st_mode & 0o777) for p in (shim, hooks)}
        directory_modes = {p: p.stat().st_mode & 0o777 for p in (parent, adapter)}
        with patch.dict(os.environ, {"PATH": str(self.bin)}), self.assertRaises(InstallError):
            install("codex", source_root=self.source, config_dir=str(self.root))
        self.assertEqual({p: (p.read_bytes(), p.stat().st_mode & 0o777) for p in (shim, hooks)}, before)
        self.assertFalse((self.root / "config.toml").exists())
        self.assertEqual({p: p.stat().st_mode & 0o777 for p in (parent, adapter)}, directory_modes)

    def test_symlinked_adapter_parent_is_refused_without_profile_changes(self):
        outside = Path(self.tmp.name) / "outside"
        outside.mkdir(mode=0o700)
        (self.root / "harness-herdr-hooks").symlink_to(outside, target_is_directory=True)
        hooks = self.root / "hooks.json"
        hooks.write_bytes(b'{"hooks": {}}\n')
        hooks.chmod(0o640)
        before = hooks.read_bytes(), hooks.stat().st_mode & 0o777
        with patch.dict(os.environ, {"PATH": str(self.bin)}), self.assertRaises(InstallError):
            install("codex", source_root=self.source, config_dir=str(self.root))
        self.assertEqual((hooks.read_bytes(), hooks.stat().st_mode & 0o777), before)
        self.assertFalse((self.root / "config.toml").exists())
        self.assertEqual(list(outside.iterdir()), [])

    def test_concurrent_hook_edit_is_rejected_by_compare_and_swap(self):
        install_module = importlib.import_module("harness_herdr_hooks.install")
        from harness_herdr_hooks.install import _atomic_json as real_atomic_json
        hooks = self.root / "hooks.json"
        original = b'{"hooks": {}}\n'
        hooks.write_bytes(original)
        hooks.chmod(0o640)
        config = self.root / "config.toml"
        concurrent = b'{"hooks": {"UserEvent": []}}\n'
        def racing_atomic(path, data, **kwargs):
            if path == hooks and hooks.read_bytes() == original:
                hooks.write_bytes(concurrent)
                hooks.chmod(0o640)
            return real_atomic_json(path, data, **kwargs)
        with patch.dict(os.environ, {"PATH": str(self.bin)}), patch.object(install_module, "_atomic_json", side_effect=racing_atomic):
            with self.assertRaisesRegex(InstallError, "changed during managed update"):
                install("codex", source_root=self.source, config_dir=str(self.root))
        self.assertEqual(hooks.read_bytes(), concurrent)
        self.assertEqual(hooks.stat().st_mode & 0o777, 0o640)
        self.assertFalse(config.exists())

    def test_opencode_install_is_retired(self):
        install("codex", source_root=self.source, config_dir=str(self.root))
        other = Path(self.tmp.name) / "other"
        other.mkdir(mode=0o700)
        with self.assertRaisesRegex(InstallError, "OpenCode installation is retired"):
            install("opencode", source_root=self.source, config_dir=str(other))
        self.assertFalse((other / "plugins/harness-herdr-hooks.js").exists())

    def test_legacy_opencode_link_status_and_uninstall_remain_ownership_checked(self):
        root=Path(self.tmp.name)/"legacy-opencode"; (root/"plugins").mkdir(parents=True)
        source=self.source/"integrations/opencode/plugin.js"
        dest=root/"plugins/harness-herdr-hooks.js"; dest.symlink_to(source)
        manifest=root/".harness-herdr-hooks.json"
        manifest.write_text(json.dumps({"schema":1,"entries":{"opencode":{"source":str(source),"destination":str(dest)}}}))
        manifest.chmod(0o600)
        self.assertEqual(status("opencode",config_dir=str(root))["status"],"installed")
        self.assertEqual(uninstall("opencode",config_dir=str(root))["action"],"unlinked")
        self.assertFalse(dest.is_symlink())
        self.assertFalse(manifest.exists())

    def test_next_install_recovers_interrupted_adapter_publication(self):
        with patch.dict(os.environ, {"PATH": str(self.bin)}):
            install("codex", source_root=self.source, config_dir=str(self.root))
            shim = self.root / "harness-herdr-hooks/codex-adapter/codex"
            before = shim.read_bytes()
            interrupted = b"partially published adapter"
            shim.write_bytes(interrupted)
            journal = self.root / ".harness-herdr-hooks-transaction.json"
            journal.write_text(json.dumps({"schema": 1, "records": {
                str(shim): {"before": before.hex(), "mode": 0o700,
                            "after_sha256": hashlib.sha256(interrupted).hexdigest()}
            }}))
            journal.chmod(0o600)
            install("codex", source_root=self.source, config_dir=str(self.root))
        self.assertFalse(journal.exists())
        self.assertEqual(shim.read_bytes(), (self.source / "integrations/codex/codex").read_bytes())

    def test_recovery_preserves_unrecognized_concurrent_adapter_edit(self):
        from harness_herdr_hooks.install import _recover_transaction
        shim = self.root / "harness-herdr-hooks/codex-adapter/codex"
        shim.parent.mkdir(parents=True)
        shim.write_bytes(b"concurrent edit")
        journal = self.root / ".harness-herdr-hooks-transaction.json"
        journal.write_text(json.dumps({"schema": 1, "records": {
            str(shim): {"before": b"original".hex(), "mode": 0o700,
                        "after_sha256": hashlib.sha256(b"expected after").hexdigest()}
        }}))
        journal.chmod(0o600)
        with self.assertRaises(InstallError):
            _recover_transaction(self.root)
        self.assertEqual(shim.read_bytes(), b"concurrent edit")

    def test_manifest_publication_failure_restores_config_and_keeps_mode(self):
        install_module = importlib.import_module("harness_herdr_hooks.install")
        from harness_herdr_hooks.install import _atomic_json as real_atomic_json
        manifest = self.root / ".harness-herdr-hooks.json"
        config = self.root / "config.toml"
        original = b"# profile\n"
        config.write_bytes(original); config.chmod(0o640)
        def fail_manifest(path, data, **kwargs):
            if path == manifest:
                raise OSError("injected manifest publication failure")
            return real_atomic_json(path, data, **kwargs)
        with patch.dict(os.environ, {"PATH": str(self.bin)}), patch.object(install_module, "_atomic_json", side_effect=fail_manifest):
            with self.assertRaises(OSError):
                install("codex", source_root=self.source, config_dir=str(self.root))
        self.assertEqual(config.read_bytes(), original)
        self.assertEqual(config.stat().st_mode & 0o777, 0o640)
        self.assertFalse((self.root / ".harness-herdr-hooks-path-journal.json").exists())

    def test_committed_manifest_recovery_clears_path_journal_without_rollback(self):
        from harness_herdr_hooks.install import _recover_transaction
        manifest = self.root / ".harness-herdr-hooks.json"
        config = self.root / "config.toml"
        manifest_after = b'{"schema": 1, "entries": {"codex": {}}}\n'
        config_after = b"[shell_environment_policy.set]\nPATH = \"adapter:/bin\"\n"
        manifest.write_bytes(manifest_after); manifest.chmod(0o600)
        config.write_bytes(config_after); config.chmod(0o640)
        path_journal = self.root / ".harness-herdr-hooks-path-journal.json"
        path_journal.write_text("{}")
        transaction = self.root / ".harness-herdr-hooks-transaction.json"
        transaction.write_text(json.dumps({"schema": 1, "records": {
            str(manifest): {"before": None, "mode": 0o600, "after_sha256": hashlib.sha256(manifest_after).hexdigest()},
            str(config): {"before": b"# old\n".hex(), "before_sha256": hashlib.sha256(b"# old\n").hexdigest(),
                          "mode": 0o640, "after_sha256": hashlib.sha256(config_after).hexdigest()},
        }})); transaction.chmod(0o600)
        _recover_transaction(self.root)
        self.assertEqual(config.read_bytes(), config_after)
        self.assertFalse(path_journal.exists())
        self.assertFalse(transaction.exists())

    def test_recovery_after_config_publication_restores_preimage_before_adapter(self):
        from harness_herdr_hooks.install import _recover_transaction
        config = self.root / "config.toml"
        before, after = b"# original\n", b"# original\n[shell_environment_policy.set]\nPATH = \"adapter:/bin\"\n"
        config.write_bytes(after); config.chmod(0o640)
        path_journal = self.root / ".harness-herdr-hooks-path-journal.json"
        path_journal.write_text("{}")
        transaction = self.root / ".harness-herdr-hooks-transaction.json"
        transaction.write_text(json.dumps({"schema": 1, "records": {
            str(config): {"before": before.hex(), "before_sha256": hashlib.sha256(before).hexdigest(),
                          "mode": 0o640, "after_sha256": hashlib.sha256(after).hexdigest()}
        }})); transaction.chmod(0o600)
        _recover_transaction(self.root)
        self.assertEqual(config.read_bytes(), before)
        self.assertEqual(config.stat().st_mode & 0o777, 0o640)
        self.assertFalse(path_journal.exists())

    def test_concurrent_config_edit_during_install_is_preserved_with_mode(self):
        config_module = importlib.import_module("harness_herdr_hooks.codex_config")
        from harness_herdr_hooks.codex_config import _atomic as real_atomic
        config = self.root / "config.toml"
        original = b"# original\n"
        concurrent = b"# concurrent profile edit\n"
        config.write_bytes(original); config.chmod(0o640)
        def race_config(path, raw, mode, **kwargs):
            if path == config and config.read_bytes() == original:
                config.write_bytes(concurrent); config.chmod(0o640)
            return real_atomic(path, raw, mode, **kwargs)
        with patch.dict(os.environ, {"PATH": str(self.bin)}), patch.object(config_module, "_atomic", side_effect=race_config):
            with self.assertRaises(InstallError):
                install("codex", source_root=self.source, config_dir=str(self.root))
        self.assertEqual(config.read_bytes(), concurrent)
        self.assertEqual(config.stat().st_mode & 0o777, 0o640)


if __name__ == "__main__":
    unittest.main()
