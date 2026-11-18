"""Behaviour tests for the Studio admin autocomplete endpoints.

These power search-as-you-type in the admin. The rules that matter are the staff gate
(a non-staff session must get nothing back, even though the URL is reachable) and the
fallbacks: `PersonAutocomplete` still finds a person when the query is a UUID, and it
renders a different label inside the admin.
"""
import uuid

from django.contrib.sites.models import Site
from django.test import TestCase, override_settings
from django.urls import reverse

from course_discovery.apps.core.tests.factories import SiteFactory, UserFactory
from course_discovery.apps.course_metadata.tests.factories import (
    CourseFactory,
    CourseRunFactory,
    OrganizationFactory,
    PersonFactory,
)

TEST_DOMAIN = 'testserver.fake'


@override_settings(SITE_ID=1)
class AutocompleteTestCase(TestCase):
    def setUp(self):
        super().setUp()
        Site.objects.all().delete()
        SiteFactory(id=1, domain=TEST_DOMAIN)

    def login_staff(self):
        user = UserFactory(username='autocomplete-staff', is_staff=True)
        self.client.force_login(user)
        self.staff = user
        return user

    def results(self, url_name, query, referer='http://testserver/admin/course_metadata/'):
        # The person lookup renders a different label outside the admin; default to the admin
        # referer, which is the only reachable path in this fork (see the residue test below).
        response = self.client.get(
            reverse('admin_metadata:' + url_name), {'q': query}, HTTP_REFERER=referer
        )
        self.assertEqual(response.status_code, 200, response.content)
        return [str(item['id']) for item in response.json()['results']]


class StaffGateTests(AutocompleteTestCase):
    def test_a_non_staff_user_gets_no_results(self):
        """The endpoint is not admin-protected, so the gate has to live in the view."""
        CourseFactory(key='course-v1:edX+DemoX+2026')
        self.client.force_login(UserFactory(username='plain-user', is_staff=False))

        self.assertEqual(self.results('course-autocomplete', 'DemoX'), [])

    def test_an_anonymous_user_gets_no_results(self):
        CourseFactory(key='course-v1:edX+DemoX+2026')

        self.assertEqual(self.results('course-autocomplete', 'DemoX'), [])

    def test_a_staff_user_sees_the_matches(self):
        course = CourseFactory(key='course-v1:edX+DemoX+2026')
        self.login_staff()

        self.assertEqual(self.results('course-autocomplete', 'DemoX'), [str(course.pk)])


class CourseAutocompleteTests(AutocompleteTestCase):
    def setUp(self):
        super().setUp()
        self.login_staff()

    def test_an_empty_query_lists_everything(self):
        first, second = CourseFactory(), CourseFactory()

        self.assertEqual(sorted(self.results('course-autocomplete', '')), sorted([str(first.pk), str(second.pk)]))

    def test_matches_on_key_or_title(self):
        by_key = CourseFactory(key='course-v1:edX+Alpha+2026', title='Unrelated')
        by_title = CourseFactory(key='course-v1:edX+Beta+2026', title='Alpha in the title')

        self.assertEqual(sorted(self.results('course-autocomplete', 'Alpha')),
                         sorted([str(by_key.pk), str(by_title.pk)]))


class CourseRunAutocompleteTests(AutocompleteTestCase):
    def setUp(self):
        super().setUp()
        self.login_staff()

    def test_matches_on_the_run_key_or_the_parent_course_title(self):
        matching_course = CourseFactory(title='Distinctive Title')
        by_course_title = CourseRunFactory(course=matching_course)
        by_key = CourseRunFactory(key='course-v1:edX+Other+run-Distinctive')

        self.assertEqual(
            sorted(self.results('course-run-autocomplete', 'Distinctive')),
            sorted([str(by_course_title.pk), str(by_key.pk)]),
        )


class OrganizationAutocompleteTests(AutocompleteTestCase):
    def setUp(self):
        super().setUp()
        self.login_staff()

    def test_matches_on_key_or_name(self):
        by_key = OrganizationFactory(key='DistinctiveOrg')
        by_name = OrganizationFactory(name='Distinctive Organisation')

        self.assertEqual(
            sorted(self.results('organisation-autocomplete', 'Distinctive')),
            sorted([str(by_key.pk), str(by_name.pk)]),
        )


class PersonAutocompleteTests(AutocompleteTestCase):
    def setUp(self):
        super().setUp()
        self.login_staff()
        self.person = PersonFactory(given_name='Ada', family_name='Lovelace')

    def test_matches_on_given_or_family_name(self):
        self.assertEqual(self.results('person-autocomplete', 'Lovelace'), [str(self.person.pk)])

    def test_falls_back_to_a_uuid_when_the_name_search_finds_nothing(self):
        """The admin shows a person's uuid; pasting it into the widget must resolve them."""
        self.assertEqual(self.results('person-autocomplete', str(self.person.uuid)), [str(self.person.pk)])

    def test_a_non_uuid_query_without_matches_returns_nothing(self):
        """The uuid fallback must not raise on a query that is not a uuid."""
        self.assertEqual(self.results('person-autocomplete', 'nobody-by-this-name'), [])

    def test_the_non_admin_label_path_is_broken_residue_from_the_publisher_removal(self):
        """Documents a real defect rather than enshrining it.

        `get_result_label` renders `publisher/_personLookup.html` for any request outside the
        admin, but the `publisher` app was removed from this fork, so the template does not
        exist and the endpoint raises `TemplateDoesNotExist` (HTTP 500). Nothing in this
        deployment requests it off-admin: the widget only runs inside the admin. The branch
        should be deleted, not tested around — recorded here so it is visible.
        """
        # `raise_request_exception` is a Client constructor argument, not a request one.
        client = self.client_class(raise_request_exception=False)
        client.force_login(self.staff)
        response = client.get(
            reverse('admin_metadata:person-autocomplete'),
            {'q': 'Lovelace'},
            HTTP_REFERER='http://testserver/elsewhere/',
        )

        self.assertEqual(response.status_code, 500)

    def test_login_is_required(self):
        """Unlike the other three lookups, this one is behind LoginRequiredMixin."""
        self.client.logout()

        response = self.client.get(reverse('admin_metadata:person-autocomplete'), {'q': 'Lovelace'})

        self.assertEqual(response.status_code, 302)
        self.assertIn('/login/', response['Location'])
