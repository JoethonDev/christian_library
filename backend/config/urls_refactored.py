from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.conf.urls.i18n import i18n_patterns
from django.http import HttpResponseRedirect
from django.urls import reverse
from django.views.i18n import set_language
from django.views.generic import RedirectView
from core.utils.cache_utils import cache_unless_authenticated
from django.views.decorators.cache import cache_page
import logging

logger = logging.getLogger(__name__)


@cache_unless_authenticated(timeout=300)
def redirect_to_custom_admin(request):
    """Redirect default admin to custom admin dashboard"""
    return HttpResponseRedirect(reverse('frontend_api:admin_dashboard'))


# Base URL patterns (non-internationalized)
urlpatterns = [
    # Admin URLs
    path('admin/', redirect_to_custom_admin, name='admin_redirect'),
    path('django-admin/', admin.site.urls, name='django_admin'),
    
    # API endpoints (non-internationalized for consistency)
    path('api/media/', include('apps.media_manager.urls', namespace='media_api')),
    path('api/courses/', include('apps.courses.urls', namespace='courses_api')),
    path('api/users/', include('apps.users.urls', namespace='users_api')),
    
    # System endpoints
    path('health/', include('apps.core.urls', namespace='core')),
    path('i18n/setlang/', set_language, name='set_language'),
    path('i18n/', include('django.conf.urls.i18n')),
    
    # Root redirect to default language
    path('', RedirectView.as_view(url='/ar/', permanent=False), name='root_redirect'),
]

# Internationalized URL patterns
urlpatterns += i18n_patterns(
    # Main application URLs
    path('', include('apps.frontend_api.urls', namespace='frontend')),
    
    # Course URLs
    path('courses/', include('apps.courses.urls', namespace='courses')),
    
    # Media URLs  
    path('media/', include('apps.media_manager.urls', namespace='media')),
    
    # User URLs
    path('users/', include('apps.users.urls', namespace='users')),
    
    prefix_default_language=True
)

# Error handling URLs (only in DEBUG mode)
if settings.DEBUG:
    # Development error pages
    from django.views.defaults import page_not_found, server_error, permission_denied, bad_request
    
    urlpatterns += [
        path('400/', bad_request, {'exception': Exception("Bad Request")}, name='400'),
        path('403/', permission_denied, {'exception': Exception("Permission Denied")}, name='403'),  
        path('404/', page_not_found, {'exception': Exception("Page not found")}, name='404'),
        path('500/', server_error, name='500'),
    ]
    
    # Serve media and static files in development
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
    
# Production static file handling
else:
    # In production, static files should be served by nginx/apache
    # But add these for completeness
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)


# Custom error handlers for production
handler400 = 'apps.core.views.custom_bad_request'
handler403 = 'apps.core.views.custom_permission_denied'  
handler404 = 'apps.core.views.custom_page_not_found'
handler500 = 'apps.core.views.custom_server_error'