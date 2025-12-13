from django.urls import path
from . import views

app_name = 'media_manager'

urlpatterns = [
    # DEPRECATED: Direct media serving (for HTML5 audio/video elements)
    # This endpoint is no longer used - media is now served through core.utils.nginx_security
    path('serve/<str:content_type>/<uuid:content_uuid>/', 
         views.DirectMediaServeView.as_view(), name='direct_serve'),
    
    # DEPRECATED: Secure media delivery endpoints 
    # This endpoint is no longer used - media is now served through core.utils.nginx_security
    path('secure/<str:content_type>/<uuid:content_uuid>/', 
         views.SecureMediaView.as_view(), name='secure_media'),
    
    # DEPRECATED: HLS streaming endpoints
    # HLS streaming is handled through nginx X-Accel-Redirect now
    path('hls/<uuid:video_uuid>/', 
         views.HLSStreamView.as_view(), name='hls_stream'),
    path('hls/<uuid:video_uuid>/<str:quality>/', 
         views.HLSStreamView.as_view(), name='hls_stream_quality'),
    
    # DEPRECATED: Authentication check for Nginx
    # Authentication is now handled in core.utils.nginx_security
    path('auth-check/', views.auth_check, name='auth_check'),
    
    # DEPRECATED: Embedded player views
    # Players are now handled through frontend_api views
    path('player/<str:content_type>/<uuid:content_uuid>/', 
         views.MediaPlayerView.as_view(), name='media_player'),
]