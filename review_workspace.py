"""Paged reviews, exact-thread replies and durable, commit-bound batch reviews."""
import base64
import hashlib
import json
import re
from urllib.parse import urlencode
from github_client import GhError
from lifecycle import choice, field, changed, text
from navigation import repository, path
from workspace import target, block, detail_base, page_controls, selector
from review_threads import diff_lines
import local_state

ACTIONS={'thread-reply','stage-comment','discard-review','submit-review','file-viewed','apply-suggestion'}
THREAD='''id path line startLine originalLine diffSide isResolved isOutdated viewerCanResolve viewerCanUnresolve
 pullRequest{number headRefOid baseRefName repository{nameWithOwner}}
 comments(first:30,after:$cursor){totalCount pageInfo{hasNextPage endCursor} nodes{id databaseId body updatedAt author{login}}}'''


def key(repo,number): return repo+'#'+str(number)


def snapshot(pr):
    return {'headSha':pr['head']['sha'],'baseRef':pr['base']['ref'],'number':pr['number']}


def checked_pr(client,repo,number,expected):
    pr=client.api(f'repos/{repo}/pulls/{int(number)}')
    if pr['head']['sha']!=expected.get('headSha') or pr['base']['ref']!=expected.get('baseRef'): changed()
    return pr


def file_operations(file,pr,page=1,size=100):
    lines,rendered=diff_lines(file.get('patch'))
    if not lines: return []
    expected={**snapshot(pr),'path':file['filename'],'page':page,'size':size}
    return [choice('stage-comment','Add to pending review','Save a comment locally. Submit the whole review when ready.',expected,[
        selector('location','End line',lines),dict(key='start',label='Start line (optional; same side)',value='',options=['']+lines),
        field('body','Comment (use a ```suggestion block to propose replacement code)',required=True,multiline=True)]),
        choice('file-viewed','Mark file viewed','Record this file as viewed on GitHub at the current PR commit.',expected,[selector('viewed','Viewed',['yes','no'])])]


def thread(client,repo,thread_id,cursor=None):
    node=client.graph('query($id:ID!,$cursor:String){node(id:$id){... on PullRequestReviewThread{'+THREAD+'}}}',{'id':thread_id,'cursor':cursor}).get('node')
    if not node or node['pullRequest']['repository']['nameWithOwner'].lower()!=repo.lower():
        raise GhError('Review thread does not belong to this repository.', 'input')
    return node


def detail(client,item):
    repo=repository(item['repo']); kind=item['kind']; number=int(item['number']); base=f'repos/{repo}/pulls/{number}'
    pr=client.api(base); result=detail_base(item,f"{repo} #{number} · {item.get('section','Review')}")
    result['actions']=[]
    if kind=='review-page':
        section=item.get('section','files'); n=item.get('page',1)
        if type(n) is not int or not 1<=n<=1000: raise GhError('Invalid page.', 'input')
        if section=='pending':
            pending=local_state.read(client.account,'reviews').get(key(repo,number),{})
            rows=[block(c['path']+':'+str(c['line']),c['body'],markdown=True) for c in pending.get('comments',[])]
            if pending and pending['sha']!=pr['head']['sha']: result['warnings'].append('The PR changed. This saved review cannot be submitted; discard it and review the new commit.')
            result['tabs']=[dict(id='reviews',label='Pending review',blocks=rows)]
            result['actions']=[choice('submit-review','Submit review','Post all saved comments together with this review.',snapshot(pr),[
                selector('event','Review',['COMMENT','APPROVE','REQUEST_CHANGES']),field('body','Summary',multiline=True)]),
                choice('discard-review','Discard pending review','Delete this local review draft.',snapshot(pr))]
            return result
        if section not in ('files','reviews','comments'): raise GhError('Invalid review view.', 'input')
        nodes,headers=client.response(base+'/'+section+'?'+urlencode({'per_page':100,'page':n}))
        rows=[]
        if section=='files':
            viewed=local_state.read(client.account,'viewed') if client.account else {}
            for file in nodes:
                _,rendered=diff_lines(file.get('patch'))
                seen=viewed.get(key(repo,number)+':'+pr['head']['sha']+':'+file['filename'])
                rows.append(block(file['filename']+f" · +{file.get('additions',0)} −{file.get('deletions',0)}"+(' · viewed' if seen else ''),rendered or 'Binary or oversized patch: preview unavailable.',operations=file_operations(file,pr,n),operationLabel='Review file'))
        else:
            rows=[block('@'+(node.get('user') or {}).get('login','ghost')+' · '+str(node.get('state') or node.get('path') or ''),node.get('body') or '',markdown=True) for node in nodes]
        result['tabs']=[dict(id='changes' if section=='files' else 'reviews',label=section.title(),blocks=rows)]
        page_controls(result,item,'rel="next"' in headers.get('link',''),pr.get('changed_files') if section=='files' else None,len(nodes))
    elif kind=='thread-page':
        owner,name=repo.split('/')
        data=client.graph('''query($o:String!,$r:String!,$n:Int!,$cursor:String){repository(owner:$o,name:$r){pullRequest(number:$n){reviewThreads(first:30,after:$cursor){totalCount pageInfo{hasNextPage endCursor} nodes{id path line originalLine isResolved isOutdated comments(first:1){nodes{body author{login}}}}}}}}''',{'o':owner,'r':name,'n':number,'cursor':item.get('cursor')})['repository']['pullRequest']['reviewThreads']
        rows=[block(n['path']+':'+str(n['line'] or n['originalLine'] or '?'),('Resolved' if n['isResolved'] else 'Unresolved')+(' · outdated' if n['isOutdated'] else ''),target('thread',repo,number=number,thread=n['id']),operationLabel='Read / reply to thread') for n in data['nodes']]
        result['tabs']=[dict(id='threads',label='Review threads',blocks=rows)]
        result['pageLabel']=str(data['totalCount'])+' threads total'
        if data['pageInfo']['hasNextPage']: result['nextTarget']={**item,'cursor':data['pageInfo']['endCursor']}
    else:
        node=thread(client,repo,item['thread'],item.get('cursor'))
        if node['pullRequest']['number']!=number: raise GhError('Thread belongs to another PR.', 'input')
        result['title']=node['path']+':'+str(node['line'] or node['originalLine'] or '?')
        result['body']=('Resolved' if node['isResolved'] else 'Unresolved')+(' · outdated' if node['isOutdated'] else '')
        expected={**snapshot(pr),'thread':node['id']}
        result['actions']=[choice('thread-reply','Reply in this thread','Post to this inline conversation.',expected,[field('body','Reply',required=True,multiline=True)])]
        rows=[]
        for comment in node['comments']['nodes']:
            operations=[]
            suggestions=re.findall(r'```suggestion\r?\n(.*?)\r?\n```',comment['body'],re.S)
            if len(suggestions)==1 and not node['isOutdated'] and node['diffSide']=='RIGHT' and node['line'] and pr['state']=='open':
                operations.append(choice('apply-suggestion','Apply suggestion','Commit this replacement to the PR source branch. This starts new CI runs.',
                    {**expected,'cursor':item.get('cursor'),'comment':comment['id'],'updated':comment['updatedAt'],'replacementHash':hashlib.sha256(suggestions[0].encode()).hexdigest()},[
                        field('message','Commit message','Apply review suggestion',True)]))
            rows.append(block('@'+(comment.get('author') or {}).get('login','ghost'),comment['body'],operations=operations,operationLabel='Suggestion actions',markdown=True))
        result['tabs']=[dict(id='conversation',label='Thread',blocks=rows)]
        if node['comments']['pageInfo']['hasNextPage']: result['nextTarget']={**item,'cursor':node['comments']['pageInfo']['endCursor']}
    return result


def validate_comment(client,repo,pr,expected,values):
    number=pr['number']; size=int(expected.get('size',100)); p=int(expected.get('page',1))
    if size!=100 or not 1<=p<=1000: raise GhError('Invalid diff page.', 'input')
    files=client.api(f'repos/{repo}/pulls/{number}/files?per_page=100&page={p}')
    file=next((f for f in files if f['filename']==expected.get('path')),None)
    if not file: changed()
    locations,_=diff_lines(file.get('patch'))
    end=text(values,'location',True); start=text(values,'start')
    if end not in locations or (start and start not in locations): changed()
    a=re.fullmatch(r'(New|Old) line (\d+)',end); b=re.fullmatch(r'(New|Old) line (\d+)',start) if start else None
    if b and (b[1]!=a[1] or int(b[2])>int(a[2])): raise GhError('Choose a range on the same side, in ascending order.', 'input')
    result={'path':file['filename'],'line':int(a[2]),'side':'RIGHT' if a[1]=='New' else 'LEFT','body':text(values,'body',True)}
    if b and b[2]!=a[2]: result.update(start_line=int(b[2]),start_side=result['side'])
    return result


def perform(client,request):
    if request.get('confirmed') is not True: raise GhError('Confirm this review action.', 'input')
    item=request['item']; repo=repository(item['repo']); values=request.get('values') or {}; expected=request.get('expected') or {}; action=request['action']
    number=expected.get('number') or item.get('number'); pr=checked_pr(client,repo,number,expected)
    if action=='discard-review':
        local_state.put(client.account,'reviews',key(repo,number),None)
    elif action=='stage-comment':
        if pr['state']!='open': raise GhError('This PR is no longer open.', 'blocked')
        comment=validate_comment(client,repo,pr,expected,values)
        review=local_state.read(client.account,'reviews').get(key(repo,number),{'sha':pr['head']['sha'],'comments':[]})
        if review['sha']!=pr['head']['sha']: raise GhError('Discard the review for the older commit first.', 'changed')
        if len(review['comments'])>=50: raise GhError('Submit this batch of 50 comments before adding another.', 'response-limit')
        review['comments'].append(comment); local_state.put(client.account,'reviews',key(repo,number),review)
        return {'ok':True,'message':'Comment saved to pending review.','target':target('review-page',repo,number=number,section='pending')}
    elif action=='submit-review':
        if pr['state']!='open': raise GhError('This PR is no longer open.', 'blocked')
        review=local_state.read(client.account,'reviews').get(key(repo,number),{'sha':pr['head']['sha'],'comments':[]})
        if review['sha']!=pr['head']['sha']: changed()
        event=values.get('event'); body=text(values,'body')
        if event not in ('COMMENT','APPROVE','REQUEST_CHANGES'): raise GhError('Choose a review type.', 'input')
        if (event=='REQUEST_CHANGES' or (event=='COMMENT' and not review['comments'])) and not body.strip(): raise GhError('This review needs a summary.', 'input')
        result=client.api(f'repos/{repo}/pulls/{number}/reviews','POST',{'commit_id':pr['head']['sha'],'event':event,'body':body,'comments':review['comments']})
        if not result.get('id') or result.get('state') not in ('COMMENTED','APPROVED','CHANGES_REQUESTED'): raise GhError('GitHub did not confirm review submission. Refresh before retrying.', 'unconfirmed')
        local_state.put(client.account,'reviews',key(repo,number),None)
    elif action=='file-viewed':
        action_name='markFileAsViewed' if values.get('viewed')=='yes' else 'unmarkFileAsViewed'
        input_name='MarkFileAsViewedInput' if action_name=='markFileAsViewed' else 'UnmarkFileAsViewedInput'
        client.graph(f'mutation($input:{input_name}!){{{action_name}(input:$input){{clientMutationId}}}}',{'input':{'pullRequestId':pr['node_id'],'path':expected['path']}})
        local_state.put(client.account,'viewed',key(repo,number)+':'+pr['head']['sha']+':'+expected['path'],values.get('viewed')=='yes')
    elif action in ('thread-reply','apply-suggestion'):
        node=thread(client,repo,expected['thread'],expected.get('cursor') if action=='apply-suggestion' else None)
        if node['pullRequest']['number']!=number or node['pullRequest']['headRefOid']!=pr['head']['sha']: changed()
        if action=='thread-reply':
            comments=node['comments']['nodes']
            if not comments: raise GhError('Thread has no parent comment.', 'input')
            client.api(f"repos/{repo}/pulls/{number}/comments/{comments[0]['databaseId']}/replies",'POST',{'body':text(values,'body',True)})
        else: apply_suggestion(client,repo,pr,node,expected,values)
    return {'ok':True,'message':'Review action completed.'}


def apply_suggestion(client,repo,pr,node,expected,values):
    if node['isOutdated'] or node['diffSide']!='RIGHT' or not node['line'] or pr['state']!='open': changed()
    comment=next((c for c in node['comments']['nodes'] if c['id']==expected.get('comment')),None)
    if not comment or comment['updatedAt']!=expected.get('updated'): changed()
    suggestions=re.findall(r'```suggestion\r?\n(.*?)\r?\n```',comment['body'],re.S)
    if len(suggestions)!=1 or hashlib.sha256(suggestions[0].encode()).hexdigest()!=expected.get('replacementHash'): changed()
    headrepo=repository(pr['head']['repo']['full_name']); ref=pr['head']['ref']; sha=pr['head']['sha']; base='repos/'+headrepo
    head=client.api(base+'/git/ref/heads/'+path(ref))
    if head['object']['sha']!=sha: changed()
    file=client.api(base+'/contents/'+path(node['path'])+'?'+urlencode({'ref':sha}))
    raw=base64.b64decode(file.get('content',''))
    if file.get('encoding')!='base64' or len(raw)>1024*1024 or b'\x00' in raw: raise GhError('Suggestion requires an available text file under 1 MiB.', 'unsupported')
    source=raw.decode('utf-8'); lines=source.splitlines(keepends=True); first=(node.get('startLine') or node['line'])-1; last=node['line']
    if not 0<=first<last<=len(lines): changed()
    replacement=suggestions[0]
    newline='\r\n' if '\r\n' in source else '\n'
    replacement=replacement.replace('\r\n','\n').replace('\n',newline)
    if lines[last-1].endswith('\n'): replacement+=newline
    updated=''.join(lines[:first])+replacement+''.join(lines[last:])
    commit=client.api(base+'/git/commits/'+sha)
    tree_sha=commit['tree']['sha']; mode=None
    pieces=node['path'].split('/')
    for index,piece in enumerate(pieces):
        entries=client.api(base+'/git/trees/'+tree_sha)
        entry=next((e for e in entries['tree'] if e['path']==piece),None)
        if not entry or entries.get('truncated'): raise GhError('Could not verify the source file mode.', 'unavailable')
        if index<len(pieces)-1:
            if entry['type']!='tree': raise GhError('Suggestion path crosses a non-directory.', 'blocked')
            tree_sha=entry['sha']
        else: mode=entry['mode']
    if mode not in ('100644','100755'): raise GhError('Suggestions apply only to regular text files.', 'unsupported')
    tree=client.api(base+'/git/trees','POST',{'base_tree':commit['tree']['sha'],'tree':[{'path':node['path'],'mode':mode,'type':'blob','content':updated}]})
    created=client.api(base+'/git/commits','POST',{'message':text(values,'message',True),'tree':tree['sha'],'parents':[sha]})
    # A concurrent branch advance rejects this non-fast-forward ref update.
    result=client.api(base+'/git/refs/heads/'+path(ref),'PATCH',{'sha':created['sha'],'force':False})
    if result.get('object',{}).get('sha')!=created['sha']: raise GhError('GitHub did not confirm the branch update. Refresh before retrying.', 'unconfirmed')
