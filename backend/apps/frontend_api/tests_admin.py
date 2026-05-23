"""
Tests for Admin Service, Admin views, and Gemini services.
Moved from apps/health/tests.py (was misplaced there).
"""
import json
import time
from types import SimpleNamespace
from unittest.mock import Mock, patch, MagicMock
from django.test import TestCase, RequestFactory
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.urls import resolve, Resolver404
from apps.media_manager.models import APIUploadQueue, ContentItem, ProcessingJob


User = get_user_model()


class R2StorageAPIEndpointTestCase(TestCase):
    """Test R2 Storage Usage API endpoint"""

    def setUp(self):
        """Set up test data"""
        self.factory = RequestFactory()
        self.user = User.objects.create_user(
            username='testuser',
            email='testuser@example.com',
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

        mock_service = MagicMock()
        mock_service.get_bucket_usage.return_value = {
            'success': True,
            'total_size_bytes': 1073741824,
            'total_size_gb': 1.0,
            'object_count': 10,
            'last_updated': '2026-02-03T22:00:00Z'
        }
        mock_get_service.return_value = mock_service

        request = self.factory.get('/api/admin/r2-storage-usage/')
        request.user = self.user

        response = get_r2_storage_usage(request)

        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content)
        self.assertTrue(data['success'])
        self.assertEqual(data['total_size_gb'], 1.0)
        self.assertEqual(data['object_count'], 10)

    @patch('apps.frontend_api.admin_views.get_r2_storage_service')
    def test_r2_storage_endpoint_non_staff(self, mock_get_service):
        """Test R2 storage endpoint denies non-staff users"""
        from apps.frontend_api.admin_views import get_r2_storage_usage

        non_staff_user = User.objects.create_user(
            username='regularuser',
            email='regularuser@example.com',
            password='testpass',
            is_staff=False
        )

        request = self.factory.get('/api/admin/r2-storage-usage/')
        request.user = non_staff_user

        response = get_r2_storage_usage(request)

        # staff_member_required redirects non-staff users to the admin login page.
        self.assertEqual(response.status_code, 302)


class SystemMonitorTestCase(TestCase):
    """Test System Monitor functionality"""

    def setUp(self):
        """Set up test data"""
        from apps.frontend_api.admin_services import AdminService
        self.admin_service = AdminService()

    def test_disk_usage_calculation(self):
        """Test disk usage calculation returns valid data"""
        disk_usage = self.admin_service._get_disk_usage()

        self.assertIn('total', disk_usage)
        self.assertIn('used', disk_usage)
        self.assertIn('free', disk_usage)
        self.assertIn('percentage', disk_usage)

        self.assertIsInstance(disk_usage['total'], int)
        self.assertIsInstance(disk_usage['used'], int)
        self.assertIsInstance(disk_usage['free'], int)
        self.assertIsInstance(disk_usage['percentage'], int)

        self.assertGreaterEqual(disk_usage['percentage'], 0)
        self.assertLessEqual(disk_usage['percentage'], 100)

    def test_storage_breakdown_structure(self):
        """Test storage breakdown returns correct structure"""
        breakdown = self.admin_service._get_storage_breakdown()

        self.assertIn('original', breakdown)
        self.assertIn('hls', breakdown)
        self.assertIn('compressed', breakdown)

        for category in ['original', 'hls', 'compressed']:
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

        self.assertIn('total', stats)
        self.assertIn('storage', stats)

    @patch('core.services.r2_storage_service.get_r2_storage_service')
    @patch('apps.frontend_api.admin_services.settings')
    def test_r2_stats_enabled(self, mock_settings, mock_r2_service):
        """Test R2 stats when R2 is enabled"""
        mock_settings.R2_ENABLED = True

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

        self.assertIn('total', stats)
        self.assertIn('storage', stats)
        self.assertTrue(stats['storage']['success'])
        self.assertEqual(stats['storage']['total_size_gb'], 1.0)
        self.assertEqual(stats['storage']['object_count'], 100)

    def test_system_monitor_data_complete(self):
        """Test get_system_monitor_data returns all required data"""
        data = self.admin_service.get_system_monitor_data()

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

        self.assertIn('active_tasks', data['task_monitor'])
        self.assertIn('task_stats', data['task_monitor'])
        self.assertIn('has_tasks', data['task_monitor'])


class JobsDashboardEndpointsTestCase(TestCase):
    """Regression tests for admin jobs API endpoints."""

    def setUp(self):
        self.staff_user = User.objects.create_user(
            username='jobs_staff',
            email='jobs_staff@example.com',
            password='testpass123',
            is_staff=True,
        )
        self.non_staff_user = User.objects.create_user(
            username='jobs_regular',
            email='jobs_regular@example.com',
            password='testpass123',
            is_staff=False,
        )

        self.content_item = ContentItem.objects.create(
            title_ar='محتوى الوظائف',
            title_en='Jobs Content',
            description_ar='وصف',
            description_en='Description',
            content_type='video',
            is_active=True,
        )
        ProcessingJob.objects.create(
            content_item=self.content_item,
            status='pending',
            current_stage='file_processing',
        )
        APIUploadQueue.objects.create(
            file_name='queue_video.mp4',
            file_path='tmp/queue_video.mp4',
            content_type='video',
            file_size_mb=12.0,
            status='pending',
            queue_status='waiting',
        )

    def test_api_jobs_list_htmx_returns_partial(self):
        self.client.force_login(self.staff_user)
        response = self.client.get('/en/dashboard/jobs/api/list/', HTTP_HX_REQUEST='true')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Job Queue')

    def test_api_jobs_list_non_htmx_redirects_dashboard(self):
        self.client.force_login(self.staff_user)
        response = self.client.get('/en/dashboard/jobs/api/list/?status=pending&type=all')
        self.assertEqual(response.status_code, 302)
        self.assertIn('/dashboard/jobs/', response.url)

    def test_api_jobs_stats_returns_expected_keys(self):
        self.client.force_login(self.staff_user)
        response = self.client.get('/en/dashboard/jobs/api/stats/')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        for key in ['active', 'pending', 'canceled', 'completed', 'failed']:
            self.assertIn(key, data)

    def test_api_jobs_list_non_staff_redirected(self):
        self.client.force_login(self.non_staff_user)
        response = self.client.get('/en/dashboard/jobs/api/list/', HTTP_HX_REQUEST='true')
        self.assertEqual(response.status_code, 302)


class JobsTransitionGuardTestCase(TestCase):
    """Phase 3 transition guard tests for jobs dashboard action APIs."""

    def setUp(self):
        self.factory = RequestFactory()
        self.staff_user = User.objects.create_user(
            username='phase3_staff',
            email='phase3_staff@example.com',
            password='testpass123',
            is_staff=True,
        )
        self.content_item = ContentItem.objects.create(
            title_ar='وظيفة انتقال',
            title_en='Transition Job',
            description_ar='وصف',
            description_en='Description',
            content_type='video',
            is_active=True,
        )

    @patch('apps.frontend_api.admin_views.dispatch_processing_task')
    def test_promote_failed_processing_job_retries_then_processes(self, mock_dispatch):
        from apps.frontend_api.admin_views import api_job_promote

        mock_dispatch.return_value = SimpleNamespace(id='task-123')
        job = ProcessingJob.objects.create(
            content_item=self.content_item,
            status='failed',
            current_stage='file_processing',
            failure_stage='file_processing',
            retry_count=0,
        )

        request = self.factory.post(
            '/ar/dashboard/jobs/api/promote/',
            data=json.dumps({'job_id': str(job.id), 'source': 'processing_job'}),
            content_type='application/json',
        )
        request.user = self.staff_user
        response = api_job_promote(request)

        self.assertEqual(response.status_code, 200)
        job.refresh_from_db()
        self.assertEqual(job.status, 'processing')
        self.assertEqual(job.retry_count, 1)
        self.assertEqual(job.celery_task_id, 'task-123')
        self.assertEqual(job.last_action_source, 'admin:jobs_api')

    def test_cancel_processing_job_rejects_processing_status(self):
        from apps.frontend_api.admin_views import api_job_cancel

        job = ProcessingJob.objects.create(
            content_item=self.content_item,
            status='processing',
            current_stage='file_processing',
        )

        request = self.factory.post(
            '/ar/dashboard/jobs/api/cancel/',
            data=json.dumps({'job_id': str(job.id), 'source': 'processing_job'}),
            content_type='application/json',
        )
        request.user = self.staff_user
        response = api_job_cancel(request)

        self.assertEqual(response.status_code, 400)
        job.refresh_from_db()
        self.assertEqual(job.status, 'processing')

    def test_cancel_api_queue_rejects_completed_status(self):
        from apps.frontend_api.admin_views import api_job_cancel

        queue_item = APIUploadQueue.objects.create(
            file_name='completed_queue.mp4',
            file_path='tmp/completed_queue.mp4',
            content_type='video',
            file_size_mb=10.0,
            status='completed',
            queue_status='ready',
        )

        request = self.factory.post(
            '/ar/dashboard/jobs/api/cancel/',
            data=json.dumps({'job_id': str(queue_item.id), 'source': 'api_queue'}),
            content_type='application/json',
        )
        request.user = self.staff_user
        response = api_job_cancel(request)

        self.assertEqual(response.status_code, 400)
        queue_item.refresh_from_db()
        self.assertEqual(queue_item.status, 'completed')


class JobsDispatchPipelineTestCase(TestCase):
    """Phase 3 dispatch and aggregation behavior tests."""

    def setUp(self):
        self.content_item = ContentItem.objects.create(
            title_ar='وظيفة خطوط الانابيب',
            title_en='Pipeline Job',
            description_ar='وصف',
            description_en='Description',
            content_type='video',
            is_active=True,
        )

    @patch('apps.frontend_api.utils.jobs_dashboard.dispatch_processing_task')
    def test_dispatch_content_item_blocks_duplicate_processing_job(self, mock_dispatch):
        from apps.frontend_api.utils.jobs_dashboard import dispatch_content_item_for_stage

        ProcessingJob.objects.create(
            content_item=self.content_item,
            status='processing',
            current_stage='file_processing',
            celery_task_id='existing-task-id',
        )

        task_id = dispatch_content_item_for_stage(self.content_item, stage='file_processing')

        self.assertEqual(task_id, '')
        mock_dispatch.assert_not_called()

    @patch('apps.frontend_api.utils.jobs_dashboard.dispatch_processing_task')
    def test_dispatch_content_item_persists_action_source(self, mock_dispatch):
        from apps.frontend_api.utils.jobs_dashboard import dispatch_content_item_for_stage

        mock_dispatch.return_value = SimpleNamespace(id='task-xyz')

        task_id = dispatch_content_item_for_stage(
            self.content_item,
            stage='file_processing',
            action_source='admin:jobs_api',
        )

        self.assertEqual(task_id, 'task-xyz')
        job = ProcessingJob.objects.get(content_item=self.content_item)
        self.assertEqual(job.last_action_source, 'admin:jobs_api')

    @patch('apps.media_manager.services.api_upload_queue_service.APIUploadQueueService.can_process_type')
    def test_api_queue_promote_persists_action_source(self, mock_can_process_type):
        from apps.media_manager.services.api_upload_queue_service import APIUploadQueueService

        mock_can_process_type.return_value = False
        queue_item = APIUploadQueue.objects.create(
            file_name='source_queue.mp4',
            file_path='tmp/source_queue.mp4',
            content_type='video',
            file_size_mb=5.0,
            status='pending',
            queue_status='waiting',
        )

        APIUploadQueueService.promote_item(str(queue_item.id), action_source='admin:jobs_api')

        queue_item.refresh_from_db()
        self.assertEqual(queue_item.last_action_source, 'admin:jobs_api')

    def test_get_jobs_counts_uses_canonical_api_queue_statuses(self):
        from apps.frontend_api.utils.jobs_dashboard import get_jobs_counts

        ContentItem.objects.create(
            title_ar='وظيفة مكتملة',
            title_en='Completed Job',
            description_ar='وصف',
            description_en='Description',
            content_type='audio',
            is_active=True,
        )

        APIUploadQueue.objects.create(
            file_name='queued_item.mp4',
            file_path='tmp/queued_item.mp4',
            content_type='video',
            file_size_mb=5.0,
            status='queued',
            queue_status='ready',
        )
        APIUploadQueue.objects.create(
            file_name='cancelled_item.mp4',
            file_path='tmp/cancelled_item.mp4',
            content_type='video',
            file_size_mb=5.0,
            status='cancelled',
            queue_status='ready',
        )

        counts = get_jobs_counts()

        self.assertGreaterEqual(counts['pending'], 1)
        self.assertGreaterEqual(counts['canceled'], 1)


class RemovedStandaloneDashboardRoutesTestCase(TestCase):
    """Phase 2 hard-removal tests for deprecated standalone dashboard pages."""

    def setUp(self):
        self.staff_user = User.objects.create_user(
            username='phase2_staff',
            email='phase2_staff@example.com',
            password='testpass123',
            is_staff=True,
        )
        self.queue_item = APIUploadQueue.objects.create(
            file_name='phase2_queue_video.mp4',
            file_path='tmp/phase2_queue_video.mp4',
            content_type='video',
            file_size_mb=8.0,
            status='pending',
            queue_status='waiting',
        )

    def test_removed_routes_do_not_resolve_and_fail_fast(self):
        removed_urls = [
            '/ar/dashboard/api-queue/',
            f'/ar/dashboard/api-queue/{self.queue_item.id}/',
            '/ar/dashboard/r2/',
            '/ar/dashboard/seo/',
        ]

        for url in removed_urls:
            start = time.monotonic()
            with self.assertRaises(Resolver404, msg=f'Expected unresolved route for {url}'):
                resolve(url)
            elapsed = time.monotonic() - start
            self.assertLess(
                elapsed,
                1.0,
                msg=f'URL resolution took too long for removed route {url}: {elapsed:.3f}s',
            )


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

        self.assertIn('en', cleaned)
        self.assertIn('ar', cleaned)

        self.assertIn('title', cleaned['en'])
        self.assertIn('description', cleaned['en'])
        self.assertEqual(cleaned['en']['title'], 'Test Video Title')

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

        self.assertEqual(len(cleaned['en']['title']), 100)
        self.assertEqual(len(cleaned['en']['description']), 200)
        self.assertEqual(len(cleaned['ar']['title']), 100)
        self.assertEqual(len(cleaned['ar']['description']), 200)

    def test_metadata_prompt_contains_coptic_context(self):
        """Test that metadata prompt includes Coptic Orthodox context"""
        prompt = self.service._create_metadata_prompt('video')

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

        self.assertIn('en', cleaned)
        self.assertIn('ar', cleaned)

        self.assertIn('meta_title', cleaned['en'])
        self.assertIn('description', cleaned['en'])
        self.assertIn('keywords', cleaned['en'])
        self.assertIsInstance(cleaned['en']['keywords'], list)

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

        self.assertLessEqual(len(cleaned['en']['meta_title']), 60)
        self.assertLessEqual(len(cleaned['en']['description']), 160)
        self.assertLessEqual(len(cleaned['ar']['meta_title']), 60)
        self.assertLessEqual(len(cleaned['ar']['description']), 160)


class GeminiBaseServiceTest(TestCase):
    """Test shared Gemini file handling"""

    def setUp(self):
        from core.services.gemini_seo_service import GeminiSEOService

        self.service = GeminiSEOService()
        self.service.client = SimpleNamespace(files=SimpleNamespace(get=Mock()))

    @patch('core.services.gemini_base_service.time.sleep', return_value=None)
    @patch('core.services.gemini_base_service.time.monotonic', return_value=0)
    def test_wait_for_file_active_polls_until_active(self, mock_monotonic, mock_sleep):
        """Test that Gemini files are polled until ACTIVE before use"""
        processing_file = SimpleNamespace(
            name='files/test-123',
            state=SimpleNamespace(value='PROCESSING'),
        )
        active_file = SimpleNamespace(
            name='files/test-123',
            state=SimpleNamespace(value='ACTIVE'),
        )
        self.service.client.files.get = Mock(side_effect=[active_file])

        result = self.service._wait_for_file_active(
            processing_file,
            timeout_seconds=10,
            poll_interval_seconds=1,
        )

        self.assertIs(result, active_file)
        self.service.client.files.get.assert_called_once_with(name='files/test-123')
        mock_sleep.assert_called_once_with(1)

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

        self.assertLessEqual(len(cleaned['en']['keywords']), 12)
        self.assertLessEqual(len(cleaned['ar']['keywords']), 12)

    def test_seo_prompt_contains_google_optimization(self):
        """Test that SEO prompt includes Google SEO requirements"""
        prompt = self.service._create_seo_prompt('video')

        self.assertIn('50-60', prompt)
        self.assertIn('150-160', prompt)
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
        self.factory = RequestFactory()
        self.user = User.objects.create_user(
            username='testuser',
            email='metadata@example.com',
            password='testpass123',
            is_staff=True
        )

    def test_endpoint_requires_post(self):
        """Test that endpoint requires POST method"""
        from apps.frontend_api.admin_views import generate_metadata_only

        request = self.factory.get('/api/admin/generate-metadata-only/')
        request.user = self.user
        response = generate_metadata_only(request)
        self.assertEqual(response.status_code, 405)

    def test_endpoint_requires_file(self):
        """Test that endpoint requires file parameter"""
        from apps.frontend_api.admin_views import generate_metadata_only

        request = self.factory.post('/api/admin/generate-metadata-only/', {})
        request.user = self.user
        request._dont_enforce_csrf_checks = True
        response = generate_metadata_only(request)
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content)
        self.assertFalse(data['success'])
        self.assertTrue(
            ('File required' in data['error']) or ('الملف مطلوب' in data['error'])
        )


class SEOEndpointTest(TestCase):
    """Test SEO generation endpoint"""

    def setUp(self):
        """Set up test fixtures"""
        self.factory = RequestFactory()
        self.user = User.objects.create_user(
            username='testuser',
            email='seo@example.com',
            password='testpass123',
            is_staff=True
        )

    def test_endpoint_requires_post(self):
        """Test that endpoint requires POST method"""
        from apps.frontend_api.admin_views import generate_seo_only

        request = self.factory.get('/api/admin/generate-seo-only/')
        request.user = self.user
        response = generate_seo_only(request)
        self.assertEqual(response.status_code, 405)

    def test_endpoint_requires_file(self):
        """Test that endpoint requires file parameter"""
        from apps.frontend_api.admin_views import generate_seo_only

        request = self.factory.post('/api/admin/generate-seo-only/', {})
        request.user = self.user
        request._dont_enforce_csrf_checks = True
        response = generate_seo_only(request)
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content)
        self.assertFalse(data['success'])
        self.assertTrue(
            ('File required' in data['error']) or ('الملف مطلوب' in data['error'])
        )