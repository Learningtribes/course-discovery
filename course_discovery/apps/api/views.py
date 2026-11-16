from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect
from django.urls import reverse
from django.utils.translation import gettext as _
from drf_yasg import openapi
from drf_yasg.views import get_schema_view
from rest_framework.permissions import AllowAny


# django-rest-swagger 2.2.0 (CoreJSONRenderer / SchemaGenerator) was removed with
# DRF 3.17's coreapi removal. Follow the platform: serve the API docs with drf-yasg.
SwaggerSchemaView = get_schema_view(
    openapi.Info(title='Discovery API', default_version='v1'),
    public=False,
    permission_classes=(AllowAny,),
)


def api_docs_permission_denied_handler(request):
    """
    Permission denied handler for calls to the API documentation.

    Args:
        request (Request): Original request to the view the documentation

    Raises:
        PermissionDenied: The user is not authorized to view the API documentation.

    Returns:
        HttpResponseRedirect: Redirect to the login page if the user is not logged in. After a
            successful login, the user will be redirected back to the original path.
    """
    if request.user and request.user.is_authenticated:
        raise PermissionDenied(_('You are not permitted to access the API documentation.'))

    login_url = '{path}?next={next}'.format(path=reverse('login'), next=request.path)
    return redirect(login_url, permanent=False)
