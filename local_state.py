"""Account-scoped, atomic private state. No tokens and no queued remote writes."""
import hashlib
import json
import os
from pathlib import Path
import time
from github_client import atomic_write, GhError

LIMIT = 8 * 1024 * 1024


def root(account):
    if not account or not isinstance(account, str):
        raise GhError('Sign in before using saved workspace data.', 'auth')
    base = Path(os.environ.get('XDG_STATE_HOME', Path.home() / '.local/state'))
    return base / 'omarchy/github/accounts' / hashlib.sha256(account.encode()).hexdigest()[:24]


def read(account, name):
    path = root(account) / (name + '.json')
    try:
        if path.stat().st_size > LIMIT:
            raise GhError('Saved workspace data exceeds its size limit.', 'response-limit')
        value = json.loads(path.read_text())
        return value if isinstance(value, dict) else {}
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def put(account, name, key, value):
    data = read(account, name)
    if value is None:
        data.pop(key, None)
    else:
        data[key] = value
    if len(json.dumps(data).encode()) > LIMIT:
        raise GhError('Saved workspace is full. Remove old drafts or saved views.', 'response-limit')
    atomic_write(root(account) / (name + '.json'), data)
    return data


def cache_key(item):
    return hashlib.sha256(json.dumps(item, sort_keys=True).encode()).hexdigest()


def cache(account, item, detail):
    data = read(account, 'cache')
    data[cache_key(item)] = {'at': time.time(), 'detail': detail}
    # Bound total size as well as count. Eviction is oldest-first.
    while len(data) > 25 or len(json.dumps(data).encode()) > LIMIT:
        del data[min(data, key=lambda k: data[k]['at'])]
    atomic_write(root(account) / 'cache.json', data)


def cached(account, item):
    record = read(account, 'cache').get(cache_key(item))
    if not record:
        return None
    detail = record['detail']
    detail.update(cached=True, canReply=False, actions=[], pr=None, threadId='')
    detail['warnings'] = ['Offline copy — fetched ' + time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime(record['at'])) + '. Refresh before taking an action.']
    for tab in detail.get('tabs', []):
        for block in tab.get('blocks', []):
            block['operations'] = []
    return detail
