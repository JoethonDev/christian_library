from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from django.core.files.storage import default_storage
import os

from .models import ContentItem, VideoMeta, AudioMeta, PdfMeta
from core.tasks.media_processing import (
    process_video_to_hls, process_audio_compression, process_pdf_optimization
)


@receiver(post_save, sender=ContentItem)
def create_content_meta(sender, instance, created, **kwargs):
    """Create appropriate meta object when ContentItem is created"""
    if created:
        if instance.content_type == 'video':
            VideoMeta.objects.get_or_create(content_item=instance)
        elif instance.content_type == 'audio':
            AudioMeta.objects.get_or_create(content_item=instance)
        elif instance.content_type == 'pdf':
            PdfMeta.objects.get_or_create(content_item=instance)


@receiver(post_save, sender=VideoMeta)
def trigger_video_processing(sender, instance, created, **kwargs):
    """Trigger video processing when video file is uploaded"""
    if instance.original_file and instance.processing_status == 'pending':
        # Only trigger if file was just uploaded or changed
        update_fields = kwargs.get('update_fields', []) or []
        if created or 'original_file' in update_fields:
            # Only trigger if there's actually a file to process
            if instance.original_file.name:
                # Delay the task to ensure file is fully saved
                process_video_to_hls.apply_async(
                    args=[instance.id],
                    countdown=5  # Wait 5 seconds before starting
                )


@receiver(post_save, sender=AudioMeta)
def trigger_audio_processing(sender, instance, created, **kwargs):
    """Trigger audio processing when audio file is uploaded"""
    if instance.original_file and instance.processing_status == 'pending':
        update_fields = kwargs.get('update_fields', []) or []
        if created or 'original_file' in update_fields:
            # Only trigger if there's actually a file to process
            if instance.original_file.name:
                process_audio_compression.apply_async(
                    args=[instance.id],
                    countdown=5
                )


@receiver(post_save, sender=PdfMeta)
def trigger_pdf_processing(sender, instance, created, **kwargs):
    """Trigger PDF processing when PDF file is uploaded"""
    if instance.original_file and instance.processing_status == 'pending':
        update_fields = kwargs.get('update_fields', []) or []
        if created or 'original_file' in update_fields:
            # Only trigger if there's actually a file to process
            if instance.original_file.name:
                process_pdf_optimization.apply_async(
                    args=[instance.id],
                    countdown=5
                )


@receiver(post_delete, sender=VideoMeta)
def delete_video_files(sender, instance, **kwargs):
    """Clean up video files when VideoMeta is deleted"""
    # Delete original file
    if instance.original_file:
        if default_storage.exists(instance.original_file.name):
            default_storage.delete(instance.original_file.name)
    
    # Delete HLS directories
    if instance.content_item:
        import shutil
        from django.conf import settings
        from pathlib import Path
        
        hls_base_path = Path(settings.MEDIA_ROOT) / 'hls' / 'videos' / str(instance.content_item.id)
        if hls_base_path.exists():
            shutil.rmtree(hls_base_path)


@receiver(post_delete, sender=AudioMeta)
def delete_audio_files(sender, instance, **kwargs):
    """Clean up audio files when AudioMeta is deleted"""
    # Delete original file
    if instance.original_file:
        if default_storage.exists(instance.original_file.name):
            default_storage.delete(instance.original_file.name)
    
    # Delete compressed file
    if instance.compressed_file:
        if default_storage.exists(instance.compressed_file.name):
            default_storage.delete(instance.compressed_file.name)


@receiver(post_delete, sender=PdfMeta)
def delete_pdf_files(sender, instance, **kwargs):
    """Clean up PDF files when PdfMeta is deleted"""
    # Delete original file
    if instance.original_file:
        if default_storage.exists(instance.original_file.name):
            default_storage.delete(instance.original_file.name)
    
    # Delete optimized file
    if instance.optimized_file:
        if default_storage.exists(instance.optimized_file.name):
            default_storage.delete(instance.optimized_file.name)