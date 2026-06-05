from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import uuid


class Migration(migrations.Migration):

    dependencies = [
        ("media_manager", "0024_processingjob_apiuploadqueue_last_action_source"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="ContentLifecycleAuditLog",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("action_type", models.CharField(db_index=True, max_length=64, verbose_name="Action Type")),
                ("source", models.CharField(blank=True, db_index=True, default="", max_length=64, verbose_name="Source")),
                ("previous_state", models.CharField(blank=True, default="", max_length=32, verbose_name="Previous State")),
                ("new_state", models.CharField(blank=True, default="", max_length=32, verbose_name="New State")),
                ("message", models.TextField(blank=True, default="", verbose_name="Message")),
                ("payload", models.JSONField(blank=True, default=dict, verbose_name="Payload")),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True, verbose_name="Created At")),
                (
                    "actor",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="content_lifecycle_logs",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Actor",
                    ),
                ),
                (
                    "content_item",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="lifecycle_audit_logs",
                        to="media_manager.contentitem",
                        verbose_name="Content Item",
                    ),
                ),
            ],
            options={
                "verbose_name": "Content Lifecycle Audit Log",
                "verbose_name_plural": "Content Lifecycle Audit Logs",
                "ordering": ["-created_at"],
            },
        ),
        migrations.AddIndex(
            model_name="contentlifecycleauditlog",
            index=models.Index(fields=["content_item", "created_at"], name="media_manage_content_4f58cc_idx"),
        ),
        migrations.AddIndex(
            model_name="contentlifecycleauditlog",
            index=models.Index(fields=["action_type", "created_at"], name="media_manage_action__fd7b6b_idx"),
        ),
        migrations.AddIndex(
            model_name="contentlifecycleauditlog",
            index=models.Index(fields=["actor", "created_at"], name="media_manage_actor_i_b8d001_idx"),
        ),
        migrations.AddIndex(
            model_name="contentlifecycleauditlog",
            index=models.Index(fields=["new_state", "created_at"], name="media_manage_new_sta_2e5eb2_idx"),
        ),
    ]
