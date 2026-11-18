"""Behaviour tests for the Learning Path (Program) API the platform proxies to.

The endpoints exercised here are the ones Studio calls through
`/api/proxy/discovery/api/v1/programs/`, so a regression breaks Learning Path
creation, editing, publishing and course ordering without touching any LMS code.
Before this module the whole write surface (`create`/`update`/`destroy` and every
`ProgramCoursesViewSet` method) was untested.
"""
import json

from django.contrib.sites.models import Site
from django.test import TestCase, override_settings
from django.urls import reverse
from rest_framework.test import APIClient

from course_discovery.apps.api.tests.jwt_utils import generate_jwt_header_for_user
from course_discovery.apps.core.tests.factories import SiteFactory, UserFactory
from course_discovery.apps.course_metadata.choices import ProgramStatus
from course_discovery.apps.course_metadata.models import Program
from course_discovery.apps.course_metadata.tests.factories import (
    CourseFactory,
    CourseRunFactory,
    ProgramFactory,
)

TEST_DOMAIN = 'testserver.fake'


@override_settings(SITE_ID=1)
class ProgramApiTestCase(TestCase):
    """Shared login/site setup: every Program endpoint requires an authenticated JWT."""

    def setUp(self):
        super().setUp()
        Site.objects.all().delete()
        SiteFactory(id=1, domain=TEST_DOMAIN)
        self.user = UserFactory(username='lp-api-user')
        self.client = APIClient()
        self.client.credentials(HTTP_AUTHORIZATION=generate_jwt_header_for_user(self.user))

    def create_program(self, **overrides):
        payload = {'title': 'API Learning Path', 'org': 'edX', 'languages': ['en']}
        payload.update(overrides)
        return self.client.post(reverse('api:v1:program-list'), payload, format='json')


class ProgramCreateTests(ProgramApiTestCase):
    def test_create_returns_the_new_program_uuid(self):
        response = self.create_program()

        self.assertEqual(response.status_code, 201, response.content)
        program = Program.objects.get(uuid=response.json()['program_uuid'])
        self.assertEqual(program.title, 'API Learning Path')
        self.assertEqual(program.org, 'edX')

    def test_create_defaults_to_unpublished(self):
        """A new path must not appear in the catalogue before an explicit publish."""
        response = self.create_program()

        program = Program.objects.get(uuid=response.json()['program_uuid'])
        self.assertEqual(program.status, ProgramStatus.Unpublished)

    def test_create_without_org_is_rejected(self):
        """Studio always sends the site org; without it the row could not be scoped to a tenant.

        The view raises `django.core.exceptions.ValidationError`, which DRF does not translate,
        so the rejection surfaces as 500 rather than 400. Either code is a rejection; what
        matters is that nothing is persisted.
        """
        response = self.client.post(
            reverse('api:v1:program-list'), {'title': 'No Org Path', 'languages': ['en']}, format='json'
        )

        self.assertIn(response.status_code, (400, 500))
        self.assertFalse(Program.objects.filter(title='No Org Path').exists())

    def test_duplicate_title_reports_a_named_error(self):
        """`Program.title` is unique; Studio shows this message instead of a stack trace."""
        self.create_program(title='Taken Title')

        response = self.create_program(title='Taken Title')

        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.json()['api_error_message'], 'Path name already exist.')
        self.assertEqual(Program.objects.filter(title='Taken Title').count(), 1)


class ProgramUpdateTests(ProgramApiTestCase):
    def test_patch_publishes_and_stamps_the_release_date(self):
        """Publishing is what makes the path visible in the LMS catalogue.

        Studio sends `released_date` alongside `status`; the view replaces whatever value the
        client sent with `datetime.now()`, so the stamp is server-side and cannot be backdated.
        """
        program = ProgramFactory(status=ProgramStatus.Unpublished)
        self.assertIsNone(program.released_date)

        response = self.client.patch(
            reverse('api:v1:program-detail', kwargs={'uuid': program.uuid}),
            {'status': ProgramStatus.Active, 'released_date': 'auto_updated'},
            format='json',
        )

        self.assertEqual(response.status_code, 200, response.content)
        program.refresh_from_db()
        self.assertEqual(program.status, ProgramStatus.Active)
        self.assertIsNotNone(program.released_date)

    def test_patch_ignores_a_client_supplied_release_date(self):
        """The stamp is the publish moment, not whatever the caller claims."""
        program = ProgramFactory(status=ProgramStatus.Unpublished)

        self.client.patch(
            reverse('api:v1:program-detail', kwargs={'uuid': program.uuid}),
            {'status': ProgramStatus.Active, 'released_date': '2000-01-01T00:00:00Z'},
            format='json',
        )

        program.refresh_from_db()
        self.assertGreater(program.released_date.year, 2000)

    def test_patch_replaces_the_course_list_in_the_given_order(self):
        """Studio sends the published course order; it must survive the round trip."""
        program = ProgramFactory()
        first = CourseFactory()
        second = CourseFactory()
        program.courses.set([second, first])

        response = self.client.patch(
            reverse('api:v1:program-detail', kwargs={'uuid': program.uuid}),
            {'draft_program_courses': [str(first.uuid), str(second.uuid)]},
            format='json',
        )

        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual([course.uuid for course in program.courses.all()], [first.uuid, second.uuid])

    def test_patch_can_clear_the_course_list(self):
        """Unpublishing every course is a legitimate edit, not an ignored argument."""
        program = ProgramFactory()
        program.courses.add(CourseFactory())

        response = self.client.patch(
            reverse('api:v1:program-detail', kwargs={'uuid': program.uuid}),
            {'draft_program_courses': []},
            format='json',
        )

        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(program.courses.count(), 0)

    def test_duplicate_title_on_patch_reports_a_named_error(self):
        program = ProgramFactory(title='Existing Path')
        other = ProgramFactory(title='Another Path')

        response = self.client.patch(
            reverse('api:v1:program-detail', kwargs={'uuid': other.uuid}),
            {'title': 'Existing Path'},
            format='json',
        )

        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.json()['api_error_message'], 'Learning path title already exist.')
        other.refresh_from_db()
        self.assertEqual(other.title, 'Another Path')


class ProgramDestroyTests(ProgramApiTestCase):
    def test_delete_removes_the_program(self):
        program = ProgramFactory()
        uuid = program.uuid

        response = self.client.delete(reverse('api:v1:program-detail', kwargs={'uuid': uuid}))

        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()['program_uuid'], str(uuid))
        self.assertFalse(Program.objects.filter(uuid=uuid).exists())


class ProgramListTests(ProgramApiTestCase):
    def test_uuids_only_returns_bare_uuids_for_the_requested_org(self):
        """`SiteProgramsLoader` asks for exactly this shape when it looks up a site's paths."""
        wanted = ProgramFactory(org='wanted-org')
        ProgramFactory(org='other-org')

        response = self.client.get(
            reverse('api:v1:program-list'), {'org': 'wanted-org', 'uuids_only': 1}
        )

        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json(), [str(wanted.uuid)])


class ProgramCoursesApiTests(ProgramApiTestCase):
    def setUp(self):
        super().setUp()
        self.program = ProgramFactory()
        self.course = CourseFactory()
        self.course_run = CourseRunFactory(course=self.course)

    def courses_url(self):
        return reverse('api:v1:courses-list', kwargs={'program_uuid': self.program.uuid})

    def test_list_returns_the_courses_of_the_program(self):
        self.program.courses.add(self.course)

        response = self.client.get(self.courses_url())

        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual([item['key'] for item in response.json()], [self.course.key])

    def test_list_of_a_program_without_courses_is_empty(self):
        response = self.client.get(self.courses_url())

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), [])

    def test_create_without_course_ids_is_rejected(self):
        """`course_ids` is required; a django ValidationError surfaces as 500, not 400."""
        response = self.client.post(self.courses_url(), {'course_ids': []}, format='json')

        self.assertIn(response.status_code, (400, 500))

    def test_create_returns_the_courses_without_attaching_them(self):
        """Studio's Add-courses screen previews the dates before anything is attached."""
        response = self.client.post(
            self.courses_url(), {'course_ids': [self.course_run.key]}, format='json'
        )

        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual([item['key'] for item in response.json()], [self.course.key])
        self.assertEqual(self.program.courses.count(), 0)

    def test_create_with_exec_attaches_the_courses(self):
        response = self.client.post(
            self.courses_url(), {'course_ids': [self.course_run.key], 'exec': '1'}, format='json'
        )

        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual([course.uuid for course in self.program.courses.all()], [self.course.uuid])

    def test_create_reports_the_program_date_range(self):
        """Studio renders the date range from this response once the courses are attached."""
        self.course_run.start = '2026-01-01T00:00:00Z'
        self.course_run.end = '2026-12-31T00:00:00Z'
        self.course_run.save()

        response = self.client.post(
            self.courses_url(), {'course_ids': [self.course_run.key], 'exec': '1'}, format='json'
        )

        self.assertIsNotNone(response.json()[0]['program_start'])
        self.assertIsNotNone(response.json()[0]['program_end'])

    def test_create_preview_reports_no_date_range_before_attaching(self):
        """Without `exec` nothing is attached, so the program has no dates to report yet."""
        self.course_run.start = '2026-01-01T00:00:00Z'
        self.course_run.end = '2026-12-31T00:00:00Z'
        self.course_run.save()

        response = self.client.post(
            self.courses_url(), {'course_ids': [self.course_run.key]}, format='json'
        )

        self.assertIsNone(response.json()[0]['program_start'])
        self.assertIsNone(response.json()[0]['program_end'])

    def test_delete_detaches_a_single_course(self):
        self.program.courses.add(self.course)

        response = self.client.delete(
            reverse('api:v1:courses-detail', kwargs={'program_uuid': self.program.uuid, 'uuid': self.course.uuid})
        )

        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()['course_uuid'], str(self.course.uuid))
        self.assertEqual(self.program.courses.count(), 0)

    def test_patch_rejects_an_out_of_range_order(self):
        """A stale Studio tab must not corrupt the persisted order."""
        self.program.courses.add(self.course)

        response = self.client.patch(
            self.courses_url(),
            {'course_uuid': str(self.course.uuid), 'order_no': 5},
            format='json',
        )

        self.assertIn(response.status_code, (400, 500))

    def test_patch_reorders_two_courses(self):
        first, second = CourseFactory(), CourseFactory()
        self.program.courses.set([first, second])

        response = self.client.patch(
            self.courses_url(),
            {'course_uuid': str(second.uuid), 'order_no': 0},
            format='json',
        )

        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual([course.uuid for course in self.program.courses.all()], [second.uuid, first.uuid])
