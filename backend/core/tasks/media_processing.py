import logging
import os
import random
import shutil
import tempfile
from datetime import timedelta
from pathlib import Path

from celery import shared_task
from django.apps import apps
from django.conf import settings
from django.core.cache import cache
from django.core.files import File
from django.utils import timezone

from apps.health.task_monitor import TaskMonitor
from apps.media_manager.models import AudioMeta, PdfMeta, VideoMeta
from apps.media_manager.services.job_tracker import job_advance, job_complete, job_fail, job_start
from .media_finalization import generate_seo_metadata_task, finalize_media_processing

from core.storage_backends import R2Service
from core.storage_backends import R2Service as DjangoR2Service
from core.utils.media_processing import (
    VideoProcessor, AudioProcessor, PDFProcessor,
    generate_unique_filename, DependencyError
)

logger = logging.getLogger(__name__)


def _resolve_local_source_path(file_field, prefix):
    try:
        return file_field.path, None
    except Exception:
        source_name = file_field.name or prefix
        suffix = Path(source_name).suffix
        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=suffix, prefix=f'{prefix}_')
        temp_file.close()
        with file_field.open('rb') as source, open(temp_file.name, 'wb') as target:
            shutil.copyfileobj(source, target)
        return temp_file.name, temp_file.name


@shared_task(bind=True, max_retries=3)
def process_video_to_hls(self, video_meta_id):
    """Process uploaded video to HLS format with multiple resolutions"""
    VideoMeta = apps.get_model('media_manager', 'VideoMeta')
    source_cleanup_path = None
    try:
        video_meta = VideoMeta.objects.get(id=video_meta_id)
        
        # Register task for monitoring
        TaskMonitor.register_task(
            task_id=self.request.id,
            task_name='Video HLS Processing',
            metadata={'video_id': video_meta_id, 'content_id': str(video_meta.content_item.id)}
        )
        job_start(video_meta.content_item.id, 'file_processing', self.request.id)
        
        # Check if there's actually a file to process
        if not video_meta.original_file:
            logger.warning(f"No file to process for VideoMeta {video_meta_id}")
            video_meta.processing_status = 'completed'
            video_meta.save()
            job_complete(video_meta.content_item.id)
            
            TaskMonitor.update_task_status(self.request.id, 'SUCCESS', {'message': 'Skipped - no file'})
            return {'status': 'skipped', 'message': 'No file to process'}
        
        video_meta.processing_status = 'processing'
        video_meta.save()
        
        # Update ContentItem status
        video_meta.content_item.processing_status = 'processing'
        video_meta.content_item.save(update_fields=['processing_status'])
        
        TaskMonitor.update_progress(self.request.id, 5, "Setting up video processing environment...", "Initialization")
        
        logger.info(f"Starting HLS processing for video: {video_meta.content_item.title_ar}")
        
        try:
            processor = VideoProcessor()
        except DependencyError as e:
            logger.error(f"Video processing dependencies not available: {e}")
            video_meta.processing_status = 'failed'
            video_meta.save()
            TaskMonitor.update_task_status(self.request.id, 'FAILURE', error=f'Dependencies missing: {e}')
            return {'status': 'error', 'message': f'Dependencies missing: {e}'}
        
        input_path, source_cleanup_path = _resolve_local_source_path(video_meta.original_file, 'video')
        content_uuid = str(video_meta.content_item.id)
        
        # Create HLS directories
        hls_base_path = Path(settings.MEDIA_ROOT) / 'hls' / 'videos' / content_uuid
        hls_720p_dir = hls_base_path / '720p'
        hls_480p_dir = hls_base_path / '480p'
        
        # Process 720p HLS
        try:
            TaskMonitor.update_progress(self.request.id, 10, "Crafting High-Definition (720p) adaptive stream...", "720p Encoding")
            playlist_720p = processor.generate_hls(input_path, hls_720p_dir, '720')
            video_meta.hls_720p_path = f'hls/videos/{content_uuid}/720p/playlist.m3u8'
            logger.info(f"720p HLS generated successfully: {playlist_720p}")
        except Exception as e:
            logger.error(f"720p HLS generation failed: {e}")
            TaskMonitor.update_progress(self.request.id, 10, f"720p Encoding failed: {e}", "Error")
            raise
        
        # Process 480p HLS
        try:
            TaskMonitor.update_progress(self.request.id, 50, "Optimizing Standard (480p) adaptive stream...", "480p Encoding")
            playlist_480p = processor.generate_hls(input_path, hls_480p_dir, '480')
            video_meta.hls_480p_path = f'hls/videos/{content_uuid}/480p/playlist.m3u8'
            logger.info(f"480p HLS generated successfully: {playlist_480p}")
        except Exception as e:
            logger.error(f"480p HLS generation failed: {e}")
            TaskMonitor.update_progress(self.request.id, 50, f"480p Encoding failed: {e}", "Error")
            raise
        
        if not video_meta.duration_seconds:
            TaskMonitor.update_progress(self.request.id, 90, "Cataloging video technical details (duration)...", "Metadata Extraction")
            video_meta.duration_seconds = processor.get_duration(input_path)
        
        # --- NEW: Generate thumbnail if missing ---
        if not video_meta.content_item.thumbnail:
            try:
                TaskMonitor.update_progress(self.request.id, None, "Capturing video thumbnail...", "Thumbnail Generation")
                thumb_filename = f"thumb_{content_uuid}.jpg"
                temp_thumb_path = os.path.join(tempfile.gettempdir(), thumb_filename)
                
                processor.generate_thumbnail(input_path, temp_thumb_path)
                
                if os.path.exists(temp_thumb_path):
                    with open(temp_thumb_path, 'rb') as f:
                        video_meta.content_item.thumbnail.save(thumb_filename, File(f), save=True)
                    
                    # Cleanup temp thumb
                    os.remove(temp_thumb_path)
                    logger.info(f"Auto-generated thumbnail for video: {content_uuid}")
            except Exception as e:
                logger.error(f"Auto-thumbnail generation failed for video {content_uuid}: {e}")
        
        # --- NEW: Upload thumbnail to R2 if available but not uploaded ---
        if video_meta.content_item.thumbnail and not video_meta.content_item.r2_thumbnail_url:
            try:
                r2 = R2Service()
                r2.upload_thumbnail(video_meta.content_item)
            except Exception as e:
                logger.error(f"Failed to upload video thumbnail to R2 for {content_uuid}: {e}")
        
        video_meta.processing_status = 'completed'
        video_meta.save()
        
        # Update ContentItem processing status
        video_meta.content_item.processing_status = 'completed'
        video_meta.content_item.save(update_fields=['processing_status'])
        job_advance(video_meta.content_item.id, 'r2_upload')

        TaskMonitor.update_progress(self.request.id, 92, "Video processed. Starting AI enrichment and cloud delivery...", "Finalizing")
        
        upload_video_to_r2.delay(str(video_meta.id))
        generate_seo_metadata_task.delay(str(video_meta.content_item.id))
        logger.info(f"Triggered R2 upload for video: {video_meta.id}")
        
        
        
        TaskMonitor.update_task_status(self.request.id, 'SUCCESS', {'message': 'Video processing complete. AI and Cloud tasks started.', 'progress': 100})
        
        return {
            'status': 'success',
            'video_id': str(video_meta.content_item.id),
            'hls_720p': video_meta.hls_720p_path,
            'hls_480p': video_meta.hls_480p_path
        }
        
    except VideoMeta.DoesNotExist:
        logger.error(f"VideoMeta with id {video_meta_id} not found")
        return {'status': 'error', 'message': 'Video not found'}
    
    except DependencyError as e:
        logger.error(f"Video processing dependencies not available: {e}")
        try:
            video_meta = VideoMeta.objects.get(id=video_meta_id)
            video_meta.processing_status = 'failed'
            video_meta.save()
            job_fail(video_meta.content_item.id, 'file_processing', e)
            
            # Update ContentItem status
            video_meta.content_item.processing_status = 'failed'
            video_meta.content_item.save(update_fields=['processing_status'])
        except:
            pass
        return {'status': 'error', 'message': f'Dependencies missing: {e}'}
        
    except Exception as e:
        logger.error(f"Video processing failed: {e}")
        
        # Update status to failed
        try:
            video_meta = VideoMeta.objects.get(id=video_meta_id)
            video_meta.processing_status = 'failed'
            video_meta.save()
            job_fail(video_meta.content_item.id, 'file_processing', e)
            
            # Update ContentItem status
            video_meta.content_item.processing_status = 'failed'
            video_meta.content_item.save(update_fields=['processing_status'])
        except:
            pass
        
        # Don't retry for dependency errors
        if isinstance(e, DependencyError):
            return {'status': 'error', 'message': str(e)}
        
        # Retry the task if we haven't exceeded max retries
        if self.request.retries < self.max_retries:
            logger.info(f"Retrying video processing (attempt {self.request.retries + 1})")
            raise self.retry(countdown=60 * (2 ** self.request.retries))
        
        return {'status': 'error', 'message': str(e)}
    finally:
        if source_cleanup_path and os.path.exists(source_cleanup_path):
            os.remove(source_cleanup_path)


@shared_task(bind=True, max_retries=3)
def process_audio_compression(self, audio_meta_id):
    """Process uploaded audio with compression"""
    AudioMeta = apps.get_model('media_manager', 'AudioMeta')
    source_cleanup_path = None
    try:
        audio_meta = AudioMeta.objects.get(id=audio_meta_id)
        
        # Register task for monitoring
        TaskMonitor.register_task(
            task_id=self.request.id,
            task_name='Audio Compression',
            metadata={'audio_id': audio_meta_id, 'content_id': str(audio_meta.content_item.id)}
        )
        job_start(audio_meta.content_item.id, 'file_processing', self.request.id)
        
        # Check if there's actually a file to process
        if not audio_meta.original_file:
            logger.warning(f"No file to process for AudioMeta {audio_meta_id}")
            audio_meta.processing_status = 'completed'  # Mark as completed since there's nothing to do
            audio_meta.save()
            job_complete(audio_meta.content_item.id)
            TaskMonitor.update_task_status(self.request.id, 'SUCCESS', {'message': 'Skipped - no file'})
            return {'status': 'skipped', 'message': 'No file to process'}
        
        audio_meta.processing_status = 'processing'
        audio_meta.save()
        
        # Update ContentItem status
        audio_meta.content_item.processing_status = 'processing'
        audio_meta.content_item.save(update_fields=['processing_status'])
        
        TaskMonitor.update_progress(self.request.id, 5, "Setting up audio processing environment...", "Initialization")
        
        logger.info(f"Starting audio compression for: {audio_meta.content_item.title_ar}")
        
        try:
            processor = AudioProcessor()
        except DependencyError as e:
            logger.error(f"Audio processing dependencies not available: {e}")
            audio_meta.processing_status = 'failed'
            audio_meta.save()
            TaskMonitor.update_task_status(self.request.id, 'FAILURE', error=f'Dependencies missing: {e}')
            return {'status': 'error', 'message': f'Dependencies missing: {e}'}
        
        input_path, source_cleanup_path = _resolve_local_source_path(audio_meta.original_file, 'audio')
        
        # Generate compressed filename
        original_name = audio_meta.original_file.name
        compressed_filename = generate_unique_filename(original_name, 'audio')
        
        # Set up output path
        compressed_dir = Path(settings.MEDIA_ROOT) / 'compressed' / 'audio'
        os.makedirs(compressed_dir, exist_ok=True)
        output_path = compressed_dir / compressed_filename
        
        # Extract metadata from original file
        TaskMonitor.update_progress(self.request.id, 15, "Analyzing audio frequency and duration...", "Metadata Extraction")
        metadata = processor.extract_metadata(input_path)
        audio_meta.duration_seconds = metadata['duration']
        
        # Compress audio
        try:
            TaskMonitor.update_progress(self.request.id, 25, "Optimizing audio fidelity and file size...", "Compression")
            compressed_path, file_size = processor.compress_audio(
                input_path, output_path, target_bitrate='192k', max_size_mb=50
            )
            
            # Update audio meta with compressed file info
            audio_meta.compressed_file.name = f'compressed/audio/{compressed_filename}'
            audio_meta.bitrate = 192  # Target bitrate
            
            logger.info(f"Audio compressed successfully: {compressed_path} ({file_size/1024/1024:.1f}MB)")
            
        except Exception as e:
            logger.error(f"Audio compression failed: {e}")
            TaskMonitor.update_progress(self.request.id, 25, f"Compression failed: {e}", "Error")
            raise
        
        audio_meta.processing_status = 'completed'
        audio_meta.save()
        
        # Update ContentItem processing status
        audio_meta.content_item.processing_status = 'completed'
        audio_meta.content_item.save(update_fields=['processing_status'])
        job_advance(audio_meta.content_item.id, 'r2_upload')
        
        TaskMonitor.update_task_status(self.request.id, 'SUCCESS', {'message': 'Audio compression complete. AI and Cloud tasks started.', 'progress': 100})
        
        logger.info(f"Audio processing completed successfully for: {audio_meta.content_item.title_ar}")
        
        TaskMonitor.update_progress(self.request.id, 92, "Audio processed. Starting AI enrichment and cloud delivery...", "Finalizing")
    
        upload_audio_to_r2.delay(str(audio_meta.id))
        generate_seo_metadata_task.delay(str(audio_meta.content_item.id))
        logger.info(f"Triggered R2 upload for audio: {audio_meta.id}")
            
        return {
            'status': 'success',
            'audio_id': str(audio_meta.content_item.id),
            'compressed_file': audio_meta.compressed_file.name,
            'file_size': file_size
        }
        
    except AudioMeta.DoesNotExist:
        logger.error(f"AudioMeta with id {audio_meta_id} not found")
        return {'status': 'error', 'message': 'Audio not found'}
    
    except DependencyError as e:
        logger.error(f"Audio processing dependencies not available: {e}")
        try:
            audio_meta = AudioMeta.objects.get(id=audio_meta_id)
            audio_meta.processing_status = 'failed'
            audio_meta.save()
            job_fail(audio_meta.content_item.id, 'file_processing', e)
            
            # Update ContentItem status
            audio_meta.content_item.processing_status = 'failed'
            audio_meta.content_item.save(update_fields=['processing_status'])
        except:
            pass
        return {'status': 'error', 'message': f'Dependencies missing: {e}'}
        
    except Exception as e:
        logger.error(f"Audio processing failed: {e}")
        
        # Update status to failed
        try:
            audio_meta = AudioMeta.objects.get(id=audio_meta_id)
            audio_meta.processing_status = 'failed'
            audio_meta.save()
            job_fail(audio_meta.content_item.id, 'file_processing', e)
            
            # Update ContentItem status
            audio_meta.content_item.processing_status = 'failed'
            audio_meta.content_item.save(update_fields=['processing_status'])
        except:
            pass
        
        # Don't retry for dependency errors
        if isinstance(e, DependencyError):
            return {'status': 'error', 'message': str(e)}
        
        # Retry the task if we haven't exceeded max retries
        if self.request.retries < self.max_retries:
            logger.info(f"Retrying audio processing (attempt {self.request.retries + 1})")
            raise self.retry(countdown=60 * (2 ** self.request.retries))
        
        return {'status': 'error', 'message': str(e)}
    finally:
        if source_cleanup_path and os.path.exists(source_cleanup_path):
            os.remove(source_cleanup_path)

def _generate_pdf_thumbnail(processor, input_path, pdf_meta_id, content_item):
    """Generate and optionally upload a PDF thumbnail."""
    try:
        thumb_filename = f"thumb_{pdf_meta_id}.jpg"
        temp_thumb_path = os.path.join(tempfile.gettempdir(), thumb_filename)

        processor.generate_thumbnail(input_path, temp_thumb_path)

        if os.path.exists(temp_thumb_path) and os.path.getsize(temp_thumb_path) > 0:
            with open(temp_thumb_path, 'rb') as f:
                content_item.thumbnail.save(thumb_filename, File(f), save=True)

            try:
                r2_service = DjangoR2Service()
                r2_service.upload_thumbnail(content_item)
            except Exception as r2_err:
                logger.error(f"Failed to upload PDF thumbnail to R2: {r2_err}")

            logger.info(f"Generated and saved thumbnail for PDF: {content_item.title_ar}")

        if os.path.exists(temp_thumb_path):
            os.remove(temp_thumb_path)

    except Exception as thumb_err:
        logger.error(f"Failed to generate PDF thumbnail for {pdf_meta_id}: {thumb_err}")


@shared_task(bind=True, max_retries=3)
def process_pdf(self, pdf_meta_id):
    """Unified PDF processing task (metadata extraction + indexing only)."""
    PdfMeta = apps.get_model('media_manager', 'PdfMeta')
    source_cleanup_path = None
    try:
        pdf_meta = PdfMeta.objects.get(id=pdf_meta_id)
        
        # Register task for monitoring
        TaskMonitor.register_task(
            task_id=self.request.id,
            task_name='PDF Processing',
            metadata={
                'pdf_id': pdf_meta_id,
                'content_id': str(pdf_meta.content_item.id),
            }
        )
        job_start(pdf_meta.content_item.id, 'file_processing', self.request.id)
        
        # Check if there's actually a file to process
        if not pdf_meta.original_file:
            logger.warning(f"No file to process for PdfMeta {pdf_meta_id}")
            pdf_meta.processing_status = 'completed'
            pdf_meta.save()
            job_complete(pdf_meta.content_item.id)
            TaskMonitor.update_task_status(self.request.id, 'SUCCESS', {'message': 'Skipped - no file'})
            return {'status': 'skipped', 'message': 'No file to process'}
        
        pdf_meta.processing_status = 'processing'
        pdf_meta.save()
        
        # Update ContentItem status
        pdf_meta.content_item.processing_status = 'processing'
        pdf_meta.content_item.save(update_fields=['processing_status'])
        
        TaskMonitor.update_progress(self.request.id, 5, "Setting up PDF processing environment...", "Initialization")
        
        logger.info(f"Starting PDF processing for: {pdf_meta.content_item.title_ar}")
        
        try:
            processor = PDFProcessor()
        except DependencyError as e:
            logger.error(f"PDF processing dependencies not available: {e}")
            pdf_meta.processing_status = 'failed'
            pdf_meta.save()
            TaskMonitor.update_task_status(self.request.id, 'FAILURE', error=f'Dependencies missing: {e}')
            return {'status': 'error', 'message': f'Dependencies missing: {e}'}
        
        input_path, source_cleanup_path = _resolve_local_source_path(pdf_meta.original_file, 'pdf')
        
        # Extract PDF info
        TaskMonitor.update_progress(self.request.id, 15, "Analyzing PDF structure and complexity...", "Metadata Extraction")
        pdf_info = processor.get_pdf_info(input_path)
        pdf_meta.file_size = pdf_info['file_size']
        pdf_meta.page_count = pdf_info['page_count']
        
        # Generate thumbnail if not already present
        content_item = pdf_meta.content_item
        if not content_item.thumbnail:
            _generate_pdf_thumbnail(processor, input_path, pdf_meta_id, content_item)

        TaskMonitor.update_progress(self.request.id, 30, "PDF metadata extracted. Preparing indexing pipeline...", "Processing")
        
        pdf_meta.processing_status = 'completed'
        pdf_meta.save()
        
        # Update ContentItem status
        pdf_meta.content_item.processing_status = 'completed'
        pdf_meta.content_item.save(update_fields=['processing_status'])
        job_advance(pdf_meta.content_item.id, 'text_extraction')
        
        TaskMonitor.update_task_status(self.request.id, 'SUCCESS', {'message': 'PDF processing complete', 'progress': 100})
        
        logger.info(f"PDF processing completed successfully for: {pdf_meta.content_item.title_ar}")
        
        # Trigger Text Extraction and Search Indexing sequentially
        from apps.media_manager.tasks import extract_and_index_contentitem
        TaskMonitor.update_progress(self.request.id, 90, "PDF processing complete. Starting text extraction for search...", "Indexing")
        extract_and_index_contentitem.delay(str(pdf_meta.content_item.id))
        
        return {
            'status': 'success',
            'pdf_id': str(pdf_meta.content_item.id),
            'file_size': pdf_meta.file_size,
            'page_count': pdf_meta.page_count,
        }
        
    except PdfMeta.DoesNotExist:
        logger.error(f"PdfMeta with id {pdf_meta_id} not found")
        return {'status': 'error', 'message': 'PDF not found'}
    
    except DependencyError as e:
        logger.error(f"PDF processing dependencies not available: {e}")
        try:
            pdf_meta = PdfMeta.objects.get(id=pdf_meta_id)
            pdf_meta.processing_status = 'failed'
            pdf_meta.save()
            job_fail(pdf_meta.content_item.id, 'file_processing', e)
            
            # Update ContentItem status
            pdf_meta.content_item.processing_status = 'failed'
            pdf_meta.content_item.save(update_fields=['processing_status'])
        except:
            pass
        return {'status': 'error', 'message': f'Dependencies missing: {e}'}
        
    except Exception as e:
        logger.error(f"PDF processing failed: {e}")
        
        # Update status to failed
        try:
            pdf_meta = PdfMeta.objects.get(id=pdf_meta_id)
            pdf_meta.processing_status = 'failed'
            pdf_meta.save()
            job_fail(pdf_meta.content_item.id, 'file_processing', e)
            
            # Update ContentItem status
            pdf_meta.content_item.processing_status = 'failed'
            pdf_meta.content_item.save(update_fields=['processing_status'])
        except:
            pass
        
        # Don't retry for dependency errors
        if isinstance(e, DependencyError):
            return {'status': 'error', 'message': str(e)}
        
        # Retry the task if we haven't exceeded max retries
        if self.request.retries < self.max_retries:
            logger.info(f"Retrying PDF processing (attempt {self.request.retries + 1})")
            raise self.retry(countdown=60 * (2 ** self.request.retries))
        
        return {'status': 'error', 'message': str(e)}
    finally:
        if source_cleanup_path and os.path.exists(source_cleanup_path):
            os.remove(source_cleanup_path)


@shared_task
def cleanup_failed_uploads():
    """
    Detect and recover stale processing jobs.

    A job is considered *stale* when it has been in 'processing' status for
    more than STALE_JOB_HOURS without any update.  We handle three pipeline
    stages:

    file_processing  — FFMPEG / PDF extraction still running  (retry once)
    r2_upload        — R2 cloud upload hung                    (mark failed)
    seo_generation   — Gemini call hung                        (mark failed + finalize)

    All time comparisons use ProcessingJob.updated_at so we measure how long
    the current active task has been running, not how long ago the item was
    created.
    """
    VideoMeta = apps.get_model('media_manager', 'VideoMeta')
    AudioMeta = apps.get_model('media_manager', 'AudioMeta')
    PdfMeta = apps.get_model('media_manager', 'PdfMeta')
    ContentItem = apps.get_model('media_manager', 'ContentItem')
    ProcessingJob = apps.get_model('media_manager', 'ProcessingJob')

    STALE_JOB_HOURS = 5
    stale_cutoff = timezone.now() - timedelta(hours=STALE_JOB_HOURS)
    total_cleaned = 0

    try:
        # ------------------------------------------------------------------ #
        # Stage 1 – file_processing stale (HLS encode / audio compress / PDF) #
        # ------------------------------------------------------------------ #
        stale_file_jobs = ProcessingJob.objects.filter(
            status='processing',
            current_stage='file_processing',
            updated_at__lt=stale_cutoff,
        ).select_related('content_item')

        for job in stale_file_jobs:
            content_item = job.content_item
            logger.warning(
                f"[stale] file_processing exceeded {STALE_JOB_HOURS}h for "
                f"item {content_item.id} ({content_item.title_ar})"
            )
            try:
                meta = content_item.get_meta_object()
                if meta and hasattr(meta, 'processing_status'):
                    meta.processing_status = 'failed'
                    meta.save(update_fields=['processing_status'])

                content_item.processing_status = 'failed'
                content_item.save(update_fields=['processing_status'])
                job_fail(content_item.id, 'file_processing', f'Stale: exceeded {STALE_JOB_HOURS}h processing limit')

                # Auto-retry once if never retried before
                if job.retry_count == 0 and meta:
                    job.retry_count = 1
                    job.status = 'pending'
                    job.current_stage = 'file_processing'
                    job.celery_task_id = ''
                    job.save(update_fields=['retry_count', 'status', 'current_stage', 'celery_task_id', 'updated_at'])

                    meta.processing_status = 'pending'
                    meta.save(update_fields=['processing_status'])
                    content_item.processing_status = 'pending'
                    content_item.save(update_fields=['processing_status'])

                    # Dispatch the correct re-processing task per content type
                    if content_item.content_type == 'video':
                        process_video_to_hls.delay(str(meta.id))
                    elif content_item.content_type == 'audio':
                        process_audio_compression.delay(str(meta.id))
                    elif content_item.content_type == 'pdf':
                        process_pdf.delay(str(meta.id))
                    logger.info(f"[stale] Auto-retried file_processing for item {content_item.id}")

                total_cleaned += 1
            except Exception as e:
                logger.error(f"[stale] Error handling stale file_processing for {content_item.id}: {e}")

        # ------------------------------------------------------------------ #
        # Stage 2 – r2_upload stale                                           #
        # ------------------------------------------------------------------ #
        stale_r2_jobs = ProcessingJob.objects.filter(
            status='processing',
            current_stage='r2_upload',
            updated_at__lt=stale_cutoff,
        ).select_related('content_item')

        for job in stale_r2_jobs:
            content_item = job.content_item
            logger.warning(
                f"[stale] r2_upload exceeded {STALE_JOB_HOURS}h for "
                f"item {content_item.id} ({content_item.title_ar})"
            )
            try:
                meta = content_item.get_meta_object()
                if meta and hasattr(meta, 'r2_upload_status') and meta.r2_upload_status == 'uploading':
                    meta.r2_upload_status = 'failed'
                    meta.r2_upload_progress = 100
                    meta.save(update_fields=['r2_upload_status', 'r2_upload_progress'])
                job_fail(content_item.id, 'r2_upload', f'Stale: R2 upload exceeded {STALE_JOB_HOURS}h')
                total_cleaned += 1
            except Exception as e:
                logger.error(f"[stale] Error handling stale r2_upload for {content_item.id}: {e}")

        # ------------------------------------------------------------------ #
        # Stage 3 – seo_generation stale                                      #
        # ------------------------------------------------------------------ #
        stale_seo_jobs = ProcessingJob.objects.filter(
            status='processing',
            current_stage='seo_generation',
            updated_at__lt=stale_cutoff,
        ).select_related('content_item')

        for job in stale_seo_jobs:
            content_item = job.content_item
            logger.warning(
                f"[stale] seo_generation exceeded {STALE_JOB_HOURS}h for "
                f"item {content_item.id} ({content_item.title_ar})"
            )
            try:
                content_item.seo_processing_status = 'failed'
                content_item.save(update_fields=['seo_processing_status'])
                job_fail(content_item.id, 'seo_generation', f'Stale: SEO generation exceeded {STALE_JOB_HOURS}h')
                # Trigger finalize so local file cleanup and job completion still happen
                finalize_media_processing.delay(str(content_item.id))
                total_cleaned += 1
            except Exception as e:
                logger.error(f"[stale] Error handling stale seo_generation for {content_item.id}: {e}")

        # ------------------------------------------------------------------ #
        # Stage 4 – text_extraction stale (PDF only)                          #
        # ------------------------------------------------------------------ #
        stale_text_jobs = ProcessingJob.objects.filter(
            status='processing',
            current_stage='text_extraction',
            updated_at__lt=stale_cutoff,
        ).select_related('content_item')

        for job in stale_text_jobs:
            content_item = job.content_item
            logger.warning(
                f"[stale] text_extraction exceeded {STALE_JOB_HOURS}h for "
                f"item {content_item.id} ({content_item.title_ar})"
            )
            try:
                job_fail(content_item.id, 'text_extraction', f'Stale: text extraction exceeded {STALE_JOB_HOURS}h')
                # Continue pipeline: text extraction failure should not block R2 upload
                meta = content_item.get_meta_object()
                if meta:
                    job_advance(content_item.id, 'r2_upload')
                    upload_pdf_to_r2.delay(str(meta.id))
                total_cleaned += 1
            except Exception as e:
                logger.error(f"[stale] Error handling stale text_extraction for {content_item.id}: {e}")

        logger.info(f"[stale cleanup] Processed {total_cleaned} stale job(s).")
        return {'status': 'success', 'cleaned_items': total_cleaned}

    except Exception as e:
        logger.error(f"cleanup_failed_uploads task failed: {e}")
        return {'status': 'error', 'message': str(e)}


# R2 Upload Tasks

@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def upload_video_to_r2(self, video_meta_id):
    """
    Upload processed video files to Cloudflare R2
    Args:
        video_meta_id: UUID of VideoMeta instance
    """
    try:
        video_meta = VideoMeta.objects.get(id=video_meta_id)
        logger.info(f"Starting R2 upload for video: {video_meta_id}")
        job_start(video_meta.content_item.id, 'r2_upload', self.request.id)
        
        # Check if video processing is completed
        if video_meta.processing_status != 'completed':
            logger.warning(f"Video {video_meta_id} not ready for R2 upload (status: {video_meta.processing_status})")
            # Retry in case processing completes later
            raise self.retry(countdown=120, max_retries=5)
        
        # Initialize R2 service
        r2_service = R2Service()
        
        # Update status to uploading
        video_meta.r2_upload_status = 'uploading'
        video_meta.r2_upload_progress = 0
        video_meta.save(update_fields=['r2_upload_status', 'r2_upload_progress'])
        
        # Upload original video file
        original_upload_success = r2_service.upload_video_file(video_meta)
        if not original_upload_success:
            logger.error(f"Original video upload failed for {video_meta_id}")
        
        # Upload HLS files if they exist
        if video_meta.hls_720p_path or video_meta.hls_480p_path:
            # Upload HLS playlist and segments
            success = r2_service.upload_hls_video(video_meta)
            
            if success:
                video_meta.r2_upload_status = 'completed'
                video_meta.r2_upload_progress = 100
                logger.info(f"Successfully uploaded video {video_meta_id} to R2")
                
                # Issue 3: Automatic Activation After R2 Upload
                content_item = video_meta.content_item
                if not content_item.is_active:
                    content_item.is_active = True
                    content_item.save(update_fields=['is_active'])
                    logger.info(f"Automatically activated ContentItem {content_item.id} after successful R2 upload")
            else:
                video_meta.r2_upload_status = 'failed'
                video_meta.r2_upload_progress = 100  # Ensure progress reaches 100% even on failure
                logger.error(f"Failed to upload video {video_meta_id} to R2")
        else:
            # No HLS files to upload, but original might have been uploaded
            logger.warning(f"No HLS files found for video {video_meta_id}")
            if video_meta.r2_original_file_url:
                video_meta.r2_upload_status = 'completed'
                video_meta.r2_upload_progress = 100
                
                # Issue 3: Automatic Activation After R2 Upload
                content_item = video_meta.content_item
                if not content_item.is_active:
                    content_item.is_active = True
                    content_item.save(update_fields=['is_active'])
                    logger.info(f"Automatically activated ContentItem {content_item.id} after successful R2 upload")
            else:
                video_meta.r2_upload_status = 'local_only'
                video_meta.r2_upload_progress = 100  # Mark as complete for local-only storage

        if not original_upload_success and not (video_meta.r2_hls_720p_url or video_meta.r2_hls_480p_url):
            raise Exception("Original video upload to R2 failed")
        
        video_meta.save(update_fields=['r2_upload_status', 'r2_upload_progress'])
        
        if video_meta.r2_upload_status == 'completed':
            finalize_media_processing.delay(str(video_meta.content_item.id))
        
    except VideoMeta.DoesNotExist:
        logger.error(f"VideoMeta {video_meta_id} not found")
        return {'status': 'error', 'message': 'VideoMeta not found'}
        
    except Exception as exc:
        logger.error(f"R2 upload failed for video {video_meta_id}: {str(exc)}", exc_info=True)
        
        # Update status to failed with 100% progress to unblock UI
        try:
            video_meta = VideoMeta.objects.get(id=video_meta_id)
            video_meta.r2_upload_status = 'failed'
            video_meta.r2_upload_progress = 100  # Always set to 100% on final failure
            video_meta.save(update_fields=['r2_upload_status', 'r2_upload_progress'])
            job_fail(video_meta.content_item.id, 'r2_upload', exc)
        except:
            pass
            
        # Retry with exponential backoff
        try:
            countdown = 60 * (2 ** self.request.retries)
            self.retry(countdown=countdown)
        except self.MaxRetriesExceededError:
            logger.error(f"Max retries exceeded for video {video_meta_id} R2 upload. Progress set to 100%.")
            # Ensure progress is 100% on max retries exceeded
            try:
                video_meta = VideoMeta.objects.get(id=video_meta_id)
                video_meta.r2_upload_status = 'failed'
                video_meta.r2_upload_progress = 100
                video_meta.save(update_fields=['r2_upload_status', 'r2_upload_progress'])
                job_fail(video_meta.content_item.id, 'r2_upload', exc)
            except:
                pass
            return {'status': 'failed', 'message': 'Max retries exceeded', 'progress': 100}


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def upload_audio_to_r2(self, audio_meta_id):
    """
    Upload processed audio files to Cloudflare R2
    Args:
        audio_meta_id: UUID of AudioMeta instance
    """
    try:
        audio_meta = AudioMeta.objects.get(id=audio_meta_id)
        logger.info(f"Starting R2 upload for audio: {audio_meta_id}")
        job_start(audio_meta.content_item.id, 'r2_upload', self.request.id)
        
        # Check if audio processing is completed
        if audio_meta.processing_status not in ['completed', 'pending']:
            logger.warning(f"Audio {audio_meta_id} not ready for R2 upload (status: {audio_meta.processing_status})")
            raise self.retry(countdown=60, max_retries=3)
        
        # Initialize R2 service
        r2_service = R2Service()
        
        # Update status to uploading
        audio_meta.r2_upload_status = 'uploading'
        audio_meta.r2_upload_progress = 0
        audio_meta.save(update_fields=['r2_upload_status', 'r2_upload_progress'])
        
        # Upload audio file
        success = r2_service.upload_audio_file(audio_meta)
        
        if success:
            audio_meta.r2_upload_status = 'completed'
            audio_meta.r2_upload_progress = 100
            logger.info(f"Successfully uploaded audio {audio_meta_id} to R2")
            
            # Issue 3: Automatic Activation After R2 Upload
            content_item = audio_meta.content_item
            if not content_item.is_active:
                content_item.is_active = True
                content_item.save(update_fields=['is_active'])
                logger.info(f"Automatically activated ContentItem {content_item.id} after successful R2 upload")
        else:
            audio_meta.r2_upload_status = 'failed'
            audio_meta.r2_upload_progress = 100  # Ensure progress reaches 100% even on failure
            logger.error(f"Failed to upload audio {audio_meta_id} to R2")
        
        audio_meta.save(update_fields=['r2_upload_status', 'r2_upload_progress'])
        
        if audio_meta.r2_upload_status == 'completed':
            finalize_media_processing.delay(str(audio_meta.content_item.id))
        
    except AudioMeta.DoesNotExist:
        logger.error(f"AudioMeta {audio_meta_id} not found")
        return {'status': 'error', 'message': 'AudioMeta not found'}
        
    except Exception as exc:
        logger.error(f"R2 upload failed for audio {audio_meta_id}: {str(exc)}", exc_info=True)
        
        # Update status to failed with 100% progress to unblock UI
        try:
            audio_meta = AudioMeta.objects.get(id=audio_meta_id)
            audio_meta.r2_upload_status = 'failed'
            audio_meta.r2_upload_progress = 100  # Always set to 100% on final failure
            audio_meta.save(update_fields=['r2_upload_status', 'r2_upload_progress'])
            job_fail(audio_meta.content_item.id, 'r2_upload', exc)
        except:
            pass
            
        # Retry with exponential backoff
        try:
            countdown = 60 * (2 ** self.request.retries)
            self.retry(countdown=countdown)
        except self.MaxRetriesExceededError:
            logger.error(f"Max retries exceeded for audio {audio_meta_id} R2 upload. Progress set to 100%.")
            # Ensure progress is 100% on max retries exceeded
            try:
                audio_meta = AudioMeta.objects.get(id=audio_meta_id)
                audio_meta.r2_upload_status = 'failed'
                audio_meta.r2_upload_progress = 100
                audio_meta.save(update_fields=['r2_upload_status', 'r2_upload_progress'])
                job_fail(audio_meta.content_item.id, 'r2_upload', exc)
            except:
                pass
            return {'status': 'failed', 'message': 'Max retries exceeded', 'progress': 100}


@shared_task(bind=True, max_retries=5, default_retry_delay=60)
def upload_pdf_to_r2(self, pdf_meta_id):
    """
    Upload processed PDF files to Cloudflare R2 with improved bulk processing support.
    Enhanced with concurrency control, rate limiting, and resource management.
    Args:
        pdf_meta_id: UUID of PdfMeta instance
    """
    concurrent_uploads_key = 'r2_pdf_uploads_active'
    max_concurrent_uploads = getattr(settings, 'R2_MAX_CONCURRENT_PDF_UPLOADS', 3)
    slot_acquired = False
    
    try:
        pdf_meta = PdfMeta.objects.get(id=pdf_meta_id)
        logger.info(f"Starting R2 upload for PDF: {pdf_meta_id} (attempt {self.request.retries + 1})")
        logger.info(f"PDF processing status: {pdf_meta.processing_status}, R2 status: {pdf_meta.r2_upload_status}")
        job_start(pdf_meta.content_item.id, 'r2_upload', self.request.id)
        
        # Check if PDF processing is completed
        if pdf_meta.processing_status not in ['completed', 'pending']:
            logger.warning(f"PDF {pdf_meta_id} not ready for R2 upload (status: {pdf_meta.processing_status})")
            raise self.retry(countdown=60, max_retries=3)
        
        # Skip if already completed or uploading
        if pdf_meta.r2_upload_status == 'completed':
            logger.info(f"PDF {pdf_meta_id} already uploaded to R2, skipping")
            return {'status': 'already_completed', 'message': 'Already uploaded to R2'}
        
        # Concurrency control - wait if too many uploads are active
        current_uploads = cache.get(concurrent_uploads_key, 0)
        if current_uploads >= max_concurrent_uploads:
            # Add random jitter to prevent thundering herd
            jitter_delay = random.randint(30, 120)
            logger.info(f"Too many concurrent R2 uploads ({current_uploads}/{max_concurrent_uploads}). Retrying in {jitter_delay}s")
            raise self.retry(countdown=jitter_delay, max_retries=self.max_retries)
        
        # Acquire upload slot
        cache.set(concurrent_uploads_key, current_uploads + 1, timeout=600)  # 10 minute timeout
        slot_acquired = True
        
        try:
            # Update status to uploading
            pdf_meta.r2_upload_status = 'uploading'
            pdf_meta.r2_upload_progress = 0
            pdf_meta.save(update_fields=['r2_upload_status', 'r2_upload_progress'])
            
            # Initialize R2 service and yield worker slot on transient init failures.
            try:
                r2_service = R2Service()
                logger.info(f"R2 service initialized, use_r2: {r2_service.use_r2}")
            except Exception as init_exc:
                logger.warning(f"R2 service init failed for PDF {pdf_meta_id}: {init_exc}")
                base_delay = 30 * (2 ** self.request.retries)
                jitter = random.randint(0, 15)
                raise self.retry(exc=init_exc, countdown=base_delay + jitter)
            
            # Update progress
            pdf_meta.r2_upload_progress = 10
            pdf_meta.save(update_fields=['r2_upload_progress'])
            
            # Upload PDF file with better error handling
            logger.info(f"Starting R2 upload for PDF {pdf_meta_id}")
            success = r2_service.upload_pdf_file(pdf_meta)
            
            if success:
                pdf_meta.r2_upload_status = 'completed'
                pdf_meta.r2_upload_progress = 100
                logger.info(f"Successfully uploaded PDF {pdf_meta_id} to R2")

                content_item = pdf_meta.content_item
                if not content_item.is_active:
                    content_item.is_active = True
                    content_item.save(update_fields=['is_active'])
                    logger.info(f"Automatically activated ContentItem {content_item.id} after successful R2 upload")

                pdf_meta.save(update_fields=['r2_upload_status', 'r2_upload_progress'])

                if pdf_meta.r2_upload_status == 'completed':
                    finalize_media_processing.delay(str(pdf_meta.content_item.id))

                return {'status': 'success', 'message': f'PDF {pdf_meta_id} uploaded to R2 successfully'}
            else:
                pdf_meta.r2_upload_status = 'failed'
                pdf_meta.r2_upload_progress = 100  # Ensure progress reaches 100% even on failure
                logger.error(f"❌ Failed to upload PDF {pdf_meta_id} to R2")
                raise Exception("R2 upload_pdf_file returned False")
        
        finally:
            # Always release the upload slot
            if slot_acquired:
                try:
                    current = cache.get(concurrent_uploads_key, 0)
                    cache.set(concurrent_uploads_key, max(0, current - 1), timeout=600)
                except Exception as e:
                    logger.warning(f"Failed to release upload slot: {e}")
        
        pdf_meta.save(update_fields=['r2_upload_status', 'r2_upload_progress'])
        
    except PdfMeta.DoesNotExist:
        logger.error(f"PdfMeta {pdf_meta_id} not found")
        return {'status': 'error', 'message': 'PdfMeta not found'}
        
    except Exception as exc:
        logger.error(f"R2 upload failed for PDF {pdf_meta_id}: {str(exc)}", exc_info=True)
        
        # Update status to failed with 100% progress to unblock UI
        try:
            pdf_meta = PdfMeta.objects.get(id=pdf_meta_id)
            if pdf_meta.r2_upload_status != 'completed':  # Don't override completed status
                pdf_meta.r2_upload_status = 'failed'
                pdf_meta.r2_upload_progress = 100  # Always set to 100% on final failure
                pdf_meta.save(update_fields=['r2_upload_status', 'r2_upload_progress'])
                job_fail(pdf_meta.content_item.id, 'r2_upload', exc)
        except:
            pass
            
        # Enhanced retry logic with jittered backoff
        try:
            # Add jitter to prevent thundering herd during bulk processing
            base_countdown = 60 * (2 ** self.request.retries)
            jitter = random.randint(0, 30)  # 0-30 second jitter
            countdown = base_countdown + jitter
            
            logger.info(f"Retrying PDF {pdf_meta_id} R2 upload in {countdown}s (attempt {self.request.retries + 1}/{self.max_retries})")
            self.retry(countdown=countdown)
        except self.MaxRetriesExceededError:
            logger.error(f"❌ Max retries exceeded for PDF {pdf_meta_id} R2 upload. Marking as failed.")
            # Ensure progress is 100% on max retries exceeded
            try:
                pdf_meta = PdfMeta.objects.get(id=pdf_meta_id)
                pdf_meta.r2_upload_status = 'failed'
                pdf_meta.r2_upload_progress = 100
                pdf_meta.save(update_fields=['r2_upload_status', 'r2_upload_progress'])
                job_fail(pdf_meta.content_item.id, 'r2_upload', exc)
            except:
                pass
            return {'status': 'failed', 'message': 'Max retries exceeded', 'progress': 100}