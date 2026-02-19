from django.db import models
from django.utils.translation import gettext_lazy as _
from django.conf import settings
import uuid
import json
from datetime import datetime, timedelta

# Frontend API models if needed in the future


class GoogleReindexingTask(models.Model):
    """
    Tracks Google Search Console re-indexing operations.
    Stores progress, results, and history of bulk URL submissions to Google Indexing API.
    """
    
    STATUS_CHOICES = [
        ('pending', _('Pending')),
        ('in_progress', _('In Progress')),
        ('completed', _('Completed')),
        ('failed', _('Failed')),
        ('cancelled', _('Cancelled')),
    ]
    
    CONTENT_TYPE_CHOICES = [
        ('all', _('All Content')),
        ('video', _('Videos Only')),
        ('audio', _('Audios Only')),
        ('pdf', _('PDFs Only')),
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    status = models.CharField(
        max_length=20, 
        choices=STATUS_CHOICES, 
        default='pending',
        db_index=True,
        verbose_name=_('Status')
    )
    content_type = models.CharField(
        max_length=10, 
        choices=CONTENT_TYPE_CHOICES, 
        null=True, 
        blank=True,
        verbose_name=_('Content Type')
    )
    total_urls = models.IntegerField(
        default=0,
        verbose_name=_('Total URLs')
    )
    submitted_urls = models.IntegerField(
        default=0,
        verbose_name=_('Submitted URLs')
    )
    successful_urls = models.IntegerField(
        default=0,
        verbose_name=_('Successful URLs')
    )
    failed_urls = models.IntegerField(
        default=0,
        verbose_name=_('Failed URLs')
    )
    error_log = models.TextField(
        blank=True,
        default='[]',
        verbose_name=_('Error Log'),
        help_text=_('JSON array of error details')
    )
    started_at = models.DateTimeField(
        null=True, 
        blank=True,
        verbose_name=_('Started At')
    )
    completed_at = models.DateTimeField(
        null=True, 
        blank=True,
        verbose_name=_('Completed At')
    )
    initiated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name='reindexing_tasks',
        verbose_name=_('Initiated By')
    )
    sitemap_included = models.BooleanField(
        default=True,
        verbose_name=_('Sitemap Included'),
        help_text=_('Whether to ping sitemap after completion')
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name=_('Created At')
    )
    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name=_('Updated At')
    )
    
    class Meta:
        verbose_name = _('Google Re-indexing Task')
        verbose_name_plural = _('Google Re-indexing Tasks')
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['-created_at']),
            models.Index(fields=['status', '-created_at']),
        ]
    
    def __str__(self):
        return f"Re-indexing Task {self.id} - {self.status}"
    
    def get_progress_percentage(self):
        """Calculate progress percentage based on submitted URLs"""
        if self.total_urls == 0:
            return 0
        return round((self.submitted_urls / self.total_urls) * 100, 2)
    
    def get_estimated_time_remaining(self):
        """
        Estimate remaining time in seconds based on current progress.
        Returns None if cannot estimate.
        """
        from django.utils import timezone
        
        if not self.started_at or self.submitted_urls == 0 or self.status != 'in_progress':
            return None
        
        now = timezone.now()
        elapsed_seconds = (now - self.started_at).total_seconds()
        
        urls_remaining = self.total_urls - self.submitted_urls
        if urls_remaining <= 0:
            return 0
        
        avg_time_per_url = elapsed_seconds / self.submitted_urls
        estimated_remaining = int(avg_time_per_url * urls_remaining)
        
        return estimated_remaining
    
    def get_error_summary(self):
        """
        Parse error log and return summary statistics.
        Returns dict with error counts by type.
        """
        try:
            errors = json.loads(self.error_log) if self.error_log else []
            if not errors:
                return {}
            
            error_types = {}
            for error in errors:
                error_type = error.get('type', 'unknown')
                error_types[error_type] = error_types.get(error_type, 0) + 1
            
            return error_types
        except json.JSONDecodeError:
            return {'parse_error': 1}
    
    def mark_as_completed(self):
        """Mark task as completed with timestamp"""
        from django.utils import timezone
        self.status = 'completed'
        self.completed_at = timezone.now()
        self.save(update_fields=['status', 'completed_at', 'updated_at'])
    
    def mark_as_failed(self, error_message=None):
        """Mark task as failed with optional error message"""
        from django.utils import timezone
        self.status = 'failed'
        self.completed_at = timezone.now()
        
        if error_message:
            errors = json.loads(self.error_log) if self.error_log else []
            errors.append({
                'type': 'task_failure',
                'message': str(error_message),
                'timestamp': timezone.now().isoformat()
            })
            self.error_log = json.dumps(errors)
        
        self.save(update_fields=['status', 'completed_at', 'error_log', 'updated_at'])
    
    def add_error(self, url, error_message, error_type='api_error'):
        """Add an error to the error log"""
        from django.utils import timezone
        errors = json.loads(self.error_log) if self.error_log else []
        errors.append({
            'url': url,
            'type': error_type,
            'message': str(error_message),
            'timestamp': timezone.now().isoformat()
        })
        self.error_log = json.dumps(errors)
        self.save(update_fields=['error_log', 'updated_at'])
    
    def get_success_rate(self):
        """Calculate success rate percentage"""
        if self.submitted_urls == 0:
            return 0
        return round((self.successful_urls / self.submitted_urls) * 100, 2)