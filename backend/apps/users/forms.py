from django import forms
from django.contrib.auth.forms import AuthenticationForm
from django.utils.translation import gettext_lazy as _


class CustomLoginForm(AuthenticationForm):
    """Custom login form with Arabic RTL support"""
    
    username = forms.CharField(
        max_length=254,
        widget=forms.TextInput(attrs={
            'class': 'appearance-none relative block w-full px-3 py-3 border border-gray-300 rounded-lg placeholder-gray-500 text-ink-black focus:outline-none focus:ring-heavenly-cyan focus:border-heavenly-cyan focus:z-10 sm:text-sm',
            'placeholder': _('أدخل اسم المستخدم'),
        }),
        label=_('اسم المستخدم')
    )
    
    password = forms.CharField(
        widget=forms.PasswordInput(attrs={
            'class': 'appearance-none relative block w-full px-3 py-3 border border-gray-300 rounded-lg placeholder-gray-500 text-ink-black focus:outline-none focus:ring-heavenly-cyan focus:border-heavenly-cyan focus:z-10 sm:text-sm',
            'placeholder': _('أدخل كلمة المرور'),
        }),
        label=_('كلمة المرور')
    )
    
    error_messages = {
        'invalid_login': _(
            "يرجى التأكد من صحة اسم المستخدم وكلمة المرور. تذكر أن كلا الحقلين قد يكونان حساسين للحروف الكبيرة والصغيرة."
        ),
        'inactive': _("هذا الحساب غير مفعل."),
    }


class UserPreferencesForm(forms.ModelForm):
    """User preferences form"""
    
    class Meta:
        from .models import User
        model = User
        fields = ['preferred_language', 'phone']
        
        widgets = {
            'preferred_language': forms.Select(attrs={
                'class': 'mt-1 block w-full border border-gray-300 rounded-lg px-3 py-2 shadow-sm focus:outline-none focus:ring-heavenly-cyan focus:border-heavenly-cyan'
            }),
            'phone': forms.TextInput(attrs={
                'class': 'mt-1 block w-full border border-gray-300 rounded-lg px-3 py-2 shadow-sm focus:outline-none focus:ring-heavenly-cyan focus:border-heavenly-cyan',
                'placeholder': _('رقم الهاتف (اختياري)'),
            }),
        }
        
        labels = {
            'preferred_language': _('اللغة المفضلة'),
            'phone': _('رقم الهاتف'),
        }