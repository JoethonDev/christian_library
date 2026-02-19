"""
Tests for RESTful Upload API.
"""
import os
import tempfile
from django.test import TestCase, override_settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient
from apps.media_manager.models import APIUploadQueue, APIUploadLog
from apps.media_manager.api.authentication import APISecretKeyAuthentication

User = get_user_model()


@override_settings(API_SECRET_KEY='test-secret-key-12345')
class APIAuthenticationTestCase(TestCase):
    """Test API authentication."""
    
    def setUp(self):
        self.client = APIClient()
    
    def test_missing_api_key(self):
        """Test request without API key."""
        response = self.client.get('/api/v1/queue/')
        self.assertEqual(response.status_code, 401)
    
    def test_invalid_api_key(self):
        """Test request with invalid API key."""
        response = self.client.get(
            '/api/v1/queue/',
            HTTP_X_API_SECRET_KEY='invalid-key'
        )
        self.assertEqual(response.status_code, 403)
    
    def test_valid_api_key(self):
        """Test request with valid API key."""
        response = self.client.get(
            '/api/v1/queue/',
            HTTP_X_API_SECRET_KEY='test-secret-key-12345'
        )
        self.assertIn(response.status_code, [200, 404])  # 404 if no queue items


@override_settings(API_SECRET_KEY='test-secret-key-12345', MEDIA_ROOT=tempfile.mkdtemp())
class ContentUploadAPITestCase(TestCase):
    """Test content upload API endpoints."""
    
    def setUp(self):
        self.client = APIClient()
        self.api_key = 'test-secret-key-12345'
    
    def _create_test_file(self, name='test.pdf', content=b'test content', content_type='application/pdf'):
        """Helper to create test file."""
        return SimpleUploadedFile(name, content, content_type=content_type)
    
    def test_minimal_upload(self):
        """Test minimal file-only upload."""
        file = self._create_test_file('test.pdf')
        
        response = self.client.post(
            '/api/v1/upload/',
            {'file': file},
            HTTP_X_API_SECRET_KEY=self.api_key,
            format='multipart'
        )
        
        self.assertIn(response.status_code, [201, 202])
        self.assertIn('queue_id', response.data)
        self.assertIn('status', response.data)
        self.assertIn('content_type', response.data)
    
    def test_full_upload_with_metadata(self):
        """Test upload with full metadata."""
        file = self._create_test_file('test.pdf')
        
        response = self.client.post(
            '/api/v1/upload/',
            {
                'file': file,
                'title_ar': 'عنوان اختبار',
                'title_en': 'Test Title',
                'description_ar': 'وصف اختبار',
                'description_en': 'Test Description',
            },
            HTTP_X_API_SECRET_KEY=self.api_key,
            format='multipart'
        )
        
        self.assertIn(response.status_code, [201, 202])
        
        # Verify queue item created
        queue_item = APIUploadQueue.objects.filter(
            id=response.data['queue_id']
        ).first()
        self.assertIsNotNone(queue_item)
        self.assertEqual(queue_item.file_name, 'test.pdf')
        self.assertEqual(queue_item.content_type, 'pdf')
    
    def test_invalid_file_type(self):
        """Test upload with unsupported file type."""
        file = self._create_test_file('test.txt', content_type='text/plain')
        
        response = self.client.post(
            '/api/v1/upload/',
            {'file': file},
            HTTP_X_API_SECRET_KEY=self.api_key,
            format='multipart'
        )
        
        self.assertEqual(response.status_code, 400)
        self.assertIn('errors', response.data)
    
    def test_queue_status(self):
        """Test queue status endpoint."""
        # Create a queue item first
        file = self._create_test_file('test.pdf')
        upload_response = self.client.post(
            '/api/v1/upload/',
            {'file': file},
            HTTP_X_API_SECRET_KEY=self.api_key,
            format='multipart'
        )
        
        queue_id = upload_response.data['queue_id']
        
        # Check status
        response = self.client.get(
            f'/api/v1/queue/status/{queue_id}/',
            HTTP_X_API_SECRET_KEY=self.api_key
        )
        
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['queue_id'], queue_id)
        self.assertIn('status', response.data)
        self.assertIn('queue_status', response.data)


@override_settings(API_SECRET_KEY='test-secret-key-12345', MEDIA_ROOT=tempfile.mkdtemp())
class BulkUploadAPITestCase(TestCase):
    """Test bulk upload API endpoint."""
    
    def setUp(self):
        self.client = APIClient()
        self.api_key = 'test-secret-key-12345'
    
    def _create_test_file(self, name='test.pdf', content=b'test content'):
        """Helper to create test file."""
        return SimpleUploadedFile(name, content, content_type='application/pdf')
    
    def test_bulk_upload(self):
        """Test bulk file upload."""
        files = [
            self._create_test_file('test1.pdf'),
            self._create_test_file('test2.pdf'),
            self._create_test_file('test3.pdf'),
        ]
        
        response = self.client.post(
            '/api/v1/upload/bulk/',
            {'files': files},
            HTTP_X_API_SECRET_KEY=self.api_key,
            format='multipart'
        )
        
        self.assertEqual(response.status_code, 202)
        self.assertIn('queue_items', response.data)
        self.assertEqual(response.data['total'], 3)
        self.assertGreaterEqual(response.data['queued'] + response.data['processing'], 3)


class QueueManagementTestCase(TestCase):
    """Test queue management operations."""
    
    def setUp(self):
        self.queue_item = APIUploadQueue.objects.create(
            file_name='test.pdf',
            file_path='/tmp/test.pdf',
            content_type='pdf',
            file_size_mb=1.5,
            status='pending',
            queue_status='waiting'
        )
    
    def test_queue_position(self):
        """Test queue position calculation."""
        position = self.queue_item.get_queue_position()
        self.assertGreaterEqual(position, 1)
    
    def test_can_process(self):
        """Test can_process check."""
        can_process = self.queue_item.can_process()
        self.assertTrue(can_process)
        
        # Change status to processing
        self.queue_item.status = 'processing'
        self.queue_item.save()
        
        can_process = self.queue_item.can_process()
        self.assertFalse(can_process)
    
    def test_schedule_for_next_day(self):
        """Test scheduling for next day at 3:00 AM."""
        self.queue_item.schedule_for_next_day()
        
        self.queue_item.refresh_from_db()
        self.assertEqual(self.queue_item.delay_count, 1)
        self.assertEqual(self.queue_item.status, 'rate_limited')
        self.assertEqual(self.queue_item.queue_status, 'delayed')
        self.assertIsNotNone(self.queue_item.scheduled_for)
    
    def test_promote_to_ready(self):
        """Test promoting item to ready status."""
        self.queue_item.promote_to_ready()
        
        self.queue_item.refresh_from_db()
        self.assertEqual(self.queue_item.priority, 1000)
        self.assertEqual(self.queue_item.queue_status, 'ready')
    
    def test_delay_count_cancellation(self):
        """Test automatic cancellation after 7 delays."""
        self.queue_item.delay_count = 6
        self.queue_item.save()
        
        self.queue_item.schedule_for_next_day()
        
        self.queue_item.refresh_from_db()
        self.assertEqual(self.queue_item.delay_count, 7)
        self.assertEqual(self.queue_item.status, 'cancelled')
