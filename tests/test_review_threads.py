import copy,json,sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from reader_client import Client,GhError
import review_threads as rt
from test_pr_actions import PR,SHA
PATCH='@@ -4,3 +4,3 @@\n same\n-old\n+new\n end\n\\ No newline at end of file\n@@ -20 +20,2 @@\n x\n+y'
FILE={'filename':'file.py','patch':PATCH}
THREAD={'id':'PRRT_1','path':'file.py','line':5,'originalLine':5,'diffSide':'RIGHT','isResolved':False,'isOutdated':False,
        'viewerCanResolve':True,'viewerCanUnresolve':True,'comments':{'totalCount':1,'nodes':[{'id':'C1','updatedAt':'now','body':'Please fix','author':{'login':'alice'},'diffHunk':PATCH}]},
        'pullRequest':{'number':9,'headRefOid':SHA,'baseRefName':'main','repository':{'nameWithOwner':'a/b'}}}
class InlineReviewTests(unittest.TestCase):
    def client(self,pr=None,thread=None,files=None,write=None):
        calls=[]
        def runner(args,payload):
            method,path=args[4:6];calls.append((method,path,payload))
            if method=='GET': return json.dumps({'repos/a/b/pulls/9':pr or PR,'repos/a/b/pulls/9/files?per_page=100':[FILE] if files is None else files}[path])
            if path=='graphql' and payload['query'].startswith('query'):
                return json.dumps({'data':{'node':thread or THREAD,'repository':{'pullRequest':{'reviewThreads':{'nodes':[thread or THREAD],'pageInfo':{'hasNextPage':False}}}}}})
            if isinstance(write,Exception):raise write
            return json.dumps(write or {})
        return Client(runner),calls
    def request(self,action='inline-comment',expected=None):
        return {'confirmed':True,'action':action,'item':{'repo':'a/b','kind':'pull-request','number':9},
                'expected':expected or {'headSha':SHA,'baseRef':'main','path':'file.py'},'values':{'location':'New line 5','body':'Change this\n`literal` $(code)'}}
    def writes(self,calls): return [x for x in calls if x[0]!='GET' and not (x[2] or {}).get('query','').startswith('query')]
    def test_diff_locations_cover_hunks_and_both_sides(self):
        locations,body=rt.diff_lines(PATCH)
        self.assertIn('Old line 5',locations);self.assertIn('New line 5',locations)
        self.assertIn('New line 21',locations);self.assertNotIn('New line 22',locations)
        self.assertIn('R    5 +new',body)
        self.assertEqual(rt.diff_lines('@@ -0,0 +1,2 @@\n+one\n+two')[0],['New line 1','New line 2'])
    def test_inline_payload_is_exact_commit_file_side_line_and_body(self):
        for location,side in [('New line 5','RIGHT'),('Old line 5','LEFT')]:
            client,calls=self.client(write={'id':1,'commit_id':SHA})
            req=self.request();req['values']['location']=location
            self.assertTrue(client.action(req)['ok'])
            self.assertEqual(self.writes(calls),[('POST','repos/a/b/pulls/9/comments',{'body':req['values']['body'],'commit_id':SHA,'path':'file.py','line':5,'side':side})])
    def test_invalid_or_changed_comment_target_never_writes(self):
        for patch in [{'confirmed':False},{'values':{'body':'','location':'New line 5'}},{'values':{'body':'x','location':'New line 500'}}]:
            client,calls=self.client()
            with self.assertRaises(GhError):client.action({**self.request(),**patch})
            self.assertEqual(self.writes(calls),[])
        for pr,files in [({**PR,'head':{'sha':'b'*40}},None),(PR,[]),({**PR,'state':'closed'},None)]:
            client,calls=self.client(pr=pr,files=files)
            with self.assertRaises(GhError):client.action(self.request())
            self.assertEqual(self.writes(calls),[])
    def test_binary_files_have_no_comment_control(self):
        self.assertEqual(rt.file_blocks([{'filename':'image.png'}],PR)[0]['operations'],[])
    def test_thread_actions_and_status_are_described(self):
        client,_=self.client()
        tab,warnings=rt.load_threads(client,'a/b',9,PR)
        self.assertIn('UNRESOLVED',tab['blocks'][0]['title'])
        self.assertEqual(tab['blocks'][0]['operations'][0]['id'],'resolve-thread')
        self.assertEqual(warnings,[])
    def test_resolve_and_reopen_exact_thread(self):
        for resolved,action,mutation in [(False,'resolve-thread','resolveReviewThread'),(True,'reopen-thread','unresolveReviewThread')]:
            thread={**THREAD,'isResolved':resolved}
            expected={**rt.stamp(thread),'headSha':SHA,'baseRef':'main'}
            client,calls=self.client(thread=thread,write={'data':{mutation:{'thread':{'id':'PRRT_1','isResolved':not resolved}}}})
            self.assertTrue(client.action(self.request(action,expected))['ok'])
            self.assertEqual(self.writes(calls)[0][2]['variables'],{'id':'PRRT_1'})
    def test_wrong_pr_changed_comments_or_permissions_block_resolution(self):
        expected={**rt.stamp(THREAD),'headSha':SHA,'baseRef':'main'}
        changed=copy.deepcopy(THREAD);changed['comments']['totalCount']=2
        for thread in [changed,{**THREAD,'viewerCanResolve':False},{**THREAD,'isResolved':True},
                       {**THREAD,'pullRequest':{**THREAD['pullRequest'],'number':10}}]:
            client,calls=self.client(thread=thread)
            with self.assertRaises(GhError):client.action(self.request('resolve-thread',expected))
            self.assertEqual(self.writes(calls),[])
    def test_failed_or_unconfirmed_mutation_is_not_retried(self):
        for response in [{},GhError('Permission denied')]:
            client,calls=self.client(write=response)
            with self.assertRaises(GhError):client.action(self.request())
            self.assertEqual(len(self.writes(calls)),1)

if __name__=='__main__':unittest.main()
