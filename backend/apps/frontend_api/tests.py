from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.sites.models import Site
from apps.media_manager.models import ContentItem
from apps.frontend_api.schema_generators import (
    generate_video_schema, generate_audio_schema, generate_book_schema,
    generate_schema_for_content, schema_to_json_ld
)
from apps.frontend_api.google_seo_service import get_absolute_content_url
import json


class RobotsTxtTestCase(TestCase):
    """Test robots.txt generation"""
    
    def setUp(self):
        self.client = Client()
    
    def test_robots_txt_accessible(self):
        """Test that robots.txt is accessible"""
        response = self.client.get('/robots.txt')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'text/plain')
    
    def test_robots_txt_disallows_admin(self):
        """Test that robots.txt disallows admin paths"""
        response = self.client.get('/robots.txt')
        content = response.content.decode('utf-8')
        self.assertIn('Disallow: /admin/', content)
        self.assertIn('Disallow: /api/', content)
        self.assertIn('Disallow: /dashboard/', content)
    
    def test_robots_txt_allows_public_content(self):
        """Test that robots.txt allows public content"""
        response = self.client.get('/robots.txt')
        content = response.content.decode('utf-8')
        self.assertIn('Allow: /ar/', content)
        self.assertIn('Allow: /en/', content)
    
    def test_robots_txt_includes_sitemap(self):
        """Test that robots.txt includes sitemap reference"""
        response = self.client.get('/robots.txt')
        content = response.content.decode('utf-8')
        self.assertIn('Sitemap:', content)
        self.assertIn('/sitemap.xml', content)


class SitemapTestCase(TestCase):
    """Test sitemap generation"""
    
    def setUp(self):
        self.client = Client()
    
    def test_sitemap_index_accessible(self):
        """Test that sitemap index is accessible"""
        response = self.client.get('/sitemap.xml')
        self.assertEqual(response.status_code, 200)
        self.assertIn('application/xml', response['Content-Type'])
    
    def test_sitemap_section_accessible(self):
        """Test that individual sitemap sections are accessible"""
        response = self.client.get('/sitemap-home.xml')
        self.assertEqual(response.status_code, 200)
        self.assertIn('application/xml', response['Content-Type'])


class RSSFeedTestCase(TestCase):
    """Test RSS feed generation"""
    
    def setUp(self):
        self.client = Client()
    
    def test_latest_feed_accessible(self):
        """Test that latest content RSS feed is accessible"""
        response = self.client.get('/feeds/latest.rss')
        self.assertEqual(response.status_code, 200)
        self.assertIn('xml', response['Content-Type'])
    
    def test_atom_feed_accessible(self):
        """Test that Atom feed is accessible"""
        response = self.client.get('/feeds/latest.atom')
        self.assertEqual(response.status_code, 200)
        self.assertIn('xml', response['Content-Type'])
    
    def test_videos_feed_accessible(self):
        """Test that videos RSS feed is accessible"""
        response = self.client.get('/feeds/videos.rss')
        self.assertEqual(response.status_code, 200)
        self.assertIn('xml', response['Content-Type'])
    
    def test_audios_feed_accessible(self):
        """Test that audios RSS feed is accessible"""
        response = self.client.get('/feeds/audios.rss')
        self.assertEqual(response.status_code, 200)
        self.assertIn('xml', response['Content-Type'])
    
    def test_pdfs_feed_accessible(self):
        """Test that PDFs RSS feed is accessible"""
        response = self.client.get('/feeds/pdfs.rss')
        self.assertEqual(response.status_code, 200)
        self.assertIn('xml', response['Content-Type'])


class SchemaGeneratorTestCase(TestCase):
    """Test JSON-LD schema generation"""
    
    def test_video_schema_generation(self):
        """Test video schema generation"""
        # Create a mock ContentItem for video
        content = ContentItem(
            id='123e4567-e89b-12d3-a456-426614174000',
            content_type='video',
            title_en='Test Video',
            title_ar='فيديو تجريبي',
            description_en='Test video description',
            description_ar='وصف الفيديو التجريبي',
            seo_keywords_en='test, video, keywords'
        )
        
        schema = generate_video_schema(content)
        
        self.assertEqual(schema['@type'], 'VideoObject')
        self.assertIn('name', schema)
        self.assertIn('description', schema)
        self.assertIn('keywords', schema)
    
    def test_audio_schema_generation(self):
        """Test audio schema generation"""
        content = ContentItem(
            id='123e4567-e89b-12d3-a456-426614174001',
            content_type='audio',
            title_en='Test Audio',
            title_ar='صوت تجريبي',
            description_en='Test audio description',
            description_ar='وصف الصوت التجريبي'
        )
        
        schema = generate_audio_schema(content)
        
        self.assertEqual(schema['@type'], 'AudioObject')
        self.assertIn('name', schema)
        self.assertIn('description', schema)
    
    def test_book_schema_generation(self):
        """Test book/PDF schema generation"""
        content = ContentItem(
            id='123e4567-e89b-12d3-a456-426614174002',
            content_type='pdf',
            title_en='Test Book',
            title_ar='كتاب تجريبي',
            description_en='Test book description',
            description_ar='وصف الكتاب التجريبي'
        )
        
        schema = generate_book_schema(content)
        
        self.assertEqual(schema['@type'], 'Book')
        self.assertIn('name', schema)
        self.assertIn('description', schema)
    
    def test_schema_to_json_ld(self):
        """Test conversion of schema to JSON-LD script tag"""
        schema = {
            "@context": "https://schema.org",
            "@type": "VideoObject",
            "name": "Test Video"
        }
        
        result = schema_to_json_ld(schema)
        
        self.assertIn('<script type="application/ld+json">', result)
        self.assertIn('"@type": "VideoObject"', result)
        self.assertIn('</script>', result)
    
    def test_generate_schema_for_content(self):
        """Test automatic schema generation based on content type"""
        # Test video
        video = ContentItem(
            id='123e4567-e89b-12d3-a456-426614174003',
            content_type='video',
            title_en='Video'
        )
        schema = generate_schema_for_content(video)
        self.assertEqual(schema['@type'], 'VideoObject')
        
        # Test audio
        audio = ContentItem(
            id='123e4567-e89b-12d3-a456-426614174004',
            content_type='audio',
            title_en='Audio'
        )
        schema = generate_schema_for_content(audio)
        self.assertEqual(schema['@type'], 'AudioObject')
        
        # Test PDF
        pdf = ContentItem(
            id='123e4567-e89b-12d3-a456-426614174005',
            content_type='pdf',
            title_en='Book'
        )
        schema = generate_schema_for_content(pdf)
        self.assertEqual(schema['@type'], 'Book')
