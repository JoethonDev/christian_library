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
from django.db import models
from django.utils.translation import gettext_lazy as _
from django.core.exceptions import ValidationError
from django.urls import reverse
import uuid
# For full-text search support
from django.contrib.postgres.indexes import GinIndex
from django.contrib.postgres.search import SearchVectorField, SearchVector
from django.contrib.postgres.fields import ArrayField
from apps.media_manager.tasks import extract_and_index_contentitem
from pdfminer.high_level import extract_text
from django.contrib.postgres.search import SearchVector
from django.db import connection
import os
import logging
import fitz  # PyMuPDF for PDF processing and OCR fallback
from PIL import Image
import io
import subprocess
from pathlib import Path



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
        """Return most popular tags based on content count"""
        return self.annotate(
            content_count=models.Count('contentitem')
        ).order_by('-content_count')[:limit]


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


class ContentItemManager(models.Manager):
    """Custom manager for ContentItem with optimized queries"""
    
    def active(self):
        """Return only active content items"""
        return self.filter(is_active=True)
    
    def by_type(self, content_type):
        """Return content items by type"""
        return self.filter(content_type=content_type)
    
    def with_meta(self):
        """Return content items with related meta objects"""
        return self.prefetch_related('tags')
    
    def videos_with_meta(self):
        """Return videos with video meta"""
        return self.filter(content_type='video').select_related('videometa').prefetch_related('tags')
    
    def audios_with_meta(self):
        """Return audios with audio meta"""
        return self.filter(content_type='audio').select_related('audiometa').prefetch_related('tags')
    
    def pdfs_with_meta(self):
        """Return PDFs with PDF meta"""
        return self.filter(content_type='pdf').select_related('pdfmeta').prefetch_related('tags')
    
    def by_tags(self, tags):
        """Return content items filtered by tags"""
        return self.filter(tags__in=tags).distinct()
    
    def untagged(self):
        """Return content items without any tags"""
        return self.filter(tags__isnull=True)


class ContentItem(models.Model):
    def save(self, *args, **kwargs):
        """
        Override save to trigger background extraction/indexing if relevant fields change.
        Extraction and FTS update are always done in the background (never synchronously).
        """
        is_new = self._state.adding
        super().save(*args, **kwargs)
        # Only trigger for PDFs
        if self.content_type == 'pdf':
            self.trigger_background_extraction_and_indexing()

    def trigger_background_extraction_and_indexing(self):
        """
        Trigger a Celery task to extract text and update FTS in the background.
        """
        extract_and_index_contentitem.delay(str(self.id))

    def extract_text_from_pdf(self):
        """
        Extract text from the associated PDF file (PdfMeta.original_file) and store in book_content.
        This should be called from a background task. Supports Arabic text extraction.
        Falls back to OCR if PDF contains only images.
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
            
            logger.info(f"Starting text extraction for PDF: {self.id}")
            
            # First try: Extract text using pdfminer
            text = extract_text(pdf_path)
            
            # Clean and validate extracted text
            if text and text.strip() and len(text.strip()) > 10:
                self.book_content = text.strip()
                logger.info(f"Successfully extracted {len(text)} characters using pdfminer for PDF {self.id}")
                return
            
            # Second try: Use PyMuPDF for better text extraction
            logger.info(f"Pdfminer extraction minimal, trying PyMuPDF for PDF {self.id}")
            text = self._extract_text_with_pymupdf(pdf_path)
            
            if text and text.strip() and len(text.strip()) > 10:
                self.book_content = text.strip()
                logger.info(f"Successfully extracted {len(text)} characters using PyMuPDF for PDF {self.id}")
                return
            
            # Third try: OCR fallback for image-based PDFs
            logger.info(f"PDF appears to be image-based, attempting OCR for PDF {self.id}")
            text = self._extract_text_with_ocr(pdf_path)
            
            if text and text.strip():
                self.book_content = text.strip()
                logger.info(f"Successfully extracted {len(text)} characters using OCR for PDF {self.id}")
                return
            
            # If all methods fail
            logger.warning(f"All text extraction methods failed for PDF {self.id}")
            self.book_content = ''
            
        except Exception as e:
            logger.error(f"Error extracting text from PDF {self.id}: {str(e)}", exc_info=True)
            self.book_content = ''

    def _extract_text_with_pymupdf(self, pdf_path):
        """
        Extract text using PyMuPDF (fitz) which often works better than pdfminer.
        """
        try:
            text_content = []
            with fitz.open(pdf_path) as doc:
                for page_num in range(len(doc)):
                    page = doc.load_page(page_num)
                    page_text = page.get_text()
                    if page_text.strip():
                        text_content.append(page_text)
            
            return '\n\n'.join(text_content) if text_content else ''
        except Exception as e:
            logging.getLogger(__name__).warning(f"PyMuPDF extraction failed: {str(e)}")
            return ''

    def _extract_text_with_ocr(self, pdf_path):
        """
        Extract text using OCR (Tesseract) for image-based PDFs.
        Supports Arabic text recognition.
        """
        logger = logging.getLogger(__name__)
        
        try:
            # Check if Tesseract is available
            result = subprocess.run(['tesseract', '--version'], 
                                  capture_output=True, text=True, check=True)
            if 'tesseract' not in result.stdout.lower():
                logger.warning("Tesseract OCR not available, skipping OCR extraction")
                return ''
        except (subprocess.CalledProcessError, FileNotFoundError):
            logger.warning("Tesseract OCR not available, skipping OCR extraction")
            return ''
        
        try:
            text_content = []
            
            # Convert PDF pages to images and perform OCR
            with fitz.open(pdf_path) as doc:
                for page_num in range(len(doc)):
                    page = doc.load_page(page_num)
                    
                    # Convert page to image
                    mat = fitz.Matrix(2.0, 2.0)  # Higher resolution for better OCR
                    pix = page.get_pixmap(matrix=mat)
                    img_data = pix.tobytes("png")
                    
                    # Create temporary image file for Tesseract
                    temp_image_path = f"/tmp/ocr_page_{self.id}_{page_num}.png"
                    temp_text_path = f"/tmp/ocr_text_{self.id}_{page_num}"
                    
                    try:
                        # Save image temporarily
                        with open(temp_image_path, "wb") as img_file:
                            img_file.write(img_data)
                        
                        # Run Tesseract OCR with Arabic and English
                        cmd = [
                            'tesseract', 
                            temp_image_path, 
                            temp_text_path, 
                            '-l', 'ara+eng',  # Arabic + English
                            '--oem', '3',     # Use LSTM OCR engine
                            '--psm', '6'      # Assume uniform block of text
                        ]
                        
                        subprocess.run(cmd, check=True, capture_output=True)
                        
                        # Read OCR output
                        output_file = f"{temp_text_path}.txt"
                        if os.path.exists(output_file):
                            with open(output_file, 'r', encoding='utf-8') as f:
                                page_text = f.read().strip()
                                if page_text:
                                    text_content.append(page_text)
                    
                    except Exception as page_error:
                        logger.warning(f"OCR failed for page {page_num}: {str(page_error)}")
                        continue
                    
                    finally:
                        # Clean up temporary files
                        for temp_file in [temp_image_path, f"{temp_text_path}.txt"]:
                            if os.path.exists(temp_file):
                                try:
                                    os.remove(temp_file)
                                except:
                                    pass
            
            # Join all page texts
            full_text = '\n\n'.join(text_content) if text_content else ''
            
            if full_text:
                logger.info(f"OCR extraction completed for PDF {self.id}: {len(full_text)} characters")
            
            return full_text
            
        except Exception as e:
            logger.error(f"OCR extraction failed for PDF {self.id}: {str(e)}", exc_info=True)
            return ''

    def update_search_vector(self):
        """
        Update the search_vector field using book_content, title_ar, and description_ar.
        Should use PostgreSQL FTS with Arabic language config.
        This should be called from a background task.
        """
        # Use weights: A for title, B for description, C for content
        vector = (
            SearchVector('title_ar', weight='A', config='arabic') +
            SearchVector('description_ar', weight='B', config='arabic') +
            SearchVector('book_content', weight='C', config='arabic')
        )
        # Update only this instance
        ContentItem = self.__class__
        ContentItem.objects.filter(pk=self.pk).update(
            search_vector=vector
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
    is_active = models.BooleanField(default=True, verbose_name=_('Active'), db_index=True)
    created_at = models.DateTimeField(auto_now_add=True, verbose_name=_('Created At'), db_index=True)
    updated_at = models.DateTimeField(auto_now=True, verbose_name=_('Updated At'))

    # --- Full-Text Search & Content Extraction Fields ---
    # Stores extracted book text (supports Arabic, can hold millions of characters)
    book_content = models.TextField(blank=True, null=True, verbose_name=_('Extracted Book Content'))
    # PostgreSQL SearchVectorField for FTS (supports Arabic config)
    search_vector = SearchVectorField(blank=True, null=True, verbose_name=_('Search Vector'))

    # --- SEO Metadata Fields (Generated by Gemini AI) ---
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

    # --- SEO Helper Methods ---
    def has_seo_metadata(self):
        """Check if this content item has SEO metadata generated"""
        return bool(self.seo_keywords_ar or self.seo_keywords_en or self.structured_data)

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
            'tags_en', 'seo_keywords_ar', 'seo_keywords_en',
            'seo_meta_description_ar', 'seo_meta_description_en',
            'seo_title_suggestions', 'structured_data',
            'title_ar', 'title_en', 'description_ar', 'description_en',
            'updated_at'
        ])
        
        return True
    

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
    
    class Meta:
        verbose_name = _('Video Metadata')
        verbose_name_plural = _('Video Metadata')
        indexes = [
            models.Index(fields=['processing_status']),
            models.Index(fields=['duration_seconds']),
        ]
    
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
    
    class Meta:
        verbose_name = _('Audio Metadata')
        verbose_name_plural = _('Audio Metadata')
        indexes = [
            models.Index(fields=['processing_status']),
            models.Index(fields=['duration_seconds']),
        ]
    
    def __str__(self):
        return f"{_('Audio')}: {self.content_item.title_ar}"
    
    def is_ready_for_playback(self):
        """Check if audio is ready for playback"""
        return (self.processing_status == 'completed' and 
                (self.compressed_file or self.original_file))
    
    def get_playback_file(self):
        """Get the best file for playback (compressed if available)"""
        return self.compressed_file if self.compressed_file else self.original_file
    
    def get_duration_formatted(self):
        """Get formatted duration string"""
        if not self.duration_seconds:
            return _('Unknown')
        
        minutes = self.duration_seconds // 60
        seconds = self.duration_seconds % 60
        return f"{minutes:02d}:{seconds:02d}"


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
    
    class Meta:
        verbose_name = _('PDF Metadata')
        verbose_name_plural = _('PDF Metadata')
        indexes = [
            models.Index(fields=['processing_status']),
            models.Index(fields=['file_size_mb']),
            models.Index(fields=['page_count']),
        ]
    
    def __str__(self):
        return f"{_('PDF')}: {self.content_item.title_ar}"
    
    def is_ready_for_viewing(self):
        """Check if PDF is ready for viewing"""
        return (self.processing_status == 'completed' and 
                (self.optimized_file or self.original_file))
    
    def get_viewing_file(self):
        """Get the best file for viewing (optimized if available, otherwise original)"""
        return self.optimized_file if self.optimized_file else self.original_file
    
    def get_original_file(self):
        """Get the original PDF file for download"""
        return self.original_file
    
    def get_download_file(self):
        """Get the file for download (always original for PDFs)"""
        return self.original_file