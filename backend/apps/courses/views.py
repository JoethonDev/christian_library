"""
Enhanced views for courses app with service layer integration and caching.
"""

from django.shortcuts import get_object_or_404, render
from django.views.generic import ListView, DetailView, View
from django.http import JsonResponse, Http404
from django.core.paginator import Paginator
from django.db.models import Q
from django.utils.translation import gettext as _
from django.views.decorators.cache import cache_page
from django.utils.decorators import method_decorator
from django.views.decorators.vary import vary_on_headers
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import AllowAny
import logging

from .models import Course, Module
from .services import CourseService, ModuleService
from core.utils.cache_utils import cache_page_with_user, CacheKeys

logger = logging.getLogger(__name__)


# Frontend Views

@method_decorator(cache_page_with_user(timeout=1800), name='dispatch')
@method_decorator(vary_on_headers('Accept-Language'), name='dispatch')
class CourseListView(ListView):
    """List all active courses with filtering"""
    model = Course
    template_name = 'courses/course_list.html'
    context_object_name = 'courses'
    paginate_by = 12
    
    def get_queryset(self):
        category = self.request.GET.get('category')
        search = self.request.GET.get('search')
        return CourseService.get_active_courses(category=category, search=search)
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['categories'] = CourseService.get_categories_with_counts()
        context['selected_category'] = self.request.GET.get('category', 'all')
        context['search_query'] = self.request.GET.get('search', '')
        return context


@method_decorator(cache_page_with_user(timeout=3600), name='dispatch')
@method_decorator(vary_on_headers('Accept-Language'), name='dispatch')
class CourseDetailView(DetailView):
    """Course detail with modules and content"""
    model = Course
    template_name = 'courses/course_detail.html'
    context_object_name = 'course'
    
    def get_object(self, queryset=None):
        pk = self.kwargs.get('pk')
        course = CourseService.get_course_with_content(pk)
        if not course:
            raise Http404(_("Course not found"))
        return course
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['modules'] = ModuleService.get_course_modules(self.object.id, include_content=True)
        context['statistics'] = CourseService.get_course_statistics(self.object)
        return context


class CourseCategoryView(ListView):
    """Courses filtered by category"""
    model = Course
    template_name = 'courses/course_category.html'
    context_object_name = 'courses'
    paginate_by = 12
    
    def get_queryset(self):
        category = self.kwargs.get('category')
        return CourseService.get_active_courses(category=category)
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['category'] = self.kwargs.get('category')
        context['categories'] = CourseService.get_categories_with_counts()
        return context


class CourseSearchView(ListView):
    """Course search results"""
    model = Course
    template_name = 'courses/course_search.html'
    context_object_name = 'courses'
    paginate_by = 12
    
    def get_queryset(self):
        search_query = self.request.GET.get('q', '').strip()
        if not search_query:
            return Course.objects.none()
        return CourseService.get_active_courses(search=search_query)
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['search_query'] = self.request.GET.get('q', '')
        return context


@method_decorator(cache_page_with_user(timeout=3600), name='dispatch')
class ModuleDetailView(DetailView):
    """Module detail with content"""
    model = Module
    template_name = 'courses/module_detail.html'
    context_object_name = 'module'
    
    def get_queryset(self):
        return Module.objects.select_related('course').prefetch_related(
            'contentitem_set__tags',
            'contentitem_set__videometa',
            'contentitem_set__audiometa', 
            'contentitem_set__pdfmeta'
        ).filter(is_active=True)
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['course'] = self.object.course
        context['content_items'] = self.object.contentitem_set.filter(is_active=True).order_by('created_at')
        context['statistics'] = ModuleService.get_module_statistics(self.object)
        return context


# API Views

class CourseListAPIView(APIView):
    """API endpoint for course list"""
    permission_classes = [AllowAny]
    
    def get(self, request):
        try:
            category = request.GET.get('category')
            search = request.GET.get('search')
            page = int(request.GET.get('page', 1))
            page_size = int(request.GET.get('page_size', 20))
            
            courses = CourseService.get_active_courses(category=category, search=search)
            
            # Pagination
            paginator = Paginator(courses, page_size)
            page_obj = paginator.get_page(page)
            
            # Serialize course data
            course_data = []
            for course in page_obj:
                stats = CourseService.get_course_statistics(course)
                course_data.append({
                    'id': course.id,
                    'title': course.get_title(),
                    'description': course.get_description(),
                    'category': course.category,
                    'created_at': course.created_at.isoformat(),
                    'module_count': stats.get('total_modules', 0),
                    'content_count': stats.get('total_content', 0),
                    'url': course.get_absolute_url(),
                })
            
            return Response({
                'results': course_data,
                'count': paginator.count,
                'page': page,
                'pages': paginator.num_pages,
                'has_next': page_obj.has_next(),
                'has_previous': page_obj.has_previous(),
            })
            
        except Exception as e:
            logger.error(f"Error in CourseListAPIView: {str(e)}")
            return Response(
                {'error': _('Failed to retrieve courses')},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class CourseDetailAPIView(APIView):
    """API endpoint for course detail"""
    permission_classes = [AllowAny]
    
    def get(self, request, pk):
        try:
            course = CourseService.get_course_with_content(pk)
            if not course:
                return Response(
                    {'error': _('Course not found')},
                    status=status.HTTP_404_NOT_FOUND
                )
            
            # Get modules with content
            modules = ModuleService.get_course_modules(course.id, include_content=True)
            modules_data = []
            
            for module in modules:
                content_items = []
                for item in module.contentitem_set.filter(is_active=True):
                    content_items.append({
                        'id': item.id,
                        'title': item.get_title(),
                        'type': item.content_type,
                        'created_at': item.created_at.isoformat(),
                        'url': item.get_absolute_url(),
                    })
                
                modules_data.append({
                    'id': module.id,
                    'title': module.get_title(),
                    'description': module.get_description(),
                    'order': module.order,
                    'content_items': content_items,
                })
            
            statistics = CourseService.get_course_statistics(course)
            
            return Response({
                'id': course.id,
                'title': course.get_title(),
                'description': course.get_description(),
                'category': course.category,
                'created_at': course.created_at.isoformat(),
                'modules': modules_data,
                'statistics': statistics,
                'url': course.get_absolute_url(),
            })
            
        except Exception as e:
            logger.error(f"Error in CourseDetailAPIView: {str(e)}")
            return Response(
                {'error': _('Failed to retrieve course')},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class ModuleListAPIView(APIView):
    """API endpoint for course modules"""
    permission_classes = [AllowAny]
    
    def get(self, request, course_id):
        try:
            modules = ModuleService.get_course_modules(course_id, include_content=True)
            
            modules_data = []
            for module in modules:
                stats = ModuleService.get_module_statistics(module)
                modules_data.append({
                    'id': module.id,
                    'title': module.get_title(),
                    'description': module.get_description(),
                    'order': module.order,
                    'statistics': stats,
                    'url': module.get_absolute_url(),
                })
            
            return Response({'modules': modules_data})
            
        except Exception as e:
            logger.error(f"Error in ModuleListAPIView: {str(e)}")
            return Response(
                {'error': _('Failed to retrieve modules')},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class ModuleDetailAPIView(APIView):
    """API endpoint for module detail"""
    permission_classes = [AllowAny]
    
    def get(self, request, pk):
        try:
            module = get_object_or_404(Module.objects.select_related('course'), pk=pk, is_active=True)
            
            content_items = []
            for item in module.contentitem_set.filter(is_active=True):
                content_items.append({
                    'id': item.id,
                    'title': item.get_title(),
                    'description': item.get_description(),
                    'type': item.content_type,
                    'created_at': item.created_at.isoformat(),
                    'url': item.get_absolute_url(),
                })
            
            statistics = ModuleService.get_module_statistics(module)
            
            return Response({
                'id': module.id,
                'title': module.get_title(),
                'description': module.get_description(),
                'course': {
                    'id': module.course.id,
                    'title': module.course.get_title(),
                    'url': module.course.get_absolute_url(),
                },
                'order': module.order,
                'content_items': content_items,
                'statistics': statistics,
                'url': module.get_absolute_url(),
            })
            
        except Exception as e:
            logger.error(f"Error in ModuleDetailAPIView: {str(e)}")
            return Response(
                {'error': _('Failed to retrieve module')},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class CategoryListAPIView(APIView):
    """API endpoint for course categories"""
    permission_classes = [AllowAny]
    
    def get(self, request):
        try:
            categories = CourseService.get_categories_with_counts()
            return Response({'categories': categories})
            
        except Exception as e:
            logger.error(f"Error in CategoryListAPIView: {str(e)}")
            return Response(
                {'error': _('Failed to retrieve categories')},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class CourseSearchAPIView(APIView):
    """API endpoint for course search"""
    permission_classes = [AllowAny]
    
    def get(self, request):
        try:
            query = request.GET.get('q', '').strip()
            if not query:
                return Response({'results': [], 'count': 0})
            
            courses = CourseService.get_active_courses(search=query)
            
            # Limit results for search
            courses = courses[:20]  # First 20 results
            
            results = []
            for course in courses:
                results.append({
                    'id': course.id,
                    'title': course.get_title(),
                    'description': course.get_description(),
                    'category': course.category,
                    'url': course.get_absolute_url(),
                })
            
            return Response({
                'results': results,
                'count': len(results),
                'query': query,
            })
            
        except Exception as e:
            logger.error(f"Error in CourseSearchAPIView: {str(e)}")
            return Response(
                {'error': _('Search failed')},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )