"""Read-only smoke check against the existing local gh session."""
import sys,json
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from reader_client import Client
c=Client()
cache=json.loads((Path.home()/'.local/state/omarchy/github/dashboard.json').read_text())
items=[{'repo':'tcballard/omarchy','kind':'pull-request','number':2}]
for kind in ['notifications','issues','discussions','ci']:
    if cache.get(kind): items.append(cache[kind][0])
for item in items:
    try:
        d=c.detail(item)
        print(json.dumps({'kind':item['kind'],'ok':d['ok'],'tabs':[t['id'] for t in d['tabs']], 'blocks':sum(len(t['blocks']) for t in d['tabs']),'warnings':d['warnings']}),flush=True)
    except Exception as e:
        print(json.dumps({'kind':item['kind'],'error':str(e)}),flush=True)
