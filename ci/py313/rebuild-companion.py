"""Verify (and, optionally, rebuild) the committed companion archive from upstream + patch.

The one non-PyPI input to the lock is `ci/py313/companions/artifacts/edx_drf_extensions-*.tar.gz`.
It is a patched sdist, so it has no registry hash to cite; instead `companions/manifest.json`
records its identity and this script reconstructs it from the public upstream sdist plus the
committed patch, then checks the bytes match. A reviewer can run the same command and get the
same archive, which is the answer to "why is a binary committed to git": it is not opaque, it is
reproducible.

    python ci/py313/rebuild-companion.py              # verify the committed archive matches upstream+patch
    python ci/py313/rebuild-companion.py --write      # rebuild and overwrite the committed archive

Rebuilding requires network access to `files.pythonhosted.org` and the `patch` binary. The verify
path downloads the upstream sdist too, because reproducing it is the point; run it in CI or on a
machine with PyPI access.
"""
import argparse
import gzip
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import urllib.request

ROOT = Path(__file__).resolve().parent
MANIFEST = ROOT / 'companions' / 'manifest.json'
PATCHES = ROOT / 'companion-patches'
ARTIFACTS = ROOT / 'companions' / 'artifacts'


def digest(data):
    return hashlib.sha256(data).hexdigest()


def record():
    records = json.loads(MANIFEST.read_text())['packages']
    if len(records) != 1:
        raise ValueError('expected exactly one companion record, found %d' % len(records))
    return records[0]


def download(url):
    with urllib.request.urlopen(url, timeout=120) as response:
        return response.read()


def extract(data, directory):
    with tarfile.open(fileobj=io.BytesIO(data)) as archive:
        if not all(member.isfile() or member.isdir() for member in archive.getmembers()):
            raise ValueError('unexpected upstream archive member type')
        archive.extractall(directory, filter='data')
    return next(iter(directory.iterdir()))


def tree_files(source):
    return {path.relative_to(source).as_posix(): digest(path.read_bytes())
            for path in sorted(source.rglob('*')) if path.is_file()}


def apply_patch(record, source):
    patch = record.get('patch')
    if not patch:
        return
    patch_path = PATCHES / patch
    if digest(patch_path.read_bytes()) != record['patch_sha256']:
        raise ValueError('patch digest mismatch: ' + patch)
    subprocess.run(['patch', '--batch', '--fuzz=0', '-p1', '-i', str(patch_path)],
                   cwd=source, check=True, stdout=subprocess.DEVNULL)


def apply_version_edits(record, source):
    for edit in record.get('version_edits', []):
        path = source / edit['file']
        text = path.read_text()
        if text.count(edit['old']) != 1:
            raise ValueError('unexpected version declaration: ' + edit['file'])
        path.write_text(text.replace(edit['old'], edit['new']))
    for metadata in source.rglob('PKG-INFO'):
        text = metadata.read_text()
        metadata.write_text(text.replace(
            '\nVersion: ' + record['upstream_version'] + '\n',
            '\nVersion: ' + record['version'] + '\n', 1))


def repack(record, source):
    if any(path.is_symlink() for path in source.rglob('*')):
        raise ValueError('symbolic links are not admitted in companion sources')
    buffer = io.BytesIO()
    with gzip.GzipFile(fileobj=buffer, mode='wb', filename='', mtime=0) as compressed:
        with tarfile.open(fileobj=compressed, mode='w', format=tarfile.PAX_FORMAT) as archive:
            prefix = record['artifact'].removesuffix('.tar.gz')
            for path in sorted(source.rglob('*')):
                if not path.is_file():
                    continue
                content = path.read_bytes()
                info = tarfile.TarInfo(prefix + '/' + path.relative_to(source).as_posix())
                info.size = len(content)
                info.mode = 0o755 if path.stat().st_mode & 0o111 else 0o644
                info.mtime = info.uid = info.gid = 0
                archive.addfile(info, io.BytesIO(content))
    return buffer.getvalue()


def rebuild():
    """Return the reconstructed archive bytes and its per-file tree, verifying each recorded identity."""
    record_ = record()
    upstream = download(record_['upstream_url'])
    if digest(upstream) != record_['upstream_sha256']:
        raise ValueError('upstream digest mismatch: ' + record_['name'])
    with tempfile.TemporaryDirectory() as tmp:
        directory = Path(tmp)
        source = extract(upstream, directory)
        apply_patch(record_, source)
        apply_version_edits(record_, source)
        data = repack(record_, source)
        files = tree_files(source)
    return record_, data, files


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--write', action='store_true',
                        help='overwrite the committed archive with the rebuilt one')
    args = parser.parse_args(argv)

    record_, data, files = rebuild()
    committed = ARTIFACTS / record_['artifact']
    actual = digest(data)
    committed_digest = digest(committed.read_bytes()) if committed.is_file() else None

    print('upstream  :', record_['upstream_url'])
    print('patch     :', record_['patch'])
    print('rebuilt   :', actual)
    print('committed :', committed_digest)
    if actual != record_['sha256']:
        raise SystemExit('rebuilt archive does not match the manifest sha256: %s' % record_['name'])
    if files != record_['files']:
        raise SystemExit('rebuilt source tree does not match the manifest files: %s' % record_['name'])
    if args.write:
        committed.write_bytes(data)
        print('wrote     :', committed)
    elif committed_digest != record_['sha256']:
        raise SystemExit('committed archive does not match the manifest sha256: %s' % record_['name'])
    print('PASS: the committed archive is reproducible from upstream + patch')
    return 0


if __name__ == '__main__':
    sys.exit(main())
