"""
Django Admin Customizations
Enhances the default Django admin with custom templates and functionality
"""
from django.contrib import admin
from django.contrib.admin.sites import AdminSite
from django.template.response import TemplateResponse
from django.urls import path
from apps.media_manager.models import ContentItem, Tag, VideoMeta, AudioMeta, PdfMeta
from apps.users.models import User
from apps.core.task_monitor import TaskMonitor


class CustomAdminSite(AdminSite):
    """Custom admin site with task monitoring"""
    site_header = 'Christian Library - Django Admin'
    site_title = 'Christian Library Admin'
    index_title = 'Django Administration'
    
    def index(self, request, extra_context=None):
        """
        Enhanced admin index with task monitoring
        """
        extra_context = extra_context or {}
        
        # Add task monitoring data
        try:
            task_stats = TaskMonitor.get_task_stats()
            active_tasks = TaskMonitor.get_active_tasks()
            extra_context.update({
                'task_stats': task_stats,
                'active_tasks': active_tasks[:5],  # Show 5 latest tasks
                'has_task_monitoring': True,
            })
        except Exception:
            extra_context['has_task_monitoring'] = False
        
        return super().index(request, extra_context)
    
    def get_urls(self):
        """Add custom URLs to admin"""
        urls = super().get_urls()
        custom_urls = [
            path('tasks/', self.task_monitor_view, name='admin_tasks'),
            path('tasks/<str:task_id>/', self.task_detail_view, name='admin_task_detail'),
        ]
        return custom_urls + urls
    
    def task_monitor_view(self, request):
        """Task monitoring view"""
        active_tasks = TaskMonitor.get_active_tasks()
        task_stats = TaskMonitor.get_task_stats()
        
        context = {
            'title': 'Background Task Monitor',
            'active_tasks': active_tasks,
            'task_stats': task_stats,
            'opts': {'app_label': 'admin_django'},
        }
        
        return TemplateResponse(
            request, 
            'admin_django/task_monitor.html', 
            context
        )
    
    def task_detail_view(self, request, task_id):
        """Individual task detail view"""
        task_details = TaskMonitor.get_task_details(task_id)
        
        context = {
            'title': f'Task Details: {task_id}',
            'task': task_details,
            'opts': {'app_label': 'admin_django'},
        }
        
        return TemplateResponse(
            request, 
            'admin_django/task_detail.html', 
            context
        )


# Create custom admin site instance
custom_admin_site = CustomAdminSite(name='custom_admin')

# Register models with enhanced admin
@admin.register(ContentItem, site=custom_admin_site)
class ContentItemAdmin(admin.ModelAdmin):
    list_display = ['title_ar', 'content_type', 'is_active', 'created_at']
    list_filter = ['content_type', 'is_active', 'created_at']
    search_fields = ['title_ar', 'title_en', 'description_ar']
    readonly_fields = ['id', 'created_at', 'updated_at', 'search_vector']
    
    fieldsets = (
        (None, {
            'fields': ('title_ar', 'title_en', 'content_type', 'is_active')
        }),
        ('Content', {
            'fields': ('description_ar', 'description_en', 'tags')
        }),
        ('SEO', {
            'fields': ('seo_keywords_ar', 'seo_keywords_en', 'seo_meta_description_ar', 'seo_meta_description_en'),
            'classes': ('collapse',)
        }),
        ('Search', {
            'fields': ('book_content', 'search_vector'),
            'classes': ('collapse',)
        }),
        ('Metadata', {
            'fields': ('id', 'created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )


@admin.register(Tag, site=custom_admin_site)
class TagAdmin(admin.ModelAdmin):
    list_display = ['name_ar', 'name_en', 'color', 'is_active', 'created_at']
    list_filter = ['is_active', 'created_at']
    search_fields = ['name_ar', 'name_en']


@admin.register(VideoMeta, site=custom_admin_site)
class VideoMetaAdmin(admin.ModelAdmin):
    list_display = ['content_item', 'processing_status', 'duration_seconds', 'file_size_mb']
    list_filter = ['processing_status', 'r2_upload_status']
    search_fields = ['content_item__title_ar', 'content_item__title_en']
    readonly_fields = ['file_size_mb', 'duration_seconds']


@admin.register(AudioMeta, site=custom_admin_site)
class AudioMetaAdmin(admin.ModelAdmin):
    list_display = ['content_item', 'processing_status', 'duration_seconds', 'file_size_mb']
    list_filter = ['processing_status', 'r2_upload_status']
    search_fields = ['content_item__title_ar', 'content_item__title_en']
    readonly_fields = ['file_size_mb', 'duration_seconds']


@admin.register(PdfMeta, site=custom_admin_site)
class PdfMetaAdmin(admin.ModelAdmin):
    list_display = ['content_item', 'processing_status', 'page_count', 'file_size_mb']
    list_filter = ['processing_status', 'r2_upload_status']
    search_fields = ['content_item__title_ar', 'content_item__title_en']
    readonly_fields = ['file_size_mb', 'page_count']


@admin.register(User, site=custom_admin_site)
class UserAdmin(admin.ModelAdmin):
    list_display = ['username', 'email', 'is_active', 'is_staff', 'date_joined']
    list_filter = ['is_active', 'is_staff', 'is_superuser', 'date_joined']
    search_fields = ['username', 'email', 'first_name', 'last_name']
    
    fieldsets = (
        (None, {
            'fields': ('username', 'password')
        }),
        ('Personal info', {
            'fields': ('first_name', 'last_name', 'email')
        }),
        ('Permissions', {
            'fields': ('is_active', 'is_staff', 'is_superuser', 'groups', 'user_permissions'),
        }),
        ('Important dates', {
            'fields': ('last_login', 'date_joined'),
            'classes': ('collapse',)
        }),
    )


# Replace default admin site
admin.site = custom_admin_site
admin.sites.site = custom_admin_site