# Generated migration for adding unique_view_count field

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('media_manager', '0012_add_analytics_models'),
    ]

    operations = [
        migrations.AddField(
            model_name='dailycontentviewsummary',
            name='unique_view_count',
            field=models.PositiveIntegerField(default=0, help_text='Number of unique views based on IP address', verbose_name='Unique View Count'),
        ),
    ]
