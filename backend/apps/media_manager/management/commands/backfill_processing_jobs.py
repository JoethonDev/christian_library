from django.core.management.base import BaseCommand

from apps.media_manager.models import ContentItem, ProcessingJob


class Command(BaseCommand):
    help = 'Backfill ProcessingJob records for existing ContentItem rows'

    def handle(self, *args, **options):
        created_count = 0
        existing_count = 0

        for content_item in ContentItem.objects.all().iterator(chunk_size=500):
            _, created = ProcessingJob.objects.get_or_create(content_item=content_item)
            if created:
                created_count += 1
            else:
                existing_count += 1

        self.stdout.write(
            self.style.SUCCESS(
                f'Backfill complete. Created {created_count} ProcessingJob records; '
                f'{existing_count} already existed.'
            )
        )
