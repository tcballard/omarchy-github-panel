"""Validate typed navigation; never execute or open arbitrary schemes."""
import re
from urllib.parse import urlparse, unquote, quote
from github_client import GhError


def repository(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', value) or any(x in ('.', '..') for x in value.split('/')):
        raise GhError('Use owner/repository.', 'input')
    return value


def segment(value):
    return quote(str(value), safe='')


def path(value):
    if not isinstance(value, str) or '\x00' in value or any(x in ('.', '..') for x in value.split('/')) or value.startswith('/'):
        raise GhError('Invalid repository path.', 'input')
    return '/'.join(segment(x) for x in value.split('/'))


def web_url(value):
    try:
        u = urlparse(value)
        if u.scheme != 'https' or not u.hostname or u.username or u.password or u.port not in (None, 443):
            return ''
        return value
    except ValueError:
        return ''


def resolve(value, repo=''):
    value = str(value).strip()
    if re.fullmatch(r'#?[1-9][0-9]*', value) and repo:
        return {'kind':'issue', 'repo':repository(repo), 'number':int(value.lstrip('#'))}
    if re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', value):
        return {'kind':'repository', 'repo':repository(value)}
    if not web_url(value) or urlparse(value).hostname != 'github.com':
        raise GhError('Paste a github.com repository, issue, PR, release or Actions URL.', 'input')
    u = urlparse(value)
    parts = [unquote(p) for p in u.path.strip('/').split('/')]
    if len(parts) < 2:
        raise GhError('This GitHub URL does not identify a repository.', 'unsupported')
    repo = repository('/'.join(parts[:2]))
    tail = parts[2:]
    if not tail:
        return {'kind':'repository', 'repo':repo}
    mapping = {'issues':'issue', 'pull':'pull-request', 'discussions':'discussion', 'commit':'commit'}
    if len(tail) >= 2 and tail[0] in mapping:
        number = tail[1]
        if tail[0] == 'commit':
            if not re.fullmatch(r'[a-fA-F0-9]{7,40}', number):
                raise GhError('Invalid commit URL.', 'input')
        elif not re.fullmatch(r'[1-9][0-9]*', number):
            raise GhError('Invalid item number.', 'input')
        else:
            number = int(number)
        return {'kind':mapping[tail[0]], 'repo':repo, 'number':number}
    if tail[:2] == ['actions','runs'] and len(tail) >= 3 and tail[2].isdigit():
        if len(tail) >= 5 and tail[3] == 'job' and tail[4].isdigit():
            return {'kind':'job', 'repo':repo, 'number':int(tail[4])}
        return {'kind':'run', 'repo':repo, 'number':int(tail[2])}
    if tail[:2] == ['releases','tag'] and len(tail) > 2:
        return {'kind':'release-tag', 'repo':repo, 'tag':'/'.join(tail[2:])}
    if tail[0] in ('blob','tree') and len(tail) >= 2:
        # Resolve branch names containing slashes on the server, longest first.
        return {'kind':'code-url', 'repo':repo, 'path':'/'.join(tail[1:])}
    collection = {'issues':'issues', 'pulls':'pulls', 'actions':'runs', 'releases':'releases', 'branches':'branches', 'commits':'commits', 'discussions':'discussions'}.get(tail[0])
    if collection:
        return {'kind':'collection', 'collection':collection, 'repo':repo}
    raise GhError('This GitHub page is not supported by the native reader.', 'unsupported')
