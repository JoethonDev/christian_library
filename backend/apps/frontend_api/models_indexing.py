"""
Google Indexing Queue Model
Tracks individual URL submissions to Google Indexing API with quota management
"""
from django.db import models
from django.utils.translation import gettext_lazy as _
from django.utils import timezone
from django.core.cache import cache
import uuid


class GoogleIndexingQueue(models.Model):
    """
    Queue for managing Google Indexing API submissions with quota tracking.
    Ensures we don't exceed 200 requests per day limit.
    """
    
    STATUS_CHOICES = [
        ('pending', _('Pending')),
        ('processing', _('Processing')),
        ('success', _('Success')),
        ('failed', _('Failed')),
        ('quota_exceeded', _('Quota Exceeded')),
        ('invalid', _('Invalid - Missing SEO/Metadata')),
    ]
    
    ACTION_CHOICES = [
        ('URL_UPDATED', _('URL Updated')),
        ('URL_DELETED', _('URL Deleted')),
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    
    # Content reference
    content_item = models.ForeignKey(
        'media_manager.ContentItem',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='indexing_queue',
        verbose_name=_('Content Item'),
        help_text=_('Reference to content item (null if deleted)')
    )
    
    # URL and action
    url = models.URLField(
        max_length=500,
        verbose_name=_('URL'),
        help_text=_('Full URL to submit to Google')
    )
    action = models.CharField(
        max_length=20,
        choices=ACTION_CHOICES,
        default='URL_UPDATED',
        verbose_name=_('Action')
    )
    
    # Status tracking
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='pending',
        db_index=True,
        verbose_name=_('Status')
    )
    
    # Priority (higher = more important)
    priority = models.IntegerField(
        default=5,
        verbose_name=_('Priority'),
        help_text=_('Higher priority items processed first (1-10)')
    )
    
    # Retry tracking
    retry_count = models.IntegerField(
        default=0,
        verbose_name=_('Retry Count')
    )
    max_retries = models.IntegerField(
        default=3,
        verbose_name=_('Max Retries')
    )
    
    # Error tracking
    error_message = models.TextField(
        blank=True,
        verbose_name=_('Error Message')
    )
    error_code = models.CharField(
        max_length=50,
        blank=True,
        verbose_name=_('Error Code')
    )
    
    # Google API response
    google_response = models.JSONField(
        null=True,
        blank=True,
        verbose_name=_('Google Response'),
        help_text=_('Full response from Google Indexing API')
    )
    
    # Timestamps
    created_at = models.DateTimeField(
        auto_now_add=True,
        db_index=True,
        verbose_name=_('Created At')
    )
    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name=_('Updated At')
    )
    processed_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name=_('Processed At')
    )
    scheduled_for = models.DateTimeField(
        null=True,
        blank=True,
        db_index=True,
        verbose_name=_('Scheduled For'),
        help_text=_('When to process this item (for quota management)')
    )
    
    class Meta:
        verbose_name = _('Google Indexing Queue Item')
        verbose_name_plural = _('Google Indexing Queue Items')
        ordering = ['-priority', 'created_at']
        indexes = [
            models.Index(fields=['status', '-priority', 'created_at']),
            models.Index(fields=['scheduled_for', 'status']),
            models.Index(fields=['-created_at']),
        ]
    
    def __str__(self):
        return f"{self.action} - {self.url} [{self.status}]"
    
    def mark_as_success(self, response=None):
        """Mark item as successfully processed"""
        self.status = 'success'
        self.processed_at = timezone.now()
        if response:
            self.google_response = response
        self.save(update_fields=['status', 'processed_at', 'google_response', 'updated_at'])
    
    def mark_as_failed(self, error_message, error_code='', response=None):
        """Mark item as failed with error details"""
        self.status = 'failed'
        self.error_message = error_message
        self.error_code = error_code
        self.processed_at = timezone.now()
        if response:
            self.google_response = response
        self.save(update_fields=['status', 'error_message', 'error_code', 'processed_at', 'google_response', 'updated_at'])
    
    def mark_as_quota_exceeded(self, next_available_time=None):
        """Mark item as quota exceeded and reschedule"""
        self.status = 'quota_exceeded'
        if next_available_time:
            self.scheduled_for = next_available_time
        self.save(update_fields=['status', 'scheduled_for', 'updated_at'])
    
    def increment_retry(self):
        """Increment retry count"""
        self.retry_count += 1
        self.save(update_fields=['retry_count', 'updated_at'])
    
    @classmethod
    def get_pending_count(cls):
        """Get count of pending items"""
        return cls.objects.filter(status='pending').count()
    
    @classmethod
    def get_daily_quota_used(cls):
        """Get number of requests submitted today"""
        today = timezone.now().date()
        return cls.objects.filter(
            processed_at__date=today,
            status='success'
        ).count()
    
    @classmethod
    def get_daily_quota_remaining(cls):
        """Get remaining quota for today (200 max)"""
        return max(0, 200 - cls.get_daily_quota_used())
    
    @classmethod
    def can_submit_today(cls):
        """Check if we can submit more requests today"""
        return cls.get_daily_quota_remaining() > 0


class GoogleIndexingQuota(models.Model):
    """
    Daily quota tracking for Google Indexing API.
    Singleton model to track usage and reset daily.
    """
    
    date = models.DateField(
        unique=True,
        db_index=True,
        verbose_name=_('Date')
    )
    requests_used = models.IntegerField(
        default=0,
        verbose_name=_('Requests Used')
    )
    requests_failed = models.IntegerField(
        default=0,
        verbose_name=_('Requests Failed')
    )
    last_reset_at = models.DateTimeField(
        auto_now=True,
        verbose_name=_('Last Reset At')
    )
    
    class Meta:
        verbose_name = _('Google Indexing Quota')
        verbose_name_plural = _('Google Indexing Quotas')
        ordering = ['-date']
    
    def __str__(self):
        return f"Quota {self.date}: {self.requests_used}/200"
    
    @classmethod
    def get_today_quota(cls):
        """Get or create today's quota record"""
        today = timezone.now().date()
        quota, created = cls.objects.get_or_create(
            date=today,
            defaults={'requests_used': 0, 'requests_failed': 0}
        )
        return quota
    
    @classmethod
    def increment_usage(cls, success=True):
        """Increment today's usage counter"""
        quota = cls.get_today_quota()
        if success:
            quota.requests_used += 1
        else:
            quota.requests_failed += 1
        quota.save(update_fields=['requests_used', 'requests_failed', 'last_reset_at'])
        
        # Also cache for fast access
        cache_key = f'google_indexing_quota_{quota.date}'
        cache.set(cache_key, quota.requests_used, 3600 * 24)  # Cache for 24 hours
    
    @classmethod
    def get_remaining_quota(cls):
        """Get remaining quota for today"""
        quota = cls.get_today_quota()
        return max(0, 200 - quota.requests_used)
    
    @classmethod
    def has_quota_available(cls):
        """Check if quota is available"""
        return cls.get_remaining_quota() > 0
