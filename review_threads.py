"""Inline diff comments and explicitly confirmed review-thread state changes."""
import hashlib
import json
import re
from github_client import GhError
from lifecycle import choice, field, text, changed

ACTIONS = {'inline-comment', 'resolve-thread', 'reopen-thread'}
THREAD_FIELDS = '''id path line originalLine diffSide isResolved isOutdated viewerCanResolve viewerCanUnresolve
  comments(first:100) { totalCount nodes { id body updatedAt author { login } diffHunk } }'''


def diff_lines(patch):
    """Return selectable API locations and a numbered unified diff."""
    locations, rendered = [], []
    old = new = old_left = new_left = 0
    for line in (patch or '').splitlines():
        hunk = re.match(r'^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@', line)
        if hunk:
            old, old_left, new, new_left = [int(x) if x is not None else 1 for x in hunk.groups()]
            rendered.append(line)
        elif line.startswith('-') and old_left > 0:
            locations.append(f'Old line {old}')
            rendered.append(f'L{old:>5}        {line}'); old += 1; old_left -= 1
        elif line.startswith('+') and new_left > 0:
            locations.append(f'New line {new}')
            rendered.append(f'       R{new:>5} {line}'); new += 1; new_left -= 1
        elif line.startswith(' ') and old_left > 0 and new_left > 0:
            locations.extend([f'New line {new}', f'Old line {old}'])
            rendered.append(f'L{old:>5} R{new:>5} {line}'); old += 1; new += 1; old_left -= 1; new_left -= 1
        else:
            rendered.append(line)
    return list(dict.fromkeys(locations)), '\n'.join(rendered)


def file_blocks(files, pr):
    blocks = []
    for file in files:
        locations, patch = diff_lines(file.get('patch'))
        expected = {'headSha':pr['head']['sha'], 'baseRef':pr['base']['ref'], 'path':file['filename']}
        operations = []
        if locations and pr.get('state') == 'open':
            operations.append(choice('inline-comment', 'Comment on a diff line',
                'Post an inline review comment on ' + file['filename'] + '. New lines are on the right side; old lines are on the left.', expected,
                [dict(key='location',label='Diff line',value=locations[0],options=locations,required=True),
                 field('body','Comment',required=True,multiline=True)]))
        blocks.append({'title':f"{file['filename']} · +{file.get('additions',0)} −{file.get('deletions',0)}",
                       'body':patch or 'Patch unavailable (binary or too large).', 'action':None,
                       'operations':operations, 'operationLabel':'Comment on line…'})
    return blocks


def stamp(thread):
    comments = thread['comments']
    payload = [comments['totalCount'], [(x['id'],x['updatedAt']) for x in comments['nodes']]]
    return {'threadId':thread['id'], 'resolved':thread['isResolved'],
            'commentsHash':hashlib.sha256(json.dumps(payload).encode()).hexdigest()}


def load_threads(client, repo, number, pr):
    owner, name = repo.split('/')
    result = client.graph('''query($owner:String!,$name:String!,$number:Int!){repository(owner:$owner,name:$name){
      pullRequest(number:$number){reviewThreads(first:100){pageInfo{hasNextPage} nodes{''' + THREAD_FIELDS + '}}}}}',
      {'owner':owner,'name':name,'number':number})
    node = (result.get('repository') or {}).get('pullRequest')
    if not node: raise GhError('Review threads are unavailable.')
    threads = node['reviewThreads']
    warnings = ['Showing the first 100 review threads.'] if threads['pageInfo']['hasNextPage'] else []
    blocks = []
    for thread in threads['nodes']:
        comments = thread['comments']['nodes']
        expected = {**stamp(thread), 'headSha':pr['head']['sha'], 'baseRef':pr['base']['ref']}
        resolved = thread['isResolved']
        permitted = thread['viewerCanUnresolve'] if resolved else thread['viewerCanResolve']
        label = 'Reopen review thread' if resolved else 'Resolve review thread'
        operation = choice('reopen-thread' if resolved else 'resolve-thread', label,
                           label + ' at ' + thread['path'] + ':' + str(thread['line'] or thread['originalLine'] or '?') + '.', expected,
                           reason='' if permitted else 'Your GitHub account cannot change this thread’s resolution.')
        body = (comments[0].get('diffHunk') or '') if comments else ''
        body += '\n\n' + '\n\n'.join('@' + (c.get('author') or {}).get('login','ghost') + '\n' + c['body'] for c in comments)
        if thread['comments']['totalCount'] > len(comments):
            body += '\n\nOnly the first 100 comments are shown. Load the remaining conversation before resolving.'
            operation['reason'] = 'This thread exceeds the reader’s 100-comment limit; resolution is disabled to avoid resolving unread comments.'
        blocks.append({'title':('RESOLVED' if resolved else 'UNRESOLVED') + (' · OUTDATED' if thread['isOutdated'] else '') +
                       f" · {thread['path']}:{thread['line'] or thread['originalLine'] or '?'} · {thread['diffSide']}",
                       'body':body, 'action':None, 'operations':[operation], 'operationLabel':'Thread actions…'})
    return {'id':'threads','label':'Threads','blocks':blocks}, warnings


def perform(client, request):
    if request.get('confirmed') is not True: raise GhError('Review and confirm this action first.', 'input')
    action = request.get('action')
    if action not in ACTIONS: raise GhError('Unsupported review action.', 'input')
    target = client.target(request.get('item') or {})
    expected, values = request.get('expected') or {}, request.get('values') or {}
    if target['kind'] != 'pull-request' or not isinstance(expected,dict) or not isinstance(values,dict):
        raise GhError('Open a pull request first.', 'input')
    if not re.fullmatch(r'[a-fA-F0-9]{40}',str(expected.get('headSha',''))) or not expected.get('baseRef'):
        raise GhError('Refresh the PR before reviewing.', 'input')
    if action == 'inline-comment':
        body = text(values,'body',True)
        location = text(values,'location',True,50)
        match = re.fullmatch(r'(New|Old) line ([1-9][0-9]*)',location)
        if not match or not isinstance(expected.get('path'),str): raise GhError('Choose a valid diff line.', 'input')
    repo, number = target['repo'], target['number']
    endpoint = f'repos/{repo}/pulls/{number}'
    pr = client.api(endpoint)
    if pr['head']['sha'] != expected['headSha'] or pr['base']['ref'] != expected['baseRef']: changed()
    if action == 'inline-comment':
        if pr['state'] != 'open': raise GhError('This PR is no longer open.', 'blocked')
        files = client.api(endpoint + '/files?per_page=100')
        file = next((f for f in files if f['filename'] == expected['path']), None)
        if not file or location not in diff_lines(file.get('patch'))[0]: changed()
        payload = {'body':body,'commit_id':expected['headSha'],'path':file['filename'],
                   'line':int(match[2]),'side':'RIGHT' if match[1]=='New' else 'LEFT'}
        result = client.api(endpoint + '/comments','POST',payload)
        if not result.get('id') or result.get('commit_id') != expected['headSha']:
            raise GhError('GitHub did not confirm the inline comment. Refresh before retrying.')
        return {'ok':True,'message':'Inline comment posted.'}
    thread_id = expected.get('threadId')
    if not isinstance(thread_id,str) or not re.fullmatch(r'[A-Za-z0-9_=-]{1,200}',thread_id):
        raise GhError('Invalid review thread.', 'input')
    thread = client.graph('query($id:ID!){node(id:$id){... on PullRequestReviewThread{' + THREAD_FIELDS +
        ' pullRequest{number headRefOid baseRefName repository{nameWithOwner}}}}}', {'id':thread_id}).get('node')
    if not thread: raise GhError('The review thread is no longer available.', 'changed')
    owner = thread['pullRequest']
    if owner['number'] != number or owner['repository']['nameWithOwner'].lower() != repo.lower():
        raise GhError('This review thread belongs to a different PR.', 'input')
    if owner['headRefOid'] != expected['headSha'] or owner['baseRefName'] != expected['baseRef']: changed()
    if any(expected.get(key) != value for key,value in stamp(thread).items()): changed()
    resolving = action == 'resolve-thread'
    if thread['isResolved'] == resolving: changed()
    if not thread['viewerCanResolve' if resolving else 'viewerCanUnresolve']:
        raise GhError('Your GitHub account cannot change this thread’s resolution.', 'blocked')
    if thread['comments']['totalCount'] > len(thread['comments']['nodes']):
        raise GhError('The full thread is not loaded; resolution is disabled.', 'blocked')
    mutation = 'resolveReviewThread' if resolving else 'unresolveReviewThread'
    result = client.graph(f'mutation($id:ID!){{{mutation}(input:{{threadId:$id}}){{thread{{id isResolved}}}}}}', {'id':thread_id})
    updated = (result.get(mutation) or {}).get('thread') or {}
    if updated.get('id') != thread_id or updated.get('isResolved') is not resolving:
        raise GhError('GitHub did not confirm the thread change. Refresh before retrying.')
    return {'ok':True,'message':'Review thread resolved.' if resolving else 'Review thread reopened.'}
