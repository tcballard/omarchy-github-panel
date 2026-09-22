"""Explicit, bounded asset transfers; no archive extraction or shell expansion."""
import json
import os
from pathlib import Path
import re
import subprocess
from bounded_process import run_bounded, OutputLimitExceeded
from github_client import GhError
from navigation import repository, segment

MAX_BYTES=256*1024*1024


def download(repo,kind,number,name,runner=run_bounded):
    repository(repo)
    if not isinstance(number,int) or number<1 or kind not in ('asset','artifact'): raise GhError('Invalid download.', 'input')
    endpoint=f'repos/{repo}/'+('releases/assets/'+str(number) if kind=='asset' else 'actions/artifacts/'+str(number)+'/zip')
    filename=re.sub(r'[^A-Za-z0-9._ -]','_',str(name))[:160].strip(' .') or f'{kind}-{number}'
    if kind=='artifact' and not filename.endswith('.zip'): filename+='.zip'
    folder=Path.home()/'Downloads'
    folder.mkdir(mode=0o700,parents=True,exist_ok=True)
    try:
        result=runner(['gh','api','--hostname','github.com',endpoint,'-H','Accept: application/octet-stream'],stdout_limit=MAX_BYTES,timeout=180)
    except (OutputLimitExceeded,subprocess.TimeoutExpired) as exc:
        raise GhError('Download exceeded 256 MiB or three minutes; no file was saved.', 'response-limit') from exc
    if result.returncode: raise GhError(result.stderr.decode('utf-8','replace')[:500] or 'Download failed.')
    for index in range(1000):
        destination=folder/(filename if index==0 else f'{index}-{filename}')
        try: descriptor=os.open(destination,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        except FileExistsError: continue
        try:
            with os.fdopen(descriptor,'wb') as f: f.write(result.stdout)
        except OSError:
            destination.unlink(missing_ok=True); raise
        return str(destination)
    raise GhError('Too many files with this download name.', 'input')


def upload(repo,release_id,filename,runner=run_bounded):
    repository(repo)
    source=Path(filename).expanduser()
    if not source.is_absolute() or not source.is_file() or source.stat().st_size>MAX_BYTES:
        raise GhError('Choose an absolute path to a file under 256 MiB.', 'input')
    endpoint=f'https://uploads.github.com/repos/{repo}/releases/{int(release_id)}/assets?name='+segment(source.name)
    try:
        result=runner(['gh','api','--hostname','github.com','-X','POST',endpoint,'-H','Content-Type: application/octet-stream','--input',str(source)],stdout_limit=1024*1024,timeout=180)
    except (OutputLimitExceeded,subprocess.TimeoutExpired) as exc:
        raise GhError('Upload timed out or returned too much data. Inspect release assets before retrying.', 'unconfirmed') from exc
    if result.returncode: raise GhError(result.stderr.decode('utf-8','replace')[:500] or 'Upload failed.')
    node=json.loads(result.stdout)
    if node.get('state')!='uploaded': raise GhError('GitHub did not confirm the uploaded asset.', 'unconfirmed')
    return node
