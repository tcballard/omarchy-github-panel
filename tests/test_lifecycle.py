import copy
import json
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from reader_client import Client, GhError
import lifecycle as lc
from test_pr_actions import PR, REPOSITORY, SHA

ISSUE = {'title':'Issue','body':'Original','state':'open','updated_at':'2026-09-05T12:00:00Z',
         'labels':[{'name':'bug'}], 'assignees':[{'login':'author'}]}
RUN = {'id':44,'head_sha':SHA,'run_attempt':2,'status':'completed','conclusion':'failure'}
JOB = {'id':55, 'run_id':44,'status':'completed'}
QUEUE = {'id':'PR_9','headRefOid':SHA,'baseRefName':'main','state':'OPEN','isDraft':False,
         'isMergeQueueEnabled':True,'viewerCanEnableAutoMerge':True,'viewerCanDisableAutoMerge':True,
         'autoMergeRequest':None,'mergeQueueEntry':None}

class LifecycleTests(unittest.TestCase):
    def client(self, pr=None, issue=None, run=None, queue=None, write=None):
        calls=[]
        pr = {**PR,'node_id':'PR_9'} if pr is None else pr
        issue = ISSUE if issue is None else issue
        run = RUN if run is None else run
        queue = QUEUE if queue is None else queue
        def runner(args, payload):
            method, path = args[4:6]
            calls.append((method,path,payload))
            if path == 'graphql' and payload['query'].startswith('query'):
                return json.dumps({'data':{'repository':{'pullRequest':queue}}})
            if method == 'GET':
                return json.dumps({'repos/a/b/pulls/9':pr,'repos/a/b/issues/9':issue,
                  'repos/a/b/actions/runs/44':run,'repos/a/b/actions/jobs/55':JOB,
                  'repos/a/b':REPOSITORY,'user':{'login':'reviewer'}}[path])
            if isinstance(write, Exception): raise write
            if callable(write): return json.dumps(write(method,path,payload))
            return json.dumps(write or {})
        return Client(runner), calls

    def request(self, action, kind='pull-request', expected=None, values=None, **kwargs):
        return {'op':'action','action':action,'confirmed':True,
                'item':{'kind':kind,'repo':'a/b','number':55 if kind=='job' else 44 if kind=='run' else 9},
                'expected':expected or {},'values':values or {},**kwargs}

    def pr_expected(self, action, pr=None, queue=None):
        options=lc.pr_actions(pr or PR, {'mergeMethods':['squash','merge']}, queue)
        return next(x['expected'] for x in options if x['id']==action)

    def writes(self,calls):
        return [c for c in calls if c[0]!='GET' and not (c[1]=='graphql' and c[2]['query'].startswith('query'))]

    def test_every_action_requires_confirmation_without_network(self):
        for action in lc.ACTIONS:
            client,calls=self.client()
            with self.subTest(action=action), self.assertRaises(GhError):
                client.action(self.request(action,confirmed=False))
            self.assertEqual(calls,[])

    def test_create_issue_exact_text_and_navigate_to_result(self):
        client,calls=self.client(write={'number':17})
        values={'repo':'a/b','title':'A title','body':'`code`\n$(no command)'}
        result=client.action(self.request('create-issue',values=values))
        self.assertEqual(result['target'],{'kind':'issue','repo':'a/b','number':17})
        self.assertEqual(self.writes(calls),[('POST','repos/a/b/issues',{'title':values['title'],'body':values['body']})])
        for bad in ['a/b/../../x','--help','https://github.com/a/b']:
            client,calls=self.client()
            with self.assertRaises(GhError): client.action(self.request('create-issue',values={**values,'repo':bad}))
            self.assertEqual(calls,[])

    def test_edit_issue_preserves_text_and_rejects_changed_snapshot(self):
        values={'title':'Renamed','body':'Description\n\n```code```'}
        client,calls=self.client(write={**ISSUE,**values})
        client.action(self.request('edit-issue','issue',lc.issue_snapshot(ISSUE),values))
        self.assertEqual(self.writes(calls)[0],('PATCH','repos/a/b/issues/9',values))
        client,calls=self.client(issue={**ISSUE,'body':'Someone else edited'})
        with self.assertRaisesRegex(GhError,'changed'): client.action(self.request('edit-issue','issue',lc.issue_snapshot(ISSUE),values))
        self.assertEqual(self.writes(calls),[])

    def test_labels_and_assignees_replace_and_clear(self):
        for action,values,result in [('labels',{'labels':'help wanted\nbug\nbug'},{'labels':[{'name':'bug'},{'name':'help wanted'}]}),
                                     ('assignees',{'assignees':''},{'assignees':[]})]:
            client,calls=self.client(write=result)
            client.action(self.request(action,'issue',lc.issue_snapshot(ISSUE),values))
            expected=['help wanted','bug'] if action=='labels' else []
            self.assertEqual(self.writes(calls)[0][2],{action:expected})

    def test_silently_ignored_assignment_is_not_success(self):
        client,calls=self.client(write={'assignees':[]})
        with self.assertRaisesRegex(GhError,'did not apply'):
            client.action(self.request('assignees','issue',lc.issue_snapshot(ISSUE),{'assignees':'alice'}))
        self.assertEqual(len(self.writes(calls)),1)

    def test_issue_close_reopen(self):
        for action,state,reason in [('close','closed','completed'),('reopen','open','reopened')]:
            issue={**ISSUE,'state':'open' if action=='close' else 'closed'}
            client,calls=self.client(issue=issue,write={'state':state,'state_reason':reason})
            client.action(self.request(action,'issue',lc.issue_snapshot(issue)))
            self.assertEqual(self.writes(calls)[0][2],{'state':state,'state_reason':reason})

    def test_pr_close_reopen_never_merges(self):
        for action,state in [('close','closed'),('reopen','open')]:
            pr={**PR,'state':'open' if action=='close' else 'closed'}
            client,calls=self.client(pr=pr,write={'state':state})
            client.action(self.request(action,expected=self.pr_expected(action,pr)))
            self.assertEqual(self.writes(calls),[('PATCH','repos/a/b/pulls/9',{'state':state})])

    def test_reviewers_require_names_and_use_structured_payload(self):
        expected=self.pr_expected('reviewers')
        client,calls=self.client()
        with self.assertRaises(GhError): client.action(self.request('reviewers',expected=expected))
        self.assertEqual(self.writes(calls),[])
        client,calls=self.client()
        client.action(self.request('reviewers',expected=expected,values={'reviewers':'alice\nbob','teams':'core'}))
        self.assertEqual(self.writes(calls)[0],('POST','repos/a/b/pulls/9/requested_reviewers',{'reviewers':['alice','bob'],'team_reviewers':['core']}))

    def test_ready_and_update_branch(self):
        pr={**PR,'draft':True,'node_id':'PR_9'}
        client,calls=self.client(pr=pr,write={'data':{'markPullRequestReadyForReview':{'pullRequest':{'isDraft':False}}}})
        client.action(self.request('ready',expected=self.pr_expected('ready',pr)))
        self.assertEqual(self.writes(calls)[0][2]['variables'],{'id':'PR_9'})
        client,calls=self.client()
        client.action(self.request('update-branch',expected=self.pr_expected('update-branch')))
        self.assertEqual(self.writes(calls),[('PUT','repos/a/b/pulls/9/update-branch',{'expected_head_sha':SHA})])

    def test_pr_head_change_blocks_all_lifecycle_actions(self):
        for action in ('close','reviewers','ready','update-branch','auto-merge','enqueue','disable-auto','dequeue'):
            pr={**PR,'draft': action=='ready'}
            queue={**QUEUE,'autoMergeRequest':{'mergeMethod':'SQUASH'} if action=='disable-auto' else None,
                   'mergeQueueEntry':{'position':1,'state':'QUEUED'} if action=='dequeue' else None}
            expected=self.pr_expected(action,pr,queue)
            client,calls=self.client(pr={**pr,'head':{**PR['head'],'sha':'b'*40}},queue=queue)
            with self.subTest(action=action),self.assertRaises(GhError): client.action(self.request(action,expected=expected))
            self.assertEqual(self.writes(calls),[])

    def test_auto_merge_and_queue_bind_sha_without_bypass(self):
        for action,mutation,payload in [('auto-merge','enablePullRequestAutoMerge',{'pullRequest':{'autoMergeRequest':{'mergeMethod':'SQUASH'}}}),
                                        ('enqueue','enqueuePullRequest',{'mergeQueueEntry':{'position':3,'state':'QUEUED'}})]:
            client,calls=self.client(write={'data':{mutation:payload}})
            client.action(self.request(action,expected=self.pr_expected(action,queue=QUEUE),values={'mergeMethod':'squash'}))
            inputs=self.writes(calls)[0][2]['variables']['input']
            self.assertEqual(inputs['expectedHeadOid'],SHA)
            self.assertEqual(inputs['pullRequestId'],'PR_9')
            self.assertNotIn('jump',inputs)
            self.assertNotIn('admin',inputs)
            if action=='auto-merge': self.assertEqual(inputs['mergeMethod'],'SQUASH')

    def test_disable_auto_and_dequeue(self):
        queue={**QUEUE,'autoMergeRequest':{'mergeMethod':'SQUASH'},'mergeQueueEntry':{'position':1,'state':'QUEUED'}}
        for action,mutation,result in [('disable-auto','disablePullRequestAutoMerge',{'pullRequest':{'autoMergeRequest':None}}),
                                       ('dequeue','dequeuePullRequest',{'pullRequest':{'isInMergeQueue':False}})]:
            client,calls=self.client(queue=queue,write={'data':{mutation:result}})
            client.action(self.request(action,expected=self.pr_expected(action,queue=queue)))
            self.assertEqual(self.writes(calls)[0][2]['variables']['input'],{'pullRequestId':'PR_9'})

    def test_blocked_auto_merge_and_disabled_method_never_mutate(self):
        for queue,method in [({**QUEUE,'viewerCanEnableAutoMerge':False},'squash'),(QUEUE,'rebase')]:
            client,calls=self.client(queue=queue)
            with self.assertRaises(GhError): client.action(self.request('auto-merge',expected=self.pr_expected('auto-merge',queue=queue),values={'mergeMethod':method}))
            self.assertEqual(self.writes(calls),[])

    def test_ci_routes_and_rechecks_attempt(self):
        for action,kind,path in [('rerun','run','runs/44/rerun'),('rerun-failed','run','runs/44/rerun-failed-jobs'),
                                 ('rerun-job','job','jobs/55/rerun'),('cancel-run','run','runs/44/cancel')]:
            run={**RUN,'status':'in_progress','conclusion':None} if action=='cancel-run' else RUN
            expected=lc.run_snapshot(run)
            if action=='rerun-job': expected['jobId']=55
            client,calls=self.client(run=run)
            client.action(self.request(action,kind,expected))
            self.assertEqual(self.writes(calls),[('POST','repos/a/b/actions/'+path,None)])
            client,calls=self.client(run={**run,'run_attempt':3})
            with self.assertRaises(GhError): client.action(self.request(action,kind,expected))
            self.assertEqual(self.writes(calls),[])

    def test_no_failed_rerun_for_success_or_cancel_for_completed(self):
        for action,run in [('rerun-failed',{**RUN,'conclusion':'success'}),('cancel-run',RUN)]:
            client,calls=self.client(run=run)
            with self.assertRaises(GhError): client.action(self.request(action,'run',lc.run_snapshot(run)))
            self.assertEqual(self.writes(calls),[])

    def test_api_permission_failure_and_unconfirmed_response_do_not_retry(self):
        for write in [GhError('HTTP 403'),{}]:
            client,calls=self.client(write=write)
            with self.assertRaises(GhError): client.action(self.request('close',expected=self.pr_expected('close')))
            self.assertEqual(len(self.writes(calls)),1)

if __name__=='__main__': unittest.main()
