# Generated migration for multilingual full-text search enhancement

from django.db import migrations


def update_search_vectors(apps, schema_editor):
    """
    Update all ContentItem search vectors to include new fields:
    - English title and description
    - Transcript
    - Notes
    This is a data migration that updates existing records using raw SQL.
    """
    # Use raw SQL to update search vectors efficiently
    # This avoids the complexity of using SearchVector in migrations
    sql = """
        UPDATE media_manager_contentitem
        SET search_vector = 
            setweight(to_tsvector('arabic', COALESCE(title_ar, '')), 'A') ||
            setweight(to_tsvector('english', COALESCE(title_en, '')), 'A') ||
            setweight(to_tsvector('arabic', COALESCE(description_ar, '')), 'B') ||
            setweight(to_tsvector('english', COALESCE(description_en, '')), 'B') ||
            setweight(to_tsvector('simple', COALESCE(transcript, '')), 'C') ||
            setweight(to_tsvector('simple', COALESCE(notes, '')), 'D') ||
            setweight(to_tsvector('arabic', COALESCE(book_content, '')), 'D')
        WHERE 
            title_ar IS NOT NULL OR
            title_en IS NOT NULL OR
            description_ar IS NOT NULL OR
            description_en IS NOT NULL OR
            transcript IS NOT NULL OR
            notes IS NOT NULL OR
            book_content IS NOT NULL;
    """
    
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(sql)


def reverse_update(apps, schema_editor):
    """
    Reverse migration: revert to old search vector format 
    (title_ar, description_ar, book_content only)
    """
    sql = """
        UPDATE media_manager_contentitem
        SET search_vector = 
            setweight(to_tsvector('arabic', COALESCE(title_ar, '')), 'A') ||
            setweight(to_tsvector('arabic', COALESCE(description_ar, '')), 'B') ||
            setweight(to_tsvector('arabic', COALESCE(book_content, '')), 'C')
        WHERE 
            title_ar IS NOT NULL OR
            description_ar IS NOT NULL OR
            book_content IS NOT NULL;
    """
    
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(sql)


class Migration(migrations.Migration):

    dependencies = [
        ('media_manager', '0014_alter_dailycontentviewsummary_view_count'),
    ]

    operations = [
        migrations.RunPython(update_search_vectors, reverse_update),
    ]
