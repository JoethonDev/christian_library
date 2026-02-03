"""
Management command to verify all Phase 3 strategic indexes are present.
Usage: python manage.py verify_phase3_indexes
"""
from django.core.management.base import BaseCommand
from django.db import connection


class Command(BaseCommand):
    help = 'Verify all Phase 3 strategic database indexes are present'
    
    # Expected indexes from Phase 3 optimization
    EXPECTED_INDEXES = [
        # ContentItem indexes (from model Meta)
        'mgr_active_type_created_idx',
        'mgr_active_search_idx', 
        'mgr_type_title_ar_idx',
        'mgr_type_lookup_idx',
        'mgr_updated_at_idx',
        
        # Tag indexes (from model Meta)
        'mgr_tag_active_created_idx',
        'mgr_tag_active_name_idx',
        
        # M2M indexes (from migrations only - keep original names)
        'media_mgr_contentitem_tags_covering_idx',
    ]
    
    def handle(self, *args, **options):
        """Check database for Phase 3 strategic indexes"""
        
        self.stdout.write(
            self.style.SUCCESS('=== Phase 3 Index Verification ===\n')
        )
        
        with connection.cursor() as cursor:
            # Get all indexes
            if connection.vendor == 'postgresql':
                cursor.execute("""
                    SELECT indexname FROM pg_indexes 
                    WHERE indexname LIKE 'mgr_%' OR indexname LIKE 'media_mgr_%'
                    ORDER BY indexname
                """)
            else:  # SQLite
                cursor.execute("""
                    SELECT name FROM sqlite_master 
                    WHERE type='index' AND (name LIKE 'mgr_%' OR name LIKE 'media_mgr_%')
                    ORDER BY name
                """)
            
            existing_indexes = {row[0] for row in cursor.fetchall()}
        
        # Check each expected index
        missing_indexes = []
        for index_name in self.EXPECTED_INDEXES:
            if index_name in existing_indexes:
                self.stdout.write(
                    f"✅ {index_name} - Present"
                )
            else:
                self.stdout.write(
                    self.style.ERROR(f"❌ {index_name} - MISSING")
                )
                missing_indexes.append(index_name)
        
        # Summary
        self.stdout.write(f"\n=== Summary ===")
        self.stdout.write(f"Expected indexes: {len(self.EXPECTED_INDEXES)}")
        self.stdout.write(f"Present indexes: {len(self.EXPECTED_INDEXES) - len(missing_indexes)}")
        
        if missing_indexes:
            self.stdout.write(
                self.style.ERROR(f"Missing indexes: {len(missing_indexes)}")
            )
            self.stdout.write(
                self.style.WARNING(
                    f"\nTo fix missing indexes, run:\n"
                    f"python manage.py makemigrations media_manager\n"
                    f"python manage.py migrate media_manager"
                )
            )
        else:
            self.stdout.write(
                self.style.SUCCESS("All Phase 3 strategic indexes are present! 🎉")
            )