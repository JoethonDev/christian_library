from django.urls import path, include
from . import views

app_name = 'courses'

# API patterns
api_patterns = [
    path('', views.CourseListAPIView.as_view(), name='api_list'),
    path('<int:pk>/', views.CourseDetailAPIView.as_view(), name='api_detail'),
    path('<int:course_id>/modules/', views.ModuleListAPIView.as_view(), name='api_modules'),
    path('modules/<int:pk>/', views.ModuleDetailAPIView.as_view(), name='api_module_detail'),
    path('categories/', views.CategoryListAPIView.as_view(), name='api_categories'),
    path('search/', views.CourseSearchAPIView.as_view(), name='api_search'),
]

# Frontend patterns
frontend_patterns = [
    path('', views.CourseListView.as_view(), name='list'),
    path('<int:pk>/', views.CourseDetailView.as_view(), name='detail'),
    path('<int:pk>/<slug:slug>/', views.CourseDetailView.as_view(), name='detail_slug'),
    path('category/<str:category>/', views.CourseCategoryView.as_view(), name='category'),
    path('search/', views.CourseSearchView.as_view(), name='search'),
    path('module/<int:pk>/', views.ModuleDetailView.as_view(), name='module_detail'),
]

urlpatterns = [
    path('api/', include(api_patterns)),
    path('', include(frontend_patterns)),
]