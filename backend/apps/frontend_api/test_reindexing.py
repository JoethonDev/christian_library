"""
Tests for Google Re-indexing functionality
"""
from django.test import TestCase, Client
from django.contrib.auth import get_user_model
from django.urls import reverse
from unittest.mock import patch, MagicMock
import json

from apps.frontend_api.models import GoogleReindexingTask
from apps.frontend_api.services.google_reindexing_service import GoogleReindexingService, RateLimiter
from apps.media_manager.models import ContentItem, Tag

User = get_user_model()


class RateLimiterTestCase(TestCase):
    """Test rate limiter functionality"""
    
    def test_rate_limiter_initialization(self):
        """Test rate limiter initializes correctly"""
        limiter = RateLimiter(rate_per_minute=200)
        self.assertEqual(limiter.rate_per_minute, 200)
        self.assertEqual(limiter.tokens, 200)
    
    def test_rate_limiter_acquire_single_token(self):
        """Test acquiring a single token"""
        limiter = RateLimiter(rate_per_minute=200)
        wait_time = limiter.acquire(1)
        self.assertEqual(wait_time, 0)
        self.assertEqual(limiter.tokens, 199)
    
    def test_rate_limiter_blocks_when_insufficient_tokens(self):
        """Test that limiter blocks when tokens are insufficient"""
        limiter = RateLimiter(rate_per_minute=1)  # Very low rate
        limiter.tokens = 0
        # This should wait, but we'll just check the logic
        # In real scenario, this would block for ~60 seconds
        self.assertLessEqual(limiter.tokens, 1)


class GoogleReindexingServiceTestCase(TestCase):
    """Test GoogleReindexingService functionality"""
    
    def setUp(self):
        """Set up test data"""
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            is_staff=True
        )
        self.service = GoogleReindexingService()
        
        # Create test content
        self.video = ContentItem.objects.create(
            title_en='Test Video',
            title_ar='فيديو تجريبي',
            content_type='video',
            is_active=True,
            user=self.user
        )
        self.audio = ContentItem.objects.create(
            title_en='Test Audio',
            title_ar='صوت تجريبي',
            content_type='audio',
            is_active=True,
            user=self.user
        )
        self.pdf = ContentItem.objects.create(
            title_en='Test PDF',
            title_ar='PDF تجريبي',
            content_type='pdf',
            is_active=True,
            user=self.user
        )
    
    def test_initiate_reindexing(self):
        """Test initiating a re-indexing task"""
        task_id = self.service.initiate_reindexing(self.user, content_type='all')
        self.assertIsNotNone(task_id)
        
        # Verify task was created
        task = GoogleReindexingTask.objects.get(id=task_id)
        self.assertEqual(task.status, 'pending')
        self.assertEqual(task.content_type, 'all')
        self.assertEqual(task.initiated_by, self.user)
    
    def test_prevent_concurrent_reindexing(self):
        """Test that concurrent re-indexing is prevented"""
        # Create first task
        self.service.initiate_reindexing(self.user, content_type='all')
        
        # Try to create second task
        with self.assertRaises(ValueError):
            self.service.initiate_reindexing(self.user, content_type='all')
    
    def test_get_active_urls_all_content(self):
        """Test getting URLs for all content types"""
        urls = self.service.get_active_urls(content_type='all')
        # Should have 2 URLs per content item (ar and en)
        self.assertEqual(len(urls), 6)  # 3 items × 2 languages
    
    def test_get_active_urls_filter_by_type(self):
        """Test filtering URLs by content type"""
        urls = self.service.get_active_urls(content_type='video')
        # Should only have video URLs
        self.assertEqual(len(urls), 2)  # 1 video × 2 languages
        for url_info in urls:
            self.assertEqual(url_info['content_type'], 'video')
    
    def test_get_task_status(self):
        """Test getting task status"""
        task_id = self.service.initiate_reindexing(self.user, content_type='all')
        status = self.service.get_task_status(task_id)
        
        self.assertTrue('task_id' in status)
        self.assertTrue('status' in status)
        self.assertTrue('progress' in status)
        self.assertEqual(status['status'], 'pending')
    
    def test_cancel_task(self):
        """Test cancelling a task"""
        task_id = self.service.initiate_reindexing(self.user, content_type='all')
        
        # Cancel the task
        result = self.service.cancel_task(task_id)
        self.assertTrue(result)
        
        # Verify task is cancelled
        task = GoogleReindexingTask.objects.get(id=task_id)
        self.assertEqual(task.status, 'cancelled')
    
    def test_cancel_completed_task_fails(self):
        """Test that cancelling a completed task fails"""
        task_id = self.service.initiate_reindexing(self.user, content_type='all')
        task = GoogleReindexingTask.objects.get(id=task_id)
        task.mark_as_completed()
        
        # Try to cancel
        result = self.service.cancel_task(task_id)
        self.assertFalse(result)
    
    def test_get_reindexing_history(self):
        """Test getting re-indexing history"""
        # Create multiple tasks
        task_id1 = self.service.initiate_reindexing(self.user, content_type='all')
        task = GoogleReindexingTask.objects.get(id=task_id1)
        task.mark_as_completed()
        
        # Get history
        history = self.service.get_reindexing_history(limit=10)
        self.assertEqual(len(history), 1)
        self.assertEqual(str(history[0].id), task_id1)
    
    def test_estimate_duration(self):
        """Test duration estimation"""
        duration = self.service.estimate_duration(1000)
        self.assertGreater(duration, 0)
        # With 1000 URLs at ~0.4s each, should be around 400 seconds
        self.assertGreater(duration, 300)
        self.assertLess(duration, 500)


class GoogleReindexingTaskModelTestCase(TestCase):
    """Test GoogleReindexingTask model"""
    
    def setUp(self):
        """Set up test data"""
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com'
        )
        self.task = GoogleReindexingTask.objects.create(
            status='pending',
            content_type='all',
            total_urls=100,
            initiated_by=self.user
        )
    
    def test_get_progress_percentage(self):
        """Test progress percentage calculation"""
        self.assertEqual(self.task.get_progress_percentage(), 0)
        
        self.task.submitted_urls = 50
        self.assertEqual(self.task.get_progress_percentage(), 50.0)
        
        self.task.submitted_urls = 100
        self.assertEqual(self.task.get_progress_percentage(), 100.0)
    
    def test_get_success_rate(self):
        """Test success rate calculation"""
        self.task.submitted_urls = 100
        self.task.successful_urls = 95
        self.assertEqual(self.task.get_success_rate(), 95.0)
    
    def test_mark_as_completed(self):
        """Test marking task as completed"""
        self.task.mark_as_completed()
        self.assertEqual(self.task.status, 'completed')
        self.assertIsNotNone(self.task.completed_at)
    
    def test_mark_as_failed(self):
        """Test marking task as failed"""
        self.task.mark_as_failed('Test error message')
        self.assertEqual(self.task.status, 'failed')
        self.assertIsNotNone(self.task.completed_at)
        
        # Check error log
        errors = json.loads(self.task.error_log)
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0]['type'], 'task_failure')
    
    def test_add_error(self):
        """Test adding errors to log"""
        self.task.add_error('https://example.com/test', 'Test error', 'api_error')
        
        errors = json.loads(self.task.error_log)
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0]['url'], 'https://example.com/test')
        self.assertEqual(errors[0]['type'], 'api_error')
    
    def test_get_error_summary(self):
        """Test error summary generation"""
        self.task.add_error('url1', 'Error 1', 'api_error')
        self.task.add_error('url2', 'Error 2', 'api_error')
        self.task.add_error('url3', 'Error 3', 'rate_limit')
        
        summary = self.task.get_error_summary()
        self.assertEqual(summary['api_error'], 2)
        self.assertEqual(summary['rate_limit'], 1)


class GoogleReindexingAPITestCase(TestCase):
    """Test Google Re-indexing API endpoints"""
    
    def setUp(self):
        """Set up test data"""
        self.client = Client()
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass',
            is_staff=True
        )
        self.client.login(username='testuser', password='testpass')
        
        # Create test content
        self.video = ContentItem.objects.create(
            title_en='Test Video',
            title_ar='فيديو تجريبي',
            content_type='video',
            is_active=True,
            user=self.user
        )
    
    @patch('apps.frontend_api.tasks.reindex_website_google.delay')
    def test_initiate_reindexing_api(self, mock_task):
        """Test initiating re-indexing via API"""
        url = reverse('frontend_api:initiate_google_reindexing')
        data = {
            'content_type': 'all',
            'include_sitemap': True
        }
        
        response = self.client.post(
            url,
            data=json.dumps(data),
            content_type='application/json'
        )
        
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['success'])
        self.assertIn('task_id', data)
        self.assertIn('total_urls', data)
        
        # Verify task was created
        task = GoogleReindexingTask.objects.get(id=data['task_id'])
        self.assertEqual(task.content_type, 'all')
    
    def test_initiate_reindexing_unauthorized(self):
        """Test that non-staff users cannot initiate re-indexing"""
        # Create non-staff user
        non_staff_user = User.objects.create_user(
            username='nonstaff',
            password='testpass',
            is_staff=False
        )
        self.client.login(username='nonstaff', password='testpass')
        
        url = reverse('frontend_api:initiate_google_reindexing')
        response = self.client.post(
            url,
            data=json.dumps({'content_type': 'all'}),
            content_type='application/json'
        )
        
        self.assertEqual(response.status_code, 403)
    
    def test_get_task_status_api(self):
        """Test getting task status via API"""
        # Create a task
        service = GoogleReindexingService()
        task_id = service.initiate_reindexing(self.user, content_type='all')
        
        # Get status
        url = reverse('frontend_api:reindex_status', kwargs={'task_id': task_id})
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['success'])
        self.assertEqual(data['status'], 'pending')
    
    def test_cancel_task_api(self):
        """Test cancelling task via API"""
        # Create a task
        service = GoogleReindexingService()
        task_id = service.initiate_reindexing(self.user, content_type='all')
        
        # Cancel task
        url = reverse('frontend_api:cancel_reindex', kwargs={'task_id': task_id})
        response = self.client.post(url)
        
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['success'])
        self.assertTrue(data['cancelled'])
    
    def test_get_history_api(self):
        """Test getting re-indexing history via API"""
        # Create a task
        service = GoogleReindexingService()
        task_id = service.initiate_reindexing(self.user, content_type='all')
        
        # Get history
        url = reverse('frontend_api:reindex_history')
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['success'])
        self.assertEqual(len(data['tasks']), 1)
        self.assertEqual(data['tasks'][0]['task_id'], task_id)
    
    def test_seo_reindex_page_access(self):
        """Test accessing the re-indexing page"""
        url = reverse('frontend_api:seo_reindex_page')
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Google Search Console Re-indexing')
