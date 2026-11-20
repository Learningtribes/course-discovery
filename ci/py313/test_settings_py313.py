"""Contract tests for `course_discovery.settings.py313`.

Two contracts are pinned here.

**The module is local-only.** It enables DEBUG, accepts any Host header and can fall back to a
JWT secret published in this repository, so it refuses to import unless `DISCOVERY_LOCAL_RUN=1`
says this is a local run. Measured before the guard: a token forged with
`discovery-py313-jwt-secret-key` was accepted with `administrator=True`.

**OIDC credentials are required.** The module used to carry a hardcoded `OIDC_KEY`/`OIDC_SECRET`
pair that matched no application the runner registers, so discovery authenticated as the wrong
DOT client and the LMS answered 401 on a metadata call. A missing half now fails at import time
and nothing falls back to a static value.

`course_discovery.settings.base` is replaced by a stub because the module is about its own
guards only; the real base is exercised by the runner's `manage.py check` stage.
"""
import importlib.util
import sys
import types
from pathlib import Path

import pytest

SETTINGS = Path(__file__).resolve().parents[2] / 'course_discovery' / 'settings' / 'py313.py'


class ImproperlyConfigured(Exception):
    """Stands in for `django.core.exceptions.ImproperlyConfigured`."""


@pytest.fixture
def load(monkeypatch):
    """Execute the real py313.py with a stubbed django and base, returning the module."""
    django = types.ModuleType('django')
    core = types.ModuleType('django.core')
    exceptions = types.ModuleType('django.core.exceptions')
    exceptions.ImproperlyConfigured = ImproperlyConfigured
    core.exceptions = exceptions
    django.core = core
    base = types.ModuleType('course_discovery.settings.base')
    base.__all__ = ['JWT_AUTH', 'LOGGING']
    base.JWT_AUTH = {'JWT_ISSUERS': []}
    base.LOGGING = {}
    package = types.ModuleType('course_discovery')
    package.__path__ = []
    settings_package = types.ModuleType('course_discovery.settings')
    settings_package.__path__ = []

    stubs = {
        'django': django, 'django.core': core, 'django.core.exceptions': exceptions,
        'course_discovery': package, 'course_discovery.settings': settings_package,
        'course_discovery.settings.base': base,
    }
    for name, module in stubs.items():
        monkeypatch.setitem(sys.modules, name, module)
    monkeypatch.delenv('DISCOVERY_OIDC_KEY', raising=False)
    monkeypatch.delenv('DISCOVERY_OIDC_SECRET', raising=False)
    # The OIDC tests are about the OIDC guard, so they run as a confirmed local run.
    monkeypatch.setenv('DISCOVERY_LOCAL_RUN', '1')

    spec = importlib.util.spec_from_file_location('py313_under_test', SETTINGS)

    def _load():
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    return _load


@pytest.fixture
def oidc(monkeypatch):
    """Satisfy the OIDC guard, so a test can reach the settings it actually asserts on."""
    monkeypatch.setenv('DISCOVERY_OIDC_KEY', 'derived-key')
    monkeypatch.setenv('DISCOVERY_OIDC_SECRET', 'derived-secret')


@pytest.mark.parametrize('value', [None, '', '0', 'true', 'yes'])
def test_the_module_refuses_to_load_without_the_local_run_flag(load, monkeypatch, value):
    """Anything other than exactly `1` is not a confirmation, including a truthy-looking word."""
    if value is None:
        monkeypatch.delenv('DISCOVERY_LOCAL_RUN')
    else:
        monkeypatch.setenv('DISCOVERY_LOCAL_RUN', value)

    with pytest.raises(ImproperlyConfigured) as error:
        load()

    assert 'DISCOVERY_LOCAL_RUN' in str(error.value)
    assert 'production' in str(error.value)


def test_a_confirmed_local_run_still_gets_the_permissive_values(load, oidc):
    module = load()

    assert module.DEBUG is True
    assert module.ALLOWED_HOSTS == ['*']


def test_a_standalone_local_run_falls_back_to_the_published_secret(load, oidc, monkeypatch):
    """The fallback is reachable only behind the flag; this pins what a standalone run gets."""
    monkeypatch.delenv('DISCOVERY_LMS_JWT_SECRET', raising=False)
    monkeypatch.delenv('DISCOVERY_JWT_SECRET_KEY', raising=False)

    assert load().JWT_AUTH['JWT_SECRET_KEY'] == 'discovery-py313-jwt-secret-key'


def test_a_missing_key_fails_instead_of_using_a_static_default(load):
    with pytest.raises(ImproperlyConfigured) as error:
        load()
    assert 'DISCOVERY_OIDC_KEY' in str(error.value)


def test_a_missing_secret_fails_even_when_the_key_is_present(load, monkeypatch):
    monkeypatch.setenv('DISCOVERY_OIDC_KEY', 'derived-key')
    with pytest.raises(ImproperlyConfigured) as error:
        load()
    assert 'DISCOVERY_OIDC_SECRET' in str(error.value)


def test_both_values_are_taken_from_the_environment_verbatim(load, monkeypatch):
    monkeypatch.setenv('DISCOVERY_OIDC_KEY', 'derived-key')
    monkeypatch.setenv('DISCOVERY_OIDC_SECRET', 'derived-secret')
    api = load().COURSES_API
    assert api['OIDC_KEY'] == 'derived-key'
    assert api['OIDC_SECRET'] == 'derived-secret'
