"""
Comprehensive tests for multilingual full-text search functionality.
Tests cover Arabic, English, mixed-language search, tag filtering, and ranking.
"""

from django.test import TestCase, Client
from django.contrib.postgres.search import SearchQuery, SearchRank
from django.db import models

from apps.media_manager.models import ContentItem, Tag


class MultilingualSearchTest(TestCase):
    """Test multilingual full-text search functionality"""
    
    def setUp(self):
        """Create test data with various language combinations"""
        # Create tags for testing
        self.tag_arabic = Tag.objects.create(
            name_ar="لاهوت",
            name_en="Theology",
            description_ar="موضوعات لاهوتية",
            is_active=True
        )
        
        self.tag_english = Tag.objects.create(
            name_ar="تاريخ",
            name_en="History",
            description_ar="تاريخ الكنيسة",
            is_active=True
        )
        
        # Content item with Arabic only
        self.item_arabic = ContentItem.objects.create(
            title_ar="كتاب اللاهوت المسيحي",
            description_ar="دراسة شاملة في اللاهوت المسيحي الأرثوذكسي",
            content_type="pdf",
            book_content="محتوى الكتاب يتناول موضوعات لاهوتية عميقة في التقليد الأرثوذكسي",
            transcript="نص إضافي عن اللاهوت",
            notes="ملاحظات دراسية عن المحتوى",
            is_active=True
        )
        self.item_arabic.tags.add(self.tag_arabic)
        self.item_arabic.update_search_vector()
        self.item_arabic.save()
        
        # Content item with English only
        self.item_english = ContentItem.objects.create(
            title_en="Introduction to Christian Theology",
            description_en="A comprehensive study of Christian Orthodox theology",
            content_type="video",
            transcript="This video covers theological topics in the Orthodox tradition",
            notes="Study notes on the content",
            is_active=True
        )
        self.item_english.tags.add(self.tag_english)
        self.item_english.update_search_vector()
        self.item_english.save()
        
        # Content item with both languages
        self.item_bilingual = ContentItem.objects.create(
            title_ar="تاريخ الكنيسة القبطية",
            title_en="History of the Coptic Church",
            description_ar="تاريخ الكنيسة القبطية الأرثوذكسية عبر العصور",
            description_en="History of the Coptic Orthodox Church through the ages",
            content_type="audio",
            transcript="Historical account of the Coptic Church",
            notes="ملاحظات تاريخية مهمة",
            is_active=True
        )
        self.item_bilingual.tags.add(self.tag_arabic, self.tag_english)
        self.item_bilingual.update_search_vector()
        self.item_bilingual.save()
        
        # Content item with PDF content
        self.item_pdf_content = ContentItem.objects.create(
            title_ar="كتاب الصلوات",
            title_en="Prayer Book",
            description_ar="كتاب الصلوات اليومية",
            description_en="Daily prayer book",
            content_type="pdf",
            book_content="صلاة الصباح: يا رب ارحمنا. صلاة المساء: أيها المسيح إلهنا",
            is_active=True
        )
        self.item_pdf_content.update_search_vector()
        self.item_pdf_content.save()
    
    def test_arabic_title_search(self):
        """Test searching in Arabic title"""
        results = ContentItem.objects.search_optimized("اللاهوت")
        self.assertIn(self.item_arabic, results)
        self.assertGreater(results.count(), 0)
    
    def test_english_title_search(self):
        """Test searching in English title"""
        results = ContentItem.objects.search_optimized("Theology")
        self.assertIn(self.item_english, results)
        self.assertGreater(results.count(), 0)
    
    def test_arabic_description_search(self):
        """Test searching in Arabic description"""
        results = ContentItem.objects.search_optimized("أرثوذكسي")
        self.assertIn(self.item_arabic, results)
    
    def test_english_description_search(self):
        """Test searching in English description"""
        results = ContentItem.objects.search_optimized("Orthodox")
        self.assertIn(self.item_english, results)
    
    def test_transcript_search(self):
        """Test searching in transcript field"""
        results = ContentItem.objects.search_optimized("theological topics")
        self.assertIn(self.item_english, results)
    
    def test_notes_search(self):
        """Test searching in notes field"""
        results = ContentItem.objects.search_optimized("دراسية")
        self.assertIn(self.item_arabic, results)
    
    def test_book_content_search(self):
        """Test searching in PDF book_content field"""
        results = ContentItem.objects.search_optimized("صلاة الصباح")
        self.assertIn(self.item_pdf_content, results)
    
    def test_bilingual_content_arabic_search(self):
        """Test searching bilingual content in Arabic"""
        results = ContentItem.objects.search_optimized("القبطية")
        self.assertIn(self.item_bilingual, results)
    
    def test_bilingual_content_english_search(self):
        """Test searching bilingual content in English"""
        results = ContentItem.objects.search_optimized("Coptic")
        self.assertIn(self.item_bilingual, results)
    
    def test_content_type_filter(self):
        """Test filtering by content type"""
        # Search for theology in PDFs only
        results = ContentItem.objects.search_optimized("اللاهوت", content_type="pdf")
        self.assertIn(self.item_arabic, results)
        self.assertNotIn(self.item_english, results)  # Video should be excluded
        
        # Search in videos only
        results = ContentItem.objects.search_optimized("Theology", content_type="video")
        self.assertIn(self.item_english, results)
        self.assertNotIn(self.item_arabic, results)  # PDF should be excluded
    
    def test_empty_query_returns_all(self):
        """Test that empty query returns all active content"""
        # Get expected count dynamically to make test robust
        expected_count = ContentItem.objects.filter(is_active=True).count()
        
        results = ContentItem.objects.search_optimized("")
        self.assertEqual(results.count(), expected_count)
    
    def test_inactive_content_excluded(self):
        """Test that inactive content is not returned"""
        # Create inactive item
        inactive_item = ContentItem.objects.create(
            title_ar="محتوى غير نشط",
            description_ar="وصف",
            content_type="pdf",
            is_active=False
        )
        inactive_item.update_search_vector()
        inactive_item.save()
        
        results = ContentItem.objects.search_optimized("غير نشط")
        self.assertNotIn(inactive_item, results)
    
    def test_language_detection_arabic(self):
        """Test automatic language detection for Arabic queries"""
        results = ContentItem.objects.search_optimized("اللاهوت", language=None)
        self.assertGreater(results.count(), 0)
    
    def test_language_detection_english(self):
        """Test automatic language detection for English queries"""
        results = ContentItem.objects.search_optimized("Theology", language=None)
        self.assertGreater(results.count(), 0)
    
    def test_fts_ranking(self):
        """Test that results are ranked by relevance"""
        # Create item with query in title (should rank higher)
        high_rank_item = ContentItem.objects.create(
            title_ar="اللاهوت",  # Exact match in title
            description_ar="موضوع آخر",
            content_type="pdf",
            is_active=True
        )
        high_rank_item.update_search_vector()
        high_rank_item.save()
        
        results = list(ContentItem.objects.search_optimized("اللاهوت"))
        
        # Item with query in title should appear before items with query in description/content
        self.assertEqual(results[0], high_rank_item)


class TagSearchTest(TestCase):
    """Test tag search functionality"""
    
    def setUp(self):
        """Create test tags"""
        self.tag1 = Tag.objects.create(
            name_ar="لاهوت عقيدي",
            name_en="Dogmatic Theology",
            description_ar="دراسة العقائد المسيحية",
            is_active=True
        )
        
        self.tag2 = Tag.objects.create(
            name_ar="تاريخ كنسي",
            name_en="Church History",
            description_ar="تاريخ الكنيسة عبر العصور",
            is_active=True
        )
        
        self.tag_inactive = Tag.objects.create(
            name_ar="غير نشط",
            name_en="Inactive",
            is_active=False
        )
        
        # Create content to test content_count
        item = ContentItem.objects.create(
            title_ar="محتوى تجريبي",
            content_type="pdf",
            is_active=True
        )
        item.tags.add(self.tag1)
    
    def test_search_tags_arabic(self):
        """Test searching tags in Arabic"""
        results = Tag.objects.search_tags("لاهوت")
        self.assertIn(self.tag1, results)
        self.assertGreater(results.count(), 0)
    
    def test_search_tags_english(self):
        """Test searching tags in English"""
        results = Tag.objects.search_tags("Theology")
        self.assertIn(self.tag1, results)
    
    def test_search_tags_description(self):
        """Test searching in tag description"""
        results = Tag.objects.search_tags("العقائد")
        self.assertIn(self.tag1, results)
    
    def test_search_tags_inactive_excluded(self):
        """Test that inactive tags are excluded"""
        results = Tag.objects.search_tags("غير نشط")
        self.assertNotIn(self.tag_inactive, results)
    
    def test_search_tags_content_count(self):
        """Test that tags are annotated with content count"""
        results = Tag.objects.search_tags("لاهوت")
        tag = results.first()
        self.assertTrue(hasattr(tag, 'content_count'))
        self.assertEqual(tag.content_count, 1)  # One item tagged
    
    def test_search_tags_minimum_length(self):
        """Test that queries < 2 characters return nothing"""
        results = Tag.objects.search_tags("ل")
        self.assertEqual(results.count(), 0)
    
    def test_search_tags_language_detection(self):
        """Test automatic language detection for tag search"""
        # Arabic query
        results = Tag.objects.search_tags("لاهوت", language=None)
        self.assertGreater(results.count(), 0)
        
        # English query
        results = Tag.objects.search_tags("History", language=None)
        self.assertGreater(results.count(), 0)


class SearchAPITest(TestCase):
    """Test search API endpoints"""
    
    def setUp(self):
        """Set up test client and data"""
        self.client = Client()
        
        # Create test content
        self.item = ContentItem.objects.create(
            title_ar="كتاب اختبار",
            title_en="Test Book",
            description_ar="وصف الاختبار",
            content_type="pdf",
            is_active=True
        )
        self.item.update_search_vector()
        self.item.save()
        
        # Create test tag
        self.tag = Tag.objects.create(
            name_ar="اختبار",
            name_en="Test",
            is_active=True
        )
    
    def test_tag_search_api_arabic(self):
        """Test tag search API with Arabic query"""
        response = self.client.get('/api/search/tags/', {'q': 'اختبار'})
        self.assertEqual(response.status_code, 200)
        
        data = response.json()
        self.assertTrue(data['success'])
        self.assertGreater(data['count'], 0)
        self.assertIn('tags', data)
    
    def test_tag_search_api_english(self):
        """Test tag search API with English query"""
        response = self.client.get('/api/search/tags/', {'q': 'Test'})
        self.assertEqual(response.status_code, 200)
        
        data = response.json()
        self.assertTrue(data['success'])
        self.assertGreater(data['count'], 0)
    
    def test_tag_search_api_missing_query(self):
        """Test tag search API returns error without query"""
        response = self.client.get('/api/search/tags/')
        self.assertEqual(response.status_code, 400)
        
        data = response.json()
        self.assertFalse(data['success'])
        self.assertIn('error', data)
    
    def test_tag_search_api_language_param(self):
        """Test tag search API with language parameter"""
        response = self.client.get('/api/search/tags/', {
            'q': 'Test',
            'language': 'en'
        })
        self.assertEqual(response.status_code, 200)
        
        data = response.json()
        self.assertTrue(data['success'])


class SearchPerformanceTest(TestCase):
    """Test search performance and query optimization"""
    
    def setUp(self):
        """Create bulk test data"""
        # Create 50 items for performance testing
        for i in range(50):
            item = ContentItem.objects.create(
                title_ar=f"عنوان رقم {i}",
                title_en=f"Title {i}",
                description_ar=f"وصف المحتوى رقم {i}",
                description_en=f"Description of content {i}",
                content_type="pdf" if i % 3 == 0 else ("video" if i % 3 == 1 else "audio"),
                is_active=True
            )
            item.update_search_vector()
            item.save()
    
    def test_search_query_count(self):
        """Test that search executes minimal queries"""
        from django.db import connection, reset_queries
        
        # Enable query counting
        reset_queries()
        
        # Execute search
        results = list(ContentItem.objects.search_optimized("المحتوى"))
        
        # Check query count (optimized with prefetch_related)
        queries = len(connection.queries)
        
        # Should execute 2-3 queries:
        # 1. Main query with annotations (rank calculation)
        # 2. Prefetch for tags (M2M relationship)
        # 3. Possibly prefetch for metadata (videometa/audiometa/pdfmeta) if accessed
        self.assertLessEqual(queries, 3, f"Search executed {queries} queries, expected <= 3")
        self.assertGreaterEqual(queries, 1, f"Search must execute at least 1 query")
        
        # Verify that results are properly prefetched (accessing relations shouldn't trigger new queries)
        if results:
            reset_queries()
            # Access tags for first result
            _ = list(results[0].tags.all())
            new_queries = len(connection.queries)
            self.assertEqual(new_queries, 0, "Accessing prefetched tags should not trigger queries")
    
    def test_pagination_performance(self):
        """Test that paginated search is efficient and tags are prefetched"""
        from django.core.paginator import Paginator
        from django.db import connection, reset_queries
        
        queryset = ContentItem.objects.search_optimized("المحتوى")
        paginator = Paginator(queryset, 12)
        
        # Reset query count
        reset_queries()
        
        # Access first page
        page1 = paginator.get_page(1)
        self.assertLessEqual(len(page1), 12)
        
        # Verify tags are prefetched (accessing tags should not trigger new queries)
        initial_query_count = len(connection.queries)
        
        # Access tags for all items in page
        for item in page1:
            _ = list(item.tags.all())
        
        # Should not execute additional queries if tags are properly prefetched
        final_query_count = len(connection.queries)
        self.assertEqual(
            initial_query_count, 
            final_query_count,
            "Accessing prefetched tags should not trigger additional queries"
        )
