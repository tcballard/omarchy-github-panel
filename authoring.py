"""Issue templates, workflow forms and nested discussion readers."""
import re
from urllib.parse import urlencode
from github_client import GhError
from lifecycle import choice, field
from navigation import repository, path, segment
from workspace import block, target, detail_base, selector, decode_content, filter_action


def yaml_document(source):
    try:
        import yaml
    except ImportError as exc:
        raise GhError('Install python-yaml to use GitHub issue forms and workflow input forms.', 'dependency') from exc
    if len(source)>262144: raise GhError('YAML form exceeds 256 KiB.', 'response-limit')
    class FormLoader(yaml.SafeLoader):
        count=0
        depth=0
        def compose_node(self,parent,index):
            self.count+=1; self.depth+=1
            if self.count>10000 or self.depth>40:
                raise GhError('YAML form is too complex.', 'response-limit')
            try: return super().compose_node(parent,index)
            finally: self.depth-=1
    try: return yaml.load(source,Loader=FormLoader) or {}
    except yaml.YAMLError as exc: raise GhError('Could not parse this repository form: '+str(exc)[:200], 'parse') from exc


def template_form(client,repo,filename):
    if not filename.startswith('.github/ISSUE_TEMPLATE/') or not filename.lower().endswith(('.md','.yaml','.yml')):
        raise GhError('Invalid issue template.', 'input')
    node=client.api('repos/'+repo+'/contents/'+path(filename))
    source=decode_content(node)
    expected={'path':filename,'sha':node['sha']}
    if filename.lower().endswith('.md'):
        metadata={}
        if source.startswith('---\n'):
            parts=source.split('---',2)
            if len(parts)==3: metadata=yaml_document(parts[1]); source=parts[2].lstrip('\n')
        return choice('create-template-issue','Create issue','Create an issue using '+filename+'.',expected,
            [field('title','Title',str(metadata.get('title') or ''),True),field('body','Description',source,multiline=True)]),metadata
    schema=yaml_document(source)
    fields=[field('title','Title',str(schema.get('title') or ''),True)]
    for index, entry in enumerate(schema.get('body',[])):
        if not isinstance(entry,dict): continue
        kind=entry.get('type'); attrs=entry.get('attributes') or {}; required=bool((entry.get('validations') or {}).get('required'))
        key='form_'+str(index); label=str(attrs.get('label') or entry.get('id') or 'Field')
        if kind=='markdown': continue
        if kind in ('input','textarea'):
            fields.append(field(key,label,str(attrs.get('value') or ''),required,kind=='textarea'))
        elif kind=='dropdown':
            values=[str(x) for x in attrs.get('options',[])]
            if attrs.get('multiple'):
                fields.append(dict(field(key,label+' (one selection per line)',required=required,multiline=True),suggestions=values))
            else:
                fields.append(dict(key=key,label=label,options=['']+values,value='',required=required))
        elif kind=='checkboxes':
            for j,option in enumerate(attrs.get('options',[])):
                fields.append(selector(key+'_'+str(j),str(option.get('label') or label),['no','yes']))
        else: raise GhError('Unsupported issue form control: '+str(kind), 'unsupported')
    return choice('create-template-issue','Create issue',str(schema.get('description') or 'Complete this repository issue form.'),expected,fields),schema


def template_payload(client,repo,expected,values):
    form,schema=template_form(client,repo,expected['path'])
    if form['expected']!=expected: raise GhError('The issue template changed. Reopen it.', 'changed')
    from lifecycle import text
    title=text(values,'title',True,256)
    if expected['path'].lower().endswith('.md'): body=text(values,'body')
    else:
        parts=[]
        for index,entry in enumerate(schema.get('body',[])):
            kind=entry.get('type'); attrs=entry.get('attributes') or {}; key='form_'+str(index)
            required=bool((entry.get('validations') or {}).get('required')); label=str(attrs.get('label') or entry.get('id') or 'Field')
            if kind=='markdown': continue
            if kind=='checkboxes':
                lines=[]
                for j,option in enumerate(attrs.get('options',[])):
                    selected=values.get(key+'_'+str(j))=='yes'
                    if option.get('required') and not selected: raise GhError('Confirm: '+str(option['label']), 'input')
                    lines.append('- ['+('x' if selected else ' ')+'] '+str(option['label']))
                answer='\n'.join(lines)
            else:
                answer=text(values,key,required)
                if kind=='dropdown':
                    chosen=answer.splitlines() if attrs.get('multiple') else [answer]
                    if any(v and v not in [str(x) for x in attrs.get('options',[])] for v in chosen): raise GhError('Choose a listed value for '+label, 'input')
            parts.append('### '+label+'\n\n'+(answer or '_No response_'))
        body='\n\n'.join(parts)
    payload={'title':title,'body':body}
    for key in ('labels','assignees'):
        value=schema.get(key) or []
        if isinstance(value,str): value=[v.strip() for v in value.split(',') if v.strip()]
        if value: payload[key]=value
    if len(body)>60000: raise GhError('Issue description exceeds 60,000 characters.', 'input')
    return payload


def workflow_form(client,repo,number,ref):
    node=client.api(f'repos/{repo}/actions/workflows/{int(number)}')
    content=client.api('repos/'+repo+'/contents/'+path(node['path'])+'?'+urlencode({'ref':ref}))
    schema=yaml_document(decode_content(content))
    events=schema.get('on',schema.get(True,{}))
    if isinstance(events,str): events={events:{}}
    if isinstance(events,list): events={e:{} for e in events}
    if not isinstance(events,dict) or 'workflow_dispatch' not in events:
        return node,None,{}
    dispatch=events.get('workflow_dispatch') or {}; inputs=dispatch.get('inputs') or {}
    fields=[]
    for name,definition in inputs.items():
        definition=definition or {}; kind=definition.get('type','string'); default=definition.get('default','')
        required=bool(definition.get('required')); label=name+(' — '+str(definition['description']) if definition.get('description') else '')
        if kind=='boolean': fields.append(selector(name,label,['false','true'],str(default).lower() if default!='' else 'false'))
        elif kind=='choice': fields.append(dict(key=name,label=label,value=str(default),options=['']+[str(x) for x in definition.get('options',[])],required=required))
        else: fields.append(field(name,label,str(default),required))
    form=choice('dispatch-workflow','Run workflow','Request '+node['name']+' at '+ref+'.',{'workflow':node['id'],'ref':ref,'sha':content['sha']},fields)
    return node,form,inputs


def detail(client,item):
    repo=repository(item['repo']); kind=item['kind']; base='repos/'+repo
    result=detail_base(item,kind.replace('-',' ').title())
    if kind=='templates':
        rows=[]
        try: nodes=client.api(base+'/contents/.github/ISSUE_TEMPLATE')
        except GhError as exc:
            result['warnings'].append('Templates unavailable: '+str(exc)); nodes=[]
        if isinstance(nodes,list):
            rows=[block(n['name'],'',target('template',repo,path=n['path']),operationLabel='Use template') for n in nodes if n['name'].lower().endswith(('.md','.yml','.yaml')) and n['name'] not in ('config.yml','config.yaml')]
        result['tabs']=[dict(id='templates',label='Issue templates',blocks=rows)]
        result['actions']=[choice('create-issue','Blank issue','Create an issue without a template.',{},[field('repo','Repository',repo,True),field('title','Title',required=True),field('body','Description',multiline=True)])]
    elif kind=='template':
        form,schema=template_form(client,repo,item['path'])
        result['title']=schema.get('name') or item['path']; result['body']=str(schema.get('description') or schema.get('about') or '')
        result['actions']=[form]
        for key in ('labels','assignees'):
            if schema.get(key): result['body']+='\n'+key.title()+': '+str(schema[key])
        result['tabs']=[dict(id='templates',label='Form instructions',blocks=[block('Instructions',str(e.get('attributes',{}).get('value') or '')) for e in schema.get('body',[]) if isinstance(e,dict) and e.get('type')=='markdown'])]
    elif kind=='workflow':
        ref=item.get('ref') or client.api(base)['default_branch']
        node,form,inputs=workflow_form(client,repo,item['number'],ref)
        result['title']=node['name']; result['body']=node['path']+'\nBranch/ref: '+ref
        result['actions']=[filter_action(item,[field('ref','Branch or tag',ref,True)])]+([form] if form else [])
        if not form: result['warnings'].append('This workflow does not declare workflow_dispatch at this ref.')
        result['tabs']=[dict(id='workflow',label='Workflow',blocks=[block('Run history','',target('collection',repo,collection='runs',workflow=str(node['id'])),operationLabel='Browse runs')])]
    elif kind=='discussion-replies':
        nodeid=item['comment']; cursor=item.get('cursor')
        data=client.graph('''query($id:ID!,$cursor:String){node(id:$id){... on DiscussionComment{id body discussion{number repository{nameWithOwner}} replies(first:30,after:$cursor){pageInfo{hasNextPage endCursor} nodes{id body createdAt author{login}}}}}}''',{'id':nodeid,'cursor':cursor})['node']
        if not data or data['discussion']['repository']['nameWithOwner'].lower()!=repo.lower(): raise GhError('Discussion comment not found in this repository.', 'input')
        result['body']=data['body']; result['actions']=[choice('discussion-reply','Reply to this comment','Add a nested reply.',{'comment':nodeid,'discussion':data['discussion']['number']},[field('body','Reply',required=True,multiline=True)])]
        rows=[block('@'+(n.get('author') or {}).get('login','ghost'),n['body'],markdown=True) for n in data['replies']['nodes']]
        result['tabs']=[dict(id='conversation',label='Replies',blocks=rows)]
        if data['replies']['pageInfo']['hasNextPage']: result['nextTarget']={**item,'cursor':data['replies']['pageInfo']['endCursor']}
    elif kind=='people':
        # A paginated directory rather than guessed usernames or truncated pickers.
        return client.detail(target('collection',repo,collection=item.get('collection','people'),page=item.get('page',1)))
    return result
