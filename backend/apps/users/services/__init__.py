from django.db import models, transaction
from django.core.cache import cache
from django.db.models import Count, Sum, Q
from django.contrib.auth import authenticate
from typing import Dict, List, Optional, Any
import logging

from ..models import User

logger = logging.getLogger(__name__)


class UserService:
    """Service layer for User operations"""
    
    @staticmethod
    def get_content_managers() -> models.QuerySet:
        """Get active content managers"""
        cache_key = "content_managers"
        
        managers = cache.get(cache_key)
        if managers is not None:
            return managers
        
        managers = User.objects.filter(
            is_content_manager=True, 
            is_active=True
        ).select_related()
        
        # Cache for 1 hour
        cache.set(cache_key, managers, 3600)
        return managers
    
    @staticmethod
    def get_user_statistics(user: User) -> Dict[str, Any]:
        """Get comprehensive user statistics"""
        cache_key = f"user_stats_{user.id}"
        
        stats = cache.get(cache_key)
        if stats is not None:
            return stats
        
        # Get content counts
        content_items = user.contentitem_set.filter(is_active=True)
        courses = user.course_set.filter(is_active=True) if hasattr(user, 'course_set') else []
        modules = user.module_set.filter(is_active=True) if hasattr(user, 'module_set') else []
        
        # Calculate file sizes (this would need to be implemented based on your file fields)
        total_upload_size = 0
        for item in content_items:
            meta = item.get_meta_object()
            if meta and hasattr(meta, 'file_size_mb') and meta.file_size_mb:
                total_upload_size += meta.file_size_mb
        
        stats = {
            'content_count': content_items.count(),
            'course_count': len(courses),
            'module_count': len(modules),
            'video_count': content_items.filter(content_type='video').count(),
            'audio_count': content_items.filter(content_type='audio').count(),
            'pdf_count': content_items.filter(content_type='pdf').count(),
            'total_upload_size_mb': total_upload_size,
        }
        
        # Cache for 30 minutes
        cache.set(cache_key, stats, 1800)
        return stats
    
    @staticmethod
    def create_user(username: str, email: str, password: str, **extra_fields) -> User:
        """Create new user with validation"""
        with transaction.atomic():
            user = User.objects.create_user(
                username=username,
                email=email,
                password=password,
                **extra_fields
            )
            
            logger.info(f"New user created: {username}")
            
            # Clear relevant caches
            cache.delete_many(['user_list'])
            if extra_fields.get('is_content_manager'):
                cache.delete('content_managers')
            
            return user
    
    @staticmethod
    def authenticate_user(username: str, password: str) -> Optional[User]:
        """Authenticate user with logging"""
        user = authenticate(username=username, password=password)
        
        if user:
            logger.info(f"Successful authentication: {username}")
        else:
            logger.warning(f"Failed authentication attempt: {username}")
            
        return user
    
    @staticmethod
    def update_user_profile(user: User, **kwargs) -> User:
        """Update user profile with cache invalidation"""
        with transaction.atomic():
            # Track if content manager status changed
            content_manager_changed = 'is_content_manager' in kwargs and \
                                    kwargs['is_content_manager'] != user.is_content_manager
            
            for field, value in kwargs.items():
                setattr(user, field, value)
            user.save()
            
            # Clear caches
            cache.delete(f'user_stats_{user.id}')
            if content_manager_changed:
                cache.delete('content_managers')
            
            logger.info(f"User profile updated: {user.username}")
            return user
    
    @staticmethod
    def get_user_content_summary(user: User) -> Dict[str, Any]:
        """Get summary of user's content"""
        if not user.is_content_manager:
            return {}
        
        cache_key = f"user_content_summary_{user.id}"
        summary = cache.get(cache_key)
        if summary is not None:
            return summary
        
        # Get recent content
        recent_content = user.contentitem_set.filter(is_active=True).order_by('-created_at')[:5]
        
        # Get processing status counts
        content_meta_status = {}
        for item in user.contentitem_set.filter(is_active=True):
            meta = item.get_meta_object()
            if meta:
                status = getattr(meta, 'processing_status', 'unknown')
                content_meta_status[status] = content_meta_status.get(status, 0) + 1
        
        summary = {
            'recent_content': [
                {
                    'title': item.get_title(),
                    'type': item.content_type,
                    'created': item.created_at,
                    'url': item.get_absolute_url()
                } for item in recent_content
            ],
            'processing_status': content_meta_status,
            'total_active_content': user.contentitem_set.filter(is_active=True).count()
        }
        
        # Cache for 15 minutes
        cache.set(cache_key, summary, 900)
        return summary
    
    @staticmethod
    def deactivate_user_content(user: User, reason: str = 'User deactivated') -> int:
        """Deactivate all user content when user is deactivated"""
        with transaction.atomic():
            count = user.contentitem_set.filter(is_active=True).update(is_active=False)
            
            if count > 0:
                logger.info(f"Deactivated {count} content items for user {user.username}: {reason}")
                
                # Clear related caches
                cache.delete_many([
                    f'user_stats_{user.id}',
                    f'user_content_summary_{user.id}',
                    'content_stats'
                ])
            
            return count
    
    @staticmethod
    def get_user_by_username_or_email(identifier: str) -> Optional[User]:
        """Get user by username or email"""
        try:
            if '@' in identifier:
                return User.objects.get(email=identifier, is_active=True)
            else:
                return User.objects.get(username=identifier, is_active=True)
        except User.DoesNotExist:
            return None
    
    @staticmethod
    def get_active_users_with_content() -> models.QuerySet:
        """Get active users who have created content"""
        return User.objects.filter(
            is_active=True,
            contentitem__isnull=False
        ).annotate(
            content_count=Count('contentitem', filter=Q(contentitem__is_active=True))
        ).filter(content_count__gt=0).distinct()
    
    @staticmethod
    def validate_user_permissions(user: User, action: str, resource: str = None) -> bool:
        """Validate user permissions for specific actions"""
        if not user.is_active:
            return False
        
        # Superuser has all permissions
        if user.is_superuser:
            return True
        
        # Staff users have admin access
        if action == 'admin_access' and user.is_staff:
            return True
        
        # Content managers can manage content
        if action in ['create_content', 'edit_content', 'upload_media'] and user.is_content_manager:
            return True
        
        # Regular users can view public content
        if action in ['view_content', 'browse_courses']:
            return True
        
        return False