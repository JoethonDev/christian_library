"""
Backup management command for Christian Library project.
"""

import os
import subprocess
import tarfile
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand
from django.core.mail import send_mail


class Command(BaseCommand):
    help = 'Create backup of database and media files'

    def add_arguments(self, parser):
        parser.add_argument(
            '--type',
            choices=['database', 'media', 'full'],
            default='full',
            help='Type of backup to create'
        )
        parser.add_argument(
            '--cleanup',
            action='store_true',
            help='Clean up old backups'
        )
        parser.add_argument(
            '--retention-days',
            type=int,
            default=getattr(settings, 'BACKUP_RETENTION_DAYS', 30),
            help='Number of days to retain backups'
        )

    def handle(self, *args, **options):
        backup_type = options['type']
        cleanup = options['cleanup']
        retention_days = options['retention_days']

        # Create backup directory
        backup_dir = Path(getattr(settings, 'BACKUP_LOCAL_DIRECTORY', '/app/backups/'))
        backup_dir.mkdir(exist_ok=True)

        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        
        try:
            if backup_type in ['database', 'full']:
                self._backup_database(backup_dir, timestamp)
                self.stdout.write(
                    self.style.SUCCESS(f'Database backup completed: {timestamp}')
                )

            if backup_type in ['media', 'full']:
                self._backup_media(backup_dir, timestamp)
                self.stdout.write(
                    self.style.SUCCESS(f'Media backup completed: {timestamp}')
                )

            if cleanup:
                self._cleanup_old_backups(backup_dir, retention_days)
                self.stdout.write(
                    self.style.SUCCESS(f'Cleanup completed: removed backups older than {retention_days} days')
                )

            # Send notification email if configured
            if hasattr(settings, 'EMAIL_HOST_USER') and settings.EMAIL_HOST_USER:
                self._send_notification(backup_type, timestamp, success=True)

        except Exception as e:
            self.stdout.write(
                self.style.ERROR(f'Backup failed: {str(e)}')
            )
            
            # Send error notification
            if hasattr(settings, 'EMAIL_HOST_USER') and settings.EMAIL_HOST_USER:
                self._send_notification(backup_type, timestamp, success=False, error=str(e))
            
            raise

    def _backup_database(self, backup_dir, timestamp):
        """Create database backup using pg_dump"""
        db_config = settings.DATABASES['default']
        
        # Set environment variables for pg_dump
        env = os.environ.copy()
        env['PGPASSWORD'] = db_config['PASSWORD']
        
        backup_file = backup_dir / f'database_backup_{timestamp}.sql.gz'
        
        # Create pg_dump command
        cmd = [
            'pg_dump',
            '-h', db_config['HOST'],
            '-p', str(db_config['PORT']),
            '-U', db_config['USER'],
            '-d', db_config['NAME'],
            '--no-password',
            '--verbose',
            '--clean',
            '--no-owner',
            '--no-privileges',
        ]
        
        # Execute pg_dump and compress
        with open(backup_file, 'wb') as f:
            dump_process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=env
            )
            
            gzip_process = subprocess.Popen(
                ['gzip'],
                stdin=dump_process.stdout,
                stdout=f,
                stderr=subprocess.PIPE
            )
            
            dump_process.stdout.close()
            gzip_process.communicate()
            
            if dump_process.returncode != 0:
                raise Exception(f'pg_dump failed with return code {dump_process.returncode}')
            
            if gzip_process.returncode != 0:
                raise Exception(f'gzip compression failed with return code {gzip_process.returncode}')

    def _backup_media(self, backup_dir, timestamp):
        """Create media files backup"""
        media_root = Path(settings.MEDIA_ROOT)
        backup_file = backup_dir / f'media_backup_{timestamp}.tar.gz'
        
        if not media_root.exists():
            self.stdout.write(
                self.style.WARNING('Media directory does not exist, skipping media backup')
            )
            return
        
        with tarfile.open(backup_file, 'w:gz') as tar:
            tar.add(media_root, arcname='media')

    def _cleanup_old_backups(self, backup_dir, retention_days):
        """Remove backups older than retention_days"""
        cutoff_date = datetime.now() - timedelta(days=retention_days)
        
        for backup_file in backup_dir.glob('*_backup_*.{sql.gz,tar.gz}'):
            file_stat = backup_file.stat()
            file_date = datetime.fromtimestamp(file_stat.st_mtime)
            
            if file_date < cutoff_date:
                backup_file.unlink()
                self.stdout.write(
                    self.style.WARNING(f'Removed old backup: {backup_file.name}')
                )

    def _send_notification(self, backup_type, timestamp, success=True, error=None):
        """Send email notification about backup status"""
        if success:
            subject = f'Christian Library Backup Successful - {backup_type} - {timestamp}'
            message = f'''
Backup completed successfully:

Type: {backup_type}
Timestamp: {timestamp}
Server: {os.environ.get('HOSTNAME', 'Unknown')}

All backup files have been created and stored securely.
            '''
        else:
            subject = f'Christian Library Backup FAILED - {backup_type} - {timestamp}'
            message = f'''
Backup FAILED:

Type: {backup_type}
Timestamp: {timestamp}
Server: {os.environ.get('HOSTNAME', 'Unknown')}
Error: {error}

Please check the backup system immediately.
            '''

        try:
            send_mail(
                subject,
                message,
                settings.DEFAULT_FROM_EMAIL,
                ['admin@christianlibrary.com'],
                fail_silently=False,
            )
        except Exception as e:
            self.stdout.write(
                self.style.WARNING(f'Failed to send notification email: {str(e)}')
            )