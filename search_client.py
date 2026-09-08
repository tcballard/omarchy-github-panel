#!/usr/bin/python3
"""Bounded, read-only issue and PR search using the existing gh session."""
import json
import re
import sys
from urllib.parse import urlencode, urlparse
from reader_client import Client, GhError, REPO

PAGE_SIZE = 50
ME = re.compile(r'(?<!\S)(author|assignee|mentions|review-requested|involves):@me(?=\s|$)')


def search(request, client=None):
    client = client or Client()
    query = request.get('query', '')
    repo = request.get('repo', '')
    kind = request.get('kind', 'all')
    state = request.get('state', 'all')
    page = request.get('page', 1)
    if not isinstance(query, str) or len(query) > 1000 or not isinstance(repo, str):
        raise GhError('Use a search query of at most 1,000 characters.', 'input')
    query, repo = query.strip(), repo.strip()
    if repo and (not REPO.fullmatch(repo) or any(x in ('.', '..') for x in repo.split('/'))):
        raise GhError('Use owner/repository for the repository filter.', 'input')
    if kind not in ('all', 'issue', 'pr') or state not in ('all', 'open', 'closed', 'merged'):
        raise GhError('Invalid search filter.', 'input')
    if type(page) is not int or not 1 <= page <= 20:
        raise GhError('Search supports the first 1,000 results. Narrow your query.', 'input')
    if not query and not repo:
        raise GhError('Enter a search query or repository.', 'input')
    if kind == 'issue' and state == 'merged':
        raise GhError('Merged applies to pull requests. Choose PRs or another state.', 'input')
    if ME.search(query):
        login = client.api('user')['login']
        query = ME.sub(lambda match: match[1] + ':' + login, query)
    terms = ['(' + query + ')'] if query else []
    if repo: terms.append('repo:' + repo)
    if kind != 'all': terms.append('is:' + kind)
    if state != 'all': terms.append('is:' + state)
    params = urlencode({'q': ' '.join(terms), 'sort':'updated', 'order':'desc', 'per_page':PAGE_SIZE, 'page':page, 'advanced_search':'true'})
    response = client.api('search/issues?' + params)
    items = []
    for node in response.get('items', []):
        repository_url = urlparse(node.get('repository_url', ''))
        if repository_url.scheme != 'https' or repository_url.netloc != 'api.github.com':
            raise GhError('GitHub returned an unsupported repository URL.', 'parse')
        repository = repository_url.path.removeprefix('/repos/')
        target = client.target({'kind':'pull-request' if node.get('pull_request') else 'issue', 'repo':repository, 'number':node['number']})
        items.append({**target, 'id':f"{target['kind']}:{repository}:{node['number']}",
                      'title':node['title'], 'updatedAt':node.get('updated_at',''),
                      'state':('merged' if (node.get('pull_request') or {}).get('merged_at') else node.get('state','')).upper(),
                      'lane':'Pull request' if target['kind']=='pull-request' else 'Issue',
                      'author':(node.get('user') or {}).get('login',''), 'url':node.get('html_url','')})
    total = response.get('total_count', 0)
    warning = 'GitHub returned incomplete results. Narrow your query or search again.' if response.get('incomplete_results') else ''
    if total > 1000: warning += (' ' if warning else '') + 'Only the first 1,000 results are available; narrow your query to see the rest.'
    return {'ok':True, 'items':items, 'total':total, 'page':page,
            'hasMore':bool(items) and page * PAGE_SIZE < min(total, 1000), 'warning':warning}


def main():
    try:
        result = search(json.loads(sys.stdin.readline(10000)))
    except (GhError, ValueError, TypeError, KeyError) as exc:
        result = {'ok':False, 'error':str(exc)}
    print(json.dumps(result, ensure_ascii=False))

if __name__ == '__main__': main()
