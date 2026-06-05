"""
Test SEO Generation Management Command
========================================
Tests Gemini SEO metadata generation with Phase 2 enhancements.
Validates character limits, format compliance, and quality.

Usage:
    python manage.py test_seo_generation --file path/to/test/file.mp4
    python manage.py test_seo_generation --type video --sample
"""
from django.core.management.base import BaseCommand
from core.services.gemini_seo_service import get_gemini_seo_service
from core.services.gemini_metadata_service import get_gemini_metadata_service
import os
import traceback


class Command(BaseCommand):
    help = 'Test SEO generation with Phase 2 validation'

    def add_arguments(self, parser):
        parser.add_argument(
            '--file',
            type=str,
            help='Path to test file (video/audio/pdf)'
        )
        parser.add_argument(
            '--type',
            type=str,
            choices=['video', 'audio', 'pdf'],
            help='Content type for sample test'
        )
        parser.add_argument(
            '--sample',
            action='store_true',
            help='Use sample data instead of real file'
        )

    def handle(self, *args, **options):
        self.stdout.write(self.style.WARNING('\n=== SEO Generation Test (Phase 2) ===\n'))
        
        # Get services
        seo_service = get_gemini_seo_service()
        metadata_service = get_gemini_metadata_service()
        
        # Check availability
        if not seo_service.is_available():
            self.stdout.write(self.style.ERROR('✗ Gemini SEO service not available'))
            self.stdout.write('  Check GEMINI_API_KEY in settings')
            return
        
        self.stdout.write(self.style.SUCCESS('✓ Gemini services available\n'))
        
        # Determine test file
        file_path = options.get('file')
        content_type = options.get('type', 'video')
        use_sample = options.get('sample', False)
        
        if use_sample or not file_path:
            self.stdout.write(self.style.WARNING('Using sample test (no file upload)\n'))
            self.test_prompt_format(seo_service, content_type)
        else:
            if not os.path.exists(file_path):
                self.stdout.write(self.style.ERROR(f'✗ File not found: {file_path}'))
                return
            
            self.stdout.write(f'Testing with file: {file_path}\n')
            self.test_real_file(seo_service, metadata_service, file_path, content_type)
    
    def test_prompt_format(self, seo_service, content_type):
        """Test prompt format without actually calling API"""
        self.stdout.write(self.style.SUCCESS('--- Testing Prompt Format ---\n'))
        
        # Generate prompt
        prompt = seo_service._create_seo_prompt(content_type)
        
        # Check for Phase 2 enhancements
        checks = {
            'EXCELLENT EXAMPLES': '✅ Good/bad examples' in prompt or 'EXCELLENT EXAMPLES' in prompt,
            'Character count validation': 'EXACTLY 50-60' in prompt,
            'Media type': f'MEDIA TYPE FOR THIS CONTENT:' in prompt,
            'Title format': '| Video | Anba Abraam Library' in prompt or '| Audio |' in prompt or '| PDF Book |' in prompt,
            'Action verbs': 'Watch/Listen/Download' in prompt
        }
        
        for check, passed in checks.items():
            if passed:
                self.stdout.write(self.style.SUCCESS(f'  ✓ {check}'))
            else:
                self.stdout.write(self.style.ERROR(f'  ✗ {check}'))
        
        # Display prompt excerpt
        self.stdout.write('\n--- Prompt Excerpt (Examples Section) ---')
        if 'EXCELLENT EXAMPLES' in prompt:
            start = prompt.index('EXCELLENT EXAMPLES')
            end = start + 800
            self.stdout.write(prompt[start:end] + '...\n')
        
        self.stdout.write(self.style.SUCCESS('\n✓ Prompt format test complete'))
    
    def test_real_file(self, seo_service, metadata_service, file_path, content_type):
        """Test with real file generation"""
        self.stdout.write(self.style.SUCCESS('--- Testing Real File Generation ---\n'))
        
        try:
            # Generate SEO metadata
            self.stdout.write('Generating SEO metadata...')
            success, seo_data = seo_service.generate_seo(file_path, content_type)
            
            if not success:
                self.stdout.write(self.style.ERROR('✗ SEO generation failed'))
                self.stdout.write(f'  Error: {seo_data}')
                return
            
            self.stdout.write(self.style.SUCCESS('✓ SEO generation successful\n'))
            
            # Validate results
            self.validate_seo_output(seo_data)
            
            # Generate metadata for comparison
            self.stdout.write('\nGenerating content metadata...')
            success, metadata = metadata_service.generate_metadata(file_path, content_type)
            
            if success:
                self.stdout.write(self.style.SUCCESS('✓ Metadata generation successful\n'))
                self.validate_metadata_output(metadata)
            
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'✗ Error during generation: {e}'))
            self.stdout.write(traceback.format_exc())
    
    def validate_seo_output(self, seo_data):
        """Validate SEO output against Phase 2 requirements"""
        self.stdout.write(self.style.WARNING('--- SEO Validation ---\n'))
        
        total_checks = 0
        passed_checks = 0
        
        for lang in ['en', 'ar']:
            if lang not in seo_data:
                self.stdout.write(self.style.ERROR(f'✗ Missing {lang.upper()} data'))
                continue
            
            lang_data = seo_data[lang]
            lang_display = lang.upper()
            
            # Check meta_title
            title = lang_data.get('meta_title', '')
            title_len = len(title)
            total_checks += 1
            if 50 <= title_len <= 60:
                self.stdout.write(self.style.SUCCESS(
                    f'  ✓ [{lang_display}] Title length: {title_len} chars ✓ PERFECT'
                ))
                passed_checks += 1
            else:
                self.stdout.write(self.style.ERROR(
                    f'  ✗ [{lang_display}] Title length: {title_len} chars (target: 50-60)'
                ))
            self.stdout.write(f'      "{title}"')
            
            # Check title format (should contain | and Anba Abraam Library)
            total_checks += 1
            if '|' in title and ('Anba Abraam Library' in title or 'مكتبة الأنبا أبرآم' in title):
                self.stdout.write(self.style.SUCCESS(
                    f'  ✓ [{lang_display}] Title format: Contains pipe separator and site name'
                ))
                passed_checks += 1
            else:
                self.stdout.write(self.style.WARNING(
                    f'  ⚠ [{lang_display}] Title format: May not follow blueprint'
                ))
            
            # Check description
            desc = lang_data.get('description', '')
            desc_len = len(desc)
            total_checks += 1
            if 150 <= desc_len <= 160:
                self.stdout.write(self.style.SUCCESS(
                    f'  ✓ [{lang_display}] Description length: {desc_len} chars ✓ PERFECT'
                ))
                passed_checks += 1
            else:
                self.stdout.write(self.style.ERROR(
                    f'  ✗ [{lang_display}] Description length: {desc_len} chars (target: 150-160)'
                ))
            self.stdout.write(f'      "{desc[:80]}..."')
            
            # Check keywords
            keywords = lang_data.get('keywords', [])
            kw_count = len(keywords)
            total_checks += 1
            if 8 <= kw_count <= 12:
                self.stdout.write(self.style.SUCCESS(
                    f'  ✓ [{lang_display}] Keywords: {kw_count} keywords ✓ GOOD'
                ))
                passed_checks += 1
            else:
                self.stdout.write(self.style.WARNING(
                    f'  ⚠ [{lang_display}] Keywords: {kw_count} keywords (target: 8-12)'
                ))
            
            # Check structured_data
            structured = lang_data.get('structured_data', {})
            total_checks += 1
            if '@type' in structured:
                self.stdout.write(self.style.SUCCESS(
                    f'  ✓ [{lang_display}] Structured data: @type = {structured.get("@type")}'
                ))
                passed_checks += 1
            else:
                self.stdout.write(self.style.ERROR(
                    f'  ✗ [{lang_display}] Structured data: Missing @type'
                ))
        
        # Summary
        score = (passed_checks / total_checks * 100) if total_checks > 0 else 0
        self.stdout.write(f'\n--- Validation Score: {passed_checks}/{total_checks} ({score:.1f}%) ---\n')
        
        if score >= 90:
            self.stdout.write(self.style.SUCCESS('✓ EXCELLENT - SEO quality meets Phase 2 standards'))
        elif score >= 70:
            self.stdout.write(self.style.WARNING('⚠ GOOD - Minor improvements needed'))
        else:
            self.stdout.write(self.style.ERROR('✗ NEEDS WORK - Review Gemini prompts'))
    
    def validate_metadata_output(self, metadata):
        """Validate metadata output"""
        self.stdout.write(self.style.WARNING('--- Metadata Validation ---\n'))
        
        for lang in ['en', 'ar']:
            if lang in metadata:
                lang_data = metadata[lang]
                title = lang_data.get('title', '')
                desc = lang_data.get('description', '')
                tags = lang_data.get('tags', [])
                
                self.stdout.write(f'  [{lang.upper()}] Title: {title} ({len(title)} chars)')
                self.stdout.write(f'  [{lang.upper()}] Description: {desc[:50]}... ({len(desc)} chars)')
                self.stdout.write(f'  [{lang.upper()}] Tags: {len(tags)} tags')
