"""Private bare-Git conflict workspace; only explicit publish updates a remote ref."""
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import time
import uuid

from bounded_process import run_bounded, OutputLimitExceeded
from github_client import GhError, atomic_write
from lifecycle import choice, field
from navigation import repository, path
from workspace import block, detail_base, selector, target
import local_state

ACTIONS = {'conflicts-prepare', 'conflicts-save', 'conflicts-discard', 'conflicts-publish'}
KINDS = {'conflicts', 'conflict-file'}
DISK_LIMIT = 256 * 1024 * 1024
TEXT_LIMIT = 60000
SUPPORTED = {'Auto-merging', 'CONFLICT (contents)', 'CONFLICT (add/add)',
             'CONFLICT (modify/delete)', 'CONFLICT (binary)', 'CONFLICT (distinct modes)'}


def oid(value):
    if not isinstance(value, str) or not re.fullmatch('[0-9a-f]{40}', value):
        raise GhError('Invalid Git object identity.', 'input')
    return value


def identity(pr):
    if pr.get('state') != 'open' or pr.get('merged') or not pr.get('head', {}).get('repo'):
        raise GhError('Conflict resolution requires an open PR with an existing source branch.', 'blocked')
    return dict(headSha=oid(pr['head']['sha']), baseSha=oid(pr['base']['sha']),
                headRepo=repository(pr['head']['repo']['full_name']),
                baseRepo=repository(pr['base']['repo']['full_name']),
                headRef=pr['head']['ref'], baseRef=pr['base']['ref'])


def current(client, repo, number, expected=None):
    pr = client.api(f'repos/{repo}/pulls/{number}')
    value = identity(pr)
    if expected is not None and any(value[k] != expected.get(k) for k in value):
        raise GhError('A PR branch changed. Prepare a fresh conflict workspace before publishing.', 'changed')
    return value


def location(account, repo, number):
    key = hashlib.sha256((repo.lower() + '#' + str(number)).encode()).hexdigest()
    return local_state.root(account) / 'conflicts' / key


@contextmanager
def locked(folder):
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(folder, 0o700)
    with (folder / 'lock').open('a') as handle:
        os.chmod(folder / 'lock', 0o600)
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise GhError('Another conflict operation is running. Try again when it finishes.', 'busy') from exc
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


class Git:
    def __init__(self, folder, seconds=180):
        self.folder = Path(folder)
        self.deadline = time.monotonic() + seconds
        self.env = {k: v for k, v in os.environ.items() if not k.startswith('GIT_')}
        self.env.update(GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=os.devnull,
                        GIT_TERMINAL_PROMPT='0', GIT_ASKPASS='/bin/false',
                        GIT_ATTR_NOSYSTEM='1', GIT_NO_REPLACE_OBJECTS='1', LC_ALL='C')

    def guard(self):
        total = 0
        for parent, _, files in os.walk(self.folder):
            for name in files:
                try: total += (Path(parent) / name).stat().st_size
                except FileNotFoundError: continue
                if total > DISK_LIMIT:
                    raise GhError('Conflict workspace exceeds 256 MiB. Use a local Git checkout for this repository.', 'response-limit')

    def run(self, *args, input=None, codes=(0,), limit=4 * 1024 * 1024):
        command = ['git', '--git-dir=' + str(self.folder), '-c', 'core.hooksPath=/dev/null',
                   '-c', 'core.attributesFile=/dev/null', '-c', 'credential.helper=',
                   '-c', 'credential.helper=!gh auth git-credential', '-c', 'protocol.file.allow=never',
                   '-c', 'protocol.ext.allow=never', '-c', 'gc.auto=0', '-c', 'maintenance.auto=false',
                   *args]
        try:
            remaining = self.deadline - time.monotonic()
            if remaining <= 0: raise subprocess.TimeoutExpired(command, 180)
            result = run_bounded(command, timeout=remaining, stdout_limit=limit,
                                 stderr_limit=65536, input=input, env=self.env, guard=self.guard)
        except (subprocess.TimeoutExpired, OutputLimitExceeded) as exc:
            raise GhError('Git exceeded its time or output limit. Your remote branches were not retried; refresh before trying again.', 'timeout') from exc
        except FileNotFoundError as exc:
            raise GhError('Install git and github-cli to resolve conflicts.', 'dependency') from exc
        self.guard()
        if result.returncode not in codes:
            # Git/credential output can contain sensitive URLs; do not echo it.
            raise GhError('Git could not complete this operation. Check repository access, branch rules and network, then refresh. Git 2.38 or newer is required.', 'git')
        return result.stdout, result.returncode

    def blob_text(self, sha):
        size = int(self.run('cat-file', '-s', oid(sha))[0])
        if size > TEXT_LIMIT * 4: return None
        raw = self.run('cat-file', 'blob', sha, limit=TEXT_LIMIT * 4)[0]
        try: result = raw.decode('utf-8')
        except UnicodeDecodeError: return None
        return result if '\0' not in result and len(result) <= TEXT_LIMIT else None


def fetch(git, snapshot, number):
    git.run('init', '--bare', '--template=', str(git.folder))
    git.run('remote', 'add', 'origin', 'https://github.com/' + snapshot['baseRepo'] + '.git')
    git.run('config', 'remote.origin.promisor', 'true')
    git.run('config', 'remote.origin.partialclonefilter', 'blob:none')
    # Fetch full ancestry with blobs on demand, allowing Git to compute ALL merge
    # bases (including criss-cross histories). No checkout, submodules or hooks.
    git.run('fetch', '--quiet', '--no-tags', '--filter=blob:none', 'origin', snapshot['headSha'], snapshot['baseSha'])


def parse_merge(raw, status):
    parts = raw.decode('utf-8').split('\0')
    tree = oid(parts.pop(0)); files = {}
    while parts and parts[0]:
        meta, filename = parts.pop(0).split('\t', 1)
        mode, sha, stage = meta.split()
        if stage not in ('1', '2', '3'): raise GhError('Unknown Git conflict stage.', 'parse')
        files.setdefault(filename, {})[stage] = {'mode': mode, 'sha': oid(sha)}
    if parts: parts.pop(0)
    messages = []; unsupported = []
    while parts and parts[0]:
        count = int(parts.pop(0))
        if count < 0 or count > len(parts) - 2: raise GhError('Invalid Git conflict record.', 'parse')
        del parts[:count]
        kind, message = parts[:2]; del parts[:2]
        messages.append(message.strip())
        if kind not in SUPPORTED: unsupported.append(kind)
    if status == 1 and not files: unsupported.append('Conflict without a per-file resolution')
    if len(files) > 100: unsupported.append('More than 100 conflicted files')
    if any(v['mode'] not in ('100644', '100755') for stages in files.values() for v in stages.values()):
        unsupported.append('Symlink, submodule or file-type conflict')
    return dict(tree=tree, files=files, messages=messages, unsupported=sorted(set(unsupported)))


def read_session(folder, expected=None):
    try: session = json.loads((folder / 'session.json').read_text())
    except FileNotFoundError: raise GhError('Prepare a conflict workspace first.', 'input')
    if expected is not None and (session['session'] != expected.get('session') or session['revision'] != expected.get('revision')):
        raise GhError('The saved resolution changed. Refresh before continuing.', 'changed')
    return session


def prepare(client, repo, number, folder, expected):
    snapshot = current(client, repo, number, expected)
    # Replace only this PR's disposable objects after an explicit Prepare action.
    shutil.rmtree(folder / 'objects.git', ignore_errors=True)
    (folder / 'session.json').unlink(missing_ok=True)
    git = Git(folder / 'objects.git')
    try:
        fetch(git, snapshot, number)
        # Keep the editor's unresolved-marker check aligned with Git even when
        # the repository configures another marker size in .gitattributes.
        (git.folder / 'info').mkdir(exist_ok=True)
        (git.folder / 'info' / 'attributes').write_text('* conflict-marker-size=7\n')
        raw, status = git.run('merge-tree', '--write-tree', '-z', snapshot['headSha'], snapshot['baseSha'], codes=(0, 1))
        session = parse_merge(raw, status)
        session.update(snapshot, session=uuid.uuid4().hex, revision=0, resolutions={})
        current(client, repo, number, snapshot)
        atomic_write(folder / 'session.json', session)
    except Exception:
        shutil.rmtree(folder / 'objects.git', ignore_errors=True)
        raise
    return session


def expectation(session):
    return {k: session[k] for k in ('headSha', 'baseSha', 'headRepo', 'baseRepo', 'headRef', 'baseRef', 'session', 'revision')}


def conflict_target(repo, number, filename=None):
    return target('conflict-file' if filename is not None else 'conflicts', repo, number=number, **({'path': filename} if filename is not None else {}))


def resolved_entry(git, session, filename):
    resolution = session['resolutions'].get(filename)
    if resolution is None: raise GhError('Resolve every file before publishing.', 'blocked')
    if resolution['mode'] == 'edit':
        sha = git.run('hash-object', '-w', '--stdin', input=resolution['body'].encode())[0].decode().strip()
        return {'mode': resolution['fileMode'], 'sha': oid(sha)}
    return session['files'][filename].get('2' if resolution['mode'] == 'source' else '3')


def merged_text(git, session, filename):
    raw = git.run('ls-tree', '-z', session['tree'], '--', filename)[0]
    if not raw: return ''
    meta, found = raw.rstrip(b'\0').split(b'\t', 1)
    if found.decode() != filename: raise GhError('Cannot preview this conflict path.', 'unsupported')
    return git.blob_text(meta.split()[2].decode())


def detail(client, item):
    repo = repository(item['repo']); number = int(item['number'])
    folder = location(client.account, repo, number)
    result = detail_base(item, f'{repo} #{number} · Resolve conflicts')
    snapshot = current(client, repo, number)
    result['body'] = ('Merge ' + snapshot['baseRef'] + ' into ' + snapshot['headRef'] + '. Save each file locally, review the result, then publish to the PR branch.')
    with locked(folder):
        if not (folder / 'session.json').exists():
            result['actions'] = [choice('conflicts-prepare', 'Prepare conflict workspace', 'Fetch Git objects and calculate the merge locally. This does not update GitHub.', snapshot)]
            return result
        session = read_session(folder); exp = expectation(session)
        stale = any(session[k] != snapshot[k] for k in snapshot)
        result['actions'] = [choice('conflicts-prepare', 'Start again', 'Discard saved resolutions and fetch the current PR branches.', snapshot),
                             choice('conflicts-discard', 'Discard workspace', 'Delete this PR’s local Git objects and saved resolutions.', exp)]
        if stale:
            result['warnings'].append('A branch changed. Start again before resolving or publishing.')
            return result
        git = Git(folder / 'objects.git')
        if session['unsupported']:
            result['warnings'].append('This merge needs a local Git checkout: ' + ', '.join(session['unsupported']) + '. Publication is disabled.')
            result['tabs'] = [dict(id='conflicts', label='Conflicts', blocks=[block('Git merge details', '\n'.join(session['messages']))])]
            return result
        if item['kind'] == 'conflict-file':
            filename = item.get('path'); stages = session['files'].get(filename)
            if stages is None: raise GhError('This file is not part of the prepared conflict.', 'input')
            result['title'] = filename
            rows = []
            for stage, label in [('1', 'Common ancestor'), ('2', 'PR source: ' + snapshot['headRef']), ('3', 'Target: ' + snapshot['baseRef'])]:
                entry = stages.get(stage)
                text = git.blob_text(entry['sha']) if entry else '(File absent / deleted)'
                rows.append(block(label, text if text is not None else '(Binary or oversized file; choose a whole-file version.)'))
            saved = session['resolutions'].get(filename)
            candidate = saved['body'] if saved and saved['mode'] == 'edit' else merged_text(git, session, filename)
            if saved and saved['mode'] != 'edit':
                entry = resolved_entry(git, session, filename)
                candidate = git.blob_text(entry['sha']) if entry else ''
            rows.append(block('Saved resolution' if saved else 'Merged result to edit', candidate if candidate is not None else '(Binary or oversized file)'))
            options = ['source', 'target'] + (['edit'] if candidate is not None else [])
            fields = [selector('mode', 'Resolution (source/target replaces the whole file; an absent side deletes it)', options, saved['mode'] if saved else ('edit' if candidate is not None else 'source'))]
            if candidate is not None:
                fields += [dict(field('body', 'Resolved file contents (used only for edit)', candidate, multiline=True), code=True),
                           selector('fileMode', 'Edited file permissions', ['100644', '100755'], saved.get('fileMode') if saved and saved.get('fileMode') else (stages.get('2') or stages.get('3'))['mode'])]
            result['actions'].insert(0, choice('conflicts-save', 'Save resolution', 'Save this file locally. Choose edit to preserve and combine changes; remove all conflict markers.', {**exp, 'path': filename}, fields))
            result['tabs'] = [dict(id='conflict', label='Compare and resolve', blocks=rows)]
        else:
            complete = len(session['resolutions']) == len(session['files'])
            result['body'] += f"\n{len(session['resolutions'])}/{len(session['files'])} files resolved."
            result['tabs'] = [dict(id='conflicts', label='Files', blocks=[block(filename, 'Resolved' if filename in session['resolutions'] else 'Unresolved', conflict_target(repo, number, filename), operationLabel='Compare / resolve') for filename in session['files']])]
            if complete:
                tree = resolution_tree(git, session)
                diff = git.run('diff', '--no-ext-diff', '--no-textconv', '--stat', session['headSha'], tree)[0].decode('utf-8', 'replace')
                result['tabs'].append(dict(id='preview', label='Merge preview', blocks=[block('All changes to the PR branch', diff or 'No file changes.')]))
                try:
                    patch = git.run('diff', '--no-ext-diff', '--no-textconv', '--patch', session['headSha'], tree, limit=1024 * 1024)[0].decode('utf-8', 'replace')
                    result['tabs'][-1]['blocks'].append(block('Resolved merge diff', patch or 'No file changes.'))
                except GhError:
                    result['warnings'].append('Full merge diff unavailable or exceeds 1 MiB. The change summary is shown; inspect a local checkout if needed before publishing.')
            result['actions'].insert(0, choice('conflicts-publish', 'Commit resolved merge', 'Create a two-parent merge commit on the PR source branch. This can trigger CI; the PR stays open.', exp,
                [field('message', 'Merge commit message', 'Merge ' + snapshot['baseRef'] + ' and resolve conflicts', True)], reason='' if complete else 'Resolve every conflicted file first.'))
    return result


def resolution_tree(git, session):
    if session['unsupported']: raise GhError('Unsupported structural conflicts must be resolved in a local Git checkout.', 'unsupported')
    if set(session['resolutions']) != set(session['files']): raise GhError('Resolve every file before publishing.', 'blocked')
    git.run('read-tree', session['tree'])
    entries = []
    for filename in session['files']:
        entry = resolved_entry(git, session, filename)
        entries.append(((entry['mode'] + ' ' + entry['sha']) if entry else '0 ' + '0' * 40) + '\t' + filename + '\0')
    if entries: git.run('update-index', '-z', '--index-info', input=''.join(entries).encode())
    return oid(git.run('write-tree')[0].decode().strip())


def publish(client, repo, number, folder, session, values):
    if client.api('user')['login'] != client.account: raise GhError('The active account changed.', 'auth')
    current(client, repo, number, session)
    git = Git(folder / 'objects.git')
    tree = resolution_tree(git, session)
    message = values.get('message', '')
    if not isinstance(message, str) or not message.strip() or len(message) > 60000:
        raise GhError('Enter a merge commit message.', 'input')
    user = client.api('user')
    git.env.update(GIT_AUTHOR_NAME=user['login'], GIT_COMMITTER_NAME=user['login'],
                   GIT_AUTHOR_EMAIL=f"{int(user['id'])}+{user['login']}@users.noreply.github.com",
                   GIT_COMMITTER_EMAIL=f"{int(user['id'])}+{user['login']}@users.noreply.github.com")
    commit = oid(git.run('commit-tree', tree, '-p', session['headSha'], '-p', session['baseSha'], input=message.encode())[0].decode().strip())
    current(client, repo, number, session)
    # Exact lease makes source update compare-and-swap. Commit construction above
    # always preserves the confirmed source as first parent; no history rewrite.
    ref = 'refs/heads/' + session['headRef']
    git.run('check-ref-format', ref)
    git.run('push', '--porcelain', '--no-verify', '--force-with-lease=' + ref + ':' + session['headSha'],
            'https://github.com/' + session['headRepo'] + '.git', commit + ':' + ref)
    confirmed = client.api('repos/' + session['headRepo'] + '/git/ref/heads/' + path(session['headRef']))
    if confirmed['object']['sha'] != commit:
        raise GhError('The branch moved after publication. Refresh the PR before doing anything else.', 'unconfirmed')
    shutil.rmtree(folder / 'objects.git', ignore_errors=True)
    (folder / 'session.json').unlink(missing_ok=True)
    return commit


def perform(client, req):
    if req.get('confirmed') is not True: raise GhError('Confirm this conflict action first.', 'input')
    item = req['item']; repo = repository(item['repo']); number = int(item['number'])
    if number <= 0: raise GhError('Invalid PR number.', 'input')
    folder = location(client.account, repo, number); expected = req.get('expected') or {}; values = req.get('values') or {}
    action = req['action']
    if action not in ACTIONS: raise GhError('Unknown conflict action.', 'input')
    with locked(folder):
        if action == 'conflicts-prepare':
            prepare(client, repo, number, folder, expected)
        else:
            session = read_session(folder, expected)
            if action == 'conflicts-discard':
                shutil.rmtree(folder / 'objects.git', ignore_errors=True)
                (folder / 'session.json').unlink(missing_ok=True)
            elif action == 'conflicts-publish':
                commit = publish(client, repo, number, folder, session, values)
                return dict(ok=True, message='Resolved merge committed: ' + commit[:12], target=target('pull-request', repo, number=number))
            else:
                current(client, repo, number, session)
                if session['unsupported']: raise GhError('This merge requires a local Git checkout.', 'unsupported')
                filename = expected.get('path'); mode = values.get('mode')
                if filename not in session['files'] or mode not in ('source', 'target', 'edit'):
                    raise GhError('Choose a conflicted file and a resolution.', 'input')
                resolution = {'mode': mode}
                if mode == 'edit':
                    body = values.get('body'); file_mode = values.get('fileMode')
                    if not isinstance(body, str) or len(body) > TEXT_LIMIT or '\0' in body or file_mode not in ('100644', '100755'):
                        raise GhError('Use a UTF-8 text file of at most 60,000 characters and regular file permissions.', 'input')
                    if re.search(r'(?m)^(?:<{7,}|={7,}|>{7,}|\|{7,})(?:\s|$)', body):
                        raise GhError('Remove all conflict markers before saving the resolved file.', 'input')
                    resolution.update(body=body, fileMode=file_mode)
                session['resolutions'][filename] = resolution; session['revision'] += 1
                atomic_write(folder / 'session.json', session)
    return dict(ok=True, message='Local conflict workspace updated.', target=conflict_target(repo, number))
