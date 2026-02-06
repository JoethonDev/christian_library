# robots.txt
from apps.frontend_api.views_root_robots import robots_txt
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.conf.urls.i18n import i18n_patterns
from django.http import HttpResponseRedirect
from django.urls import reverse
from django.views.i18n import set_language
from django.views.generic import RedirectView
from apps.frontend_api.views_root_redirect import smart_root_redirect
from core.utils.cache_utils import cache_unless_authenticated
from django.views.decorators.cache import cache_page
import logging

logger = logging.getLogger(__name__)


urlpatterns = [
    # Django Default Admin (at /admin/)
    path('admin/', admin.site.urls, name='django_admin'),
    
    # Task Monitoring Admin (at /admin/tasks/)
    path('admin/tasks/', include('apps.admin_django.urls', namespace='admin_django')),
    
    # Authentication redirects
    path('accounts/login/', RedirectView.as_view(url='/ar/users/login/', permanent=False), name='login_redirect'),
    path('accounts/logout/', RedirectView.as_view(url='/ar/users/logout/', permanent=False), name='logout_redirect'),
    
    # API endpoints (non-internationalized for consistency)
    path('api/auth/', include(('apps.users.urls', 'users'), namespace='auth_api')),
    path('api/media/', include('apps.media_manager.urls', namespace='media_api')),

    path('api/users/', include('apps.users.urls', namespace='users_api')),
    
    # System endpoints
    path('', include('apps.core.urls', namespace='core')),
    path('core/', include('core.urls', namespace='core_utils')),
    path('i18n/setlang/', set_language, name='set_language'),
    path('i18n/', include('django.conf.urls.i18n')),
    
    # Root redirect to user's preferred language
    path('', smart_root_redirect, name='root_redirect'),
]

# Sitemap and SEO
from django.contrib.sitemaps.views import sitemap, index as sitemap_index
from apps.frontend_api.sitemaps import (
    HomeSitemap, ContentListSitemap, VideoSitemap, AudioSitemap, 
    PdfSitemap, PdfListSitemap, PdfDetailSitemap
)
from apps.frontend_api.feeds import (
    LatestContentFeed, LatestVideosFeed, LatestAudiosFeed, 
    LatestPdfsFeed, LatestContentAtomFeed
)

sitemaps = {
    'home': HomeSitemap(),
    'content-lists': ContentListSitemap(),
    'videos': VideoSitemap(),
    'audios': AudioSitemap(),
    'pdfs': PdfSitemap(),
    # Legacy sitemaps for backward compatibility
    'pdf-list': PdfListSitemap(),
    'pdf-detail': PdfDetailSitemap(),
}

urlpatterns += [
    # Individual sitemap sections (non-i18n fallback)
    path('sitemap-<section>.xml', sitemap, {'sitemaps': sitemaps}, name='django.contrib.sitemaps.views.sitemap'),
    
    # Global sitemap redirect to preferred language
    path('sitemap.xml', RedirectView.as_view(url='/ar/sitemap.xml', permanent=False), name='sitemap_redirect_global'),
    
    # RSS/Atom Feeds
    path('feeds/latest.rss', LatestContentFeed(), name='feed_latest'),
    path('feeds/latest.atom', LatestContentAtomFeed(), name='feed_latest_atom'),
    path('feeds/videos.rss', LatestVideosFeed(), name='feed_videos'),
    path('feeds/audios.rss', LatestAudiosFeed(), name='feed_audios'),
    path('feeds/pdfs.rss', LatestPdfsFeed(), name='feed_pdfs'),
    
    # robots.txt
    path('robots.txt', robots_txt, name='robots_txt'),
]

# Internationalized URL patterns
urlpatterns += i18n_patterns(
    # Main application URLs
    path('', include('apps.frontend_api.urls')),
    
    # Sitemaps (i18n versions)
    path('sitemap.xml', sitemap_index, {'sitemaps': sitemaps, 'sitemap_url_name': 'sitemap_section_i18n'}, name='sitemap_index_i18n'),
    path('sitemap-<section>.xml', sitemap, {'sitemaps': sitemaps}, name='sitemap_section_i18n'),

    # Media URLs  
    path('media/', include('apps.media_manager.urls', namespace='media')),
    
    # User URLs
    path('users/', include('apps.users.urls', namespace='users')),
    
    # Enable language prefixes for all languages, including default
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
    
    # Django Debug Toolbar (if installed)

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