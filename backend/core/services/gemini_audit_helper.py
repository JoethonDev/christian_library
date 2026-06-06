import logging

logger = logging.getLogger(__name__)


def log_gemini_error(
    action_type,
    *,
    model,
    error=None,
    content_item=None,
    actor=None,
    payload=None,
    message='',
):
    """
    Log a Gemini failure to ContentLifecycleAuditLog.
    Never raises — failures are logged and suppressed.
    """
    from apps.media_manager.services.lifecycle_audit_service import LifecycleAuditService

    base_payload = {'model': model}
    if error:
        base_payload['error'] = str(error)[:2000]
    if payload:
        base_payload.update(payload)

    try:
        LifecycleAuditService.log_event(
            content_item=content_item,
            action_type=action_type,
            actor=actor,
            source='gemini',
            new_state='failure',
            message=message or str(error)[:500] if error else action_type,
            payload=base_payload,
        )
    except Exception as e:
        logger.error(f"Audit log write failed for {action_type}: {e}")
