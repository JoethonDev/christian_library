# Generated manually for analytics models

from django.db import migrations, models
import django.utils.timezone


class Migration(migrations.Migration):

    dependencies = [
        ('media_manager', '0011_contentitem_notes_contentitem_seo_processing_status_and_more'),
    ]

    operations = [
        migrations.CreateModel(
            name='ContentViewEvent',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('content_type', models.CharField(choices=[('video', 'Video'), ('audio', 'Audio'), ('pdf', 'PDF'), ('static', 'Static Page')], db_index=True, max_length=10, verbose_name='Content Type')),
                ('content_id', models.UUIDField(db_index=True, help_text='UUID for ContentItem or static page slug', verbose_name='Content ID')),
                ('timestamp', models.DateTimeField(db_index=True, default=django.utils.timezone.now, verbose_name='Timestamp')),
                ('user_agent', models.CharField(blank=True, max_length=256, verbose_name='User Agent')),
                ('ip_address', models.GenericIPAddressField(blank=True, null=True, verbose_name='IP Address')),
                ('referrer', models.CharField(blank=True, max_length=256, verbose_name='Referrer')),
            ],
            options={
                'verbose_name': 'Content View Event',
                'verbose_name_plural': 'Content View Events',
                'ordering': ['-timestamp'],
            },
        ),
        migrations.CreateModel(
            name='DailyContentViewSummary',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('content_type', models.CharField(choices=[('video', 'Video'), ('audio', 'Audio'), ('pdf', 'PDF'), ('static', 'Static Page')], db_index=True, max_length=10, verbose_name='Content Type')),
                ('content_id', models.UUIDField(db_index=True, verbose_name='Content ID')),
                ('date', models.DateField(db_index=True, verbose_name='Date')),
                ('view_count', models.PositiveIntegerField(default=0, verbose_name='View Count')),
            ],
            options={
                'verbose_name': 'Daily Content View Summary',
                'verbose_name_plural': 'Daily Content View Summaries',
                'ordering': ['-date', '-view_count'],
                'unique_together': {('content_type', 'content_id', 'date')},
            },
        ),
        migrations.AddIndex(
            model_name='contentviewevent',
            index=models.Index(fields=['content_type', 'content_id', 'timestamp'], name='media_manag_content_idx'),
        ),
        migrations.AddIndex(
            model_name='dailycontentviewsummary',
            index=models.Index(fields=['content_type', 'content_id', 'date'], name='media_manag_content_date_idx'),
        ),
    ]
