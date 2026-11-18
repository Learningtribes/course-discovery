import datetime
from unittest import mock

from django.db import models
from django.test import TestCase

from course_discovery.apps.core.utils import (
    ElasticsearchUtils,
    SearchQuerySetWrapper,
    delete_expired_courses,
    get_all_related_field_names,
    serialize_datetime,
)
from course_discovery.apps.course_metadata.models import Course, CourseRun
from course_discovery.apps.course_metadata.tests.factories import CourseFactory, CourseRunFactory


class UnrelatedModel(models.Model):
    class Meta:
        app_label = 'core'
        managed = False


class RelatedModel(models.Model):
    class Meta:
        app_label = 'core'
        managed = False


class ForeignRelatedModel(models.Model):
    fk = models.ForeignKey(RelatedModel, on_delete=models.CASCADE)

    class Meta:
        app_label = 'core'
        managed = False


class M2MRelatedModel(models.Model):
    m2m = models.ManyToManyField(RelatedModel)

    class Meta:
        app_label = 'core'
        managed = False


class ModelUtilTests(TestCase):
    def test_get_all_related_field_names(self):
        """ Verify the method returns the names of all relational fields for a model. """
        self.assertEqual(get_all_related_field_names(UnrelatedModel), [])
        self.assertEqual(set(get_all_related_field_names(RelatedModel)), {'foreignrelatedmodel', 'm2mrelatedmodel'})


class SerializeDatetimeTests(TestCase):
    def test_formats_to_utc_iso_without_microseconds(self):
        """The API contract is second resolution with a `Z` suffix."""
        self.assertEqual(serialize_datetime(datetime.datetime(2026, 11, 18, 12, 34, 56, 789)), '2026-11-18T12:34:56Z')

    def test_none_stays_none(self):
        """Optional dates must not serialise the string 'None'."""
        self.assertIsNone(serialize_datetime(None))


class DeleteExpiredCoursesTests(TestCase):
    def test_removes_the_named_courses_only(self):
        """`refresh_course_metadata` prunes the courses the LMS no longer reports."""
        expired = CourseFactory()
        kept = CourseFactory()

        delete_expired_courses([expired.key])

        self.assertFalse(Course.objects.filter(pk=expired.pk).exists())
        self.assertTrue(Course.objects.filter(pk=kept.pk).exists())

    def test_an_empty_list_deletes_nothing(self):
        course = CourseFactory()

        delete_expired_courses([])

        self.assertTrue(Course.objects.filter(pk=course.pk).exists())

    def test_a_failure_is_logged_instead_of_raised(self):
        """A pruning error must not abort the whole metadata refresh."""
        with mock.patch('course_discovery.apps.course_metadata.models.Course.objects.filter',
                        side_effect=RuntimeError('db down')), \
                self.assertLogs('course_discovery.apps.core.utils', level='ERROR') as logs:
            delete_expired_courses(['course-v1:x+y+z'])

        self.assertIn('db down', '\n'.join(logs.output))


class SearchQuerySetWrapperTests(TestCase):
    """The wrapper yields model instances, not search results, and proxies everything else."""

    def _result(self, payload):
        result = mock.Mock()
        result.object = payload
        return result

    def test_iteration_yields_the_wrapped_objects(self):
        wrapper = SearchQuerySetWrapper([self._result('a'), self._result('b')])

        self.assertEqual(list(wrapper), ['a', 'b'])

    def test_integer_indexing_returns_the_object(self):
        results = [self._result('a'), self._result('b')]
        wrapper = SearchQuerySetWrapper(results)

        self.assertEqual(wrapper[1], 'b')

    def test_slicing_returns_another_wrapper(self):
        results = [self._result('a'), self._result('b')]
        wrapper = SearchQuerySetWrapper(results)

        sliced = wrapper[0:2]

        self.assertIsInstance(sliced, SearchQuerySetWrapper)
        self.assertEqual(list(sliced), ['a', 'b'])

    def test_unknown_attributes_proxy_to_the_query_set(self):
        query_set = mock.Mock()
        query_set.count.return_value = 7

        wrapper = SearchQuerySetWrapper(query_set)

        self.assertEqual(wrapper.count(), 7)


class ElasticsearchUtilsTests(TestCase):
    """The alias/index helpers are the only place index naming and synonyms are decided."""

    def test_create_index_prefixes_with_the_alias_and_installs_synonyms(self):
        es_connection = mock.Mock()

        with mock.patch.object(ElasticsearchUtils, 'create_index', wraps=ElasticsearchUtils.create_index), \
                mock.patch('course_discovery.apps.core.utils.get_synonyms', return_value=['a,b']), \
                mock.patch('course_discovery.apps.core.utils.settings') as settings_mock, \
                mock.patch('course_discovery.apps.core.utils.datetime') as datetime_mock:
            settings_mock.ELASTICSEARCH_INDEX_SETTINGS = {'settings': {'analysis': {'filter': {'synonym': {}}}}}
            datetime_mock.datetime.utcnow.return_value = __import__('datetime').datetime(2026, 11, 18, 1, 2, 3)

            index_name = ElasticsearchUtils.create_index(es_connection, prefix='catalog')

        self.assertEqual(index_name, 'catalog_20261118_010203')
        body = es_connection.indices.create.call_args.kwargs['body']
        self.assertEqual(body['settings']['analysis']['filter']['synonym']['synonyms'], ['a,b'])

    def test_create_alias_and_index_does_nothing_when_the_alias_exists(self):
        es_connection = mock.Mock()
        es_connection.indices.exists_alias.return_value = True

        ElasticsearchUtils.create_alias_and_index(es_connection, 'catalog')

        es_connection.indices.update_aliases.assert_not_called()

    def test_create_alias_and_index_points_the_alias_at_the_new_index(self):
        es_connection = mock.Mock()
        es_connection.indices.exists_alias.return_value = False

        with mock.patch.object(ElasticsearchUtils, 'create_index', return_value='catalog_20261118_010203'):
            ElasticsearchUtils.create_alias_and_index(es_connection, 'catalog')

        actions = es_connection.indices.update_aliases.call_args.args[0]['actions']
        self.assertEqual(actions[1], {'add': {'alias': 'catalog', 'index': 'catalog_20261118_010203'}})

    def test_delete_index_ignores_a_missing_index(self):
        """Pruning an already-deleted index during a reindex must not raise."""
        es_connection = mock.Mock()

        ElasticsearchUtils.delete_index(es_connection, 'catalog_old')

        self.assertEqual(es_connection.indices.delete.call_args.kwargs['ignore'], 404)

    def test_refresh_index_waits_for_yellow(self):
        es_connection = mock.Mock()

        ElasticsearchUtils.refresh_index(es_connection, 'catalog')

        self.assertEqual(es_connection.cluster.health.call_args.kwargs['wait_for_status'], 'yellow')
