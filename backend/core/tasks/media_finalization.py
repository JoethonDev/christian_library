import logging
import os
import shutil
from datetime import datetime, timedelta
from pathlib import Path
from celery import shared_task
from django.apps import apps
from django.conf import settings
from django.db import transaction
from django.utils import timezone
from apps.health.task_monitor import TaskMonitor
from core.services.gemini_manager import get_gemini_manager
from apps.media_manager.services.job_tracker import job_start, job_advance, job_complete, job_fail
from apps.media_manager.services.lifecycle_audit_service import LifecycleAuditService

logger = logging.getLogger(__name__)


@shared_task
def delete_files_task(paths):
    deleted = []
    logger.info(f"[delete_files_task] Starting deletion for {len(paths)} paths: {paths}")
    for path in paths:
        try:
            if os.path.isdir(path):
                shutil.rmtree(path)
                logger.info(f"[delete_files_task] Deleted directory: {path}")
                deleted.append(path)
            elif os.path.isfile(path):
                os.remove(path)
                logger.info(f"[delete_files_task] Deleted file: {path}")
                deleted.append(path)
            else:
                logger.info(f"[delete_files_task] Path does not exist: {path}")
        except Exception as e:
            logger.warning(f"[delete_files_task] Failed to delete {path}: {e}")
    logger.info(f"[delete_files_task] Deletion complete. Deleted: {deleted}")
    return {'deleted': deleted, 'requested': paths}


def get_contentitem_model():
    return apps.get_model('media_manager', 'ContentItem')


@shared_task(bind=True, max_retries=10, default_retry_delay=600)
def generate_seo_metadata_task(self, contentitem_id, force_regenerate=False):
    ContentItem = get_contentitem_model()

    TaskMonitor.register_task(
        task_id=self.request.id,
        task_name='AI SEO Metadata Generation',
        metadata={
            'content_id': contentitem_id,
            'attempt': self.request.retries + 1,
            'force': force_regenerate,
            'max_retries': self.max_retries,
            'queue': 'gemini'
        },
        checklist_steps=['validation', 'ai_generation', 'content_update']
    )
    job_start(contentitem_id, 'seo_generation', self.request.id)

    try:
        logger.info(f"Starting SEO metadata generation for ContentItem {contentitem_id} (attempt {self.request.retries + 1}/{self.max_retries + 1}, force={force_regenerate})")

        TaskMonitor.update_progress(
            self.request.id,
            message='Validating content item...',
            step='validation'
        )

        item = ContentItem.objects.get(id=contentitem_id)

        LifecycleAuditService.log_event(
            content_item=item,
            action_type='gemini_processing_started',
            source='system:seo_task',
            previous_state='pending',
            new_state='processing',
            message='Gemini SEO generation task started',
            payload={'content_id': str(item.id), 'task_id': self.request.id, 'force': force_regenerate},
        )

        if not force_regenerate and item.has_seo_metadata():
            logger.info(f"ContentItem {contentitem_id} already has SEO metadata. Skipping generation (use force_regenerate=True to override).")
            item.seo_processing_status = 'completed'
            item.save(update_fields=['seo_processing_status'])

            TaskMonitor.update_checklist_step(self.request.id, 'validation', True, "Content already has SEO metadata")
            TaskMonitor.update_checklist_step(self.request.id, 'ai_generation', True, "Skipped - already exists")
            TaskMonitor.update_checklist_step(self.request.id, 'content_update', True, "No update needed")

            TaskMonitor.update_task_status(
                self.request.id,
                'SUCCESS',
                {'message': 'SEO metadata already exists - skipped'}
            )
            return

        TaskMonitor.update_checklist_step(
            self.request.id,
            'validation',
            True,
            "Content validation successful"
        )

        item.seo_processing_status = 'processing'
        item.save(update_fields=['seo_processing_status'])

        TaskMonitor.update_progress(
            self.request.id,
            message='Preparing content for AI analysis...',
            step='ai_generation'
        )

        meta = item.get_meta_object()
        context_text = item.book_content if item.book_content else None
        file_path = None

        if meta and hasattr(meta, 'original_file') and meta.original_file:
            file_path = meta.original_file.path
            if not os.path.exists(file_path):
                if not context_text:
                    logger.warning(f"Media file not found at {file_path}")
                    item.seo_processing_status = 'failed'
                    item.save(update_fields=['seo_processing_status'])
                    TaskMonitor.update_task_status(
                        self.request.id,
                        'FAILURE',
                        {'message': 'Media file not found on disk', 'progress': 100}
                    )
                    return
                file_path = None
        elif not context_text:
            logger.warning(f"No media file found for ContentItem {contentitem_id}")
            item.seo_processing_status = 'failed'
            item.save(update_fields=['seo_processing_status'])
            TaskMonitor.update_task_status(
                self.request.id,
                'FAILURE',
                {'message': 'No media file found', 'progress': 100}
            )
            return

        TaskMonitor.update_progress(
            self.request.id,
            30,
            'Connecting to AI service...',
            'AI Service'
        )

        manager = get_gemini_manager()

        TaskMonitor.update_progress(
            self.request.id,
            50,
            f'Generating combined metadata and SEO with AI (attempt {self.request.retries + 1}/3)...',
            'AI Processing'
        )

        success, combined_data = manager.generate_combined_ai_data(contentitem_id, file_path, item.content_type, context_text=context_text)

        if success and combined_data:
            TaskMonitor.update_progress(
                self.request.id,
                80,
                'Updating content with AI-generated metadata...',
                'Saving'
            )

            success_update = item.update_combined_ai_data(combined_data)

            if success_update:
                item.seo_processing_status = 'completed'

                update_fields = ['seo_processing_status']
                if item.processing_status != 'completed':
                    item.processing_status = 'completed'
                    update_fields.append('processing_status')

                item.save(update_fields=update_fields)

                LifecycleAuditService.log_event(
                    content_item=item,
                    action_type='gemini_processing_completed',
                    source='system:seo_task',
                    previous_state='processing',
                    new_state='completed',
                    message='Gemini SEO generation task completed',
                    payload={'content_id': str(item.id), 'task_id': self.request.id, 'force': force_regenerate},
                )

                logger.info(f"Successfully generated and updated SEO metadata for ContentItem {contentitem_id}")

                TaskMonitor.update_task_status(
                    self.request.id,
                    'SUCCESS',
                    {'message': 'AI SEO metadata generated successfully', 'progress': 100}
                )
                finalize_media_processing.delay(str(item.id))
            else:
                logger.error(f"Failed to update SEO metadata for ContentItem {contentitem_id}")
                item.seo_processing_status = 'failed'
                item.save(update_fields=['seo_processing_status'])
                job_fail(contentitem_id, 'seo_generation', 'Failed to save AI-generated metadata')
                TaskMonitor.update_task_status(
                    self.request.id,
                    'FAILURE',
                    {'message': 'Failed to save AI-generated metadata', 'progress': 100}
                )
        else:
            error_msg = combined_data.get('error', 'Unknown error') if isinstance(combined_data, dict) else 'Generation failed'
            logger.error(f"Failed to generate SEO metadata for ContentItem {contentitem_id}: {error_msg}")
            raise Exception(f"Combined AI generation failed: {error_msg}")

    except ContentItem.DoesNotExist:
        logger.error(f"ContentItem {contentitem_id} not found")
        job_fail(contentitem_id, 'seo_generation', 'Content not found')
        TaskMonitor.update_task_status(
            self.request.id,
            'FAILURE',
            {'message': 'Content not found', 'progress': 100}
        )
        return

    except Exception as exc:
        logger.error(f"Error generating SEO metadata for ContentItem {contentitem_id}: {str(exc)}", exc_info=True)
        job_fail(contentitem_id, 'seo_generation', exc)

        def _seo_permanently_failed(reason: str):
            try:
                _item = ContentItem.objects.get(id=contentitem_id)
                _item.seo_processing_status = 'failed'
                _item.save(update_fields=['seo_processing_status'])
            except Exception:
                pass
            job_fail(contentitem_id, 'seo_generation', reason)
            finalize_media_processing.delay(str(contentitem_id))
            TaskMonitor.update_task_status(
                self.request.id,
                'FAILURE',
                {'message': reason, 'progress': 100},
            )
            logger.error(f"SEO permanently failed for {contentitem_id}: {reason}")

        is_rate_limit_error = _is_gemini_rate_limit_error(exc)
        is_server_error = _is_gemini_server_error(exc)

        if self.request.retries >= 2:
            next_3am_delay = _calculate_next_3am_delay()
            logger.warning(f"3 attempts failed for ContentItem {contentitem_id}. Scheduling next attempt for 3:00 AM.")
            try:
                item.seo_processing_status = 'failed'
                item.save(update_fields=['seo_processing_status'])
            except Exception:
                pass

            TaskMonitor.update_task_status(
                self.request.id,
                'RETRY',
                {
                    'message': f'3 attempts failed - rescheduling for 3:00 AM (Error: {str(exc)[:100]})',
                    'retry_at': '3:00 AM',
                    'delay_hours': round(next_3am_delay / 3600, 1),
                },
            )
            try:
                raise self.retry(exc=exc, countdown=next_3am_delay)
            except self.MaxRetriesExceededError:
                _seo_permanently_failed('All retries exhausted for SEO generation (3AM schedule)')
                return {'status': 'failed', 'message': 'Max retries exhausted'}

        if is_server_error:
            logger.warning(f"Gemini server error detected (5xx) for ContentItem {contentitem_id} (attempt {self.request.retries + 1})")
            countdown = 600
            TaskMonitor.update_task_status(
                self.request.id,
                'RETRY',
                {
                    'message': f'Server error (5xx) - retrying in 10 minutes (attempt {self.request.retries + 1}/3)',
                    'countdown': countdown,
                    'error_type': 'server',
                },
            )
            try:
                raise self.retry(exc=exc, countdown=countdown)
            except self.MaxRetriesExceededError:
                _seo_permanently_failed('Max retries exceeded for SEO generation (server error path)')
                return {'status': 'failed', 'message': 'Max retries exceeded'}

        if is_rate_limit_error:
            logger.warning(f"Gemini rate limit detected for ContentItem {contentitem_id} (attempt {self.request.retries + 1})")
            countdown = 300
            TaskMonitor.update_task_status(
                self.request.id,
                'RETRY',
                {
                    'message': f'Rate limited - retrying in 5 minutes (attempt {self.request.retries + 1}/3)',
                    'rate_limited': True,
                    'countdown': countdown,
                },
            )
            try:
                raise self.retry(exc=exc, countdown=countdown)
            except self.MaxRetriesExceededError:
                _seo_permanently_failed('Max retries exceeded for SEO generation (rate limit path)')
                return {'status': 'failed', 'message': 'Max retries exceeded'}

        countdown = 120 * (2 ** self.request.retries)
        logger.info(f"Standard retry for ContentItem {contentitem_id} in {countdown}s (attempt {self.request.retries + 1})")
        TaskMonitor.update_task_status(
            self.request.id,
            'RETRY',
            {
                'message': f'Error retry in {countdown}s (attempt {self.request.retries + 1}/3)',
                'countdown': countdown,
                'error_type': 'standard',
            },
        )
        try:
            raise self.retry(exc=exc, countdown=countdown)
        except self.MaxRetriesExceededError:
            _seo_permanently_failed('Max retries exceeded for SEO generation (standard path)')
            return {'status': 'failed', 'message': 'Max retries exceeded'}


def _is_gemini_rate_limit_error(exception):
    error_str = str(exception).lower()
    rate_limit_indicators = [
        'rate limit',
        'quota exceeded',
        'too many requests',
        'resource exhausted',
        '429',
        'credits exhausted',
        'quota_exceeded',
        'rate_limit_exceeded'
    ]
    return any(indicator in error_str for indicator in rate_limit_indicators)


def _is_gemini_server_error(exception):
    error_str = str(exception).lower()
    server_error_indicators = [
        '500', '502', '503', '504',
        'internal server error',
        'service unavailable',
        'gateway timeout',
        'bad gateway',
        'upstream error'
    ]
    return any(indicator in error_str for indicator in server_error_indicators)


def _calculate_next_3am_delay():
    now = timezone.now()
    today_3am = now.replace(hour=3, minute=0, second=0, microsecond=0)
    if now >= today_3am:
        tomorrow_3am = today_3am + timedelta(days=1)
        target_time = tomorrow_3am
    else:
        target_time = today_3am
    delay_seconds = (target_time - now).total_seconds()
    return max(delay_seconds, 3600)


@shared_task(bind=True, max_retries=8, default_retry_delay=600)
def finalize_media_processing(self, contentitem_id):
    ContentItem = get_contentitem_model()

    try:
        with transaction.atomic():
            item = ContentItem.objects.select_for_update().get(id=contentitem_id)
            meta = item.get_meta_object()

            if not meta:
                logger.warning(f"finalize_media_processing: no meta for {contentitem_id}, completing job anyway")
                job_complete(contentitem_id)
                return

            r2_done = meta.r2_upload_status == 'completed'
            r2_failed = meta.r2_upload_status == 'failed'
            seo_done = item.seo_processing_status == 'completed'

            if r2_done and seo_done:
                logger.info(f"Both R2 and SEO finished for {contentitem_id}. Cleaning up local files.")

                local_paths = []
                try:
                    if meta.original_file and os.path.exists(meta.original_file.path):
                        local_paths.append(str(meta.original_file.path))

                    if item.content_type == 'video':
                        hls_dir = Path(settings.MEDIA_ROOT) / 'hls' / 'videos' / str(item.id)
                        if hls_dir.exists():
                            local_paths.append(str(hls_dir))
                    elif item.content_type == 'audio':
                        if hasattr(meta, 'compressed_file') and meta.compressed_file and os.path.exists(meta.compressed_file.path):
                            local_paths.append(str(meta.compressed_file.path))

                    if local_paths:
                        delete_files_task.delay(local_paths)
                        logger.info(f"Queued deletion for {len(local_paths)} paths for item {item.id}")
                    else:
                        logger.info(f"No local files to delete for item {item.id} (already cleaned or never written)")

                    job_complete(contentitem_id)
                except Exception as e:
                    logger.warning(f"Error preparing local files for deletion for item {item.id}: {e}")
                    job_complete(contentitem_id)

                return

            if r2_failed and seo_done:
                logger.warning(f"R2 failed, SEO complete — files preserved for {contentitem_id}")
                job_complete(contentitem_id)
                return

        logger.info(f"Finalize deferred: R2={meta.r2_upload_status}, SEO={item.seo_processing_status}")
        raise self.retry(countdown=600)

    except ContentItem.DoesNotExist:
        pass
    except self.MaxRetriesExceededError:
        logger.warning("Max retries — completing without full cleanup")
        job_complete(contentitem_id)


@shared_task
def bulk_generate_seo_metadata(content_type=None, limit=None):
    ContentItem = get_contentitem_model()

    try:
        queryset = ContentItem.objects.filter(
            is_active=True,
            seo_keywords_ar__len=0,
            seo_keywords_en__len=0
        )

        if content_type:
            queryset = queryset.filter(content_type=content_type)

        if limit:
            queryset = queryset[:limit]

        count = 0
        for item in queryset:
            try:
                meta = item.get_meta_object()
                if meta and hasattr(meta, 'original_file') and meta.original_file:
                    generate_seo_metadata_task.delay(str(item.id))
                    count += 1
                else:
                    logger.warning(f"No media file for ContentItem {item.id}, skipping SEO generation")
            except Exception as e:
                logger.error(f"Error queuing SEO generation for ContentItem {item.id}: {str(e)}")

        logger.info(f"Queued SEO metadata generation for {count} content items")
        return count

    except Exception as exc:
        logger.error(f"Error in bulk SEO metadata generation: {str(exc)}", exc_info=True)
        return 0
