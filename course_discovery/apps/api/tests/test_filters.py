from unittest import mock

from django.test import TestCase

from course_discovery.apps.api.filters import CourseFilter, CourseRunFilter
from course_discovery.apps.course_metadata.models import Course, CourseRun
from course_discovery.apps.course_metadata.tests.factories import CourseFactory, CourseRunFactory




class CharListFilterTests(TestCase):
    """`keys=a,b` is how clients send a multi-value filter in one query param."""

    def test_a_comma_separated_value_becomes_a_list(self):
        course = CourseFactory(key='course-v1:edX+Keep+2026')
        CourseFactory(key='course-v1:edX+Drop+2026')

        filtered = CourseFilter({'keys': course.key}, Course.objects.all())

        self.assertEqual([item.key for item in filtered.qs], [course.key])

    def test_an_empty_value_does_not_narrow_the_queryset(self):
        CourseFactory()
        CourseFactory()

        filtered = CourseFilter({'keys': ''}, Course.objects.all())

        self.assertEqual(filtered.qs.count(), 2)

    def test_an_absent_value_does_not_narrow_the_queryset(self):
        CourseFactory()

        filtered = CourseFilter({}, Course.objects.all())

        self.assertEqual(filtered.qs.count(), 1)


class FilterSetMixinTests(TestCase):
    """`active=1` / `marketable=1` call the queryset helper of the same name, and nothing else."""

    def _queryset(self):
        queryset = mock.Mock()
        queryset.active.return_value = 'active-result'
        queryset.marketable.return_value = 'marketable-result'
        return queryset

    def test_active_applies_when_the_flag_is_truthy(self):
        queryset = self._queryset()

        self.assertEqual(CourseRunFilter().filter_active(queryset, 'active', '1'), 'active-result')
        queryset.active.assert_called_once_with()

    def test_marketable_applies_when_the_flag_is_truthy(self):
        queryset = self._queryset()

        self.assertEqual(CourseRunFilter().filter_marketable(queryset, 'marketable', '1'), 'marketable-result')
        queryset.marketable.assert_called_once_with()

    def test_a_falsy_flag_leaves_the_queryset_untouched(self):
        queryset = self._queryset()

        self.assertIs(CourseRunFilter().filter_active(queryset, 'active', '0'), queryset)
        queryset.active.assert_not_called()


class CourseRunFilterQuerysetTests(TestCase):
    def test_a_non_django_queryset_is_returned_untouched(self):
        """A Haystack result set must not be treated as a Django queryset."""
        sentinel = ['not-a-queryset']
        filter_set = CourseRunFilter({'keys': 'x'}, queryset=CourseRun.objects.all())
        # The filter set is built against a real queryset (django-filter needs `.model`), then
        # swapped for the Haystack result the endpoint would pass in view code.
        filter_set.queryset = sentinel

        self.assertIs(filter_set.qs, sentinel)

    def test_a_django_queryset_is_filtered_normally(self):
        kept = CourseRunFactory(key='course-v1:edX+Keep+2026')
        CourseRunFactory(key='course-v1:edX+Drop+2026')

        filter_set = CourseRunFilter({'keys': kept.key}, queryset=CourseRun.objects.all())

        self.assertEqual([run.key for run in filter_set.qs], [kept.key])
