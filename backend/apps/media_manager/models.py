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

See tests.py for FTS/Arabic search tests.
"""
from django.db import models
from django.utils.translation import gettext_lazy as _
from django.core.exceptions import ValidationError
from django.urls import reverse
import uuid
# For full-text search support
from django.contrib.postgres.indexes import GinIndex
from django.contrib.postgres.search import SearchVectorField
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
            models.Index(fields=['is_active', 'name_ar']),
        ]
    
    def __str__(self):
        return self.name_ar
    
    def get_name(self, language='ar'):
        """Get name in specified language"""
        return self.name_ar if language == 'ar' else (self.name_en or self.name_ar)
    
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

    # Custom manager
    objects = ContentItemManager()

    class Meta:
        verbose_name = _('Content Item')
        verbose_name_plural = _('Content Items')
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['content_type', 'is_active', '-created_at']),
            models.Index(fields=['is_active', '-created_at']),
            GinIndex(fields=['search_vector']),  # GIN index for FTS
        ]

    def __str__(self):
        return self.title_ar

    def get_title(self, language='ar'):
        """Get title in specified language"""
        return self.title_ar if language == 'ar' else (self.title_en or self.title_ar)

    def get_description(self, language='ar'):
        """Get description in specified language"""
        return self.description_ar if language == 'ar' else (self.description_en or self.description_ar)

    def get_absolute_url(self):
        """Get the absolute URL for this content item"""
        return reverse('frontend_api:content_detail', kwargs={
            'content_type': self.content_type,
            'pk': self.id
        })

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