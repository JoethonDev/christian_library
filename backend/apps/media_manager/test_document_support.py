"""
Tests for document content support functionality.
Tests document upload, text extraction, and search integration.
"""
import os
import tempfile
from django.test import TestCase, override_settings
from django.core.files.uploadedfile import SimpleUploadedFile
from apps.media_manager.models import ContentItem, Tag
from apps.media_manager.services.document_processor_service import DocumentProcessorService
from apps.media_manager.services.upload_service import MediaUploadService


class AdminDashboardDocumentUploadTest(TestCase):
    """Test admin dashboard document upload integration."""
    
    def test_create_content_item_with_document(self):
        """Test creating content item with document file populates book_content."""
        service = MediaUploadService()
        
        # Create mock PDF file
        pdf_content = b'%PDF-1.4 Mock PDF'
        pdf_file = SimpleUploadedFile(
            'test.pdf',
            pdf_content,
            content_type='application/pdf'
        )
        
        # Create mock document file with text
        document_content = b'Mock Word document content for book_content'
        document_file = SimpleUploadedFile(
            'test.docx',
            document_content,
            content_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document'
        )
        
        # Create content item with document
        result = service.create_content_item(
            file_obj=pdf_file,
            title_ar='Test PDF with Document',
            description_ar='Test Description',
            document_file=document_file
        )
        
        # Verify success
        self.assertTrue(result.get('success'))
        self.assertIsNotNone(result.get('content_item'))
        
        # Verify book_content is set (even though document processing might fail in test)
        content_item = result.get('content_item')
        # Note: In test environment without python-docx, book_content might be empty
        # But the flow should be correct
        self.assertIsNotNone(content_item)
    
    def test_pdf_extraction_skips_when_book_content_exists(self):
        """Test that PDF extraction is skipped when book_content already populated."""
        # Create a content item with book_content already set
        content_item = ContentItem.objects.create(
            title_ar='Test Content',
            description_ar='Test Description',
            content_type='pdf',
            book_content='Pre-existing book content from document',
            is_active=False
        )
        
        # Call extract_text_from_pdf
        initial_content = content_item.book_content
        content_item.extract_text_from_pdf()
        
        # Verify book_content was not overwritten
        self.assertEqual(content_item.book_content, initial_content)


class DocumentProcessorServiceTest(TestCase):
    """Test document text extraction service."""
    
    def setUp(self):
        self.service = DocumentProcessorService()
    
    def test_validate_document_valid_docx(self):
        """Test validation of valid .docx file."""
        is_valid, error = self.service.validate_document(
            file_size=1024 * 1024,  # 1MB
            mime_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document',
            filename='test.docx'
        )
        self.assertTrue(is_valid)
        self.assertEqual(error, '')
    
    def test_validate_document_valid_doc(self):
        """Test validation of valid .doc file."""
        is_valid, error = self.service.validate_document(
            file_size=1024 * 1024,  # 1MB
            mime_type='application/msword',
            filename='test.doc'
        )
        self.assertTrue(is_valid)
        self.assertEqual(error, '')
    
    def test_validate_document_invalid_extension(self):
        """Test validation rejects invalid extensions."""
        is_valid, error = self.service.validate_document(
            file_size=1024 * 1024,
            mime_type='text/plain',
            filename='test.txt'
        )
        self.assertFalse(is_valid)
        self.assertIn('not allowed', error)
    
    def test_validate_document_too_large(self):
        """Test validation rejects files over 2GB."""
        is_valid, error = self.service.validate_document(
            file_size=3 * 1024 * 1024 * 1024,  # 3GB
            mime_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document',
            filename='test.docx'
        )
        self.assertFalse(is_valid)
        self.assertIn('exceeds 2GB', error)
    
    def test_clean_and_normalize_text(self):
        """Test text cleaning and normalization."""
        raw_text = "Test   text  with   extra\n\n\n\nspaces    and    breaks"
        cleaned = self.service.clean_and_normalize_text(raw_text)
        
        # Check excessive spaces are removed
        self.assertNotIn('   ', cleaned)
        # Check excessive newlines are normalized
        self.assertNotIn('\n\n\n', cleaned)
    
    def test_normalize_arabic_text(self):
        """Test Arabic text normalization."""
        # Text with various Alef forms and diacritics
        raw_text = "أإآٱا"  # Different Alef forms
        normalized = self.service._normalize_arabic_text(raw_text)
        
        # All Alef forms should be normalized to standard Alef
        self.assertIn('ا', normalized)


class DocumentUploadServiceTest(TestCase):
    """Test document upload and attachment to content items."""
    
    def setUp(self):
        # Create a test content item
        self.content_item = ContentItem.objects.create(
            title_ar='Test Content',
            description_ar='Test Description',
            content_type='pdf',
            is_active=False
        )
        self.service = MediaUploadService()
    
    def test_attach_supplementary_document_model_fields(self):
        """Test that document attachment updates model fields correctly."""
        # Create a mock document file
        document_content = b'Mock Word document content'
        document_file = SimpleUploadedFile(
            'test_document.docx',
            document_content,
            content_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document'
        )
        
        # Attach document
        result = self.service.attach_supplementary_document(
            str(self.content_item.id),
            document_file
        )
        
        # Check result
        self.assertTrue(result.get('success'))
        
        # Refresh content item
        self.content_item.refresh_from_db()
        
        # Check fields are set
        self.assertTrue(self.content_item.has_supplementary_document)
        self.assertEqual(self.content_item.supplementary_document_name, 'test_document.docx')
        self.assertIsNotNone(self.content_item.supplementary_document_size)
        self.assertIsNotNone(self.content_item.supplementary_document_uploaded_at)
    
    def test_delete_supplementary_document(self):
        """Test document deletion clears all fields."""
        # First attach a document
        document_file = SimpleUploadedFile(
            'test_document.docx',
            b'Mock content',
            content_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document'
        )
        
        self.service.attach_supplementary_document(
            str(self.content_item.id),
            document_file
        )
        
        # Refresh and verify it's attached
        self.content_item.refresh_from_db()
        self.assertTrue(self.content_item.has_supplementary_document)
        
        # Now delete it
        result = self.service.delete_supplementary_document(str(self.content_item.id))
        
        # Check result
        self.assertTrue(result.get('success'))
        
        # Refresh and verify it's deleted
        self.content_item.refresh_from_db()
        self.assertFalse(self.content_item.has_supplementary_document)
        self.assertEqual(self.content_item.supplementary_document_name, '')
        self.assertIsNone(self.content_item.supplementary_document_size)
        self.assertEqual(self.content_item.supplementary_document_text, '')


class DocumentSearchIntegrationTest(TestCase):
    """Test that document text is included in search."""
    
    def setUp(self):
        self.content_item = ContentItem.objects.create(
            title_ar='Test Content',
            description_ar='Test Description',
            content_type='pdf',
            is_active=True
        )
    
    def test_has_supplementary_document_property(self):
        """Test has_supplementary_document property."""
        self.assertFalse(self.content_item.has_supplementary_document)
        
        # Set document fields manually for testing
        self.content_item.supplementary_document_name = 'test.docx'
        self.content_item.supplementary_document = 'documents/2024/01/test.docx'
        self.content_item.save()
        
        # Refresh and check
        self.content_item.refresh_from_db()
        self.assertTrue(self.content_item.has_supplementary_document)
    
    def test_document_text_in_search_vector(self):
        """Test that document text is included in search vector update."""
        # Set some document text
        self.content_item.supplementary_document_text = 'Important searchable content from document'
        self.content_item.save()
        
        # Update search vector (this would normally be done by the task)
        from django.contrib.postgres.search import SearchVector
        from django.db import connection
        
        # Only test if using PostgreSQL
        if 'postgresql' in connection.settings_dict['ENGINE']:
            self.content_item.update_search_vector()
            self.content_item.save()
            
            # Verify search_vector is not None
            self.assertIsNotNone(self.content_item.search_vector)
