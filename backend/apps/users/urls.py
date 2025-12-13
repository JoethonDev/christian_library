from django.urls import path, include
from . import views

app_name = 'users'

# API patterns
api_patterns = [
    # Authentication endpoints
    path('auth/login/', views.LoginAPIView.as_view(), name='api_login'),
    path('auth/logout/', views.LogoutAPIView.as_view(), name='api_logout'),
    
    # User management endpoints
    path('profile/', views.UserProfileAPIView.as_view(), name='api_profile'),
    path('content/', views.UserContentAPIView.as_view(), name='api_content'),
    path('statistics/', views.UserStatisticsAPIView.as_view(), name='api_statistics'),
    path('preferences/', views.UserPreferencesAPIView.as_view(), name='api_preferences'),
]

# Authentication patterns
auth_patterns = [
    path('login/', views.LoginView.as_view(), name='login'),
    path('logout/', views.LogoutView.as_view(), name='logout'),
    path('register/', views.RegisterView.as_view(), name='register'),
    path('password-reset/', views.PasswordResetView.as_view(), name='password_reset'),
    path('password-reset-confirm/<uidb64>/<token>/', 
         views.PasswordResetConfirmView.as_view(), name='password_reset_confirm'),
]

# Profile patterns
profile_patterns = [
    path('profile/', views.ProfileView.as_view(), name='profile'),
    path('profile/edit/', views.ProfileEditView.as_view(), name='profile_edit'),
    path('content/', views.UserContentView.as_view(), name='content'),
    path('preferences/', views.PreferencesView.as_view(), name='preferences'),
]

urlpatterns = [
    path('api/', include(api_patterns)),
    path('auth/', include(auth_patterns)),
    
    # Direct login/logout for convenience
    path('login/', views.LoginView.as_view(), name='login'),
    path('logout/', views.LogoutView.as_view(), name='logout'),
    
    path('', include(profile_patterns)),
]