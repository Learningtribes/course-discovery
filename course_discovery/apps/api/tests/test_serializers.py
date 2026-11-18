# pylint: disable=no-member,test-inherits-tests
import datetime

from django.core.exceptions import ValidationError
from django.test import TestCase
from pytz import UTC
from rest_framework.test import APIRequestFactory

from course_discovery.apps.api.fields import StdImageSerializerField
from course_discovery.apps.api.serializers import (
    CourseRunSerializer, CourseSerializer,
    MinimalCourseRunSerializer, MinimalCourseSerializer,
    MinimalProgramCourseSerializer, MinimalProgramSerializer,
    ProgramSerializer, _validate_comma_separated_languages_list
)
from course_discovery.apps.api.tests.mixins import SiteMixin
from course_discovery.apps.core.tests.factories import UserFactory
from course_discovery.apps.course_metadata.choices import CourseRunStatus
from course_discovery.apps.course_metadata.tests.factories import (
    CourseFactory, CourseRunFactory,
    OrganizationFactory, ProgramFactory, SeatFactory
)


def json_date_format(datetime_obj):
    return datetime.datetime.strftime(datetime_obj, "%Y-%m-%dT%H:%M:%S.%fZ")


def make_request():
    user = UserFactory()
    request = APIRequestFactory().get('/')
    request.user = user
    return request


def serialize_language_to_code(language):
    return language.code


class MinimalCourseSerializerTests(SiteMixin, TestCase):
    serializer_class = MinimalCourseSerializer

    @classmethod
    def get_expected_data(cls, course, request):
        context = {'request': request}

        return {
            'key': course.key,
            'uuid': str(course.uuid),
            'title': course.title,
            'course_runs': MinimalCourseRunSerializer(course.course_runs, many=True, context=context).data,
        }

    def test_data(self):
        request = make_request()
        course = CourseFactory(org='test-org')
        CourseRunFactory.create_batch(2, course=course)
        serializer = self.serializer_class(course, context={'request': request})
        expected = self.get_expected_data(course, request)
        self.assertDictEqual(serializer.data, expected)


class CourseSerializerTests(MinimalCourseSerializerTests):
    serializer_class = CourseSerializer

    @classmethod
    def get_expected_data(cls, course, request):
        expected = super().get_expected_data(course, request)
        expected.update({
            'modified': json_date_format(course.modified),  # pylint: disable=no-member
            'course_runs': CourseRunSerializer(course.course_runs, many=True, context={'request': request}).data,
            'card_image_url': course.card_image_url,
        })

        return expected


class MinimalCourseRunSerializerTests(TestCase):
    serializer_class = MinimalCourseRunSerializer

    @classmethod
    def get_expected_data(cls, course_run, request):  # pylint: disable=unused-argument
        return {
            'key': course_run.key,
            'uuid': str(course_run.uuid),
            'title': course_run.title,
            'start': json_date_format(course_run.start),
            'end': json_date_format(course_run.end),
            'enrollment_start': json_date_format(course_run.enrollment_start),
            'enrollment_end': json_date_format(course_run.enrollment_end),
            'status': course_run.status,
        }

    def test_data(self):
        request = make_request()
        course_run = CourseRunFactory()
        serializer = self.serializer_class(course_run, context={'request': request})
        expected = self.get_expected_data(course_run, request)
        self.assertDictEqual(serializer.data, expected)


class CourseRunSerializerTests(MinimalCourseRunSerializerTests):
    serializer_class = CourseRunSerializer

    @classmethod
    def get_expected_data(cls, course_run, request):
        expected = super().get_expected_data(course_run, request)
        expected.update({
            'course': course_run.course.key,
            'key': course_run.key,
            'title': course_run.title,  # pylint: disable=no-member
            'modified': json_date_format(course_run.modified),  # pylint: disable=no-member
            'status': course_run.status,
        })

        return expected


class CourseRunWithProgramsSerializerTests(TestCase):
    def setUp(self):
        super().setUp()
        self.request = make_request()
        self.course_run = CourseRunFactory()
        self.serializer_context = {'request': self.request}

    def test_data(self):
        serializer = CourseRunSerializer(self.course_run, context=self.serializer_context)
        ProgramFactory(courses=[self.course_run.course])
        self.assertDictEqual(serializer.data, self.get_expected_data(self.course_run, self.request))

    def test_data_excluded_course_run(self):
        """
        If a course run is excluded on a program, that program should not be
        returned for that course run on the course run endpoint.
        """
        serializer = CourseRunSerializer(self.course_run, context=self.serializer_context)
        ProgramFactory(courses=[self.course_run.course])
        expected = CourseRunSerializer(self.course_run, context=self.serializer_context).data
        assert serializer.data == expected

    @classmethod
    def get_expected_data(cls, course_run, request):
        return CourseRunSerializer(course_run, context={'request': request}).data


class MinimalProgramCourseSerializerTests(TestCase):
    def setUp(self):
        super(MinimalProgramCourseSerializerTests, self).setUp()
        self.program = ProgramFactory(courses=[CourseFactory()])

    def assert_program_courses_serialized(self, program):
        request = make_request()

        serializer = MinimalProgramCourseSerializer(
            program.courses,
            many=True,
            context={
                'request': request,
                'program': program,
                'course_runs': list(program.course_runs)
            }
        )
        expected = MinimalCourseSerializer(program.courses, many=True, context={'request': request}).data
        self.assertSequenceEqual(serializer.data, expected)

    def test_data(self):
        for course in self.program.courses.all():
            CourseRunFactory(course=course)

        self.assert_program_courses_serialized(self.program)

    def test_data_without_course_runs(self):
        """
        Make sure that if a course has no runs, the serializer still works as expected
        """
        self.assert_program_courses_serialized(self.program)

    def test_with_published_course_runs_only_context(self):
        """ Verify setting the published_course_runs_only context value excludes unpublished course runs. """
        # Create a program and course. The course should have both published and un-published course runs.
        request = make_request()
        course = CourseFactory()
        program = ProgramFactory(courses=[course])
        unpublished_course_run = CourseRunFactory(status=CourseRunStatus.Unpublished, course=course)
        CourseRunFactory(status=CourseRunStatus.Published, course=course)

        # We do NOT expect the results to included the unpublished data
        expected = MinimalCourseSerializer(course, context={'request': request}).data
        expected['course_runs'] = [course_run for course_run in expected['course_runs'] if
                                   course_run['key'] != str(unpublished_course_run.key)]
        self.assertEqual(len(expected['course_runs']), 1)

        serializer = MinimalProgramCourseSerializer(
            course,
            context={
                'request': request,
                'program': program,
                'published_course_runs_only': True,
                'course_runs': list(program.course_runs),
            }
        )

        self.assertSequenceEqual(serializer.data, expected)

    def test_use_full_course_serializer(self):
        """
        Verify that we can use the `use_full_course_serializer` parameter to use the
        CourseRun serializer.
        """
        request = make_request()
        course = CourseFactory()
        program = ProgramFactory(courses=[course])
        CourseRunFactory(course=course)

        serializer_data = MinimalProgramCourseSerializer(
            course,
            context={
                'request': request,
                'program': program,
                'use_full_course_serializer': 1,
                'course_runs': list(program.course_runs),
            }
        ).data

        expected = CourseRunSerializer(
            course.course_runs.all(),
            many=True,
            context={
                'request': request,
                'use_full_course_serializer': 1
            }
        ).data

        assert serializer_data['course_runs'] == expected


class MinimalProgramSerializerTests(TestCase):
    serializer_class = MinimalProgramSerializer

    def create_program(self):
        organizations = OrganizationFactory.create_batch(2)

        courses = CourseFactory.create_batch(3)
        for course in courses:
            CourseRunFactory.create_batch(2, course=course, start=datetime.datetime.now(UTC))

        return ProgramFactory(
            courses=courses,
        )

    @classmethod
    def get_expected_data(cls, program, request):
        image_field = StdImageSerializerField()
        image_field._context = {'request': request}  # pylint: disable=protected-access

        return {
            'uuid': str(program.uuid),
            'title': program.title,
            'status': program.status,
            'org': program.org,
            'visibility': program.visibility,
            'courses': MinimalProgramCourseSerializer(
                program.courses,
                many=True,
                context={
                    'request': request,
                    'program': program,
                    'course_runs': list(program.course_runs),
                }).data,
            'card_image_url': program.card_image_url,
            'languages': program.languages,
            'duration': program.duration,
            'start': program.start,
            'end': program.end,
            'enrollment_start': program.enrollment_start,
            'enrollment_end': program.enrollment_end,
        }

    # def test_data(self):
    #     request = make_request()
    #     program = self.create_program()
    #     serializer = self.serializer_class(program, context={'request': request})
    #     expected = self.get_expected_data(program, request)
    #     self.assertDictEqual(serializer.data, expected)


class ProgramSerializerTests(MinimalProgramSerializerTests):
    serializer_class = ProgramSerializer

    @classmethod
    def get_expected_data(cls, program, request):
        expected = super().get_expected_data(program, request)
        expected.update({
            'languages': [serialize_language_to_code(l) for l in program.languages] if program.languages else [],
        })
        return expected

    def test_marketable_enrollable_course_runs_with_archived(self):
        """ Test that the marketable_enrollable_course_runs_with_archived flag hides course runs
        that are not marketable or enrollable
        """
        course = CourseFactory()
        CourseRunFactory(status=CourseRunStatus.Unpublished, course=course)
        marketable_enrollable_run = CourseRunFactory(
            status=CourseRunStatus.Published,
            end=datetime.datetime.now(UTC) + datetime.timedelta(days=10),
            enrollment_start=None,
            enrollment_end=None,
            course=course
        )
        SeatFactory(course_run=marketable_enrollable_run)
        program = ProgramFactory(courses=[course])
        request = make_request()

        serializer = self.serializer_class(
            program,
            context={
                'request': request,
                'marketable_enrollable_course_runs_with_archived': True
            }
        )

        expected = MinimalProgramCourseSerializer(
            [course],
            many=True,
            context={
                'request': request,
                'program': program,
                'course_runs': [marketable_enrollable_run]
            }
        ).data

        assert len(expected[0]['course_runs']) == 1
        assert sorted(serializer.data['courses'][0]['course_runs'], key=lambda x: x['key']) == \
            sorted(expected[0]['course_runs'], key=lambda x: x['key'])


class ProgramLanguageValidationTests(TestCase):
    """`languages` is a comma-separated list; the validator is what rejects a bad payload."""

    def _serializer(self, languages):
        payload = {
            'title': 'Validation Path', 'org': 'edX', 'status': 'unpublished',
            'languages': languages, 'courses': [],
        }
        return MinimalProgramSerializer(data=payload, context={'request': None})

    def test_a_supported_code_passes(self):
        serializer = self._serializer(['en'])

        self.assertTrue(serializer.is_valid(), serializer.errors)

    def test_an_unknown_code_is_reported_as_a_field_error(self):
        serializer = self._serializer(['xx-not-a-language'])

        self.assertFalse(serializer.is_valid())
        self.assertIn('languages', serializer.errors)

    def test_the_validator_itself_rejects_a_non_list(self):
        """DRF's `ListField` wraps a bare string before validating, so assert on the validator.

        Reaching this branch through the serializer is not possible; it is reachable only when
        someone calls the validator directly, which the field definition allows.
        """
        with self.assertRaises(ValidationError):
            _validate_comma_separated_languages_list('en')

    def test_the_validator_itself_accepts_a_list_of_known_codes(self):
        self.assertIsNone(_validate_comma_separated_languages_list(['en']))


class ProgramPrefetchQuerysetTests(TestCase):
    def test_a_uuid_argument_scopes_the_queryset_to_that_program(self):
        wanted = ProgramFactory()
        ProgramFactory()

        queryset = MinimalProgramSerializer.prefetch_queryset(uuid=str(wanted.uuid))

        self.assertEqual([program.uuid for program in queryset], [wanted.uuid])

    def test_an_org_argument_scopes_the_queryset_to_that_tenant(self):
        wanted = ProgramFactory(org='org-a')
        ProgramFactory(org='org-b')

        queryset = MinimalProgramSerializer.prefetch_queryset(org='org-a')

        self.assertEqual([program.org for program in queryset], ['org-a'])


class ProgramCourseTitleFilterTests(TestCase):
    """Studio's add-courses search narrows the draft list by title.

    `get_courses` applies `query_by_title` on top of the draft uuid list, so a search in the
    add-courses dialog shows only the matching subset rather than everything already drafted.
    """

    def _serialize(self, uuids, title=None):
        program = ProgramFactory()
        context = {'request': None, 'draft_program_courses_uuids': uuids}
        if title is not None:
            context['query_by_title'] = title
        return MinimalProgramSerializer(program, context=context).get_courses(program)

    def test_a_title_filter_narrows_the_draft_list(self):
        matching = CourseFactory(title='Distinctive Course Title')
        other = CourseFactory(title='Something Else')

        courses = self._serialize([str(matching.uuid), str(other.uuid)], title='Distinctive')

        self.assertEqual([course['key'] for course in courses], [matching.key])

    def test_without_a_title_every_draft_course_is_returned(self):
        first = CourseFactory(title='Alpha')
        second = CourseFactory(title='Beta')

        courses = self._serialize([str(first.uuid), str(second.uuid)])

        self.assertEqual({course['key'] for course in courses}, {first.key, second.key})
