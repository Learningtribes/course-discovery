"""Write a Django 5.2-correct ``discovery.yml`` for a py3.13 staging/production host.

Why this script exists
----------------------
`course_discovery.settings.production` reads one YAML file (``$DISCOVERY_CFG``) and one
JSON file (``discovery.auth.json``). Neither ``base.py`` nor ``production.py`` defines a
``CACHES`` default, so the YAML's ``CACHES`` is what Django gets. The Ansible role that
writes that YAML (``edx_django_service_caches``) still emits
``django.core.cache.backends.memcached.MemcachedCache``, which Django removed in 4.1; a
py3.13 host therefore dies at ``django.setup()`` with ``InvalidCacheBackendError`` before
it opens a database connection, because ``django-parler`` touches the cache at import.

The Platform solved the same problem the same way: its own generator
(``platform/ci/py313/bringup/generate_aws_config.py``) writes the config into a
Platform-owned directory and the service is pointed at it with ``CONFIG_ROOT``, so the
Ansible-generated file is not reused. Discovery follows that pattern: this script writes a
corrected copy, and ``DISCOVERY_CFG`` is pointed at it. The Ansible file is left untouched,
so a rollback is "point ``DISCOVERY_CFG`` back".

Why the source is read rather than regenerated
----------------------------------------------
The Ansible YAML carries environment values this repository does not know (Elasticsearch
URL, e-mail host, partner id, OIDC keys, ...). Rewriting the whole file from scratch would
have to duplicate them, and any drift would silently change a live deployment. So the
script copies the source and replaces only the keys Django 5.2 forces us to change. Use
``--minimal`` on a host that has no Ansible output yet.

Usage
-----
    # from a host that already ran the discovery Ansible role
    python ci/py313/generate_discovery_config.py \
        --source /edx/etc/discovery.yml \
        --out /edx/app/discovery/py313-config/discovery.yml

    # which export line does the service need?
    python ci/py313/generate_discovery_config.py --source ... --out ... --print-env

    # a fresh host with no Ansible output
    python ci/py313/generate_discovery_config.py --minimal --out ... --print-env

The script never prints a secret value: only key names and the non-secret identity of the
file it wrote.
"""
import argparse
import importlib
import json
import os
from pathlib import Path
import sys

import yaml

DEFAULT_CACHE_BACKEND = 'django.core.cache.backends.memcached.PyMemcacheCache'
DEFAULT_KEY_PREFIX = 'discovery-py313'
# Backends Django 5.2 still ships, so a hand-edited file cannot smuggle an older one back in.
SUPPORTED_BACKENDS = (
    'django.core.cache.backends.memcached.PyMemcacheCache',
    'django.core.cache.backends.memcached.PyLibMCCache',
)
DEFAULT_MEMCACHE_PORT = '11211'
# Set by `production.py` to build DATABASES; a YAML without it is useless.
REQUIRED_KEYS = ('SECRET_KEY',)

# `AUTHENTICATION_BACKENDS` names `auth_backends.backends.EdXOAuth2`. social-auth derives the
# settings prefix from the backend's `name = 'edx-oauth2'`, so it reads `SOCIAL_AUTH_EDX_OAUTH2_*`.
# The Ansible role that writes this YAML still emits the keys of the removed `EdXOpenIdConnect`
# backend, which nothing reads now, so a corrected copy that keeps those names leaves browser
# login unconfigured while looking perfectly healthy.
OAUTH2_RENAMES = {
    'SOCIAL_AUTH_EDX_OIDC_KEY': 'SOCIAL_AUTH_EDX_OAUTH2_KEY',
    'SOCIAL_AUTH_EDX_OIDC_SECRET': 'SOCIAL_AUTH_EDX_OAUTH2_SECRET',
    'SOCIAL_AUTH_EDX_OIDC_URL_ROOT': 'SOCIAL_AUTH_EDX_OAUTH2_URL_ROOT',
    'SOCIAL_AUTH_EDX_OIDC_LOGOUT_URL': 'SOCIAL_AUTH_EDX_OAUTH2_LOGOUT_URL',
}
# Dropped rather than renamed: it only fed the removed backend's ID-token decryption, and the
# OAuth2 backend has no equivalent. Carrying it forward would suggest it still has an effect.
OAUTH2_DROPPED = ('SOCIAL_AUTH_EDX_OIDC_ID_TOKEN_DECRYPTION_KEY',)


def fail(message):
    raise SystemExit('generate_discovery_config: ' + message)


def read_source(path):
    if not path.is_file():
        fail('%s does not exist; run the discovery Ansible role first, or pass --minimal' % path)
    try:
        loaded = yaml.safe_load(path.read_text(encoding='utf-8'))
    except yaml.YAMLError as exc:
        fail('%s is not valid YAML: %s' % (path, exc))
    if not isinstance(loaded, dict):
        fail('%s must contain a YAML mapping at the top level' % path)
    return loaded


def minimal_config():
    """The smallest mapping `production.py` can start from; every other key falls back to base.py."""
    return {
        'SECRET_KEY': os.environ.get('DISCOVERY_SECRET_KEY') or fail('--minimal needs DISCOVERY_SECRET_KEY'),
        'TIME_ZONE': 'UTC',
        'LANGUAGE_CODE': 'en',
    }


def cache_locations(config):
    """Keep the deployment's existing memcached addresses; they are not ours to guess."""
    existing = ((config.get('CACHES') or {}).get('default') or {}).get('LOCATION')
    if isinstance(existing, str):
        return [existing]
    if isinstance(existing, list) and existing:
        return list(existing)
    from_env = os.environ.get('DISCOVERY_MEMCACHE')
    if from_env:
        return [item.strip() for item in from_env.replace(',', ' ').split() if item.strip()]
    return ['memcache']


def with_port(location):
    """`cache+memcached://host:port/` needs an explicit port; a bare host is not accepted there."""
    return location if ':' in location else location + ':' + DEFAULT_MEMCACHE_PORT


def apply_django52(config):
    """Replace exactly what Django 4.1+ forces: the cache backend, its namespace, the Celery result URL."""
    locations = cache_locations(config)
    key_prefix = os.environ.get('DISCOVERY_CACHE_KEY_PREFIX', DEFAULT_KEY_PREFIX)
    if not key_prefix:
        fail('DISCOVERY_CACHE_KEY_PREFIX must not be empty')
    caches = dict(config.get('CACHES') or {})
    default = dict(caches.get('default') or {})
    default.update(BACKEND=DEFAULT_CACHE_BACKEND, KEY_PREFIX=key_prefix, LOCATION=locations)
    caches['default'] = default
    # Every alias the old file carried has to move too, or a named cache alias keeps the
    # removed backend and fails only when something first reads it.
    for alias, entry in list(caches.items()):
        if alias == 'default' or not isinstance(entry, dict):
            continue
        backend = entry.get('BACKEND')
        if backend and backend not in SUPPORTED_BACKENDS:
            entry['BACKEND'] = DEFAULT_CACHE_BACKEND
            entry.setdefault('LOCATION', locations)
    config['CACHES'] = caches

    result_backend = os.environ.get('DISCOVERY_CELERY_RESULT_BACKEND') or (
        'cache+memcached://' + with_port(locations[0]) + '/')
    config.setdefault('CELERY_RESULT_BACKEND', result_backend)
    return config


def apply_oauth2_backend(config):
    """Move the backend's credential keys onto the prefix `EdXOAuth2` actually reads.

    Values are moved as-is; nothing here reads, prints or validates a secret. A key that is
    already spelled the new way wins, so re-running over an already-corrected file is a no-op
    rather than a way to clobber a newer value with a stale one.
    """
    for old, new in OAUTH2_RENAMES.items():
        if old not in config:
            continue
        if new not in config:
            config[new] = config[old]
        del config[old]
    for dropped in OAUTH2_DROPPED:
        config.pop(dropped, None)
    return config


def validate_oauth2(config):
    """Report keys the backend ignores, and fail only on a configuration that cannot log in.

    `apply_oauth2_backend` renames every key it knows about, so a key from `OAUTH2_RENAMES`
    surviving to here is a bug in that function, while anything else starting with
    `SOCIAL_AUTH_EDX_OIDC_` is a setting of the removed backend that has no OAuth2 equivalent.
    The distinction matters because a leftover must not block a deployment: a harmless extra
    key in an Ansible file would otherwise stop the generator and, with it, the config the
    service needs to start at all. Unknown keys are reported and dropped; only a rename-table
    key that somehow survived is fatal.
    """
    survived = sorted(key for key in config if key in OAUTH2_RENAMES)
    if survived:
        raise ValueError('apply_oauth2_backend did not rename: ' + ', '.join(survived))
    ignored = sorted(key for key in config if key.startswith('SOCIAL_AUTH_EDX_OIDC_'))
    if ignored:
        print('note: dropping keys the EdXOAuth2 backend ignores: ' + ', '.join(ignored),
              file=sys.stderr)
        for key in ignored:
            del config[key]
    if config.get('SOCIAL_AUTH_EDX_OAUTH2_KEY') and not config.get('SOCIAL_AUTH_EDX_OAUTH2_URL_ROOT'):
        fail('SOCIAL_AUTH_EDX_OAUTH2_KEY is set but SOCIAL_AUTH_EDX_OAUTH2_URL_ROOT is not; '
             'browser login would have no LMS to redirect to')
    return config


def validate(config, check_imports=True):
    """Refuse to write a file that cannot start: a wrong backend only surfaces at django.setup()."""
    missing = [key for key in REQUIRED_KEYS if not config.get(key)]
    if missing:
        fail('source is missing required key(s): ' + ', '.join(missing))
    caches = config.get('CACHES')
    if not isinstance(caches, dict) or not isinstance(caches.get('default'), dict):
        fail('CACHES.default is missing')
    for alias, entry in sorted(caches.items()):
        if not isinstance(entry, dict):
            fail('CACHES.%s is not a mapping' % alias)
        backend = entry.get('BACKEND')
        if backend not in SUPPORTED_BACKENDS:
            fail('CACHES.%s uses %r, which Django 5.2 does not provide' % (alias, backend))
        if not check_imports:
            continue
        try:
            module_name, _, attribute = backend.rpartition('.')
            getattr(importlib.import_module(module_name), attribute)
        except (ImportError, AttributeError) as exc:
            fail('CACHES.%s backend %s is not importable here: %s\n'
                 'Run this script with the service venv (it owns Django), or pass --skip-import-check'
                 % (alias, backend, exc))
    return config


def write(path, config, force):
    if path.exists() and not force:
        fail('%s already exists; rerun with --force to replace it' % path)
    path.parent.mkdir(parents=True, exist_ok=True)
    text = yaml.safe_dump(config, default_flow_style=False, sort_keys=True, allow_unicode=True)
    tmp = path.with_name(path.name + '.tmp')
    tmp.write_text(text, encoding='utf-8')
    os.chmod(tmp, 0o640)
    tmp.replace(path)
    return text


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--source', type=Path,
                        help='the Ansible-generated discovery.yml to correct (default: $DISCOVERY_CFG)')
    parser.add_argument('--minimal', action='store_true',
                        help='build from base.py defaults instead of an existing file (fresh host)')
    parser.add_argument('--out', type=Path, required=True,
                        help='where to write the corrected file (a new, service-owned directory)')
    parser.add_argument('--force', action='store_true', help='replace an existing --out file')
    parser.add_argument('--print-env', action='store_true',
                        help='print the DISCOVERY_CFG export line the service needs')
    parser.add_argument('--dry-run', action='store_true', help='report the plan without writing')
    parser.add_argument('--skip-import-check', action='store_true',
                        help='do not import the backend class (for a host without the service venv)')
    args = parser.parse_args(argv)

    if args.minimal:
        config = minimal_config()
    else:
        source = args.source or (Path(os.environ['DISCOVERY_CFG']) if os.environ.get('DISCOVERY_CFG') else None)
        if source is None:
            fail('pass --source, set DISCOVERY_CFG, or use --minimal')
        config = read_source(source)
        if args.source is None:
            print('Source: $DISCOVERY_CFG')
        if source.resolve() == args.out.resolve():
            fail('--out must not be the source file; the corrected copy replaces it via DISCOVERY_CFG')

    config = validate(apply_django52(config), check_imports=not args.skip_import_check)
    config = validate_oauth2(apply_oauth2_backend(config))

    if args.dry_run:
        print('Would write %s with keys: %s' % (args.out, ', '.join(sorted(config))))
        return 0
    write(args.out, config, args.force)
    print('Wrote %s (mode 0640) with keys: %s' % (args.out, ', '.join(sorted(config))))
    print('CACHES.default.BACKEND: ' + config['CACHES']['default']['BACKEND'])
    print('CACHES.default.KEY_PREFIX: ' + str(config['CACHES']['default']['KEY_PREFIX']))
    if args.print_env:
        print('export DISCOVERY_CFG="%s"' % args.out)
    return 0


if __name__ == '__main__':
    sys.exit(main())
