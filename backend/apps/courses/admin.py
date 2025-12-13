from django.contrib import admin
from django.utils.translation import gettext_lazy as _
from django.utils.safestring import mark_safe
from django.utils.html import format_html
from django.db.models import Count, Q
from django.contrib import messages
from django.core.cache import cache
import logging

from .models import Course, Module, Tag
from .services import CourseService, ModuleService

logger = logging.getLogger(__name__)


class ModuleInline(admin.TabularInline):
    model = Module
    extra = 0
    fields = ['title_ar', 'title_en', 'order', 'is_active', 'content_count']
    readonly_fields = ['content_count']
    ordering = ['order']
    
    def content_count(self, obj):
        """Display content count for module"""
        if obj.pk:
            count = obj.contentitem_set.filter(is_active=True).count()
            return format_html(
                '<span style="color: {};">{} {}</span>',
                'green' if count > 0 else 'gray',
                count,
                _('items')
            )
        return '-'
    content_count.short_description = _('Content Items')


@admin.register(Course)
class CourseAdmin(admin.ModelAdmin):
    list_display = ['title_display', 'category_display', 'module_count', 'content_count', 'is_active', 'created_at']
    list_filter = ['category', 'is_active', 'created_at']
    search_fields = ['title_ar', 'title_en', 'description_ar', 'description_en']
    ordering = ['-created_at']
    readonly_fields = ['id', 'created_at', 'updated_at', 'course_url', 'statistics_display']
    inlines = [ModuleInline]
    
    fieldsets = (
        (_('Basic Information'), {
            'fields': ('title_ar', 'title_en', 'category', 'is_active')
        }),
        (_('Description'), {
            'fields': ('description_ar', 'description_en'),
            'classes': ('wide',)
        }),
        (_('System Information'), {
            'fields': ('id', 'created_at', 'updated_at', 'course_url', 'statistics_display'),
            'classes': ('collapse',)
        })
    )
    
    def get_queryset(self, request):
        """Optimize queryset with annotations"""
        return super().get_queryset(request).annotate(
            module_count=Count('modules', filter=Q(modules__is_active=True)),
            content_count=Count('modules__contentitem', filter=Q(
                modules__contentitem__is_active=True
            ))
        )
    
    def title_display(self, obj):
        """Display title with fallback"""
        return obj.get_title()
    title_display.short_description = _('Title')
    title_display.admin_order_field = 'title_ar'
    
    def category_display(self, obj):
        """Display localized category"""
        category_map = {
            'theology': _('Theology'),
            'bible_study': _('Bible Study'),
            'history': _('History'),
            'apologetics': _('Apologetics'),
            'christian_living': _('Christian Living'),
            'liturgy': _('Liturgy'),
        }
        return category_map.get(obj.category, obj.category)
    category_display.short_description = _('Category')
    category_display.admin_order_field = 'category'
    
    def module_count(self, obj):
        """Display module count with link"""
        count = getattr(obj, 'module_count', 0)
        if count > 0:
            return format_html(
                '<a href="/admin/courses/module/?course__id__exact={}" style="color: blue;">{}</a>',
                obj.pk,
                count
            )
        return format_html('<span style="color: gray;">{}</span>', count)
    module_count.short_description = _('Modules')
    module_count.admin_order_field = 'module_count'
    
    def content_count(self, obj):
        """Display total content count"""
        count = getattr(obj, 'content_count', 0)
        color = 'green' if count > 0 else 'gray'
        return format_html('<span style="color: {};">{}</span>', color, count)
    content_count.short_description = _('Content Items')
    content_count.admin_order_field = 'content_count'
    
    def course_url(self, obj):
        """Display course URL for frontend"""
        if obj.pk:
            url = obj.get_absolute_url()
            return format_html('<a href="{}" target="_blank">{}</a>', url, _('View Course'))
        return '-'
    course_url.short_description = _('Course URL')
    
    def statistics_display(self, obj):
        """Display detailed course statistics"""
        if not obj.pk:
            return '-'
            
        try:
            stats = CourseService.get_course_statistics(obj)
            return format_html(
                """
                <div style="font-size: 12px;">
                    <strong>{modules_label}:</strong> {modules}<br>
                    <strong>{videos_label}:</strong> {videos}<br>
                    <strong>{audios_label}:</strong> {audios}<br>
                    <strong>{pdfs_label}:</strong> {pdfs}<br>
                    <strong>{processing_label}:</strong> {processing}
                </div>
                """,
                modules_label=_('Modules'),
                modules=stats.get('total_modules', 0),
                videos_label=_('Videos'),
                videos=stats.get('video_count', 0),
                audios_label=_('Audio Files'),
                audios=stats.get('audio_count', 0),
                pdfs_label=_('PDF Files'),
                pdfs=stats.get('pdf_count', 0),
                processing_label=_('Processing'),
                processing=stats.get('processing_count', 0)
            )
        except Exception:
            return _('Error loading statistics')
    statistics_display.short_description = _('Statistics')
    
    def save_model(self, request, obj, form, change):
        """Custom save with logging and cache invalidation"""
        action = 'updated' if change else 'created'
        super().save_model(request, obj, form, change)
        
        logger.info(f"Course {action} by {request.user.username}: {obj.get_title()}")
        
        # Clear relevant caches
        cache.delete('course_list')
        cache.delete(f'course_{obj.pk}')
        
        messages.success(
            request,
            _(f'Course "{obj.get_title()}" has been {action} successfully.')
        )
    
    actions = ['make_active', 'make_inactive', 'export_course_data']
    
    def make_active(self, request, queryset):
        """Bulk activate courses"""
        count = queryset.update(is_active=True)
        messages.success(request, _(f'{count} courses activated.'))
        cache.delete('course_list')
    make_active.short_description = _('Activate selected courses')
    
    def make_inactive(self, request, queryset):
        """Bulk deactivate courses"""
        count = queryset.update(is_active=False)
        messages.success(request, _(f'{count} courses deactivated.'))
        cache.delete('course_list')
    make_inactive.short_description = _('Deactivate selected courses')
    
    def export_course_data(self, request, queryset):
        """Export course data"""
        # This would be implemented with actual export functionality
        messages.info(request, _('Course export functionality will be implemented.'))
    export_course_data.short_description = _('Export course data')


@admin.register(Module)
class ModuleAdmin(admin.ModelAdmin):
    list_display = ['title_display', 'course_display', 'order', 'content_count', 'is_active', 'created_at']
    list_filter = ['course', 'is_active', 'created_at']
    search_fields = ['title_ar', 'title_en', 'course__title_ar', 'course__title_en']
    ordering = ['course', 'order']
    readonly_fields = ['id', 'created_at', 'updated_at', 'module_url']
    list_editable = ['order', 'is_active']
    
    fieldsets = (
        (_('Basic Information'), {
            'fields': ('title_ar', 'title_en', 'course', 'order', 'is_active')
        }),
        (_('Description'), {
            'fields': ('description_ar', 'description_en'),
            'classes': ('wide',)
        }),
        (_('System Information'), {
            'fields': ('id', 'created_at', 'updated_at', 'module_url'),
            'classes': ('collapse',)
        })
    )
    
    def get_queryset(self, request):
        """Optimize queryset with select_related and annotations"""
        return super().get_queryset(request).select_related('course').annotate(
            content_count=Count('contentitem', filter=Q(contentitem__is_active=True))
        )
    
    def title_display(self, obj):
        """Display title with fallback"""
        return obj.get_title()
    title_display.short_description = _('Title')
    title_display.admin_order_field = 'title_ar'
    
    def course_display(self, obj):
        """Display course title"""
        return obj.course.get_title()
    course_display.short_description = _('Course')
    course_display.admin_order_field = 'course__title_ar'
    
    def content_count(self, obj):
        """Display content count with link"""
        count = getattr(obj, 'content_count', 0)
        if count > 0:
            return format_html(
                '<a href="/admin/media_manager/contentitem/?module__id__exact={}" style="color: blue;">{}</a>',
                obj.pk,
                count
            )
        return format_html('<span style="color: gray;">{}</span>', count)
    content_count.short_description = _('Content Items')
    content_count.admin_order_field = 'content_count'
    
    def module_url(self, obj):
        """Display module URL for frontend"""
        if obj.pk:
            url = obj.get_absolute_url()
            return format_html('<a href="{}" target="_blank">{}</a>', url, _('View Module'))
        return '-'
    module_url.short_description = _('Module URL')
    
    def save_model(self, request, obj, form, change):
        """Custom save with cache invalidation"""
        action = 'updated' if change else 'created'
        super().save_model(request, obj, form, change)
        
        logger.info(f"Module {action} by {request.user.username}: {obj.get_title()}")
        
        # Clear relevant caches
        cache.delete('course_list')
        cache.delete(f'course_{obj.course.pk}')
        
        messages.success(
            request,
            _(f'Module "{obj.get_title()}" has been {action} successfully.')
        )
    
    actions = ['make_active', 'make_inactive', 'reorder_modules']
    
    def make_active(self, request, queryset):
        """Bulk activate modules"""
        count = queryset.update(is_active=True)
        messages.success(request, _(f'{count} modules activated.'))
    make_active.short_description = _('Activate selected modules')
    
    def make_inactive(self, request, queryset):
        """Bulk deactivate modules"""
        count = queryset.update(is_active=False)
        messages.success(request, _(f'{count} modules deactivated.'))
    make_inactive.short_description = _('Deactivate selected modules')
    
    def reorder_modules(self, request, queryset):
        """Reorder modules within their courses"""
        messages.info(request, _('Module reordering functionality will be implemented.'))
    reorder_modules.short_description = _('Reorder modules')


@admin.register(Tag)
class TagAdmin(admin.ModelAdmin):
    list_display = ['name_display', 'color_display', 'usage_count', 'is_active', 'created_at']
    list_filter = ['is_active', 'created_at']
    search_fields = ['name_ar', 'name_en']
    ordering = ['name_ar']
    readonly_fields = ['id', 'created_at']
    list_editable = ['is_active']
    
    fieldsets = (
        (_('Basic Information'), {
            'fields': ('name_ar', 'name_en', 'color', 'is_active')
        }),
        (_('System Information'), {
            'fields': ('id', 'created_at'),
            'classes': ('collapse',)
        })
    )
    
    def get_queryset(self, request):
        """Add usage count annotation"""
        return super().get_queryset(request).annotate(
            usage_count=Count('contentitem')
        )
    
    def name_display(self, obj):
        """Display name with fallback"""
        return obj.get_name()
    name_display.short_description = _('Name')
    name_display.admin_order_field = 'name_ar'
    
    def color_display(self, obj):
        """Display color with visual indicator"""
        if obj.color:
            return format_html(
                '<div style="display: inline-block; width: 20px; height: 20px; background-color: {}; '
                'border: 1px solid #ccc; border-radius: 3px; margin-right: 5px;"></div> {}',
                obj.color,
                obj.color
            )
        return '-'
    color_display.short_description = _('Color')
    
    def usage_count(self, obj):
        """Display usage count with link"""
        count = getattr(obj, 'usage_count', 0)
        if count > 0:
            return format_html(
                '<a href="/admin/media_manager/contentitem/?tags__id__exact={}" style="color: blue;">{}</a>',
                obj.pk,
                count
            )
        return format_html('<span style="color: gray;">{}</span>', count)
    usage_count.short_description = _('Used in Content')
    usage_count.admin_order_field = 'usage_count'
    
    def save_model(self, request, obj, form, change):
        """Custom save with logging"""
        action = 'updated' if change else 'created'
        super().save_model(request, obj, form, change)
        
        logger.info(f"Tag {action} by {request.user.username}: {obj.get_name()}")
        
        # Clear tag-related caches
        cache.delete('tag_list')
        
        messages.success(
            request,
            _(f'Tag "{obj.get_name()}" has been {action} successfully.')
        )
    
    actions = ['make_active', 'make_inactive', 'merge_tags']
    
    def make_active(self, request, queryset):
        """Bulk activate tags"""
        count = queryset.update(is_active=True)
        messages.success(request, _(f'{count} tags activated.'))
        cache.delete('tag_list')
    make_active.short_description = _('Activate selected tags')
    
    def make_inactive(self, request, queryset):
        """Bulk deactivate tags"""
        count = queryset.update(is_active=False)
        messages.success(request, _(f'{count} tags deactivated.'))
        cache.delete('tag_list')
    make_inactive.short_description = _('Deactivate selected tags')
    
    def merge_tags(self, request, queryset):
        """Merge duplicate tags"""
        messages.info(request, _('Tag merging functionality will be implemented.'))
    merge_tags.short_description = _('Merge selected tags')