"""
URLs for the admin autocomplete lookups.
"""
from django.urls import re_path

from course_discovery.apps.core.lookups import UserAutocomplete

app_name = "admin_core"

urlpatterns = [
    re_path(r'^user-autocomplete/$', UserAutocomplete.as_view(), name='user-autocomplete',),
]
