from django.db import models, transaction
from django.core.cache import cache
from django.utils.translation import get_language
from django.db.models import Q, Count, Prefetch
from typing import Dict, List, Optional, Any
import logging

from ..models import Course, Module, Tag

logger = logging.getLogger(__name__)


class CourseService:
    """Service layer for Course operations"""
    
    @staticmethod
    def get_active_courses(category: Optional[str] = None, search: Optional[str] = None) -> models.QuerySet:
        """Get active courses with optional filtering"""
        cache_key = f"courses_active_{category or 'all'}_{search or 'all'}_{get_language()}"
        
        # Try cache first
        courses = cache.get(cache_key)
        if courses is not None:
            return courses
        
        # Build queryset
        queryset = Course.objects.select_related().prefetch_related(
            'modules__contentitem_set'
        ).filter(is_active=True)
        
        if category:
            queryset = queryset.filter(category=category)
        
        if search:
            lang = get_language()
            if lang == 'ar':
                queryset = queryset.filter(
                    Q(title_ar__icontains=search) | 
                    Q(description_ar__icontains=search)
                )
            else:
                queryset = queryset.filter(
                    Q(title_en__icontains=search) | 
                    Q(description_en__icontains=search) |
                    Q(title_ar__icontains=search) | 
                    Q(description_ar__icontains=search)
                )
        
        # Annotate with counts
        queryset = queryset.annotate(
            module_count=Count('modules', filter=Q(modules__is_active=True)),
            content_count=Count('modules__contentitem', filter=Q(
                modules__contentitem__is_active=True
            ))
        ).order_by('-created_at')
        
        # Cache for 15 minutes
        cache.set(cache_key, queryset, 900)
        return queryset
    
    @staticmethod
    def get_course_with_content(course_id: int) -> Optional[Course]:
        """Get course with all related content optimized"""
        cache_key = f"course_detail_{course_id}_{get_language()}"
        
        course = cache.get(cache_key)
        if course is not None:
            return course
        
        try:
            course = Course.objects.select_related().prefetch_related(
                Prefetch('modules', queryset=Module.objects.filter(is_active=True).prefetch_related(
                    'contentitem_set__tags'
                ).order_by('order')),
                'modules__contentitem_set__videometa',
                'modules__contentitem_set__audiometa',
                'modules__contentitem_set__pdfmeta'
            ).get(id=course_id, is_active=True)
            
            # Cache for 30 minutes
            cache.set(cache_key, course, 1800)
            return course
            
        except Course.DoesNotExist:
            return None
    
    @staticmethod
    def get_course_statistics(course: Course) -> Dict[str, Any]:
        """Get comprehensive course statistics"""
        cache_key = f"course_stats_{course.id}"
        
        stats = cache.get(cache_key)
        if stats is not None:
            return stats
        
        # Get modules and content counts
        modules = course.modules.filter(is_active=True)
        total_modules = modules.count()
        
        content_items = course.modules.filter(is_active=True).values_list(
            'contentitem__content_type', 'contentitem__videometa__processing_status',
            'contentitem__audiometa__processing_status', 'contentitem__pdfmeta__processing_status'
        ).filter(contentitem__is_active=True)
        
        # Count by type
        video_count = sum(1 for item in content_items if item[0] == 'video')
        audio_count = sum(1 for item in content_items if item[0] == 'audio')
        pdf_count = sum(1 for item in content_items if item[0] == 'pdf')
        
        # Count processing status
        processing_count = sum(1 for item in content_items 
                             if item[1] in ['pending', 'processing'] or
                                item[2] in ['pending', 'processing'] or
                                item[3] in ['pending', 'processing'])
        
        stats = {
            'total_modules': total_modules,
            'video_count': video_count,
            'audio_count': audio_count,
            'pdf_count': pdf_count,
            'total_content': video_count + audio_count + pdf_count,
            'processing_count': processing_count
        }
        
        # Cache for 10 minutes
        cache.set(cache_key, stats, 600)
        return stats
    
    @staticmethod
    def create_course(title_ar: str, title_en: str, category: str, 
                     description_ar: str = '', description_en: str = '', 
                     user = None) -> Course:
        """Create new course with logging"""
        with transaction.atomic():
            course = Course.objects.create(
                title_ar=title_ar,
                title_en=title_en,
                category=category,
                description_ar=description_ar,
                description_en=description_en
            )
            
            if user:
                logger.info(f"Course created by {user.username}: {course.get_title()}")
            
            # Clear caches
            cache.delete_many(['course_list', 'courses_active_all_all_ar', 'courses_active_all_all_en'])
            
            return course
    
    @staticmethod
    def update_course(course: Course, **kwargs) -> Course:
        """Update course with cache invalidation"""
        with transaction.atomic():
            for field, value in kwargs.items():
                setattr(course, field, value)
            course.save()
            
            # Clear related caches
            cache.delete_many([
                'course_list',
                f'course_detail_{course.id}_ar',
                f'course_detail_{course.id}_en',
                f'course_stats_{course.id}'
            ])
            
            return course
    
    @staticmethod
    def get_categories_with_counts() -> List[Dict[str, Any]]:
        """Get all categories with course counts"""
        cache_key = f"course_categories_{get_language()}"
        
        categories = cache.get(cache_key)
        if categories is not None:
            return categories
        
        from django.db.models import Case, When, IntegerField
        
        # Get counts for each category
        category_counts = Course.objects.filter(is_active=True).values('category').annotate(
            count=Count('id')
        ).order_by('category')
        
        # Localize category names
        category_names = {
            'theology': {'ar': 'اللاهوت', 'en': 'Theology'},
            'bible_study': {'ar': 'دراسة الكتاب المقدس', 'en': 'Bible Study'},
            'history': {'ar': 'التاريخ', 'en': 'History'},
            'apologetics': {'ar': 'علم الدفاعيات', 'en': 'Apologetics'},
            'christian_living': {'ar': 'الحياة المسيحية', 'en': 'Christian Living'},
            'liturgy': {'ar': 'الطقوس', 'en': 'Liturgy'},
        }
        
        lang = get_language()
        categories = []
        
        for item in category_counts:
            category_key = item['category']
            name = category_names.get(category_key, {}).get(lang, category_key)
            categories.append({
                'key': category_key,
                'name': name,
                'count': item['count']
            })
        
        # Cache for 1 hour
        cache.set(cache_key, categories, 3600)
        return categories


class ModuleService:
    """Service layer for Module operations"""
    
    @staticmethod
    def get_course_modules(course_id: int, include_content: bool = True) -> models.QuerySet:
        """Get modules for a course with optional content"""
        cache_key = f"course_modules_{course_id}_{include_content}_{get_language()}"
        
        modules = cache.get(cache_key)
        if modules is not None:
            return modules
        
        queryset = Module.objects.filter(
            course_id=course_id, 
            is_active=True
        ).select_related('course')
        
        if include_content:
            queryset = queryset.prefetch_related(
                'contentitem_set__tags',
                'contentitem_set__videometa',
                'contentitem_set__audiometa',
                'contentitem_set__pdfmeta'
            )
        
        modules = queryset.order_by('order')
        
        # Cache for 30 minutes
        cache.set(cache_key, modules, 1800)
        return modules
    
    @staticmethod
    def create_module(course: Course, title_ar: str, title_en: str,
                     description_ar: str = '', description_en: str = '',
                     order: Optional[int] = None, user = None) -> Module:
        """Create new module with proper ordering"""
        with transaction.atomic():
            if order is None:
                # Get next order number
                last_order = Module.objects.filter(course=course).aggregate(
                    models.Max('order')
                )['order__max'] or 0
                order = last_order + 1
            
            module = Module.objects.create(
                course=course,
                title_ar=title_ar,
                title_en=title_en,
                description_ar=description_ar,
                description_en=description_en,
                order=order
            )
            
            if user:
                logger.info(f"Module created by {user.username}: {module.get_title()}")
            
            # Clear caches
            cache.delete_many([
                f'course_detail_{course.id}_ar',
                f'course_detail_{course.id}_en',
                f'course_modules_{course.id}_True_ar',
                f'course_modules_{course.id}_True_en',
                f'course_stats_{course.id}'
            ])
            
            return module
    
    @staticmethod
    def reorder_modules(course: Course, module_orders: Dict[int, int]) -> bool:
        """Reorder modules within a course"""
        try:
            with transaction.atomic():
                for module_id, new_order in module_orders.items():
                    Module.objects.filter(
                        id=module_id, 
                        course=course
                    ).update(order=new_order)
                
                # Clear caches
                cache.delete_many([
                    f'course_detail_{course.id}_ar',
                    f'course_detail_{course.id}_en',
                    f'course_modules_{course.id}_True_ar',
                    f'course_modules_{course.id}_True_en'
                ])
                
                return True
                
        except Exception as e:
            logger.error(f"Error reordering modules for course {course.id}: {str(e)}")
            return False
    
    @staticmethod
    def get_module_statistics(module: Module) -> Dict[str, Any]:
        """Get module statistics"""
        cache_key = f"module_stats_{module.id}"
        
        stats = cache.get(cache_key)
        if stats is not None:
            return stats
        
        content_items = module.contentitem_set.filter(is_active=True)
        
        stats = {
            'total_content': content_items.count(),
            'video_count': content_items.filter(content_type='video').count(),
            'audio_count': content_items.filter(content_type='audio').count(),
            'pdf_count': content_items.filter(content_type='pdf').count(),
        }
        
        # Cache for 15 minutes
        cache.set(cache_key, stats, 900)
        return stats


class TagService:
    """Service layer for Tag operations"""
    
    @staticmethod
    def get_popular_tags(limit: int = 20) -> models.QuerySet:
        """Get most popular tags by usage"""
        cache_key = f"popular_tags_{limit}_{get_language()}"
        
        tags = cache.get(cache_key)
        if tags is not None:
            return tags
        
        tags = Tag.objects.filter(is_active=True).annotate(
            usage_count=Count('contentitem')
        ).filter(usage_count__gt=0).order_by('-usage_count', 'name_ar')[:limit]
        
        # Cache for 1 hour
        cache.set(cache_key, tags, 3600)
        return tags
    
    @staticmethod
    def search_tags(query: str, limit: int = 10) -> models.QuerySet:
        """Search tags by name"""
        lang = get_language()
        
        if lang == 'ar':
            return Tag.objects.filter(
                Q(name_ar__icontains=query) & Q(is_active=True)
            ).order_by('name_ar')[:limit]
        else:
            return Tag.objects.filter(
                Q(name_en__icontains=query) | Q(name_ar__icontains=query) & Q(is_active=True)
            ).order_by('name_en')[:limit]
    
    @staticmethod
    def create_tag(name_ar: str, name_en: str, color: str = '#007cba', user = None) -> Tag:
        """Create new tag with validation"""
        with transaction.atomic():
            tag = Tag.objects.create(
                name_ar=name_ar,
                name_en=name_en,
                color=color
            )
            
            if user:
                logger.info(f"Tag created by {user.username}: {tag.get_name()}")
            
            # Clear caches
            cache.delete('tag_list')
            
            return tag