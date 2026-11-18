"""The API cache keys carry a timestamp so a model change invalidates every cached response."""

from django.conf import settings
from django.core.cache import cache
from django.test import TestCase

from course_discovery.apps.api.cache import (
    API_TIMESTAMP_KEY,
    ApiTimestampKeyBit,
    api_change_receiver,
    set_api_timestamp,
    timestamped_list_key_constructor,
    timestamped_object_key_constructor,
)


class ApiTimestampKeyBitTests(TestCase):
    def setUp(self):
        super().setUp()
        cache.delete(API_TIMESTAMP_KEY)
        self.addCleanup(cache.delete, API_TIMESTAMP_KEY)

    def test_the_timestamp_is_created_on_first_read(self):
        """The key must never be absent, or responses would cache forever."""
        timestamp = ApiTimestampKeyBit().get_data()

        self.assertIsNotNone(timestamp)
        self.assertEqual(cache.get(API_TIMESTAMP_KEY), timestamp)

    def test_an_existing_timestamp_is_reused(self):
        set_api_timestamp(1234)

        self.assertEqual(ApiTimestampKeyBit().get_data(), 1234)


class KeyConstructorWiringTests(TestCase):
    """The constructors are one-line delegations registered by dotted path in the settings.

    Driving them needs a fully initialised DRF `Request` (drf-extensions reads
    `request.accepted_renderer`), so the contract asserted here is the wiring that actually
    decides whether the timestamp and the querystring reach the key at all.
    """

    def test_the_list_and_object_key_functions_are_registered(self):
        rest_framework_extensions = settings.REST_FRAMEWORK_EXTENSIONS

        self.assertEqual(
            rest_framework_extensions['DEFAULT_LIST_CACHE_KEY_FUNC'],
            'course_discovery.apps.api.cache.timestamped_list_key_constructor',
        )
        self.assertEqual(
            rest_framework_extensions['DEFAULT_OBJECT_CACHE_KEY_FUNC'],
            'course_discovery.apps.api.cache.timestamped_object_key_constructor',
        )

    def test_the_registered_names_resolve_to_the_module_functions(self):
        """A renamed module would leave the setting pointing at nothing."""
        for func in (timestamped_list_key_constructor, timestamped_object_key_constructor):
            self.assertEqual(
                '{}.{}'.format(func.__module__, func.__name__),
                'course_discovery.apps.api.cache.' + func.__name__,
            )

    def test_the_constructors_carry_a_timestamp_and_a_querystring_bit(self):
        """Without both bits, a model change or a different query param would reuse a stale body."""
        from course_discovery.apps.api.cache import (
            TimestampedListKeyConstructor, TimestampedObjectKeyConstructor,
        )

        for constructor in (TimestampedListKeyConstructor, TimestampedObjectKeyConstructor):
            self.assertIsInstance(constructor.timestamp, ApiTimestampKeyBit)
            self.assertEqual(getattr(constructor, 'querystring', None).__class__.__name__,
                             'QueryParamsKeyBit')


class ApiChangeReceiverTests(TestCase):
    def setUp(self):
        super().setUp()
        cache.delete(API_TIMESTAMP_KEY)
        self.addCleanup(cache.delete, API_TIMESTAMP_KEY)

    def test_a_model_change_advances_the_timestamp(self):
        """Every write to course_metadata must invalidate the cached API responses."""
        set_api_timestamp(1000)

        api_change_receiver(sender=type('Program', (), {}))

        self.assertNotEqual(cache.get(API_TIMESTAMP_KEY), 1000)

    def test_the_change_is_logged_with_the_model_name(self):
        with self.assertLogs('course_discovery.apps.api.cache', level='INFO') as logs:
            api_change_receiver(sender=type('Program', (), {}))

        self.assertIn('Program model changed', '\n'.join(logs.output))
