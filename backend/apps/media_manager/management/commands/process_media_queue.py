from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta

from apps.media_manager.models import VideoMeta, AudioMeta, PdfMeta
from core.tasks.media_processing import (
    process_video_to_hls, process_audio_compression, process_pdf_optimization
)


class Command(BaseCommand):
    help = 'Process pending media files and monitor processing queue'
    
    def add_arguments(self, parser):
        parser.add_argument(
            '--type',
            type=str,
            choices=['video', 'audio', 'pdf', 'all'],
            default='all',
            help='Type of media to process (default: all)'
        )
        parser.add_argument(
            '--retry-failed',
            action='store_true',
            help='Retry failed processing tasks'
        )
        parser.add_argument(
            '--status',
            action='store_true',
            help='Show processing status overview'
        )
    
    def handle(self, *args, **options):
        if options['status']:
            self.show_status()
            return
        
        media_type = options['type']
        retry_failed = options['retry_failed']
        
        self.stdout.write(f'Processing {media_type} media files...')
        
        if media_type in ['video', 'all']:
            self.process_videos(retry_failed)
        
        if media_type in ['audio', 'all']:
            self.process_audios(retry_failed)
        
        if media_type in ['pdf', 'all']:
            self.process_pdfs(retry_failed)
        
        self.stdout.write(
            self.style.SUCCESS('Successfully processed media queue')
        )
    
    def process_videos(self, retry_failed=False):
        """Process pending video files"""
        status_filter = ['pending']
        if retry_failed:
            status_filter.append('failed')
        
        videos = VideoMeta.objects.filter(
            processing_status__in=status_filter,
            original_file__isnull=False
        )
        
        count = 0
        for video in videos:
            video.processing_status = 'pending'
            video.save()
            process_video_to_hls.delay(video.id)
            count += 1
            self.stdout.write(f'Queued video: {video.content_item.title_ar}')
        
        self.stdout.write(f'Queued {count} videos for processing')
    
    def process_audios(self, retry_failed=False):
        """Process pending audio files"""
        status_filter = ['pending']
        if retry_failed:
            status_filter.append('failed')
        
        audios = AudioMeta.objects.filter(
            processing_status__in=status_filter,
            original_file__isnull=False
        )
        
        count = 0
        for audio in audios:
            audio.processing_status = 'pending'
            audio.save()
            process_audio_compression.delay(audio.id)
            count += 1
            self.stdout.write(f'Queued audio: {audio.content_item.title_ar}')
        
        self.stdout.write(f'Queued {count} audios for processing')
    
    def process_pdfs(self, retry_failed=False):
        """Process pending PDF files"""
        status_filter = ['pending']
        if retry_failed:
            status_filter.append('failed')
        
        pdfs = PdfMeta.objects.filter(
            processing_status__in=status_filter,
            original_file__isnull=False
        )
        
        count = 0
        for pdf in pdfs:
            pdf.processing_status = 'pending'
            pdf.save()
            process_pdf_optimization.delay(pdf.id)
            count += 1
            self.stdout.write(f'Queued PDF: {pdf.content_item.title_ar}')
        
        self.stdout.write(f'Queued {count} PDFs for processing')
    
    def show_status(self):
        """Show processing status overview"""
        self.stdout.write('\n=== Media Processing Status ===')
        
        # Video status
        video_stats = VideoMeta.objects.values_list('processing_status', flat=True)
        video_counts = {}
        for status in video_stats:
            video_counts[status] = video_counts.get(status, 0) + 1
        
        self.stdout.write('\nVideos:')
        for status, count in video_counts.items():
            self.stdout.write(f'  {status}: {count}')
        
        # Audio status
        audio_stats = AudioMeta.objects.values_list('processing_status', flat=True)
        audio_counts = {}
        for status in audio_stats:
            audio_counts[status] = audio_counts.get(status, 0) + 1
        
        self.stdout.write('\nAudios:')
        for status, count in audio_counts.items():
            self.stdout.write(f'  {status}: {count}')
        
        # PDF status
        pdf_stats = PdfMeta.objects.values_list('processing_status', flat=True)
        pdf_counts = {}
        for status in pdf_stats:
            pdf_counts[status] = pdf_counts.get(status, 0) + 1
        
        self.stdout.write('\nPDFs:')
        for status, count in pdf_counts.items():
            self.stdout.write(f'  {status}: {count}')
        
        # Find stuck processing items (processing for > 2 hours)
        stuck_cutoff = timezone.now() - timedelta(hours=2)
        
        stuck_videos = VideoMeta.objects.filter(
            processing_status='processing',
            content_item__created_at__lt=stuck_cutoff
        ).count()
        
        stuck_audios = AudioMeta.objects.filter(
            processing_status='processing',
            content_item__created_at__lt=stuck_cutoff
        ).count()
        
        stuck_pdfs = PdfMeta.objects.filter(
            processing_status='processing',
            content_item__created_at__lt=stuck_cutoff
        ).count()
        
        if stuck_videos + stuck_audios + stuck_pdfs > 0:
            self.stdout.write(
                self.style.WARNING(
                    f'\nStuck items (processing > 2h): '
                    f'Videos: {stuck_videos}, Audios: {stuck_audios}, PDFs: {stuck_pdfs}'
                )
            )
            self.stdout.write(
                'Run with --retry-failed to reprocess stuck items'
            )
        
        self.stdout.write('\n=== End Status ===')