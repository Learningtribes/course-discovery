# Generated by Django 1.11.15 on 2019-02-05 15:59


from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('course_metadata', '0155_auto_20190207_1546'),
    ]

    operations = [
        migrations.AddField(
            model_name='curriculum',
            name='is_active',
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name='curriculum',
            name='name',
            field=models.CharField(blank=True, max_length=255),
        ),
    ]
