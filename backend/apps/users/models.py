from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.db import models
from django.utils.translation import gettext_lazy as _
from django.core.exceptions import ValidationError
import uuid


class UserManager(BaseUserManager):
    """Custom manager for User model"""
    
    def create_user(self, username, email=None, password=None, **extra_fields):
        """Create and save a regular User with the given username and password"""
        if not username:
            raise ValueError('The Username field must be set')
        
        email = self.normalize_email(email) if email else None
        user = self.model(username=username, email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user
    
    def create_superuser(self, username, email=None, password=None, **extra_fields):
        """Create and save a SuperUser with the given username and password"""
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        extra_fields.setdefault('is_content_manager', True)
        extra_fields.setdefault('preferred_language', 'ar')
        
        if extra_fields.get('is_staff') is not True:
            raise ValueError('Superuser must have is_staff=True.')
        if extra_fields.get('is_superuser') is not True:
            raise ValueError('Superuser must have is_superuser=True.')
        
        return self.create_user(username, email, password, **extra_fields)
    
    def content_managers(self):
        """Return only content managers"""
        return self.filter(is_content_manager=True, is_active=True)
    
    def admins(self):
        """Return only admin users"""
        return self.filter(is_staff=True, is_active=True)
    
    def get_by_natural_key(self, username):
        """Get user by username (required for authentication)"""
        return self.get(**{self.model.USERNAME_FIELD: username})


class User(AbstractUser):
    """Custom user model for admin users only in Phase 1"""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    
    # Additional profile fields
    phone = models.CharField(
        max_length=20, 
        blank=True, 
        verbose_name=_('Phone Number'),
        help_text=_('Optional phone number for contact')
    )
    is_content_manager = models.BooleanField(
        default=False, 
        verbose_name=_('Content Manager'),
        help_text=_('Can this user manage content uploads and processing?')
    )
    preferred_language = models.CharField(
        max_length=5,
        choices=[('ar', _('Arabic')), ('en', _('English'))],
        default='ar',
        verbose_name=_('Preferred Language')
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name=_('Created At'))
    updated_at = models.DateTimeField(auto_now=True, verbose_name=_('Updated At'))
    
    # Custom manager
    objects = UserManager()
    
    class Meta:
        verbose_name = _('User')
        verbose_name_plural = _('Users')
        indexes = [
            models.Index(fields=['is_content_manager', 'is_active']),
            models.Index(fields=['is_staff', 'is_active']),
        ]
        
    def __str__(self):
        return self.username
    
    def get_full_name_or_username(self):
        """Return full name if available, otherwise username"""
        full_name = self.get_full_name()
        return full_name if full_name else self.username
    
    def can_manage_content(self):
        """Check if user can manage content"""
        return self.is_content_manager or self.is_staff or self.is_superuser
    
    def clean(self):
        """Validate the user"""
        super().clean()
        if self.phone and not self.phone.replace('+', '').replace('-', '').replace(' ', '').isdigit():
            raise ValidationError(_('Phone number must contain only digits, +, -, and spaces'))