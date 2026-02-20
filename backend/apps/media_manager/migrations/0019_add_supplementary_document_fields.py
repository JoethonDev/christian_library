# Generated migration for supplementary document support

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('media_manager', '0018_add_api_upload_models'),
    ]

    operations = [
        migrations.AddField(
            model_name='contentitem',
            name='supplementary_document',
            field=models.FileField(
                blank=True,
                null=True,
                upload_to='documents/%Y/%m/',
                verbose_name='Supplementary Document',
                help_text='Word document (.doc/.docx) with additional content'
            ),
        ),
        migrations.AddField(
            model_name='contentitem',
            name='supplementary_document_name',
            field=models.CharField(
                blank=True,
                max_length=255,
                verbose_name='Document Name',
                help_text='Original filename of supplementary document'
            ),
        ),
        migrations.AddField(
            model_name='contentitem',
            name='supplementary_document_size',
            field=models.IntegerField(
                blank=True,
                null=True,
                verbose_name='Document Size (bytes)',
                help_text='File size in bytes'
            ),
        ),
        migrations.AddField(
            model_name='contentitem',
            name='supplementary_document_type',
            field=models.CharField(
                blank=True,
                max_length=100,
                verbose_name='Document Type',
                help_text='MIME type of document (e.g., application/vnd.openxmlformats-officedocument.wordprocessingml.document)'
            ),
        ),
        migrations.AddField(
            model_name='contentitem',
            name='supplementary_document_uploaded_at',
            field=models.DateTimeField(
                blank=True,
                null=True,
                verbose_name='Document Uploaded At',
                help_text='Timestamp when document was uploaded'
            ),
        ),
        migrations.AddField(
            model_name='contentitem',
            name='supplementary_document_text',
            field=models.TextField(
                blank=True,
                null=True,
                verbose_name='Extracted Document Text',
                help_text='Text extracted from supplementary document'
            ),
        ),
    ]
