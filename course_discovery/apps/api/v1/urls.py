""" API v1 URLs. """
from django.urls import include, re_path
from django.views.decorators.csrf import csrf_exempt
from rest_framework_nested import routers

from course_discovery.apps.api.v1.views.programs import ProgramViewSet
from course_discovery.apps.api.v1.views.programs import ProgramCoursesViewSet
from course_discovery.apps.course_metadata.views import CourseMetadataRefresher


partners_router = routers.SimpleRouter()

app_name = "v1"

urlpatterns = [
    re_path(r'^partners/', include((partners_router.urls, 'partners'), namespace='partners')),
    re_path(r'^refresh_course_metadata/', csrf_exempt(CourseMetadataRefresher.as_view()), name='refresh-course-metadata')
]

router = routers.SimpleRouter()

router.register(r'programs', ProgramViewSet, basename='program')
program_courses_router = routers.NestedSimpleRouter(router, r'programs', lookup=r'program')
program_courses_router.register(r'courses', ProgramCoursesViewSet, basename=r'courses')

urlpatterns += router.urls
urlpatterns += program_courses_router.urls
