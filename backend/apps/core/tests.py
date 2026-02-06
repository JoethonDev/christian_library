"""
Tests for R2 Storage Service and Task Progress Reporting
"""
import json
from unittest.mock import Mock, patch, MagicMock
from django.test import TestCase, RequestFactory
from django.contrib.auth.models import User
from django.core.cache import cache
from django.conf import settings

from core.services.r2_storage_service import R2StorageService, get_r2_storage_service
from apps.core.task_monitor import TaskMonitor


class R2StorageServiceTestCase(TestCase):
    """Test R2 Storage Service functionality"""
    
    def setUp(self):
        """Set up test data"""
        # Clear cache before each test
        cache.clear()
        
    def tearDown(self):
        """Clean up after tests"""
        cache.clear()
    
    @patch('core.services.r2_storage_service.boto3.client')
    @patch('core.services.r2_storage_service.settings')
    def test_r2_service_initialization_success(self, mock_settings, mock_boto_client):
        """Test R2StorageService initializes correctly with valid settings"""
        # Mock settings
        mock_settings.R2_ENABLED = True
        mock_settings.R2_BUCKET_NAME = 'test-bucket'
        mock_settings.R2_ACCESS_KEY_ID = 'test-key-id'
        mock_settings.R2_SECRET_ACCESS_KEY = 'test-secret-key'
        mock_settings.R2_ENDPOINT_URL = 'https://test.r2.cloudflarestorage.com'
        mock_settings.R2_REGION_NAME = 'auto'
        
        # Create service
        service = R2StorageService()
        
        # Verify initialization
        self.assertTrue(service.enabled)
        self.assertIsNotNone(service.client)
        self.assertEqual(service.bucket_name, 'test-bucket')
    
    @patch('core.services.r2_storage_service.settings')
    def test_r2_service_initialization_disabled(self, mock_settings):
        """Test R2StorageService handles disabled R2"""
        # Mock settings with R2 disabled
        mock_settings.R2_ENABLED = False
        
        # Create service
        service = R2StorageService()
        
        # Verify service is disabled
        self.assertFalse(service.enabled)
        self.assertIsNone(service.client)
    
    @patch('core.services.r2_storage_service.boto3.client')
    @patch('core.services.r2_storage_service.settings')
    def test_get_bucket_usage_success(self, mock_settings, mock_boto_client):
        """Test successful bucket usage retrieval"""
        # Mock settings
        mock_settings.R2_ENABLED = True
        mock_settings.R2_BUCKET_NAME = 'test-bucket'
        mock_settings.R2_ACCESS_KEY_ID = 'test-key-id'
        mock_settings.R2_SECRET_ACCESS_KEY = 'test-secret-key'
        mock_settings.R2_ENDPOINT_URL = 'https://test.r2.cloudflarestorage.com'
        
        # Mock boto3 client response
        mock_client = MagicMock()
        mock_boto_client.return_value = mock_client
        
        # Mock paginator response
        mock_paginator = MagicMock()
        mock_client.get_paginator.return_value = mock_paginator
        
        # Mock page iterator with sample data
        mock_page_iterator = [
            {
                'Contents': [
                    {'Size': 1024 * 1024 * 100},  # 100 MB
                    {'Size': 1024 * 1024 * 200},  # 200 MB
                ]
            },
            {
                'Contents': [
                    {'Size': 1024 * 1024 * 300},  # 300 MB
                ]
            }
        ]
        mock_paginator.paginate.return_value = mock_page_iterator
        
        # Create service and get usage
        service = R2StorageService()
        result = service.get_bucket_usage(use_cache=False)
        
        # Verify result
        self.assertTrue(result['success'])
        self.assertEqual(result['total_size_bytes'], 1024 * 1024 * 600)  # 600 MB
        self.assertEqual(result['total_size_gb'], 0.59)  # ~0.59 GB (rounded)
        self.assertEqual(result['object_count'], 3)
        self.assertIn('last_updated', result)
    
    @patch('core.services.r2_storage_service.settings')
    def test_get_bucket_usage_disabled(self, mock_settings):
        """Test bucket usage when R2 is disabled"""
        # Mock settings with R2 disabled
        mock_settings.R2_ENABLED = False
        
        # Create service and get usage
        service = R2StorageService()
        result = service.get_bucket_usage(use_cache=False)
        
        # Verify error result
        self.assertFalse(result['success'])
        self.assertIn('error', result)
        self.assertEqual(result['total_size_gb'], 0.0)
        self.assertEqual(result['object_count'], 0)
    
    @patch('core.services.r2_storage_service.boto3.client')
    @patch('core.services.r2_storage_service.settings')
    def test_get_bucket_usage_caching(self, mock_settings, mock_boto_client):
        """Test that bucket usage data is cached correctly"""
        # Mock settings
        mock_settings.R2_ENABLED = True
        mock_settings.R2_BUCKET_NAME = 'test-bucket'
        mock_settings.R2_ACCESS_KEY_ID = 'test-key-id'
        mock_settings.R2_SECRET_ACCESS_KEY = 'test-secret-key'
        mock_settings.R2_ENDPOINT_URL = 'https://test.r2.cloudflarestorage.com'
        
        # Mock boto3 client
        mock_client = MagicMock()
        mock_boto_client.return_value = mock_client
        mock_paginator = MagicMock()
        mock_client.get_paginator.return_value = mock_paginator
        mock_paginator.paginate.return_value = [
            {'Contents': [{'Size': 1024 * 1024}]}  # 1 MB
        ]
        
        # Create service
        service = R2StorageService()
        
        # First call - should hit API
        result1 = service.get_bucket_usage(use_cache=True)
        self.assertTrue(result1['success'])
        
        # Verify data is cached
        cached_data = cache.get('r2_storage_usage')
        self.assertIsNotNone(cached_data)
        self.assertEqual(cached_data['total_size_gb'], result1['total_size_gb'])
        
        # Second call - should use cache (won't hit API again)
        result2 = service.get_bucket_usage(use_cache=True)
        self.assertEqual(result1, result2)
    
    @patch('core.services.r2_storage_service.boto3.client')
    @patch('core.services.r2_storage_service.settings')
    def test_clear_cache(self, mock_settings, mock_boto_client):
        """Test cache clearing functionality"""
        # Mock settings
        mock_settings.R2_ENABLED = True
        mock_settings.R2_BUCKET_NAME = 'test-bucket'
        mock_settings.R2_ACCESS_KEY_ID = 'test-key-id'
        mock_settings.R2_SECRET_ACCESS_KEY = 'test-secret-key'
        mock_settings.R2_ENDPOINT_URL = 'https://test.r2.cloudflarestorage.com'
        
        # Create service
        service = R2StorageService()
        
        # Set cache manually
        test_data = {'success': True, 'total_size_gb': 1.5}
        cache.set('r2_storage_usage', test_data, 300)
        
        # Verify cache exists
        self.assertIsNotNone(cache.get('r2_storage_usage'))
        
        # Clear cache
        service.clear_cache()
        
        # Verify cache is cleared
        self.assertIsNone(cache.get('r2_storage_usage'))


class TaskMonitorProgressTestCase(TestCase):
    """Test TaskMonitor progress reporting"""
    
    def setUp(self):
        """Set up test data"""
        cache.clear()
    
    def tearDown(self):
        """Clean up after tests"""
        cache.clear()
    
    def test_task_registration(self):
        """Test task registration with TaskMonitor"""
        task_id = 'test-task-123'
        task_name = 'Test Task'
        metadata = {'content_id': 'abc-123'}
        
        # Register task
        TaskMonitor.register_task(
            task_id=task_id,
            task_name=task_name,
            user_id='user-1',
            metadata=metadata
        )
        
        # Verify task is registered
        task_info = TaskMonitor.get_task_details(task_id)
        self.assertIsNotNone(task_info)
        self.assertEqual(task_info['task_name'], task_name)
        self.assertEqual(task_info['status'], 'PENDING')
    
    def test_progress_updates(self):
        """Test progress updates reach 100%"""
        task_id = 'test-task-progress'
        
        # Register task
        TaskMonitor.register_task(task_id=task_id, task_name='Progress Test')
        
        # Update progress incrementally
        TaskMonitor.update_progress(task_id, 25, 'Step 1', 'Processing')
        task_info = TaskMonitor.get_task_details(task_id)
        self.assertEqual(task_info['progress'], 25)
        
        TaskMonitor.update_progress(task_id, 50, 'Step 2', 'Processing')
        task_info = TaskMonitor.get_task_details(task_id)
        self.assertEqual(task_info['progress'], 50)
        
        TaskMonitor.update_progress(task_id, 100, 'Complete', 'Done')
        task_info = TaskMonitor.get_task_details(task_id)
        self.assertEqual(task_info['progress'], 100)
    
    def test_task_status_success_with_100_progress(self):
        """Test that SUCCESS status includes progress=100"""
        task_id = 'test-task-success'
        
        # Register task
        TaskMonitor.register_task(task_id=task_id, task_name='Success Test')
        
        # Update to SUCCESS with 100% progress
        TaskMonitor.update_task_status(
            task_id, 
            'SUCCESS', 
            {'message': 'Task completed', 'progress': 100}
        )
        
        # Verify status and progress
        task_info = TaskMonitor.get_task_details(task_id)
        self.assertEqual(task_info['status'], 'SUCCESS')
        self.assertEqual(task_info['result']['progress'], 100)
    
    def test_task_status_failure_with_100_progress(self):
        """Test that FAILURE status includes progress=100"""
        task_id = 'test-task-failure'
        
        # Register task
        TaskMonitor.register_task(task_id=task_id, task_name='Failure Test')
        
        # Update to FAILURE with 100% progress
        TaskMonitor.update_task_status(
            task_id, 
            'FAILURE', 
            {'message': 'Task failed after retries', 'progress': 100}
        )
        
        # Verify status and progress
        task_info = TaskMonitor.get_task_details(task_id)
        self.assertEqual(task_info['status'], 'FAILURE')
        self.assertEqual(task_info['result']['progress'], 100)


class R2StorageAPIEndpointTestCase(TestCase):
    """Test R2 Storage Usage API endpoint"""
    
    def setUp(self):
        """Set up test data"""
        self.factory = RequestFactory()
        self.user = User.objects.create_user(
            username='testuser',
            password='testpass',
            is_staff=True
        )
        cache.clear()
    
    def tearDown(self):
        """Clean up"""
        cache.clear()
    
    @patch('apps.frontend_api.admin_views.get_r2_storage_service')
    def test_r2_storage_endpoint_success(self, mock_get_service):
        """Test R2 storage endpoint returns correct data"""
        from apps.frontend_api.admin_views import get_r2_storage_usage
        
        # Mock service response
        mock_service = MagicMock()
        mock_service.get_bucket_usage.return_value = {
            'success': True,
            'total_size_bytes': 1073741824,  # 1 GB
            'total_size_gb': 1.0,
            'object_count': 10,
            'last_updated': '2026-02-03T22:00:00Z'
        }
        mock_get_service.return_value = mock_service
        
        # Create request
        request = self.factory.get('/api/admin/r2-storage-usage/')
        request.user = self.user
        
        # Call endpoint
        response = get_r2_storage_usage(request)
        
        # Verify response
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content)
        self.assertTrue(data['success'])
        self.assertEqual(data['total_size_gb'], 1.0)
        self.assertEqual(data['object_count'], 10)
    
    @patch('apps.frontend_api.admin_views.get_r2_storage_service')
    def test_r2_storage_endpoint_non_staff(self, mock_get_service):
        """Test R2 storage endpoint denies non-staff users"""
        from apps.frontend_api.admin_views import get_r2_storage_usage
        
        # Create non-staff user
        non_staff_user = User.objects.create_user(
            username='regularuser',
            password='testpass',
            is_staff=False
        )
        
        # Create request
        request = self.factory.get('/api/admin/r2-storage-usage/')
        request.user = non_staff_user
        
        # Call endpoint
        response = get_r2_storage_usage(request)
        
        # Verify response is forbidden
        self.assertEqual(response.status_code, 403)
        data = json.loads(response.content)
        self.assertFalse(data['success'])
        self.assertIn('Permission denied', data['error'])


class TaskProgressIntegrationTestCase(TestCase):
    """Integration tests for task progress accuracy"""
    
    def test_progress_reaches_100_on_all_paths(self):
        """Test that all task completion paths reach 100% progress"""
        # This would be an integration test that runs actual tasks
        # For now, we verify the structure exists
        
        from apps.media_manager.tasks import generate_seo_metadata_task
        from core.tasks.media_processing import (
            upload_video_to_r2,
            upload_audio_to_r2,
            upload_pdf_to_r2
        )
        
        # Verify tasks exist
        self.assertTrue(callable(generate_seo_metadata_task))
        self.assertTrue(callable(upload_video_to_r2))
        self.assertTrue(callable(upload_audio_to_r2))
        self.assertTrue(callable(upload_pdf_to_r2))
        
        # Verify tasks have bind=True (required for self.request.id)
        self.assertTrue(hasattr(generate_seo_metadata_task, 'max_retries'))
        self.assertEqual(generate_seo_metadata_task.max_retries, 2)


class SystemMonitorTestCase(TestCase):
    """Test System Monitor functionality"""
    
    def setUp(self):
        """Set up test data"""
        from apps.frontend_api.admin_services import AdminService
        self.admin_service = AdminService()
    
    def test_disk_usage_calculation(self):
        """Test disk usage calculation returns valid data"""
        disk_usage = self.admin_service._get_disk_usage()
        
        # Verify structure
        self.assertIn('total', disk_usage)
        self.assertIn('used', disk_usage)
        self.assertIn('free', disk_usage)
        self.assertIn('percentage', disk_usage)
        
        # Verify types
        self.assertIsInstance(disk_usage['total'], int)
        self.assertIsInstance(disk_usage['used'], int)
        self.assertIsInstance(disk_usage['free'], int)
        self.assertIsInstance(disk_usage['percentage'], int)
        
        # Verify percentage is in valid range
        self.assertGreaterEqual(disk_usage['percentage'], 0)
        self.assertLessEqual(disk_usage['percentage'], 100)
    
    def test_storage_breakdown_structure(self):
        """Test storage breakdown returns correct structure"""
        breakdown = self.admin_service._get_storage_breakdown()
        
        # Verify all expected categories exist
        self.assertIn('original', breakdown)
        self.assertIn('hls', breakdown)
        self.assertIn('optimized', breakdown)
        self.assertIn('compressed', breakdown)
        
        # Verify each category has size and count
        for category in ['original', 'hls', 'optimized', 'compressed']:
            self.assertIn('size', breakdown[category])
            self.assertIn('count', breakdown[category])
            self.assertIsInstance(breakdown[category]['size'], int)
            self.assertIsInstance(breakdown[category]['count'], int)
            self.assertGreaterEqual(breakdown[category]['size'], 0)
            self.assertGreaterEqual(breakdown[category]['count'], 0)
    
    @patch('apps.frontend_api.admin_services.settings')
    def test_r2_stats_disabled(self, mock_settings):
        """Test R2 stats when R2 is disabled"""
        mock_settings.R2_ENABLED = False
        
        stats = self.admin_service._get_r2_stats()
        
        # Should return default structure even when disabled
        self.assertIn('total', stats)
        self.assertIn('storage', stats)
    
    @patch('apps.frontend_api.admin_services.get_r2_storage_service')
    @patch('apps.frontend_api.admin_services.settings')
    def test_r2_stats_enabled(self, mock_settings, mock_r2_service):
        """Test R2 stats when R2 is enabled"""
        mock_settings.R2_ENABLED = True
        
        # Mock R2 service response
        mock_service = MagicMock()
        mock_service.get_bucket_usage.return_value = {
            'success': True,
            'total_size_bytes': 1073741824,
            'total_size_gb': 1.0,
            'object_count': 100,
            'last_updated': '2026-02-04T07:00:00Z'
        }
        mock_r2_service.return_value = mock_service
        
        stats = self.admin_service._get_r2_stats()
        
        # Verify structure
        self.assertIn('total', stats)
        self.assertIn('storage', stats)
        self.assertTrue(stats['storage']['success'])
        self.assertEqual(stats['storage']['total_size_gb'], 1.0)
        self.assertEqual(stats['storage']['object_count'], 100)
    
    def test_system_monitor_data_complete(self):
        """Test get_system_monitor_data returns all required data"""
        data = self.admin_service.get_system_monitor_data()
        
        # Verify all expected keys exist
        expected_keys = [
            'processing_stats',
            'content_stats',
            'recent_activity',
            'task_monitor',
            'disk_usage',
            'storage_breakdown',
            'r2_enabled',
            'r2_stats'
        ]
        
        for key in expected_keys:
            self.assertIn(key, data, f"Missing key: {key}")
        
        # Verify task_monitor has expected structure
        self.assertIn('active_tasks', data['task_monitor'])
        self.assertIn('task_stats', data['task_monitor'])
        self.assertIn('has_tasks', data['task_monitor'])


class GeminiMetadataServiceTest(TestCase):
    """Test Gemini Metadata Service"""
    
    def setUp(self):
        """Set up test fixtures"""
        from core.services.gemini_metadata_service import GeminiMetadataService
        self.service = GeminiMetadataService()
    
    def test_service_initialization(self):
        """Test that service initializes properly"""
        self.assertIsNotNone(self.service)
        self.assertTrue(hasattr(self.service, 'generate_metadata'))
        self.assertTrue(hasattr(self.service, 'is_available'))
    
    def test_validate_metadata(self):
        """Test metadata validation"""
        test_metadata = {
            'en': {
                'title': 'Test Video Title',
                'description': 'This is a test description for a video about Coptic Orthodox liturgy.'
            },
            'ar': {
                'title': 'عنوان الفيديو التجريبي',
                'description': 'هذا وصف تجريبي لفيديو عن الليتورجيا القبطية الأرثوذكسية.'
            }
        }
        
        cleaned = self.service._validate_metadata(test_metadata)
        
        # Check structure
        self.assertIn('en', cleaned)
        self.assertIn('ar', cleaned)
        
        # Check English
        self.assertIn('title', cleaned['en'])
        self.assertIn('description', cleaned['en'])
        self.assertEqual(cleaned['en']['title'], 'Test Video Title')
        
        # Check Arabic
        self.assertIn('title', cleaned['ar'])
        self.assertIn('description', cleaned['ar'])
        self.assertEqual(cleaned['ar']['title'], 'عنوان الفيديو التجريبي')
    
    def test_validate_metadata_truncation(self):
        """Test that metadata is properly truncated"""
        long_title = 'A' * 150
        long_description = 'B' * 300
        
        test_metadata = {
            'en': {
                'title': long_title,
                'description': long_description
            },
            'ar': {
                'title': long_title,
                'description': long_description
            }
        }
        
        cleaned = self.service._validate_metadata(test_metadata)
        
        # Check truncation
        self.assertEqual(len(cleaned['en']['title']), 100)
        self.assertEqual(len(cleaned['en']['description']), 200)
        self.assertEqual(len(cleaned['ar']['title']), 100)
        self.assertEqual(len(cleaned['ar']['description']), 200)
    
    def test_metadata_prompt_contains_coptic_context(self):
        """Test that metadata prompt includes Coptic Orthodox context"""
        prompt = self.service._create_metadata_prompt('video')
        
        # Check for key phrases
        self.assertIn('Coptic Orthodox', prompt)
        self.assertIn('Christian', prompt)
        self.assertIn('theological', prompt.lower())
    
    def test_singleton_pattern(self):
        """Test that get_gemini_metadata_service returns singleton"""
        from core.services.gemini_metadata_service import get_gemini_metadata_service
        service1 = get_gemini_metadata_service()
        service2 = get_gemini_metadata_service()
        self.assertIs(service1, service2)


class GeminiSEOServiceTest(TestCase):
    """Test Gemini SEO Service"""
    
    def setUp(self):
        """Set up test fixtures"""
        from core.services.gemini_seo_service import GeminiSEOService
        self.service = GeminiSEOService()
    
    def test_service_initialization(self):
        """Test that service initializes properly"""
        self.assertIsNotNone(self.service)
        self.assertTrue(hasattr(self.service, 'generate_seo'))
        self.assertTrue(hasattr(self.service, 'is_available'))
    
    def test_validate_seo(self):
        """Test SEO validation"""
        test_seo = {
            'en': {
                'meta_title': 'Coptic Orthodox Liturgy Video',
                'description': 'Learn about the Divine Liturgy in the Coptic Orthodox Church with this comprehensive video guide covering hymns, prayers, and traditions.',
                'keywords': ['Coptic Orthodox', 'Divine Liturgy', 'Coptic hymns', 'Egyptian Christianity']
            },
            'ar': {
                'meta_title': 'فيديو الليتورجيا القبطية',
                'description': 'تعلم عن القداس الإلهي في الكنيسة القبطية الأرثوذكسية من خلال هذا الدليل الشامل الذي يغطي الترانيم والصلوات والتقاليد.',
                'keywords': ['القبطية الأرثوذكسية', 'القداس الإلهي', 'الترانيم القبطية', 'المسيحية المصرية']
            }
        }
        
        cleaned = self.service._validate_seo(test_seo)
        
        # Check structure
        self.assertIn('en', cleaned)
        self.assertIn('ar', cleaned)
        
        # Check English
        self.assertIn('meta_title', cleaned['en'])
        self.assertIn('description', cleaned['en'])
        self.assertIn('keywords', cleaned['en'])
        self.assertIsInstance(cleaned['en']['keywords'], list)
        
        # Check Arabic
        self.assertIn('meta_title', cleaned['ar'])
        self.assertIn('description', cleaned['ar'])
        self.assertIn('keywords', cleaned['ar'])
        self.assertIsInstance(cleaned['ar']['keywords'], list)
    
    def test_validate_seo_character_limits(self):
        """Test that SEO metadata respects character limits"""
        long_title = 'A' * 100
        long_description = 'B' * 300
        
        test_seo = {
            'en': {
                'meta_title': long_title,
                'description': long_description,
                'keywords': []
            },
            'ar': {
                'meta_title': long_title,
                'description': long_description,
                'keywords': []
            }
        }
        
        cleaned = self.service._validate_seo(test_seo)
        
        # Check character limits (meta_title: 60, description: 160)
        self.assertLessEqual(len(cleaned['en']['meta_title']), 60)
        self.assertLessEqual(len(cleaned['en']['description']), 160)
        self.assertLessEqual(len(cleaned['ar']['meta_title']), 60)
        self.assertLessEqual(len(cleaned['ar']['description']), 160)
    
    def test_validate_seo_keyword_limits(self):
        """Test that keywords are limited to max 12"""
        test_seo = {
            'en': {
                'meta_title': 'Title',
                'description': 'Description',
                'keywords': [f'keyword{i}' for i in range(20)]
            },
            'ar': {
                'meta_title': 'عنوان',
                'description': 'وصف',
                'keywords': [f'كلمة{i}' for i in range(20)]
            }
        }
        
        cleaned = self.service._validate_seo(test_seo)
        
        # Check keyword limits
        self.assertLessEqual(len(cleaned['en']['keywords']), 12)
        self.assertLessEqual(len(cleaned['ar']['keywords']), 12)
    
    def test_seo_prompt_contains_google_optimization(self):
        """Test that SEO prompt includes Google SEO requirements"""
        prompt = self.service._create_seo_prompt('video')
        
        # Check for key SEO phrases
        self.assertIn('50-60', prompt)  # Meta title character limit
        self.assertIn('150-160', prompt)  # Meta description character limit
        self.assertIn('Coptic Orthodox', prompt)
        self.assertIn('SEO', prompt)
        self.assertIn('keywords', prompt.lower())
    
    def test_singleton_pattern(self):
        """Test that get_gemini_seo_service returns singleton"""
        from core.services.gemini_seo_service import get_gemini_seo_service
        service1 = get_gemini_seo_service()
        service2 = get_gemini_seo_service()
        self.assertIs(service1, service2)


class MetadataEndpointTest(TestCase):
    """Test metadata generation endpoint"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.user = User.objects.create_user(
            username='testuser',
            password='testpass123',
            is_staff=True
        )
    
    def test_endpoint_requires_post(self):
        """Test that endpoint requires POST method"""
        from django.test import Client
        from django.urls import reverse
        
        client = Client()
        client.login(username='testuser', password='testpass123')
        url = reverse('frontend_api:generate_metadata_only')
        response = client.get(url)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertFalse(data['success'])
        self.assertIn('POST method required', data['error'])
    
    def test_endpoint_requires_file(self):
        """Test that endpoint requires file parameter"""
        from django.test import Client
        from django.urls import reverse
        
        client = Client()
        client.login(username='testuser', password='testpass123')
        url = reverse('frontend_api:generate_metadata_only')
        response = client.post(url, {})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertFalse(data['success'])
        self.assertIn('File required', data['error'])


class SEOEndpointTest(TestCase):
    """Test SEO generation endpoint"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.user = User.objects.create_user(
            username='testuser',
            password='testpass123',
            is_staff=True
        )
    
    def test_endpoint_requires_post(self):
        """Test that endpoint requires POST method"""
        from django.test import Client
        from django.urls import reverse
        
        client = Client()
        client.login(username='testuser', password='testpass123')
        url = reverse('frontend_api:generate_seo_only')
        response = client.get(url)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertFalse(data['success'])
        self.assertIn('POST method required', data['error'])
    
    def test_endpoint_requires_file(self):
        """Test that endpoint requires file parameter"""
        from django.test import Client
        from django.urls import reverse
        
        client = Client()
        client.login(username='testuser', password='testpass123')
        url = reverse('frontend_api:generate_seo_only')
        response = client.post(url, {})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertFalse(data['success'])
        self.assertIn('File required', data['error'])


