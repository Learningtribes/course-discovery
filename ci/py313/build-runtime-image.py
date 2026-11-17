"""Build and push the multi-platform course-discovery runtime base image, then write its lock.

This is the course-discovery counterpart of the Devstack replay's
`docker/py313/build-runtime-image.py`, and it exists for the same reason: the Devstack
replay consumes a *released* runtime image by digest, so that an image identity is a
reviewable committed artefact instead of whatever happened to be built on one machine.

Why discovery needs its own release step
----------------------------------------
The platform's runtime image (`ltdps/edxapp`) is published by Devstack because the
Platform code lives outside Devstack. Discovery's Dockerfile lives in *this* repository
(`ci/py313/Dockerfile`), so discovery owns its own publication. Both images are
deliberately the same shape: a digest-pinned `python:3.13-slim-bookworm` base, Debian
mirror build args, declared build dependencies and a Node 16.20.2 stage -- and neither
bakes the application in. The application is installed later, inside the container, from
`requirements/py313/local.txt` into an isolated venv.

What the lock is for
--------------------
`ci/py313/runtime-image.lock.json` records the tag, the OCI index digest, the per-platform
manifest digests and the source commit. A Devstack run can then be configured with
`discovery_image = ltdps/discovery@sha256:<index digest>`, which is reproducible and
verifiable, instead of a mutable tag or a machine-local image ID.

Run with Python 3.13 on the host, from a clean tree:

    uv run --no-project --python 3.13 python -B ci/py313/build-runtime-image.py \
        --tag ltdps/discovery:py313-devstack-YYYYMMDD --context /new/dir

The script refuses `latest`/implicit tags, an existing remote tag and a dirty tree, builds
from `git archive HEAD` (so only committed content enters the archive) and pushes with
`docker buildx build --push`.
"""
import argparse
import datetime
import hashlib
import io
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tarfile

REPOSITORY = 'ltdps/discovery'
STAGE = 'final'
PLATFORMS = ('linux/amd64', 'linux/arm64')
# The Dockerfile reads nothing from the repository: the build context only has to carry it.
BUILD_INPUTS = ('ci/py313/Dockerfile',)
BUILD_ARG_NAMES = {'DEBIAN_MIRROR', 'DEBIAN_SECURITY_MIRROR', 'NODE_DIST_URL'}
TAG_RE = re.compile(re.escape(REPOSITORY) + r':[A-Za-z0-9_][A-Za-z0-9_.-]*\d{8}[a-z]?')
INDEX_MEDIA_TYPE = 'application/vnd.oci.image.index.v1+json'
BACKOFF = (5, 15, 30)
REGISTRY_BACKOFF = (5, 15, 30, 60, 120)
ROOT = Path(__file__).resolve().parents[2]
LOCK_PATH = Path(__file__).resolve().with_name('runtime-image.lock.json')


def git(*args, **kwargs):
    # Ignore GIT_* inherited from hooks or worktree wrappers; operate on this checkout only.
    env = {key: value for key, value in os.environ.items() if not key.startswith('GIT_')}
    return subprocess.run(['git', '-C', str(ROOT), *args], check=True, env=env, **kwargs)


def validate_tag(tag):
    if not TAG_RE.fullmatch(tag) or tag.rpartition(':')[2].startswith('latest'):
        raise SystemExit('Refusing a shared or implicit tag; use %s:<name>-YYYYMMDD[a-z]' % REPOSITORY)
    return tag


def retrying(command, definitive=None, backoff=BACKOFF, **kwargs):
    # A VPN can reset registry connections mid-build; layers are cached, so a retry is cheap.
    result = None
    for delay in (*backoff, None):
        result = subprocess.run(command, **kwargs)
        if result.returncode == 0 or delay is None or (definitive and definitive(result)):
            return result
        print('retrying in %ds after exit %d: %s' % (delay, result.returncode, ' '.join(command[:4])), flush=True)
        sys.stdout.flush()


def tag_missing(result):
    text = (result.stderr or '') + (result.stdout or '')
    return 'not found' in text.lower() or 'manifest unknown' in text.lower()


def registry_environment(proxy):
    env = dict(os.environ)
    if proxy:
        for key in ('HTTPS_PROXY', 'https_proxy', 'HTTP_PROXY', 'http_proxy'):
            env[key] = proxy
    return env


def tag_exists(tag, env=None):
    result = retrying(['docker', 'buildx', 'imagetools', 'inspect', tag], definitive=tag_missing,
                      backoff=REGISTRY_BACKOFF, capture_output=True, text=True, env=env)
    if result.returncode == 0:
        return True
    if tag_missing(result):
        return False
    raise SystemExit('Cannot determine whether %s exists remotely:\n%s' % (tag, result.stderr))


def builder_args(name):
    """Reuse the current builder when it can already push an index; else create a container driver."""
    if name:
        return ['--builder', name]
    if subprocess.run(['docker', 'buildx', 'inspect'], capture_output=True).returncode == 0:
        return []
    name = 'py313-discovery-index'
    if subprocess.run(['docker', 'buildx', 'inspect', name], capture_output=True).returncode:
        subprocess.run(['docker', 'buildx', 'create', '--name', name, '--driver', 'docker-container'], check=True)
    return ['--builder', name]


def pushed_index(tag, env):
    """Read the index and per-platform manifests back from the registry, not from local metadata."""
    raw = retrying(['docker', 'buildx', 'imagetools', 'inspect', '--raw', tag], backoff=REGISTRY_BACKOFF,
                   capture_output=True, text=True, env=env)
    if raw.returncode:
        raise SystemExit('Cannot inspect pushed ' + tag)
    index = json.loads(raw.stdout)
    if index.get('mediaType') != INDEX_MEDIA_TYPE:
        raise SystemExit('Pushed tag is %r, not an OCI image index' % index.get('mediaType'))
    digest = hashlib.sha256(raw.stdout.encode('utf-8')).hexdigest()
    manifests = {}
    for entry in index['manifests']:
        platform = entry.get('platform') or {}
        name = platform.get('os', '') + '/' + platform.get('architecture', '')
        if platform.get('variant'):
            name += '/' + platform['variant']
        manifests[name] = entry['digest']
    return 'sha256:' + digest, manifests


def write_lock(path, tag, index_digest, platforms, commit):
    record = {
        'schema_version': 1, 'repository': REPOSITORY, 'tag': tag.partition(':')[2], 'stage': STAGE,
        'index_digest': index_digest, 'platforms': platforms, 'source_commit': commit,
        'registry_manifest_type': INDEX_MEDIA_TYPE, 'built_on': datetime.date.today().isoformat(),
    }
    path.write_text(json.dumps(record, indent=2, sort_keys=True) + '\n')
    print('Wrote %s; commit it in a follow-up commit.' % path)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--tag', required=True, help='new tag, e.g. %s:py313-devstack-YYYYMMDD' % REPOSITORY)
    parser.add_argument('--context', type=Path, help='new directory, kept for build audit (required to build)')
    parser.add_argument('--builder', help='buildx builder (default: the current one if it can push an index)')
    parser.add_argument('--build-arg', action='append', default=[], metavar='NAME=VALUE',
                        help='mirror override, one of ' + ', '.join(sorted(BUILD_ARG_NAMES)))
    parser.add_argument('--registry-proxy', metavar='URL',
                        help='HTTP CONNECT proxy for client-side registry reads (tag check, index inspect)')
    parser.add_argument('--lock', type=Path, default=LOCK_PATH, help='lock file to write')
    parser.add_argument('--lock-only', action='store_true',
                        help='record an already pushed tag (recovery after a failed inspect); needs --source-commit')
    parser.add_argument('--source-commit', help='commit the pushed image was built from (with --lock-only)')
    args = parser.parse_args(argv)
    validate_tag(args.tag)
    registry_env = registry_environment(args.registry_proxy)
    if args.lock_only:
        if not args.source_commit or not re.fullmatch(r'[0-9a-f]{40}', args.source_commit):
            raise SystemExit('--lock-only requires the full --source-commit the image was built from')
        write_lock(args.lock, args.tag, *pushed_index(args.tag, registry_env), args.source_commit)
        return
    if not args.context:
        raise SystemExit('--context is required to build')
    build_args = []
    for item in args.build_arg:
        name, _, value = item.partition('=')
        if name not in BUILD_ARG_NAMES or not value:
            raise SystemExit('--build-arg must be NAME=VALUE with NAME in ' + ', '.join(sorted(BUILD_ARG_NAMES)))
        build_args += ['--build-arg', item]
    dirty = git('status', '--porcelain', '--untracked-files=all', capture_output=True, text=True).stdout
    if dirty.strip():
        raise SystemExit('Refusing to build from a dirty tree:\n' + dirty)
    commit = git('rev-parse', 'HEAD', capture_output=True, text=True).stdout.strip()
    if not re.fullmatch(r'[0-9a-f]{40}', commit):
        raise SystemExit('Cannot resolve HEAD')
    if tag_exists(args.tag, registry_env):
        raise SystemExit('%s already exists remotely; choose a new tag (e.g. a "b" suffix)' % args.tag)
    args.context.mkdir(mode=0o700, parents=False)
    data = git('archive', commit, *BUILD_INPUTS, capture_output=True).stdout
    with tarfile.open(fileobj=io.BytesIO(data)) as archive:
        archive.extractall(args.context, filter='data')
    context = args.context / 'ci/py313'
    # --provenance/--sbom off: attestation manifests would add unknown/unknown entries to the index.
    command = ['docker', 'buildx', 'build', *builder_args(args.builder), '--platform', ','.join(PLATFORMS),
               '--target', STAGE, '--provenance=false', '--sbom=false', *build_args,
               '-f', str(context / 'Dockerfile'), '-t', args.tag, '--push', str(context)]
    if retrying(command).returncode:
        raise SystemExit('Build or push failed')
    try:
        index_digest, platforms = pushed_index(args.tag, registry_env)
    except SystemExit:
        print('Push succeeded but the index could not be read; record it with: --lock-only --tag %s '
              '--source-commit %s' % (args.tag, commit), file=sys.stderr)
        raise
    write_lock(args.lock, args.tag, index_digest, platforms, commit)


if __name__ == '__main__':
    main()
