import sys
import json
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from reader_client import Client, GhError, transport
from unittest.mock import patch

class ReaderTests(unittest.TestCase):
    def client(self, responses):
        calls=[]
        def run(args,payload=None):
            calls.append((args,payload))
            key=args[5] if args[0]=='api' else 'logs'
            value=responses[key]
            if isinstance(value,Exception): raise value
            return value if isinstance(value,str) else json.dumps(value)
        return Client(run), calls

    def test_notification_targets_are_restricted(self):
        c=Client()
        good={'repo':'owner/repo','kind':'notification','subjectUrl':'https://api.github.com/repos/owner/repo/pulls/123'}
        self.assertEqual(c.target(good),{'repo':'owner/repo','kind':'pull-request','number':123})
        for url in ['https://evil.test/repos/owner/repo/pulls/123',
                    'https://api.github.com/repos/other/repo/pulls/123',
                    'https://api.github.com@evil.test/repos/owner/repo/pulls/123',
                    'https://api.github.com/repos/owner/repo/pulls/123?foo=bar',
                    'https://api.github.com/repos/owner/repo/pulls/$(touch nope)']:
            with self.subTest(url=url), self.assertRaises(GhError): c.target({**good,'subjectUrl':url})
        for repo in ['../repo','--help','owner/repo/extra','owner/..']:
            with self.assertRaises(GhError): c.target({'repo':repo,'kind':'issue','number':1})

    def test_check_notification_without_url_falls_back_explicitly(self):
        t=Client().target({'repo':'a/b','kind':'notification','subjectType':'CheckSuite','subjectUrl':'','url':'https://github.com/a/b'})
        self.assertTrue(t['notificationFallback'])
        self.assertEqual(t['kind'],'ci')

    def test_issue_preserves_body_and_pages_comments(self):
        c,calls=self.client({'repos/a/b/issues/4':{'title':'Issue','body':'# Title\n\nFull body','comments':31,'user':{'login':'a'},'state':'open'},
                            'repos/a/b/issues/4/comments?per_page=30&page=1':[{'body':'line1\nline2','user':{'login':'b'},'created_at':'today'}]})
        d=c.detail({'repo':'a/b','kind':'issue','number':4})
        self.assertEqual(d['body'],'# Title\n\nFull body')
        self.assertEqual(d['tabs'][0]['blocks'][0]['body'],'line1\nline2')
        self.assertEqual(d['nextPage'],2)
        self.assertTrue(d['canReply'])
        self.assertTrue(all(args[4]=='GET' for args,payload in calls))

    def test_pr_context_and_partial_failure(self):
        c,calls=self.client({'repos/a/b/issues/4':{'title':'PR','pull_request':{},'body':'x','comments':0},
                            'repos/a/b/issues/4/comments?per_page=30&page=1':[],
                            'repos/a/b/pulls/4':GhError('No access to PR')})
        d=c.detail({'repo':'a/b','kind':'pull-request','number':4})
        self.assertEqual(d['body'],'x');self.assertEqual(d['warnings'],['No access to PR'])
        self.assertEqual(d['tabs'][0]['id'],'conversation')

    def test_issue_notification_resolves_pr(self):
        c,calls=self.client({'repos/a/b/issues/4':{'title':'PR','pull_request':{'url':'x'},'comments':0},
                            'repos/a/b/issues/4/comments?per_page=30&page=1':[],
                            'repos/a/b/pulls/4':GhError('limited')})
        d=c.detail({'repo':'a/b','kind':'notification','id':'notification:77','url':'https://github.com/a/b/issues/4'})
        self.assertEqual(d['target']['kind'],'pull-request'); self.assertEqual(d['threadId'],'77')

    def test_reply_exact_body_and_no_shell_interpolation(self):
        c,calls=self.client({'repos/a/b/issues/4/comments':{'id':99}})
        text='a\n\n`code` $(touch /tmp/not-executed) "quoted" @someone'
        r=c.action({'action':'reply','item':{'repo':'a/b','kind':'issue','number':4},'body':text})
        args,payload=calls[0]
        self.assertEqual(payload,{'body':text})
        self.assertEqual(args,['api','--hostname','github.com','-X','POST','repos/a/b/issues/4/comments','--input','-'])
        self.assertTrue(r['ok'])

    def test_mark_read_is_exact_thread_only(self):
        c,calls=self.client({'notifications/threads/77':''})
        c.action({'action':'mark-read','item':{'id':'notification:77'}})
        self.assertEqual(calls[0][0][4:6],['PATCH','notifications/threads/77'])
        with self.assertRaises(GhError): c.action({'action':'mark-read','item':{'id':'notification:../../notifications'}})
        self.assertEqual(len(calls),1)

    def test_invalid_actions_never_call_github(self):
        c,calls=self.client({})
        for req in [{'action':'merge'}, {'action':'reply','body':' '}, {'action':'reply','body':'x'*60001}]:
            with self.assertRaises(GhError): c.action(req)
        self.assertEqual(calls,[])

    def test_discussion_nested_replies_and_cursor(self):
        node={'id':'D_1','title':'Discussion','body':'text','locked':False,
              'comments':{'pageInfo':{'hasNextPage':True,'endCursor':'NEXT'},'nodes':[
                {'body':'parent','author':{'login':'a'},'replies':{'totalCount':1,'nodes':[{'body':'reply','author':{'login':'b'}}]}}]}}
        c,calls=self.client({'graphql':{'data':{'repository':{'discussion':node}}}})
        d=c.detail({'repo':'a/b','kind':'discussion','number':1},cursor='PREV')
        self.assertEqual(d['nextCursor'],'NEXT'); self.assertEqual(len(d['tabs'][0]['blocks']),2)
        self.assertEqual(calls[0][1]['variables']['cursor'],'PREV')

    def test_run_jobs_have_internal_log_targets(self):
        c,calls=self.client({'repos/a/b/actions/runs/1':{'name':'build','status':'completed'},
            'repos/a/b/actions/runs/1/jobs?per_page=100':{'jobs':[{'id':2,'name':'tests','status':'completed','conclusion':'failure','steps':[{'name':'unit','conclusion':'failure'}]}]}})
        d=c.detail({'repo':'a/b','kind':'run','number':1})
        b=d['tabs'][0]['blocks'][0]
        self.assertEqual(b['action'],{'kind':'job','repo':'a/b','number':2})
        self.assertIn('failure: unit',b['body'])

    def test_action_error_does_not_report_success(self):
        c,calls=self.client({'repos/a/b/issues/4/comments':GhError('Permission denied')})
        with self.assertRaisesRegex(GhError,'Permission denied'):
            c.action({'action':'reply','item':{'kind':'issue','repo':'a/b','number':4},'body':'test'})

    def test_transport_passes_json_via_stdin(self):
        from types import SimpleNamespace
        with patch('reader_client.subprocess.run',return_value=SimpleNamespace(returncode=0,stdout=b'{}',stderr=b'')) as run:
            transport(['api','graphql','--input','-'],{'body':'\n@hi `x`'})
        self.assertEqual(json.loads(run.call_args.kwargs['input']),{'body':'\n@hi `x`'})
        self.assertNotIn('shell',run.call_args.kwargs)

if __name__=='__main__': unittest.main()
