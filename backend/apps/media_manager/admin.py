from django.contrib import admin
from django.utils.safestring import mark_safe
from django.urls import reverse
from django.http import HttpResponseRedirect
from django.contrib import messages
from django.utils.translation import gettext_lazy as _
from django.utils.html import format_html
from django.core.cache import cache
import logging

from .models import ContentItem, VideoMeta, AudioMeta, PdfMeta, Tag
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
    fields = ['original_file', 'duration_display', 'file_size_display', 'processing_status', 'hls_paths_display']
    readonly_fields = ['duration_display', 'file_size_display', 'processing_status', 'hls_paths_display']
    
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
    fields = ['original_file', 'compression_display', 'duration_display', 'bitrate_display', 'processing_status']
    readonly_fields = ['compression_display', 'duration_display', 'bitrate_display', 'processing_status']
    
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
    fields = ['original_file', 'optimization_display', 'file_info_display', 'processing_status']
    readonly_fields = ['optimization_display', 'file_info_display', 'processing_status']
    
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
    list_display = ['title_display', 'content_type_display', 'tags_display', 'status_display', 'is_active', 'created_at']
    list_filter = ['content_type', 'is_active', 'created_at', 'tags']
    search_fields = ['title_ar', 'title_en', 'description_ar', 'description_en']
    readonly_fields = ['id', 'created_at', 'updated_at', 'content_url']
    
    fieldsets = (
        (_('Basic Information'), {
            'fields': ('title_ar', 'title_en', 'description_ar', 'description_en')
        }),
        (_('Classification'), {
            'fields': ('content_type', 'tags')
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
    
    actions = ['make_active', 'make_inactive', 'reprocess_media']
    
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