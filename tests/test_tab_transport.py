import unittest
from pathlib import Path

from harness_herdr_hooks.herdr import HerdrClient, HerdrError
class TabTransportFixtureTests(unittest.TestCase):
    def setUp(self):
        self.client = HerdrClient('/tmp/herdr-test.sock')
        self.cwd = Path('/tmp/child-work')
        self.requests = []

    def response(self, result):
        def request(method, params):
            self.requests.append((method, params))
            return result
        self.client.request = request

    def test_create_accepts_exact_unfocused_ack(self):
        self.response({'type':'tab_created', 'tab':{'tab_id':'t2','workspace_id':'w','focused':False,'label':'Subagents: main'},
                       'root_pane':{'pane_id':'p2','workspace_id':'w','tab_id':'t2','focused':False,'cwd':str(self.cwd)}})
        self.assertEqual(self.client.create_subagent_tab('w', self.cwd, 'Subagents: main'), ('t2','p2'))
        self.assertEqual(self.requests[0][1]['focus'], False)

    def test_create_rejects_wrong_workspace_or_cwd_and_label(self):
        for field, bad in [('workspace_id','wrong'),('cwd','/tmp/wrong'),('label','wrong')]:
            tab={'tab_id':'t2','workspace_id':'w','focused':False,'label':'Subagents: main'}
            pane={'pane_id':'p2','workspace_id':'w','tab_id':'t2','focused':False,'cwd':str(self.cwd)}
            if field=='workspace_id': tab[field]=bad
            elif field=='cwd': pane[field]=bad
            else: tab[field]=bad
            self.response({'type':'tab_created','tab':tab,'root_pane':pane})
            with self.subTest(field=field), self.assertRaises(HerdrError):
                self.client.create_subagent_tab('w',self.cwd,'Subagents: main')

    def test_split_rejects_wrong_tab_focus_cwd_and_target_reuse(self):
        for field,bad in [('tab_id','wrong'),('focused',True),('cwd','/tmp/wrong'),('pane_id','target')]:
            pane={'pane_id':'newpane','workspace_id':'w','tab_id':'t2','focused':False,'cwd':str(self.cwd)}
            if field=='pane_id': pane[field]=bad
            else: pane[field]=bad
            self.response({'type':'pane_info','pane':pane})
            with self.subTest(field=field), self.assertRaises(HerdrError):
                self.client.split_subagent_tab('target','w','t2',self.cwd)

    def test_create_rejects_acknowledged_different_label(self):
        self.response({'type':'tab_created', 'tab':{'tab_id':'t2','workspace_id':'w','focused':False,'label':'other'},
                       'root_pane':{'pane_id':'p2','workspace_id':'w','tab_id':'t2','focused':False,'cwd':str(self.cwd)}})
        with self.assertRaises(HerdrError):
            self.client.create_subagent_tab('w', self.cwd, 'requested')

    def test_rename_requires_exact_identity_label_and_unfocused_state(self):
        for field,bad in [('tab_id','wrong'),('workspace_id','wrong'),('label','wrong'),('focused','yes')]:
            tab={'tab_id':'t2','workspace_id':'w','label':'new label','focused':False}
            tab[field]=bad
            self.response({'type':'tab_info','tab':tab})
            with self.subTest(field=field), self.assertRaises(HerdrError):
                self.client.rename_subagent_tab('t2','w','new label')

    def test_rename_accepts_focus_state_without_mutating_focus(self):
        self.response({'type':'tab_info','tab':{'tab_id':'t2','workspace_id':'w','label':'new label','focused':True}})
        self.client.rename_subagent_tab('t2','w','new label')
        self.assertEqual(self.requests, [('tab.rename', {'tab_id':'t2','label':'new label'})])


if __name__ == '__main__':
    unittest.main()
