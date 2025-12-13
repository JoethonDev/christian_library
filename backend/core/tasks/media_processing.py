from celery import shared_task
from django.core.files.storage import default_storage
from django.conf import settings
import os
from pathlib import Path
import logging

from core.utils.media_processing import (
    VideoProcessor, AudioProcessor, PDFProcessor,
    generate_unique_filename, get_storage_path, DependencyError
)
from apps.media_manager.models import VideoMeta, AudioMeta, PdfMeta, ContentItem

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
    try:
        video_meta = VideoMeta.objects.get(id=video_meta_id)
        
        # Check if there's actually a file to process
        if not video_meta.original_file:
            logger.warning(f"No file to process for VideoMeta {video_meta_id}")
            video_meta.processing_status = 'completed'
            video_meta.save()
            return {'status': 'skipped', 'message': 'No file to process'}
        
        video_meta.processing_status = 'processing'
        video_meta.save()
        
        logger.info(f"Starting HLS processing for video: {video_meta.content_item.title_ar}")
        
        try:
            processor = VideoProcessor()
        except DependencyError as e:
            logger.error(f"Video processing dependencies not available: {e}")
            video_meta.processing_status = 'failed'
            video_meta.save()
            return {'status': 'error', 'message': f'Dependencies missing: {e}'}
        
        input_path = video_meta.original_file.path
        content_uuid = str(video_meta.content_item.id)
        
        # Create HLS directories
        hls_base_path = Path(settings.MEDIA_ROOT) / 'hls' / 'videos' / content_uuid
        hls_720p_dir = hls_base_path / '720p'
        hls_480p_dir = hls_base_path / '480p'
        
        # Process 720p HLS
        try:
            playlist_720p = processor.generate_hls(input_path, hls_720p_dir, '720')
            video_meta.hls_720p_path = f'hls/videos/{content_uuid}/720p/playlist.m3u8'
            logger.info(f"720p HLS generated successfully: {playlist_720p}")
        except Exception as e:
            logger.error(f"720p HLS generation failed: {e}")
            raise
        
        # Process 480p HLS
        try:
            playlist_480p = processor.generate_hls(input_path, hls_480p_dir, '480')
            video_meta.hls_480p_path = f'hls/videos/{content_uuid}/480p/playlist.m3u8'
            logger.info(f"480p HLS generated successfully: {playlist_480p}")
        except Exception as e:
            logger.error(f"480p HLS generation failed: {e}")
            raise
        
        # Extract video metadata if not already set
        if not video_meta.duration_seconds:
            video_meta.duration_seconds = processor.get_duration(input_path)
        
        video_meta.processing_status = 'completed'
        video_meta.save()
        
        logger.info(f"Video processing completed successfully for: {video_meta.content_item.title_ar}")
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
    try:
        audio_meta = AudioMeta.objects.get(id=audio_meta_id)
        
        # Check if there's actually a file to process
        if not audio_meta.original_file:
            logger.warning(f"No file to process for AudioMeta {audio_meta_id}")
            audio_meta.processing_status = 'completed'  # Mark as completed since there's nothing to do
            audio_meta.save()
            return {'status': 'skipped', 'message': 'No file to process'}
        
        audio_meta.processing_status = 'processing'
        audio_meta.save()
        
        logger.info(f"Starting audio compression for: {audio_meta.content_item.title_ar}")
        
        try:
            processor = AudioProcessor()
        except DependencyError as e:
            logger.error(f"Audio processing dependencies not available: {e}")
            audio_meta.processing_status = 'failed'
            audio_meta.save()
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
        metadata = processor.extract_metadata(input_path)
        audio_meta.duration_seconds = metadata['duration']
        
        # Compress audio
        try:
            compressed_path, file_size = processor.compress_audio(
                input_path, output_path, target_bitrate='192k', max_size_mb=50
            )
            
            # Update audio meta with compressed file info
            audio_meta.compressed_file.name = f'compressed/audio/{compressed_filename}'
            audio_meta.bitrate = 192  # Target bitrate
            
            logger.info(f"Audio compressed successfully: {compressed_path} ({file_size/1024/1024:.1f}MB)")
            
        except Exception as e:
            logger.error(f"Audio compression failed: {e}")
            raise
        
        audio_meta.processing_status = 'completed'
        audio_meta.save()
        
        logger.info(f"Audio processing completed successfully for: {audio_meta.content_item.title_ar}")
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
    try:
        pdf_meta = PdfMeta.objects.get(id=pdf_meta_id)
        
        # Check if there's actually a file to process
        if not pdf_meta.original_file:
            logger.warning(f"No file to process for PdfMeta {pdf_meta_id}")
            pdf_meta.processing_status = 'completed'
            pdf_meta.save()
            return {'status': 'skipped', 'message': 'No file to process'}
        
        pdf_meta.processing_status = 'processing'
        pdf_meta.save()
        
        logger.info(f"Starting PDF optimization for: {pdf_meta.content_item.title_ar}")
        
        try:
            processor = PDFProcessor()
        except DependencyError as e:
            logger.error(f"PDF processing dependencies not available: {e}")
            pdf_meta.processing_status = 'failed'
            pdf_meta.save()
            return {'status': 'error', 'message': f'Dependencies missing: {e}'}
        
        processor = PDFProcessor()
        input_path = pdf_meta.original_file.path
        
        # Extract PDF info
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
        else:
            logger.info("PDF size acceptable, no optimization needed")
        
        pdf_meta.processing_status = 'completed'
        pdf_meta.save()
        
        logger.info(f"PDF processing completed successfully for: {pdf_meta.content_item.title_ar}")
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
            logger.info(f"Marked video as failed: {video.content_item.title_ar}")
        
        # Clean up audio processing failures
        failed_audios = AudioMeta.objects.filter(
            processing_status='processing',
            content_item__created_at__lt=cutoff_time
        )
        
        for audio in failed_audios:
            audio.processing_status = 'failed'
            audio.save()
            logger.info(f"Marked audio as failed: {audio.content_item.title_ar}")
        
        # Clean up PDF processing failures
        failed_pdfs = PdfMeta.objects.filter(
            processing_status='processing',
            content_item__created_at__lt=cutoff_time
        )
        
        for pdf in failed_pdfs:
            pdf.processing_status = 'failed'
            pdf.save()
            logger.info(f"Marked PDF as failed: {pdf.content_item.title_ar}")
        
        return {'status': 'success', 'cleaned_items': len(failed_videos) + len(failed_audios) + len(failed_pdfs)}
        
    except Exception as e:
        logger.error(f"Cleanup task failed: {e}")
        return {'status': 'error', 'message': str(e)}