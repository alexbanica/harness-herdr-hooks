import os, tempfile, unittest
from pathlib import Path
from harness_herdr_hooks.codex_config import ConfigError, install_path, restore_path, recover_path_journal, _edit

class CodexConfigTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory(); self.root=Path(self.tmp.name)/'profile'; self.root.mkdir(mode=0o700)
  self.adapter=self.root/'adapter'; self.adapter.mkdir(); self.bin=Path(self.tmp.name)/'bin'; self.bin.mkdir()
  exe=self.bin/'codex'; exe.write_text('#!/bin/sh\n'); exe.chmod(0o700)
  self.envpath=str(self.bin)+os.pathsep+'/usr/bin'
 def tearDown(self): self.tmp.cleanup()
 def test_absent_config_uses_concrete_original_path_and_restore(self):
  owned=install_path(self.root,self.adapter,env_path=self.envpath)
  raw=(self.root/'config.toml').read_text(); self.assertIn('PATH = '+repr(owned['installed_path']),raw.replace('"','\''))
  self.assertEqual(owned['native_executable'],str((self.bin/'codex').resolve()))
  self.assertEqual(restore_path(owned),'restored'); self.assertNotIn('PATH =',(self.root/'config.toml').read_text())
 def test_preserves_bytes_comment_mode_and_restores_after_unrelated_edit(self):
  path=self.root/'config.toml'; original=b'# keep me\nmodel = "x"\n\n[shell_environment_policy.set]\nPATH = "/usr/bin:/bin" # owned field\n'
  path.write_bytes(original); path.chmod(0o640)
  owned=install_path(self.root,self.adapter,env_path=self.envpath)
  after=path.read_bytes(); self.assertIn(b'# keep me\nmodel = "x"',after); self.assertIn(b'# owned field',after); self.assertEqual(path.stat().st_mode&0o777,0o640)
  path.write_bytes(after+b'\n[other]\nkey = "new"\n')
  restore_path(owned); result=path.read_bytes(); self.assertIn(b'PATH = "/usr/bin:/bin" # owned field',result); self.assertIn(b'key = "new"',result)
 def test_reinstall_is_idempotent_and_conflict_is_preserved(self):
  p=self.root/'config.toml'; p.write_text('[shell_environment_policy.set]\nPATH="/usr/bin"\n')
  own=install_path(self.root,self.adapter,env_path=self.envpath); own2=install_path(self.root,self.adapter,env_path=self.envpath,ownership=own)
  self.assertEqual(own['installed_path'],own2['installed_path'])
  p.write_text(p.read_text().replace(own['installed_path'],'/user/changed'))
  changed=p.read_bytes()
  with self.assertRaises(ConfigError): restore_path(own)
  self.assertEqual(p.read_bytes(),changed)
 def test_duplicate_or_ambiguous_toml_and_symlink_fail_closed(self):
  p=self.root/'config.toml'; p.write_text('[shell_environment_policy.set]\nPATH="/usr/bin"\n[shell_environment_policy.set]\nPATH="/bin"\n')
  with self.assertRaises(ConfigError): install_path(self.root,self.adapter,env_path=self.envpath)
  p.unlink(); target=self.root/'target'; target.write_text(''); p.symlink_to(target)
  with self.assertRaises(ConfigError): install_path(self.root,self.adapter,env_path=self.envpath)
 def test_interrupted_owned_edit_recovers_only_exact_after_image(self):
  path=self.root/'config.toml'; before=b'model = "x"\n'; path.write_bytes(before); path.chmod(0o600)
  installed=_edit(before,str(self.adapter)+os.pathsep+self.envpath); path.write_bytes(installed)
  import hashlib,json
  journal={"schema":1,"before_sha256":hashlib.sha256(before).hexdigest(),"after_sha256":hashlib.sha256(installed).hexdigest(),"before_exists":True,"before_mode":0o600,"before_bytes":before.hex(),"after_bytes":installed.hex()}
  (self.root/'.harness-herdr-hooks-path-journal.json').write_text(json.dumps(journal)); (self.root/'.harness-herdr-hooks-path-journal.json').chmod(0o600)
  self.assertEqual(recover_path_journal(self.root),'recovered'); self.assertEqual(path.read_bytes(),before)
  path.write_bytes(installed); (self.root/'.harness-herdr-hooks-path-journal.json').write_text(json.dumps(journal)); (self.root/'.harness-herdr-hooks-path-journal.json').chmod(0o600)
  path.write_bytes(installed+b'# concurrent\n'); self.assertEqual(recover_path_journal(self.root),'conflict-preserved')
 def test_path_journal_recovers_config_absence_and_keeps_existing_empty_file(self):
  import hashlib,json
  path=self.root/'config.toml'; installed=_edit(b'',str(self.adapter)+os.pathsep+self.envpath); path.write_bytes(installed); path.chmod(0o600)
  journal={'schema':1,'before_sha256':hashlib.sha256(b'').hexdigest(),'after_sha256':hashlib.sha256(installed).hexdigest(),'before_exists':False,'before_mode':0o600,'before_bytes':'','after_bytes':installed.hex()}
  jp=self.root/'.harness-herdr-hooks-path-journal.json'; jp.write_text(json.dumps(journal)); jp.chmod(0o600)
  self.assertEqual(recover_path_journal(self.root),'recovered'); self.assertFalse(path.exists())
  path.write_bytes(b''); path.chmod(0o600); own=install_path(self.root,self.adapter,env_path=self.envpath)
  self.assertEqual(restore_path(own),'restored'); self.assertTrue(path.exists()); self.assertNotIn(b'PATH =',path.read_bytes())
 def test_adds_path_inside_existing_set_table_and_restore_keeps_path_extra(self):
  p=self.root/'config.toml'; p.write_text('[shell_environment_policy.set]\nOTHER = "yes"\nPATH_EXTRA = "keep"\n')
  own=install_path(self.root,self.adapter,env_path=self.envpath)
  raw=p.read_text(); self.assertEqual(raw.count('[shell_environment_policy.set]'),1); self.assertIn('OTHER = "yes"',raw)
  restore_path(own); restored=p.read_text(); self.assertIn('PATH_EXTRA = "keep"',restored); self.assertNotIn('\nPATH =',restored)
 def test_journal_retained_until_manifest_commit_and_conflict_blocks_reinstall(self):
  from harness_herdr_hooks.codex_config import commit_path_journal
  own=install_path(self.root,self.adapter,env_path=self.envpath,retain_journal=True)
  journal=self.root/'.harness-herdr-hooks-path-journal.json'; self.assertTrue(journal.exists())
  commit_path_journal(self.root); self.assertFalse(journal.exists())
  journal.write_text('{"schema":1,"before_sha256":"bad","after_sha256":"bad","before_exists":true,"before_mode":384,"before_bytes":"","after_bytes":""}'); journal.chmod(0o600)
  with self.assertRaises(ConfigError): install_path(self.root,self.adapter,env_path=self.envpath,ownership=own)
 def test_non_string_path_and_unsupported_dotted_layout_fail_closed(self):
  p=self.root/'config.toml'; p.write_text('[shell_environment_policy.set]\nPATH=["/bin"]\n')
  with self.assertRaises(ConfigError): install_path(self.root,self.adapter,env_path=self.envpath)
  p.write_text('shell_environment_policy.set.PATH = "/bin"\n')
  with self.assertRaises(ConfigError): install_path(self.root,self.adapter,env_path=self.envpath)
if __name__=='__main__': unittest.main()
