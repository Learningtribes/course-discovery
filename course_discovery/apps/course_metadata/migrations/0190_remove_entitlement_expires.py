# -*- coding: utf-8 -*-
# Generated by Django 1.11.23 on 2019-08-21 18:11
from __future__ import unicode_literals

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('course_metadata', '0189_add_salesforce_ids'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='courseentitlement',
            name='expires',
        ),
        migrations.RemoveField(
            model_name='historicalcourseentitlement',
            name='expires',
        ),
    ]
