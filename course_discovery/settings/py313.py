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

# The container has no syslog socket at /dev/log; without this every log record raises
# "Logging error" tracebacks. Same override as settings/devstack.py: the console handler keeps the output.
LOGGING['handlers']['local'] = {
    'class': 'logging.NullHandler',
}

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
        # A new namespace: 3.13 must not read 3.5-written pickles (§2.4). The prefix can be overridden so
        # several runs can share one memcached (the devstack bring-up passes its run's cache prefix).
        'KEY_PREFIX': os.environ.get('DISCOVERY_CACHE_PREFIX', 'discovery-py313'),
    }
}

# JWT interop with the platform py3 LMS (phase 6a local integration).
# When DISCOVERY_LMS_JWT_SECRET is set, discovery verifies platform-signed JWTs
# (HS256, issuer http://<lms>/oauth2) instead of its own self-signed tokens. The
# shared secret is the platform's PY313_STARTUP_SECRET_KEY, injected by the runner.
_lms_jwt_secret = os.environ.get('DISCOVERY_LMS_JWT_SECRET', '')
if _lms_jwt_secret:
    JWT_AUTH['JWT_ISSUERS'] = [{
        'ISSUER': os.environ.get('DISCOVERY_LMS_JWT_ISSUER', 'http://localhost:18000/oauth2'),
        'SECRET_KEY': _lms_jwt_secret,
        'AUDIENCE': os.environ.get('DISCOVERY_LMS_JWT_AUDIENCE', 'py313-local-lms'),
    }]
else:
    # Self-signed fallback (phase 4a behaviour) for a standalone discovery.
    JWT_AUTH['JWT_SECRET_KEY'] = os.environ.get('DISCOVERY_JWT_SECRET_KEY', 'discovery-py313-jwt-secret-key')
# drf-jwt's default header prefix changed from 'JWT' to 'Bearer' in the fork that
# edx-drf-extensions 10.6.0 pins. The platform still signs/sends with 'JWT'
# (SuppliedJwtAuth -> 'JWT {token}'), so restore the prefix here.
JWT_AUTH['JWT_AUTH_HEADER_PREFIX'] = 'JWT'

# Courses API: discovery fetches course metadata from the platform LMS via OAuth2
# client-credentials. OIDC_KEY/OIDC_SECRET are the DOT application credentials
# registered in the LMS (see the phase 6a local integration). Dev defaults match
# that registration; override via env for staging/production.
COURSES_API = {
    'URL': '/api/courses/v1/',
    'OIDC_URL_ROOT': '/oauth2',
    'OIDC_KEY': os.environ.get('DISCOVERY_OIDC_KEY', 'lH8u2KmAwOP1CIUYAtCxQkp3jig86xKgbKrkOp3u'),
    'OIDC_SECRET': os.environ.get('DISCOVERY_OIDC_SECRET', 'discovery-secret'),
    'IS_SECURE': False,
}

# Avoid the deleted haystack signal processor still referenced by shared/test.py.
HAYSTACK_SIGNAL_PROCESSOR = None

# Sites: disable the cached-site fast path in local dev (matches test.py).
SITE_CACHE_TTL = 0

# The dev DB seeds Site id=1 as discovery-py3.local (see the phase-4a seed step).
SITE_ID = int(os.environ.get('SITE_ID', 1))
