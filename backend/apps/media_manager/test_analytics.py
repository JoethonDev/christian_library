"""
Tests for Content Analytics functionality.

Tests cover:
- ContentViewEvent model
- DailyContentViewSummary model
- Analytics tracking utility
- Aggregation task
- Analytics dashboard views
- Analytics API endpoints
"""
from django.test import TestCase, RequestFactory
from django.contrib.auth import get_user_model
from django.utils import timezone
from datetime import timedelta, date
import uuid

from apps.media_manager.models import (
    ContentItem, Tag, ContentViewEvent, DailyContentViewSummary,
    VideoMeta, AudioMeta, PdfMeta
)
from apps.media_manager.analytics import record_content_view
from apps.media_manager.tasks import aggregate_daily_content_views

User = get_user_model()


class ContentViewEventModelTest(TestCase):
    """Test ContentViewEvent model"""
    
    def setUp(self):
        """Set up test data"""
        # Create a test content item
        self.tag = Tag.objects.create(
            name_ar='تجريبي',
            name_en='Test',
            is_active=True
        )
        
        self.content = ContentItem.objects.create(
            title_ar='فيديو تجريبي',
            title_en='Test Video',
            description_ar='وصف تجريبي',
            description_en='Test description',
            content_type='video',
            is_active=True
        )
        
        # Create video meta
        self.video_meta = VideoMeta.objects.create(
            content_item=self.content,
            duration_seconds=120,
            processing_status='completed'
        )
    
    def test_create_view_event(self):
        """Test creating a view event"""
        event = ContentViewEvent.objects.create(
            content_type='video',
            content_id=self.content.id,
            user_agent='Mozilla/5.0',
            ip_address='192.168.1.1',
            referrer='https://example.com'
        )
        
        self.assertEqual(event.content_type, 'video')
        self.assertEqual(event.content_id, self.content.id)
        self.assertEqual(event.user_agent, 'Mozilla/5.0')
        self.assertEqual(event.ip_address, '192.168.1.1')
        self.assertIsNotNone(event.timestamp)
    
    def test_view_event_ordering(self):
        """Test that view events are ordered by timestamp descending"""
        event1 = ContentViewEvent.objects.create(
            content_type='video',
            content_id=self.content.id
        )
        
        # Create second event slightly later
        event2 = ContentViewEvent.objects.create(
            content_type='video',
            content_id=self.content.id
        )
        
        events = ContentViewEvent.objects.all()
        # Most recent should be first
        self.assertEqual(events[0].id, event2.id)
        self.assertEqual(events[1].id, event1.id)


class DailyContentViewSummaryModelTest(TestCase):
    """Test DailyContentViewSummary model"""
    
    def setUp(self):
        """Set up test data"""
        self.tag = Tag.objects.create(
            name_ar='تجريبي',
            name_en='Test',
            is_active=True
        )
        
        self.content = ContentItem.objects.create(
            title_ar='محتوى تجريبي',
            title_en='Test Content',
            description_ar='وصف',
            description_en='Description',
            content_type='pdf',
            is_active=True
        )
    
    def test_create_summary(self):
        """Test creating a summary record"""
        today = date.today()
        summary = DailyContentViewSummary.objects.create(
            content_type='pdf',
            content_id=self.content.id,
            date=today,
            view_count=10
        )
        
        self.assertEqual(summary.content_type, 'pdf')
        self.assertEqual(summary.content_id, self.content.id)
        self.assertEqual(summary.date, today)
        self.assertEqual(summary.view_count, 10)
    
    def test_unique_constraint(self):
        """Test that content_type + content_id + date is unique"""
        today = date.today()
        
        DailyContentViewSummary.objects.create(
            content_type='pdf',
            content_id=self.content.id,
            date=today,
            view_count=5
        )
        
        # Creating duplicate should fail
        with self.assertRaises(Exception):
            DailyContentViewSummary.objects.create(
                content_type='pdf',
                content_id=self.content.id,
                date=today,
                view_count=10
            )


class AnalyticsTrackingTest(TestCase):
    """Test analytics tracking utility"""
    
    def setUp(self):
        """Set up test data"""
        self.factory = RequestFactory()
        
        self.tag = Tag.objects.create(
            name_ar='تجريبي',
            name_en='Test',
            is_active=True
        )
        
        self.content = ContentItem.objects.create(
            title_ar='صوتي تجريبي',
            title_en='Test Audio',
            description_ar='وصف',
            description_en='Description',
            content_type='audio',
            is_active=True
        )
    
    def test_record_content_view(self):
        """Test recording a content view"""
        request = self.factory.get('/test/')
        request.META['HTTP_USER_AGENT'] = 'Test Browser'
        request.META['REMOTE_ADDR'] = '10.0.0.1'
        request.META['HTTP_REFERER'] = 'https://google.com'
        
        event = record_content_view(request, 'audio', self.content.id)
        
        self.assertIsNotNone(event)
        self.assertEqual(event.content_type, 'audio')
        self.assertEqual(event.content_id, self.content.id)
        self.assertEqual(event.user_agent, 'Test Browser')
        self.assertEqual(event.ip_address, '10.0.0.1')
        self.assertEqual(event.referrer, 'https://google.com')
    
    def test_record_view_with_proxy(self):
        """Test recording view with X-Forwarded-For header"""
        request = self.factory.get('/test/')
        request.META['HTTP_X_FORWARDED_FOR'] = '203.0.113.1, 198.51.100.1'
        request.META['REMOTE_ADDR'] = '10.0.0.1'
        
        event = record_content_view(request, 'audio', self.content.id)
        
        # Should use first IP from X-Forwarded-For
        self.assertEqual(event.ip_address, '203.0.113.1')


class AggregationTaskTest(TestCase):
    """Test the aggregation Celery task"""
    
    def setUp(self):
        """Set up test data"""
        self.tag = Tag.objects.create(
            name_ar='تجريبي',
            name_en='Test',
            is_active=True
        )
        
        # Create multiple content items
        self.video = ContentItem.objects.create(
            title_ar='فيديو',
            title_en='Video',
            description_ar='وصف',
            description_en='Description',
            content_type='video',
            is_active=True
        )
        
        self.audio = ContentItem.objects.create(
            title_ar='صوتي',
            title_en='Audio',
            description_ar='وصف',
            description_en='Description',
            content_type='audio',
            is_active=True
        )
        
        # Create view events from yesterday
        yesterday = timezone.now() - timedelta(days=1)
        
        # 5 video views
        for _ in range(5):
            ContentViewEvent.objects.create(
                content_type='video',
                content_id=self.video.id,
                timestamp=yesterday
            )
        
        # 3 audio views
        for _ in range(3):
            ContentViewEvent.objects.create(
                content_type='audio',
                content_id=self.audio.id,
                timestamp=yesterday
            )
    
    def test_aggregate_daily_views(self):
        """Test aggregating daily views"""
        # Run aggregation task
        result = aggregate_daily_content_views()
        
        # Check that summaries were created
        yesterday_date = (timezone.now() - timedelta(days=1)).date()
        
        video_summary = DailyContentViewSummary.objects.get(
            content_type='video',
            content_id=self.video.id,
            date=yesterday_date
        )
        self.assertEqual(video_summary.view_count, 5)
        
        audio_summary = DailyContentViewSummary.objects.get(
            content_type='audio',
            content_id=self.audio.id,
            date=yesterday_date
        )
        self.assertEqual(audio_summary.view_count, 3)
        
        # Check result
        self.assertEqual(result['aggregated'], 2)


class AnalyticsDashboardViewTest(TestCase):
    """Test analytics dashboard view"""
    
    def setUp(self):
        """Set up test data"""
        # Create superuser
        self.user = User.objects.create_superuser(
            username='admin',
            email='admin@example.com',
            password='testpass123'
        )
        
        self.tag = Tag.objects.create(
            name_ar='تجريبي',
            name_en='Test',
            is_active=True
        )
        
        # Create content
        self.content = ContentItem.objects.create(
            title_ar='محتوى',
            title_en='Content',
            description_ar='وصف',
            description_en='Description',
            content_type='video',
            is_active=True
        )
        
        # Create summary data
        today = date.today()
        DailyContentViewSummary.objects.create(
            content_type='video',
            content_id=self.content.id,
            date=today,
            view_count=100
        )
    
    def test_analytics_dashboard_requires_login(self):
        """Test that analytics dashboard requires login"""
        response = self.client.get('/en/dashboard/analytics/')
        # Should redirect to login
        self.assertEqual(response.status_code, 302)
    
    def test_analytics_dashboard_authenticated(self):
        """Test analytics dashboard with authenticated user"""
        self.client.login(username='admin', password='testpass123')
        response = self.client.get('/en/dashboard/analytics/')
        
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Content Analytics')
        self.assertContains(response, 'Total Views')
    
    def test_analytics_dashboard_with_date_filter(self):
        """Test analytics dashboard with date range filter"""
        self.client.login(username='admin', password='testpass123')
        response = self.client.get('/en/dashboard/analytics/?days=7')
        
        self.assertEqual(response.status_code, 200)
        self.assertIn('days', response.context)
        self.assertEqual(response.context['days'], 7)


class AnalyticsAPIViewTest(TestCase):
    """Test analytics API endpoint"""
    
    def setUp(self):
        """Set up test data"""
        # Create superuser
        self.user = User.objects.create_superuser(
            username='admin',
            email='admin@example.com',
            password='testpass123'
        )
        
        self.tag = Tag.objects.create(
            name_ar='تجريبي',
            name_en='Test',
            is_active=True
        )
        
        # Create content
        self.content = ContentItem.objects.create(
            title_ar='محتوى',
            title_en='Content',
            description_ar='وصف',
            description_en='Description',
            content_type='pdf',
            is_active=True
        )
        
        # Create summary data
        today = date.today()
        DailyContentViewSummary.objects.create(
            content_type='pdf',
            content_id=self.content.id,
            date=today,
            view_count=50
        )
    
    def test_api_requires_login(self):
        """Test that API requires login"""
        response = self.client.get('/en/dashboard/analytics/api/')
        self.assertEqual(response.status_code, 302)
    
    def test_api_returns_json(self):
        """Test that API returns JSON data"""
        self.client.login(username='admin', password='testpass123')
        response = self.client.get('/en/dashboard/analytics/api/')
        
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/json')
        
        data = response.json()
        self.assertTrue(data['success'])
        self.assertIn('data', data)
        self.assertIn('start_date', data)
        self.assertIn('end_date', data)
    
    def test_api_content_type_filter(self):
        """Test API with content type filter"""
        self.client.login(username='admin', password='testpass123')
        response = self.client.get('/en/dashboard/analytics/api/?content_type=pdf')
        
        self.assertEqual(response.status_code, 200)
        data = response.json()
        
        # All returned data should be for PDF content
        for item in data['data']:
            self.assertEqual(item['content_type'], 'pdf')
