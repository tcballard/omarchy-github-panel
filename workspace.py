"""Native repository workspace: bounded pages, internal links and discoverable views."""
import base64
import hashlib
import json
import re
from urllib.parse import urlencode
from github_client import GhError, notification_items
from lifecycle import choice, field
from navigation import repository, segment, path, resolve
import local_state

PAGE = 30
KINDS = {'collection','repository','code','code-url','release-tag','review-page','thread-page','thread','templates','template','workflow','discussion-replies','people'}


def target(kind, repo='', **values):
    return dict(kind=kind, repo=repo, **values)


def block(title, body='', action=None, **extra):
    return dict(title=title, body=body, action=action, **extra)


def detail_base(item, title):
    return dict(ok=True, target=item, title=title, subtitle=item.get('repo','GitHub'), body='',
                tabs=[], actions=[], canReply=False, warnings=[], nextPage=None, nextCursor=None, threadId='')


def selector(key, label, values, value=''):
    return dict(key=key,label=label,options=values,value=value or values[0],required=True)


def filter_action(item, fields):
    return choice('browse-filter','Filter this view','Choose which GitHub items to show.',{},fields)


def page(client, endpoint, item, key=None, params=None):
    number = item.get('page',1)
    if type(number) is not int or not 1 <= number <= 10000:
        raise GhError('Invalid page.', 'input')
    params = dict(params or {}, per_page=PAGE, page=number)
    response, headers = client.response(endpoint + ('&' if '?' in endpoint else '?') + urlencode(params))
    rows = response.get(key,[]) if key else response
    if not isinstance(rows,list): raise GhError('Unexpected GitHub list response.', 'parse')
    more = 'rel="next"' in headers.get('link','')
    return rows, more, response.get('total_count') if isinstance(response,dict) else None


def page_controls(result,item,more,total=None,count=0):
    n=item.get('page',1)
    result['pageLabel']=f'Page {n} · {count} items' + (f' · {total} total' if total is not None else '')
    result['nextTarget']={**item,'page':n+1} if more else None
    result['previousTarget']={**item,'page':n-1} if n>1 else None
    result['body']=result.get('body','') or ('No matches in this view.' if not count else '')


def repo_row(node):
    return block(node['full_name'], (node.get('description') or 'No description.') +
        f"\n{node.get('language') or '—'} · ★ {node.get('stargazers_count',0)}" + (' · private' if node.get('private') else '') + (' · fork' if node.get('fork') else ''),
        target('repository',node['full_name']),operationLabel='Open repository')


def collection(client,item):
    kind=item.get('collection','repositories'); repo=item.get('repo','')
    if repo: repository(repo)
    result=detail_base(item,kind.replace('-',' ').title())
    rows=[]; more=False; total=None; filters=[]; nodes=[]
    base=f'repos/{repo}'
    account=client.account or client.api('user')['login']
    if kind in ('saved','pinned','recent'):
        data=local_state.read(account,'preferences').get(kind,{} if kind=='saved' else [])
        if kind=='saved':
            rows=[block(name,'Saved view',value,operationLabel='Open saved view',operations=[choice('delete-view','Remove saved view','Remove this local saved view.',{'name':name})]) for name,value in data.items()]
        else:
            rows=[block(name,'',target('repository',name),operationLabel='Open repository') for name in data]
    elif kind in ('repositories','stars'):
        query=str(item.get('query','')).strip(); owner=str(item.get('owner','')).strip(); scope=item.get('scope','affiliated')
        filters=[field('query','Search repositories',query),field('owner','Owner or organisation (optional)',owner)]
        if kind=='repositories': filters.append(selector('scope','Repositories',['affiliated','owned','all-public'],scope))
        if owner and not re.fullmatch(r'[A-Za-z0-9_-]+',owner): raise GhError('Invalid owner.', 'input')
        if kind=='stars' and (query or owner):
            return search_stars(client,item,filters)
        elif kind=='stars':
            nodes,more,total=page(client,'user/starred',item,params={'sort':'updated','direction':'desc'})
            if query or owner:
                nodes=[n for n in nodes if (not query or query.lower() in (n['full_name']+' '+(n.get('description') or '')).lower()) and (not owner or n['owner']['login'].lower()==owner.lower())]
                result['warnings'].append('Star search filters each page of your complete starred list. Continue through pages to see older matching stars.')
        elif query or (kind=='repositories' and scope=='all-public'):
            terms=[query] if query else []
            if owner: terms.append('user:'+owner)
            elif scope=='owned': terms.append('user:'+account)
            elif scope!='all-public':
                # Search API's user qualifier does not mean collaborator access.
                result['warnings'].append('Repository search covers accessible GitHub repositories. Set an owner to narrow it; clear search for your affiliated list.')
            nodes,more,total=page(client,'search/repositories',item,'items',{'q':' '.join(terms),'sort':'updated'})
        elif owner:
            who=client.api('users/'+owner)
            if owner.lower()==account.lower():
                nodes,more,total=page(client,'user/repos',item,params={'sort':'pushed','affiliation':'owner'})
            else:
                nodes,more,total=page(client,('orgs/' if who['type']=='Organization' else 'users/')+owner+'/repos',item,params={'sort':'pushed','type':'all'})
                if who['type']!='Organization': result['warnings'].append('Other users’ profile listings show their public repositories. Use Affiliated to include private repositories shared with you.')
        else: nodes,more,total=page(client,'user/repos',item,params={'sort':'pushed','affiliation':'owner' if scope=='owned' else 'owner,collaborator,organization_member'})
        rows=[repo_row(n) for n in nodes]
    elif kind in ('issues','pulls'):
        from search_client import search
        view=item.get('view','repository' if repo else ('assigned' if kind=='issues' else 'incoming'))
        owner=item.get('owner',account); query=item.get('query',''); state=item.get('state','open')
        options=['repository','assigned','created','involving','incoming'] if kind=='issues' else ['repository','authored','review-requested','involving','incoming']
        filters=[selector('view','View',options,view),field('repo','Repository (optional)',repo),field('owner','Incoming owner / organisation',owner),selector('state','State',['open','closed','all']+(['merged'] if kind=='pulls' else []),state),field('query','Extra GitHub search qualifiers',query)]
        if view not in options: raise GhError('Unknown view.', 'input')
        qualifiers={'assigned':'assignee:@me','created':'author:@me','authored':'author:@me','involving':'involves:@me','review-requested':'review-requested:@me'}
        if view=='repository' and not repo: raise GhError('Choose a repository or a personal view.', 'input')
        if view=='incoming':
            if not re.fullmatch(r'[A-Za-z0-9_-]+',owner): raise GhError('Enter an owner or organisation.', 'input')
            query=f'({query}) user:{owner}' if query else f'user:{owner}'
        elif view in qualifiers: query=f'({query}) {qualifiers[view]}' if query else qualifiers[view]
        if view=='repository' and repo and not query:
            endpoint=base+('/issues' if kind=='issues' else '/pulls')
            nodes,more,total=page(client,endpoint,item,params={'state':'closed' if state=='merged' else state,'sort':'updated','direction':'desc'})
            if kind=='issues': nodes=[n for n in nodes if not n.get('pull_request')]
            if state=='merged': nodes=[n for n in nodes if n.get('merged_at')]
            rows=[block(f"#{n['number']} · {n['title']}",('MERGED' if n.get('merged_at') else n['state'].upper())+' · @'+(n.get('user') or {}).get('login','ghost'),
                target('issue' if kind=='issues' else 'pull-request',repo,number=n['number']),operationLabel='Read '+('issue' if kind=='issues' else 'PR')) for n in nodes]
            if kind=='issues' or state=='merged': result['warnings'].append('GitHub returns mixed records on these pages; a filtered page can be empty while more pages remain.')
        else:
            found=search({'query':query,'repo':repo,'kind':'issue' if kind=='issues' else 'pr','state':state,'page':item.get('page',1)},client)
            rows=[block(f"{n['repo']} #{n['number']} · {n['title']}",f"{n['state']} · @{n['author']} · {n['updatedAt']}",n,operationLabel='Read '+('issue' if kind=='issues' else 'PR')) for n in found['items']]
            more,total=found['hasMore'],found['total']
            if found['warning']: result['warnings'].append(found['warning'])
        # Search uses 50 records per page; page controls do not assume page size.
    elif kind=='inbox':
        mode=item.get('mode','unread'); reason=item.get('reason','all')
        filters=[field('repo','Repository (optional)',repo),selector('mode','Show',['unread','all'],mode),selector('reason','Reason',['all','mention','review_requested','author','assign','comment','ci_activity','subscribed','team_mention'],reason)]
        nodes,more,total=page(client,base+'/notifications' if repo else 'notifications',item,params={'all':str(mode=='all').lower(),'participating':'false'})
        visible=[n for n in nodes if reason=='all' or n.get('reason')==reason]
        for n, link in zip(visible,notification_items(visible)):
            operations=[choice('notification-done','Done','Remove this notification from your inbox.',{'thread':str(n['id']),'updated':n.get('updated_at')}),choice('notification-unsubscribe','Unsubscribe','Ignore future notifications for this thread.',{'thread':str(n['id']),'updated':n.get('updated_at')})]
            rows.append(block(link['title'],link['repo']+' · '+link['lane']+(' · unread' if n['unread'] else ' · read'),link,operations=operations,operationLabel='Read / manage notification'))
        if visible:
            result['actions'].append(choice('notifications-read','Mark this page read','Mark only the displayed notifications as read. New or changed notifications are left untouched.',{'threads':[{'id':str(n['id']),'updated':n.get('updated_at')} for n in visible]}))
        if reason!='all': result['warnings'].append('Reason is filtered within each server page. Continue to the next page even if this page has no matches.')
    else:
        if not repo: raise GhError('Choose a repository first.', 'input')
        if kind=='branches':
            nodes,more,total=page(client,base+'/branches',item)
            rows=[block(n['name'],'Protected' if n.get('protected') else '',target('code',repo,ref=n['name'],path=''),operationLabel='Browse branch') for n in nodes]
        elif kind=='commits':
            filters=[field('ref','Branch or SHA',item.get('ref',''))]
            nodes,more,total=page(client,base+'/commits',item,params={'sha':item['ref']} if item.get('ref') else {})
            rows=[block(n['commit']['message'].split('\n')[0],n['sha'][:12]+' · '+n['commit'].get('author',{}).get('name',''),target('commit',repo,number=n['sha']),operationLabel='Read commit') for n in nodes]
        elif kind=='releases':
            nodes,more,total=page(client,base+'/releases',item)
            rows=[block(n.get('name') or n['tag_name'],n['tag_name']+(' · draft' if n['draft'] else '')+(' · prerelease' if n['prerelease'] else ''),target('release',repo,number=n['id']),operationLabel='Read release') for n in nodes]
            result['actions'].append(release_create())
        elif kind=='runs':
            branch=item.get('branch',''); workflow=item.get('workflow',''); status=item.get('status','all')
            filters=[field('branch','Branch',branch),field('workflow','Workflow filename or ID',workflow),selector('status','Status',['all','queued','in_progress','completed','success','failure','cancelled'],status)]
            params={k:v for k,v in [('branch',branch),('status',status if status!='all' else '')] if v}
            if item.get('sha'): params['head_sha']=item['sha']
            endpoint=base+'/actions/'+('workflows/'+segment(workflow)+'/runs' if workflow else 'runs')
            nodes,more,total=page(client,endpoint,item,'workflow_runs',params)
            rows=[block(n.get('display_title') or n.get('name','Workflow'),f"{n.get('conclusion') or n.get('status')} · {n.get('head_branch')} · {n.get('created_at')}",target('run',repo,number=n['id']),operationLabel='Jobs and logs') for n in nodes]
        elif kind=='workflows':
            nodes,more,total=page(client,base+'/actions/workflows',item,'workflows')
            rows=[block(n['name'],n['path']+' · '+n['state'],target('workflow',repo,number=n['id']),operationLabel='Runs and manual dispatch') for n in nodes]
        elif kind=='discussions':
            owner,name=repo.split('/'); cursor=item.get('cursor')
            data=client.graph('''query($owner:String!,$name:String!,$cursor:String){repository(owner:$owner,name:$name){discussions(first:30,after:$cursor,orderBy:{field:UPDATED_AT,direction:DESC}){totalCount pageInfo{hasNextPage endCursor} nodes{number title updatedAt category{name} author{login}}}}}''',{'owner':owner,'name':name,'cursor':cursor})['repository']['discussions']
            nodes=data['nodes']; total=data['totalCount']
            rows=[block(n['title'],n['category']['name']+' · '+n['updatedAt'],target('discussion',repo,number=n['number']),operationLabel='Read discussion') for n in nodes]
            if data['pageInfo']['hasNextPage']: result['cursorTarget']={**item,'cursor':data['pageInfo']['endCursor'],'page':item.get('page',1)+1}
            result['actions'].append(choice('create-discussion','Create discussion','Create a discussion in this repository.',{},[field('category','Category ID (see repository categories)',required=True),field('title','Title',required=True),field('body','Description',multiline=True)]))
            result['links']=[block('Discussion categories','',target('collection',repo,collection='categories'))]
        elif kind=='categories':
            owner,name=repo.split('/')
            data=client.graph('query($o:String!,$n:String!){repository(owner:$o,name:$n){id discussionCategories(first:100){nodes{id name description isAnswerable} pageInfo{hasNextPage}}}}',{'o':owner,'n':name})['repository']
            rows=[block(n['name'],n['description'],operations=[choice('create-discussion','Create discussion','Create a discussion in '+n['name']+'.',{},[field('category','Category ID',n['id'],True),field('title','Title',required=True),field('body','Description',multiline=True)])]) for n in data['discussionCategories']['nodes']]
            if data['discussionCategories']['pageInfo']['hasNextPage']: result['warnings'].append('Only the first 100 categories are shown.')
        elif kind=='milestones':
            nodes,more,total=page(client,base+'/milestones',item,params={'state':'all'})
            rows=[block(f"#{n['number']} · {n['title']}",n.get('description') or '') for n in nodes]
        elif kind=='timeline':
            nodes,more,total=page(client,base+'/issues/'+str(int(item['number']))+'/timeline',item)
            rows=[block(str(n.get('event','Event'))+' · @'+(n.get('actor') or n.get('user') or {}).get('login','ghost'),
                (n.get('body') or '')+'\n'+str(n.get('created_at',''))+'\n'+json.dumps({k:n[k] for k in ('label','milestone','source','commit_id','rename') if k in n},ensure_ascii=False),markdown=True) for n in nodes]
        elif kind=='jobs':
            nodes,more,total=page(client,base+'/actions/runs/'+str(int(item['number']))+'/jobs',item,'jobs')
            rows=[block(n['name'],str(n.get('conclusion') or n.get('status'))+'\n'+'\n'.join(str(s.get('conclusion') or s.get('status'))+': '+s['name'] for s in n.get('steps',[])),
                target('job',repo,number=n['id']) if n['status']=='completed' else None,operationLabel='Read logs') for n in nodes]
        elif kind=='artifacts':
            nodes,more,total=page(client,base+'/actions/runs/'+str(int(item['number']))+'/artifacts',item,'artifacts')
            rows=[block(n['name'],str(n['size_in_bytes'])+' bytes'+(' · expired' if n.get('expired') else ''),operations=[] if n.get('expired') else [choice('download-artifact','Download artifact','Save this ZIP in ~/Downloads. It will not be extracted.',{'id':n['id'],'name':n['name'],'size':n['size_in_bytes']})],operationLabel='Download') for n in nodes]
        elif kind=='annotations':
            nodes,more,total=page(client,base+'/check-runs/'+str(int(item['number']))+'/annotations',item)
            rows=[block(n['path']+':'+str(n['start_line'])+' · '+n['annotation_level'],(n.get('title') or '')+'\n'+n['message']+'\n'+(n.get('raw_details') or '')) for n in nodes]
        elif kind in ('labels','people'):
            nodes,more,total=page(client,base+('/labels' if kind=='labels' else '/assignees'),item)
            rows=[block(n.get('name') or n['login'],n.get('description') or '') for n in nodes]
        else: raise GhError('Unknown collection.', 'input')
    if filters: result['actions'].insert(0,filter_action(item,filters))
    result['actions'].append(choice('save-view','Save this view','Save these filters locally for quick access.',{},[field('name','Name',result['title'],True)]))
    result['tabs']=[dict(id='collection',label=result['title'],blocks=rows)]
    if result.get('links'): result['tabs'][0]['blocks']=result['links']+rows
    page_controls(result,item,more,total,len(rows))
    if result.get('cursorTarget'): result['nextTarget']=result['cursorTarget']
    return result


def release_create():
    return choice('create-release','Draft release','Create an unpublished release. Publish it after checking the notes and assets.',{},[
        field('tag','Tag',required=True),field('target','Target branch or commit (for a new tag)'),field('name','Release title'),field('body','Release notes',multiline=True),selector('prerelease','Prerelease',['no','yes'])])


def search_stars(client,item,fields):
    """Scan a complete star list in resumable bounded chunks; never a global guess."""
    query=str(item.get('query','')).lower(); owner=str(item.get('owner','')).lower()
    identifier=hashlib.sha256((query+'\n'+owner).encode()).hexdigest()
    start=item.get('scan',1)
    if type(start) is not int or start<1: raise GhError('Invalid star search cursor.', 'input')
    progress=local_state.read(client.account,'star-search').get(identifier,{}) if start>1 else {}
    if start>1 and progress.get('next')!=start: raise GhError('This star search changed. Apply the filter again.', 'changed')
    matches=progress.get('matches',{}); scanned=progress.get('scanned',0); more=False
    for number in range(start,start+5):
        nodes,headers=client.response('user/starred?'+urlencode({'per_page':100,'page':number,'sort':'created','direction':'desc'}))
        scanned+=len(nodes)
        for node in nodes:
            if (not query or query in (node['full_name']+' '+(node.get('description') or '')).lower()) and (not owner or node['owner']['login'].lower()==owner):
                matches[node['full_name']]={k:node.get(k) for k in ('full_name','description','language','stargazers_count','private','fork')}
        more='rel="next"' in headers.get('link','')
        if not more: break
    nextpage=number+1 if more else None
    local_state.put(client.account,'star-search',identifier,{'matches':matches,'scanned':scanned,'next':nextpage})
    result=detail_base(item,'Search your stars')
    result['tabs']=[dict(id='collection',label='Starred repositories',blocks=[repo_row(n) for n in matches.values()])]
    result['pageLabel']=f'{len(matches)} matches · {scanned} starred repositories scanned'+(' · search complete' if not more else '')
    result['actions']=[filter_action(item,fields),choice('save-view','Save this view','Save this star search locally.',{},[field('name','Name','Star search',True)])]
    if more:
        result['nextTarget']={**item,'scan':nextpage}
        result['warnings'].append('Search is still scanning your stars. Continue to include older stars; matches accumulate across chunks of up to 500 repositories.')
        result['nextLabel']='Continue star search'
    return result


def repository_detail(client,item):
    repo=repository(item['repo']); node=client.api('repos/'+repo)
    result=detail_base(item,repo); result['body']=node.get('description') or ''
    result['subtitle']=f"{node.get('visibility','public')} · ★ {node.get('stargazers_count',0)} · {node.get('language') or '—'}"
    links=[block(label,'',target('collection',repo,collection=kind),operationLabel='Open '+label.lower()) for kind,label in [('issues','Issues'),('pulls','Pull requests'),('runs','Actions runs'),('workflows','Workflows'),('releases','Releases'),('branches','Branches'),('commits','Commits'),('discussions','Discussions')]]
    links.insert(0,block('Code','',target('code',repo,ref=node['default_branch'],path=''),operationLabel='Browse files'))
    links.append(block('New issue from a template','',target('templates',repo),operationLabel='Choose issue template'))
    result['tabs']=[dict(id='overview',label='Overview',blocks=links)]
    result['markdownRef']=node['default_branch']
    try:
        readme=client.api('repos/'+repo+'/readme')
        result['tabs'].append(dict(id='readme',label='README',blocks=[block('README',decode_content(readme),markdown=True)]))
    except GhError as exc: result['warnings'].append('README unavailable: '+str(exc))
    result['actions']=[choice('star','Star repository','Add this repository to your GitHub stars.',{}),choice('unstar','Unstar repository','Remove this repository from your GitHub stars.',{}),choice('pin','Pin locally','Keep this repository in Pinned.',{}),choice('unpin','Unpin locally','Remove this repository from Pinned.',{}),
        choice('create-pr','Create pull request','Open a PR from an existing pushed branch.',{},[field('title','Title',required=True),field('head','Source branch or owner:branch',required=True),field('base','Target branch',node['default_branch'],True),field('body','Description',multiline=True),selector('draft','Draft',['yes','no'])]),release_create()]
    if client.account:
        recent=local_state.read(client.account,'preferences').get('recent',[])
        local_state.put(client.account,'preferences','recent',([repo]+[r for r in recent if r!=repo])[:50])
    return result


def decode_content(node):
    if node.get('encoding')!='base64': raise GhError('GitHub did not include file contents; this file may be too large.', 'response-limit')
    raw=base64.b64decode(node.get('content',''))
    if len(raw)>1024*1024: raise GhError('File exceeds the 1 MiB native preview limit.', 'response-limit')
    if b'\x00' in raw: raise GhError('Binary file: no text preview is available.', 'unsupported')
    return raw.decode('utf-8','replace')


def code_detail(client,item):
    repo=repository(item['repo']); ref=str(item.get('ref','HEAD')); filename=item.get('path','')
    result=detail_base(item,filename or repo+' / code')
    result['subtitle']=repo+' · '+ref; result['markdownRef']=ref
    node=client.api('repos/'+repo+'/contents/'+path(filename)+'?'+urlencode({'ref':ref}))
    result['actions']=[filter_action(item,[field('ref','Branch, tag or SHA',ref,True),field('path','File or folder',filename)])]
    if isinstance(node,list):
        rows=[block(n['name'],n['type'],target('code',repo,ref=ref,path=n['path']),operationLabel='Open') for n in sorted(node,key=lambda x:(x['type']!='dir',x['name'].lower()))]
        if len(node)>=1000: result['warnings'].append('GitHub Contents API limits directories to 1,000 entries. Additional entries cannot be displayed in this view.')
        result['tabs']=[dict(id='files',label='Files',blocks=rows)]
    elif node.get('type')=='file':
        try: text=decode_content(node)
        except GhError as exc: text=str(exc)
        result['tabs']=[dict(id='code',label='Source',blocks=[block(filename,text)])]
        if filename.lower().endswith(('.md','.markdown')): result['tabs'].insert(0,dict(id='readme',label='Preview',blocks=[block(filename,text,markdown=True)]))
    else: result['body']='Symlink or submodule: '+str(node.get('target') or node.get('submodule_git_url') or '')
    return result


def detail(client,item):
    kind=item.get('kind')
    if kind=='collection': return collection(client,item)
    if kind=='repository': return repository_detail(client,item)
    if kind=='code': return code_detail(client,item)
    repo=repository(item['repo'])
    if kind=='code-url':
        parts=item['path'].split('/')
        # Resolve using branches/tags APIs instead of guessing where ref ends.
        for size in range(len(parts),0,-1):
            ref='/'.join(parts[:size])
            for prefix in ('heads','tags'):
                try: client.api('repos/'+repo+'/git/ref/'+prefix+'/'+path(ref))
                except GhError: continue
                return code_detail(client,target('code',repo,ref=ref,path='/'.join(parts[size:])))
        if re.fullmatch(r'[0-9a-fA-F]{7,40}',parts[0]): return code_detail(client,target('code',repo,ref=parts[0],path='/'.join(parts[1:])))
        raise GhError('The branch or tag in this URL could not be resolved.', 'unavailable')
    if kind=='release-tag':
        node=client.api('repos/'+repo+'/releases/tags/'+segment(item['tag']))
        return client.detail(target('release',repo,number=node['id']))
    if kind in ('review-page','thread-page','thread'):
        import review_workspace
        return review_workspace.detail(client,item)
    if kind in ('templates','template','workflow','discussion-replies','people'):
        import authoring
        return authoring.detail(client,item)
    raise GhError('Unknown workspace view.', 'input')
