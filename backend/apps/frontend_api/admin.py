from django.contrib import admin
from .models_indexing import GoogleIndexingQueue, GoogleIndexingQuota, GoogleIndexedUrl


@admin.register(GoogleIndexingQueue)
class GoogleIndexingQueueAdmin(admin.ModelAdmin):
    list_display = [
        'url', 'action', 'status', 'priority', 'retry_count', 
        'created_at', 'processed_at'
    ]
    list_filter = ['status', 'action', 'priority']
    search_fields = ['url', 'error_message']
    readonly_fields = ['created_at', 'updated_at', 'processed_at', 'google_response']
    ordering = ['-priority', 'created_at']


@admin.register(GoogleIndexingQuota)
class GoogleIndexingQuotaAdmin(admin.ModelAdmin):
    list_display = ['date', 'requests_used', 'requests_failed', 'last_reset_at']
    readonly_fields = ['last_reset_at']
    ordering = ['-date']


@admin.register(GoogleIndexedUrl)
class GoogleIndexedUrlAdmin(admin.ModelAdmin):
    list_display = [
        'url', 'url_type', 'language', 'status', 
        'needs_reindex', 'submission_count', 'last_submitted_at'
    ]
    list_filter = ['status', 'url_type', 'language', 'needs_reindex']
    search_fields = ['url', 'last_error']
    readonly_fields = [
        'created_at', 'updated_at', 'last_submitted_at', 
        'last_indexed_at', 'last_google_response'
    ]
    ordering = ['-updated_at']
    
    fieldsets = (
        ('URL Information', {
            'fields': ('url', 'url_type', 'language', 'content_item', 'tag')
        }),
        ('Status', {
            'fields': ('status', 'needs_reindex', 'submission_count')
        }),
        ('Timestamps', {
            'fields': ('last_submitted_at', 'last_indexed_at', 'created_at', 'updated_at')
        }),
        ('Error Tracking', {
            'fields': ('last_error', 'last_error_code', 'last_google_response'),
            'classes': ('collapse',)
        }),
    )