from django.conf import settings
from django.test import TestCase
from social_django.utils import load_strategy

from auth_backends.backends import EdXOAuth2


class AuthBackendSettingsTests(TestCase):
    def test_the_configured_backend_reads_the_keys_defined_in_settings(self):
        """`EdXOAuth2` is named `edx-oauth2`, so it resolves `SOCIAL_AUTH_EDX_OAUTH2_*`, not the OIDC names."""
        backend = EdXOAuth2(load_strategy())
        self.assertIn('auth_backends.backends.EdXOAuth2', settings.AUTHENTICATION_BACKENDS)
        for name in ('KEY', 'SECRET', 'URL_ROOT'):
            self.assertEqual(backend.setting(name), getattr(settings, 'SOCIAL_AUTH_EDX_OAUTH2_' + name))

    def test_no_setting_is_left_to_the_removed_openid_connect_backend(self):
        stale = sorted(name for name in dir(settings) if name.startswith('SOCIAL_AUTH_EDX_OIDC_'))
        self.assertEqual(stale, [])
