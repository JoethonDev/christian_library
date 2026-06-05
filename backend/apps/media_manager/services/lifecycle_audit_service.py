from apps.media_manager.models import ContentLifecycleAuditLog


class LifecycleAuditService:
    """Centralized writer for content lifecycle audit events."""

    @staticmethod
    def log_event(
        *,
        content_item=None,
        action_type,
        actor=None,
        source='',
        previous_state='',
        new_state='',
        message='',
        payload=None,
    ):
        return ContentLifecycleAuditLog.objects.create(
            content_item=content_item,
            action_type=action_type,
            actor=actor,
            source=source,
            previous_state=previous_state,
            new_state=new_state,
            message=message,
            payload=payload or {},
        )
