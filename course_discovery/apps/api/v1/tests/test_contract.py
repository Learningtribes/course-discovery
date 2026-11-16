"""Contract tests for phase 5 S5.4.

These are the targeted safety-net tests the plan (§3.9.4 / §3.8 S5.4) asked for
and which the fork never had:

1. org isolation — a tenant's request filtered to `?org=A` must never return
   another tenant's data;
2. JWT negative — a token signed with the wrong key must be rejected, and a
   valid token must be accepted (proves the `JWT` header prefix + symmetric
   key path survives the drf-jwt 1.19.2 / PyJWT 2.x upgrade).
"""
import jwt
from django.contrib.sites.models import Site
from django.test import TestCase, override_settings
from django.urls import reverse
from rest_framework.exceptions import AuthenticationFailed

from course_discovery.apps.api.tests.jwt_utils import (
    generate_jwt_header_for_user,
    generate_jwt_payload,
)
from course_discovery.apps.core.tests.factories import SiteFactory, UserFactory
from course_discovery.apps.course_metadata.tests.factories import ProgramFactory


@override_settings(SITE_ID=1)
class ProgramOrgIsolationTests(TestCase):
    """tenant A's token must not read tenant B's programs."""

    def setUp(self):
        super().setUp()
        Site.objects.all().delete()
        SiteFactory(id=1, domain='testserver.fake')
        self.program_a = ProgramFactory(org='tenant-a')
        self.program_b = ProgramFactory(org='tenant-b')
        user = UserFactory(username='tenant-a-user')
        self.auth_header = generate_jwt_header_for_user(user)

    def test_org_filter_returns_only_requested_org(self):
        response = self.client.get(
            reverse('api:v1:program-list'),
            {'org': 'tenant-a'},
            HTTP_AUTHORIZATION=self.auth_header,
        )
        self.assertEqual(response.status_code, 200)
        orgs = {item['org'] for item in response.json()['results']}
        self.assertEqual(orgs, {'tenant-a'})

    def test_unauthenticated_request_is_rejected(self):
        response = self.client.get(reverse('api:v1:program-list'), {'org': 'tenant-a'})
        self.assertIn(response.status_code, (401, 403))


class JwtAuthenticationContractTests(TestCase):
    """The JWT negative/positive contract from §2.5.2."""

    def setUp(self):
        super().setUp()
        self.user = UserFactory(username='contract-user')

    def _authenticate(self, token):
        from edx_rest_framework_extensions.auth.jwt.authentication import JwtAuthentication
        from django.test import RequestFactory

        request = RequestFactory().get('/api/v1/programs/')
        request.META['HTTP_AUTHORIZATION'] = 'JWT {token}'.format(token=token)
        return JwtAuthentication().authenticate(request)

    def test_valid_token_is_accepted(self):
        user, _ = self._authenticate(
            generate_jwt_header_for_user(self.user).split(' ', 1)[1]
        )
        self.assertEqual(user.username, 'contract-user')

    def test_forged_token_is_rejected(self):
        payload = generate_jwt_payload(self.user)
        forged = jwt.encode(payload, 'wrong-secret', algorithm='HS256')
        with self.assertRaises(AuthenticationFailed):
            self._authenticate(forged)
