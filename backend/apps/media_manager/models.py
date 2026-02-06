"""
Christian Library Backend: Full-Text Search & Extraction

New fields:
    - ContentItem.book_content: stores extracted text from PDF (supports Arabic, millions of chars)
    - ContentItem.search_vector: PostgreSQL FTS vector (GIN index, Arabic config)

Background processing:
    - ContentItem.save() triggers Celery task for extraction/indexing (never sync)
    - Celery task: extract_and_index_contentitem (see tasks.py)

Bulk processing:
    - Management command: bulk_extract_index (triggers all PDFs)

Phase 3 Database Indexes (Strategic Performance Optimization):
    ContentItem indexes:
        - mgr_active_type_created_idx: Composite (is_active, content_type, -created_at) with partial condition
        - mgr_active_search_idx: Partial index for search operations on active content
        - mgr_type_title_ar_idx: Content type with Arabic title for admin dashboard
        - mgr_type_lookup_idx: Type-specific lookups with active condition
        - mgr_updated_at_idx: Change tracking for cache invalidation
        
    Tag indexes:
        - mgr_tag_active_created_idx: Active tags with chronological ordering
        - mgr_tag_active_name_idx: Active tag name lookups (Arabic)
        
    M2M indexes (migration-only):
        - media_mgr_contentitem_tags_covering_idx: (tag_id, contentitem_id) covering index

Verification:
    Run: python manage.py verify_phase3_indexes

See tests.py for FTS/Arabic search tests.
"""
from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _
from django.core.exceptions import ValidationError
from django.urls import reverse
import uuid
# For full-text search support
from django.contrib.postgres.indexes import GinIndex
from django.contrib.postgres.search import SearchVectorField, SearchVector
from pdfminer.high_level import extract_text
from django.contrib.postgres.search import SearchVector
from django.db import connection
import os
import logging
import re

logger = logging.getLogger(__name__)


import fitz  # PyMuPDF for PDF processing and OCR fallback
from PIL import Image
import io
import subprocess
from pathlib import Path
import cv2
import numpy as np



class TagManager(models.Manager):
    """Custom manager for Tag with optimized queries"""
    
    def active(self):
        """Return only active tags"""
        return self.filter(is_active=True)
    
    def by_name(self, name, language='ar'):
        """Return tag by name in specific language"""
        if language == 'ar':
            return self.filter(name_ar__iexact=name)
        else:
            return self.filter(name_en__iexact=name)
    
    def popular(self, limit=10):
        """Return most popular tags based on content count - single query"""
        return self.active().annotate(
            content_count=models.Count('contentitem', filter=models.Q(contentitem__is_active=True))
        ).order_by('-content_count')[:limit]
    
    def for_content_type(self, content_type):
        """Get tags used by specific content type - optimized query"""
        return self.active().filter(
            contentitem__content_type=content_type,
            contentitem__is_active=True
        ).distinct().order_by('name_ar')
    
    def get_tag_statistics(self, tag_id):
        """Get statistics for a specific tag in single query"""
        return self.filter(id=tag_id).annotate(
            total_videos=models.Count('contentitem', filter=models.Q(
                contentitem__content_type='video',
                contentitem__is_active=True
            )),
            total_audios=models.Count('contentitem', filter=models.Q(
                contentitem__content_type='audio', 
                contentitem__is_active=True
            )),
            total_pdfs=models.Count('contentitem', filter=models.Q(
                contentitem__content_type='pdf',
                contentitem__is_active=True
            )),
            total_content=models.Count('contentitem', filter=models.Q(
                contentitem__is_active=True
            ))
        ).first()
    
    def for_autocomplete(self, query, language='ar'):
        """Optimized autocomplete for tags"""
        if len(query) < 2:
            return self.none()
            
        if language == 'ar':
            return self.active().filter(
                models.Q(name_ar__icontains=query) | 
                models.Q(name_en__icontains=query)
            ).values_list('name_ar', 'name_en')[:5]
        else:
            return self.active().filter(
                models.Q(name_en__icontains=query) | 
                models.Q(name_ar__icontains=query)  
            ).values_list('name_en', 'name_ar')[:5]


class Tag(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name_ar = models.CharField(max_length=100, unique=True, verbose_name=_('Arabic Name'), db_index=True)
    name_en = models.CharField(max_length=100, blank=True, verbose_name=_('English Name'), db_index=True)
    description_ar = models.TextField(blank=True, verbose_name=_('Arabic Description'))
    color = models.CharField(
        max_length=7, 
        default='#8C1C13', 
        verbose_name=_('Color'),
        help_text=_('Hex color code (e.g., #8C1C13)')
    )
    is_active = models.BooleanField(default=True, verbose_name=_('Active'), db_index=True)
    created_at = models.DateTimeField(auto_now_add=True, verbose_name=_('Created At'))
    
    # Custom manager
    objects = TagManager()
    
    class Meta:
        verbose_name = _('Tag')
        verbose_name_plural = _('Tags')
        ordering = ['name_ar']
        indexes = [
            # Legacy index (keep for compatibility)
            models.Index(fields=['is_active', 'name_ar']),
            
            # Phase 3: Strategic Tag Index Optimizations
            # 1. Tag performance with chronological ordering
            models.Index(
                fields=['is_active', '-created_at'],
                name='mgr_tag_active_created_idx'
            ),
            
            # 2. Tag name optimization for Arabic content
            models.Index(
                fields=['is_active', 'name_ar'],
                name='mgr_tag_active_name_idx'
            ),
        ]
    
    def __str__(self):
        return self.name_ar
    
    def get_name(self, language='ar'):
        """Get tag name with fallback logic for guest-facing views.
        Returns name in requested language, falls back to other language if empty/missing.
        """
        if language == 'ar':
            return self.name_ar if self.name_ar and self.name_ar.strip() else (self.name_en or '')
        else:
            return self.name_en if self.name_en and self.name_en.strip() else (self.name_ar or '')
    
    def get_content_count(self):
        """Get the number of content items using this tag"""
        return self.contentitem_set.filter(is_active=True).count()
    
    def clean(self):
        """Validate the tag"""
        super().clean()
        if not self.color.startswith('#') or len(self.color) != 7:
            raise ValidationError(_('Color must be a valid hex color code (e.g., #8C1C13)'))


class ContentItemQuerySet(models.QuerySet):
    """Optimized QuerySet for ContentItem with zero N+1 queries"""
    
    def active(self):
        """Return only active content items"""
        return self.filter(is_active=True)
    
    def by_type(self, content_type):
        """Return content items by type with optimized meta prefetching"""
        qs = self.filter(content_type=content_type)
        
        # Auto-optimize based on content type
        if content_type == 'video':
            return qs.select_related('videometa').prefetch_related('tags')
        elif content_type == 'audio':
            return qs.select_related('audiometa').prefetch_related('tags')
        elif content_type == 'pdf':
            return qs.select_related('pdfmeta').prefetch_related('tags')
        
        return qs.prefetch_related('tags')
    
    def with_full_meta(self):
        """Return content with all possible meta relationships optimized"""
        return self.select_related(
            'videometa', 'audiometa', 'pdfmeta'
        ).prefetch_related('tags')
    
    def with_meta(self):
        """Optimized method to fetch content with appropriate meta - eliminates N+1 queries"""
        return self.select_related(
            'videometa', 'audiometa', 'pdfmeta'
        ).prefetch_related('tags')
    
    def for_media_serving(self):
        """Optimized for media serving views - includes all necessary relations"""
        return self.active().select_related(
            'videometa', 'audiometa', 'pdfmeta'
        ).prefetch_related('tags')
    
    def ready_for_playback(self):
        """Return content items ready for playback/viewing"""
        from django.db.models import Q
        
        return self.active().select_related(
            'videometa', 'audiometa', 'pdfmeta'
        ).filter(
            Q(content_type='video', videometa__processing_status='completed') |
            Q(content_type='audio', audiometa__processing_status='completed') |
            Q(content_type='pdf', pdfmeta__processing_status='completed')
        )
    
    def for_listing(self, content_type=None):
        """Optimized for listing pages - single query with all relations"""
        qs = self.active().select_related(
            'videometa', 'audiometa', 'pdfmeta'
        ).prefetch_related('tags')
        
        if content_type:
            qs = qs.filter(content_type=content_type)
        
        return qs.order_by('-created_at')
    
    def for_home_page(self):
        """Optimized query for home page content - eliminates 6 separate queries"""
        return self.active().select_related(
            'videometa', 'audiometa', 'pdfmeta'
        ).prefetch_related('tags').order_by('-created_at')
    
    def by_tags(self, tag_ids):
        """Return content items filtered by tag IDs with optimized joins"""
        if not tag_ids:
            return self.none()
        
        return self.filter(
            tags__id__in=tag_ids
        ).select_related(
            'videometa', 'audiometa', 'pdfmeta'
        ).prefetch_related('tags').distinct()
    
    def search_optimized(self, query, content_type=None):
        """Optimized search with proper indexing and minimal queries"""
        from django.db.models import Q
        from django.contrib.postgres.search import SearchQuery, SearchRank
        
        # Start with active content and proper relations
        qs = self.active().select_related(
            'videometa', 'audiometa', 'pdfmeta'
        ).prefetch_related('tags')
        
        if content_type:
            qs = qs.filter(content_type=content_type)
        
        if not query:
            return qs.order_by('-created_at')
        
        # Use FTS for PDFs, fallback for others
        if not content_type or content_type == 'pdf':
            # PostgreSQL FTS with Arabic config
            search_query = SearchQuery(query, config='arabic')
            qs = qs.annotate(
                rank=SearchRank(models.F('search_vector'), search_query)
            ).filter(rank__gte=0.1).order_by('-rank')
        else:
            # Fallback search for video/audio
            search_conditions = (
                Q(title_ar__icontains=query) |
                Q(title_en__icontains=query) |
                Q(description_ar__icontains=query) |
                Q(description_en__icontains=query) |
                Q(tags__name_ar__icontains=query) |
                Q(tags__name_en__icontains=query)
            )
            qs = qs.filter(search_conditions).distinct().order_by('-created_at')
        
        return qs
    
    def related_content(self, content_item, limit=4):
        """Get related content based on shared tags - single optimized query"""
        if not content_item.tags.exists():
            # Fallback to recent content of same type
            return self.active().filter(
                content_type=content_item.content_type
            ).exclude(id=content_item.id).select_related(
                'videometa', 'audiometa', 'pdfmeta'
            ).prefetch_related('tags').order_by('-created_at')[:limit]
        
        # Get tag IDs in a single query
        tag_ids = list(content_item.tags.values_list('id', flat=True))
        
        return self.active().filter(
            content_type=content_item.content_type,
            tags__id__in=tag_ids
        ).exclude(id=content_item.id).select_related(
            'videometa', 'audiometa', 'pdfmeta'
        ).prefetch_related('tags').distinct()[:limit]
    
    def get_statistics(self, include_inactive=True):
        """Get content statistics. If include_inactive=True, counts all items."""
        from django.db.models import Count, Q
        
        target_qs = self.all() if include_inactive else self.active()
        
        return target_qs.aggregate(
            total_videos=Count('id', filter=Q(content_type='video')),
            total_audios=Count('id', filter=Q(content_type='audio')),
            total_pdfs=Count('id', filter=Q(content_type='pdf')),
            total_content=Count('id'),
            active_content=Count('id', filter=Q(is_active=True)),
            processing_content=Count('id', filter=Q(processing_status='processing')),
            failed_content=Count('id', filter=Q(processing_status='failed')),
            pending_content=Count('id', filter=Q(processing_status='pending'))
        )
    
    def for_autocomplete(self, query, language='ar'):
        """Optimized autocomplete query with language preference"""
        if len(query) < 2:
            return self.none()
        
        if language == 'ar':
            return self.active().filter(
                models.Q(title_ar__icontains=query) | models.Q(title_en__icontains=query)
            ).values_list('title_ar', 'title_en')[:5]
        else:
            return self.active().filter(
                models.Q(title_en__icontains=query) | models.Q(title_ar__icontains=query)
            ).values_list('title_en', 'title_ar')[:5]


class ContentItemManager(models.Manager):
    """Enhanced manager using optimized QuerySet"""
    
    def get_queryset(self):
        return ContentItemQuerySet(self.model, using=self._db)
    
    def active(self):
        return self.get_queryset().active()
    
    def by_type(self, content_type):
        return self.get_queryset().by_type(content_type)
    
    def for_listing(self, content_type=None):
        return self.get_queryset().for_listing(content_type)
    
    def for_home_page(self):
        return self.get_queryset().for_home_page()
    
    def search_optimized(self, query, content_type=None):
        return self.get_queryset().search_optimized(query, content_type)
    
    def related_content(self, content_item, limit=4):
        return self.get_queryset().related_content(content_item, limit)
    
    def with_meta(self):
        return self.get_queryset().with_meta()
    
    def for_media_serving(self):
        return self.get_queryset().for_media_serving()
    
    def ready_for_playback(self):
        return self.get_queryset().ready_for_playback()
    
    def get_statistics(self, include_inactive=True):
        return self.get_queryset().get_statistics(include_inactive)
    
    def for_autocomplete(self, query, language='ar'):
        return self.get_queryset().for_autocomplete(query, language)
    
    def get_home_data(self):
        """Get all home page data in minimal queries"""
        # Get all content for home page in one query
        all_content = self.for_home_page()
        
        # Slice efficiently without separate queries
        videos = [item for item in all_content if item.content_type == 'video'][:6]
        audios = [item for item in all_content if item.content_type == 'audio'][:6]
        pdfs = [item for item in all_content if item.content_type == 'pdf'][:6]
        
        return {
            'videos': videos,
            'audios': audios, 
            'pdfs': pdfs,
        }


class ContentItem(models.Model):
    def save(self, *args, **kwargs):
        """
        Override save to trigger background extraction/indexing if relevant fields change.
        Extraction and FTS update are always done in the background (never synchronously).
        """
        update_fields = kwargs.get('update_fields')
        is_new = self._state.adding
        
        super().save(*args, **kwargs)
        
        # Only trigger for PDFs
        if self.content_type == 'pdf':
            # Avoid infinite loop: don't trigger if we're only updating fields that 
            # are updated BY the extraction task itself.
            if update_fields:
                updates = set(update_fields)
                # If we are only updating search-related fields, don't re-trigger the task
                if updates.issubset({'book_content', 'search_vector', 'updated_at'}):
                    return
            
            # Text extraction is now triggered sequentially by the media processing pipeline
            # (Pdf Optimization -> Text Extraction -> SEO Generation)
            # self.trigger_background_extraction_and_indexing()

    def trigger_background_extraction_and_indexing(self):
        """
        Trigger a Celery task to extract text and update FTS in the background.
        """
        from apps.media_manager.tasks import extract_and_index_contentitem
        extract_and_index_contentitem.delay(str(self.id))

    def extract_text_from_pdf(self):
        """
        Extract ONLY Arabic text from the associated PDF file (PdfMeta.original_file) and store in book_content.
        This should be called from a background task. Tries multiple methods for best results.
        
        Uses PdfProcessorService for text extraction, OCR, and normalization.
        """
        logger = logging.getLogger(__name__)
        
        try:
            pdfmeta = getattr(self, 'pdfmeta', None)
            if not pdfmeta or not pdfmeta.original_file:
                logger.warning(f"PDF meta or file not found for ContentItem {self.id}")
                self.book_content = ''
                return

            pdf_path = pdfmeta.original_file.path
            if not os.path.exists(pdf_path):
                logger.error(f"PDF file does not exist at path: {pdf_path}")
                self.book_content = ''
                return
            
            page_count = getattr(pdfmeta, 'page_count', 0) or 0
            
            # Use the dedicated PDF processor service
            from apps.media_manager.services.pdf_processor_service import create_pdf_processor
            processor = create_pdf_processor(str(self.id))
            
            self.book_content = processor.extract_text_from_pdf(pdf_path, page_count)
            
            if self.book_content:
                logger.info(f"Successfully extracted and cleaned {len(self.book_content)} Arabic characters for PDF {self.id}")
            else:
                logger.warning(f"No Arabic text could be extracted for PDF {self.id}")
            
        except Exception as e:
            logger.error(f"Error extracting text from PDF {self.id}: {str(e)}", exc_info=True)
            self.book_content = ''

    def update_search_vector(self):
        """
        Update the search_vector field using book_content, title_ar, and description_ar.
        Should use PostgreSQL FTS with Arabic language config.
        This should be called from a background task.
        """
        if 'postgresql' not in connection.settings_dict['ENGINE']:
            logger.debug(f"Skipping search vector update for {self.id} - not using PostgreSQL")
            return
        
        if not self.book_content:
            logger.debug(f"No book content for {self.id}, clearing search vector")
            self.search_vector = None
            return
        
        # Create search-ready version of content for better matching
        search_content = self.book_content
        try:
            from core.utils.arabic_text_processor import quick_arabic_normalize
            search_content = quick_arabic_normalize(self.book_content)
            logger.debug(f"Applied quick Arabic normalization for search vector {self.id}")
        except ImportError:
            pass  # Use original content if processor not available
        
        # Use weights: A for title, B for description, C for content
        # Note: We set the attribute on self so it can be saved by the caller
        self.search_vector = (
            SearchVector('title_ar', weight='A', config='arabic') +
            SearchVector('description_ar', weight='B', config='arabic') +
            SearchVector('book_content', weight='C', config='arabic')
        )
    CONTENT_TYPES = (
        ('video', _('Video')),
        ('audio', _('Audio')),
        ('pdf', _('PDF')),
    )

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    title_ar = models.CharField(max_length=200, verbose_name=_('Arabic Title'), db_index=True)
    title_en = models.CharField(max_length=200, blank=True, verbose_name=_('English Title'), db_index=True)
    description_ar = models.TextField(verbose_name=_('Arabic Description'))
    description_en = models.TextField(blank=True, verbose_name=_('English Description'))
    content_type = models.CharField(max_length=10, choices=CONTENT_TYPES, verbose_name=_('Content Type'), db_index=True)
    tags = models.ManyToManyField('Tag', blank=True, verbose_name=_('Tags'))
    is_active = models.BooleanField(default=False, verbose_name=_('Active'), db_index=True)
    
    PROCESSING_STATUS_CHOICES = (
        ('pending', _('Pending')),
        ('processing', _('Processing')),
        ('completed', _('Completed')),
        ('failed', _('Failed')),
    )
    processing_status = models.CharField(
        max_length=20, 
        choices=PROCESSING_STATUS_CHOICES,
        default='pending', 
        verbose_name=_('Processing Status'),
        db_index=True
    )
    
    # New status to track SEO generation independently
    seo_processing_status = models.CharField(
        max_length=20,
        choices=PROCESSING_STATUS_CHOICES,
        default='pending',
        verbose_name=_('SEO Processing Status'),
        db_index=True
    )

    created_at = models.DateTimeField(auto_now_add=True, verbose_name=_('Created At'), db_index=True)
    updated_at = models.DateTimeField(auto_now=True, verbose_name=_('Updated At'))

    # --- Full-Text Search & Content Extraction Fields ---
    # Stores extracted book text (supports Arabic, can hold millions of characters)
    book_content = models.TextField(blank=True, null=True, verbose_name=_('Extracted Book Content'))
    # PostgreSQL SearchVectorField for FTS (supports Arabic config)
    search_vector = SearchVectorField(blank=True, null=True, verbose_name=_('Search Vector'))

    # --- Content Discovery & SEO Help Fields ---
    transcript = models.TextField(blank=True, null=True, verbose_name=_('Transcript'), help_text=_('Full text transcript of audio/video or summary for SEO'))
    notes = models.TextField(blank=True, null=True, verbose_name=_('Notes'), help_text=_('Additional study notes or context'))

    # --- SEO Metadata Fields (Generated by Gemini AI) ---
    seo_title_ar = models.CharField(
        max_length=70,
        blank=True,
        verbose_name=_('Arabic SEO Title'),
        help_text=_('Optimized Arabic title for search engines (max 70 chars)')
    )
    seo_title_en = models.CharField(
        max_length=70,
        blank=True,
        verbose_name=_('English SEO Title'),
        help_text=_('Optimized English title for search engines (max 70 chars)')
    )
    # English tags for multilingual SEO - Using TextField for SQLite compatibility
    tags_en = models.TextField(
        default='',
        blank=True,
        verbose_name=_('English Tags'),
        help_text=_('English tags for SEO (comma-separated, max 6 tags)')
    )
    # Arabic SEO keywords - Using TextField for SQLite compatibility
    seo_keywords_ar = models.TextField(
        default='',
        blank=True,
        verbose_name=_('Arabic SEO Keywords'),
        help_text=_('Arabic SEO keywords generated by AI (comma-separated, max 30)')
    )
    # English SEO keywords - Using TextField for SQLite compatibility
    seo_keywords_en = models.TextField(
        default='',
        blank=True,
        verbose_name=_('English SEO Keywords'),
        help_text=_('English SEO keywords generated by AI (comma-separated, max 30)')
    )
    # SEO meta descriptions (160 chars max per Google guidelines)
    seo_meta_description_ar = models.CharField(
        max_length=160,
        blank=True,
        verbose_name=_('Arabic Meta Description'),
        help_text=_('Arabic meta description for search engines (max 160 chars)')
    )
    seo_meta_description_en = models.CharField(
        max_length=160,
        blank=True,
        verbose_name=_('English Meta Description'),
        help_text=_('English meta description for search engines (max 160 chars)')
    )
    # Alternative SEO titles for optimization - Using TextField for SQLite compatibility
    seo_title_suggestions = models.TextField(
        default='',
        blank=True,
        verbose_name=_('SEO Title Suggestions'),
        help_text=_('Alternative SEO titles for search optimization (comma-separated, max 3)')
    )
    # JSON-LD structured data for rich snippets
    structured_data = models.JSONField(
        default=dict,
        blank=True,
        verbose_name=_('Structured Data'),
        help_text=_('JSON-LD structured data for search engines')
    )

    # Custom manager
    objects = ContentItemManager()

    class Meta:
        verbose_name = _('Content Item')
        verbose_name_plural = _('Content Items')
        ordering = ['-created_at']
        indexes = [
            # Legacy indexes (keep for compatibility)
            models.Index(fields=['content_type', 'is_active', '-created_at']),
            models.Index(fields=['is_active', '-created_at']),
            GinIndex(fields=['search_vector']),  # GIN index for FTS
            
            # Phase 3: Strategic Index Optimizations
            # 1. Composite index for home page filtering (partial index for active content only)
            models.Index(
                fields=['is_active', 'content_type', '-created_at'],
                name='mgr_active_type_created_idx',
                condition=models.Q(is_active=True)
            ),
            
            # 2. Search performance index (partial index for active content with search data)
            models.Index(
                fields=['is_active'], 
                name='mgr_active_search_idx',
                condition=models.Q(is_active=True, search_vector__isnull=False)
            ),
            
            # 3. Content type + title index for admin dashboard performance
            models.Index(
                fields=['content_type', 'title_ar'],
                name='mgr_type_title_ar_idx'
            ),
            
            # 4. Type-specific lookup optimization (partial index)
            models.Index(
                fields=['content_type'],
                name='mgr_type_lookup_idx',
                condition=models.Q(is_active=True)
            ),
            
            # 5. Cache invalidation and change tracking support
            models.Index(
                fields=['-updated_at'],
                name='mgr_updated_at_idx'
            ),
            
            # 6. Arabic text search optimization indexes
            models.Index(
                fields=['content_type', 'processing_status'],
                name='mgr_pdf_processing_idx',
                condition=models.Q(content_type='pdf')
            ),
            
            # Note: M2M covering index (tag_id, contentitem_id) is handled via migration
            # See: media_mgr_contentitem_tags_covering_idx in migration 0003_phase3_index_optimizations
        ]

    def __str__(self):
        return self.title_ar

    def get_title(self, language='ar'):
        """Get title with fallback logic for guest-facing views.
        Returns title in requested language, falls back to other language if empty/missing.
        """
        if language == 'ar':
            return self.title_ar if self.title_ar and self.title_ar.strip() else (self.title_en or '')
        else:
            return self.title_en if self.title_en and self.title_en.strip() else (self.title_ar or '')

    def get_description(self, language='ar'):
        """Get description with fallback logic for guest-facing views.
        Returns description in requested language, falls back to other language if empty/missing.
        """
        if language == 'ar':
            return self.description_ar if self.description_ar and self.description_ar.strip() else (self.description_en or '')
        else:
            return self.description_en if self.description_en and self.description_en.strip() else (self.description_ar or '')

    def get_absolute_url(self):
        """Get the absolute URL for this content item"""
        try:
            if self.content_type == 'video':
                return reverse('frontend_api:video_detail', kwargs={'video_uuid': self.id})
            elif self.content_type == 'audio':
                return reverse('frontend_api:audio_detail', kwargs={'audio_uuid': self.id})
            elif self.content_type == 'pdf':
                return reverse('frontend_api:pdf_detail', kwargs={'pdf_uuid': self.id})
            else:
                # Fallback for unknown content types
                return f'/content/{self.content_type}/{self.id}/'
        except Exception:
            # Fallback URL if reverse fails
            return f'/content/{self.content_type}/{self.id}/'

    def get_meta_object(self):
        """Get the appropriate meta object based on content type"""
        if self.content_type == 'video':
            return getattr(self, 'videometa', None)
        elif self.content_type == 'audio':
            return getattr(self, 'audiometa', None)
        elif self.content_type == 'pdf':
            return getattr(self, 'pdfmeta', None)
        return None

    def clean(self):
        """Validate the content item"""
        super().clean()
        if self.content_type not in [choice[0] for choice in self.CONTENT_TYPES]:
            raise ValidationError(_('Invalid content type'))
        
        # Prevent activating items that are still being processed
        # Rule: R2 Upload must be completed for activation (if R2 is enabled)
        if self.is_active:
            meta = self.get_meta_object()
            if meta:
                # If R2 is enabled, verify it's completed
                if getattr(settings, 'R2_ENABLED', False):
                    if meta.r2_upload_status != 'completed':
                        raise ValidationError(_('Cannot activate item until R2 upload is successfully completed. Current status: {}').format(
                            getattr(meta, 'get_r2_status_display', lambda: meta.r2_upload_status)()
                        ))
                else:
                    # If R2 is not enabled, ensure local processing is done
                    if meta.processing_status != 'completed':
                         raise ValidationError(_('Cannot activate item until processing is successfully completed.'))
            elif self.processing_status in ['pending', 'failed']:
                 raise ValidationError(_('Cannot activate item until processing is successfully completed.'))

    # --- SEO Helper Methods ---
    def has_seo_metadata(self):
        """Check if this content item has SEO metadata generated"""
        return bool(self.seo_keywords_ar or self.seo_keywords_en or self.seo_title_ar or self.seo_title_en or self.structured_data)

    def get_seo_title(self, language='en'):
        """Get SEO title with fallback logic"""
        if language == 'ar':
            return self.seo_title_ar or self.get_title('ar')
        else:
            return self.seo_title_en or self.get_title('en')

    def get_seo_meta_description(self, language='en'):
        """Get SEO meta description with fallback logic"""
        if language == 'ar':
            return self.seo_meta_description_ar or self.seo_meta_description_en or self.get_description('ar')[:160]
        else:
            return self.seo_meta_description_en or self.seo_meta_description_ar or self.get_description('en')[:160]

    def get_seo_keywords(self, language='en'):
        """Get SEO keywords as list from comma-separated string"""
        if language == 'ar':
            keywords = self.seo_keywords_ar.split(',') if self.seo_keywords_ar else []
        else:
            keywords = self.seo_keywords_en.split(',') if self.seo_keywords_en else []
        # Clean up whitespace and filter out empty strings
        return [keyword.strip() for keyword in keywords if keyword.strip()]
    
    @property
    def seo_keywords_ar_string(self):
        """Get Arabic SEO keywords as comma-separated string for templates"""
        return ', '.join(self.get_seo_keywords('ar'))
    
    @property
    def seo_keywords_en_string(self):
        """Get English SEO keywords as comma-separated string for templates"""
        return ', '.join(self.get_seo_keywords('en'))

    # Template-friendly properties for titles
    @property
    def title_ar_display(self):
        """Get Arabic title for templates"""
        return self.get_title('ar')
    
    @property
    def title_en_display(self):
        """Get English title for templates"""
        return self.get_title('en')
    
    # Template-friendly properties for SEO titles
    @property
    def seo_title_ar_display(self):
        """Get Arabic SEO title for templates"""
        return self.get_seo_title('ar')
    
    @property
    def seo_title_en_display(self):
        """Get English SEO title for templates"""
        return self.get_seo_title('en')
    
    # Template-friendly properties for descriptions
    @property
    def description_ar_display(self):
        """Get Arabic description for templates"""
        return self.get_description('ar')
    
    @property
    def description_en_display(self):
        """Get English description for templates"""
        return self.get_description('en')
    
    # Template-friendly properties for SEO meta descriptions
    @property
    def seo_meta_description_ar_display(self):
        """Get Arabic SEO meta description for templates"""
        return self.get_seo_meta_description('ar')
    
    @property
    def seo_meta_description_en_display(self):
        """Get English SEO meta description for templates"""
        return self.get_seo_meta_description('en')

    @property
    def indexed_char_count(self):
        """Return the number of indexed characters from extracted book content"""
        return len(self.book_content) if self.book_content else 0

    @property
    def has_indexed_content(self):
        """Check if content has been indexed"""
        return bool(self.book_content and self.book_content.strip())

    def get_structured_data_json(self):
        """Get structured data as JSON string for templates"""
        import json
        if self.structured_data:
            return json.dumps(self.structured_data, ensure_ascii=False, indent=2)
        return ''

    def get_canonical_url(self):
        """Get canonical URL for SEO"""
        try:
            from django.contrib.sites.models import Site
            current_site = Site.objects.get_current()
            return f"https://{current_site.domain}{self.get_absolute_url()}"
        except (ImportError, RuntimeError):
            # django.contrib.sites is not installed or configured
            return self.get_absolute_url()
        except Exception:
            # Fallback for any other site-related errors
            return self.get_absolute_url()

    def get_schema_type(self):
        """Get appropriate schema.org type based on content type"""
        schema_mapping = {
            'video': 'VideoObject',
            'audio': 'AudioObject',
            'pdf': 'Book'
        }
        return schema_mapping.get(self.content_type, 'CreativeWork')

    def generate_seo_metadata_async(self):
        """Trigger async SEO metadata generation via Celery"""
        from apps.media_manager.tasks import generate_seo_metadata_task
        generate_seo_metadata_task.delay(str(self.id))

    def update_seo_from_gemini(self, seo_metadata_dict):
        """Update SEO fields from Gemini AI response"""
        if not seo_metadata_dict:
            return False
        
        # Update SEO fields from Gemini response - Convert lists to comma-separated strings for SQLite
        tags_en = seo_metadata_dict.get('tags_en', [])
        self.tags_en = ', '.join(tags_en) if isinstance(tags_en, list) else tags_en
        
        seo_keywords_ar = seo_metadata_dict.get('seo_keywords_ar', [])
        self.seo_keywords_ar = ', '.join(seo_keywords_ar) if isinstance(seo_keywords_ar, list) else seo_keywords_ar
        
        seo_keywords_en = seo_metadata_dict.get('seo_keywords_en', [])
        self.seo_keywords_en = ', '.join(seo_keywords_en) if isinstance(seo_keywords_en, list) else seo_keywords_en
        
        self.seo_meta_description_ar = seo_metadata_dict.get('seo_meta_description_ar', '')
        self.seo_meta_description_en = seo_metadata_dict.get('seo_meta_description_en', '')
        self.seo_title_ar = seo_metadata_dict.get('seo_title_ar', '')
        self.seo_title_en = seo_metadata_dict.get('seo_title_en', '')
        self.transcript = seo_metadata_dict.get('transcript', '')
        self.notes = seo_metadata_dict.get('notes', '')
        
        seo_title_suggestions = seo_metadata_dict.get('seo_title_suggestions', [])
        self.seo_title_suggestions = ', '.join(seo_title_suggestions) if isinstance(seo_title_suggestions, list) else seo_title_suggestions
        
        self.structured_data = seo_metadata_dict.get('structured_data', {})
        
        # Also update basic metadata if provided
        if seo_metadata_dict.get('title_ar'):
            self.title_ar = seo_metadata_dict['title_ar']
        if seo_metadata_dict.get('title_en'):
            self.title_en = seo_metadata_dict['title_en']
        if seo_metadata_dict.get('description_ar'):
            self.description_ar = seo_metadata_dict['description_ar']
        if seo_metadata_dict.get('description_en'):
            self.description_en = seo_metadata_dict['description_en']
        
        self.save(update_fields=[
            'tags_en', 'seo_keywords_ar', 'seo_keywords_en', 'transcript', 'notes',
            'seo_meta_description_ar', 'seo_meta_description_en',
            'seo_title_ar', 'seo_title_en',
            'seo_title_suggestions', 'structured_data',
            'title_ar', 'title_en', 'description_ar', 'description_en',
            'updated_at'
        ])
        
        return True
    

class VideoMetaQuerySet(models.QuerySet):
    """Optimized QuerySet for VideoMeta with zero N+1 queries"""
    
    def ready_for_streaming(self):
        """Return videos ready for streaming"""
        return self.filter(
            processing_status='completed'
        ).filter(
            models.Q(hls_720p_path__isnull=False) | models.Q(hls_480p_path__isnull=False)
        )
    
    def for_player(self):
        """Optimized for video player - includes content item"""
        return self.select_related('content_item').filter(
            processing_status='completed'
        )
    
    def processing(self):
        """Return videos currently processing"""
        return self.filter(processing_status__in=['pending', 'processing'])
    
    def with_content(self):
        """Always include related content item"""
        return self.select_related('content_item')
    
    def by_quality(self, quality):
        """Filter by available quality"""
        if quality == '720p':
            return self.filter(hls_720p_path__isnull=False)
        elif quality == '480p':
            return self.filter(hls_480p_path__isnull=False)
        return self
    
    def r2_uploaded(self):
        """Return videos uploaded to R2"""
        return self.filter(r2_upload_status='completed')
    
    def get_streaming_stats(self):
        """Get streaming statistics in single query"""
        return self.aggregate(
            total_videos=models.Count('id'),
            ready_videos=models.Count('id', filter=models.Q(processing_status='completed')),
            processing_videos=models.Count('id', filter=models.Q(processing_status__in=['pending', 'processing'])),
            hls_720p_count=models.Count('id', filter=models.Q(hls_720p_path__isnull=False)),
            hls_480p_count=models.Count('id', filter=models.Q(hls_480p_path__isnull=False)),
            r2_uploaded_count=models.Count('id', filter=models.Q(r2_upload_status='completed'))
        )


class VideoMetaManager(models.Manager):
    """Custom manager for VideoMeta"""
    
    def get_queryset(self):
        return VideoMetaQuerySet(self.model, using=self._db)
    
    def ready_for_streaming(self):
        return self.get_queryset().ready_for_streaming()
    
    def for_player(self):
        return self.get_queryset().for_player()
    
    def processing(self):
        return self.get_queryset().processing()
    
    def with_content(self):
        return self.get_queryset().with_content()


class VideoMeta(models.Model):
    PROCESSING_STATUS_CHOICES = (
        ('pending', _('Pending')),
        ('processing', _('Processing')),
        ('completed', _('Completed')),
        ('failed', _('Failed')),
    )
    
    content_item = models.OneToOneField(
        ContentItem, 
        on_delete=models.CASCADE, 
        verbose_name=_('Content Item')
    )
    original_file = models.FileField(
        upload_to='original/videos/', 
        blank=True, 
        verbose_name=_('Original File')
    )
    duration_seconds = models.PositiveIntegerField(
        null=True, 
        blank=True, 
        verbose_name=_('Duration (seconds)'),
        db_index=True
    )
    hls_720p_path = models.CharField(
        max_length=500, 
        blank=True, 
        verbose_name=_('HLS 720p Path')
    )
    hls_480p_path = models.CharField(
        max_length=500, 
        blank=True, 
        verbose_name=_('HLS 480p Path')
    )
    processing_status = models.CharField(
        max_length=20, 
        choices=PROCESSING_STATUS_CHOICES,
        default='pending', 
        verbose_name=_('Processing Status'),
        db_index=True
    )
    file_size_mb = models.PositiveIntegerField(
        null=True, 
        blank=True, 
        verbose_name=_('File Size (MB)')
    )

    # --- Cloudflare R2 Integration Fields ---
    r2_original_file_url = models.URLField(
        max_length=1000,
        blank=True,
        verbose_name=_('R2 Original File URL'),
        help_text=_('Cloudflare R2 URL for the original video file (if uploaded)')
    )
    r2_hls_720p_url = models.URLField(
        max_length=1000,
        blank=True,
        verbose_name=_('R2 HLS 720p URL'),
        help_text=_('Cloudflare R2 URL for 720p HLS playlist (if uploaded)')
    )
    r2_hls_480p_url = models.URLField(
        max_length=1000,
        blank=True,
        verbose_name=_('R2 HLS 480p URL'),
        help_text=_('Cloudflare R2 URL for 480p HLS playlist (if uploaded)')
    )
    r2_upload_status = models.CharField(
        max_length=32,
        blank=True,
        default='',
        verbose_name=_('R2 Upload Status'),
        help_text=_('Status of R2 upload: pending, uploading, completed, failed')
    )
    r2_upload_progress = models.PositiveIntegerField(
        null=True,
        blank=True,
        verbose_name=_('R2 Upload Progress (%)'),
        help_text=_('Upload progress percentage (0-100)')
    )
    
    class Meta:
        verbose_name = _('Video Metadata')
        verbose_name_plural = _('Video Metadata')
        indexes = [
            models.Index(fields=['processing_status']),
            models.Index(fields=['duration_seconds']),
        ]
    
    # Use custom manager
    objects = VideoMetaManager()

    def __str__(self):
        return f"{_('Video')}: {self.content_item.title_ar}"
    
    def is_ready_for_streaming(self):
        """Check if video is ready for streaming"""
        return (self.processing_status == 'completed' and 
                (self.hls_720p_path or self.hls_480p_path))
    
    def get_duration_formatted(self):
        """Get formatted duration string"""
        if not self.duration_seconds:
            return _('Unknown')
        
        hours = self.duration_seconds // 3600
        minutes = (self.duration_seconds % 3600) // 60
        seconds = self.duration_seconds % 60
        
        if hours:
            return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
        else:
            return f"{minutes:02d}:{seconds:02d}"
    
    def get_duration_iso(self):
        """Get duration in ISO 8601 format (PT#H#M#S) for schema.org"""
        if not self.duration_seconds:
            return None
        
        hours = int(self.duration_seconds // 3600)
        minutes = int((self.duration_seconds % 3600) // 60)
        seconds = int(self.duration_seconds % 60)
        
        if hours:
            return f"PT{hours}H{minutes}M{seconds}S"
        return f"PT{minutes}M{seconds}S"
    
    def get_hls_master_playlist(self):
        """Get the best available HLS playlist (highest quality first)"""
        if self.hls_720p_path:
            return self.hls_720p_path
        elif self.hls_480p_path:
            return self.hls_480p_path
        return None
    
    def get_hls_playlist(self, quality='auto'):
        """Get HLS playlist for specific quality"""
        if quality == '720p' and self.hls_720p_path:
            return self.hls_720p_path
        elif quality == '480p' and self.hls_480p_path:
            return self.hls_480p_path
        elif quality == 'auto':
            return self.get_hls_master_playlist()
        return None
    
    def get_available_qualities(self):
        """Get list of available streaming qualities"""
        qualities = []
        if self.hls_720p_path:
            qualities.append('720p')
        if self.hls_480p_path:
            qualities.append('480p')
        return qualities
    
    def get_streaming_file(self, quality='auto'):
        """Get the best file for streaming (HLS if available, otherwise original)"""
        hls_playlist = self.get_hls_playlist(quality)
        if hls_playlist:
            return hls_playlist
        return self.original_file
    
    def get_download_file(self):
        """Get the file for download (always original)"""
        return self.original_file
    
    def get_playback_file(self):
        """Get the best file for playback (original file)"""
        return self.original_file

    def get_direct_download_url(self):
        """Get the direct download URL (R2 if available, otherwise local)"""
        if self.r2_original_file_url:
            return self.r2_original_file_url
        return self.original_file.url if self.original_file else None

    # --- R2 Helper Methods ---
    def has_r2_files(self):
        """Check if any R2 files are available"""
        return bool(self.r2_original_file_url or self.r2_hls_720p_url or self.r2_hls_480p_url)
    
    def get_r2_status_display(self):
        """Get human-readable R2 upload status"""
        status_map = {
            '': 'Not enabled',
            'pending': 'Pending upload',
            'uploading': f'Uploading ({self.r2_upload_progress or 0}%)',
            'completed': 'Upload complete',
            'failed': 'Upload failed'
        }
        return status_map.get(self.r2_upload_status, 'Unknown')
    
    def get_best_streaming_url(self):
        """Get the best available streaming URL (R2 first, then local)"""
        if self.r2_hls_720p_url:
            return self.r2_hls_720p_url
        elif self.r2_hls_480p_url:
            return self.r2_hls_480p_url
        elif self.r2_original_file_url:
            return self.r2_original_file_url
        else:
            streaming_file = self.get_streaming_file()
            # Handle if it's a FileField or a path string
            if hasattr(streaming_file, 'url'):
                return streaming_file.url
            return f"{settings.MEDIA_URL}{streaming_file}"

    def get_safe_file_size(self):
        """Safely get file size in bytes, handling missing files and R2 storage"""
        try:
            if self.original_file and self.original_file.name:
                return self.original_file.size
        except (FileNotFoundError, AttributeError, ValueError, OSError):
            pass
            
        # Fallback to file_size_mb if available
        if hasattr(self, 'file_size_mb') and self.file_size_mb:
            return self.file_size_mb * 1024 * 1024
            
        return 0
    
    @property
    def has_seo(self):
        """Check if content has SEO metadata"""
        return bool(
            self.content_item.seo_keywords_ar or 
            self.content_item.seo_keywords_en or 
            self.content_item.seo_meta_description_ar or 
            self.content_item.seo_meta_description_en
        )
    
    @property
    def has_metadata(self):
        """Check if video has complete metadata"""
        return bool(
            self.duration_seconds and 
            self.content_item.description_ar and 
            self.content_item.tags.exists()
        )


class AudioMetaQuerySet(models.QuerySet):
    """Optimized QuerySet for AudioMeta with zero N+1 queries"""
    
    def ready_for_playback(self):
        """Return audio files ready for playback"""
        return self.filter(processing_status='completed').filter(
            models.Q(compressed_file__isnull=False) | models.Q(original_file__isnull=False)
        )
    
    def for_player(self):
        """Optimized for audio player - includes content item"""
        return self.select_related('content_item').filter(
            processing_status='completed'
        )
    
    def processing(self):
        """Return audio files currently processing"""
        return self.filter(processing_status__in=['pending', 'processing'])
    
    def with_content(self):
        """Always include related content item"""
        return self.select_related('content_item')
    
    def with_compressed(self):
        """Return audio with compressed versions available"""
        return self.filter(compressed_file__isnull=False)
    
    def r2_uploaded(self):
        """Return audio uploaded to R2"""
        return self.filter(r2_upload_status='completed')
    
    def get_audio_stats(self):
        """Get audio statistics in single query"""
        return self.aggregate(
            total_audio=models.Count('id'),
            ready_audio=models.Count('id', filter=models.Q(processing_status='completed')),
            processing_audio=models.Count('id', filter=models.Q(processing_status__in=['pending', 'processing'])),
            compressed_count=models.Count('id', filter=models.Q(compressed_file__isnull=False)),
            r2_uploaded_count=models.Count('id', filter=models.Q(r2_upload_status='completed'))
        )


class AudioMetaManager(models.Manager):
    """Custom manager for AudioMeta"""
    
    def get_queryset(self):
        return AudioMetaQuerySet(self.model, using=self._db)
    
    def ready_for_playback(self):
        return self.get_queryset().ready_for_playback()
    
    def for_player(self):
        return self.get_queryset().for_player()
    
    def processing(self):
        return self.get_queryset().processing()
    
    def with_content(self):
        return self.get_queryset().with_content()


class AudioMeta(models.Model):
    PROCESSING_STATUS_CHOICES = (
        ('pending', _('Pending')),
        ('processing', _('Processing')),
        ('completed', _('Completed')),
        ('failed', _('Failed')),
    )
    
    content_item = models.OneToOneField(
        ContentItem, 
        on_delete=models.CASCADE, 
        verbose_name=_('Content Item')
    )
    original_file = models.FileField(
        upload_to='original/audio/', 
        blank=True, 
        verbose_name=_('Original File')
    )
    compressed_file = models.FileField(
        upload_to='compressed/audio/', 
        blank=True, 
        verbose_name=_('Compressed File')
    )
    duration_seconds = models.PositiveIntegerField(
        null=True, 
        blank=True, 
        verbose_name=_('Duration (seconds)'),
        db_index=True
    )
    bitrate = models.PositiveIntegerField(
        null=True, 
        blank=True, 
        verbose_name=_('Bitrate (kbps)')
    )
    processing_status = models.CharField(
        max_length=20, 
        choices=PROCESSING_STATUS_CHOICES,
        default='pending', 
        verbose_name=_('Processing Status'),
        db_index=True
    )
    file_size_mb = models.PositiveIntegerField(
        null=True, 
        blank=True, 
        verbose_name=_('File Size (MB)')
    )

    # --- Cloudflare R2 Integration Fields ---
    r2_original_file_url = models.URLField(
        max_length=1000,
        blank=True,
        verbose_name=_('R2 Original File URL'),
        help_text=_('Cloudflare R2 URL for the original audio file (if uploaded)')
    )
    r2_compressed_file_url = models.URLField(
        max_length=1000,
        blank=True,
        verbose_name=_('R2 Compressed File URL'),
        help_text=_('Cloudflare R2 URL for the compressed audio file (if uploaded)')
    )
    r2_upload_status = models.CharField(
        max_length=32,
        blank=True,
        default='',
        verbose_name=_('R2 Upload Status'),
        help_text=_('Status of R2 upload: pending, uploading, completed, failed')
    )
    r2_upload_progress = models.PositiveIntegerField(
        null=True,
        blank=True,
        verbose_name=_('R2 Upload Progress (%)'),
        help_text=_('Upload progress percentage (0-100)')
    )
    
    class Meta:
        verbose_name = _('Audio Metadata')
        verbose_name_plural = _('Audio Metadata')
        indexes = [
            models.Index(fields=['processing_status']),
            models.Index(fields=['duration_seconds']),
        ]
    
    # Use custom manager
    objects = AudioMetaManager()

    def __str__(self):
        return f"{_('Audio')}: {self.content_item.title_ar}"
    
    def is_ready_for_playback(self):
        """Check if audio is ready for playback"""
        return (self.processing_status == 'completed' and 
                (self.compressed_file or self.original_file))
    
    def get_playback_file(self):
        """Get the best file for playback (compressed if available)"""
        return self.compressed_file if self.compressed_file else self.original_file
    
    def get_direct_download_url(self):
        """Get the direct download URL (R2 if available, otherwise local)"""
        if self.r2_original_file_url:
            return self.r2_original_file_url
        if self.r2_compressed_file_url:
            return self.r2_compressed_file_url
        return self.original_file.url if self.original_file else None
    
    def get_direct_playback_url(self):
        """Get the direct playback URL (R2 if available, otherwise local)"""
        if self.r2_compressed_file_url:
            return self.r2_compressed_file_url
        if self.r2_original_file_url:
            return self.r2_original_file_url
        file_obj = self.get_playback_file()
        return file_obj.url if file_obj else None
    
    def get_duration_formatted(self):
        """Get formatted duration string"""
        if not self.duration_seconds:
            return _('Unknown')
        
        minutes = self.duration_seconds // 60
        seconds = self.duration_seconds % 60
        return f"{minutes:02d}:{seconds:02d}"
    
    def get_duration_iso(self):
        """Get duration in ISO 8601 format (PT#H#M#S) for schema.org"""
        if not self.duration_seconds:
            return None
        
        hours = int(self.duration_seconds // 3600)
        minutes = int((self.duration_seconds % 3600) // 60)
        seconds = int(self.duration_seconds % 60)
        
        if hours:
            return f"PT{hours}H{minutes}M{seconds}S"
        return f"PT{minutes}M{seconds}S"
    
    # --- R2 Helper Methods ---
    def has_r2_files(self):
        """Check if any R2 files are available"""
        return bool(self.r2_original_file_url or self.r2_compressed_file_url)
    
    def get_r2_status_display(self):
        """Get human-readable R2 upload status"""
        status_map = {
            '': 'Not enabled',
            'pending': 'Pending upload',
            'uploading': f'Uploading ({self.r2_upload_progress or 0}%)',
            'completed': 'Upload complete',
            'failed': 'Upload failed'
        }
        return status_map.get(self.r2_upload_status, 'Unknown')
    
    def get_best_streaming_url(self):
        """Get the best playback URL (R2 URL if available)"""
        if self.r2_compressed_file_url:
            return self.r2_compressed_file_url
        if self.r2_original_file_url:
            return self.r2_original_file_url
            
        file_obj = self.get_playback_file()
        return file_obj.url if file_obj else None

    def get_safe_file_size(self):
        """Safely get file size in bytes, handling missing files and R2 storage"""
        try:
            if self.original_file and self.original_file.name:
                return self.original_file.size
        except (FileNotFoundError, AttributeError, ValueError, OSError):
            pass
            
        # Fallback to file_size_mb if available
        if hasattr(self, 'file_size_mb') and self.file_size_mb:
            return self.file_size_mb * 1024 * 1024
            
        return 0
    
    @property
    def has_seo(self):
        """Check if content has SEO metadata"""
        return bool(
            self.content_item.seo_keywords_ar or 
            self.content_item.seo_keywords_en or 
            self.content_item.seo_meta_description_ar or 
            self.content_item.seo_meta_description_en
        )
    
    @property
    def has_metadata(self):
        """Check if audio has complete metadata"""
        return bool(
            self.duration_seconds and 
            self.content_item.description_ar and 
            self.content_item.tags.exists()
        )


class PdfMetaQuerySet(models.QuerySet):
    """Optimized QuerySet for PdfMeta with zero N+1 queries"""
    
    def ready_for_viewing(self):
        """Return PDFs ready for viewing"""
        return self.filter(processing_status='completed').filter(
            models.Q(optimized_file__isnull=False) | models.Q(original_file__isnull=False)
        )
    
    def for_viewer(self):
        """Optimized for PDF viewer - includes content item"""
        return self.select_related('content_item').filter(
            processing_status='completed'
        )
    
    def processing(self):
        """Return PDFs currently processing"""
        return self.filter(processing_status__in=['pending', 'processing'])
    
    def with_content(self):
        """Always include related content item"""
        return self.select_related('content_item')
    
    def with_optimized(self):
        """Return PDFs with optimized versions available"""
        return self.filter(optimized_file__isnull=False)
    
    def r2_uploaded(self):
        """Return PDFs uploaded to R2"""
        return self.filter(r2_upload_status='completed')
    
    def searchable(self):
        """Return PDFs that are searchable (have extracted text)"""
        return self.filter(content_item__book_content__isnull=False).exclude(content_item__book_content='')
    
    def get_pdf_stats(self):
        """Get PDF statistics in single query"""
        return self.aggregate(
            total_pdfs=models.Count('id'),
            ready_pdfs=models.Count('id', filter=models.Q(processing_status='completed')),
            processing_pdfs=models.Count('id', filter=models.Q(processing_status__in=['pending', 'processing'])),
            optimized_count=models.Count('id', filter=models.Q(optimized_file__isnull=False)),
            searchable_count=models.Count('id', filter=models.Q(
                content_item__book_content__isnull=False,
                content_item__book_content__gt=''
            )),
            r2_uploaded_count=models.Count('id', filter=models.Q(r2_upload_status='completed'))
        )


class PdfMetaManager(models.Manager):
    """Custom manager for PdfMeta"""
    
    def get_queryset(self):
        return PdfMetaQuerySet(self.model, using=self._db)
    
    def ready_for_viewing(self):
        return self.get_queryset().ready_for_viewing()
    
    def for_viewer(self):
        return self.get_queryset().for_viewer()
    
    def processing(self):
        return self.get_queryset().processing()
    
    def with_content(self):
        return self.get_queryset().with_content()
    
    def searchable(self):
        return self.get_queryset().searchable()


class PdfMeta(models.Model):
    PROCESSING_STATUS_CHOICES = (
        ('pending', _('Pending')),
        ('processing', _('Processing')),
        ('completed', _('Completed')),
        ('failed', _('Failed')),
    )
    
    content_item = models.OneToOneField(
        ContentItem, 
        on_delete=models.CASCADE, 
        verbose_name=_('Content Item')
    )
    original_file = models.FileField(
        upload_to='original/pdf/', 
        blank=True, 
        verbose_name=_('Original File')
    )
    optimized_file = models.FileField(
        upload_to='optimized/pdf/', 
        blank=True, 
        verbose_name=_('Optimized File')
    )
    file_size_mb = models.PositiveIntegerField(
        null=True, 
        blank=True, 
        verbose_name=_('File Size (MB)'),
        db_index=True
    )
    page_count = models.PositiveIntegerField(
        null=True, 
        blank=True, 
        verbose_name=_('Page Count'),
        db_index=True
    )
    processing_status = models.CharField(
        max_length=20, 
        choices=PROCESSING_STATUS_CHOICES,
        default='pending', 
        verbose_name=_('Processing Status'),
        db_index=True
    )

    # --- Cloudflare R2 Integration Fields ---
    r2_original_file_url = models.URLField(
        max_length=1000,
        blank=True,
        verbose_name=_('R2 Original File URL'),
        help_text=_('Cloudflare R2 URL for the original PDF file (if uploaded)')
    )
    r2_optimized_file_url = models.URLField(
        max_length=1000,
        blank=True,
        verbose_name=_('R2 Optimized File URL'),
        help_text=_('Cloudflare R2 URL for the optimized PDF file (if uploaded)')
    )
    r2_upload_status = models.CharField(
        max_length=32,
        blank=True,
        default='',
        verbose_name=_('R2 Upload Status'),
        help_text=_('Status of R2 upload: pending, uploading, completed, failed')
    )
    r2_upload_progress = models.PositiveIntegerField(
        null=True,
        blank=True,
        verbose_name=_('R2 Upload Progress (%)'),
        help_text=_('Upload progress percentage (0-100)')
    )
    
    class Meta:
        verbose_name = _('PDF Metadata')
        verbose_name_plural = _('PDF Metadata')
        indexes = [
            models.Index(fields=['processing_status']),
            models.Index(fields=['file_size_mb']),
            models.Index(fields=['page_count']),
        ]
    
    # Use custom manager
    objects = PdfMetaManager()

    def __str__(self):
        return f"{_('PDF')}: {self.content_item.title_ar}"
    
    def is_ready_for_viewing(self):
        """Check if PDF is ready for viewing"""
        return (self.processing_status == 'completed' and 
                (self.optimized_file or self.original_file))

    def get_safe_file_size(self):
        """Safely get file size in bytes, handling missing files and R2 storage"""
        try:
            if self.original_file and self.original_file.name:
                return self.original_file.size
        except (FileNotFoundError, AttributeError, ValueError, OSError):
            pass
            
        # Fallback to file_size_mb if available
        if hasattr(self, 'file_size_mb') and self.file_size_mb:
            return self.file_size_mb * 1024 * 1024
            
        return 0
    
    def get_viewing_file(self):
        """Get the best file for viewing (optimized if available, otherwise original)"""
        return self.optimized_file if self.optimized_file else self.original_file
    
    def get_original_file(self):
        """Get the original PDF file for download"""
        return self.original_file
    
    def get_download_file(self):
        """Get the file for download (always original for PDFs)"""
        return self.original_file
    
    def get_direct_download_url(self):
        """Get the direct download URL (R2 if available, otherwise local)"""
        if self.r2_original_file_url:
            return self.r2_original_file_url
        if self.r2_optimized_file_url:
            return self.r2_optimized_file_url
        return self.original_file.url if self.original_file else None
    
    def get_direct_viewing_url(self):
        """Get the direct viewing URL (R2 if available, otherwise local)"""
        if self.r2_optimized_file_url:
            return self.r2_optimized_file_url
        if self.r2_original_file_url:
            return self.r2_original_file_url
        file_obj = self.get_viewing_file()
        return file_obj.url if file_obj else None
    
    # --- R2 Helper Methods ---
    def has_r2_files(self):
        """Check if any R2 files are available"""
        return bool(self.r2_original_file_url or self.r2_optimized_file_url)
    
    def get_r2_status_display(self):
        """Get human-readable R2 upload status"""
        status_map = {
            '': 'Not enabled',
            'pending': 'Pending upload',
            'uploading': f'Uploading ({self.r2_upload_progress or 0}%)',
            'completed': 'Upload complete',
            'failed': 'Upload failed'
        }
        return status_map.get(self.r2_upload_status, 'Unknown')
    
    def get_pdf_url(self):
        """Get the best available viewing URL (R2 URL if available)"""
        if self.r2_optimized_file_url:
            return self.r2_optimized_file_url
        if self.r2_original_file_url:
            return self.r2_original_file_url
            
        file_obj = self.get_viewing_file()
        return file_obj.url if file_obj else None
    
    @property
    def has_seo(self):
        """Check if content has SEO metadata"""
        return bool(
            self.content_item.seo_keywords_ar or 
            self.content_item.seo_keywords_en or 
            self.content_item.seo_meta_description_ar or 
            self.content_item.seo_meta_description_en
        )
    
    @property
    def has_metadata(self):
        """Check if PDF has complete metadata"""
        return bool(
            self.page_count and 
            self.content_item.description_ar and 
            self.content_item.tags.exists()
        )
