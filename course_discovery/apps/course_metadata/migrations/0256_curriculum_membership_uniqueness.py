# Generated by Django 2.2.14 on 2020-08-04 17:00

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('course_metadata', '0255_auto_20200804_1401'),
    ]

    operations = [
        migrations.AlterUniqueTogether(
            name='curriculumcoursemembership',
            unique_together={('curriculum', 'course')},
        ),
        migrations.AlterUniqueTogether(
            name='curriculumprogrammembership',
            unique_together={('curriculum', 'program')},
        ),
    ]
