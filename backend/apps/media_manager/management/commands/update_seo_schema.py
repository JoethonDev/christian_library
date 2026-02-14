"""
Update SEO Schema Management Command
=====================================
Updates SiteConfiguration to use ArchiveOrganization schema type
and ensures all blueprint fields are present.

Run after Phase 1 implementation to update existing data.

Usage:
    python manage.py update_seo_schema
"""
from django.core.management.base import BaseCommand
from apps.media_manager.models import SiteConfiguration


class Command(BaseCommand):
    help = 'Update SiteConfiguration schema to ArchiveOrganization with all blueprint fields'

    def handle(self, *args, **options):
        self.stdout.write(self.style.WARNING('=== Updating SEO Schema ===\n'))
        
        try:
            config = SiteConfiguration.objects.first()
            
            if not config:
                self.stdout.write(self.style.ERROR('✗ No SiteConfiguration found. Creating default...'))
                config = SiteConfiguration.objects.create(
                    site_name_en="Anba Abraam Coptic Orthodox Library",
                    site_name_ar="مكتبة القديس أنبا أبرآم القبطية الأرثوذكسية",
                    description_en="The definitive digitized archive of Saint Anba Abraam's teachings. Featuring Coptic Orthodox PDF books, spiritual audio sermons, and liturgical video media.",
                    description_ar="الأرشيف الرقمي المعتمد لتعاليم القديس أنبا أبرآم (صديق الفقراء). تضم المكتبة كتب قبطية PDF، عظات مسموعة، ووسائط فيديو طقسية.",
                    website_url="https://anbaabraamlibrary.org"
                )
                self.stdout.write(self.style.SUCCESS('✓ Default SiteConfiguration created'))
            
            # Check current schema type
            old_type_en = config.structured_data.get('en', {}).get('@type', 'None')
            old_type_ar = config.structured_data.get('ar', {}).get('@type', 'None')
            
            self.stdout.write(f'\nCurrent Schema Type:')
            self.stdout.write(f'  EN: {old_type_en}')
            self.stdout.write(f'  AR: {old_type_ar}')
            
            # Force sync_structured_data to run
            config.sync_structured_data()
            config.save()
            
            # Verify update
            new_type_en = config.structured_data.get('en', {}).get('@type', 'None')
            new_type_ar = config.structured_data.get('ar', {}).get('@type', 'None')
            
            self.stdout.write(f'\nUpdated Schema Type:')
            self.stdout.write(self.style.SUCCESS(f'  EN: {new_type_en}'))
            self.stdout.write(self.style.SUCCESS(f'  AR: {new_type_ar}'))
            
            # Check for new fields
            new_fields = ['alternateName', 'address', 'knowsAbout', 'potentialAction']
            missing_fields = []
            
            for lang in ['en', 'ar']:
                for field in new_fields:
                    if field not in config.structured_data.get(lang, {}):
                        missing_fields.append(f'{lang}.{field}')
            
            if missing_fields:
                self.stdout.write(self.style.WARNING(f'\n⚠ Missing fields: {", ".join(missing_fields)}'))
            else:
                self.stdout.write(self.style.SUCCESS(f'\n✓ All blueprint fields present'))
            
            # Display final schema (abbreviated)
            self.stdout.write(f'\n--- English Schema Preview ---')
            en_schema = config.structured_data.get('en', {})
            self.stdout.write(f'  @type: {en_schema.get("@type")}')
            self.stdout.write(f'  name: {en_schema.get("name")}')
            self.stdout.write(f'  alternateName: {en_schema.get("alternateName")}')
            self.stdout.write(f'  knowsAbout: {len(en_schema.get("knowsAbout", []))} topics')
            self.stdout.write(f'  potentialAction: {en_schema.get("potentialAction", {}).get("@type")}')
            
            self.stdout.write(self.style.SUCCESS(f'\n✓ Schema update complete!'))
            self.stdout.write(f'\nNext Steps:')
            self.stdout.write(f'  1. Test with Google Rich Results Test')
            self.stdout.write(f'  2. Verify schema appears on homepage')
            self.stdout.write(f'  3. Check for validation errors')
            
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'\n✗ Error updating schema: {e}'))
            import traceback
            self.stdout.write(traceback.format_exc())
