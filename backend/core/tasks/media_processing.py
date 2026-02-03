from celery import shared_task
from django.conf import settings
from django.apps import apps
import os
from pathlib import Path
import logging
from apps.core.task_monitor import TaskMonitor

from core.utils.media_processing import (
    VideoProcessor, AudioProcessor, PDFProcessor,
    generate_unique_filename, DependencyError
)

logger = logging.getLogger(__name__)

@shared_task
def delete_files_task(paths):
    """
    Delete files or folders from the filesystem asynchronously.
    Accepts a list of absolute file/folder paths.
    """
    import shutil
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


@shared_task(bind=True, max_retries=3)
def process_video_to_hls(self, video_meta_id):
    """Process uploaded video to HLS format with multiple resolutions"""
    VideoMeta = apps.get_model('media_manager', 'VideoMeta')
    try:
        video_meta = VideoMeta.objects.get(id=video_meta_id)
        
        # Register task for monitoring
        TaskMonitor.register_task(
            task_id=self.request.id,
            task_name='Video HLS Processing',
            metadata={'video_id': video_meta_id, 'content_id': str(video_meta.content_item.id)}
        )
        
        # Check if there's actually a file to process
        if not video_meta.original_file:
            logger.warning(f"No file to process for VideoMeta {video_meta_id}")
            video_meta.processing_status = 'completed'
            video_meta.save()
            
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
        
        input_path = video_meta.original_file.path
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
        
        # Extract video metadata if not already set
        if not video_meta.duration_seconds:
            TaskMonitor.update_progress(self.request.id, 90, "Cataloging video technical details (duration)...", "Metadata Extraction")
            video_meta.duration_seconds = processor.get_duration(input_path)
        
        video_meta.processing_status = 'completed'
        video_meta.save()
        
        # Parallel Trigger: Trigger SEO generation and R2 upload at the same time
        from apps.media_manager.tasks import generate_seo_metadata_task
        TaskMonitor.update_progress(self.request.id, 92, "Video processed. Starting AI enrichment and cloud delivery...", "Finalizing")
        
        # 2. Trigger R2 upload
        if getattr(settings, 'R2_ENABLED', False):
            upload_video_to_r2.delay(str(video_meta.id))
            logger.info(f"Triggered parallel R2 upload for video: {video_meta.id}")

        # 1. Trigger SEO generation
        generate_seo_metadata_task.delay(str(video_meta.content_item.id))
        
        
        
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


@shared_task(bind=True, max_retries=3)
def process_audio_compression(self, audio_meta_id):
    """Process uploaded audio with compression"""
    AudioMeta = apps.get_model('media_manager', 'AudioMeta')
    try:
        audio_meta = AudioMeta.objects.get(id=audio_meta_id)
        
        # Register task for monitoring
        TaskMonitor.register_task(
            task_id=self.request.id,
            task_name='Audio Compression',
            metadata={'audio_id': audio_meta_id, 'content_id': str(audio_meta.content_item.id)}
        )
        
        # Check if there's actually a file to process
        if not audio_meta.original_file:
            logger.warning(f"No file to process for AudioMeta {audio_meta_id}")
            audio_meta.processing_status = 'completed'  # Mark as completed since there's nothing to do
            audio_meta.save()
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
        
        input_path = audio_meta.original_file.path
        
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
        
        TaskMonitor.update_task_status(self.request.id, 'SUCCESS', {'message': 'Audio compression complete. AI and Cloud tasks started.', 'progress': 100})
        
        logger.info(f"Audio processing completed successfully for: {audio_meta.content_item.title_ar}")
        
        # Parallel Trigger: Trigger SEO generation and R2 upload at the same time
        from apps.media_manager.tasks import generate_seo_metadata_task
        TaskMonitor.update_progress(self.request.id, 92, "Audio processed. Starting AI enrichment and cloud delivery...", "Finalizing")
    
        # 2. Trigger R2 upload
        if getattr(settings, 'R2_ENABLED', False):
            upload_audio_to_r2.delay(str(audio_meta.id))
            logger.info(f"Triggered parallel R2 upload for audio: {audio_meta.id}")

        # 1. Trigger SEO generation
        generate_seo_metadata_task.delay(str(audio_meta.content_item.id))
            
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


@shared_task(bind=True, max_retries=3)
def process_pdf_optimization(self, pdf_meta_id):
    """Process uploaded PDF with optimization"""
    PdfMeta = apps.get_model('media_manager', 'PdfMeta')
    try:
        pdf_meta = PdfMeta.objects.get(id=pdf_meta_id)
        
        # Register task for monitoring
        TaskMonitor.register_task(
            task_id=self.request.id,
            task_name='PDF Optimization',
            metadata={'pdf_id': pdf_meta_id, 'content_id': str(pdf_meta.content_item.id)}
        )
        
        # Check if there's actually a file to process
        if not pdf_meta.original_file:
            logger.warning(f"No file to process for PdfMeta {pdf_meta_id}")
            pdf_meta.processing_status = 'completed'
            pdf_meta.save()
            TaskMonitor.update_task_status(self.request.id, 'SUCCESS', {'message': 'Skipped - no file'})
            return {'status': 'skipped', 'message': 'No file to process'}
        
        pdf_meta.processing_status = 'processing'
        pdf_meta.save()
        
        # Update ContentItem status
        pdf_meta.content_item.processing_status = 'processing'
        pdf_meta.content_item.save(update_fields=['processing_status'])
        
        TaskMonitor.update_progress(self.request.id, 5, "Setting up PDF processing environment...", "Initialization")
        
        logger.info(f"Starting PDF optimization for: {pdf_meta.content_item.title_ar}")
        
        try:
            processor = PDFProcessor()
        except DependencyError as e:
            logger.error(f"PDF processing dependencies not available: {e}")
            pdf_meta.processing_status = 'failed'
            pdf_meta.save()
            TaskMonitor.update_task_status(self.request.id, 'FAILURE', error=f'Dependencies missing: {e}')
            return {'status': 'error', 'message': f'Dependencies missing: {e}'}
        
        input_path = pdf_meta.original_file.path
        
        # Extract PDF info
        TaskMonitor.update_progress(self.request.id, 15, "Analyzing PDF structure and complexity...", "Metadata Extraction")
        pdf_info = processor.get_pdf_info(input_path)
        pdf_meta.file_size = pdf_info['file_size']
        pdf_meta.page_count = pdf_info['page_count']
        
        # Generate optimized filename
        original_name = pdf_meta.original_file.name
        optimized_filename = generate_unique_filename(original_name, 'pdf')
        
        # Set up output path
        optimized_dir = Path(settings.MEDIA_ROOT) / 'optimized' / 'pdf'
        os.makedirs(optimized_dir, exist_ok=True)
        output_path = optimized_dir / optimized_filename
        
        # Optimize PDF (optional - only if file is large)
        original_size = pdf_info['file_size']
        if original_size > 10 * 1024 * 1024:  # 10MB threshold
            try:
                TaskMonitor.update_progress(self.request.id, 30, "Reducing PDF file size for faster loading...", "Optimization")
                optimized_path = processor.optimize_pdf(input_path, output_path)
                optimized_size = os.path.getsize(optimized_path)
                
                # Only use optimized version if it's significantly smaller
                if optimized_size < original_size * 0.8:
                    pdf_meta.optimized_file.name = f'optimized/pdf/{optimized_filename}'
                    logger.info(f"PDF optimized: {original_size/1024/1024:.1f}MB -> {optimized_size/1024/1024:.1f}MB")
                else:
                    # Remove optimized file if no significant improvement
                    os.remove(optimized_path)
                    logger.info("PDF optimization provided no significant benefit, keeping original")
                    
            except Exception as e:
                logger.warning(f"PDF optimization failed, keeping original: {e}")
                TaskMonitor.update_progress(self.request.id, 30, f"Optimization skipped: {e}", "Warning")
        else:
            logger.info("PDF size acceptable, no optimization needed")
        
        pdf_meta.processing_status = 'completed'
        pdf_meta.save()
        
        # Update ContentItem status
        pdf_meta.content_item.processing_status = 'completed'
        pdf_meta.content_item.save(update_fields=['processing_status'])
        
        TaskMonitor.update_task_status(self.request.id, 'SUCCESS', {'message': 'PDF processing complete', 'progress': 100})
        
        logger.info(f"PDF processing completed successfully for: {pdf_meta.content_item.title_ar}")
        
        # Trigger Text Extraction and Search Indexing sequentially
        from apps.media_manager.tasks import extract_and_index_contentitem
        TaskMonitor.update_progress(self.request.id, 90, "Optimization complete. Starting text extraction for search...", "Indexing")
        extract_and_index_contentitem.delay(str(pdf_meta.content_item.id))
        
        return {
            'status': 'success',
            'pdf_id': str(pdf_meta.content_item.id),
            'file_size': pdf_meta.file_size,
            'page_count': pdf_meta.page_count,
            'optimized': bool(pdf_meta.optimized_file)
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


@shared_task
def cleanup_failed_uploads():
    """Clean up files from failed processing tasks"""
    VideoMeta = apps.get_model('media_manager', 'VideoMeta')
    AudioMeta = apps.get_model('media_manager', 'AudioMeta')
    PdfMeta = apps.get_model('media_manager', 'PdfMeta')
    try:
        # Find items that have been in 'processing' state for more than 1 hour
        from django.utils import timezone
        from datetime import timedelta
        
        cutoff_time = timezone.now() - timedelta(hours=1)
        
        # Clean up video processing failures
        failed_videos = VideoMeta.objects.filter(
            processing_status='processing',
            content_item__created_at__lt=cutoff_time
        )
        
        for video in failed_videos:
            video.processing_status = 'failed'
            video.save()
            video.content_item.processing_status = 'failed'
            video.content_item.save(update_fields=['processing_status'])
            logger.info(f"Marked video as failed: {video.content_item.title_ar}")
        
        # Clean up audio processing failures
        failed_audios = AudioMeta.objects.filter(
            processing_status='processing',
            content_item__created_at__lt=cutoff_time
        )
        
        for audio in failed_audios:
            audio.processing_status = 'failed'
            audio.save()
            audio.content_item.processing_status = 'failed'
            audio.content_item.save(update_fields=['processing_status'])
            logger.info(f"Marked audio as failed: {audio.content_item.title_ar}")
        
        # Clean up PDF processing failures
        failed_pdfs = PdfMeta.objects.filter(
            processing_status='processing',
            content_item__created_at__lt=cutoff_time
        )
        
        for pdf in failed_pdfs:
            pdf.processing_status = 'failed'
            pdf.save()
            pdf.content_item.processing_status = 'failed'
            pdf.content_item.save(update_fields=['processing_status'])
            logger.info(f"Marked PDF as failed: {pdf.content_item.title_ar}")
            pdf.save()
            logger.info(f"Marked PDF as failed: {pdf.content_item.title_ar}")
        
        return {'status': 'success', 'cleaned_items': len(failed_videos) + len(failed_audios) + len(failed_pdfs)}
        
    except Exception as e:
        logger.error(f"Cleanup task failed: {e}")
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
        from core.storage_backends import R2Service
        from apps.media_manager.models import VideoMeta
        
        video_meta = VideoMeta.objects.get(id=video_meta_id)
        logger.info(f"Starting R2 upload for video: {video_meta_id}")
        
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
        r2_service.upload_video_file(video_meta)
        
        # Upload HLS files if they exist
        if video_meta.hls_720p_path or video_meta.hls_480p_path:
            # Upload HLS playlist and segments
            success = r2_service.upload_hls_video(video_meta)
            
            if success:
                video_meta.r2_upload_status = 'completed'
                video_meta.r2_upload_progress = 100
                logger.info(f"Successfully uploaded video {video_meta_id} to R2")
                
                # Check for cleanup (both R2 and SEO must be done)
                from apps.media_manager.tasks import finalize_media_processing
                finalize_media_processing.delay(str(video_meta.content_item.id))
            else:
                video_meta.r2_upload_status = 'failed'
                logger.error(f"Failed to upload video {video_meta_id} to R2")
        else:
            # No HLS files to upload, but original might have been uploaded
            logger.warning(f"No HLS files found for video {video_meta_id}")
            if video_meta.r2_original_file_url:
                video_meta.r2_upload_status = 'completed'
                
                # Check for cleanup
                from apps.media_manager.tasks import finalize_media_processing
                finalize_media_processing.delay(str(video_meta.content_item.id))
            else:
                video_meta.r2_upload_status = 'local_only'
        
        video_meta.save(update_fields=['r2_upload_status', 'r2_upload_progress'])
        
    except VideoMeta.DoesNotExist:
        logger.error(f"VideoMeta {video_meta_id} not found")
        return {'status': 'error', 'message': 'VideoMeta not found'}
        
    except Exception as exc:
        logger.error(f"R2 upload failed for video {video_meta_id}: {str(exc)}", exc_info=True)
        
        # Update status to failed
        try:
            video_meta = VideoMeta.objects.get(id=video_meta_id)
            video_meta.r2_upload_status = 'failed'
            video_meta.save(update_fields=['r2_upload_status'])
        except:
            pass
            
        # Retry with exponential backoff
        try:
            countdown = 60 * (2 ** self.request.retries)
            self.retry(countdown=countdown)
        except self.MaxRetriesExceededError:
            logger.error(f"Max retries exceeded for video {video_meta_id} R2 upload")
            return {'status': 'failed', 'message': 'Max retries exceeded'}


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def upload_audio_to_r2(self, audio_meta_id):
    """
    Upload processed audio files to Cloudflare R2
    Args:
        audio_meta_id: UUID of AudioMeta instance
    """
    try:
        from core.storage_backends import R2Service
        from apps.media_manager.models import AudioMeta
        
        audio_meta = AudioMeta.objects.get(id=audio_meta_id)
        logger.info(f"Starting R2 upload for audio: {audio_meta_id}")
        
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
            
            # Check for cleanup (both R2 and SEO must be done)
            from apps.media_manager.tasks import finalize_media_processing
            finalize_media_processing.delay(str(audio_meta.content_item.id))
        else:
            audio_meta.r2_upload_status = 'failed'
            logger.error(f"Failed to upload audio {audio_meta_id} to R2")
        
        audio_meta.save(update_fields=['r2_upload_status', 'r2_upload_progress'])
        
    except AudioMeta.DoesNotExist:
        logger.error(f"AudioMeta {audio_meta_id} not found")
        return {'status': 'error', 'message': 'AudioMeta not found'}
        
    except Exception as exc:
        logger.error(f"R2 upload failed for audio {audio_meta_id}: {str(exc)}", exc_info=True)
        
        # Update status to failed
        try:
            audio_meta = AudioMeta.objects.get(id=audio_meta_id)
            audio_meta.r2_upload_status = 'failed'
            audio_meta.save(update_fields=['r2_upload_status'])
        except:
            pass
            
        # Retry with exponential backoff
        try:
            countdown = 60 * (2 ** self.request.retries)
            self.retry(countdown=countdown)
        except self.MaxRetriesExceededError:
            logger.error(f"Max retries exceeded for audio {audio_meta_id} R2 upload")
            return {'status': 'failed', 'message': 'Max retries exceeded'}


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def upload_pdf_to_r2(self, pdf_meta_id):
    """
    Upload processed PDF files to Cloudflare R2
    Args:
        pdf_meta_id: UUID of PdfMeta instance
    """
    try:
        from core.storage_backends import R2Service
        from apps.media_manager.models import PdfMeta
        
        pdf_meta = PdfMeta.objects.get(id=pdf_meta_id)
        logger.info(f"Starting R2 upload for PDF: {pdf_meta_id}")
        logger.info(f"PDF processing status: {pdf_meta.processing_status}, R2 status: {pdf_meta.r2_upload_status}")
        
        # Check if PDF processing is completed
        if pdf_meta.processing_status not in ['completed', 'pending']:
            logger.warning(f"PDF {pdf_meta_id} not ready for R2 upload (status: {pdf_meta.processing_status})")
            raise self.retry(countdown=60, max_retries=3)
        
        # Initialize R2 service
        try:
            r2_service = R2Service()
            logger.info(f"R2 service initialized, use_r2: {r2_service.use_r2}")
        except Exception as e:
            logger.error(f"Failed to initialize R2 service: {e}")
            raise
        
        # Upload PDF file
        logger.info(f"About to call r2_service.upload_pdf_file for PDF {pdf_meta_id}")
        success = r2_service.upload_pdf_file(pdf_meta)
        logger.info(f"upload_pdf_file returned: {success} for PDF {pdf_meta_id}")
        
        if success:
            pdf_meta.r2_upload_status = 'completed'
            pdf_meta.r2_upload_progress = 100
            logger.info(f"Successfully uploaded PDF {pdf_meta_id} to R2")
            
            # Check for cleanup (both R2 and SEO must be done)
            from apps.media_manager.tasks import finalize_media_processing
            finalize_media_processing.delay(str(pdf_meta.content_item.id))
        else:
            pdf_meta.r2_upload_status = 'failed'
            logger.error(f"Failed to upload PDF {pdf_meta_id} to R2")
        
        pdf_meta.save(update_fields=['r2_upload_status', 'r2_upload_progress'])
        
    except PdfMeta.DoesNotExist:
        logger.error(f"PdfMeta {pdf_meta_id} not found")
        return {'status': 'error', 'message': 'PdfMeta not found'}
        
    except Exception as exc:
        logger.error(f"R2 upload failed for PDF {pdf_meta_id}: {str(exc)}", exc_info=True)
        
        # Update status to failed
        try:
            pdf_meta = PdfMeta.objects.get(id=pdf_meta_id)
            pdf_meta.r2_upload_status = 'failed'
            pdf_meta.save(update_fields=['r2_upload_status'])
        except:
            pass
            
        # Retry with exponential backoff
        try:
            countdown = 60 * (2 ** self.request.retries)
            self.retry(countdown=countdown)
        except self.MaxRetriesExceededError:
            logger.error(f"Max retries exceeded for PDF {pdf_meta_id} R2 upload")
            return {'status': 'failed', 'message': 'Max retries exceeded'}