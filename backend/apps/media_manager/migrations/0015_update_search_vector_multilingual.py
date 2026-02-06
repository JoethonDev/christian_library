# Generated migration for multilingual full-text search enhancement

from django.db import migrations, models
from django.contrib.postgres.search import SearchVector


def update_search_vectors(apps, schema_editor):
    """
    Update all ContentItem search vectors to include new fields:
    - English title and description
    - Transcript
    - Notes
    This is a data migration that updates existing records.
    """
    ContentItem = apps.get_model('media_manager', 'ContentItem')
    
    # Process in batches to avoid memory issues
    batch_size = 100
    total_updated = 0
    
    # Only update items that have at least one searchable field
    items = ContentItem.objects.filter(
        models.Q(title_ar__isnull=False) | 
        models.Q(title_en__isnull=False) |
        models.Q(description_ar__isnull=False) |
        models.Q(description_en__isnull=False) |
        models.Q(transcript__isnull=False) |
        models.Q(notes__isnull=False) |
        models.Q(book_content__isnull=False)
    ).iterator(chunk_size=batch_size)
    
    for item in items:
        # Build search vector from all available fields
        search_parts = []
        
        # Arabic fields
        if item.title_ar:
            search_parts.append(SearchVector('title_ar', weight='A', config='arabic'))
        if item.description_ar:
            search_parts.append(SearchVector('description_ar', weight='B', config='arabic'))
        
        # English fields
        if item.title_en:
            search_parts.append(SearchVector('title_en', weight='A', config='english'))
        if item.description_en:
            search_parts.append(SearchVector('description_en', weight='B', config='english'))
        
        # Transcript and notes (simple config for mixed languages)
        if item.transcript:
            search_parts.append(SearchVector('transcript', weight='C', config='simple'))
        if item.notes:
            search_parts.append(SearchVector('notes', weight='D', config='simple'))
        
        # Book content
        if item.book_content:
            search_parts.append(SearchVector('book_content', weight='D', config='arabic'))
        
        # Update search vector if we have any content
        if search_parts:
            search_vector = search_parts[0]
            for part in search_parts[1:]:
                search_vector += part
            
            # Update the item
            ContentItem.objects.filter(pk=item.pk).update(search_vector=search_vector)
            total_updated += 1
    
    # Migration uses schema_editor for output (not print)
    # This is logged during migration execution


def reverse_update(apps, schema_editor):
    """
    Reverse migration: revert to old search vector format (title_ar, description_ar, book_content only)
    """
    ContentItem = apps.get_model('media_manager', 'ContentItem')
    
    batch_size = 100
    items = ContentItem.objects.filter(
        models.Q(title_ar__isnull=False) | 
        models.Q(description_ar__isnull=False) |
        models.Q(book_content__isnull=False)
    ).iterator(chunk_size=batch_size)
    
    for item in items:
        search_vector = (
            SearchVector('title_ar', weight='A', config='arabic') +
            SearchVector('description_ar', weight='B', config='arabic') +
            SearchVector('book_content', weight='C', config='arabic')
        )
        ContentItem.objects.filter(pk=item.pk).update(search_vector=search_vector)


class Migration(migrations.Migration):

    dependencies = [
        ('media_manager', '0014_alter_dailycontentviewsummary_view_count'),
    ]

    operations = [
        migrations.RunPython(update_search_vectors, reverse_update),
    ]
