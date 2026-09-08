#!/usr/bin/python3
"""Build a reproducible plugin archive containing only distributable files."""
import gzip
import hashlib
import io
import json
from pathlib import Path
import tarfile

ROOT = Path(__file__).resolve().parents[1]
FILES = ['manifest.json', 'LICENSE', 'README.md', 'Panel.qml', 'Reader.qml',
         'Service.qml', 'ActionsDialog.qml', 'PRActionDialog.qml', 'SearchBar.qml',
         'github_client.py', 'reader_client.py', 'lifecycle.py', 'search_client.py', 'review_threads.py']

def main():
    manifest = json.loads((ROOT / 'manifest.json').read_text())
    filename = f"{manifest['id']}-{manifest['version']}.tar.gz"
    directory = ROOT / 'dist'
    directory.mkdir(exist_ok=True)
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode='w') as archive:
        for name in sorted(FILES):
            data = (ROOT / name).read_bytes()
            info = tarfile.TarInfo(manifest['id'] + '/' + name)
            info.mode = 0o644
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))
    data = gzip.compress(output.getvalue(), mtime=0)
    target = directory / filename
    target.write_bytes(data)
    target.with_suffix(target.suffix + '.sha256').write_text(hashlib.sha256(data).hexdigest() + '  ' + filename + '\n')
    print(target)

if __name__ == '__main__': main()
