from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("media_manager", "0022_chunkeduploadsession"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="pdfmeta",
            name="optimized_file",
        ),
        migrations.RemoveField(
            model_name="pdfmeta",
            name="r2_optimized_file_url",
        ),
    ]
