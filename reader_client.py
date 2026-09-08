#!/usr/bin/python3
"""Native GitHub reader and explicit user actions. Requests arrive as JSON on stdin."""
from __future__ import annotations
import json
import re
import subprocess
import sys
from urllib.parse import urlparse
from github_client import GhError
import lifecycle
import review_threads

LIMIT = 4 * 1024 * 1024
REPO = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+\Z")


def transport(args, payload=None):
    command = ['gh', *args]
    try:
        result = subprocess.run(command, input=json.dumps(payload).encode() if payload is not None else None,
                                capture_output=True, timeout=40)
    except subprocess.TimeoutExpired as exc:
        raise GhError('GitHub timed out. Refresh to try again.', 'timeout') from exc
    except FileNotFoundError as exc:
        raise GhError('GitHub CLI is not installed.', 'missing-gh') from exc
    if result.returncode:
        raise GhError(result.stderr.decode('utf-8', 'replace')[:600].strip() or 'GitHub request failed.')
    if len(result.stdout) > LIMIT:
        raise GhError('This response is too large to load safely. Try a smaller thread or job.', 'response-limit')
    return result.stdout.decode('utf-8', 'replace')


class Client:
    def __init__(self, runner=transport):
        self.runner = runner

    def api(self, endpoint, method='GET', payload=None):
        args = ['api', '--hostname', 'github.com', '-X', method, endpoint]
        if payload is not None:
            args += ['--input', '-']
        raw = self.runner(args, payload)
        data = json.loads(raw) if raw.strip() else {}
        if isinstance(data, dict) and data.get('errors'):
            raise GhError('; '.join(e.get('message', 'GraphQL error') for e in data['errors']))
        return data

    def graph(self, query, variables):
        return self.api('graphql', 'POST', {'query': query, 'variables': variables})['data']

    def target(self, item):
        repo = str(item.get('repo', ''))
        if not REPO.fullmatch(repo) or any(p in ('.', '..') for p in repo.split('/')):
            raise GhError('Invalid repository.', 'input')
        kind = item.get('kind')
        number = item.get('number', 0)
        if kind == 'notification':
            raw = str(item.get('subjectUrl') or item.get('url') or '')
            if item.get('subjectType') == 'CheckSuite' and not item.get('subjectUrl'):
                return {'repo': repo, 'kind': 'ci', 'sha': '', 'notificationFallback': True}
            u = urlparse(raw)
            if u.scheme != 'https' or u.netloc not in ('api.github.com', 'github.com') or u.query:
                raise GhError('This notification has no supported GitHub subject.', 'unsupported')
            path = u.path.removeprefix('/repos/').lstrip('/') if u.netloc == 'api.github.com' else u.path.lstrip('/')
            parts = path.split('/')
            if len(parts) != 4 or '/'.join(parts[:2]) != repo:
                raise GhError('This notification type does not expose a readable thread.', 'unsupported')
            kind = {'issues': 'issue', 'pulls': 'pull-request', 'pull': 'pull-request', 'discussions': 'discussion',
                    'commits': 'commit', 'commit': 'commit', 'releases': 'release', 'check-suites': 'check-suite'}.get(parts[2])
            number = parts[3]
        if kind == 'ci':
            sha = str(item.get('sha', ''))
            if sha and not re.fullmatch(r'[0-9a-fA-F]{7,40}', sha):
                raise GhError('Invalid commit.', 'input')
            return {'repo': repo, 'kind': kind, 'sha': sha}
        if kind == 'commit':
            if not re.fullmatch(r'[0-9a-fA-F]{7,40}', str(number)):
                raise GhError('Invalid commit.', 'input')
        elif kind in ('issue', 'pull-request', 'discussion', 'release', 'check-suite', 'run', 'job'):
            if not re.fullmatch(r'[1-9][0-9]{0,19}', str(number)):
                raise GhError('Invalid item number.', 'input')
            number = int(number)
        else:
            raise GhError('This GitHub item type is not supported in the reader yet.', 'unsupported')
        return {'repo': repo, 'kind': kind, 'number': number}

    def detail(self, item, page=1, cursor=None):
        t = self.target(item)
        repo, kind = t['repo'], t['kind']
        base = f'repos/{repo}'
        n = t.get('number')
        result = {'ok': True, 'target': t, 'title': item.get('title', repo), 'subtitle': repo,
                  'body': '', 'tabs': [], 'actions': [], 'canReply': False, 'warnings': [], 'nextPage': None, 'nextCursor': None}
        if kind in ('issue', 'pull-request'):
            # Issues API also resolves a PR notification delivered as an Issue.
            node = self.api(f'{base}/issues/{n}')
            if node.get('pull_request'):
                kind = t['kind'] = 'pull-request'
            result.update(title=node['title'], body=node.get('body') or '',
                          subtitle=f"{repo} #{n} · {node.get('state', '').upper()} · @{(node.get('user') or {}).get('login', 'ghost')}",
                          canReply=not node.get('locked', False))
            result['actions'] = lifecycle.issue_actions(node, kind)
            result['metadata'] = 'Labels: ' + (', '.join(x['name'] for x in node.get('labels', [])) or 'none') + '\nAssignees: ' + (', '.join(x['login'] for x in node.get('assignees', [])) or 'none')
            comments = self.api(f'{base}/issues/{n}/comments?per_page=30&page={page}')
            result['tabs'].append(tab('conversation', 'Conversation', [comment(c) for c in comments]))
            if page * 30 < node.get('comments', 0):
                result['nextPage'] = page + 1
            if kind == 'pull-request':
                self.optional(result, lambda: self.pr_context(base, n, result))
        elif kind == 'discussion':
            owner, name = repo.split('/')
            data = self.graph('''query($owner:String!,$name:String!,$n:Int!,$cursor:String) {
              repository(owner:$owner,name:$name) { discussion(number:$n) {
                id title body closed locked author { login }
                comments(first:30,after:$cursor) { pageInfo { hasNextPage endCursor }
                  nodes { author { login } body createdAt replies(first:30) {
                    totalCount nodes { author { login } body createdAt } } } }
              } } }''', {'owner':owner, 'name':name, 'n':n, 'cursor':cursor})
            node = (data.get('repository') or {}).get('discussion')
            if not node:
                raise GhError('Discussion not found or not accessible.')
            result.update(title=node['title'], body=node.get('body') or '', canReply=not node.get('locked'), discussionId=node['id'])
            blocks = []
            for c in node['comments']['nodes']:
                blocks.append(comment(c))
                replies = c['replies']
                blocks.extend(comment(r, '↳ ') for r in replies['nodes'])
                if replies['totalCount'] > len(replies['nodes']):
                    result['warnings'].append('A discussion comment has more than 30 replies; only its first 30 are shown.')
            result['tabs'].append(tab('conversation', 'Conversation', blocks))
            info = node['comments']['pageInfo']
            if info['hasNextPage']:
                result['nextCursor'] = info['endCursor']
        elif kind in ('ci', 'check-suite'):
            suffix = f'check_suite_id={n}' if kind == 'check-suite' else ('head_sha=' + t['sha'] if t['sha'] else '')
            runs = self.api(f'{base}/actions/runs?per_page=20&{suffix}')
            result['body'] = 'Select a workflow run to inspect its jobs, steps and logs.'
            if t.get('notificationFallback'):
                result['warnings'].append('GitHub does not include a run ID with this notification. Showing recent repository runs; match the workflow and time below.')
            blocks = [block(r.get('name') or r.get('display_title', 'Workflow'),
                      f"{r.get('conclusion') or r.get('status')} · {r.get('head_branch')} · {r.get('created_at')}",
                      {'kind':'run','repo':repo,'number':r['id']}) for r in runs.get('workflow_runs', [])]
            result['tabs'].append(tab('checks', 'Workflow runs', blocks))
            if runs.get('total_count', 0) > 20:
                result['warnings'].append('Showing the 20 most recent workflow runs for this signal.')
            if kind == 'ci' and t['sha']:
                self.optional(result, lambda: self.checks(base, t['sha'], result))
        elif kind == 'run':
            run = self.api(f'{base}/actions/runs/{n}')
            result['actions'] = lifecycle.run_actions(run)
            jobs = self.api(f'{base}/actions/runs/{n}/jobs?per_page=100')
            result.update(title=run.get('display_title') or run.get('name', 'Workflow'), body=f"{run.get('conclusion') or run.get('status')} · {run.get('head_branch')}\n{run.get('head_sha')}")
            blocks = []
            for job in jobs.get('jobs', []):
                steps = '\n'.join(f"{s.get('conclusion') or s.get('status')}: {s.get('name')}" for s in job.get('steps', []))
                action = {'kind':'job','repo':repo,'number':job['id']} if job.get('status') == 'completed' else None
                blocks.append(block(job['name'], f"{job.get('conclusion') or job.get('status')}\n\n{steps}", action))
            result['tabs'].append(tab('checks', 'Jobs & steps', blocks))
            if jobs.get('total_count',0) > 100:
                result['warnings'].append('Showing the first 100 jobs.')
        elif kind == 'job':
            job = self.api(f'{base}/actions/jobs/{n}')
            run = self.api(f"{base}/actions/runs/{job['run_id']}")
            result['actions'] = lifecycle.run_actions(run, job)
            log = self.runner(['run','view','--repo',f'github.com/{repo}','--job',str(n),'--log'], None)
            # ANSI sequences are not useful in a native text reader.
            log = re.sub(r'\x1b\[[0-?]*[ -/]*[@-~]', '', log)
            result.update(title=f'Job {n} logs', body='Latest available job output.')
            if len(log) > 180000:
                result['warnings'].append('Showing the final 180,000 characters of this log.')
            result['tabs'].append(tab('logs', 'Logs', [block('Output', log[-180000:])]))
        elif kind == 'release':
            node = self.api(f'{base}/releases/{n}')
            result.update(title=node.get('name') or node.get('tag_name'), body=node.get('body') or '')
            result['tabs'].append(tab('release', 'Release', [block('Assets', '\n'.join(a['name'] for a in node.get('assets',[])) or 'No release assets.')]))
        elif kind == 'commit':
            node = self.api(f'{base}/commits/{n}')
            result.update(title=node['commit']['message'].split('\n')[0], body=node['commit']['message'])
            result['tabs'].append(tab('changes', 'Changes', file_blocks(node.get('files',[]))))
            self.optional(result, lambda: self.checks(base, n, result))
        if result.get('metadata'):
            result['tabs'].append(tab('metadata', 'Details', [block('People & status', result['metadata'])]))
        thread = str(item.get('id', ''))
        result['threadId'] = thread.split(':')[1] if re.fullmatch(r'notification:[0-9]+', thread) else ''
        return result

    def optional(self, result, fn):
        try:
            fn()
        except GhError as exc:
            result['warnings'].append(str(exc))

    def pr_context(self, base, n, result):
        pr = self.api(f'{base}/pulls/{n}')
        result['subtitle'] += f" · {pr['head']['ref']} → {pr['base']['ref']}"
        self.optional(result, lambda: result.update(pr=self.pr_info(pr, base)))
        info = result.get('pr') or {'mergeMethods': []}
        queue = {}
        self.optional(result, lambda: queue.update(lifecycle.queue_info(self, result['target']['repo'], n)))
        result['actions'] += lifecycle.pr_actions(pr, info, queue if queue else None)
        result['metadata'] += '\nRequested reviewers: ' + (', '.join(x['login'] for x in pr.get('requested_reviewers', [])) or 'none')
        result['metadata'] += '\nRequested teams: ' + (', '.join(x['slug'] for x in pr.get('requested_teams', [])) or 'none')
        if queue:
            entry = queue.get('mergeQueueEntry')
            auto = queue.get('autoMergeRequest')
            result['metadata'] += '\nAuto-merge: ' + (auto['mergeMethod'].lower() if auto else 'off')
            result['metadata'] += '\nMerge queue: ' + (f"#{entry['position']} · {entry['state']}" if entry else ('not queued' if queue.get('isMergeQueueEnabled') else 'not enabled'))
            result['lifecycleStatus'] = 'Auto-merge: ' + (auto['mergeMethod'].lower() if auto else 'off') + ' · Queue: ' + (f"#{entry['position']} {entry['state']}" if entry else ('not queued' if queue.get('isMergeQueueEnabled') else 'not enabled'))
            if result.get('pr') and queue.get('isMergeQueueEnabled'):
                result['pr']['canMerge'] = False
                result['pr']['mergeReason'] = 'This branch uses a merge queue. Use Join merge queue or Enable auto-merge in Actions.'
        reviews = self.api(f'{base}/pulls/{n}/reviews?per_page=100')
        inline = self.api(f'{base}/pulls/{n}/comments?per_page=100')
        result['tabs'].append(tab('reviews', 'Reviews',
            [block(f"@{(r.get('user') or {}).get('login', 'ghost')} · {r.get('state')}", r.get('body') or '(No review text)') for r in reviews] +
            [block(f"@{(r.get('user') or {}).get('login', 'ghost')} · {r.get('path')}:{r.get('line') or r.get('original_line')}", (r.get('diff_hunk') or '') + '\n\n' + (r.get('body') or '')) for r in inline]))
        if len(reviews) == 100 or len(inline) == 100:
            result['warnings'].append('Reviews are limited to the first 100 reviews and 100 inline comments.')
        files = self.api(f'{base}/pulls/{n}/files?per_page=100')
        result['tabs'].append(tab('changes', 'Changes', review_threads.file_blocks(files, pr)))
        def threads():
            thread_tab, warnings = review_threads.load_threads(self, result['target']['repo'], n, pr)
            result['tabs'].append(thread_tab)
            result['warnings'].extend(warnings)
        self.optional(result, threads)
        if pr.get('changed_files',0) > len(files):
            result['warnings'].append(f"Showing {len(files)} of {pr['changed_files']} changed files.")
        self.checks(base, pr['head']['sha'], result)

    def checks(self, base, sha, result):
        checks = self.api(f'{base}/commits/{sha}/check-runs?per_page=100')
        statuses = self.api(f'{base}/commits/{sha}/status?per_page=100')
        blocks = [block(c['name'], f"{c.get('conclusion') or c.get('status')}\n\n" +
                    '\n'.join(str((c.get('output') or {}).get(k) or '') for k in ('title','summary','text'))) for c in checks.get('check_runs',[])]
        blocks += [block(c['context'], f"{c['state']}\n{c.get('description') or ''}") for c in statuses.get('statuses',[])]
        result['tabs'].append(tab('status', 'Checks', blocks))
        states = [c.get('conclusion') or c.get('status') for c in checks.get('check_runs', [])]
        states += [c.get('state') for c in statuses.get('statuses', [])]
        passed = sum(s in ('success', 'neutral', 'skipped') for s in states)
        failed = sum(s in ('failure', 'error', 'timed_out', 'cancelled', 'action_required', 'startup_failure') for s in states)
        pending = len(states) - passed - failed
        summary = f'{passed} passed · {failed} failed · {pending} pending' if states else 'No checks reported'
        if result.get('pr'):
            result['pr']['checkSummary'] = summary
        if checks.get('total_count',0) > 100 or statuses.get('total_count',0) > 100:
            result['warnings'].append('Check details are limited to 100 checks and 100 statuses.')

    def pr_info(self, pr, base):
        repository = self.api(base)
        viewer = self.api('user')
        return pr_info(pr, repository, viewer)

    def pr_action(self, request):
        action = request.get('action')
        if request.get('confirmed') is not True:
            raise GhError('Confirm this pull request action first.', 'input')
        target = self.target(request.get('item') or {})
        if target['kind'] != 'pull-request':
            raise GhError('This action requires a pull request.', 'input')
        sha = str(request.get('expectedHeadSha', ''))
        branch = str(request.get('expectedBase', ''))
        if not re.fullmatch(r'[0-9a-fA-F]{40}', sha) or not branch:
            raise GhError('Refresh the pull request before taking this action.', 'input')
        body = str(request.get('body', ''))
        if len(body) > 60000 or (action == 'request-changes' and not body.strip()):
            raise GhError('Request changes needs a review note. Notes may contain at most 60,000 characters.', 'input')
        method = request.get('mergeMethod')
        if action == 'merge' and method not in ('merge', 'squash', 'rebase'):
            raise GhError('Select a supported merge method.', 'input')
        base = f"repos/{target['repo']}"
        endpoint = f"{base}/pulls/{target['number']}"
        pr = self.api(endpoint)
        if (pr.get('head') or {}).get('sha') != sha or (pr.get('base') or {}).get('ref') != branch:
            raise GhError('The PR changed since you opened it. Refresh and review the new commit or target branch.', 'changed')
        info = self.pr_info(pr, base)
        if action == 'merge':
            if not info['canMerge']:
                raise GhError(info['mergeReason'], 'blocked')
            if method not in info['mergeMethods']:
                raise GhError('That merge method is no longer enabled for this repository.', 'changed')
            result = self.api(endpoint + '/merge', 'PUT', {'sha': sha, 'merge_method': method})
            if result.get('merged') is not True:
                raise GhError(result.get('message') or 'GitHub did not merge the pull request.', 'blocked')
            return {'ok': True, 'message': 'Pull request merged.', 'merged': True, 'sha': result.get('sha', '')}
        if not info['canReview']:
            raise GhError(info['reviewReason'], 'blocked')
        event = {'approve': 'APPROVE', 'request-changes': 'REQUEST_CHANGES'}[action]
        result = self.api(endpoint + '/reviews', 'POST', {'event': event, 'commit_id': sha, 'body': body})
        expected = 'APPROVED' if action == 'approve' else 'CHANGES_REQUESTED'
        if result.get('state') != expected:
            raise GhError('GitHub did not confirm the review. Refresh before retrying.', 'unconfirmed')
        return {'ok': True, 'message': 'Pull request approved.' if action == 'approve' else 'Changes requested.'}

    def action(self, request):
        # Building these controls does not perform any mutation; only an explicit UI submit calls here.
        action = request.get('action')
        item = request.get('item') or {}
        if action in review_threads.ACTIONS:
            return review_threads.perform(self, request)
        if action in lifecycle.ACTIONS:
            return lifecycle.perform(self, request)
        if action in ('approve', 'request-changes', 'merge'):
            return self.pr_action(request)
        if action == 'mark-read':
            thread = str(item.get('id',''))
            if not re.fullmatch(r'notification:[0-9]+', thread):
                raise GhError('Invalid notification.', 'input')
            self.api('notifications/threads/' + thread.split(':')[1], 'PATCH')
            return {'ok':True,'message':'Marked as read.'}
        if action != 'reply':
            raise GhError('Unsupported action.', 'input')
        body = str(request.get('body',''))
        if not body.strip() or len(body) > 60000:
            raise GhError('Enter a reply between 1 and 60,000 characters.', 'input')
        t = self.target(item)
        if t['kind'] in ('issue','pull-request'):
            self.api(f"repos/{t['repo']}/issues/{t['number']}/comments", 'POST', {'body':body})
        elif t['kind'] == 'discussion':
            owner, name = t['repo'].split('/')
            node = self.graph('query($o:String!,$r:String!,$n:Int!){repository(owner:$o,name:$r){discussion(number:$n){id}}}',
                              {'o':owner,'r':name,'n':t['number']})['repository']['discussion']
            self.graph('mutation($id:ID!,$body:String!){addDiscussionComment(input:{discussionId:$id,body:$body}){comment{id}}}', {'id':node['id'],'body':body})
        else:
            raise GhError('Replies are not supported for this item.', 'unsupported')
        return {'ok':True,'message':'Reply posted.'}


def pr_info(pr, repository, viewer):
    permissions = repository.get('permissions') or {}
    can_write = any(permissions.get(p) is True for p in ('push', 'maintain', 'admin'))
    methods = [method for method, flag in [('squash', 'allow_squash_merge'), ('merge', 'allow_merge_commit'), ('rebase', 'allow_rebase_merge')] if repository.get(flag) is True]
    opened = pr.get('state') == 'open' and not pr.get('merged')
    draft = pr.get('draft') is True
    own = str((pr.get('user') or {}).get('login', '')).lower() == str(viewer.get('login', '')).lower()
    review_reason = ''
    if not opened: review_reason = 'This pull request is already closed or merged.'
    elif own: review_reason = 'GitHub does not allow approving or requesting changes on your own PR.'
    elif draft: review_reason = 'This pull request is still a draft.'
    merge_reason = ''
    state = str(pr.get('mergeable_state') or 'unknown')
    if not opened: merge_reason = 'This pull request is already closed or merged.'
    elif draft: merge_reason = 'This pull request is still a draft.'
    elif not can_write: merge_reason = 'Your GitHub account does not have merge permission in this repository.'
    elif not methods: merge_reason = 'This repository has no enabled merge methods.'
    elif pr.get('mergeable') is None: merge_reason = 'GitHub is calculating merge readiness. Refresh in a moment.'
    elif pr.get('mergeable') is False: merge_reason = 'This pull request has merge conflicts.'
    elif state in ('blocked', 'behind', 'dirty', 'unknown'): merge_reason = 'GitHub reports this PR as ' + state + '. Resolve its requirements or merge-queue rules before merging.'
    return {'headSha': (pr.get('head') or {}).get('sha', ''),
            'headRef': (pr.get('head') or {}).get('label') or (pr.get('head') or {}).get('ref', ''),
            'baseRef': (pr.get('base') or {}).get('ref', ''),
            'state': 'merged' if pr.get('merged') else pr.get('state', ''),
            'draft': draft, 'mergeState': state, 'mergeMethods': methods,
            'canReview': not review_reason, 'reviewReason': review_reason,
            'canMerge': not merge_reason, 'mergeReason': merge_reason}


def block(title, body, action=None):
    return {'title': str(title or ''), 'body': str(body or ''), 'action': action}


def tab(id, label, blocks):
    return {'id':id, 'label':label, 'blocks':blocks}


def comment(c, prefix=''):
    author = (c.get('user') or c.get('author') or {}).get('login','ghost')
    return block(f"{prefix}@{author} · {c.get('created_at') or c.get('createdAt') or ''}", c.get('body') or '')


def file_blocks(files):
    return [block(f"{f['filename']} · +{f.get('additions',0)} −{f.get('deletions',0)}", f.get('patch') or 'Patch unavailable (binary, too large, or unchanged content).') for f in files]


def main():
    try:
        raw = sys.stdin.readline(300000)
        req = json.loads(raw)
        client = Client()
        if req.get('op') == 'detail':
            page = req.get('page',1)
            if not isinstance(page,int) or isinstance(page,bool) or not 1 <= page <= 1000:
                raise GhError('Invalid comment page.', 'input')
            result = client.detail(req['item'], page, req.get('cursor'))
        elif req.get('op') == 'action':
            result = client.action(req)
        else:
            raise GhError('Invalid request.', 'input')
    except (GhError, ValueError, KeyError, TypeError) as exc:
        result = {'ok':False, 'error':str(exc), 'errorKind':getattr(exc,'kind','parse')}
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
