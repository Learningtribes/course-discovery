from course_discovery.settings.base import *
from course_discovery.settings.shared.test import *


ALLOWED_HOSTS = ['*']

DEFAULT_PARTNER_ID = 1

TEST_NON_SERIALIZED_APPS = [
    # Prevents the issue described at https://code.djangoproject.com/ticket/23727.
    'django.contrib.contenttypes',
    # Because of the bug linked above, loading serialized data for this app in a
    # TransactionTestCase with serialized_rollback=True will cause IntegrityErrors
    # on databases that check foreign key constraints (e.g., MySQL, not SQLite).
    # The app's models contain foreign keys referencing content types that no longer
    # exist when serialized data is loaded. This is a variant of the issue described
    # at https://code.djangoproject.com/ticket/10827.
    'django.contrib.auth',
]

CACHES = {
    'default': {
        'BACKEND': os.environ.get('CACHE_BACKEND', 'django.core.cache.backends.locmem.LocMemCache'),
        'LOCATION': os.environ.get('CACHE_LOCATION', ''),
    }
}

DATABASES = {
    'default': {
        'ENGINE': os.environ.get('DB_ENGINE', 'django.db.backends.sqlite3'),
        'NAME': os.environ.get('DB_NAME', ':memory:'),
        'USER': os.environ.get('DB_USER', ''),
        'PASSWORD': os.environ.get('DB_PASSWORD', ''),
        'HOST': os.environ.get('DB_HOST', ''),
        'PORT': os.environ.get('DB_PORT', ''),
        'CONN_MAX_AGE': int(os.environ.get('CONN_MAX_AGE', 0)),
        # Django's runner otherwise creates `test_<NAME>`, a name the application user is not
        # granted. DB_TEST_NAME names the database the deploy grants instead, so a MySQL run
        # never needs global CREATE. Mirrors the platform's BRINGUP_TEST_DATABASE_NAME.
        **({'TEST': {'NAME': os.environ['DB_TEST_NAME']}} if os.environ.get('DB_TEST_NAME') else {}),
    },
}

JWT_AUTH['JWT_SECRET_KEY'] = 'course-discovery-jwt-secret-key'
# drf-jwt 1.19.2 (via edx-drf-extensions) flipped the default from 'JWT' to
# 'Bearer'. The platform still sends 'JWT {token}' (SuppliedJwtAuth), so keep the
# test environment aligned with production (matches settings/py313.py).
JWT_AUTH['JWT_AUTH_HEADER_PREFIX'] = 'JWT'

LOGGING['handlers']['local'] = {'class': 'logging.NullHandler'}

PUBLISHER_FROM_EMAIL = 'test@example.com'

# Set to 0 to disable edx-django-sites-extensions to retrieve
# the site from cache and risk working with outdated information.
SITE_CACHE_TTL = 0
