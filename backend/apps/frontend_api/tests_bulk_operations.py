"""
Tests for bulk operations in content management dashboard
"""
from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth.models import User
from apps.media_manager.models import ContentItem, VideoMeta, AudioMeta, PdfMeta, Tag
import json
import uuid


class BulkOperationsTestCase(TestCase):
    """Test cases for bulk operations on content items"""
    
    def setUp(self):
        """Set up test client and create test data"""
        self.client = Client()
        
        # Create test user
        self.user = User.objects.create_user(
            username='testuser',
            password='testpass123',
            is_staff=True
        )
        
        # Login
        self.client.login(username='testuser', password='testpass123')
        
        # Create test tags
        self.tag1 = Tag.objects.create(name_ar='تعليم', name_en='Teaching')
        self.tag2 = Tag.objects.create(name_ar='وعظ', name_en='Preaching')
        
        # Create test video content
        self.video1 = ContentItem.objects.create(
            title_ar='فيديو اختبار 1',
            title_en='Test Video 1',
            description_ar='وصف الفيديو 1',
            content_type='video',
            is_active=True
        )
        self.video1_meta = VideoMeta.objects.create(
            content_item=self.video1,
            processing_status='completed',
            duration_seconds=120
        )
        self.video1.tags.add(self.tag1)
        
        self.video2 = ContentItem.objects.create(
            title_ar='فيديو اختبار 2',
            title_en='Test Video 2',
            description_ar='وصف الفيديو 2',
            content_type='video',
            is_active=True
        )
        self.video2_meta = VideoMeta.objects.create(
            content_item=self.video2,
            processing_status='completed',
            duration_seconds=180
        )
        self.video2.tags.add(self.tag2)
        
        # Create test audio content
        self.audio1 = ContentItem.objects.create(
            title_ar='صوت اختبار 1',
            title_en='Test Audio 1',
            description_ar='وصف الصوت 1',
            content_type='audio',
            is_active=False
        )
        self.audio1_meta = AudioMeta.objects.create(
            content_item=self.audio1,
            processing_status='completed',
            duration_seconds=90
        )
        
        # Create test PDF content
        self.pdf1 = ContentItem.objects.create(
            title_ar='كتاب اختبار 1',
            title_en='Test Book 1',
            description_ar='وصف الكتاب 1',
            content_type='pdf',
            is_active=True
        )
        self.pdf1_meta = PdfMeta.objects.create(
            content_item=self.pdf1,
            processing_status='completed',
            page_count=100
        )
    
    def test_bulk_toggle_status_activate(self):
        """Test bulk activation of content items"""
        # Initially audio1 is inactive
        self.assertFalse(self.audio1.is_active)
        
        # Bulk activate audio1 and pdf1
        response = self.client.post(
            reverse('frontend_api:api_toggle_content_status'),
            data=json.dumps({
                'content_ids': [str(self.audio1.id), str(self.pdf1.id)],
                'is_active': True,
                'bulk': True
            }),
            content_type='application/json'
        )
        
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['success'])
        self.assertEqual(data['updated_count'], 2)
        
        # Verify items are activated
        self.audio1.refresh_from_db()
        self.pdf1.refresh_from_db()
        self.assertTrue(self.audio1.is_active)
        self.assertTrue(self.pdf1.is_active)
    
    def test_bulk_toggle_status_deactivate(self):
        """Test bulk deactivation of content items"""
        # Initially video1 and video2 are active
        self.assertTrue(self.video1.is_active)
        self.assertTrue(self.video2.is_active)
        
        # Bulk deactivate video1 and video2
        response = self.client.post(
            reverse('frontend_api:api_toggle_content_status'),
            data=json.dumps({
                'content_ids': [str(self.video1.id), str(self.video2.id)],
                'is_active': False,
                'bulk': True
            }),
            content_type='application/json'
        )
        
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['success'])
        self.assertEqual(data['updated_count'], 2)
        
        # Verify items are deactivated
        self.video1.refresh_from_db()
        self.video2.refresh_from_db()
        self.assertFalse(self.video1.is_active)
        self.assertFalse(self.video2.is_active)
    
    def test_single_toggle_status(self):
        """Test single item status toggle (backward compatibility)"""
        # Initially video1 is active
        self.assertTrue(self.video1.is_active)
        
        # Toggle single item (should use admin_service)
        response = self.client.post(
            reverse('frontend_api:api_toggle_content_status'),
            data=json.dumps({
                'content_id': str(self.video1.id),
                'is_active': False
            }),
            content_type='application/json'
        )
        
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['success'])
        
        # Verify item is deactivated
        self.video1.refresh_from_db()
        self.assertFalse(self.video1.is_active)
    
    def test_bulk_auto_fill_metadata(self):
        """Test bulk SEO metadata generation"""
        # This test will trigger background tasks
        # We only test that the endpoint accepts bulk requests correctly
        response = self.client.post(
            reverse('frontend_api:api_auto_fill_metadata'),
            data=json.dumps({
                'content_ids': [str(self.video1.id), str(self.video2.id)]
            }),
            content_type='application/json'
        )
        
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['success'])
        self.assertIn('task_ids', data)
        # Should have task IDs for each content item
        self.assertIsInstance(data['task_ids'], list)
    
    def test_single_auto_fill_metadata(self):
        """Test single item SEO metadata generation (backward compatibility)"""
        response = self.client.post(
            reverse('frontend_api:api_auto_fill_metadata'),
            data=json.dumps({
                'content_id': str(self.video1.id)
            }),
            content_type='application/json'
        )
        
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['success'])
        self.assertIn('task_id', data)
    
    def test_bulk_operations_require_authentication(self):
        """Test that bulk operations require authentication"""
        # Logout
        self.client.logout()
        
        # Try bulk operation without authentication
        response = self.client.post(
            reverse('frontend_api:api_toggle_content_status'),
            data=json.dumps({
                'content_ids': [str(self.video1.id)],
                'is_active': False,
                'bulk': True
            }),
            content_type='application/json'
        )
        
        # Should redirect to login or return 403
        self.assertIn(response.status_code, [302, 403])
    
    def test_bulk_operation_with_empty_list(self):
        """Test bulk operation with empty content_ids list"""
        response = self.client.post(
            reverse('frontend_api:api_toggle_content_status'),
            data=json.dumps({
                'content_ids': [],
                'is_active': True,
                'bulk': True
            }),
            content_type='application/json'
        )
        
        self.assertEqual(response.status_code, 200)
        data = response.json()
        # Should succeed but update 0 items
        self.assertTrue(data['success'])
        self.assertEqual(data['updated_count'], 0)
    
    def test_bulk_operation_with_invalid_ids(self):
        """Test bulk operation with non-existent content IDs"""
        fake_id = str(uuid.uuid4())
        
        response = self.client.post(
            reverse('frontend_api:api_toggle_content_status'),
            data=json.dumps({
                'content_ids': [fake_id],
                'is_active': True,
                'bulk': True
            }),
            content_type='application/json'
        )
        
        self.assertEqual(response.status_code, 200)
        data = response.json()
        # Should succeed but update 0 items
        self.assertTrue(data['success'])
        self.assertEqual(data['updated_count'], 0)


class ContentManagementPageTestCase(TestCase):
    """Test cases for content management pages with bulk selection"""
    
    def setUp(self):
        """Set up test client and create test data"""
        self.client = Client()
        
        # Create test user
        self.user = User.objects.create_user(
            username='testuser',
            password='testpass123',
            is_staff=True
        )
        
        # Login
        self.client.login(username='testuser', password='testpass123')
        
        # Create test video
        self.video = ContentItem.objects.create(
            title_ar='فيديو اختبار',
            title_en='Test Video',
            content_type='video',
            is_active=True
        )
        VideoMeta.objects.create(
            content_item=self.video,
            processing_status='completed'
        )
    
    def test_video_management_page_loads(self):
        """Test that video management page loads successfully"""
        response = self.client.get(reverse('frontend_api:video_management'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Video Manager')
        # Check for bulk selection checkbox
        self.assertContains(response, 'selectAll')
        self.assertContains(response, 'row-checkbox')
    
    def test_audio_management_page_loads(self):
        """Test that audio management page loads successfully"""
        response = self.client.get(reverse('frontend_api:audio_management'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Audio Manager')
        # Check for bulk selection checkbox
        self.assertContains(response, 'selectAll')
        self.assertContains(response, 'row-checkbox')
    
    def test_pdf_management_page_loads(self):
        """Test that PDF management page loads successfully"""
        response = self.client.get(reverse('frontend_api:pdf_management'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'PDF Manager')
        # Check for bulk selection checkbox
        self.assertContains(response, 'selectAll')
        self.assertContains(response, 'row-checkbox')
    
    def test_management_page_has_bulk_actions(self):
        """Test that management pages have bulk action controls"""
        response = self.client.get(reverse('frontend_api:video_management'))
        self.assertEqual(response.status_code, 200)
        # Check for bulk action bar
        self.assertContains(response, 'bulkActionsBar')
        self.assertContains(response, 'bulkGenerateSEO')
        self.assertContains(response, 'bulkActivate')
        self.assertContains(response, 'bulkDeactivate')
        self.assertContains(response, 'bulkDelete')
    
    def test_management_page_filters_work(self):
        """Test that filters work on management pages"""
        # Test missing_data filter
        response = self.client.get(
            reverse('frontend_api:video_management'),
            {'missing_data': 'no_seo'}
        )
        self.assertEqual(response.status_code, 200)
        
        # Test status filter
        response = self.client.get(
            reverse('frontend_api:video_management'),
            {'status': 'active'}
        )
        self.assertEqual(response.status_code, 200)
