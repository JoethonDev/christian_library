# Generated migration for GoogleReindexingTask model

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import uuid


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='GoogleReindexingTask',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('status', models.CharField(choices=[('pending', 'Pending'), ('in_progress', 'In Progress'), ('completed', 'Completed'), ('failed', 'Failed'), ('cancelled', 'Cancelled')], db_index=True, default='pending', max_length=20, verbose_name='Status')),
                ('content_type', models.CharField(blank=True, choices=[('all', 'All Content'), ('video', 'Videos Only'), ('audio', 'Audios Only'), ('pdf', 'PDFs Only')], max_length=10, null=True, verbose_name='Content Type')),
                ('total_urls', models.IntegerField(default=0, verbose_name='Total URLs')),
                ('submitted_urls', models.IntegerField(default=0, verbose_name='Submitted URLs')),
                ('successful_urls', models.IntegerField(default=0, verbose_name='Successful URLs')),
                ('failed_urls', models.IntegerField(default=0, verbose_name='Failed URLs')),
                ('error_log', models.TextField(blank=True, default='[]', help_text='JSON array of error details', verbose_name='Error Log')),
                ('started_at', models.DateTimeField(blank=True, null=True, verbose_name='Started At')),
                ('completed_at', models.DateTimeField(blank=True, null=True, verbose_name='Completed At')),
                ('sitemap_included', models.BooleanField(default=True, help_text='Whether to ping sitemap after completion', verbose_name='Sitemap Included')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='Created At')),
                ('updated_at', models.DateTimeField(auto_now=True, verbose_name='Updated At')),
                ('initiated_by', models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='reindexing_tasks', to=settings.AUTH_USER_MODEL, verbose_name='Initiated By')),
            ],
            options={
                'verbose_name': 'Google Re-indexing Task',
                'verbose_name_plural': 'Google Re-indexing Tasks',
                'ordering': ['-created_at'],
            },
        ),
        migrations.AddIndex(
            model_name='googlereindexingtask',
            index=models.Index(fields=['-created_at'], name='frontend_ap_created_85e5f0_idx'),
        ),
        migrations.AddIndex(
            model_name='googlereindexingtask',
            index=models.Index(fields=['status', '-created_at'], name='frontend_ap_status_dca1b9_idx'),
        ),
    ]
