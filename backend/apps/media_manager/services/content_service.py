"""
Content Management Service Layer
Handles all business logic for content operations
"""
from typing import Any, Dict, List, Optional, Tuple, Union
import uuid
from django.db import transaction, models
from django.db.models import Q
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
from core.utils.cache_utils import cache_invalidator, CacheInvalidation

logger = logging.getLogger(__name__)


class ContentService:
    """Service for managing content items and their lifecycle"""
    
    @staticmethod
    def _process_tags(tag_ids_or_names: List[str]) -> List[Tag]:
        """
        Process a list of tag IDs or names and return a list of Tag objects.
        If a tag name doesn't exist, it creates a new tag.
        Handles both Arabic and English names.
        """
        tag_objects = []
        if not tag_ids_or_names:
            return tag_objects
            
        # Clean the input: trim spaces and remove empty strings
        clean_inputs = []
        for t in tag_ids_or_names:
            if isinstance(t, str):
                parts = [p.strip() for p in t.split(',') if p.strip()]
                clean_inputs.extend(parts)
            elif t:
                clean_inputs.append(t)
        
        for input_val in clean_inputs:
            # Check if it's already a Tag object
            if isinstance(input_val, Tag):
                tag_objects.append(input_val)
                continue
                
            # Check if it's a UUID
            try:
                uuid.UUID(str(input_val))
                # It's a UUID, try to find the tag
                tag = Tag.objects.filter(id=input_val, is_active=True).first()
                if tag:
                    tag_objects.append(tag)
                continue
            except (ValueError, TypeError):
                # Not a UUID, it's a name
                pass
            
            # Since it's a name, try to find an existing tag by name_ar or name_en
            tag = Tag.objects.filter(
                Q(name_ar__iexact=input_val) | Q(name_en__iexact=input_val)
            ).first()
            
            if tag:
                tag_objects.append(tag)
            else:
                # Create a new tag
                # Heuristic: if it has Arabic characters, use as name_ar
                is_arabic = any('\u0600' <= char <= '\u06FF' for char in str(input_val))
                
                try:
                    if is_arabic:
                        new_tag = Tag.objects.create(name_ar=input_val)
                    else:
                        # For English tags, use as name_ar (since it's required) and name_en
                        new_tag = Tag.objects.create(name_ar=input_val, name_en=input_val)
                    tag_objects.append(new_tag)
                except Exception as e:
                    logger.warning(f"Failed to create new tag '{input_val}': {e}")
                    
        return tag_objects

    @staticmethod
    def get_content_by_id(content_id: str, content_type: Optional[str] = None) -> ContentItem:
        """
        Retrieve content by ID with optional type validation - optimized for zero N+1 queries
        
        Args:
            content_id: UUID string of the content item
            content_type: Optional type validation ('video', 'audio', 'pdf')
            
        Returns:
            ContentItem instance with meta relationships loaded
            
        Raises:
            ContentNotFoundError: If content doesn't exist
            InvalidContentTypeError: If content type doesn't match
        """
        try:
            # Use optimized QuerySet that loads meta relationships
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
        Get filtered list of content items - optimized for zero N+1 queries
        
        Args:
            content_type: Filter by content type
            tag_ids: Filter by tags
            search_query: Search in titles and descriptions
            language: Language for search ('ar' or 'en')
            
        Returns:
            List of ContentItem instances with meta relationships loaded
        """
        # Start with optimized QuerySet that includes all relations
        queryset = ContentItem.objects.for_listing(content_type)
        
        if tag_ids:
            queryset = queryset.filter(tags__id__in=tag_ids).distinct()
            
        if search_query:
            queryset = ContentItem.objects.search_optimized(search_query, content_type)
        
        return list(queryset)
    
    @staticmethod
    def get_content_for_media_serving(content_id: str, content_type: str) -> ContentItem:
        """
        Get content optimized for media serving with all necessary relations loaded
        
        Args:
            content_id: UUID string of the content item
            content_type: Type of content for validation
            
        Returns:
            ContentItem with meta relationships optimized for serving
        """
        try:
            return ContentItem.objects.for_media_serving().get(
                id=content_id, 
                content_type=content_type,
                is_active=True
            )
        except ContentItem.DoesNotExist:
            raise ContentNotFoundError(f"Content with ID {content_id} not found for serving")
    
    @staticmethod
    def get_ready_content_by_type(content_type: str):
        """
        Get all ready content of specific type in single optimized query
        
        Args:
            content_type: Type of content ('video', 'audio', 'pdf')
            
        Returns:
            QuerySet of ready content items
        """
        if content_type == 'video':
            return ContentItem.objects.filter(
                content_type='video',
                videometa__processing_status='completed',
                is_active=True
            ).select_related('videometa').prefetch_related('tags')
        elif content_type == 'audio':
            return ContentItem.objects.filter(
                content_type='audio',
                audiometa__processing_status='completed',
                is_active=True
            ).select_related('audiometa').prefetch_related('tags')
        elif content_type == 'pdf':
            return ContentItem.objects.filter(
                content_type='pdf',
                pdfmeta__processing_status='completed',
                is_active=True
            ).select_related('pdfmeta').prefetch_related('tags')
        else:
            raise InvalidContentTypeError(f"Invalid content type: {content_type}")
    
    @staticmethod
    def create_content_item(
        title_ar: str,
        content_type: str,
        description_ar: str = "",
        title_en: str = "",
        description_en: str = "",
        tag_ids: Optional[List[str]] = None,
        seo_keywords_ar: str = "",
        seo_keywords_en: str = "",
        seo_meta_description_ar: str = "",
        seo_meta_description_en: str = "",
        seo_title_ar: str = "",
        seo_title_en: str = "",
        transcript: str = "",
        notes: str = "",
        seo_title_suggestions: str = "",
        structured_data: Any = None
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
            seo_keywords_ar: Arabic SEO keywords (comma-separated)
            seo_keywords_en: English SEO keywords (comma-separated)
            seo_meta_description_ar: Arabic meta description for SEO
            seo_meta_description_en: English meta description for SEO
            seo_title_suggestions: JSON string of title suggestions
            structured_data: JSON string or dict of structured data
            
        Returns:
            ContentItem instance
            
        Raises:
            ValidationError: If validation fails
        """
        try:
            # Process structured data if it's a string
            if isinstance(structured_data, str) and structured_data.strip():
                try:
                    import json
                    structured_data = json.loads(structured_data)
                except json.JSONDecodeError:
                    logger.warning(f"Invalid JSON in structured_data for {title_ar}, using empty dict")
                    structured_data = {}
            elif not isinstance(structured_data, dict):
                structured_data = {}

            with transaction.atomic():
                # Create content item
                content_item = ContentItem.objects.create(
                    title_ar=title_ar,
                    title_en=title_en,
                    description_ar=description_ar,
                    description_en=description_en,
                    content_type=content_type,
                    seo_keywords_ar=seo_keywords_ar,
                    seo_keywords_en=seo_keywords_en,
                    seo_meta_description_ar=seo_meta_description_ar,
                    seo_meta_description_en=seo_meta_description_en,
                    seo_title_ar=seo_title_ar,
                    seo_title_en=seo_title_en,
                    transcript=transcript,
                    notes=notes,
                    seo_title_suggestions=seo_title_suggestions,
                    structured_data=structured_data
                )
                
                # Add tags if provided
                if tag_ids:
                    tags = ContentService._process_tags(tag_ids)
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
                tags_to_set = None
                for field, value in update_fields.items():
                    if field == 'tags':
                        tags_to_set = ContentService._process_tags(value)
                        continue
                    if hasattr(content_item, field):
                        setattr(content_item, field, value)
                
                content_item.full_clean()
                content_item.save()
                
                # Update tags if provided
                if tags_to_set is not None:
                    content_item.tags.set(tags_to_set)
                
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
        Get content statistics for dashboard - Phase 4: High-value cache only
        
        PURPOSE: Expensive aggregate queries for admin dashboard
        READ_FREQUENCY: Moderate (admin dashboard usage)  
        INVALIDATION: On content create/update/delete via signals
        TTL: 30 minutes (admin data, less critical freshness)
        
        Returns:
            Dictionary with content statistics
        """
        # Phase 4: Try to get cached statistics first
        cached_stats = cache_invalidator.get_content_statistics()
        if cached_stats is not None:
            return cached_stats
        
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
        
        # Cache with explicit TTL using new caching approach
        cache_invalidator.set_content_statistics(content_stats)
        
        return content_stats
    
    @staticmethod
    def delete_content_item(content_id: str) -> bool:
        """
        Soft delete content item and invalidate related caches
        """
        try:
            content_item = ContentService.get_content_by_id(content_id)
            content_item.is_active = False
            content_item.save()
            
            # Invalidate caches when content changes
            CacheInvalidation.invalidate_content_stats(content_id)
            
            logger.info(f"Deleted content item {content_item.id}")
            return True
            
        except Exception as e:
            logger.error(f"Error deleting content item {content_id}: {str(e)}")
            raise


class MediaMetaService:
    """Optimized service for managing media metadata with zero N+1 queries"""
    
    @staticmethod
    def get_video_meta(content_id: str) -> VideoMeta:
        """Get video metadata for content item with optimized query"""
        try:
            return VideoMeta.objects.with_content().get(content_item_id=content_id)
        except VideoMeta.DoesNotExist:
            raise MediaProcessingError(f"Video metadata not found for content {content_id}")
    
    @staticmethod
    def get_audio_meta(content_id: str) -> AudioMeta:
        """Get audio metadata for content item with optimized query"""
        try:
            return AudioMeta.objects.with_content().get(content_item_id=content_id)
        except AudioMeta.DoesNotExist:
            raise MediaProcessingError(f"Audio metadata not found for content {content_id}")
    
    @staticmethod
    def get_pdf_meta(content_id: str) -> PdfMeta:
        """Get PDF metadata for content item with optimized query"""
        try:
            return PdfMeta.objects.with_content().get(content_item_id=content_id)
        except PdfMeta.DoesNotExist:
            raise MediaProcessingError(f"PDF metadata not found for content {content_id}")
    
    @staticmethod
    def get_meta_by_content_type(content_id: str, content_type: str):
        """Get meta object by content type - eliminates separate service calls"""
        if content_type == 'video':
            return MediaMetaService.get_video_meta(content_id)
        elif content_type == 'audio':
            return MediaMetaService.get_audio_meta(content_id)
        elif content_type == 'pdf':
            return MediaMetaService.get_pdf_meta(content_id)
        else:
            raise InvalidContentTypeError(f"Invalid content type: {content_type}")
    
    @staticmethod
    def get_ready_for_streaming_videos():
        """Get all videos ready for streaming in single query"""
        return VideoMeta.objects.ready_for_streaming().with_content()
    
    @staticmethod
    def get_ready_for_playback_audio():
        """Get all audio ready for playback in single query"""
        return AudioMeta.objects.ready_for_playback().with_content()
    
    @staticmethod
    def get_ready_for_viewing_pdfs():
        """Get all PDFs ready for viewing in single query"""
        return PdfMeta.objects.ready_for_viewing().with_content()
    
    @staticmethod
    def get_processing_statistics():
        """Get comprehensive processing statistics in minimal queries"""
        video_stats = VideoMeta.objects.get_streaming_stats()
        audio_stats = AudioMeta.objects.get_audio_stats() 
        pdf_stats = PdfMeta.objects.get_pdf_stats()
        
        return {
            'videos': video_stats,
            'audio': audio_stats,
            'pdfs': pdf_stats,
            'total_processing': (
                video_stats['processing_videos'] + 
                audio_stats['processing_audio'] + 
                pdf_stats['processing_pdfs']
            )
        }
    
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