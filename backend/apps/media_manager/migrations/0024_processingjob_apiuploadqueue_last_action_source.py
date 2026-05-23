from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("media_manager", "0023_remove_pdf_optimization_fields"),
    ]

    operations = [
        migrations.AddField(
            model_name="processingjob",
            name="last_action_source",
            field=models.CharField(blank=True, default="", max_length=64),
        ),
        migrations.AddField(
            model_name="apiuploadqueue",
            name="last_action_source",
            field=models.CharField(
                blank=True,
                default="",
                help_text="Origin of last status mutation, such as admin API or queue worker",
                max_length=64,
                verbose_name="Last Action Source",
            ),
        ),
    ]
