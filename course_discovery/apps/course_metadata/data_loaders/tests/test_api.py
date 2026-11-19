import datetime
from urllib.parse import parse_qs, urlparse

import ddt
import mock
import responses
from django.test import TestCase
from edx_rest_api_client.auth import BearerAuth, SuppliedJwtAuth

from course_discovery.apps.core.tests.utils import mock_api_callback
from course_discovery.apps.course_metadata.choices import CourseRunPacing, CourseRunStatus
from course_discovery.apps.course_metadata.data_loaders.api import (
    AbstractDataLoader, CoursesApiDataLoader
)
from course_discovery.apps.course_metadata.data_loaders.tests import JSON, mock_data
from course_discovery.apps.course_metadata.data_loaders.tests.mixins import (
    ACCESS_TOKEN, ACCESS_TOKEN_TYPE, ApiClientTestMixin, DataLoaderTestMixin,
)
from course_discovery.apps.course_metadata.models import (
    Course, CourseRun, Organization
)
from course_discovery.apps.course_metadata.tests.factories import (
    CourseFactory, CourseRunFactory, ImageFactory, VideoFactory
)

LOGGER_PATH = 'course_discovery.apps.course_metadata.data_loaders.api.logger'


class AbstractDataLoaderTest(TestCase):
    def test_clean_string(self):
        """ Verify the method leading and trailing spaces, and returns None for empty strings. """
        # Do nothing for non-string input
        self.assertIsNone(AbstractDataLoader.clean_string(None))
        self.assertEqual(AbstractDataLoader.clean_string(3.14), 3.14)

        # Return None for empty strings
        self.assertIsNone(AbstractDataLoader.clean_string(''))
        self.assertIsNone(AbstractDataLoader.clean_string('    '))
        self.assertIsNone(AbstractDataLoader.clean_string('\t'))

        # Return the stripped value for non-empty strings
        for s in ('\tabc', 'abc', ' abc ', 'abc ', '\tabc\t '):
            self.assertEqual(AbstractDataLoader.clean_string(s), 'abc')

    def test_parse_date(self):
        """ Verify the method properly parses dates. """
        # Do nothing for empty values
        self.assertIsNone(AbstractDataLoader.parse_date(''))
        self.assertIsNone(AbstractDataLoader.parse_date(None))

        # Parse datetime strings
        dt = datetime.datetime.utcnow()
        self.assertEqual(AbstractDataLoader.parse_date(dt.isoformat()), dt)

    def test_delete_orphans(self):
        """ Verify the delete_orphans method deletes orphaned instances. """
        instances = (ImageFactory(), VideoFactory(),)
        AbstractDataLoader.delete_orphans()

        for instance in instances:
            self.assertFalse(instance.__class__.objects.filter(pk=instance.pk).exists())

    def test_clean_html(self):
        """ Verify the method removes unnecessary HTML attributes. """
        data = (
            ('', '',),
            ('<p>Hello!</p>', 'Hello!'),
            ('<em>Testing</em>', '<em>Testing</em>'),
            ('Hello&amp;world&nbsp;!', 'Hello&world!')
        )

        for content, expected in data:
            self.assertEqual(AbstractDataLoader.clean_html(content), expected)


@ddt.ddt
class CoursesApiDataLoaderTests(ApiClientTestMixin, DataLoaderTestMixin, TestCase):
    loader_class = CoursesApiDataLoader

    @property
    def api_url(self):
        return self.courses_api_cfg['URL']

    def mock_api(self, bodies=None):
        if not bodies:
            bodies = mock_data.COURSES_API_BODIES
        url = self.api_url + 'courses/'
        responses.add_callback(
            responses.GET,
            url,
            callback=mock_api_callback(url, bodies, pagination=True),
            content_type=JSON
        )
        return bodies

    def assert_course_run_loaded(self, body, partner_has_marketing_site=True):
        """ Assert a CourseRun corresponding to the specified data body was properly loaded into the database. """

        # Validate the Course
        course_key = '{org}+{key}'.format(org=body['org'], key=body['number'])
        organization = Organization.objects.get(key=body['org'])
        course = Course.objects.get(key=course_key)

        self.assertEqual(course.title, body['name'])
        self.assertListEqual(list(course.authoring_organizations.all()), [organization])

        # Validate the course run
        course_run = course.course_runs.get(key=body['id'])
        expected_values = {
            'title': self.loader.clean_string(body['name']),
            'end': self.loader.parse_date(body['end']),
            'enrollment_start': self.loader.parse_date(body['enrollment_start']),
            'enrollment_end': self.loader.parse_date(body['enrollment_end']),
            'card_image_url': None,
            'title_override': None,
        }

        if not partner_has_marketing_site:
            expected_values.update({
                'start': self.loader.parse_date(body['start']),
                'card_image_url': body['media'].get('image', {}).get('raw'),
                'title_override': body['name'],
                'status': CourseRunStatus.Published,
                'pacing_type': self.loader.get_pacing_type(body),
            })

        for field, value in expected_values.items():
            self.assertEqual(getattr(course_run, field), value, 'Field {} is invalid.'.format(field))

        return course_run

    @responses.activate
    @ddt.data(True, False)
    def test_ingest(self, partner_has_marketing_site):
        """ Verify the method ingests data from the Courses API. """
        api_data = self.mock_api()
        if not partner_has_marketing_site:
            self.partner.marketing_site_url_root = None
            self.partner.save()

        self.assertEqual(Course.objects.count(), 0)
        self.assertEqual(CourseRun.objects.count(), 0)

        self.loader.ingest()

        # Verify the API was called with the correct authorization header
        self.assert_api_called(1)

        # Verify the CourseRuns were created correctly
        expected_num_course_runs = len(api_data)
        self.assertEqual(CourseRun.objects.count(), expected_num_course_runs)

    @responses.activate
    def test_ingest_exception_handling(self):
        """ Verify the data loader properly handles exceptions during processing of the data from the API. """
        api_data = self.mock_api()

        with mock.patch.object(self.loader, 'clean_strings', side_effect=Exception):
            with mock.patch(LOGGER_PATH) as mock_logger:
                self.loader.ingest()
                self.assertEqual(mock_logger.exception.call_count, len(api_data))
                msg = 'An error occurred while updating {0} from {1}'.format(
                    api_data[-1]['id'],
                    self.partner.courses_api_url
                )
                mock_logger.exception.assert_called_with(msg)


class ApiClientTokenTypeTests(DataLoaderTestMixin, TestCase):
    """`COURSES_API['TOKEN_TYPE']` decides which header the LMS sees.

    Both token types authenticate; the pair has to match. A JWT is sent under `JWT` and an
    opaque token under `Bearer`, and the LMS rejects the cross combinations, so the token type
    must reach the client exactly as configured rather than being guessed here.
    """

    loader_class = CoursesApiDataLoader

    @property
    def api_url(self):
        return self.courses_api_cfg['URL']

    def _client(self, token_type):
        loader = self.loader_class(self.courses_api_cfg, self.api_url, ACCESS_TOKEN, token_type)
        return loader.api_client

    def test_a_jwt_token_type_sends_a_jwt_header(self):
        """`JWT` is this fork's default and the type production runs."""
        client = self._client('JWT')

        self.assertIsInstance(client._store['session'].auth, SuppliedJwtAuth)  # pylint: disable=protected-access

    def test_a_bearer_token_type_sends_a_bearer_header(self):
        """The `DISCOVERY_COURSES_API_TOKEN_TYPE` override, for exercising the opaque path."""
        client = self._client('Bearer')

        auth = client._store['session'].auth  # pylint: disable=protected-access
        self.assertIsInstance(auth, BearerAuth)


@ddt.ddt
class CoursesApiDataLoaderRequestShapeTests(ApiClientTestMixin, DataLoaderTestMixin, TestCase):
    """`_make_request` picks one of three query shapes; each drives a different LMS response.

    All of them are load-bearing: the incremental shape is what a frequent refresh uses,
    the target-key shape is what the LMS's single-course hook uses, and the all-courses
    shape is the nightly full sync that also prunes.
    """

    loader_class = CoursesApiDataLoader

    @property
    def api_url(self):
        return self.courses_api_cfg['URL']

    def _build(self, **kwargs):
        return self.loader_class(
            self.courses_api_cfg, self.api_url, ACCESS_TOKEN, ACCESS_TOKEN_TYPE, **kwargs
        )

    def _mock_one_page(self):
        url = self.api_url + 'courses/'
        responses.add_callback(
            responses.GET, url,
            callback=mock_api_callback(url, mock_data.COURSES_API_BODIES, pagination=True),
            content_type=JSON,
        )
        return url

    @responses.activate
    def test_full_sync_asks_for_every_org(self):
        """The nightly refresh must not be scoped to one org."""
        url = self._mock_one_page()

        self.loader.ingest()

        query = parse_qs(urlparse(responses.calls[0].request.url).query)
        self.assertEqual(query['org'], ['*'])
        self.assertNotIn('id', query)

    @responses.activate
    def test_an_incremental_window_is_forwarded_to_the_lms(self):
        """A frequent refresh asks only for recently modified courses."""
        url = self._mock_one_page()
        loader = self._build(modified_x_min_ago=60)

        loader.ingest()

        query = parse_qs(urlparse(responses.calls[0].request.url).query)
        self.assertEqual(query['modified_in_minutes'], ['60'])
        self.assertEqual(query['org'], ['*'])

    @responses.activate
    def test_a_target_course_key_asks_for_that_course_only(self):
        """The LMS's single-course hook must not trigger a full sync."""
        url = self._mock_one_page()
        target = mock_data.COURSES_API_BODIES[0]['id']
        loader = self._build(course_key=target)

        loader.ingest()

        query = parse_qs(urlparse(responses.calls[0].request.url).query)
        self.assertEqual(query['id'], [target])
        self.assertNotIn('org', query)

    @responses.activate
    def test_a_target_course_key_is_never_treated_as_a_full_sync(self):
        """Pruning on a single-course refresh would delete every other course."""
        self._mock_one_page()
        target = mock_data.COURSES_API_BODIES[0]['id']
        loader = self._build(course_key=target)

        self.assertFalse(loader.is_loading_all_courses)

    @responses.activate
    def test_an_incremental_window_is_never_treated_as_a_full_sync(self):
        """An incremental response holds too few keys for a prune to be safe."""
        loader = self._build(modified_x_min_ago=60)

        self.assertFalse(loader.is_loading_all_courses)


@ddt.ddt
class CoursesApiDataLoaderExistingRecordTests(ApiClientTestMixin, DataLoaderTestMixin, TestCase):
    """Re-ingesting a course that already exists must update it, not duplicate it."""

    loader_class = CoursesApiDataLoader

    @property
    def api_url(self):
        return self.courses_api_cfg['URL']

    def mock_api(self):
        url = self.api_url + 'courses/'
        responses.add_callback(
            responses.GET, url,
            callback=mock_api_callback(url, mock_data.COURSES_API_BODIES, pagination=True),
            content_type=JSON,
        )

    @responses.activate
    def test_ingesting_twice_updates_instead_of_duplicating(self):
        """The nightly job runs every day over the same catalogue."""
        self.mock_api()

        self.loader.ingest()
        courses, runs = Course.objects.count(), CourseRun.objects.count()

        self.loader.ingest()

        self.assertEqual(Course.objects.count(), courses)
        self.assertEqual(CourseRun.objects.count(), runs)

    @responses.activate
    def test_an_existing_course_run_gets_the_new_dates(self):
        """Courses move between runs; the update path has to carry the new window."""
        self.mock_api()
        self.loader.ingest()
        body = mock_data.COURSES_API_BODIES[0]
        course_run = CourseRun.objects.get(key=body['id'])
        course_run.end = None
        course_run.save()

        self.loader.ingest()

        course_run.refresh_from_db()
        self.assertEqual(course_run.end, self.loader.parse_date(body['end']))

    @responses.activate
    def test_the_canonical_course_is_updated_when_its_run_is(self):
        """The course row carries the title; it must follow the run it is canonical for."""
        self.mock_api()
        self.loader.ingest()
        body = mock_data.COURSES_API_BODIES[0]
        course_run = CourseRun.objects.get(key=body['id'])
        course = Course.objects.get(key=course_run.course.key)
        course.canonical_course_run = course_run
        course.title = 'Stale Title'
        course.save()

        self.loader.ingest()

        course.refresh_from_db()
        self.assertEqual(course.title, self.loader.clean_string(body['name']))


class CoursesApiDataLoaderPruningTests(DataLoaderTestMixin, TestCase):
    """`delete_expired_courses` removes what the LMS no longer reports — but only on a full sync."""

    loader_class = CoursesApiDataLoader

    @property
    def api_url(self):
        return self.courses_api_cfg['URL']

    def _loader_with(self, loaded_keys, course_count):
        loader = self.loader
        loader.loaded_course_keys = set(loaded_keys)
        loader.course_count = course_count
        return loader

    def _course_run(self, key):
        return CourseRunFactory(key=key, course=CourseFactory(key=key))

    def test_a_course_the_lms_dropped_is_deleted(self):
        gone = self._course_run('course-v1:edX+Gone+2026')
        kept = self._course_run('course-v1:edX+Kept+2026')
        loader = self._loader_with(['course-v1:edX+Kept+2026'], 1)

        loader.delete_expired_courses()

        self.assertFalse(CourseRun.objects.filter(pk=gone.pk).exists())
        self.assertTrue(CourseRun.objects.filter(pk=kept.pk).exists())

    def test_a_matching_key_count_keeps_everything(self):
        """No key is missing, so nothing may be pruned."""
        kept = self._course_run('course-v1:edX+Kept+2026')
        loader = self._loader_with(['course-v1:edX+Kept+2026'], 1)

        loader.delete_expired_courses()

        self.assertTrue(CourseRun.objects.filter(pk=kept.pk).exists())

    def test_a_partial_load_prunes_nothing_and_logs_the_mismatch(self):
        """A short page must never be read as 'the LMS dropped these courses'."""
        kept = self._course_run('course-v1:edX+Kept+2026')
        # The LMS reports 3 courses but only 1 key was seen: an incomplete load.
        loader = self._loader_with(['course-v1:edX+Kept+2026'], 3)

        with mock.patch(LOGGER_PATH) as mock_logger:
            loader.delete_expired_courses()

        self.assertTrue(CourseRun.objects.filter(pk=kept.pk).exists())
        message = mock_logger.error.call_args.args[0]
        self.assertIn('Integrity Error', message)

    def test_an_incremental_load_prunes_nothing(self):
        """An incremental window only returns changed courses; the rest would look deleted."""
        kept = self._course_run('course-v1:edX+Kept+2026')
        loader = self._loader_with([], 0)
        loader.modified_x_min_ago = 60

        loader.delete_expired_courses()

        self.assertTrue(CourseRun.objects.filter(pk=kept.pk).exists())
