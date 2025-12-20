from django.core.management.base import BaseCommand
from apps.media_manager.models import ContentItem

class Command(BaseCommand):
    help = 'Bulk extract and index all PDF ContentItems.'

    def handle(self, *args, **options):
        pdf_items = ContentItem.objects.filter(content_type='pdf')
        for item in pdf_items:
            item.trigger_background_extraction_and_indexing()
        self.stdout.write(self.style.SUCCESS(f'Triggered extraction/indexing for {pdf_items.count()} PDF items.'))
