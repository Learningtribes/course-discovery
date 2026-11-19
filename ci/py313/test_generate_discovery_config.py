"""Contract tests for the py3.13 discovery.yml generator.

The reported production failure was `InvalidCacheBackendError` at `django.setup()`, so the
tests pin the two properties that fix it: every cache alias stops naming the removed
`MemcachedCache`, and nothing else in the deployment's YAML is lost.
"""
import importlib.util
from pathlib import Path

import pytest
import yaml

SCRIPT = Path(__file__).with_name('generate_discovery_config.py')


@pytest.fixture
def gen(monkeypatch):
    monkeypatch.delenv('DISCOVERY_CACHE_KEY_PREFIX', raising=False)
    monkeypatch.delenv('DISCOVERY_CELERY_RESULT_BACKEND', raising=False)
    monkeypatch.delenv('DISCOVERY_MEMCACHE', raising=False)
    spec = importlib.util.spec_from_file_location('generate_discovery_config', SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ANSIBLE_OUTPUT = {
    'SECRET_KEY': 'secret',
    'LANGUAGE_CODE': 'en',
    'TIME_ZONE': 'UTC',
    'ELASTICSEARCH_URL': 'http://es:9200/',
    'PLATFORM_NAME': 'Triboo',
    'DEFAULT_PARTNER_ID': 1,
    'CSRF_COOKIE_SECURE': True,
    'PARLER_DEFAULT_LANGUAGE_CODE': 'en',
    'CACHES': {
        'default': {'BACKEND': 'django.core.cache.backends.memcached.MemcachedCache',
                    'KEY_PREFIX': 'discovery', 'LOCATION': ['memcache']},
        'configuration': {'BACKEND': 'django.core.cache.backends.memcached.MemcachedCache',
                          'KEY_PREFIX': 'configuration', 'LOCATION': ['memcache']},
    },
}


def test_every_cache_alias_stops_naming_the_removed_backend(gen):
    """`default` is not enough: a named alias fails only when something first reads it."""
    result = gen.apply_django52(dict(ANSIBLE_OUTPUT, CACHES={
        alias: dict(entry) for alias, entry in ANSIBLE_OUTPUT['CACHES'].items()}))
    for alias, entry in result['CACHES'].items():
        assert entry['BACKEND'] == gen.DEFAULT_CACHE_BACKEND, alias
        assert 'MemcachedCache' not in entry['BACKEND']


def test_default_alias_gets_the_new_namespace_so_old_pickles_are_not_read(gen):
    """drf-extensions pickles responses; reading a python-memcached era key breaks deserialisation."""
    result = gen.apply_django52(dict(ANSIBLE_OUTPUT, CACHES={
        alias: dict(entry) for alias, entry in ANSIBLE_OUTPUT['CACHES'].items()}))
    assert result['CACHES']['default']['KEY_PREFIX'] == 'discovery-py313'
    assert result['CACHES']['default']['KEY_PREFIX'] != 'discovery'


def test_key_prefix_is_overridable(gen, monkeypatch):
    monkeypatch.setenv('DISCOVERY_CACHE_KEY_PREFIX', 'custom-prefix')
    result = gen.apply_django52(dict(ANSIBLE_OUTPUT, CACHES={
        alias: dict(entry) for alias, entry in ANSIBLE_OUTPUT['CACHES'].items()}))
    assert result['CACHES']['default']['KEY_PREFIX'] == 'custom-prefix'


def test_existing_locations_are_preserved(gen):
    """The deployment's memcached addresses are not ours to guess."""
    source = dict(ANSIBLE_OUTPUT, CACHES={'default': {
        'BACKEND': 'django.core.cache.backends.memcached.MemcachedCache',
        'KEY_PREFIX': 'discovery', 'LOCATION': ['10.0.0.5:11211', '10.0.0.6:11211']}})
    result = gen.apply_django52(source)
    assert result['CACHES']['default']['LOCATION'] == ['10.0.0.5:11211', '10.0.0.6:11211']


def test_celery_result_backend_gets_a_port(gen):
    """`cache+memcached://host/` is rejected; the URL needs host:port."""
    result = gen.apply_django52(dict(ANSIBLE_OUTPUT, CACHES={
        alias: dict(entry) for alias, entry in ANSIBLE_OUTPUT['CACHES'].items()}))
    assert result['CELERY_RESULT_BACKEND'] == 'cache+memcached://memcache:11211/'


def test_an_explicit_celery_result_backend_is_kept(gen):
    source = dict(ANSIBLE_OUTPUT, CACHES={
        alias: dict(entry) for alias, entry in ANSIBLE_OUTPUT['CACHES'].items()},
        CELERY_RESULT_BACKEND='redis://cache:6379/0')
    result = gen.apply_django52(source)
    assert result['CELERY_RESULT_BACKEND'] == 'redis://cache:6379/0'


def test_unrelated_deployment_values_survive(gen):
    """Rewriting a live file must not drop the values this repository does not own."""
    source = dict(ANSIBLE_OUTPUT, CACHES={
        alias: dict(entry) for alias, entry in ANSIBLE_OUTPUT['CACHES'].items()})
    result = gen.apply_django52(source)
    for key in ('SECRET_KEY', 'ELASTICSEARCH_URL', 'PLATFORM_NAME',
                'DEFAULT_PARTNER_ID', 'CSRF_COOKIE_SECURE', 'EMAIL_HOST' if 'EMAIL_HOST' in source else 'TIME_ZONE'):
        assert result[key] == source[key], key


def test_validate_rejects_a_backend_django52_does_not_ship(gen):
    bad = dict(ANSIBLE_OUTPUT, CACHES={'default': {
        'BACKEND': 'django.core.cache.backends.memcached.MemcachedCache', 'KEY_PREFIX': 'x'}})
    with pytest.raises(SystemExit, match='does not provide'):
        gen.validate(bad, check_imports=False)


def test_validate_rejects_a_missing_caches_block(gen):
    """neither base.py nor production.py defines a default, so the YAML must."""
    bad = dict(ANSIBLE_OUTPUT)
    del bad['CACHES']
    with pytest.raises(SystemExit, match='CACHES.default is missing'):
        gen.validate(bad, check_imports=False)


def test_validate_rejects_a_missing_secret_key(gen):
    bad = dict(ANSIBLE_OUTPUT, CACHES=dict(ANSIBLE_OUTPUT['CACHES']))
    del bad['SECRET_KEY']
    with pytest.raises(SystemExit, match='SECRET_KEY'):
        gen.validate(bad, check_imports=False)


def test_write_refuses_to_clobber_without_force(gen, tmp_path):
    target = tmp_path / 'discovery.yml'
    target.write_text('old: value\n')
    with pytest.raises(SystemExit, match='already exists'):
        gen.write(target, {'SECRET_KEY': 'x'}, force=False)
    assert target.read_text() == 'old: value\n'


def test_write_sets_a_service_readable_mode_and_leaves_no_temp_file(gen, tmp_path):
    target = tmp_path / 'nested' / 'discovery.yml'
    gen.write(target, {'SECRET_KEY': 'x'}, force=False)
    assert oct(target.stat().st_mode & 0o777) == oct(0o640)
    assert [p.name for p in target.parent.iterdir()] == ['discovery.yml']


def test_main_writes_a_loadable_file_end_to_end(gen, tmp_path, monkeypatch):
    source = tmp_path / 'source.yml'
    source.write_text(yaml.safe_dump(ANSIBLE_OUTPUT))
    out = tmp_path / 'py313-config' / 'discovery.yml'
    monkeypatch.setattr('sys.argv', ['x', '--source', str(source), '--out', str(out), '--skip-import-check'])
    assert gen.main() == 0
    written = yaml.safe_load(out.read_text())
    assert written['CACHES']['default']['BACKEND'] == gen.DEFAULT_CACHE_BACKEND
    assert written['CACHES']['default']['KEY_PREFIX'] == 'discovery-py313'
    assert written['ELASTICSEARCH_URL'] == 'http://es:9200/'


def test_main_refuses_to_overwrite_the_source_in_place(gen, tmp_path, monkeypatch):
    """The corrected copy must be a different file, so rolling back is repointing DISCOVERY_CFG."""
    source = tmp_path / 'discovery.yml'
    source.write_text(yaml.safe_dump(ANSIBLE_OUTPUT))
    monkeypatch.setattr('sys.argv', ['x', '--source', str(source), '--out', str(source), '--skip-import-check'])
    with pytest.raises(SystemExit, match='must not be the source'):
        gen.main()


# The Ansible role still writes the removed `EdXOpenIdConnect` backend's key names, and nothing
# reads those any more, so a corrected copy that keeps them leaves browser login unconfigured
# while looking healthy. `EdXOAuth2` is named `edx-oauth2`, so social-auth reads `_OAUTH2_*`.

OIDC_SOURCE = {
    'SOCIAL_AUTH_EDX_OIDC_KEY': 'oidc-key',
    'SOCIAL_AUTH_EDX_OIDC_SECRET': 'oidc-secret',
    'SOCIAL_AUTH_EDX_OIDC_URL_ROOT': 'https://lms.example.com',
    'SOCIAL_AUTH_EDX_OIDC_LOGOUT_URL': 'https://lms.example.com/logout',
    'SOCIAL_AUTH_EDX_OIDC_ID_TOKEN_DECRYPTION_KEY': 'oidc-secret',
}

OIDC_RENAMES = {
    'SOCIAL_AUTH_EDX_OIDC_KEY': 'SOCIAL_AUTH_EDX_OAUTH2_KEY',
    'SOCIAL_AUTH_EDX_OIDC_SECRET': 'SOCIAL_AUTH_EDX_OAUTH2_SECRET',
    'SOCIAL_AUTH_EDX_OIDC_URL_ROOT': 'SOCIAL_AUTH_EDX_OAUTH2_URL_ROOT',
    'SOCIAL_AUTH_EDX_OIDC_LOGOUT_URL': 'SOCIAL_AUTH_EDX_OAUTH2_LOGOUT_URL',
}


@pytest.mark.parametrize('old,new', sorted(OIDC_RENAMES.items()))
def test_each_credential_moves_onto_the_prefix_the_backend_reads(gen, old, new):
    result = gen.apply_oauth2_backend(dict(OIDC_SOURCE))

    assert old not in result
    assert result[new] == OIDC_SOURCE[old]


def test_the_id_token_decryption_key_is_dropped_not_renamed(gen):
    """It fed the removed backend's ID-token decryption; the OAuth2 backend has no equivalent."""
    result = gen.apply_oauth2_backend(dict(OIDC_SOURCE))

    assert not [key for key in result if 'ID_TOKEN_DECRYPTION' in key]


def test_a_value_already_under_the_new_name_is_not_overwritten(gen):
    """Re-running over an already-corrected file must not put a stale value back."""
    source = dict(OIDC_SOURCE, SOCIAL_AUTH_EDX_OAUTH2_KEY='newer-key')

    result = gen.apply_oauth2_backend(source)

    assert result['SOCIAL_AUTH_EDX_OAUTH2_KEY'] == 'newer-key'
    assert 'SOCIAL_AUTH_EDX_OIDC_KEY' not in result


def test_a_file_with_no_social_auth_keys_is_untouched(gen):
    result = gen.apply_oauth2_backend({'SECRET_KEY': 'secret'})

    assert result == {'SECRET_KEY': 'secret'}


def test_validate_rejects_a_leftover_oidc_key(gen):
    """It would be ignored silently, so writing it out would look like a fix that is not one."""
    with pytest.raises(SystemExit, match='ignored by the EdXOAuth2 backend'):
        gen.validate_oauth2({'SOCIAL_AUTH_EDX_OIDC_KEY': 'k'})


def test_validate_rejects_a_key_without_a_url_root(gen):
    """Without URL_ROOT the login redirect has no LMS to point at."""
    with pytest.raises(SystemExit, match='URL_ROOT'):
        gen.validate_oauth2({'SOCIAL_AUTH_EDX_OAUTH2_KEY': 'k'})


def test_a_full_run_renames_the_keys_in_the_written_file(gen, tmp_path, monkeypatch):
    """End to end: what the service reads is the generator's output, not the Ansible file."""
    monkeypatch.setenv('DISCOVERY_SECRET_KEY', 'secret')
    out = tmp_path / 'discovery.yml'
    source = tmp_path / 'source.yml'
    source.write_text(yaml.safe_dump(dict(
        ANSIBLE_OUTPUT,
        **{'SOCIAL_AUTH_EDX_OIDC_KEY': 'oidc-key',
           'SOCIAL_AUTH_EDX_OIDC_SECRET': 'oidc-secret',
           'SOCIAL_AUTH_EDX_OIDC_URL_ROOT': 'https://lms.example.com'}
    )))

    gen.main(['--source', str(source), '--out', str(out), '--skip-import-check'])

    written = yaml.safe_load(out.read_text())
    assert written['SOCIAL_AUTH_EDX_OAUTH2_KEY'] == 'oidc-key'
    assert written['SOCIAL_AUTH_EDX_OAUTH2_URL_ROOT'] == 'https://lms.example.com'
    assert not [key for key in written if key.startswith('SOCIAL_AUTH_EDX_OIDC_')]
