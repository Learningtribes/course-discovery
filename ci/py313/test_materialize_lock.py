"""Contract tests for the lock materializer, run with pytest from ci/py313/.

What this script must get right is narrow and easy to get wrong: the placeholder has to be
gone from the written lock, the archive has to be the reviewed one, and a directory that only
looks absolute must not slip through. Those are the three assertions below.
"""
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

SCRIPT = Path(__file__).with_name('materialize-lock.py')


def load():
    spec = importlib.util.spec_from_file_location('materialize_lock', SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


materialize_lock = load()
PLACEHOLDER = materialize_lock.PLACEHOLDER


@pytest.fixture
def companions(tmp_path):
    """A companions directory holding one archive, plus a lock that names it."""
    archive = tmp_path / 'artifacts' / 'companion-1.0.tar.gz'
    archive.parent.mkdir()
    archive.write_bytes(b'reviewed bytes')
    companions_dir = archive.parent

    lock = tmp_path / 'lock.txt'
    lock.write_text(
        'django==5.2\n'
        'edx-drf-extensions @ file://%s/companion-1.0.tar.gz\n' % PLACEHOLDER
    )
    manifest = tmp_path / 'manifest.json'
    manifest.write_text(json.dumps({'packages': [{
        'artifact': archive.name,
        'sha256': hashlib.sha256(b'reviewed bytes').hexdigest(),
    }]}))
    return companions_dir, lock, manifest


def patch_manifest(monkeypatch, manifest):
    monkeypatch.setattr(materialize_lock, 'MANIFEST', manifest)


def test_placeholder_is_replaced_with_the_requested_directory(companions, monkeypatch):
    companions_dir, lock, manifest = companions
    patch_manifest(monkeypatch, manifest)

    text = materialize_lock.materialize(lock, companions_dir)

    assert PLACEHOLDER not in text
    assert 'file://%s/companion-1.0.tar.gz' % companions_dir in text
    assert 'django==5.2' in text


def test_a_lock_without_the_placeholder_is_returned_unchanged(companions, monkeypatch):
    _, _, manifest = companions
    patch_manifest(monkeypatch, manifest)
    plain = Path(manifest).parent / 'plain.txt'
    plain.write_text('django==5.2\n')

    assert materialize_lock.materialize(plain, Path('/nonexistent')) == 'django==5.2\n'


def test_a_tampered_archive_is_refused(companions, monkeypatch):
    companions_dir, lock, manifest = companions
    patch_manifest(monkeypatch, manifest)
    (companions_dir / 'companion-1.0.tar.gz').write_bytes(b'tampered')

    with pytest.raises(ValueError, match='digest mismatch'):
        materialize_lock.materialize(lock, companions_dir)


def test_a_missing_archive_is_refused(companions, monkeypatch):
    companions_dir, lock, manifest = companions
    patch_manifest(monkeypatch, manifest)
    (companions_dir / 'companion-1.0.tar.gz').unlink()

    with pytest.raises(ValueError, match='archive missing'):
        materialize_lock.materialize(lock, companions_dir)


def test_a_relative_companions_directory_is_rejected(companions, monkeypatch):
    _, lock, manifest = companions
    patch_manifest(monkeypatch, manifest)

    with pytest.raises(SystemExit, match='must be absolute'):
        materialize_lock.main([str(lock), '--companions-dir', 'ci/py313/companions/artifacts'])


def test_output_dir_receives_the_resolved_lock(companions, monkeypatch, tmp_path):
    companions_dir, lock, manifest = companions
    patch_manifest(monkeypatch, manifest)
    out = tmp_path / 'out'

    materialize_lock.main([str(lock), '--companions-dir', str(companions_dir), '--output-dir', str(out)])

    written = (out / 'lock.txt').read_text()
    assert PLACEHOLDER not in written
    assert str(companions_dir) in written
