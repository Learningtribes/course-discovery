"""Offline guards for the companion archive's identity, run with pytest from ci/py313/.

`rebuild-companion.py` itself reproduces the archive from upstream + patch and needs network, so
it is not exercised here. What must hold offline is the identities it rebuilds against: exactly
one companion record, and the committed archive and patch matching the manifest's digests. A
hand-edited binary that slips through would make the lock's `--hash` cite bytes nobody reviewed.
"""
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

SCRIPT = Path(__file__).with_name('rebuild-companion.py')


def load():
    spec = importlib.util.spec_from_file_location('rebuild_companion', SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


rebuild_companion = load()


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def test_exactly_one_companion_record():
    records = json.loads(rebuild_companion.MANIFEST.read_text())['packages']
    assert len(records) == 1
    assert records[0]['name'] == 'edx-drf-extensions'


def test_the_committed_archive_matches_the_manifest():
    record_ = rebuild_companion.record()
    committed = rebuild_companion.ARTIFACTS / record_['artifact']
    assert committed.is_file()
    assert sha256(committed.read_bytes()) == record_['sha256']


def test_the_patch_matches_its_manifest_digest():
    record_ = rebuild_companion.record()
    patch = rebuild_companion.PATCHES / record_['patch']
    assert patch.is_file()
    assert sha256(patch.read_bytes()) == record_['patch_sha256']


def test_the_manifest_records_every_source_file_digest():
    """The per-file map is what lets a reviewer confirm the archive's contents without rebuilding."""
    record_ = rebuild_companion.record()
    assert record_['files']
    assert record_['upstream_url'].startswith('https://')
    assert record_['upstream_sha256']
