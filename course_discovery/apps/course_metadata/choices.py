from django.db.models import IntegerChoices, TextChoices
from django.utils.translation import gettext_lazy as _


class CourseRunStatus(TextChoices):
    Published = 'published', _('Published')
    Unpublished = 'unpublished', _('Unpublished')


class CourseRunPacing(TextChoices):
    # Translators: Instructor-paced refers to course runs that operate on a schedule set by the instructor,
    # similar to a normal university course.
    Instructor = 'instructor_paced', _('Instructor-paced')
    # Translators: Self-paced refers to course runs that operate on the student's schedule.
    Self = 'self_paced', _('Self-paced')


class ProgramStatus(TextChoices):
    Unpublished = 'unpublished', _('Unpublished')
    Active = 'active', _('Active')
    Retired = 'retired', _('Retired')
    Deleted = 'deleted', _('Deleted')


class ProgramVisibility(IntegerChoices):
    Public = 0, _('Full public')
    Accessible = 1, _('Accessible by URL')
    Private = 2, _('Private')


class ReportingType(TextChoices):
    mooc = 'mooc', 'mooc'
    spoc = 'spoc', 'spoc'
    test = 'test', 'test'
    demo = 'demo', 'demo'
    other = 'other', 'other'
