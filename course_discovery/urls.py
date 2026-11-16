"""course_discovery URL Configuration
The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/1.8/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  re_path(r'^$', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  re_path(r'^$', Home.as_view(), name='home')
Including another URLconf
    1. Add an import:  from blog import urls as blog_urls
    2. Add a URL to urlpatterns:  re_path(r'^blog/', include(blog_urls))
"""

import os

from auth_backends.urls import oauth2_urlpatterns
from django.conf import settings
from django.urls import include, re_path
from django.conf.urls.static import static
from django.contrib import admin
from django.utils.translation import gettext_lazy as _
from django.views.i18n import JavaScriptCatalog

from course_discovery.apps.api.views import SwaggerSchemaView
from course_discovery.apps.core import views as core_views

admin.site.site_header = _('Discovery Service Administration')
admin.site.site_title = admin.site.site_header
admin.autodiscover()

urlpatterns = oauth2_urlpatterns + [
    re_path(r'^admin/course_metadata/', include('course_discovery.apps.course_metadata.urls', namespace='admin_metadata')),
    re_path(r'^admin/core/', include('course_discovery.apps.core.urls', namespace='admin_core')),
    re_path(r'^admin/', admin.site.urls),
    re_path(r'^api/', include('course_discovery.apps.api.urls', namespace='api')),
    # Use the same auth views for all logins, including those originating from the browseable API.
    re_path(r'^api-auth/', include((oauth2_urlpatterns, 'auth_backends'), namespace='rest_framework')),
    re_path(r'^api-docs/', SwaggerSchemaView.with_ui('swagger', cache_timeout=0), name='api_docs'),
    re_path(r'^auto_auth/$', core_views.AutoAuth.as_view(), name='auto_auth'),
    re_path(r'^health/$', core_views.health, name='health'),
    re_path(r'^language-tags/', include('course_discovery.apps.ietf_language_tags.urls', namespace='language_tags')),
    re_path(r'^comments/', include('django_comments.urls')),
    re_path(r'^i18n/', include('django.conf.urls.i18n')),
    re_path(r'^jsi18n/$', JavaScriptCatalog.as_view(), name='javascript-catalog'),
    re_path(r'^taggit_autosuggest/', include('taggit_autosuggest.urls')),
]

if settings.DEBUG:  # pragma: no cover
    # We need this url pattern to serve user uploaded assets according to
    # https://docs.djangoproject.com/en/1.10/howto/static-files/#serving-files-uploaded-by-a-user-during-development
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    if os.environ.get('ENABLE_DJANGO_TOOLBAR', False):
        import debug_toolbar

        urlpatterns.append(re_path(r'^__debug__/', include(debug_toolbar.urls)))
