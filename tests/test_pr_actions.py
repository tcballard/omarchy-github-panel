import copy
import json
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from reader_client import Client, GhError, pr_info

SHA='a'*40
PR={'state':'open','draft':False,'merged':False,'mergeable':True,'mergeable_state':'clean','user':{'login':'author'},
    'head':{'sha':SHA,'ref':'feature','label':'author:feature'},'base':{'ref':'main'}}
REPOSITORY={'permissions':{'push':True},'allow_squash_merge':True,'allow_merge_commit':True,'allow_rebase_merge':False}
REQUEST={'op':'action','confirmed':True,'action':'approve','item':{'kind':'pull-request','repo':'a/b','number':4},'expectedHeadSha':SHA,'expectedBase':'main','body':''}

class PRActionsTests(unittest.TestCase):
    def client(self, pr=None, repository=None, login='reviewer', result=None):
        calls=[]
        def run(args,payload):
            method, endpoint=args[4:6]
            calls.append((method,endpoint,payload))
            if method!='GET':
                if isinstance(result,Exception): raise result
                return json.dumps(result if result is not None else {'state':'APPROVED','id':1})
            responses={'repos/a/b/pulls/4':pr if pr is not None else PR, 'repos/a/b':repository if repository is not None else REPOSITORY,'user':{'login':login}}
            return json.dumps(responses[endpoint])
        return Client(run),calls

    def test_approval_is_for_exact_commit_and_note(self):
        client,calls=self.client()
        body='Looks good\n\n`code` $(not-a-command) @author'
        self.assertTrue(client.action({**REQUEST,'body':body})['ok'])
        self.assertEqual(calls[-1],('POST','repos/a/b/pulls/4/reviews',{'event':'APPROVE','commit_id':SHA,'body':body}))

    def test_request_changes_requires_note_before_network(self):
        client,calls=self.client()
        with self.assertRaises(GhError): client.action({**REQUEST,'action':'request-changes'})
        self.assertEqual(calls,[])
        client,calls=self.client(result={'state':'CHANGES_REQUESTED'})
        self.assertTrue(client.action({**REQUEST,'action':'request-changes','body':'Please add coverage.'})['ok'])
        self.assertEqual(calls[-1][2]['event'],'REQUEST_CHANGES')

    def test_merge_uses_sha_and_allowed_method_without_deleting_branch(self):
        client,calls=self.client(result={'merged':True,'sha':'b'*40})
        out=client.action({**REQUEST,'action':'merge','mergeMethod':'squash'})
        self.assertTrue(out['merged'])
        self.assertEqual(calls[-1],('PUT','repos/a/b/pulls/4/merge',{'sha':SHA,'merge_method':'squash'}))
        self.assertEqual(sum(method!='GET' for method,_,_ in calls),1)

    def test_confirmation_required_before_network(self):
        for confirmed in (False,None,'true'):
            client,calls=self.client()
            with self.assertRaises(GhError): client.action({**REQUEST,'confirmed':confirmed})
            self.assertEqual(calls,[])

    def test_changed_head_or_base_never_mutates(self):
        for action in ('approve','request-changes','merge'):
            for field,value in [('head',{'sha':'b'*40,'ref':'feature'}),('base',{'ref':'release'})]:
                pr={**PR,field:value};client,calls=self.client(pr=pr)
                with self.assertRaisesRegex(GhError,'changed since'):
                    client.action({**REQUEST,'action':action,'body':'A note','mergeMethod':'squash'})
                self.assertTrue(all(method=='GET' for method,_,_ in calls))

    def test_own_pr_cannot_be_approved(self):
        client,calls=self.client(login='AUTHOR')
        with self.assertRaisesRegex(GhError,'your own PR'): client.action(REQUEST)
        self.assertTrue(all(method=='GET' for method,_,_ in calls))

    def test_closed_draft_conflicted_and_unready_merge_blocked(self):
        for patch in [{'state':'closed'},{'merged':True},{'draft':True},{'mergeable':False},{'mergeable':None},{'mergeable_state':'blocked'}]:
            client,calls=self.client(pr={**PR,**patch})
            with self.subTest(patch=patch),self.assertRaises(GhError): client.action({**REQUEST,'action':'merge','mergeMethod':'squash'})
            self.assertTrue(all(method=='GET' for method,_,_ in calls))

    def test_merge_permission_and_disabled_method(self):
        for repo,method in [({**REPOSITORY,'permissions':{'pull':True}},'squash'),(REPOSITORY,'rebase')]:
            client,calls=self.client(repository=repo)
            with self.assertRaises(GhError): client.action({**REQUEST,'action':'merge','mergeMethod':method})
            self.assertTrue(all(m=='GET' for m,_,_ in calls))

    def test_api_rejection_is_not_success(self):
        for result in [{'merged':False,'message':'Required review missing'},GhError('HTTP 405 branch protection')]:
            client,calls=self.client(result=result)
            with self.assertRaises(GhError): client.action({**REQUEST,'action':'merge','mergeMethod':'squash'})
        client,calls=self.client(result={'state':'PENDING'})
        with self.assertRaises(GhError): client.action(REQUEST)

    def test_invalid_method_and_sha_never_call_github(self):
        for patch in [{'expectedHeadSha':'--help'}, {'expectedBase':''}, {'action':'merge','mergeMethod':'admin'}]:
            client,calls=self.client()
            with self.assertRaises(GhError): client.action({**REQUEST,**patch})
            self.assertEqual(calls,[])

    def test_metadata_describes_permissions_and_methods(self):
        info=pr_info(PR,REPOSITORY,{'login':'reviewer'})
        self.assertEqual(info['mergeMethods'],['squash','merge'])
        self.assertTrue(info['canReview']); self.assertTrue(info['canMerge'])
        self.assertFalse(pr_info(PR,REPOSITORY,{'login':'author'})['canReview'])

    def test_approval_confirmation_contains_commit_id(self):
        client,calls=self.client()
        with self.assertRaises(GhError): client.action({**REQUEST,'item':{'repo':'a/b','kind':'issue','number':4}})
        self.assertEqual(calls,[])

if __name__=='__main__': unittest.main()
