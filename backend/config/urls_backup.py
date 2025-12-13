from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.conf.urls.i18n import i18n_patterns
from django.http import HttpResponseRedirect
from django.urls import reverse

def redirect_to_custom_admin(request):
    """Redirect default admin to custom admin dashboard"""
    return HttpResponseRedirect(reverse('frontend_api:admin_dashboard'))

urlpatterns = [
    # Redirect default Django admin to custom admin dashboard
    path('admin/', redirect_to_custom_admin),
    # Keep this for any admin functionality that's still needed
    path('django-admin/', admin.site.urls),
    path('api/', include('apps.media_manager.urls')),
    path('i18n/', include('django.conf.urls.i18n')),
    path('', include('apps.core.urls')),  # Health checks and monitoring
]

# Internationalization patterns
urlpatterns += i18n_patterns(
    path('', include('apps.frontend_api.urls')),
)

# Serve media and static files in development
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATICFILES_DIRS[0])
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)