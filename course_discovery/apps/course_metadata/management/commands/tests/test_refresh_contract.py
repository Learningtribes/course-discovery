"""Contract test (phase 5 S5.4): `refresh_course_metadata` real side effects.

Unlike the unit tests in `test_refresh_course_metadata.py` (which patch
`execute_loader` and only assert the call shape), this exercises the real ingest
path: the command acquires a token, hits the mocked LMS Courses API, and persists
`Course` / `CourseRun` rows with the correct org — the contract the platform's
`refresh_course_metadata` cron relies on.
"""
import jwt
import mock
import responses
from django.contrib.sites.models import Site
from django.core.management import call_command
from django.test import TransactionTestCase, override_settings

from course_discovery.apps.core.tests.factories import PartnerFactory
from course_discovery.apps.core.tests.utils import mock_api_callback
from course_discovery.apps.course_metadata.data_loaders.tests import mock_data
from course_discovery.apps.course_metadata.models import Course, CourseRun
from course_discovery.apps.course_metadata.tests import toggle_switch


JSON = 'application/json'
ACCESS_TOKEN = jwt.encode({'preferred_username': 'bob'}, 'secret')


class RefreshCourseMetadataIngestContractTests(TransactionTestCase):
    """The command must pull course metadata from LMS and persist it."""

    def setUp(self):
        super().setUp()
        self.courses_api_cfg = {
            'URL': '/api/courses/v1/',
            'OIDC_URL_ROOT': '/oauth2',
            'OIDC_KEY': 'test-oidc-key',
            'OIDC_SECRET': 'test-oidc-secret',
            'IS_SECURE': False,
        }
        self.override = override_settings(COURSES_API=self.courses_api_cfg)
        self.override.enable()
        self.addCleanup(self.override.disable)

        # Global waffle switches leak between tests; keep the serial path deterministic.
        toggle_switch('threaded_metadata_write', False)
        toggle_switch('parallel_refresh_pipeline', False)

        Site.objects.all().delete()
        self.site = Site.objects.create(domain='test-lms.example.com', name='test-lms')
        self.partner = PartnerFactory(site=self.site)

        self.courses_api_url = 'http://{}{}'.format(self.site.domain, self.courses_api_cfg['URL'])

    @responses.activate
    def test_ingest_persists_courses_and_runs_with_org(self):
        bodies = mock_data.COURSES_API_BODIES
        url = self.courses_api_url + 'courses/'

        responses.add_callback(
            responses.GET,
            url,
            callback=mock_api_callback(url, bodies, pagination=True),
            content_type=JSON
        )

        with mock.patch('course_discovery.apps.course_metadata.management.commands.'
                        'refresh_course_metadata.get_oauth_access_token',
                        return_value=(ACCESS_TOKEN, None)):
            call_command('refresh_course_metadata')

        self.assertEqual(Course.objects.count(), len(bodies))
        self.assertEqual(CourseRun.objects.count(), len(bodies))
        self.assertEqual(
            set(Course.objects.values_list('org', flat=True)),
            {'MITx', 'KyotoUx'}
        )
