from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from django.core.files.storage import default_storage
import os

from .models import ContentItem, VideoMeta, AudioMeta, PdfMeta, ProcessingJob


@receiver(post_save, sender=ContentItem)
def create_content_meta(sender, instance, created, **kwargs):
    """Create appropriate meta object when ContentItem is created"""
    if created:
        ProcessingJob.objects.get_or_create(content_item=instance)
        if instance.content_type == 'video':
            VideoMeta.objects.get_or_create(content_item=instance)
        elif instance.content_type == 'audio':
            AudioMeta.objects.get_or_create(content_item=instance)
        elif instance.content_type == 'pdf':
            PdfMeta.objects.get_or_create(content_item=instance)


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


@receiver(post_delete, sender=ContentItem)
def delete_content_item_files(sender, instance, **kwargs):
    """Clean up thumbnail and supplementary documents when ContentItem is deleted"""
    # Delete thumbnail
    if instance.thumbnail:
        if default_storage.exists(instance.thumbnail.name):
            default_storage.delete(instance.thumbnail.name)
            
    # Delete supplementary document
    if instance.supplementary_document:
        if default_storage.exists(instance.supplementary_document.name):
            default_storage.delete(instance.supplementary_document.name)