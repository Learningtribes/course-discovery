# -*- coding: utf-8 -*-
"""
Compatibility shim for the removed ``EdxRestApiClient``.

``edx-rest-api-client`` 7.0.0 deleted the ``EdxRestApiClient`` class that this
codebase used to build authenticated Slumber API clients (``EdxRestApiClient(url,
jwt=token)`` / ``oauth_access_token=token``). The replacement ``OAuthAPIClient``
has a different construction contract (client_id/client_secret OAuth), so it is
not a drop-in. This mirrors the platform's ``openedx/core/lib/api_client.py``,
which rebuilds the old behaviour from ``SuppliedJwtAuth`` / ``BearerAuth`` plus
``slumber.API``.
"""
from __future__ import absolute_import, division, print_function, unicode_literals

from edx_rest_api_client.auth import BearerAuth, SuppliedJwtAuth
from edx_rest_api_client.client import USER_AGENT
from requests import Session
from slumber import API


def create_api_client(url, jwt=None, oauth_access_token=None):
    """
    Build an authenticated Slumber API client equivalent to the removed
    ``EdxRestApiClient(url, jwt=...)``.

    Args:
        url (str): API base URL.
        jwt (str): A pre-issued JWT; authenticates via ``JWT <token>``.
        oauth_access_token (str): A pre-issued OAuth bearer token; authenticates
            via ``Bearer <token>``.

    Returns:
        slumber.API: A Slumber client. No request is made during construction.

    Raises:
        ValueError: If neither ``jwt`` nor ``oauth_access_token`` is supplied.
    """
    session = Session()
    session.headers.update({'User-Agent': USER_AGENT})
    if jwt:
        session.auth = SuppliedJwtAuth(jwt)
    elif oauth_access_token:
        session.auth = BearerAuth(oauth_access_token)
    else:
        raise ValueError('create_api_client requires `jwt` or `oauth_access_token`.')
    return API(url, session=session)
