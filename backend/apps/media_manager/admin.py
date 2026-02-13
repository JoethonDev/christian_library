from django.contrib import admin
from django.utils.safestring import mark_safe
from django.urls import reverse
from django.http import HttpResponseRedirect
from django.contrib import messages
from django.utils.translation import gettext_lazy as _
from django.utils.html import format_html
from django.core.cache import cache
import logging

from .models import (
    ContentItem, VideoMeta, AudioMeta, PdfMeta, Tag, 
    ContentViewEvent, DailyContentViewSummary, SiteConfiguration
)
from .forms import ContentItemForm
from .services import ContentService, MediaUploadService

logger = logging.getLogger(__name__)


@admin.register(Tag)
class TagAdmin(admin.ModelAdmin):
    list_display = ['name_ar', 'name_en', 'color_preview', 'content_count', 'is_active', 'created_at']
    list_filter = ['is_active', 'created_at']
    search_fields = ['name_ar', 'name_en', 'description_ar']
    readonly_fields = ['id', 'content_count', 'created_at']
    
    fieldsets = (
        (_('Basic Information'), {
            'fields': ('name_ar', 'name_en', 'description_ar')
        }),
        (_('Appearance'), {
            'fields': ('color',)
        }),
        (_('Status'), {
            'fields': ('is_active',)
        }),
        (_('System Information'), {
            'fields': ('id', 'content_count', 'created_at'),
            'classes': ('collapse',),
        }),
    )
    
    def color_preview(self, obj):
        """Display color preview"""
        return format_html(
            '<div style="background-color: {}; width: 20px; height: 20px; '
            'border-radius: 3px; border: 1px solid #ccc;"></div>',
            obj.color
        )
    color_preview.short_description = _('Color')
    
    def content_count(self, obj):
        """Display number of content items using this tag"""
        count = obj.get_content_count()
        return format_html('<strong>{}</strong>', count)
    content_count.short_description = _('Content Count')
    
    actions = ['make_active', 'make_inactive']
    
    def make_active(self, request, queryset):
        """Bulk activate tags"""
        count = queryset.update(is_active=True)
        messages.success(request, _(f'{count} tags activated.'))
    make_active.short_description = _('Activate selected tags')
    
    def make_inactive(self, request, queryset):
        """Bulk deactivate tags"""
        count = queryset.update(is_active=False)
        messages.success(request, _(f'{count} tags deactivated.'))
    make_inactive.short_description = _('Deactivate selected tags')


class VideoMetaInline(admin.StackedInline):
    model = VideoMeta
    extra = 0
    fields = [
        'original_file', 'duration_display', 'file_size_display', 
        'processing_status', 'hls_paths_display',
        'r2_status_display', 'r2_files_display'
    ]
    readonly_fields = [
        'duration_display', 'file_size_display', 'processing_status', 
        'hls_paths_display', 'r2_status_display', 'r2_files_display'
    ]
    
    def duration_display(self, obj):
        """Display formatted duration"""
        if obj.duration_seconds:
            return obj.get_duration_formatted()
        return _('Unknown')
    duration_display.short_description = _('Duration')
    
    def file_size_display(self, obj):
        """Display file size in MB"""
        if obj.file_size_mb:
            return f"{obj.file_size_mb} MB"
        return _('Unknown')
    file_size_display.short_description = _('File Size')
    
    def r2_status_display(self, obj):
        """Display R2 upload status"""
        return obj.get_r2_status_display()
    r2_status_display.short_description = _('R2 Status')
    
    def r2_files_display(self, obj):
        """Display R2 files status"""
        files = []
        if obj.r2_original_file_url:
            files.append(f"<strong>Original:</strong> ✓")
        if obj.r2_hls_720p_url:
            files.append(f"<strong>720p HLS:</strong> ✓")
        if obj.r2_hls_480p_url:
            files.append(f"<strong>480p HLS:</strong> ✓")
        return mark_safe("<br>".join(files)) if files else "No R2 files"
    r2_files_display.short_description = _('R2 Files')
    
    def hls_paths_display(self, obj):
        """Display HLS paths with status"""
        if obj.is_ready_for_streaming():
            paths = []
            if obj.hls_720p_path:
                paths.append(f"<strong>720p:</strong> ✓")
            if obj.hls_480p_path:
                paths.append(f"<strong>480p:</strong> ✓")
            return mark_safe("<br>".join(paths))
        
        status_map = {
            'pending': _('Processing pending'),
            'processing': _('Currently processing'),
            'failed': _('Processing failed'),
        }
        return status_map.get(obj.processing_status, _('Not ready'))
    hls_paths_display.short_description = _('HLS Status')


class AudioMetaInline(admin.StackedInline):
    model = AudioMeta
    extra = 0
    fields = [
        'original_file', 'compression_display', 'duration_display', 
        'bitrate_display', 'processing_status',
        'r2_status_display', 'r2_files_display'
    ]
    readonly_fields = [
        'compression_display', 'duration_display', 'bitrate_display', 
        'processing_status', 'r2_status_display', 'r2_files_display'
    ]
    
    def compression_display(self, obj):
        """Display compression status"""
        if obj.compressed_file:
            return format_html(
                '<span style="color: green;">✓ {}</span>',
                _('Compressed')
            )
        return format_html(
            '<span style="color: orange;">⚠ {}</span>',
            _('Original only')
        )
    compression_display.short_description = _('Compression Status')
    
    def r2_status_display(self, obj):
        """Display R2 upload status"""
        return obj.get_r2_status_display()
    r2_status_display.short_description = _('R2 Status')
    
    def r2_files_display(self, obj):
        """Display R2 files status"""
        files = []
        if obj.r2_original_file_url:
            files.append(f"<strong>Original:</strong> ✓")
        if obj.r2_compressed_file_url:
            files.append(f"<strong>Compressed:</strong> ✓")
        return mark_safe("<br>".join(files)) if files else "No R2 files"
    r2_files_display.short_description = _('R2 Files')
    
    def duration_display(self, obj):
        """Display formatted duration"""
        if obj.duration_seconds:
            return obj.get_duration_formatted()
        return _('Unknown')
    duration_display.short_description = _('Duration')
    
    def bitrate_display(self, obj):
        """Display bitrate with units"""
        if obj.bitrate:
            return f"{obj.bitrate} kbps"
        return _('Unknown')
    bitrate_display.short_description = _('Bitrate')


class PdfMetaInline(admin.StackedInline):
    model = PdfMeta
    extra = 0
    fields = [
        'original_file', 'optimization_display', 'file_info_display', 
        'processing_status', 'r2_status_display', 'r2_files_display'
    ]
    readonly_fields = [
        'optimization_display', 'file_info_display', 'processing_status',
        'r2_status_display', 'r2_files_display'
    ]
    
    def optimization_display(self, obj):
        """Display optimization status"""
        if obj.optimized_file:
            return format_html(
                '<span style="color: green;">✓ {}</span>',
                _('Optimized')
            )
        return format_html(
            '<span style="color: orange;">⚠ {}</span>',
            _('Original only')
        )
    optimization_display.short_description = _('Optimization Status')
    
    def r2_status_display(self, obj):
        """Display R2 upload status"""
        return obj.get_r2_status_display()
    r2_status_display.short_description = _('R2 Status')
    
    def r2_files_display(self, obj):
        """Display R2 files status"""
        files = []
        if obj.r2_original_file_url:
            files.append(f"<strong>Original:</strong> ✓")
        if obj.r2_optimized_file_url:
            files.append(f"<strong>Optimized:</strong> ✓")
        return mark_safe("<br>".join(files)) if files else "No R2 files"
    r2_files_display.short_description = _('R2 Files')
    
    def file_info_display(self, obj):
        """Display file information"""
        info = []
        if obj.file_size_mb:
            info.append(f"{_('Size')}: {obj.file_size_mb} MB")
        if obj.page_count:
            info.append(f"{_('Pages')}: {obj.page_count}")
        return " | ".join(info) if info else _('Unknown')
    file_info_display.short_description = _('File Information')


@admin.register(ContentItem)
class ContentItemAdmin(admin.ModelAdmin):
    form = ContentItemForm
    list_display = ['title_display', 'content_type_display', 'tags_display', 'seo_status_display', 'status_display', 'is_active', 'created_at']
    list_filter = ['content_type', 'is_active', 'created_at', 'tags']
    search_fields = ['title_ar', 'title_en', 'description_ar', 'description_en', 'seo_keywords_ar', 'seo_keywords_en']
    readonly_fields = ['id', 'created_at', 'updated_at', 'content_url', 'seo_metadata_preview']
    
    fieldsets = (
        (_('Basic Information'), {
            'fields': ('title_ar', 'title_en', 'description_ar', 'description_en')
        }),
        (_('Classification'), {
            'fields': ('content_type', 'tags')
        }),
        (_('SEO Metadata (AI Generated)'), {
            'fields': (
                ('seo_title_ar', 'seo_title_en'),
                'tags_en', 
                ('seo_keywords_ar', 'seo_keywords_en'),
                ('seo_meta_description_ar', 'seo_meta_description_en'),
                'seo_title_suggestions',
                'seo_metadata_preview'
            ),
            'classes': ('collapse',),
        }),
        (_('Structured Data'), {
            'fields': ('structured_data',),
            'classes': ('collapse',),
            'description': _('Bilingual JSON-LD structured data. This field is automatically generated by AI.')
        }),
        (_('Status'), {
            'fields': ('is_active',)
        }),
        (_('System Information'), {
            'fields': ('id', 'created_at', 'updated_at', 'content_url'),
            'classes': ('collapse',),
        }),
    )
    
    filter_horizontal = ['tags']
    
    def get_inlines(self, request, obj):
        """Return appropriate inline based on content type"""
        if obj:
            if obj.content_type == 'video':
                return [VideoMetaInline]
            elif obj.content_type == 'audio':
                return [AudioMetaInline]
            elif obj.content_type == 'pdf':
                return [PdfMetaInline]
        return []
    
    def title_display(self, obj):
        """Display title with fallback"""
        return obj.get_title()
    title_display.short_description = _('Title')
    title_display.admin_order_field = 'title_ar'
    
    def content_type_display(self, obj):
        """Display localized content type"""
        type_map = {
            'video': _('Video'),
            'audio': _('Audio'),
            'pdf': _('PDF'),
        }
        return type_map.get(obj.content_type, obj.content_type)
    content_type_display.short_description = _('Type')
    content_type_display.admin_order_field = 'content_type'
    
    def tags_display(self, obj):
        """Display tags with colors"""
        tags = obj.tags.filter(is_active=True)
        if tags:
            tag_html = []
            for tag in tags:
                tag_html.append(
                    f'<span style="background-color: {tag.color}; color: white; '
                    f'padding: 2px 6px; border-radius: 3px; font-size: 11px; '
                    f'margin-right: 3px;">{tag.get_name()}</span>'
                )
            return format_html(''.join(tag_html))
        return format_html('<span style="color: gray;">%s</span>' % _('No tags'))
    tags_display.short_description = _('Tags')
    tags_display.allow_tags = True
    
    def status_display(self, obj):
        """Display processing status with visual indicators"""
        try:
            meta = obj.get_meta_object()
            if not meta:
                return format_html('<span style="color: gray;">-</span>')
            
            status_colors = {
                'pending': 'orange',
                'processing': 'blue',
                'completed': 'green',
                'failed': 'red',
            }
            
            status_labels = {
                'pending': _('Pending'),
                'processing': _('Processing'),
                'completed': _('Ready'),
                'failed': _('Failed'),
            }
            
            color = status_colors.get(meta.processing_status, 'gray')
            label = status_labels.get(meta.processing_status, meta.processing_status)
            
            return format_html(
                '<span style="color: {}; font-weight: bold;">● {}</span>',
                color,
                label
            )
        except Exception:
            return format_html('<span style="color: gray;">-</span>')
    status_display.short_description = _('Status')
    
    def content_url(self, obj):
        """Display content URL for frontend"""
        if obj.pk:
            url = obj.get_absolute_url()
            return format_html('<a href="{}" target="_blank">{}</a>', url, _('View Content'))
        return '-'
    content_url.short_description = _('Content URL')
    
    def get_queryset(self, request):
        """Optimize queryset with select_related"""
        return super().get_queryset(request).prefetch_related('tags')
    
    def save_model(self, request, obj, form, change):
        """Custom save with logging"""
        action = 'updated' if change else 'created'
        super().save_model(request, obj, form, change)
        
        logger.info(f"Content {action} by {request.user.username}: {obj.get_title()}")
        
        # Clear relevant caches
        cache.delete('content_stats')
        
        # Show success message
        messages.success(
            request,
            _(f'Content item "{obj.get_title()}" has been {action} successfully.')
        )
    
    def seo_status_display(self, obj):
        """Display SEO metadata status"""
        if obj.has_seo_metadata():
            keyword_count = len(obj.seo_keywords_ar) + len(obj.seo_keywords_en)
            return format_html(
                '<span style="color: green; font-weight: bold;">✓ SEO Ready</span><br>'
                '<small>{} keywords</small>',
                keyword_count
            )
        else:
            return format_html(
                '<span style="color: orange;">⚠ SEO Pending</span><br>'
                '<small><a href="#" onclick="generateSEO({});">Generate</a></small>',
                obj.pk
            )
    seo_status_display.short_description = _('SEO Status')
    seo_status_display.allow_tags = True
    
    def seo_metadata_preview(self, obj):
        """Display SEO metadata preview for admin"""
        if not obj.has_seo_metadata():
            return format_html(
                '<div style="padding: 10px; background: #f9f9f9; border-radius: 4px;">'
                '<p><strong>No SEO metadata generated yet</strong></p>'
                '<p><em>Upload media files and they will be automatically processed by Gemini AI</em></p>'
                '</div>'
            )
        
        html_parts = []
        
        # Keywords
        if obj.seo_keywords_ar:
            html_parts.append(f'<h4>Arabic Keywords ({len(obj.seo_keywords_ar)})</h4>')
            html_parts.append(f'<p>{", ".join(obj.seo_keywords_ar[:10])}{"..." if len(obj.seo_keywords_ar) > 10 else ""}</p>')
        
        if obj.seo_keywords_en:
            html_parts.append(f'<h4>English Keywords ({len(obj.seo_keywords_en)})</h4>')
            html_parts.append(f'<p>{", ".join(obj.seo_keywords_en[:10])}{"..." if len(obj.seo_keywords_en) > 10 else ""}</p>')
        
        # Meta descriptions
        if obj.seo_meta_description_ar:
            html_parts.append(f'<h4>Arabic Meta Description</h4>')
            html_parts.append(f'<p><em>"{obj.seo_meta_description_ar}"</em> ({len(obj.seo_meta_description_ar)} chars)</p>')
        
        if obj.seo_meta_description_en:
            html_parts.append(f'<h4>English Meta Description</h4>')
            html_parts.append(f'<p><em>"{obj.seo_meta_description_en}"</em> ({len(obj.seo_meta_description_en)} chars)</p>')
        
        # Title suggestions
        if obj.seo_title_suggestions:
            html_parts.append(f'<h4>Title Suggestions</h4>')
            html_parts.append('<ul>')
            for title in obj.seo_title_suggestions:
                html_parts.append(f'<li>{title}</li>')
            html_parts.append('</ul>')
        
        # Structured data
        if obj.structured_data:
            html_parts.append(f'<h4>Structured Data</h4>')
            html_parts.append(f'<p>Schema Type: <code>{obj.structured_data.get("@type", "Unknown")}</code></p>')
            html_parts.append(f'<p>Fields: {", ".join(obj.structured_data.keys())}</p>')
        
        return format_html(
            '<div style="max-width: 600px; font-size: 12px;">{}</div>',
            ''.join(html_parts)
        )
    seo_metadata_preview.short_description = _('SEO Metadata Preview')
    seo_metadata_preview.allow_tags = True

    actions = ['make_active', 'make_inactive', 'reprocess_media', 'generate_seo_metadata']
    
    def make_active(self, request, queryset):
        """Bulk activate content"""
        count = queryset.update(is_active=True)
        messages.success(request, _(f'{count} content items activated.'))
        cache.delete('content_stats')
    make_active.short_description = _('Activate selected content')
    
    def make_inactive(self, request, queryset):
        """Bulk deactivate content"""
        count = queryset.update(is_active=False)
        messages.success(request, _(f'{count} content items deactivated.'))
        cache.delete('content_stats')
    make_inactive.short_description = _('Deactivate selected content')
    
    def reprocess_media(self, request, queryset):
        """Reprocess selected media items"""
        count = 0
        for obj in queryset:
            try:
                meta = obj.get_meta_object()
                if meta:
                    # Queue for reprocessing based on type
                    if obj.content_type == 'video':
                        from core.tasks.media_processing import process_video_to_hls
                        process_video_to_hls.delay(str(obj.id))
                    elif obj.content_type == 'audio':
                        from core.tasks.media_processing import process_audio_compression
                        process_audio_compression.delay(str(obj.id))
                    elif obj.content_type == 'pdf':
                        from core.tasks.media_processing import process_pdf_optimization
                        process_pdf_optimization.delay(str(obj.id))
                    count += 1
            except Exception as e:
                logger.error(f"Error reprocessing {obj.id}: {str(e)}")
                
        if count > 0:
            messages.success(request, _(f'{count} items queued for reprocessing.'))
        else:
            messages.warning(request, _('No items could be queued for reprocessing.'))
    reprocess_media.short_description = _('Reprocess selected media')
    
    def generate_seo_metadata(self, request, queryset):
        """Generate SEO metadata for selected items"""
        count = 0
        for obj in queryset:
            try:
                # Check if media file exists
                meta = obj.get_meta_object()
                if meta and hasattr(meta, 'original_file') and meta.original_file:
                    obj.generate_seo_metadata_async()
                    count += 1
                else:
                    messages.warning(request, _(f'No media file found for "{obj.get_title()}"'))
            except Exception as e:
                logger.error(f"Error queuing SEO generation for {obj.id}: {str(e)}")
                messages.error(request, _(f'Error queuing SEO for "{obj.get_title()}": {str(e)}'))
                
        if count > 0:
            messages.success(request, _(f'{count} items queued for SEO metadata generation.'))
    generate_seo_metadata.short_description = _('Generate SEO metadata')


# Register individual meta models for direct access if needed
@admin.register(VideoMeta)
class VideoMetaAdmin(admin.ModelAdmin):
    list_display = ['content_item', 'duration_display', 'processing_status', 'is_ready']
    list_filter = ['processing_status']
    readonly_fields = ['content_item', 'duration_seconds', 'file_size_mb', 'hls_720p_path', 'hls_480p_path']
    
    def duration_display(self, obj):
        return obj.get_duration_formatted()
    duration_display.short_description = _('Duration')
    
    def is_ready(self, obj):
        return obj.is_ready_for_streaming()
    is_ready.short_description = _('Ready for Streaming')
    is_ready.boolean = True


@admin.register(AudioMeta)
class AudioMetaAdmin(admin.ModelAdmin):
    list_display = ['content_item', 'duration_display', 'bitrate', 'processing_status', 'is_ready']
    list_filter = ['processing_status']
    readonly_fields = ['content_item', 'duration_seconds', 'file_size_mb']
    
    def duration_display(self, obj):
        return obj.get_duration_formatted()
    duration_display.short_description = _('Duration')
    
    def is_ready(self, obj):
        return obj.is_ready_for_playback()
    is_ready.short_description = _('Ready for Playback')
    is_ready.boolean = True


@admin.register(PdfMeta)
class PdfMetaAdmin(admin.ModelAdmin):
    list_display = ['content_item', 'file_size_mb', 'page_count', 'processing_status', 'is_ready']
    list_filter = ['processing_status']
    readonly_fields = ['content_item', 'file_size_mb', 'page_count']
    
    def is_ready(self, obj):
        return obj.is_ready_for_viewing()
    is_ready.short_description = _('Ready for Viewing')
    is_ready.boolean = True


@admin.register(ContentViewEvent)
class ContentViewEventAdmin(admin.ModelAdmin):
    """Admin interface for ContentViewEvent"""
    list_display = ['content_type', 'content_id', 'timestamp', 'ip_address', 'short_user_agent']
    list_filter = ['content_type', 'timestamp']
    search_fields = ['content_id', 'ip_address', 'user_agent']
    readonly_fields = ['content_type', 'content_id', 'timestamp', 'user_agent', 'ip_address', 'referrer']
    date_hierarchy = 'timestamp'
    
    def short_user_agent(self, obj):
        """Display shortened user agent"""
        if len(obj.user_agent) > 50:
            return obj.user_agent[:50] + '...'
        return obj.user_agent
    short_user_agent.short_description = _('User Agent')
    
    def has_add_permission(self, request):
        """Disable manual creation of view events"""
        return False
    
    def has_change_permission(self, request, obj=None):
        """Make view events read-only"""
        return False


@admin.register(DailyContentViewSummary)
class DailyContentViewSummaryAdmin(admin.ModelAdmin):
    """Admin interface for DailyContentViewSummary"""
    list_display = ['date', 'content_type', 'content_id', 'view_count']
    list_filter = ['content_type', 'date']
    search_fields = ['content_id']
    readonly_fields = ['content_type', 'content_id', 'date', 'view_count']
    date_hierarchy = 'date'
    ordering = ['-date', '-view_count']
    
    def has_add_permission(self, request):
        """Disable manual creation of summaries"""
        return False
    
    def has_change_permission(self, request, obj=None):
        """Make summaries read-only"""
        return False


@admin.register(SiteConfiguration)
class SiteConfigurationAdmin(admin.ModelAdmin):
    list_display = ['site_name_en', 'site_name_ar', 'updated_at']
    fieldsets = (
        (_('Global Branding'), {
            'fields': (('site_name_en', 'site_name_ar'), 'logo_url', 'website_url')
        }),
        (_('Global SEO'), {
            'fields': ('description_en', 'description_ar')
        }),
        (_('Structured Data (Organization)'), {
            'fields': ('structured_data',),
            'classes': ('collapse',),
        }),
    )
    
    def has_add_permission(self, request):
        # Only allow one instance
        if self.model.objects.exists():
            return False
        return super().has_add_permission(request)

    def has_delete_permission(self, request, obj=None):
        # Don't allow deletion
        return False
