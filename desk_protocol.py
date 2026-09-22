"""Reader decoration, local-only state requests and cached read-only fallback."""
from github_client import GhError
import local_state
import markup


def read(client,item,page=1,cursor=None):
    try:
        if client.account and client.api('user')['login']!=client.account:
            raise GhError('The active GitHub account changed. Refresh the dashboard.', 'auth')
        result=client.detail(item,page,cursor)
        import workspace_actions
        workspace_actions.enrich(client,result)
        markup.decorate(result)
        if client.account and page==1 and not cursor:
            local_state.cache(client.account,item,result)
        return result
    except GhError as exc:
        # Authentication/permission changes must never reveal cached private data.
        if client.account and exc.kind in ('timeout','offline'):
            result=local_state.cached(client.account,item)
            if result: return result
        raise


def state(client,req):
    account=client.account
    if req.get('write'):
        name=req.get('name'); key=req.get('key'); value=req.get('value')
        if name not in ('drafts','positions') or not isinstance(key,str) or len(key)>2000:
            raise GhError('Invalid local state request.', 'input')
        if name=='drafts' and (not isinstance(value,str) or len(value)>60000):
            raise GhError('Draft exceeds 60,000 characters.', 'input')
        if name=='positions' and (not isinstance(value,dict) or set(value)-{'tab','y'}):
            raise GhError('Invalid reading position.', 'input')
        local_state.put(account,name,key,value)
        return {'ok':True}
    return {'ok':True,'drafts':local_state.read(account,'drafts'),'positions':local_state.read(account,'positions')}


def pick(client,req):
    from workspace import page
    from navigation import repository
    key=req.get('field'); repo=req.get('repo',''); rows=[]
    number=req.get('page',1)
    item={'page':number}
    if key=='repo':
        nodes,more,_=page(client,'user/repos',item,params={'sort':'pushed','affiliation':'owner,collaborator,organization_member'})
        rows=[{'value':n['full_name'],'label':n['full_name']} for n in nodes]
    else:
        repository(repo)
        endpoint={'labels':'labels','assignees':'assignees','reviewers':'assignees','milestone':'milestones','base':'branches','head':'branches','ref':'branches','branch':'branches','target':'branches'}.get(key)
        if not endpoint: raise GhError('No picker is available for this field.', 'input')
        nodes,more,_=page(client,'repos/'+repo+'/'+endpoint,item)
        for n in nodes:
            value=str(n['number']) if key=='milestone' else n.get('name') or n['login']
            label=value+' · '+n['title'] if key=='milestone' else value
            rows.append({'value':value,'label':label})
    return {'ok':True,'items':rows,'more':more,'page':number,'field':key}
