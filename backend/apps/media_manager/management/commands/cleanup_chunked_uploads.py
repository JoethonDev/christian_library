from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta
import os
from apps.media_manager.models import ChunkedUploadSession


class Command(BaseCommand):
    help = 'Cleanup abandoned ChunkedUploadSession rows and their partial staging files.'

    def add_arguments(self, parser):
        parser.add_argument('--hours', type=int, default=24, help='Consider sessions older than this (hours) as abandoned')
        parser.add_argument('--dry-run', action='store_true', help='Do not delete files, only report')

    def handle(self, *args, **options):
        hours = options.get('hours', 24)
        dry_run = options.get('dry_run', False)

        cutoff = timezone.now() - timedelta(hours=hours)
        stale_qs = ChunkedUploadSession.objects.filter(is_complete=False, updated_at__lt=cutoff)
        count = stale_qs.count()
        self.stdout.write(f'Found {count} stale ChunkedUploadSession(s) older than {hours} hours')

        if dry_run:
            for s in stale_qs:
                path = s.staging_path or '<none>'
                size = '<missing>'
                try:
                    if path and os.path.exists(path):
                        size = f"{os.path.getsize(path)} bytes"
                except Exception:
                    pass
                self.stdout.write(f'- {s.id} file={path} size={size} updated_at={s.updated_at}')
            return

        removed = ChunkedUploadSession.cleanup_abandoned(older_than_hours=hours)
        self.stdout.write(self.style.SUCCESS(f'Removed {removed} stale session(s)'))
