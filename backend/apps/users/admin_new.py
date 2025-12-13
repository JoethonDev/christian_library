from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.utils.translation import gettext_lazy as _
from django.utils.safestring import mark_safe
from django.utils.html import format_html
from django.db.models import Count, Q
from django.contrib import messages
from django.core.cache import cache
from django.urls import reverse
import logging

from .models import User
from .services import UserService

logger = logging.getLogger(__name__)


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = ['username', 'name_display', 'email', 'role_display', 'content_stats', 'last_login', 'is_active']
    list_filter = ['is_content_manager', 'is_staff', 'is_active', 'date_joined', 'last_login']
    search_fields = ['username', 'email', 'first_name', 'last_name', 'phone']
    readonly_fields = ['date_joined', 'last_login', 'user_statistics', 'content_management_link']
    ordering = ['-date_joined']
    
    fieldsets = (
        (_('Authentication'), {
            'fields': ('username', 'email', 'password')
        }),
        (_('Personal Information'), {
            'fields': ('first_name', 'last_name', 'phone'),
            'classes': ('wide',)
        }),
        (_('Permissions'), {
            'fields': ('is_active', 'is_staff', 'is_superuser', 'is_content_manager', 'groups', 'user_permissions'),
            'classes': ('collapse',)
        }),
        (_('Important Dates'), {
            'fields': ('last_login', 'date_joined'),
            'classes': ('collapse',)
        }),
        (_('Statistics & Management'), {
            'fields': ('user_statistics', 'content_management_link'),
            'classes': ('collapse',)
        })
    )
    
    add_fieldsets = (
        (_('Required Information'), {
            'classes': ('wide',),
            'fields': ('username', 'email', 'password1', 'password2'),
        }),
        (_('Personal Information'), {
            'classes': ('wide',),
            'fields': ('first_name', 'last_name', 'phone'),
        }),
        (_('Permissions'), {
            'classes': ('wide',),
            'fields': ('is_content_manager', 'is_staff'),
        }),
    )
    
    filter_horizontal = ('groups', 'user_permissions')
    
    def get_queryset(self, request):
        """Optimize queryset with content statistics"""
        return super().get_queryset(request).annotate(
            content_count=Count('contentitem', filter=Q(contentitem__is_active=True)),
            course_count=Count('course', filter=Q(course__is_active=True)),
            module_count=Count('module', filter=Q(module__is_active=True))
        )
    
    def name_display(self, obj):
        """Display full name with fallback to username"""
        full_name = obj.get_full_name().strip()
        if full_name:
            return full_name
        return format_html('<em>{}</em>', obj.username)
    name_display.short_description = _('Name')
    name_display.admin_order_field = 'first_name'
    
    def role_display(self, obj):
        """Display user role with visual indicators"""
        roles = []
        
        if obj.is_superuser:
            roles.append(format_html(
                '<span style="color: red; font-weight: bold;">● {}</span>', 
                _('Superuser')
            ))
        elif obj.is_staff:
            roles.append(format_html(
                '<span style="color: blue; font-weight: bold;">● {}</span>', 
                _('Staff')
            ))
        
        if obj.is_content_manager:
            roles.append(format_html(
                '<span style="color: green; font-weight: bold;">● {}</span>', 
                _('Content Manager')
            ))
        
        if not roles:
            roles.append(format_html(
                '<span style="color: gray;">● {}</span>', 
                _('Regular User')
            ))
        
        return mark_safe(' '.join(roles))
    role_display.short_description = _('Role')
    
    def content_stats(self, obj):
        """Display content creation statistics"""
        content_count = getattr(obj, 'content_count', 0)
        course_count = getattr(obj, 'course_count', 0)
        module_count = getattr(obj, 'module_count', 0)
        
        if not any([content_count, course_count, module_count]):
            return format_html('<span style="color: gray;">-</span>')
        
        stats = []
        if course_count > 0:
            stats.append(f"{course_count} {_('courses')}")
        if module_count > 0:
            stats.append(f"{module_count} {_('modules')}")
        if content_count > 0:
            stats.append(f"{content_count} {_('content')}")
        
        return format_html(
            '<span style="font-size: 11px;">{}</span>', 
            ' | '.join(stats)
        )
    content_stats.short_description = _('Content Statistics')
    
    def user_statistics(self, obj):
        """Display detailed user statistics"""
        if not obj.pk:
            return '-'
        
        try:
            stats = UserService.get_user_statistics(obj)
            
            return format_html(
                """
                <div style="font-size: 12px; line-height: 1.4;">
                    <strong>{joined_label}:</strong> {joined}<br>
                    <strong>{last_active_label}:</strong> {last_active}<br>
                    <strong>{content_created_label}:</strong> {content_created}<br>
                    <strong>{courses_managed_label}:</strong> {courses_managed}<br>
                    <strong>{total_uploads_label}:</strong> {total_uploads} MB
                </div>
                """,
                joined_label=_('Member Since'),
                joined=obj.date_joined.strftime('%Y-%m-%d'),
                last_active_label=_('Last Active'),
                last_active=obj.last_login.strftime('%Y-%m-%d %H:%M') if obj.last_login else _('Never'),
                content_created_label=_('Content Created'),
                content_created=stats.get('content_count', 0),
                courses_managed_label=_('Courses Managed'),
                courses_managed=stats.get('course_count', 0),
                total_uploads_label=_('Total Uploads'),
                total_uploads=round(stats.get('total_upload_size_mb', 0), 1)
            )
        except Exception as e:
            logger.error(f"Error getting user statistics for {obj.username}: {str(e)}")
            return _('Error loading statistics')
    user_statistics.short_description = _('Detailed Statistics')
    
    def content_management_link(self, obj):
        """Display links to manage user's content"""
        if not obj.pk or not obj.is_content_manager:
            return '-'
        
        links = []
        
        # Link to user's courses
        courses_url = reverse('admin:courses_course_changelist') + f'?created_by__id__exact={obj.id}'
        links.append(f'<a href="{courses_url}" target="_blank">{_("Manage Courses")}</a>')
        
        # Link to user's content
        content_url = reverse('admin:media_manager_contentitem_changelist') + f'?created_by__id__exact={obj.id}'
        links.append(f'<a href="{content_url}" target="_blank">{_("Manage Content")}</a>')
        
        return format_html(' | '.join(links))
    content_management_link.short_description = _('Content Management')
    
    def save_model(self, request, obj, form, change):
        """Custom save with logging and cache invalidation"""
        action = 'updated' if change else 'created'
        
        # Check if content manager status changed
        content_manager_changed = False
        if change:
            old_obj = User.objects.get(pk=obj.pk)
            content_manager_changed = old_obj.is_content_manager != obj.is_content_manager
        
        super().save_model(request, obj, form, change)
        
        logger.info(f"User {action} by {request.user.username}: {obj.username}")
        
        if content_manager_changed:
            logger.info(f"Content manager status changed for {obj.username}: {obj.is_content_manager}")
            # Clear user-related caches
            cache.delete_many([
                'content_managers',
                f'user_stats_{obj.id}',
                'user_list'
            ])
        
        messages.success(
            request,
            _(f'User "{obj.username}" has been {action} successfully.')
        )
    
    def delete_model(self, request, obj):
        """Custom delete with content handling"""
        username = obj.username
        
        try:
            # Check if user has content
            content_count = obj.contentitem_set.filter(is_active=True).count()
            
            if content_count > 0:
                # Soft delete: deactivate instead of hard delete
                obj.is_active = False
                obj.save()
                logger.info(f"User soft-deleted by {request.user.username}: {username} (had {content_count} content items)")
                messages.warning(
                    request, 
                    _(f'User "{username}" has been deactivated because they have {content_count} content items. '
                      'Content remains available.')
                )
            else:
                # Hard delete if no content
                super().delete_model(request, obj)
                logger.info(f"User deleted by {request.user.username}: {username}")
                messages.success(request, _(f'User "{username}" has been deleted.'))
                
            # Clear caches
            cache.delete_many(['content_managers', 'user_list'])
            
        except Exception as e:
            logger.error(f"Error deleting user {obj.username}: {str(e)}")
            messages.error(request, _(f'Error deleting user: {str(e)}'))
    
    actions = ['activate_users', 'deactivate_users', 'make_content_managers', 'remove_content_manager_status']
    
    def activate_users(self, request, queryset):
        """Bulk activate users"""
        count = queryset.update(is_active=True)
        messages.success(request, _(f'{count} users activated.'))
        cache.delete('user_list')
    activate_users.short_description = _('Activate selected users')
    
    def deactivate_users(self, request, queryset):
        """Bulk deactivate users"""
        count = queryset.update(is_active=False)
        messages.success(request, _(f'{count} users deactivated.'))
        cache.delete('user_list')
    deactivate_users.short_description = _('Deactivate selected users')
    
    def make_content_managers(self, request, queryset):
        """Make users content managers"""
        count = queryset.update(is_content_manager=True)
        messages.success(request, _(f'{count} users made content managers.'))
        cache.delete('content_managers')
    make_content_managers.short_description = _('Make content managers')
    
    def remove_content_manager_status(self, request, queryset):
        """Remove content manager status"""
        count = queryset.update(is_content_manager=False)
        messages.success(request, _(f'{count} users no longer content managers.'))
        cache.delete('content_managers')
    remove_content_manager_status.short_description = _('Remove content manager status')
    
    def has_delete_permission(self, request, obj=None):
        """Restrict deletion based on content ownership"""
        if obj and obj.contentitem_set.filter(is_active=True).exists():
            # Only superusers can delete users with content
            return request.user.is_superuser
        return super().has_delete_permission(request, obj)