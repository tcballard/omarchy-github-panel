import base64
import copy
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

from reader_client import Client
from github_client import GhError
import authoring
import desk_protocol
import local_state
import markup
import navigation
import review_workspace
import transfers
import workspace
import workspace_actions

SHA='a'*40
PR={'number':7,'node_id':'PR_7','title':'Change','body':'Description','state':'open','updated_at':'now','draft':False,'merged':False,
    'head':{'sha':SHA,'ref':'feature','repo':{'full_name':'a/b'}},'base':{'ref':'main'}}
RELEASE={'id':8,'name':'Release','body':'Notes','tag_name':'v1','draft':True,'prerelease':False,'updated_at':'now','assets':[]}


class Fake(Client):
    def __init__(self, api=None, pages=None, graph=None):
        super().__init__(account='alice')
        self.answers=api or {}; self.pages=pages or {}; self.graph_answer=graph; self.calls=[]

    def api(self,endpoint,method='GET',payload=None):
        self.calls.append((method,endpoint,copy.deepcopy(payload)))
        value=self.answers.get((method,endpoint),self.answers.get(endpoint))
        if value is None: raise AssertionError('Unexpected API: '+method+' '+endpoint)
        if isinstance(value,Exception): raise value
        return copy.deepcopy(value)

    def response(self,endpoint,method='GET',payload=None):
        self.calls.append((method,endpoint,payload))
        value=self.pages(endpoint) if callable(self.pages) else self.pages.get(endpoint)
        if value is None: raise AssertionError('Unexpected page: '+endpoint)
        return copy.deepcopy(value)

    def graph(self,query,variables):
        self.calls.append(('GRAPH',query,copy.deepcopy(variables)))
        if callable(self.graph_answer): return self.graph_answer(query,variables)
        if self.graph_answer is None: raise AssertionError('Unexpected GraphQL: '+query)
        return copy.deepcopy(self.graph_answer)


def request(action,item=None,expected=None,values=None):
    return dict(action=action,confirmed=True,item=item or {'kind':'pull-request','repo':'a/b','number':7},expected=expected or {},values=values or {})


class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.env=patch.dict(os.environ,{'XDG_STATE_HOME':self.temp.name}); self.env.start(); self.addCleanup(self.env.stop)

    def test_url_navigation_and_rejected_schemes(self):
        for url,kind in [('a/b','repository'),('https://github.com/a/b/pull/7/files','pull-request'),('https://github.com/a/b/actions/runs/8/job/9','job'),('https://github.com/a/b/releases/tag/v1/test','release-tag'),('https://github.com/a/b/blob/feature/fix/file.py','code-url')]:
            self.assertEqual(navigation.resolve(url)['kind'],kind)
        self.assertEqual(navigation.resolve('#7','a/b')['number'],7)
        for url in ['file:///etc/passwd','javascript:alert(1)','https://github.com@evil.test/a/b','https://github.com/a/../issues/2','https://github.com:123/a/b','https://github.com/a/b/pull/nope']:
            with self.subTest(url=url),self.assertRaises(GhError): navigation.resolve(url)

    def test_markdown_never_emits_remote_html_or_implicit_image_load(self):
        rich,images=markup.render('# Hello\n<img src="file:///etc/passwd">\n<script>alert(1)</script>\n![shot](https://example.com/x.png)\n[x](javascript:evil)\n[repo](https://github.com/a/b)\n```\n<a>\n```')
        self.assertIn('<h1>Hello</h1>',rich)
        self.assertNotIn('<img',rich);self.assertNotIn('<script',rich);self.assertNotIn('href="javascript:',rich)
        self.assertIn('&lt;script&gt;',rich);self.assertIn('<pre>&lt;a&gt;</pre>',rich)
        self.assertEqual(images,[{'label':'shot','url':'https://example.com/x.png'}])
        self.assertIn('href="https://github.com/a/b"',rich)

    def test_relative_image_uses_raw_repository_url(self):
        rich,images=markup.render('![Shot](assets/shot.png)','https://github.com/a/b/blob/main/')
        self.assertEqual(images[0]['url'],'https://raw.githubusercontent.com/a/b/main/assets/shot.png')

    def test_account_state_is_private_isolated_and_survives_restart(self):
        local_state.put('alice','drafts','a/b#1','A draft')
        self.assertEqual(local_state.read('alice','drafts')['a/b#1'],'A draft')
        self.assertEqual(local_state.read('bob','drafts'),{})
        self.assertEqual((local_state.root('alice')/'drafts.json').stat().st_mode & 0o777,0o600)
        self.assertEqual(local_state.root('alice').stat().st_mode & 0o777,0o700)
        with self.assertRaises(GhError): local_state.read('','drafts')

    def test_cached_details_remove_all_write_controls(self):
        item={'repo':'a/b','kind':'issue','number':1}
        detail={'target':item,'body':'Private','actions':[{'id':'close'}],'canReply':True,'pr':{'canMerge':True},'threadId':'123','tabs':[{'id':'conversation','blocks':[{'operations':[{'id':'delete'}]}]}]}
        local_state.cache('alice',item,detail)
        cached=local_state.cached('alice',item)
        self.assertTrue(cached['cached']);self.assertFalse(cached['canReply']);self.assertEqual(cached['actions'],[])
        self.assertEqual(cached['tabs'][0]['blocks'][0]['operations'],[])
        self.assertIsNone(local_state.cached('bob',item))

    def test_response_headers_drive_pagination_not_page_length(self):
        raw='HTTP/2.0 200 OK\r\nLink: <https://api.github.com/user/repos?page=2>; rel="next"\r\n\r\n[]'
        c=Client(lambda args,payload:raw)
        body,headers=c.response('user/repos')
        self.assertEqual(body,[]);self.assertIn('rel="next"',headers['link'])
        result=workspace.collection(Fake(pages=lambda url:([{'full_name':'a/b','description':'x'}],{})),{'kind':'collection','repo':'','collection':'repositories'})
        self.assertIsNone(result['nextTarget']);self.assertEqual(len(result['tabs'][0]['blocks']),1)

    def test_repository_pages_include_forks_and_all_affiliations(self):
        c=Fake(pages=lambda url:([{'full_name':'a/b','description':'x','fork':True}],{'link':'<next>; rel="next"'}))
        r=workspace.collection(c,{'kind':'collection','repo':'','collection':'repositories','page':2})
        self.assertEqual(r['nextTarget']['page'],3);self.assertEqual(r['previousTarget']['page'],1)
        query=parse_qs(urlparse(c.calls[0][1]).query)
        self.assertEqual(query['affiliation'],['owner,collaborator,organization_member'])
        self.assertIn('fork',r['tabs'][0]['blocks'][0]['body'])

    def test_incoming_prs_search_owner_not_just_authored(self):
        c=Fake(api={'search/issues?q=user%3Aasdecided&sort=updated&order=desc&per_page=50&page=1&advanced_search=true':{}})
        with patch('search_client.search',return_value={'items':[],'hasMore':False,'total':0,'warning':''}) as search:
            workspace.collection(c,{'kind':'collection','repo':'','collection':'pulls','view':'incoming','owner':'asdecided'})
        params=search.call_args.args[0]
        self.assertEqual(params['query'],'user:asdecided');self.assertEqual(params['kind'],'pr')
        self.assertNotIn('author:',params['query'])

    def test_filtered_empty_inbox_keeps_next_page(self):
        n={'id':'12','reason':'author','updated_at':'now','unread':True,'repository':{'full_name':'a/b'},'subject':{'title':'Test','type':'Issue','url':'https://api.github.com/repos/a/b/issues/1'}}
        c=Fake(pages=lambda url:([n],{'link':'<next>; rel="next"'}))
        r=workspace.collection(c,{'kind':'collection','repo':'','collection':'inbox','reason':'mention'})
        self.assertEqual(r['tabs'][0]['blocks'],[]);self.assertEqual(r['nextTarget']['page'],2)
        self.assertTrue(r['warnings'])

    def test_filter_saved_view_and_pins_never_call_network(self):
        c=Fake();item={'kind':'collection','repo':'','collection':'pulls'}
        r=workspace_actions.perform(c,request('browse-filter',item,values={'owner':'asdecided','view':'incoming','arbitrary':'ignored'}))
        self.assertNotIn('arbitrary',r['target'])
        workspace_actions.perform(c,request('save-view',r['target'],values={'name':'AsDecided'}))
        self.assertEqual(local_state.read('alice','preferences')['saved']['AsDecided']['owner'],'asdecided')
        workspace_actions.perform(c,request('pin',{'kind':'repository','repo':'a/b'}))
        self.assertEqual(local_state.read('alice','preferences')['pinned'],['a/b']);self.assertEqual(c.calls,[])

    def test_unconfirmed_new_actions_never_call_network(self):
        for action in workspace_actions.ACTIONS:
            c=Fake()
            with self.subTest(action=action),self.assertRaises(GhError): workspace_actions.perform(c,dict(request(action),confirmed=False))
            self.assertEqual(c.calls,[])

    def test_edit_pr_binds_head_and_body_timestamp(self):
        exp={**review_workspace.snapshot(PR),'updated':'now'}
        for changed_pr in [dict(PR,updated_at='later'),dict(PR,head={**PR['head'],'sha':'b'*40})]:
            c=Fake(api={'repos/a/b/pulls/7':changed_pr})
            with self.assertRaises(GhError): workspace_actions.perform(c,request('edit-pr',expected=exp,values={'title':'New','body':'Body','base':'main'}))
            self.assertTrue(all(call[0]=='GET' for call in c.calls))
        c=Fake(api={'repos/a/b/pulls/7':PR,('PATCH','repos/a/b/pulls/7'):{}})
        workspace_actions.perform(c,request('edit-pr',expected=exp,values={'title':'New','body':'literal `x`\n$(echo nope)','base':'main'}))
        self.assertEqual(c.calls[-1][2]['body'],'literal `x`\n$(echo nope)')

    def test_delete_branch_refuses_default_or_advanced_branch(self):
        pr=copy.deepcopy(PR);pr['merged']=True
        exp={**review_workspace.snapshot(pr),'updated':'now'}
        for branch in ['feature','main']:
            c=Fake(api={'repos/a/b/pulls/7':pr,'repos/a/b':{'default_branch':branch},'repos/a/b/git/ref/heads/feature':{'object':{'sha':'b'*40}}})
            with self.assertRaises(GhError): workspace_actions.perform(c,request('delete-branch',expected=exp))
            self.assertFalse(any(call[0]=='DELETE' for call in c.calls))

    def test_comment_edit_validates_parent_and_updated_version(self):
        exp={'type':'comment','id':4,'updated':'old','number':7}
        c=Fake(api={'repos/a/b/issues/comments/4':{'updated_at':'old','issue_url':'https://api.github.com/repos/a/b/issues/9'}})
        with self.assertRaises(GhError): workspace_actions.perform(c,request('comment-edit',expected=exp,values={'body':'x'}))
        self.assertEqual(len(c.calls),1)

    def test_notification_batch_preflights_all_before_writing(self):
        exp={'threads':[{'id':'1','updated':'old'},{'id':'2','updated':'old'}]}
        c=Fake(api={'notifications/threads/1':{'updated_at':'old'},'notifications/threads/2':{'updated_at':'new'}})
        with self.assertRaises(GhError): workspace_actions.perform(c,request('notifications-read',{'kind':'collection','repo':'','collection':'inbox'},exp))
        self.assertEqual([x[0] for x in c.calls],['GET','GET'])

    def test_notification_partial_failure_reports_completed_count(self):
        exp={'threads':[{'id':'1','updated':'old'},{'id':'2','updated':'old'}]}
        c=Fake(api={'notifications/threads/1':{'updated_at':'old'},'notifications/threads/2':{'updated_at':'old'},('PATCH','notifications/threads/1'):{},('PATCH','notifications/threads/2'):GhError('Permission changed')})
        with self.assertRaisesRegex(GhError,'1 notifications updated'): workspace_actions.perform(c,request('notifications-read',{'kind':'collection','repo':'','collection':'inbox'},exp))

    def test_release_publish_binds_asset_snapshot_even_with_same_timestamp(self):
        exp=workspace_actions.release_snapshot(RELEASE)
        changed_release=dict(RELEASE,assets=[{'id':1,'name':'new.zip','size':3}])
        c=Fake(api={'repos/a/b/releases/8':changed_release})
        with self.assertRaises(GhError): workspace_actions.perform(c,request('publish-release',expected=exp))
        self.assertEqual(len(c.calls),1)

    def test_release_creation_always_drafts_and_publish_is_separate(self):
        c=Fake(api={('POST','repos/a/b/releases'):{'id':8},'repos/a/b/releases/8':RELEASE,('PATCH','repos/a/b/releases/8'):dict(RELEASE,draft=False)})
        result=workspace_actions.perform(c,request('create-release',values={'tag':'v1','body':'Notes','name':'Title','prerelease':'no'}))
        self.assertTrue(c.calls[0][2]['draft']);self.assertEqual(result['target']['kind'],'release')
        workspace_actions.perform(c,request('publish-release',expected=workspace_actions.release_snapshot(RELEASE)))
        self.assertEqual(c.calls[-1][2],{'draft':False})

    def test_asset_download_does_not_overwrite_or_extract(self):
        runner=lambda *a,**k:SimpleNamespace(returncode=0,stdout=b'archive',stderr=b'')
        with patch('transfers.Path.home',return_value=Path(self.temp.name)):
            first=transfers.download('a/b','artifact',1,'../../test',runner)
            second=transfers.download('a/b','artifact',1,'../../test',runner)
        self.assertNotEqual(first,second)
        self.assertEqual(Path(first).parent,Path(self.temp.name)/'Downloads')
        self.assertEqual(Path(first).read_bytes(),b'archive');self.assertTrue(first.endswith('.zip'))
        self.assertEqual(Path(first).stat().st_mode & 0o777,0o600)

    def test_failed_transfer_leaves_no_partial_file(self):
        runner=lambda *a,**k:SimpleNamespace(returncode=1,stdout=b'partial',stderr=b'failed')
        with patch('transfers.Path.home',return_value=Path(self.temp.name)),self.assertRaises(GhError): transfers.download('a/b','asset',1,'x',runner)
        self.assertEqual(list((Path(self.temp.name)/'Downloads').iterdir()),[])

    def test_issue_form_required_checkbox_and_dropdown_validation(self):
        source='''name: Bug\ndescription: Report a bug\nbody:\n  - type: dropdown\n    attributes:\n      label: Version\n      options: [one, two]\n    validations: {required: true}\n  - type: checkboxes\n    attributes:\n      label: Confirm\n      options:\n        - label: I checked\n          required: true\n'''
        c=Fake(api={'repos/a/b/contents/.github/ISSUE_TEMPLATE/bug.yml':{'sha':'template','encoding':'base64','content':base64.b64encode(source.encode()).decode()}})
        form,schema=authoring.template_form(c,'a/b','.github/ISSUE_TEMPLATE/bug.yml')
        values={'title':'Bug','form_0':'one','form_1_0':'no'}
        with self.assertRaisesRegex(GhError,'Confirm'): authoring.template_payload(c,'a/b',form['expected'],values)
        values['form_1_0']='yes';payload=authoring.template_payload(c,'a/b',form['expected'],values)
        self.assertIn('- [x] I checked',payload['body'])
        values['form_0']='bogus'
        with self.assertRaises(GhError): authoring.template_payload(c,'a/b',form['expected'],values)

    def test_workflow_boolean_yaml_on_and_typed_inputs(self):
        source='''on:\n  workflow_dispatch:\n    inputs:\n      dry_run:\n        type: boolean\n        default: true\n      channel:\n        type: choice\n        options: [edge, stable]\n        required: true\n'''
        c=Fake(api={'repos/a/b/actions/workflows/9':{'id':9,'name':'Publish','path':'.github/workflows/publish.yml'},'repos/a/b/contents/.github/workflows/publish.yml?ref=main':{'sha':'workflow','encoding':'base64','content':base64.b64encode(source.encode()).decode()},('POST','repos/a/b/actions/workflows/9/dispatches'):{}})
        node,form,inputs=authoring.workflow_form(c,'a/b',9,'main')
        self.assertEqual(form['fields'][0]['value'],'true')
        workspace_actions.perform(c,request('dispatch-workflow',expected=form['expected'],values={'dry_run':'true','channel':'edge'}))
        self.assertEqual(c.calls[-1][2],{'ref':'main','inputs':{'dry_run':'true','channel':'edge'}})

    def test_paged_file_review_records_correct_page(self):
        c=Fake(api={'repos/a/b/pulls/7':PR},pages={'repos/a/b/pulls/7/files?per_page=100&page=2':([{'filename':'z.py','patch':'@@ -1 +1 @@\n-old\n+new'}],{})})
        result=review_workspace.detail(c,{'kind':'review-page','repo':'a/b','number':7,'section':'files','page':2})
        op=result['tabs'][0]['blocks'][0]['operations'][0]
        self.assertEqual(op['expected']['page'],2)
        self.assertEqual(result['previousTarget']['page'],1)

    def test_batch_review_is_local_until_explicit_submission(self):
        expected={**review_workspace.snapshot(PR),'path':'x.py','page':1,'size':100}
        c=Fake(api={'repos/a/b/pulls/7':PR,'repos/a/b/pulls/7/files?per_page=100&page=1':[{'filename':'x.py','patch':'@@ -1,2 +1,2 @@\n a\n+b\n-c'}],('POST','repos/a/b/pulls/7/reviews'):{'id':42,'state':'COMMENTED'}})
        workspace_actions.perform(c,request('stage-comment',expected=expected,values={'location':'New line 2','start':'New line 1','body':'Consider this'}))
        self.assertTrue(all(call[0]=='GET' for call in c.calls))
        self.assertEqual(local_state.read('alice','reviews')['a/b#7']['comments'][0]['start_line'],1)
        workspace_actions.perform(c,request('submit-review',expected=review_workspace.snapshot(PR),values={'event':'COMMENT','body':'Notes'}))
        self.assertEqual(c.calls[-1][2]['commit_id'],SHA);self.assertEqual(len(c.calls[-1][2]['comments']),1)
        self.assertEqual(local_state.read('alice','reviews'),{})

    def test_pending_review_cannot_move_to_a_new_commit(self):
        local_state.put('alice','reviews','a/b#7',{'sha':'b'*40,'comments':[]})
        c=Fake(api={'repos/a/b/pulls/7':PR})
        with self.assertRaises(GhError): workspace_actions.perform(c,request('submit-review',expected=review_workspace.snapshot(PR),values={'event':'APPROVE','body':''}))
        self.assertEqual(len(c.calls),1)

    def test_inline_thread_reply_uses_thread_parent_not_issue_comments(self):
        thread={'id':'T1','pullRequest':{'number':7,'headRefOid':SHA,'repository':{'nameWithOwner':'a/b'}},'comments':{'nodes':[{'databaseId':22}]}}
        c=Fake(api={'repos/a/b/pulls/7':PR,('POST','repos/a/b/pulls/7/comments/22/replies'):{'id':23}},graph={'node':thread})
        workspace_actions.perform(c,request('thread-reply',expected={**review_workspace.snapshot(PR),'thread':'T1'},values={'body':'Thanks'}))
        self.assertEqual(c.calls[-1][1],'repos/a/b/pulls/7/comments/22/replies')

    def test_suggestion_commit_preserves_executable_bit_and_uses_non_force_ref(self):
        suggestion='print("new")';content='```suggestion\n'+suggestion+'\n```'
        comment={'id':'C1','updatedAt':'now','body':content}
        node={'id':'T1','path':'script.py','diffSide':'RIGHT','line':1,'startLine':None,'isOutdated':False,'comments':{'nodes':[comment]}}
        expected={'comment':'C1','updated':'now','replacementHash':hashlib.sha256(suggestion.encode()).hexdigest()}
        c=Fake(api={'repos/a/b/git/ref/heads/feature':{'object':{'sha':SHA}},'repos/a/b/contents/script.py?ref='+SHA:{'encoding':'base64','content':base64.b64encode(b'print("old")\n').decode()},'repos/a/b/git/commits/'+SHA:{'tree':{'sha':'tree'}},'repos/a/b/git/trees/tree':{'tree':[{'path':'script.py','mode':'100755','type':'blob','sha':'blob'}]},('POST','repos/a/b/git/trees'):{'sha':'newtree'},('POST','repos/a/b/git/commits'):{'sha':'newcommit'},('PATCH','repos/a/b/git/refs/heads/feature'):{'object':{'sha':'newcommit'}}})
        review_workspace.apply_suggestion(c,'a/b',PR,node,expected,{'message':'Apply suggestion'})
        tree=next(call[2] for call in c.calls if call[0]=='POST' and call[1].endswith('/git/trees'))
        self.assertEqual(tree['tree'][0]['mode'],'100755');self.assertEqual(tree['tree'][0]['content'],'print("new")\n')
        self.assertEqual(c.calls[-1][2],{'sha':'newcommit','force':False})


if __name__=='__main__': unittest.main()
