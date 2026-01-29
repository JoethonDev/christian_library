"""
Content Management Service Layer
Handles all business logic for content operations
"""
from typing import Dict, List, Optional, Tuple, Union
from django.db import transaction
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import UploadedFile
from django.utils.translation import gettext_lazy as _
from django.conf import settings
import logging

from ..models import ContentItem, VideoMeta, AudioMeta, PdfMeta, Tag
from core.utils.exceptions import (
    ContentNotFoundError, 
    InvalidContentTypeError,
    MediaProcessingError
)

logger = logging.getLogger(__name__)


class ContentService:
    """Service for managing content items and their lifecycle"""
    
    @staticmethod
    def get_content_by_id(content_id: str, content_type: Optional[str] = None) -> ContentItem:
        """
        Retrieve content by ID with optional type validation
        
        Args:
            content_id: UUID string of the content item
            content_type: Optional type validation ('video', 'audio', 'pdf')
            
        Returns:
            ContentItem instance
            
        Raises:
            ContentNotFoundError: If content doesn't exist
            InvalidContentTypeError: If content type doesn't match
        """
        try:
            content_item = ContentItem.objects.with_meta().get(id=content_id, is_active=True)
            
            if content_type and content_item.content_type != content_type:
                raise InvalidContentTypeError(
                    f"Content {content_id} is not of type {content_type}"
                )
            
            return content_item
            
        except ContentItem.DoesNotExist:
            raise ContentNotFoundError(f"Content with ID {content_id} not found")
    
    @staticmethod
    def get_content_list(
        content_type: Optional[str] = None,
        tag_ids: Optional[List[str]] = None,
        search_query: Optional[str] = None,
        language: str = 'ar'
    ) -> List[ContentItem]:
        """
        Get filtered list of content items
        
        Args:
            content_type: Filter by content type
            tag_ids: Filter by tags
            search_query: Search in titles and descriptions
            language: Language for search ('ar' or 'en')
            
        Returns:
            List of ContentItem instances
        """
        queryset = ContentItem.objects.with_meta().filter(is_active=True)
        
        if content_type:
            queryset = queryset.filter(content_type=content_type)
            
        if tag_ids:
            queryset = queryset.filter(tags__id__in=tag_ids).distinct()
            
        if search_query:
            if language == 'ar':
                queryset = queryset.filter(
                    title_ar__icontains=search_query
                ) | queryset.filter(
                    description_ar__icontains=search_query
                )
            else:
                queryset = queryset.filter(
                    title_en__icontains=search_query
                ) | queryset.filter(
                    description_en__icontains=search_query
                )
        
        return queryset
    
    @staticmethod
    def create_content_item(
        title_ar: str,
        content_type: str,
        description_ar: str = "",
        title_en: str = "",
        description_en: str = "",
        tag_ids: Optional[List[str]] = None
    ) -> ContentItem:
        """
        Create a new content item
        
        Args:
            title_ar: Arabic title
            content_type: Type of content ('video', 'audio', 'pdf')
            description_ar: Arabic description
            title_en: English title
            description_en: English description
            tag_ids: List of tag UUIDs
            
        Returns:
            ContentItem instance
            
        Raises:
            ValidationError: If validation fails
        """
        try:
            with transaction.atomic():
                # Create content item
                content_item = ContentItem.objects.create(
                    title_ar=title_ar,
                    title_en=title_en,
                    description_ar=description_ar,
                    description_en=description_en,
                    content_type=content_type
                )
                
                # Add tags if provided
                if tag_ids:
                    tags = Tag.objects.filter(id__in=tag_ids, is_active=True)
                    content_item.tags.set(tags)
                
                logger.info(f"Created content item {content_item.id} of type {content_type}")
                return content_item
                
        except Exception as e:
            logger.error(f"Error creating content item: {str(e)}")
            raise ValidationError(f"{_('Error creating content item')}: {str(e)}")
    
    @staticmethod
    def update_content_item(
        content_id: str,
        **update_fields
    ) -> ContentItem:
        """
        Update an existing content item
        
        Args:
            content_id: UUID string of the content item
            **update_fields: Fields to update
            
        Returns:
            Updated ContentItem instance
            
        Raises:
            ContentNotFoundError: If content doesn't exist
            ValidationError: If validation fails
        """
        try:
            with transaction.atomic():
                content_item = ContentService.get_content_by_id(content_id)
                
                # Update fields
                for field, value in update_fields.items():
                    if hasattr(content_item, field):
                        setattr(content_item, field, value)
                
                content_item.full_clean()
                content_item.save()
                
                logger.info(f"Updated content item {content_item.id}")
                return content_item
                
        except Exception as e:
            logger.error(f"Error updating content item {content_id}: {str(e)}")
            raise ValidationError(f"{_('Error updating content item')}: {str(e)}")
    
    @staticmethod
    def delete_content_item(content_id: str) -> bool:
        """
        Soft delete a content item
        
        Args:
            content_id: UUID string of the content item
            
        Returns:
            True if successful
            
        Raises:
            ContentNotFoundError: If content doesn't exist
        """
        try:
            content_item = ContentService.get_content_by_id(content_id)
            content_item.is_active = False
            content_item.save()
            
            logger.info(f"Deleted content item {content_item.id}")
            return True
            
        except Exception as e:
            logger.error(f"Error deleting content item {content_id}: {str(e)}")
            raise
    
    @staticmethod
    def get_content_statistics() -> Dict:
        """
        Get content statistics for dashboard - Optimized to use single query with aggregation
        
        Returns:
            Dictionary with content statistics
        """
        from django.db.models import Count, Q
        
        # OPTIMIZATION: Use single query with conditional aggregation instead of 7 separate COUNT queries
        content_stats = ContentItem.objects.filter(is_active=True).aggregate(
            total_content=Count('id'),
            videos=Count('id', filter=Q(content_type='video')),
            audios=Count('id', filter=Q(content_type='audio')),
            pdfs=Count('id', filter=Q(content_type='pdf')),
        )
        
        # OPTIMIZATION: Use single query for processing status counts instead of 3 separate queries
        processing_stats = {
            'processing_videos': VideoMeta.objects.filter(
                processing_status__in=['pending', 'processing']
            ).count(),
            'processing_audios': AudioMeta.objects.filter(
                processing_status__in=['pending', 'processing']
            ).count(),
            'processing_pdfs': PdfMeta.objects.filter(
                processing_status__in=['pending', 'processing']
            ).count(),
        }
        
        # Combine results
        content_stats.update(processing_stats)
        return content_stats


class MediaMetaService:
    """Service for managing media metadata"""
    
    @staticmethod
    def get_video_meta(content_id: str) -> VideoMeta:
        """Get video metadata for content item"""
        try:
            content_item = ContentService.get_content_by_id(content_id, 'video')
            return content_item.videometa
        except AttributeError:
            raise MediaProcessingError(f"Video metadata not found for content {content_id}")
    
    @staticmethod
    def get_audio_meta(content_id: str) -> AudioMeta:
        """Get audio metadata for content item"""
        try:
            content_item = ContentService.get_content_by_id(content_id, 'audio')
            return content_item.audiometa
        except AttributeError:
            raise MediaProcessingError(f"Audio metadata not found for content {content_id}")
    
    @staticmethod
    def get_pdf_meta(content_id: str) -> PdfMeta:
        """Get PDF metadata for content item"""
        try:
            content_item = ContentService.get_content_by_id(content_id, 'pdf')
            return content_item.pdfmeta
        except AttributeError:
            raise MediaProcessingError(f"PDF metadata not found for content {content_id}")
    
    @staticmethod
    def update_processing_status(
        content_id: str,
        content_type: str,
        status: str,
        **meta_fields
    ) -> Union[VideoMeta, AudioMeta, PdfMeta]:
        """
        Update processing status and metadata
        
        Args:
            content_id: UUID string of the content item
            content_type: Type of content
            status: New processing status
            **meta_fields: Additional metadata fields to update
            
        Returns:
            Updated meta object
        """
        try:
            with transaction.atomic():
                if content_type == 'video':
                    meta = MediaMetaService.get_video_meta(content_id)
                elif content_type == 'audio':
                    meta = MediaMetaService.get_audio_meta(content_id)
                elif content_type == 'pdf':
                    meta = MediaMetaService.get_pdf_meta(content_id)
                else:
                    raise InvalidContentTypeError(f"Invalid content type: {content_type}")
                
                meta.processing_status = status
                
                for field, value in meta_fields.items():
                    if hasattr(meta, field):
                        setattr(meta, field, value)
                
                meta.save()
                
                logger.info(f"Updated {content_type} meta for {content_id}: status={status}")
                return meta
                
        except Exception as e:
            logger.error(f"Error updating meta for {content_id}: {str(e)}")
            raise MediaProcessingError(f"Error updating metadata: {str(e)}")