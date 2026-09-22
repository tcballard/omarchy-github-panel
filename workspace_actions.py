"""Additional explicit maintainer actions; all remote mutations are confirmed."""
import json
import hashlib
import re
from github_client import GhError
from lifecycle import choice, field, text, names, changed
from navigation import repository, segment, path
from workspace import block, target, selector, release_create
import local_state
import review_workspace
import conflict_workspace

ACTIONS=conflict_workspace.ACTIONS | review_workspace.ACTIONS | {'browse-filter','save-view','delete-view','pin','unpin','star','unstar','create-pr','edit-pr','draft-pr','remove-reviewers','delete-branch','comment-edit','comment-delete','reaction','milestone','close-not-planned','notifications-read','notification-done','notification-unsubscribe','create-release','edit-release','publish-release','download-asset','download-artifact','upload-asset','dispatch-workflow','create-template-issue','create-discussion','discussion-reply','discussion-answer','discussion-close'}


def release_snapshot(node):
    data={k:node.get(k) for k in ('name','body','prerelease','target_commitish')}
    data['assets']=[{k:a.get(k) for k in ('id','name','size','updated_at','state')} for a in node.get('assets',[])]
    return {'release':node['id'],'updated':node['updated_at'],'tag':node['tag_name'],'draft':node['draft'],
            'digest':hashlib.sha256(json.dumps(data,sort_keys=True).encode()).hexdigest()}


def enrich(client,result):
    item=result['target']; repo=item.get('repo',''); kind=item['kind']
    # Always expose a way back to the repository, even from a pasted deep link.
    if repo and kind!='repository': result['repositoryTarget']=target('repository',repo)
    if result.get('cached'): return
    base='repos/'+repo
    if kind in ('issue','pull-request'):
        node=client.api(base+'/issues/'+str(item['number']))
        expected={'number':item['number'],'updated':node['updated_at']}
        result['actions'] += [choice('reaction','React to issue / PR','Add a reaction.',{**expected,'type':'issue','id':item['number']},[selector('content','Reaction',['+1','-1','laugh','confused','heart','hooray','rocket','eyes'])]),
            choice('milestone','Set milestone','Assign an open milestone or clear it.',expected,[field('milestone','Milestone number (empty to clear)')])]
        result.setdefault('links',[])
        result['links'] += [block('Repository milestones','',target('collection',repo,collection='milestones')),block('Labels and assignees','',target('collection',repo,collection='labels')),block('People','',target('collection',repo,collection='people'))]
        if kind=='issue' and node['state']=='open': result['actions'].append(choice('close-not-planned','Close as not planned','Close this issue without marking it completed.',expected))
        for tab in result['tabs']:
            for b in tab['blocks']:
                comment=b.get('commentMeta')
                if comment and comment.get('id'):
                    exp={'type':'comment','id':comment['id'],'updated':comment.get('updated_at'),'number':item['number']}
                    b['operations']=[choice('comment-edit','Edit comment','Update this comment. GitHub enforces author permissions.',exp,[field('body','Comment',b['body'],True,True)]),
                        choice('comment-delete','Delete comment','Permanently delete this comment.',exp),choice('reaction','React','Add a reaction to this comment.',exp,[selector('content','Reaction',['+1','-1','laugh','confused','heart','hooray','rocket','eyes'])])]
                    b['operationLabel']='Comment actions'
        result['links'].append(block('Timeline','',target('collection',repo,collection='timeline',number=item['number'])))
        if kind=='pull-request':
            result['links'].append(block('Resolve merge conflicts','Prepare, resolve and commit a merge into this PR branch.',target('conflicts',repo,number=item['number'])))
            pr=client.api(base+'/pulls/'+str(item['number'])); exp={**review_workspace.snapshot(pr),'updated':pr['updated_at']}
            result['actions'] += [choice('edit-pr','Edit title, description and target','Update this PR. Changing its target branch changes the diff.',exp,[field('title','Title',pr['title'],True),field('body','Description',pr.get('body') or '',multiline=True),field('base','Target branch',pr['base']['ref'],True)])]
            if not pr.get('draft') and pr['state']=='open': result['actions'].append(choice('draft-pr','Convert to draft','Return this PR to draft status.',exp))
            if pr['state']=='open': result['actions'].append(choice('remove-reviewers','Remove requested reviewers','Remove only these review requests.',exp,[field('reviewers','Usernames, one per line',multiline=True),field('teams','Team slugs, one per line',multiline=True)]))
            if pr.get('merged') and pr.get('head',{}).get('repo'): result['actions'].append(choice('delete-branch','Delete merged source branch','Delete '+pr['head']['repo']['full_name']+':'+pr['head']['ref']+'. This is separate from merging.',exp))
            links=[block('All changed files','Paginated diffs and pending review comments.',target('review-page',repo,number=item['number'],section='files')),
                block('All reviews','',target('review-page',repo,number=item['number'],section='reviews')),
                block('All inline comments','',target('review-page',repo,number=item['number'],section='comments')),
                block('All review threads','Read and reply inside each thread.',target('thread-page',repo,number=item['number'])),
                block('Pending review','Review saved comments, then submit together.',target('review-page',repo,number=item['number'],section='pending')),
                block('Actions for this commit','Jobs, logs, reruns and artifacts.',target('collection',repo,collection='runs',sha=pr['head']['sha']))]
            result['links']+=links
            for tab in result['tabs']:
                if tab['id']=='status': tab['blocks'].insert(0,links[-1])
    elif kind=='run':
        result.setdefault('links',[]).append(block('Artifacts','Download workflow output.',target('collection',repo,collection='artifacts',number=item['number'])))
        result['links'].append(block('All jobs','Paginated job history.',target('collection',repo,collection='jobs',number=item['number'])))
    elif kind=='release':
        node=client.api(base+'/releases/'+str(item['number'])); exp=release_snapshot(node)
        result['actions'] += [choice('edit-release','Edit release','Save release notes and metadata.',exp,[field('name','Title',node.get('name') or ''),field('body','Release notes',node.get('body') or '',multiline=True),selector('prerelease','Prerelease',['no','yes'],'yes' if node['prerelease'] else 'no')]),choice('upload-asset','Upload asset','Upload a local file to this release. Existing assets are not overwritten.',exp,[field('path','Absolute file path',required=True)])]
        if node['draft']: result['actions'].append(choice('publish-release','Publish release','Publish '+node['tag_name']+' and its current notes/assets.',exp))
        result['tabs']=[dict(id='release',label='Assets',blocks=[block(a['name'],str(a['size'])+' bytes',operations=[choice('download-asset','Download asset','Save this asset in ~/Downloads without overwriting files.',{'id':a['id'],'name':a['name'],'size':a['size']})],operationLabel='Download') for a in node.get('assets',[])])]
    if result.get('links'):
        for b in result['links']: b.setdefault('operationLabel','Open')
        result['tabs'].append(dict(id='navigate',label='Related',blocks=result['links']))


def perform(client,req):
    if req.get('confirmed') is not True: raise GhError('Confirm this action first.', 'input')
    action=req['action']; item=req.get('item') or {}; values=req.get('values') or {}; exp=req.get('expected') or {}
    if action in conflict_workspace.ACTIONS: return conflict_workspace.perform(client,req)
    if action in review_workspace.ACTIONS: return review_workspace.perform(client,req)
    if not isinstance(values,dict) or not isinstance(exp,dict): raise GhError('Invalid action.', 'input')
    if action=='browse-filter':
        clean={k:v for k,v in values.items() if k in ('query','owner','scope','view','repo','state','mode','reason','ref','path','branch','workflow','status') and isinstance(v,str) and len(v)<2000}
        return {'ok':True,'message':'View updated.','target':{**item,**clean,'page':1,'cursor':None,'scan':1},'local':True}
    if action in ('save-view','delete-view'):
        saved=local_state.read(client.account,'preferences').get('saved',{})
        if action=='save-view': saved[text(values,'name',True,120)]={k:v for k,v in item.items() if k not in ('page','cursor','scan')}
        else: saved.pop(exp['name'],None)
        local_state.put(client.account,'preferences','saved',saved)
        return {'ok':True,'message':'Saved views updated.','local':True}
    repo=item.get('repo','')
    if action not in ('notifications-read','notification-done','notification-unsubscribe'):
        repo=repository(repo)
    base='repos/'+repo
    if action in ('pin','unpin'):
        pins=local_state.read(client.account,'preferences').get('pinned',[])
        pins=[p for p in pins if p!=repo]
        if action=='pin': pins.insert(0,repo)
        local_state.put(client.account,'preferences','pinned',pins)
        return {'ok':True,'message':'Pinned repositories updated.','local':True}
    if action in ('star','unstar'): client.api('user/starred/'+repo,'PUT' if action=='star' else 'DELETE')
    elif action=='create-pr':
        node=client.api(base+'/pulls','POST',{'title':text(values,'title',True,256),'body':text(values,'body'),'head':text(values,'head',True,256),'base':text(values,'base',True,256),'draft':values.get('draft')=='yes'})
        if not node.get('number'): raise GhError('GitHub did not confirm PR creation.', 'unconfirmed')
        return {'ok':True,'message':'Pull request created.','target':target('pull-request',repo,number=node['number'])}
    elif action in ('edit-pr','draft-pr','remove-reviewers','delete-branch'):
        pr=review_workspace.checked_pr(client,repo,item['number'],exp)
        if pr['updated_at']!=exp.get('updated'): changed()
        endpoint=base+'/pulls/'+str(item['number'])
        if action=='edit-pr': client.api(endpoint,'PATCH',{'title':text(values,'title',True,256),'body':text(values,'body'),'base':text(values,'base',True,256)})
        elif action=='draft-pr': client.graph('mutation($id:ID!){convertPullRequestToDraft(input:{pullRequestId:$id}){pullRequest{isDraft}}}',{'id':pr['node_id']})
        elif action=='remove-reviewers':
            users,teams=names(values,'reviewers'),names(values,'teams')
            if not users and not teams: raise GhError('Choose reviewers or teams to remove.', 'input')
            client.api(endpoint+'/requested_reviewers','DELETE',{'reviewers':users,'team_reviewers':teams})
        else:
            if not pr.get('merged') or not pr.get('head',{}).get('repo'): raise GhError('Only merged PR source branches can be deleted.', 'blocked')
            source=repository(pr['head']['repo']['full_name']); branch=pr['head']['ref']; metadata=client.api('repos/'+source)
            if branch==metadata['default_branch'] or (source==repo and branch==pr['base']['ref']): raise GhError('The default or target branch cannot be deleted.', 'blocked')
            current=client.api('repos/'+source+'/git/ref/heads/'+path(branch))
            if current['object']['sha']!=exp['headSha']: changed()
            client.api('repos/'+source+'/git/refs/heads/'+path(branch),'DELETE')
    elif action in ('comment-edit','comment-delete','reaction','milestone','close-not-planned'):
        comment=exp.get('type')=='comment'; number=int(exp.get('id') if comment else (exp.get('number') or item['number']))
        endpoint=base+('/issues/comments/' if comment else '/issues/')+str(number)
        node=client.api(endpoint)
        if node.get('updated_at')!=exp.get('updated'): changed()
        if comment and not node.get('issue_url','').endswith('/issues/'+str(exp['number'])): raise GhError('Comment belongs to another issue.', 'input')
        if action=='comment-edit': client.api(endpoint,'PATCH',{'body':text(values,'body',True)})
        elif action=='comment-delete': client.api(endpoint,'DELETE')
        elif action=='reaction':
            content=values.get('content')
            if content not in ('+1','-1','laugh','confused','heart','hooray','rocket','eyes'): raise GhError('Invalid reaction.', 'input')
            client.api(endpoint+'/reactions','POST',{'content':content})
        elif action=='milestone':
            value=text(values,'milestone')
            if value and not value.isdigit(): raise GhError('Use a milestone number.', 'input')
            client.api(endpoint,'PATCH',{'milestone':int(value) if value else None})
        else: client.api(endpoint,'PATCH',{'state':'closed','state_reason':'not_planned'})
    elif action in ('notification-done','notification-unsubscribe','notifications-read'):
        threads=exp.get('threads',[]) if action=='notifications-read' else [{'id':exp.get('thread'),'updated':exp.get('updated')}]
        if not threads or len(threads)>50: raise GhError('Choose a displayed notification page.', 'input')
        # Preflight every item before applying the first mutation.
        for n in threads:
            if not re.fullmatch(r'[1-9][0-9]*',str(n.get('id',''))): raise GhError('Invalid notification.', 'input')
            current=client.api('notifications/threads/'+n['id'])
            if current.get('updated_at')!=n['updated']: changed()
        completed=0
        try:
            for n in threads:
                endpoint='notifications/threads/'+n['id']
                if action=='notifications-read': client.api(endpoint,'PATCH')
                elif action=='notification-done': client.api(endpoint,'DELETE')
                else: client.api(endpoint+'/subscription','PUT',{'ignored':True})
                completed+=1
        except GhError as exc: raise GhError(f'{completed} notifications updated before an error. Refresh before retrying: {exc}', 'partial') from exc
    elif action=='create-release':
        payload={'tag_name':text(values,'tag',True,256),'name':text(values,'name'),'body':text(values,'body'),'draft':True,'prerelease':values.get('prerelease')=='yes'}
        if values.get('target'): payload['target_commitish']=text(values,'target',True,256)
        node=client.api(base+'/releases','POST',payload)
        if not node.get('id'): raise GhError('GitHub did not confirm release creation.', 'unconfirmed')
        return {'ok':True,'message':'Release draft created.','target':target('release',repo,number=node['id'])}
    elif action in ('edit-release','publish-release','upload-asset'):
        endpoint=base+'/releases/'+str(int(exp['release'])); node=client.api(endpoint)
        if release_snapshot(node)!=exp: changed()
        if action=='edit-release': client.api(endpoint,'PATCH',{'name':text(values,'name'),'body':text(values,'body'),'prerelease':values.get('prerelease')=='yes'})
        elif action=='publish-release':
            if not node['draft']: changed()
            client.api(endpoint,'PATCH',{'draft':False})
        else:
            import transfers
            transfers.upload(repo,node['id'],text(values,'path',True,4096))
    elif action in ('download-asset','download-artifact'):
        import transfers
        kind='asset' if action=='download-asset' else 'artifact'
        endpoint=base+('/releases/assets/' if kind=='asset' else '/actions/artifacts/')+str(int(exp['id']))
        node=client.api(endpoint)
        if node.get('name')!=exp['name'] or node.get('size',node.get('size_in_bytes'))!=exp.get('size'): changed()
        if node.get('expired'): raise GhError('This artifact has expired.', 'unavailable')
        location=transfers.download(repo,kind,int(exp['id']),exp['name'])
        return {'ok':True,'message':'Saved '+location,'local':True}
    elif action=='dispatch-workflow':
        import authoring
        node,form,inputs=authoring.workflow_form(client,repo,exp['workflow'],exp['ref'])
        if not form or form['expected']!=exp: changed()
        payload={}
        for f in form['fields']:
            value=text(values,f['key'],f['required'])
            if f.get('options') and value not in f['options']: raise GhError('Invalid workflow input.', 'input')
            payload[f['key']]=value
        client.api(base+'/actions/workflows/'+str(node['id'])+'/dispatches','POST',{'ref':exp['ref'],'inputs':payload})
        return {'ok':True,'message':'Workflow dispatch requested.','target':target('collection',repo,collection='runs',workflow=str(node['id']))}
    elif action=='create-template-issue':
        import authoring
        payload=authoring.template_payload(client,repo,exp,values)
        node=client.api(base+'/issues','POST',payload)
        if not node.get('number'): raise GhError('GitHub did not confirm issue creation.', 'unconfirmed')
        return {'ok':True,'message':'Issue created.','target':target('issue',repo,number=node['number'])}
    elif action in ('create-discussion','discussion-reply','discussion-answer','discussion-close'):
        return discussion_action(client,repo,action,item,exp,values)
    else: raise GhError('Unsupported workspace action.', 'input')
    return {'ok':True,'message':'Changes saved.'}


def discussion_action(client,repo,action,item,exp,values):
    owner,name=repo.split('/')
    if action=='create-discussion':
        node=client.graph('query($o:String!,$n:String!){repository(owner:$o,name:$n){id}}',{'o':owner,'n':name})['repository']
        created=client.graph('mutation($input:CreateDiscussionInput!){createDiscussion(input:$input){discussion{number}}}',{'input':{'repositoryId':node['id'],'categoryId':text(values,'category',True),'title':text(values,'title',True,256),'body':text(values,'body')}})['createDiscussion']['discussion']
        return {'ok':True,'message':'Discussion created.','target':target('discussion',repo,number=created['number'])}
    number=int(exp.get('discussion') or item['number'])
    node=client.graph('query($o:String!,$n:String!,$d:Int!){repository(owner:$o,name:$n){discussion(number:$d){id closed updatedAt}}}',{'o':owner,'n':name,'d':number})['repository']['discussion']
    if action=='discussion-reply':
        parent=client.graph('query($id:ID!){node(id:$id){... on DiscussionComment{id discussion{id}}}}',{'id':exp['comment']})['node']
        if not parent or parent['discussion']['id']!=node['id']: raise GhError('Comment belongs to another discussion.', 'input')
        client.graph('mutation($input:AddDiscussionCommentInput!){addDiscussionComment(input:$input){comment{id}}}',{'input':{'discussionId':node['id'],'replyToId':exp['comment'],'body':text(values,'body',True)}})
    elif action=='discussion-close':
        if node['updatedAt']!=exp['updated']: changed()
        mutation='reopenDiscussion' if node['closed'] else 'closeDiscussion'; inputtype='ReopenDiscussionInput' if node['closed'] else 'CloseDiscussionInput'
        client.graph(f'mutation($input:{inputtype}!){{{mutation}(input:$input){{discussion{{id closed}}}}}}',{'input':{'discussionId':node['id']}})
    else:
        comment=client.graph('query($id:ID!){node(id:$id){... on DiscussionComment{id isAnswer discussion{id}}}}',{'id':exp['comment']})['node']
        if not comment or comment['discussion']['id']!=node['id'] or comment['isAnswer']!=exp['answer']: changed()
        mutation='unmarkDiscussionCommentAsAnswer' if comment['isAnswer'] else 'markDiscussionCommentAsAnswer'
        client.graph(f'mutation($id:ID!){{{mutation}(input:{{id:$id}}){{discussion{{id}}}}}}',{'id':comment['id']})
    return {'ok':True,'message':'Discussion updated.'}
