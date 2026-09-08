"""Action descriptions and explicit GitHub lifecycle operations for the native UI."""
import re
from github_client import GhError

ACTIONS = {'create-issue', 'edit-issue', 'labels', 'assignees', 'close', 'reopen',
           'reviewers', 'ready', 'update-branch', 'auto-merge', 'disable-auto',
           'enqueue', 'dequeue', 'rerun', 'rerun-failed', 'rerun-job', 'cancel-run'}


def field(key, label, value='', required=False, multiline=False):
    return dict(key=key, label=label, value=value, required=required, multiline=multiline)


def choice(id, label, description, expected, fields=None, reason=''):
    return dict(id=id, label=label, description=description, expected=expected,
                fields=fields or [], reason=reason)


def issue_snapshot(node):
    return {key: node.get(key) for key in ('updated_at', 'state', 'title', 'body')} | {
        'labels': sorted(x['name'] for x in node.get('labels', [])),
        'assignees': sorted(x['login'] for x in node.get('assignees', []))}


def issue_actions(node, kind):
    expected = issue_snapshot(node)
    out = []
    if kind == 'issue':
        out.append(choice('edit-issue', 'Edit title and description', 'Save this title and description to GitHub.', expected,
                          [field('title', 'Title', node['title'], True), field('body', 'Description', node.get('body') or '', multiline=True)]))
    out += [choice('labels', 'Manage labels', 'One label per line. This replaces the label list; leave empty to remove all labels.', expected,
                   [field('labels', 'Labels', '\n'.join(expected['labels']), multiline=True)]),
            choice('assignees', 'Manage assignees', 'One GitHub username per line. This replaces the assignee list; leave empty to unassign everyone.', expected,
                   [field('assignees', 'Assignees', '\n'.join(expected['assignees']), multiline=True)])]
    if kind == 'issue':
        closing = node.get('state') == 'open'
        out.append(choice('close' if closing else 'reopen', 'Close issue' if closing else 'Reopen issue',
                          'Mark this issue completed.' if closing else 'Return this issue to open.', expected))
    return out


def queue_info(client, repo, number):
    owner, name = repo.split('/')
    result = client.graph('''query($owner:String!,$name:String!,$number:Int!) {
      repository(owner:$owner,name:$name) { pullRequest(number:$number) {
        id headRefOid baseRefName state isDraft isMergeQueueEnabled
        viewerCanEnableAutoMerge viewerCanDisableAutoMerge
        autoMergeRequest { mergeMethod }
        mergeQueueEntry { position state }
      } }
    }''', {'owner': owner, 'name': name, 'number': number})['repository']['pullRequest']
    if not result:
        raise GhError('PR queue status is unavailable.', 'unavailable')
    return result


def pr_actions(pr, info, queue=None):
    expected = {'headSha': pr['head']['sha'], 'baseRef': pr['base']['ref'],
                'state': pr['state'], 'draft': bool(pr.get('draft')), 'merged': bool(pr.get('merged'))}
    out = []
    if pr.get('merged'):
        return out
    opened = pr['state'] == 'open'
    out.append(choice('close' if opened else 'reopen', 'Close pull request' if opened else 'Reopen pull request',
                      'Close this PR without merging it.' if opened else 'Return this PR to open.', expected))
    if not opened:
        return out
    out.append(choice('reviewers', 'Request reviewers', 'Request review from these users and teams. Existing requests are retained.', expected,
                      [field('reviewers', 'Usernames, one per line', multiline=True),
                       field('teams', 'Team slugs, one per line (within this repository’s organisation)', multiline=True)]))
    if pr.get('draft'):
        out.append(choice('ready', 'Mark ready for review', 'Publish this draft PR for review.', expected))
    out.append(choice('update-branch', 'Update branch', 'Merge the latest target branch into the PR branch. This creates a commit if an update is needed.', expected))
    if queue is not None:
        expected = {**expected, 'autoMerge': queue.get('autoMergeRequest'), 'queueEntry': queue.get('mergeQueueEntry')}
        if queue.get('autoMergeRequest'):
            out.append(choice('disable-auto', 'Disable auto-merge', 'Stop automatic merging for this PR.', expected,
                              reason='' if queue.get('viewerCanDisableAutoMerge') else 'Your account cannot disable auto-merge here.'))
        elif not pr.get('draft'):
            out.append(choice('auto-merge', 'Enable auto-merge', 'Allow GitHub to merge this PR once its requirements are satisfied. Future commits may also be merged under GitHub’s auto-merge rules.', expected,
                              [dict(key='mergeMethod', label='Merge method', value=info['mergeMethods'][0] if info['mergeMethods'] else '', options=info['mergeMethods'], required=True)],
                              reason='' if queue.get('viewerCanEnableAutoMerge') else 'GitHub does not currently allow enabling auto-merge here. Check repository settings and PR requirements.'))
        if queue.get('mergeQueueEntry'):
            out.append(choice('dequeue', 'Leave merge queue', 'Remove this PR from the merge queue.', expected))
        elif queue.get('isMergeQueueEnabled') and not pr.get('draft'):
            out.append(choice('enqueue', 'Join merge queue', 'Queue this PR for GitHub to merge after its queue checks pass. The queue keeps its normal ordering.', expected))
    return out


def run_snapshot(run):
    return {key: run.get(key) for key in ('id', 'head_sha', 'run_attempt', 'status', 'conclusion')}


def run_actions(run, job=None):
    expected = run_snapshot(run)
    out = []
    if run.get('status') == 'completed':
        out.append(choice('rerun', 'Rerun workflow', 'Rerun every job in this workflow at the same commit.', expected))
        if run.get('conclusion') not in ('success', 'neutral', 'skipped'):
            out.append(choice('rerun-failed', 'Rerun failed jobs', 'Rerun failed jobs and their dependent jobs.', expected))
        if job:
            expected = {**expected, 'jobId': job['id']}
            out.append(choice('rerun-job', 'Rerun this job', 'Rerun this job and its dependent jobs.', expected))
    else:
        out.append(choice('cancel-run', 'Cancel workflow', 'Cancel this workflow run and its active jobs.', expected))
    return out


def text(values, key, required=False, maximum=60000):
    value = values.get(key, '')
    if not isinstance(value, str) or len(value) > maximum or (required and not value.strip()):
        raise GhError(f'Enter a valid {key} (at most {maximum} characters).', 'input')
    return value


def names(values, key):
    result = list(dict.fromkeys(line.strip() for line in text(values, key).splitlines() if line.strip()))
    if len(result) > 100 or any(len(x) > 100 for x in result):
        raise GhError('Use at most 100 names, each at most 100 characters.', 'input')
    if key != 'labels' and any(not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]*', x) for x in result):
        raise GhError('Use GitHub usernames or team slugs without @ or organisation prefixes.', 'input')
    return result


def changed():
    raise GhError('This item changed since you opened the action. Refresh and review it again.', 'changed')


def perform(client, request):
    if request.get('confirmed') is not True:
        raise GhError('Review and confirm this action first.', 'input')
    action = request.get('action')
    if action not in ACTIONS:
        raise GhError('Unsupported action.', 'input')
    values = request.get('values') or {}
    expected = request.get('expected') or {}
    if not isinstance(values, dict) or not isinstance(expected, dict):
        raise GhError('Invalid action values.', 'input')
    if action == 'create-issue':
        repo = text(values, 'repo', True, 200)
        client.target({'repo': repo, 'kind': 'ci'})  # Validate without inventing an issue number.
        payload = {'title': text(values, 'title', True, 256), 'body': text(values, 'body')}
        result = client.api(f'repos/{repo}/issues', 'POST', payload)
        if not result.get('number'):
            raise GhError('GitHub did not confirm issue creation. Refresh before retrying.')
        return {'ok': True, 'message': f"Created issue #{result['number']}.",
                'target': {'kind': 'issue', 'repo': repo, 'number': result['number']}}
    target = client.target(request.get('item') or {})
    repo, kind, n = target['repo'], target['kind'], target.get('number')
    base = f'repos/{repo}'
    if action in ('rerun', 'rerun-failed', 'rerun-job', 'cancel-run'):
        if kind not in ('run', 'job') or (action == 'rerun-job' and kind != 'job'):
            raise GhError('Open a workflow run or job first.', 'input')
        job = client.api(f'{base}/actions/jobs/{n}') if kind == 'job' else None
        run_id = job['run_id'] if job else n
        run = client.api(f'{base}/actions/runs/{run_id}')
        snapshot = run_snapshot(run)
        if action == 'rerun-job': snapshot['jobId'] = job['id']
        if snapshot != expected: changed()
        available = [x['id'] for x in run_actions(run, job)]
        if action not in available:
            raise GhError('This workflow action is no longer available.', 'blocked')
        suffix = {'rerun': 'rerun', 'rerun-failed': 'rerun-failed-jobs', 'cancel-run': 'cancel'}
        endpoint = f'{base}/actions/jobs/{n}/rerun' if action == 'rerun-job' else f'{base}/actions/runs/{run_id}/{suffix[action]}'
        client.api(endpoint, 'POST')
        return {'ok': True, 'message': 'Cancellation requested.' if action == 'cancel-run' else 'Rerun requested.'}
    if kind not in ('issue', 'pull-request'):
        raise GhError('This action requires an issue or pull request.', 'input')
    if action in ('edit-issue', 'labels', 'assignees') or (kind == 'issue' and action in ('close', 'reopen')):
        if action == 'edit-issue' and kind != 'issue':
            raise GhError('Open an issue to edit it.', 'input')
        if action == 'edit-issue': payload = {'title': text(values, 'title', True, 256), 'body': text(values, 'body')}
        elif action in ('labels', 'assignees'): payload = {action: names(values, action)}
        else: payload = {'state': 'closed' if action == 'close' else 'open', 'state_reason': 'completed' if action == 'close' else 'reopened'}
        endpoint = f'{base}/issues/{n}'
        current = client.api(endpoint)
        if bool(current.get('pull_request')) != (kind == 'pull-request'):
            raise GhError('Item type changed. Refresh first.', 'changed')
        if issue_snapshot(current) != expected: changed()
        result = client.api(endpoint, 'PATCH', payload)
        for key, value in payload.items():
            actual = result.get(key)
            if key in ('labels', 'assignees'):
                actual = sorted(x['name' if key == 'labels' else 'login'] for x in actual or [])
                value = sorted(value)
            if actual != value:
                raise GhError('GitHub did not apply every requested change. Refresh to inspect the current item before retrying.', 'unconfirmed')
        return {'ok': True, 'message': 'Changes saved.'}
    if kind != 'pull-request':
        raise GhError('This action requires a pull request.', 'input')
    endpoint = f'{base}/pulls/{n}'
    pr = client.api(endpoint)
    info = client.pr_info(pr, base)
    queue = queue_info(client, repo, n) if action in ('auto-merge', 'disable-auto', 'enqueue', 'dequeue') else None
    options = pr_actions(pr, info, queue)
    option = next((x for x in options if x['id'] == action), None)
    if not option:
        raise GhError('This PR action is no longer available.', 'blocked')
    if option['expected'] != expected: changed()
    if option['reason']:
        raise GhError(option['reason'], 'blocked')
    if action in ('close', 'reopen'):
        state = 'closed' if action == 'close' else 'open'
        result = client.api(endpoint, 'PATCH', {'state': state})
        if result.get('state') != state: raise GhError('GitHub did not confirm the state change.')
    elif action == 'reviewers':
        users, teams = names(values, 'reviewers'), names(values, 'teams')
        if not users and not teams: raise GhError('Enter at least one username or team slug.', 'input')
        client.api(endpoint + '/requested_reviewers', 'POST', {'reviewers': users, 'team_reviewers': teams})
    elif action == 'update-branch':
        client.api(endpoint + '/update-branch', 'PUT', {'expected_head_sha': expected['headSha']})
        return {'ok': True, 'message': 'Branch update requested. Refresh shortly for the new commit.'}
    elif action == 'ready':
        result = client.graph('mutation($id:ID!){markPullRequestReadyForReview(input:{pullRequestId:$id}){pullRequest{isDraft}}}', {'id': pr['node_id']})
        if result['markPullRequestReadyForReview']['pullRequest']['isDraft'] is not False:
            raise GhError('GitHub did not confirm ready-for-review status.')
    else:
        # Recheck the GraphQL snapshot too; these writes bind the confirmed head at the API.
        if queue['headRefOid'] != expected['headSha'] or queue['baseRefName'] != expected['baseRef']:
            changed()
        inputs = {'pullRequestId': queue['id']}
        if action == 'auto-merge':
            method = values.get('mergeMethod')
            if method not in info['mergeMethods']: raise GhError('Choose an enabled merge method.', 'input')
            inputs.update(mergeMethod=method.upper(), expectedHeadOid=expected['headSha'])
        elif action == 'enqueue': inputs['expectedHeadOid'] = expected['headSha']
        mutation, input_type, selection = {
            'auto-merge': ('enablePullRequestAutoMerge', 'EnablePullRequestAutoMergeInput', 'pullRequest{autoMergeRequest{mergeMethod}}'),
            'disable-auto': ('disablePullRequestAutoMerge', 'DisablePullRequestAutoMergeInput', 'pullRequest{autoMergeRequest{mergeMethod}}'),
            'enqueue': ('enqueuePullRequest', 'EnqueuePullRequestInput', 'mergeQueueEntry{position state}'),
            'dequeue': ('dequeuePullRequest', 'DequeuePullRequestInput', 'pullRequest{isInMergeQueue}')
        }[action]
        result = client.graph(f'mutation($input:{input_type}!){{{mutation}(input:$input){{{selection}}}}}', {'input': inputs})[mutation]
        valid = bool(result)
        if action == 'auto-merge': valid = bool(result.get('pullRequest', {}).get('autoMergeRequest'))
        elif action == 'disable-auto': valid = 'pullRequest' in result and result['pullRequest']['autoMergeRequest'] is None
        elif action == 'enqueue': valid = bool(result.get('mergeQueueEntry'))
        elif action == 'dequeue': valid = result.get('pullRequest', {}).get('isInMergeQueue') is False
        if not valid: raise GhError('GitHub did not confirm this action. Refresh before retrying.')
    return {'ok': True, 'message': option['label'] + ' — done.'}
