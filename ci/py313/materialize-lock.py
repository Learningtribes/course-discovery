"""Resolve a lock's companion directory and verify the archive before writing it out.

`requirements/py313/base.in` names the one non-PyPI input with the `@COMPANIONS_DIR@`
placeholder instead of a concrete directory, because no single absolute path is correct
everywhere: the devstack replay mounts this repository at `/workspace`, a deploy checkout
lives wherever it was cloned. A compiled lock therefore stays environment-neutral, and this
script turns it into an installable one for the environment at hand.

The archive is checked against `companions/manifest.json` first, so a written lock can only
name bytes whose digest was reviewed.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys

PLACEHOLDER = '@COMPANIONS_DIR@'
ROOT = Path(__file__).resolve().parent
MANIFEST = ROOT / 'companions' / 'manifest.json'


def digest(data):
    return hashlib.sha256(data).hexdigest()


def manifest_artifacts():
    """{archive filename: sha256} for every companion the manifest records."""
    return {record['artifact']: record['sha256'] for record in json.loads(MANIFEST.read_text())['packages']}


def verify_artifacts(companions_dir):
    verified = 0
    for artifact, expected in manifest_artifacts().items():
        archive = companions_dir / artifact
        if not archive.is_file():
            raise ValueError('companion archive missing: %s' % archive)
        if digest(archive.read_bytes()) != expected:
            raise ValueError('companion archive digest mismatch: %s' % archive)
        verified += 1
    return verified


def materialize(lock, companions_dir, *, check=True):
    """Return `lock`'s text with the placeholder resolved; unchanged when it has none."""
    text = Path(lock).read_text()
    if PLACEHOLDER not in text:
        return text
    if check:
        verify_artifacts(companions_dir)
    resolved = text.replace(PLACEHOLDER, str(companions_dir).rstrip('/'))
    if PLACEHOLDER in resolved:
        raise ValueError('%s: placeholder survived substitution' % lock)
    return resolved


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('lock', nargs='+', help='requirements file to rewrite')
    parser.add_argument('--companions-dir', required=True,
                        help='absolute directory holding the companion archives')
    parser.add_argument('--output-dir', help='write here instead of beside each input')
    parser.add_argument('--no-verify', action='store_true', help='skip the archive digest check')
    args = parser.parse_args(argv)

    companions_dir = Path(args.companions_dir)
    if not companions_dir.is_absolute():
        # A relative path would resolve against whatever directory the installer happens to run
        # from, which is the class of bug this script exists to remove.
        raise SystemExit('--companions-dir must be absolute, got %r' % args.companions_dir)

    for lock in args.lock:
        text = materialize(lock, companions_dir, check=not args.no_verify)
        if PLACEHOLDER not in Path(lock).read_text():
            print('%s: no %s, left unchanged' % (lock, PLACEHOLDER))
            continue
        destination = Path(args.output_dir or Path(lock).parent) / Path(lock).name
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(text)
        print('%s -> %s' % (lock, destination))
    return 0


if __name__ == '__main__':
    sys.exit(main())
