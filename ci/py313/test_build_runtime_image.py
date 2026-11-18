"""Contract tests for the release script, run with pytest from ci/py313/.

The script's value over a plain `docker build` is the index parsing, the lock validation and
the guard rails; those are the parts a wrong implementation would silently corrupt.
"""
import importlib.util
import json
from pathlib import Path

import pytest

SCRIPT = Path(__file__).with_name('build-runtime-image.py')


def load():
    spec = importlib.util.spec_from_file_location('build_runtime_image', SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


index_raw = load()


def make_index(*entries):
    return json.dumps({'mediaType': index_raw.INDEX_MEDIA_TYPE, 'manifests': list(entries)}).encode('utf-8')


AMD = {'platform': {'os': 'linux', 'architecture': 'amd64'}, 'digest': 'sha256:' + 'a' * 64}
ARM = {'platform': {'os': 'linux', 'architecture': 'arm64'}, 'digest': 'sha256:' + 'b' * 64}
ARM_V8 = {'platform': {'os': 'linux', 'architecture': 'arm64', 'variant': 'v8'},
          'digest': 'sha256:' + 'c' * 64}
ATTESTATION = {'platform': {'os': 'unknown', 'architecture': 'unknown'},
               'digest': 'sha256:' + 'd' * 64}


def test_parse_index_returns_index_digest_and_both_platforms():
    digest, platforms = index_raw.parse_index(make_index(AMD, ARM))
    assert digest.startswith('sha256:')
    assert len(digest) == len('sha256:') + 64
    assert platforms == {'linux/amd64': AMD['digest'], 'linux/arm64': ARM['digest']}


def test_parse_index_ignores_the_arm64_variant_so_the_key_stays_stable():
    """Docker reports arm64 with or without /v8; the lock key must not flip between builds."""
    _, platforms = index_raw.parse_index(make_index(AMD, ARM_V8))
    assert set(platforms) == {'linux/amd64', 'linux/arm64'}


def test_parse_index_rejects_an_attestation_manifest():
    """An unknown/unknown entry means --provenance/--sbom leaked into the index."""
    with pytest.raises(SystemExit, match='attestation'):
        index_raw.parse_index(make_index(AMD, ARM, ATTESTATION))


def test_parse_index_rejects_a_duplicate_platform():
    with pytest.raises(SystemExit, match='Duplicate platform'):
        index_raw.parse_index(make_index(AMD, ARM, ARM))


def test_parse_index_rejects_a_missing_platform():
    with pytest.raises(SystemExit, match='differ from'):
        index_raw.parse_index(make_index(AMD))


def test_parse_index_rejects_a_non_index_manifest_list():
    raw = json.dumps({'mediaType': 'application/vnd.oci.image.manifest.v1+json', 'manifests': []}).encode()
    with pytest.raises(SystemExit, match='not an OCI image index'):
        index_raw.parse_index(raw)


def good_lock(**overrides):
    lock = {
        'schema_version': 1,
        'repository': index_raw.REPOSITORY,
        'tag': 'py313-devstack-20261118',
        'stage': index_raw.STAGE,
        'registry_manifest_type': index_raw.INDEX_MEDIA_TYPE,
        'index_digest': 'sha256:' + 'e' * 64,
        'platforms': {'linux/amd64': 'sha256:' + 'a' * 64, 'linux/arm64': 'sha256:' + 'b' * 64},
        'source_commit': 'f' * 40,
        'built_on': '2026-11-18',
    }
    lock.update(overrides)
    return lock


def test_validate_lock_accepts_the_record_the_script_writes():
    assert index_raw.validate_lock(good_lock()) == good_lock()


@pytest.mark.parametrize('overrides, message', [
    ({'schema_version': 2}, 'schema version'),
    ({'repository': 'ltdps/edxapp'}, 'repository'),
    ({'tag': 'latest'}, 'dated tag'),
    ({'tag': 'py313-devstack'}, 'dated tag'),
    ({'registry_manifest_type': 'application/json'}, 'not an OCI image index'),
    ({'index_digest': 'sha256:short'}, 'index digest'),
    ({'source_commit': 'abc'}, 'source commit'),
    ({'built_on': 'yesterday'}, 'build date'),
    ({'platforms': {'linux/amd64': 'sha256:' + 'a' * 64}}, 'exactly linux/amd64'),
    ({'platforms': {'linux/amd64': 'sha256:' + 'a' * 64, 'linux/arm64': 'nope'}}, 'platform digest'),
])
def test_validate_lock_rejects_a_corrupt_record(overrides, message):
    with pytest.raises(SystemExit, match=message):
        index_raw.validate_lock(good_lock(**overrides))


def test_validate_lock_rejects_an_unknown_or_missing_key():
    lock = good_lock()
    lock['extra'] = 'value'
    with pytest.raises(SystemExit, match='invalid schema'):
        index_raw.validate_lock(lock)
    missing = good_lock()
    del missing['stage']
    with pytest.raises(SystemExit, match='invalid schema'):
        index_raw.validate_lock(missing)


@pytest.mark.parametrize('tag, accepted', [
    ('ltdps/discovery:py313-devstack-20261118', True),
    ('ltdps/discovery:py313-devstack-20261118b', True),
    ('ltdps/discovery:latest', False),
    ('ltdps/discovery:py313-local', False),
    ('ltdps/edxapp:py313-devstack-20261118', False),
    ('py313-devstack-20261118', False),
])
def test_validate_tag_requires_a_dated_repository_tag(tag, accepted):
    if accepted:
        assert index_raw.validate_tag(tag) == tag
    else:
        with pytest.raises(SystemExit, match='shared or implicit tag'):
            index_raw.validate_tag(tag)
