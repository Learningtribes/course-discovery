import ddt
import jwt
import mock
import responses
from django.contrib.sites.models import Site
from django.core.management import CommandError, call_command
from django.test import TransactionTestCase, override_settings

from course_discovery.apps.core.tests.factories import PartnerFactory
from course_discovery.apps.core.tests.utils import mock_api_callback
from course_discovery.apps.course_metadata.data_loaders.api import (
    CoursesApiDataLoader
)
from course_discovery.apps.course_metadata.data_loaders.tests import mock_data
from course_discovery.apps.course_metadata.management.commands.refresh_course_metadata import execute_parallel_loader
from course_discovery.apps.course_metadata.tests import toggle_switch
from course_discovery.apps.course_metadata.tests.factories import CourseFactory


JSON = 'application/json'
ACCESS_TOKEN = jwt.encode({'preferred_username': 'bob'}, 'secret')


@ddt.ddt
class RefreshCourseMetadataCommandTests(TransactionTestCase):
    def setUp(self):
        super(RefreshCourseMetadataCommandTests, self).setUp()
        # The fork (commit 5a28aad0) rewrote refresh_course_metadata to read the Courses API
        # config from settings.COURSES_API (a dict) and build the URL from the site domain,
        # replacing the old Partner-driven flow. Provide that config here.
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

        # Waffle switches are global state and leak across tests (the parallel test
        # toggles them on); reset to the default (off) so each test starts clean.
        toggle_switch('threaded_metadata_write', False)
        toggle_switch('parallel_refresh_pipeline', False)

        # The command iterates over Site.objects.all() and uses the first domain that
        # yields an access token. Control the Site set so the URL is deterministic.
        Site.objects.all().delete()
        self.site = Site.objects.create(domain='test-lms.example.com', name='test-lms')
        self.partner = PartnerFactory(site=self.site)

        self.courses_api_url = 'http://{}{}'.format(self.site.domain, self.courses_api_cfg['URL'])
        self.pipeline = [
            (CoursesApiDataLoader, self.courses_api_url, None),
        ]
        self.kwargs = {'username': 'bob'}

    def mock_lms_courses_api(self):
        bodies = mock_data.COURSES_API_BODIES
        url = self.courses_api_url + 'courses/'
        responses.add_callback(
            responses.GET,
            url,
            callback=mock_api_callback(url, bodies, pagination=True),
            content_type=JSON
        )
        return bodies

    @mock.patch('course_discovery.apps.api.cache.set_api_timestamp')
    @mock.patch('course_discovery.apps.course_metadata.management.commands.refresh_course_metadata.set_api_timestamp')
    def test_refresh_course_metadata_serial(self, mock_set_api_timestamp, mock_receiver):
        with responses.RequestsMock() as rsps:
            self.mock_lms_courses_api()

            with mock.patch('course_discovery.apps.course_metadata.management.commands.'
                            'refresh_course_metadata.get_oauth_access_token',
                            return_value=(ACCESS_TOKEN, None)):
                with mock.patch('course_discovery.apps.course_metadata.management.commands.'
                                'refresh_course_metadata.execute_loader') as mock_executor:
                    call_command('refresh_course_metadata')

                    # Set up expected calls
                    expected_calls = [mock.call(loader_class, self.courses_api_cfg, api_url,
                                                ACCESS_TOKEN, 'JWT', max_workers or 7, False,
                                                modified_x_min_ago=None, **self.kwargs)
                                      for loader_class, api_url, max_workers in self.pipeline]
                    mock_executor.assert_has_calls(expected_calls)

        # Verify that the API cache is invalidated once, and that it isn't
        # being done by the signal receiver.
        assert mock_set_api_timestamp.call_count == 1
        assert not mock_receiver.called

    @mock.patch('course_discovery.apps.api.cache.set_api_timestamp')
    @mock.patch('course_discovery.apps.course_metadata.management.commands.refresh_course_metadata.set_api_timestamp')
    def test_refresh_course_metadata_parallel(self, mock_set_api_timestamp, mock_receiver):
        for name in ['threaded_metadata_write', 'parallel_refresh_pipeline']:
            toggle_switch(name)

        with responses.RequestsMock() as rsps:
            self.mock_lms_courses_api()

            # Courses must exist for the command to use multiple threads. If there are no
            # courses, the command won't risk race conditions between threads trying to
            # create the same course.
            CourseFactory(org='test-org')
            with mock.patch('course_discovery.apps.course_metadata.management.commands.'
                            'refresh_course_metadata.get_oauth_access_token',
                            return_value=(ACCESS_TOKEN, None)):
                with mock.patch('concurrent.futures.ProcessPoolExecutor.submit') as mock_executor:
                    call_command('refresh_course_metadata')

                    # Set up expected calls
                    expected_calls = [mock.call(execute_parallel_loader, loader_class,
                                                self.courses_api_cfg, api_url, ACCESS_TOKEN,
                                                'JWT', max_workers or 7, True,
                                                modified_x_min_ago=None, **self.kwargs)
                                      for loader_class, api_url, max_workers in self.pipeline]
                    mock_executor.assert_has_calls(expected_calls, any_order=True)

        # Verify that the API cache is invalidated once, and that it isn't
        # being done by the signal receiver.
        assert mock_set_api_timestamp.call_count == 1
        assert not mock_receiver.called

    def test_refresh_course_metadata_with_invalid_partner_code(self):
        """ Verify an error is raised if an invalid partner code is passed on the command line. """
        with self.assertRaises(CommandError):
            command_args = ['--partner_code=invalid']
            call_command('refresh_course_metadata', *command_args)

    def test_refresh_course_metadata_errors_with_no_token(self):
        """ Verify an error is raised if an access token is not acquired. """
        logger = 'course_discovery.apps.course_metadata.management.commands.refresh_course_metadata.logger'
        with mock.patch('course_discovery.apps.course_metadata.management.commands.'
                        'refresh_course_metadata.get_oauth_access_token', side_effect=Exception):
            with mock.patch(logger) as mock_logger:
                with self.assertRaisesMessage(Exception, 'Failed to get access token !'):
                    call_command('refresh_course_metadata')
        self.assertTrue(mock_logger.warning.called)

    def test_refresh_course_metadata_with_loader_exception(self):
        """ Verify execution continues if an individual data loader fails. """
        with responses.RequestsMock() as rsps:
            # The courses API is intentionally left unmocked so the loader fails during ingest.
            logger_target = 'course_discovery.apps.course_metadata.management.commands.refresh_course_metadata.logger'
            with mock.patch('course_discovery.apps.course_metadata.management.commands.'
                            'refresh_course_metadata.get_oauth_access_token',
                            return_value=(ACCESS_TOKEN, None)):
                with mock.patch(logger_target) as mock_logger:
                    call_command('refresh_course_metadata')

                    loader_classes = (
                        CoursesApiDataLoader,
                    )
                    expected_calls = [mock.call('%s failed!', loader_class.__name__) for loader_class in loader_classes]
                    mock_logger.exception.assert_has_calls(expected_calls)
