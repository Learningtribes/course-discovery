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

Why `docker build` is not a substitute
--------------------------------------
Kept function-for-function comparable with the Devstack builder. The parity list is the
reason a plain `docker build` cannot replace it:

1. multi-platform OCI *index* (`linux/amd64` + `linux/arm64`) in one manifest list
2. dated-tag enforcement, refusing `latest` and implicit tags
3. refusal to overwrite a tag that already exists remotely
4. refusal to build from a dirty tree
5. context from `git archive HEAD`, so only committed content enters the build
6. `--provenance=false --sbom=false`, plus rejection of any `unknown/unknown` attestation
   manifest that would otherwise pollute the index
7. index digests read back *from the registry*, never from local buildx metadata
8. a validated lock pinning index digest + per-platform digests + source commit
9. retry with backoff around registry reads, which a flapping VPN resets
10. `--registry-proxy` for client-side registry reads only
11. `--lock-only --source-commit` recovery after a failed index read
12. a `docker-container` builder when the daemon has no containerd image store
13. `--context` kept on disk as a build audit trail
"""
import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tarfile
import tempfile
import time

REPOSITORY = 'ltdps/discovery'
STAGE = 'final'
PLATFORMS = ('linux/amd64', 'linux/arm64')
# The Dockerfile reads nothing from the repository beyond itself; a minimal context is reproducible.
BUILD_INPUTS = ('ci/py313/Dockerfile',)
BUILD_ARG_NAMES = {'DEBIAN_MIRROR', 'DEBIAN_SECURITY_MIRROR', 'NODE_DIST_URL'}
TAG_RE = re.compile(re.escape(REPOSITORY) + r':[A-Za-z0-9_][A-Za-z0-9_.-]*\d{8}[a-z]?')
INDEX_MEDIA_TYPE = 'application/vnd.oci.image.index.v1+json'
DIGEST_RE = re.compile(r'sha256:[0-9a-f]{64}')
BACKOFF = (5, 15, 30)
# Registry reads are the calls a flapping VPN/DNS breaks; give them longer to recover.
REGISTRY_BACKOFF = (5, 15, 30, 60, 120)
ROOT = Path(__file__).resolve().parents[2]
LOCK_PATH = Path(__file__).resolve().with_name('runtime-image.lock.json')


def git(root, *args, **kwargs):
    # Ignore GIT_* inherited from hooks or worktree wrappers; operate on `root` only.
    env = {key: value for key, value in os.environ.items() if not key.startswith('GIT_')}
    return subprocess.run(['git', '-C', str(root), *args], check=True, env=env, **kwargs)


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
        time.sleep(delay)
    return result


def tag_missing(result):
    return bool(re.search(r'not found|manifest unknown|no such manifest', result.stderr, re.IGNORECASE))


def registry_environment(proxy):
    """Environment for client-side registry reads only (buildx would forward a proxy into the build)."""
    env = dict(os.environ)
    if proxy:
        env.update(HTTPS_PROXY=proxy, https_proxy=proxy)
    return env


def tag_exists(tag, env=None):
    result = retrying(['docker', 'buildx', 'imagetools', 'inspect', tag], definitive=tag_missing,
                      backoff=REGISTRY_BACKOFF, env=env, capture_output=True, text=True)
    if result.returncode == 0:
        return True
    if tag_missing(result):
        return False
    raise SystemExit('Cannot determine whether %s exists remotely:\n%s' % (tag, result.stderr))


def containerd_store():
    info = json.loads(subprocess.check_output(['docker', 'info', '--format', '{{json .DriverStatus}}'], text=True))
    return ['driver-type', 'io.containerd.snapshotter.v1'] in info


def builder_args(name):
    """Name an explicit builder, else use the default one if the daemon can push an index itself."""
    if name:
        return ['--builder', name]
    if containerd_store():
        return []
    name = 'py313-discovery-builder'
    if subprocess.run(['docker', 'buildx', 'inspect', name], capture_output=True).returncode:
        subprocess.run(['docker', 'buildx', 'create', '--name', name, '--driver', 'docker-container',
                        '--bootstrap'], check=True)
    return ['--builder', name]


def parse_index(raw):
    """Return (index digest, {platform: child manifest digest}) from a raw OCI image index."""
    index = json.loads(raw)
    if index.get('mediaType') != INDEX_MEDIA_TYPE:
        raise SystemExit('Pushed tag is %r, not an OCI image index' % index.get('mediaType'))
    platforms = {}
    for manifest in index.get('manifests', []):
        platform = manifest.get('platform') or {}
        if platform.get('os') == 'unknown':
            raise SystemExit('Unexpected attestation manifest; build with --provenance=false --sbom=false')
        # Docker reports arm64 with or without the v8 variant depending on the producer.
        key = '%s/%s' % (platform.get('os'), platform.get('architecture'))
        if key in platforms:
            raise SystemExit('Duplicate platform in image index: ' + key)
        platforms[key] = manifest['digest']
    if set(platforms) != set(PLATFORMS):
        raise SystemExit('Image index platforms %s differ from %s' % (sorted(platforms), list(PLATFORMS)))
    return 'sha256:' + hashlib.sha256(raw).hexdigest(), platforms


def pushed_index(tag, env):
    raw = retrying(['docker', 'buildx', 'imagetools', 'inspect', '--raw', tag], backoff=REGISTRY_BACKOFF,
                   env=env, capture_output=True)
    if raw.returncode:
        raise SystemExit('Cannot inspect pushed ' + tag)
    return parse_index(raw.stdout)


def validate_lock(lock):
    """Reject a hand-edited or partially written lock before anything consumes it.

    Mirrors the Devstack replay's `validate_runtime_lock`. The one deliberate difference is the
    source key: this image is built from the course-discovery repository, so the field is
    `source_commit` rather than `devstack_commit`. A shared validator would have to generalise
    that name; no consumer reads this lock yet.
    """
    required = {'schema_version', 'repository', 'tag', 'stage', 'registry_manifest_type',
                'index_digest', 'platforms', 'source_commit', 'built_on'}
    if not isinstance(lock, dict) or set(lock) != required:
        raise SystemExit('Runtime image lock has an invalid schema')
    if type(lock['schema_version']) is not int or lock['schema_version'] != 1:
        raise SystemExit('Unsupported runtime image lock schema version')
    if lock['repository'] != REPOSITORY:
        raise SystemExit('Runtime image lock repository must be ' + REPOSITORY)
    tag = lock['tag']
    if not isinstance(tag, str) or tag.startswith('latest') or not re.search(r'\d{8}', tag):
        raise SystemExit('Runtime image lock tag must be an explicit dated tag')
    if not isinstance(lock['stage'], str) or not lock['stage']:
        raise SystemExit('Runtime image lock has no build stage')
    if lock['registry_manifest_type'] != INDEX_MEDIA_TYPE:
        raise SystemExit('Runtime image lock is not an OCI image index lock')
    if not isinstance(lock['index_digest'], str) or not DIGEST_RE.fullmatch(lock['index_digest']):
        raise SystemExit('Runtime image lock has an invalid index digest')
    if not isinstance(lock['source_commit'], str) or not re.fullmatch(r'[0-9a-f]{40}', lock['source_commit']):
        raise SystemExit('Runtime image lock has an invalid source commit')
    try:
        datetime.date.fromisoformat(lock['built_on'])
    except (TypeError, ValueError):
        raise SystemExit('Runtime image lock has an invalid build date')
    platforms = lock['platforms']
    if not isinstance(platforms, dict) or set(platforms) != set(PLATFORMS):
        raise SystemExit('Runtime image lock must carry exactly linux/amd64 and linux/arm64 manifests')
    for digest in platforms.values():
        if not isinstance(digest, str) or not DIGEST_RE.fullmatch(digest):
            raise SystemExit('Runtime image lock has an invalid platform digest')
    return lock


def lock_record(tag, index_digest, platforms, commit, built_on):
    return validate_lock({
        'schema_version': 1, 'repository': REPOSITORY, 'tag': tag.partition(':')[2], 'stage': STAGE,
        'registry_manifest_type': INDEX_MEDIA_TYPE, 'index_digest': index_digest, 'platforms': platforms,
        'source_commit': commit, 'built_on': built_on})


def write_lock(path, tag, index_digest, platforms, commit):
    record = lock_record(tag, index_digest, platforms, commit, datetime.date.today().isoformat())
    path.write_text(json.dumps(record, indent=2, sort_keys=True) + '\n')
    print('Pushed %s@%s from %s' % (REPOSITORY, index_digest, commit))
    for platform, digest in sorted(platforms.items()):
        print('  %s %s' % (platform, digest))
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
    dirty = git(ROOT, 'status', '--porcelain', '--untracked-files=all', capture_output=True, text=True).stdout
    if dirty.strip():
        raise SystemExit('Refusing to build from a dirty tree:\n' + dirty)
    sha = git(ROOT, 'rev-parse', 'HEAD', capture_output=True, text=True).stdout.strip()
    if not re.fullmatch(r'[0-9a-f]{40}', sha):
        raise SystemExit('Cannot resolve HEAD')
    if tag_exists(args.tag, registry_env):
        raise SystemExit('%s already exists remotely; choose a new tag (e.g. a "b" suffix)' % args.tag)
    args.context.mkdir(mode=0o700, parents=False)
    with tempfile.TemporaryFile() as stream:
        git(ROOT, 'archive', sha, *BUILD_INPUTS, stdout=stream)
        stream.seek(0)
        with tarfile.open(fileobj=stream) as archive:
            archive.extractall(args.context, filter='data')
    context = args.context / 'ci/py313'
    # --provenance/--sbom off: attestation manifests would add unknown/unknown entries to the index.
    command = ['docker', 'buildx', 'build', *builder_args(args.builder), '--platform', ','.join(PLATFORMS),
               '--target', STAGE, '--provenance=false', '--sbom=false', *build_args,
               '-f', str(context / 'Dockerfile'), '-t', args.tag, '--push', str(context)]
    if retrying(command).returncode:
        raise SystemExit('Build or push failed')
    try:
        index = pushed_index(args.tag, registry_env)
    except SystemExit:
        print('Push succeeded but the index could not be read; record it with: --lock-only --tag %s '
              '--source-commit %s' % (args.tag, sha), file=sys.stderr)
        raise
    write_lock(args.lock, args.tag, *index, sha)


if __name__ == '__main__':
    main()
