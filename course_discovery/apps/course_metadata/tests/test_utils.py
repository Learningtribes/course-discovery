import re
from unittest import mock

import ddt
import responses
from django.test import TestCase

from course_discovery.apps.course_metadata import utils
from course_discovery.apps.course_metadata.exceptions import (
    MarketingSiteAPIClientException, PersonToMarketingException,
)
from course_discovery.apps.course_metadata.tests.factories import ProgramFactory
from course_discovery.apps.course_metadata.tests.mixins import MarketingSiteAPIClientTestMixin


@ddt.ddt
class UploadToFieldNamePathTests(TestCase):
    """
    Test the utiltity object 'UploadtoFieldNamePath'
    """
    def setUp(self):
        super(UploadToFieldNamePathTests, self).setUp()
        self.program = ProgramFactory()

    @ddt.data(
        ('/media/program/', 'uuid', '.jpeg'),
        ('/media/program/', 'title', '.jpeg'),
        ('/media/', 'uuid', '.jpeg'),
        ('/media/', 'title', '.txt'),
        ('', 'title', ''),
    )
    @ddt.unpack
    def test_upload_to(self, path, field, ext):
        upload_to = utils.UploadToFieldNamePath(populate_from=field, path=path)
        upload_path = upload_to(self.program, 'name' + ext)
        regex = re.compile(path + str(getattr(self.program, field)) + '-[a-f0-9]{12}' + ext)
        self.assertTrue(regex.match(upload_path))


class MarketingSiteAPIClientTests(MarketingSiteAPIClientTestMixin):
    """
    Unit test cases for MarketinSiteAPIClient
    """
    def setUp(self):
        super(MarketingSiteAPIClientTests, self).setUp()
        self.api_client = utils.MarketingSiteAPIClient(
            self.username,
            self.password,
            self.api_root
        )

    @responses.activate
    def test_init_session(self):
        self.mock_login_response(200)
        session = self.api_client.init_session
        self.assert_responses_call_count(2)
        self.assertIsNotNone(session)

    @responses.activate
    def test_init_session_failed(self):
        self.mock_login_response(500)
        with self.assertRaises(MarketingSiteAPIClientException):
            self.api_client.init_session  # pylint: disable=pointless-statement

    @responses.activate
    def test_csrf_token(self):
        self.mock_login_response(200)
        self.mock_csrf_token_response(200)
        csrf_token = self.api_client.csrf_token
        self.assert_responses_call_count(3)
        self.assertEqual(self.csrf_token, csrf_token)

    @responses.activate
    def test_csrf_token_failed(self):
        self.mock_login_response(200)
        self.mock_csrf_token_response(500)
        with self.assertRaises(MarketingSiteAPIClientException):
            self.api_client.csrf_token  # pylint: disable=pointless-statement

    @responses.activate
    def test_user_id(self):
        self.mock_login_response(200)
        self.mock_user_id_response(200)
        user_id = self.api_client.user_id
        self.assert_responses_call_count(3)
        self.assertEqual(self.user_id, user_id)

    @responses.activate
    def test_user_id_failed(self):
        self.mock_login_response(200)
        self.mock_user_id_response(500)
        with self.assertRaises(MarketingSiteAPIClientException):
            self.api_client.user_id  # pylint: disable=pointless-statement

    @responses.activate
    def test_api_session(self):
        self.mock_login_response(200)
        self.mock_csrf_token_response(200)
        api_session = self.api_client.api_session
        self.assert_responses_call_count(3)
        self.assertIsNotNone(api_session)
        self.assertEqual(api_session.headers.get('Content-Type'), 'application/json')
        self.assertEqual(api_session.headers.get('X-CSRF-Token'), self.csrf_token)

    @responses.activate
    def test_api_session_failed(self):
        self.mock_login_response(500)
        self.mock_csrf_token_response(500)
        with self.assertRaises(MarketingSiteAPIClientException):
            self.api_client.api_session  # pylint: disable=pointless-statement


class CleanQueryTests(TestCase):
    """Elasticsearch treats AND/OR/NOT/TO as operators; they must be upper-case and parenthesised."""

    def test_the_query_is_lowercased_and_wrapped(self):
        self.assertEqual(utils.clean_query('Python'), '(python)')

    def test_reserved_operators_are_upper_cased(self):
        """A lowercase `and` is searched as a word, an upper-case `AND` is the operator."""
        self.assertEqual(utils.clean_query('python and django'), '(python AND django)')

    def test_every_reserved_operator_is_handled(self):
        for operator in utils.RESERVED_ELASTICSEARCH_QUERY_OPERATORS:
            with self.subTest(operator=operator):
                self.assertEqual(
                    utils.clean_query('a {op} b'.format(op=operator.lower())),
                    '(a {op} b)'.format(op=operator),
                )

    def test_an_operator_inside_a_word_is_left_alone(self):
        """`android` contains `and` but is not the operator."""
        self.assertEqual(utils.clean_query('android'), '(android)')


class UploadToDeconstructTests(TestCase):
    """Migrations serialise these callables; `deconstruct` is what Django writes into them."""

    def test_deconstruct_returns_the_importable_path_and_arguments(self):
        path, args, kwargs = utils.UploadToFieldNamePath('name', path='images/').deconstruct()

        self.assertEqual(path, 'course_discovery.apps.course_metadata.utils.UploadToFieldNamePath')
        self.assertEqual(args, ('name',))
        self.assertEqual(kwargs, {'path': 'images/'})


class UploadToAutoSlugTests(TestCase):
    def test_the_slug_replaces_the_file_name(self):
        """The stored name is derived from a model field, not the upload's own name."""
        instance = mock.Mock()
        instance.headline = 'A Great Course!'

        result = utils.UploadToAutoSlug(populate_from='headline')(instance, 'original.png')

        self.assertEqual(result, 'a-great-course.png')


class CustomRenderVariationsTests(TestCase):
    def test_every_variation_is_rendered_and_false_is_returned(self):
        """Returning False suppresses stdimage's own rendering pass."""
        with mock.patch.object(utils.StdImageFieldFile, 'render_variation') as render:
            result = utils.custom_render_variations(
                'card.jpg', {'small': {'width': 100}, 'large': {'width': 400}}, mock.Mock(), replace=True
            )

        self.assertFalse(result)
        self.assertEqual(render.call_count, 2)
        # `replace` is passed positionally as the third argument. `replace=True` is the whole
        # point: stdimage's own default refuses to overwrite an existing variation file.
        self.assertTrue(all(call.args[2] is True for call in render.call_args_list))


class MarketingSiteAPIClientCredentialTests(TestCase):
    def test_missing_credentials_are_rejected(self):
        with self.assertRaises(MarketingSiteAPIClientException):
            utils.MarketingSiteAPIClient('', '', 'https://marketing.test/api')


class PersonToMarketingExceptionTests(TestCase):
    def test_the_message_explains_the_data_was_not_saved(self):
        exception = PersonToMarketingException('boom')

        self.assertIn('boom', exception.message)
        self.assertIn('has not been saved', exception.message)
