"""Behaviour tests for the serializer fields that have no model of their own.

`StdImageSerializerField` renders the size variants of a StdImage field and accepts a
base64 data URI on the way in (Studio posts card images that way); `ImageField` renders
the flat `{src, description, height, width}` shape the API migrated to. Both had no test.
"""
import base64
from unittest import mock

from django.test import TestCase

from course_discovery.apps.api.fields import ImageField, StdImageSerializerField


class FieldTestCase(TestCase):
    def setUp(self):
        super().setUp()
        self.field = StdImageSerializerField()
        self.field._context = {'request': mock.Mock()}
        self.field.context['request'].build_absolute_uri.side_effect = lambda path: 'https://cdn.test' + path


class StdImageSerializerFieldRepresentationTests(FieldTestCase):
    def _model_instance(self):
        """A stand-in exposing `field.variations` plus one attribute per variation."""
        variations = {'small': {'width': 100, 'height': 50}, 'large': {'width': 400, 'height': 200}}
        sized_small = mock.Mock(url='/media/card_small.jpg')
        sized_large = mock.Mock(url='/media/card_large.jpg')
        instance = mock.Mock(small=sized_small, large=sized_large)
        instance.field.variations = variations
        return instance

    def test_returns_one_entry_per_variation_with_absolute_urls(self):
        serialized = self.field.to_representation(self._model_instance())

        self.assertEqual(serialized, {
            'small': {'url': 'https://cdn.test/media/card_small.jpg', 'width': 100, 'height': 50},
            'large': {'url': 'https://cdn.test/media/card_large.jpg', 'width': 400, 'height': 200},
        })

    def test_omits_a_variation_without_a_file(self):
        """A partially generated image must not serialise a null url."""
        instance = self._model_instance()
        instance.small = None

        serialized = self.field.to_representation(instance)

        self.assertNotIn('small', serialized)
        self.assertIn('large', serialized)

    def test_a_field_without_files_serialises_to_an_empty_object(self):
        instance = self._model_instance()
        instance.small = None
        instance.large = None

        self.assertEqual(self.field.to_representation(instance), {})


class StdImageSerializerFieldInternalValueTests(FieldTestCase):
    def test_none_and_empty_are_passed_through_as_none(self):
        self.assertIsNone(self.field.to_internal_value(None))
        self.assertIsNone(self.field.to_internal_value(''))

    def test_base64_data_uri_becomes_an_uploaded_file(self):
        """Studio posts the card image inline; the field decodes it to a named file."""
        payload = base64.b64encode(b'a-png-body')
        data_uri = 'data:image/png;base64,' + payload.decode()

        with mock.patch.object(StdImageSerializerField.__bases__[0], 'to_internal_value',
                               return_value='handled') as parent:
            result = self.field.to_internal_value(data_uri)

        self.assertEqual(result, 'handled')
        uploaded = parent.call_args.args[0]
        self.assertEqual(uploaded.name, 'tmp.png')
        self.assertEqual(uploaded.read(), b'a-png-body')

    def test_a_plain_string_is_forwarded_untouched(self):
        with mock.patch.object(StdImageSerializerField.__bases__[0], 'to_internal_value',
                               return_value='handled') as parent:
            self.field.to_internal_value('/already/a/url.png')

        self.assertEqual(parent.call_args.args[0], '/already/a/url.png')


class ImageFieldTests(TestCase):
    def test_renders_the_flat_shape_the_api_migrated_to(self):
        """Only `src` is meaningful; the other keys stay for client compatibility."""
        self.assertEqual(
            ImageField().to_representation('/media/course.jpg'),
            {'src': '/media/course.jpg', 'description': None, 'height': None, 'width': None},
        )
