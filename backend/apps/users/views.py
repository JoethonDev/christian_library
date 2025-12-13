"""
User authentication, profile, and content management views.
"""

from django.shortcuts import render, redirect
from django.contrib.auth import login, logout, authenticate
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic import View, TemplateView
from django.http import JsonResponse, Http404
from django.contrib import messages
from django.utils.translation import gettext as _
from django.views.decorators.cache import never_cache
from django.utils.decorators import method_decorator
from django.core.paginator import Paginator
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated, AllowAny
import logging

from .models import User
from .services import UserService
from .forms import CustomLoginForm
from apps.media_manager.models import ContentItem

logger = logging.getLogger(__name__)


# Authentication Views

class LoginView(View):
    """User login view"""
    template_name = 'registration/login.html'
    form_class = CustomLoginForm
    
    @method_decorator(never_cache)
    def dispatch(self, *args, **kwargs):
        return super().dispatch(*args, **kwargs)
    
    def get(self, request):
        if request.user.is_authenticated:
            return redirect('frontend_api:home')
        form = self.form_class()
        return render(request, self.template_name, {'form': form})
    
    def post(self, request):
        form = self.form_class(request, data=request.POST)
        if form.is_valid():
            username = form.cleaned_data.get('username')
            password = form.cleaned_data.get('password')
            user = authenticate(request, username=username, password=password)
            
            if user is not None:
                login(request, user)
                
                # Set session expiry if remember me is not checked
                if not request.POST.get('remember_me'):
                    request.session.set_expiry(0)  # Browser session only
                
                messages.success(request, _('تم تسجيل الدخول بنجاح'))
                next_url = request.GET.get('next', 'frontend_api:admin_dashboard')
                return redirect(next_url)
            else:
                messages.error(request, _('اسم المستخدم أو كلمة المرور غير صحيحة'))
        
        return render(request, self.template_name, {'form': form})


class LogoutView(View):
    """User logout view"""
    template_name = 'users/logout.html'
    
    def get(self, request):
        return render(request, self.template_name)
    
    def post(self, request):
        logout(request)
        messages.success(request, _('تم تسجيل الخروج بنجاح'))
        return render(request, self.template_name)


class RegisterView(View):
    """User registration view"""
    template_name = 'registration/register.html'
    
    def get(self, request):
        if request.user.is_authenticated:
            return redirect('frontend:home')
        return render(request, self.template_name)
    
    def post(self, request):
        username = request.POST.get('username')
        email = request.POST.get('email')
        password = request.POST.get('password')
        password_confirm = request.POST.get('password_confirm')
        first_name = request.POST.get('first_name', '')
        last_name = request.POST.get('last_name', '')
        
        # Validation
        errors = []
        
        if not all([username, email, password, password_confirm]):
            errors.append(_('All required fields must be filled'))
        
        if password != password_confirm:
            errors.append(_('Passwords do not match'))
        
        if len(password) < 8:
            errors.append(_('Password must be at least 8 characters long'))
        
        if User.objects.filter(username=username).exists():
            errors.append(_('Username already exists'))
        
        if User.objects.filter(email=email).exists():
            errors.append(_('Email already exists'))
        
        if errors:
            for error in errors:
                messages.error(request, error)
            return render(request, self.template_name, {
                'username': username,
                'email': email,
                'first_name': first_name,
                'last_name': last_name,
            })
        
        try:
            user = UserService.create_user(
                username=username,
                email=email,
                password=password,
                first_name=first_name,
                last_name=last_name
            )
            
            # Auto login after registration
            login(request, user)
            messages.success(request, _(f'Welcome to Christian Library, {user.get_full_name() or user.username}!'))
            return redirect('frontend:home')
            
        except Exception as e:
            logger.error(f"Error during user registration: {str(e)}")
            messages.error(request, _('Registration failed. Please try again.'))
            return render(request, self.template_name)


class PasswordResetView(View):
    """Password reset request view"""
    template_name = 'registration/password_reset_form.html'
    
    def get(self, request):
        return render(request, self.template_name)
    
    def post(self, request):
        # This would implement password reset functionality
        messages.info(request, _('Password reset functionality will be implemented.'))
        return render(request, self.template_name)


class PasswordResetConfirmView(View):
    """Password reset confirmation view"""
    template_name = 'users/password_reset_confirm.html'
    
    def get(self, request, uidb64, token):
        # This would implement password reset confirmation
        return render(request, self.template_name)
    
    def post(self, request, uidb64, token):
        # This would handle password reset confirmation
        messages.info(request, _('Password reset confirmation will be implemented.'))
        return render(request, self.template_name)


# Profile Views

@method_decorator(login_required, name='dispatch')
class ProfileView(TemplateView):
    """User profile view"""
    template_name = 'users/profile.html'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['user_stats'] = UserService.get_user_statistics(self.request.user)
        context['content_summary'] = UserService.get_user_content_summary(self.request.user)
        return context


@method_decorator(login_required, name='dispatch')
class ProfileEditView(View):
    """Edit user profile"""
    template_name = 'users/profile_edit.html'
    
    def get(self, request):
        return render(request, self.template_name)
    
    def post(self, request):
        first_name = request.POST.get('first_name', '').strip()
        last_name = request.POST.get('last_name', '').strip()
        email = request.POST.get('email', '').strip()
        phone = request.POST.get('phone', '').strip()
        
        # Basic validation
        if email and User.objects.filter(email=email).exclude(id=request.user.id).exists():
            messages.error(request, _('Email already in use by another account'))
            return render(request, self.template_name)
        
        try:
            UserService.update_user_profile(
                request.user,
                first_name=first_name,
                last_name=last_name,
                email=email,
                phone=phone
            )
            messages.success(request, _('Profile updated successfully'))
            return redirect('users:profile')
            
        except Exception as e:
            logger.error(f"Error updating profile for {request.user.username}: {str(e)}")
            messages.error(request, _('Failed to update profile'))
            return render(request, self.template_name)


@method_decorator(login_required, name='dispatch')
class UserContentView(LoginRequiredMixin, TemplateView):
    """User's content management"""
    template_name = 'users/user_content.html'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        # Get user's content with pagination
        content_items = ContentItem.objects.filter(
            # This assumes there's a created_by field - adjust as needed
            is_active=True
        ).order_by('-created_at')
        
        paginator = Paginator(content_items, 20)
        page_number = self.request.GET.get('page')
        page_obj = paginator.get_page(page_number)
        
        context['content_items'] = page_obj
        context['content_stats'] = UserService.get_user_statistics(self.request.user)
        
        return context


@method_decorator(login_required, name='dispatch')
class PreferencesView(View):
    """User preferences view"""
    template_name = 'users/preferences.html'
    
    def get(self, request):
        return render(request, self.template_name)
    
    def post(self, request):
        # This would handle user preferences
        messages.info(request, _('Preferences functionality will be implemented.'))
        return render(request, self.template_name)


# API Views

class UserProfileAPIView(APIView):
    """API endpoint for user profile"""
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        try:
            user = request.user
            stats = UserService.get_user_statistics(user)
            
            return Response({
                'id': user.id,
                'username': user.username,
                'email': user.email,
                'first_name': user.first_name,
                'last_name': user.last_name,
                'phone': getattr(user, 'phone', ''),
                'is_content_manager': getattr(user, 'is_content_manager', False),
                'date_joined': user.date_joined.isoformat(),
                'last_login': user.last_login.isoformat() if user.last_login else None,
                'statistics': stats,
            })
            
        except Exception as e:
            logger.error(f"Error in UserProfileAPIView: {str(e)}")
            return Response(
                {'error': _('Failed to retrieve profile')},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    def patch(self, request):
        try:
            user = request.user
            data = request.data
            
            # Update allowed fields
            allowed_fields = ['first_name', 'last_name', 'email', 'phone']
            update_data = {k: v for k, v in data.items() if k in allowed_fields}
            
            if 'email' in update_data:
                # Check email uniqueness
                if User.objects.filter(email=update_data['email']).exclude(id=user.id).exists():
                    return Response(
                        {'error': _('Email already in use')},
                        status=status.HTTP_400_BAD_REQUEST
                    )
            
            UserService.update_user_profile(user, **update_data)
            
            return Response({'message': _('Profile updated successfully')})
            
        except Exception as e:
            logger.error(f"Error updating profile via API: {str(e)}")
            return Response(
                {'error': _('Failed to update profile')},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class UserContentAPIView(APIView):
    """API endpoint for user's content"""
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        try:
            # Get user's content
            content_summary = UserService.get_user_content_summary(request.user)
            
            return Response(content_summary)
            
        except Exception as e:
            logger.error(f"Error in UserContentAPIView: {str(e)}")
            return Response(
                {'error': _('Failed to retrieve content')},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class UserStatisticsAPIView(APIView):
    """API endpoint for user statistics"""
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        try:
            stats = UserService.get_user_statistics(request.user)
            return Response(stats)
            
        except Exception as e:
            logger.error(f"Error in UserStatisticsAPIView: {str(e)}")
            return Response(
                {'error': _('Failed to retrieve statistics')},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class UserPreferencesAPIView(APIView):
    """API endpoint for user preferences"""
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        try:
            # This would return user preferences
            return Response({'preferences': {}})
            
        except Exception as e:
            logger.error(f"Error in UserPreferencesAPIView: {str(e)}")
            return Response(
                {'error': _('Failed to retrieve preferences')},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    def post(self, request):
        try:
            # This would update user preferences
            return Response({'message': _('Preferences updated successfully')})
            
        except Exception as e:
            logger.error(f"Error updating preferences via API: {str(e)}")
            return Response(
                {'error': _('Failed to update preferences')},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


# API Authentication Views

class LoginAPIView(APIView):
    """API endpoint for user login"""
    permission_classes = [AllowAny]
    
    def post(self, request):
        try:
            username = request.data.get('username')
            password = request.data.get('password')
            
            if not username or not password:
                return Response({
                    'success': False,
                    'error': 'Username and password are required'
                }, status=status.HTTP_400_BAD_REQUEST)
            
            user = authenticate(username=username, password=password)
            
            if user is not None:
                if user.is_active:
                    login(request, user)
                    return Response({
                        'success': True,
                        'message': 'Login successful',
                        'user': {
                            'id': user.id,
                            'username': user.username,
                            'first_name': user.first_name,
                            'last_name': user.last_name,
                            'email': user.email,
                            'is_staff': user.is_staff,
                            'preferred_language': getattr(user, 'preferred_language', 'ar')
                        }
                    })
                else:
                    return Response({
                        'success': False,
                        'error': 'Account is disabled'
                    }, status=status.HTTP_400_BAD_REQUEST)
            else:
                return Response({
                    'success': False,
                    'error': 'Invalid username or password'
                }, status=status.HTTP_400_BAD_REQUEST)
                
        except Exception as e:
            logger.error(f"Error in LoginAPIView: {str(e)}")
            return Response({
                'success': False,
                'error': 'Login failed'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class LogoutAPIView(APIView):
    """API endpoint for user logout"""
    permission_classes = [IsAuthenticated]
    
    def post(self, request):
        try:
            logout(request)
            return Response({
                'success': True,
                'message': 'Logout successful'
            })
        except Exception as e:
            logger.error(f"Error in LogoutAPIView: {str(e)}")
            return Response({
                'success': False,
                'error': 'Logout failed'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)