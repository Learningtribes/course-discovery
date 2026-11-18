"""Behaviour tests for the single-course refresh endpoint the LMS calls.

`POST /api/v1/refresh_course_metadata/` is the LMS's "a course just changed" hook:
the LMS POSTs `{"course_id": ...}` and discovery pulls that one course with the
OAuth2 client-credentials grant. It had no test at all, so neither the rejection
path nor the token/username handling was pinned.
"""
import json
from unittest import mock

from django.contrib.sites.models import Site
from django.test import TestCase, override_settings

from course_discovery.apps.core.tests.factories import SiteFactory

TEST_DOMAIN = 'testserver.fake'
REFRESHER_PATH = '/api/v1/refresh_course_metadata/'
COURSES_API_SETTINGS = {
    'URL': '/api/courses/v1/',
    'OIDC_URL_ROOT': '/oauth2',
    'OIDC_KEY': 'test-client-id',
    'OIDC_SECRET': 'test-client-secret',
    'IS_SECURE': False,
}


@override_settings(SITE_ID=1, COURSES_API=COURSES_API_SETTINGS)
class CourseMetadataRefresherTests(TestCase):
    def setUp(self):
        super().setUp()
        Site.objects.all().delete()
        self.site = SiteFactory(id=1, domain=TEST_DOMAIN)

    def post(self, body):
        return self.client.post(
            REFRESHER_PATH, data=json.dumps(body), content_type='application/json'
        )

    def test_missing_course_id_is_rejected(self):
        """Without a key the loader has nothing to fetch; the endpoint must say so."""
        response = self.post({})

        self.assertEqual(response.status_code, 503)
        self.assertIn('Invalid Course Key', response.json()['error'])

    def test_ingest_is_called_with_the_run_lms_and_a_jwt_token(self):
        """The URL, the credentials and the token type all come from `COURSES_API`."""
        with mock.patch(
            'course_discovery.apps.course_metadata.views.get_oauth_access_token',
            return_value=('a-jwt-token', None),
        ), mock.patch(
            'course_discovery.apps.course_metadata.views.jwt.decode',
            return_value={'preferred_username': 'lms_catalog_service_user'},
        ) as decode, mock.patch(
            'course_discovery.apps.course_metadata.views.CoursesApiDataLoader'
        ) as loader:
            response = self.post({'course_id': 'course-v1:edX+DemoX+2026'})

        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()['course_key'], 'course-v1:edX+DemoX+2026')
        loader.assert_called_once_with(
            course_key='course-v1:edX+DemoX+2026',
            courses_api_cfg=COURSES_API_SETTINGS,
            api_url='http://testserver.fake/api/courses/v1/',
            access_token='a-jwt-token',
            token_type='JWT',
            max_workers=1,
            is_threadsafe=True,
            username='lms_catalog_service_user',
        )
        loader.return_value.ingest.assert_called_once_with()
        # The username is read without verification: the token was just issued by this exchange.
        self.assertFalse(decode.call_args.kwargs['options']['verify_signature'])

    def test_an_empty_username_is_omitted_from_the_loader_arguments(self):
        """`if username:` means an empty claim is dropped rather than passed through."""
        with mock.patch(
            'course_discovery.apps.course_metadata.views.get_oauth_access_token',
            return_value=('a-jwt-token', None),
        ), mock.patch(
            'course_discovery.apps.course_metadata.views.jwt.decode',
            return_value={'preferred_username': ''},
        ), mock.patch(
            'course_discovery.apps.course_metadata.views.CoursesApiDataLoader'
        ) as loader:
            response = self.post({'course_id': 'course-v1:edX+DemoX+2026'})

        self.assertEqual(response.status_code, 200, response.content)
        self.assertNotIn('username', loader.call_args.kwargs)

    def test_a_payload_without_the_username_claim_is_reported_as_an_error(self):
        """Records the current behaviour: the claim is read with `[...]`, not `.get()`.

        The `if username:` guard reads as if an absent claim were tolerated, but a token whose
        payload omits the key raises `KeyError`, so the sync is reported as failed instead of
        proceeding anonymously. Pinned here so the discrepancy is visible; see the note in the
        pull request rather than changing behaviour under a test-only commit.
        """
        with mock.patch(
            'course_discovery.apps.course_metadata.views.get_oauth_access_token',
            return_value=('a-jwt-token', None),
        ), mock.patch(
            'course_discovery.apps.course_metadata.views.jwt.decode', return_value={}
        ), mock.patch(
            'course_discovery.apps.course_metadata.views.CoursesApiDataLoader'
        ) as loader:
            response = self.post({'course_id': 'course-v1:edX+DemoX+2026'})

        self.assertEqual(response.status_code, 200, response.content)
        self.assertIn('preferred_username', response.json()['errors'][0])
        loader.assert_not_called()

    def test_loader_failure_is_reported_without_a_500(self):
        """The LMS retries on error; a broken course must not make the hook itself crash."""
        with mock.patch(
            'course_discovery.apps.course_metadata.views.get_oauth_access_token',
            return_value=('a-jwt-token', None),
        ), mock.patch(
            'course_discovery.apps.course_metadata.views.jwt.decode',
            return_value={'preferred_username': 'u'},
        ), mock.patch(
            'course_discovery.apps.course_metadata.views.CoursesApiDataLoader'
        ) as loader:
            loader.return_value.ingest.side_effect = RuntimeError('LMS refused the course')

            response = self.post({'course_id': 'course-v1:edX+DemoX+2026'})

        self.assertEqual(response.status_code, 200, response.content)
        errors = response.json()['errors']
        self.assertEqual(len(errors), 1)
        self.assertIn('course-v1:edX+DemoX+2026', errors[0])
        self.assertIn('LMS refused the course', errors[0])

    def test_secure_scheme_follows_the_setting(self):
        """`IS_SECURE` decides https; a self-signed local LMS needs http."""
        secure = dict(COURSES_API_SETTINGS, IS_SECURE=True)
        with override_settings(COURSES_API=secure), mock.patch(
            'course_discovery.apps.course_metadata.views.get_oauth_access_token',
            return_value=('a-jwt-token', None),
        ), mock.patch(
            'course_discovery.apps.course_metadata.views.jwt.decode',
            return_value={'preferred_username': 'u'},
        ), mock.patch(
            'course_discovery.apps.course_metadata.views.CoursesApiDataLoader'
        ) as loader:
            self.post({'course_id': 'course-v1:edX+DemoX+2026'})

        self.assertEqual(loader.call_args.kwargs['api_url'], 'https://testserver.fake/api/courses/v1/')
