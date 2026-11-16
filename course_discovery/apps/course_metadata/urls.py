"""
URLs for the admin autocomplete lookups.
"""
from django.urls import re_path

from course_discovery.apps.course_metadata.lookups import (
    CourseAutocomplete, CourseRunAutocomplete, OrganizationAutocomplete, PersonAutocomplete
)

app_name = "admin_metadata"

urlpatterns = [
    re_path(r'^course-autocomplete/$', CourseAutocomplete.as_view(), name='course-autocomplete',),
    re_path(r'^course-run-autocomplete/$', CourseRunAutocomplete.as_view(), name='course-run-autocomplete',),
    re_path(r'^organisation-autocomplete/$', OrganizationAutocomplete.as_view(), name='organisation-autocomplete',),
    re_path(r'^person-autocomplete/$', PersonAutocomplete.as_view(), name='person-autocomplete',),
]
