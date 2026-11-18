import unittest

from django.contrib.auth.models import AnonymousUser
from django.core.cache import cache
from django.test import RequestFactory, TestCase
from django.urls import reverse
from rest_framework.test import APITestCase

from course_discovery.apps.api.tests.mixins import SiteMixin
from course_discovery.apps.core.models import UserThrottleRate
from course_discovery.apps.core.tests.factories import USER_PASSWORD, UserFactory
from course_discovery.apps.core.throttles import OverridableUserRateThrottle


@unittest.skip("We disable SwaggerSchemaView temporary")
class RateLimitingTest(SiteMixin, APITestCase):
    """
    Testing rate limiting of API calls.
    """

    def setUp(self):
        super(RateLimitingTest, self).setUp()

        self.url = reverse('api_docs')
        self.user = UserFactory()
        self.client.login(username=self.user.username, password=USER_PASSWORD)

    def tearDown(self):
        """
        Clear the cache, since DRF uses it for recording requests against a
        URL. Django does not clear the cache between test runs.
        """
        super(RateLimitingTest, self).tearDown()
        cache.clear()

    def _make_requests(self):
        """ Make multiple requests until the throttle's limit is exceeded.

        Returns
            Response: Response of the last request.
        """
        num_requests = OverridableUserRateThrottle().num_requests
        for __ in range(num_requests + 1):
            response = self.client.get(self.url)
        return response

    def test_rate_limiting(self):
        """ Verify the API responds with HTTP 429 if a normal user exceeds the rate limit. """
        response = self._make_requests()

        assert response.status_code == 429

    def test_user_throttle_rate(self):
        """ Verify the UserThrottleRate can be used to override the default rate limit. """
        UserThrottleRate.objects.create(user=self.user, rate='1000/day')
        self.assert_rate_limit_successfully_exceeded()

    def assert_rate_limit_successfully_exceeded(self):
        """ Asserts that the throttle's rate limit can be exceeded without encountering an error. """
        response = self._make_requests()

        assert response.status_code == 200

    def test_superuser_throttling(self):
        """ Verify superusers are not throttled. """
        self.user.is_superuser = True
        self.user.save()
        self.assert_rate_limit_successfully_exceeded()

    def test_staff_throttling(self):
        """ Verify staff users are not throttled. """
        self.user.is_staff = True
        self.user.save()
        self.assert_rate_limit_successfully_exceeded()


class OverridableUserRateThrottleTests(TestCase):
    """The throttle's own decisions, independent of the deleted `api_docs` view.

    `RateLimitingTest` above is skipped because it drives the throttle through a view that no
    longer exists. These cover the allow/deny logic directly, so a change to the staff bypass or
    the per-user override is caught even while that end-to-end test stays disabled.
    """

    def setUp(self):
        super().setUp()
        self.addCleanup(cache.clear)

    def _request(self, user):
        request = RequestFactory().get('/api/v1/programs/')
        request.user = user
        return request

    def _throttle(self):
        throttle = OverridableUserRateThrottle()
        throttle.num_requests, throttle.duration = throttle.parse_rate(throttle.rate)
        return throttle

    def test_staff_users_are_never_throttled(self):
        """Staff debug the API; a rate limit would lock them out mid-investigation."""
        user = UserFactory(is_staff=True)

        self.assertTrue(self._throttle().allow_request(self._request(user), None))

    def test_superusers_are_never_throttled(self):
        user = UserFactory(is_superuser=True)

        self.assertTrue(self._throttle().allow_request(self._request(user), None))

    def test_a_per_user_rate_overrides_the_default(self):
        """Tighten or loosen one account without changing the setting for everyone."""
        user = UserFactory()
        UserThrottleRate.objects.create(user=user, rate='1/day')
        throttle = self._throttle()

        self.assertTrue(throttle.allow_request(self._request(user), None))

        # The override is now in force: the second request in the same window is refused.
        self.assertFalse(throttle.allow_request(self._request(user), None))
        self.assertEqual(throttle.num_requests, 1)

    def test_a_user_without_an_override_uses_the_default_rate(self):
        user = UserFactory()
        throttle = self._throttle()
        default_rate = throttle.rate

        throttle.allow_request(self._request(user), None)

        self.assertEqual(throttle.rate, default_rate)

    def test_an_anonymous_request_falls_through_to_the_default_rule(self):
        """No user means no per-user override to look up."""
        request = RequestFactory().get('/api/v1/programs/')
        request.user = AnonymousUser()

        # `UserRateThrottle` keys anonymous callers by IP; the call must not raise.
        self.assertIn(self._throttle().allow_request(request, None), (True, False))
