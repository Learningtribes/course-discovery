"""Contract tests for `course_discovery.settings.py313`.

The py3.13 settings used to carry a hardcoded `OIDC_KEY`/`OIDC_SECRET` pair that matched no
application the runner registers, so discovery authenticated as the wrong DOT client and the
LMS answered 401 on a metadata call. These tests pin the replacement contract: the pair is
required, a missing half fails at import time, and nothing falls back to a static value.

`course_discovery.settings.base` is replaced by a stub because the module is about OIDC
credentials only; the real base is exercised by the runner's `manage.py check` stage.
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

    spec = importlib.util.spec_from_file_location('py313_under_test', SETTINGS)

    def _load():
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    return _load


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
