"""
Python 3.13 / Django 5.2 development settings for course-discovery.

Thin module in the spirit of the platform's `lms/envs/devstack_local.py`: it
imports the shared base and overrides only what the 3.13 environment needs —
MySQL 8.4 (container `discovery-py3-mysql`), memcached (`discovery-py3-memcached`),
a symmetric JWT key for local interop, and permissive hosts.

Nothing here is production config. Secrets come from the environment (set by the
runner), never from this file, so it can be committed.
"""
import os

from course_discovery.settings.base import *  # pylint: disable=wildcard-import,unused-wildcard-import,wrong-import-position

DEBUG = True

ALLOWED_HOSTS = ['*']

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.mysql',
        'NAME': os.environ.get('DB_NAME', 'discovery'),
        'USER': os.environ.get('DB_USER', 'root'),
        'PASSWORD': os.environ.get('DB_PASSWORD', ''),
        'HOST': os.environ.get('DB_HOST', 'discovery-py3-mysql'),
        'PORT': os.environ.get('DB_PORT', '3306'),
        'CONN_MAX_AGE': int(os.environ.get('CONN_MAX_AGE', 0)),
    }
}

CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.memcached.PyMemcacheCache',
        'LOCATION': os.environ.get('CACHE_LOCATION', 'discovery-py3-memcached:11211'),
        # A new namespace: 3.13 must not read 3.5-written pickles (§2.4).
        'KEY_PREFIX': 'discovery-py313',
    }
}

# Symmetric JWT key for local development. The legacy single-issuer form is
# resolved by edx-drf-extensions' `get_first_jwt_issuer()` fallback path
# (JWT_ISSUER / JWT_SECRET_KEY / JWT_AUDIENCE).
JWT_AUTH['JWT_SECRET_KEY'] = os.environ.get('DISCOVERY_JWT_SECRET_KEY', 'discovery-py313-jwt-secret-key')
# drf-jwt's default header prefix changed from 'JWT' to 'Bearer' in the fork that
# edx-drf-extensions 10.6.0 pins. The platform still signs/sends with 'JWT'
# (SuppliedJwtAuth -> 'JWT {token}'), so restore the prefix here.
JWT_AUTH['JWT_AUTH_HEADER_PREFIX'] = 'JWT'

# Avoid the deleted haystack signal processor still referenced by shared/test.py.
HAYSTACK_SIGNAL_PROCESSOR = None

# Sites: disable the cached-site fast path in local dev (matches test.py).
SITE_CACHE_TTL = 0

# The dev DB seeds Site id=1 as discovery-py3.local (see the phase-4a seed step).
SITE_ID = int(os.environ.get('SITE_ID', 1))
