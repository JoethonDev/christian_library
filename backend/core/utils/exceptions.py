"""
Custom exception handlers for the Django REST Framework and general application
"""
from django.http import Http404
from django.core.exceptions import PermissionDenied, ValidationError as DjangoValidationError
from django.conf import settings
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import exception_handler
from django.utils.translation import gettext_lazy as _
import logging

logger = logging.getLogger(__name__)

# Export ValidationError for easy import
ValidationError = DjangoValidationError


class MediaProcessingError(Exception):
    """Custom exception for media processing errors"""
    pass


class FileValidationError(ValidationError):
    """Custom validation error for file uploads"""
    pass


def custom_exception_handler(exc, context):
    """
    Custom exception handler for DRF that provides consistent error responses
    with proper localization support
    """
    # Call REST framework's default exception handler first
    response = exception_handler(exc, context)
    
    # Log the exception for debugging
    request = context.get('request')
    view = context.get('view')
    
    logger.error(
        f"Exception in {view.__class__.__name__ if view else 'Unknown'}: {str(exc)}",
        extra={
            'request_path': request.path if request else None,
            'request_method': request.method if request else None,
            'user': str(request.user) if request and hasattr(request, 'user') else None,
            'exception_type': exc.__class__.__name__,
        }
    )
    
    if response is not None:
        # Customize the response format
        custom_response_data = {
            'error': True,
            'message': _('An error occurred'),
            'details': response.data
        }
        
        # Handle specific exception types
        if isinstance(exc, Http404):
            custom_response_data['message'] = _('Resource not found')
        elif isinstance(exc, PermissionDenied):
            custom_response_data['message'] = _('Permission denied')
        elif isinstance(exc, DjangoValidationError):
            custom_response_data['message'] = _('Validation error')
            
        response.data = custom_response_data
    else:
        # Handle exceptions not covered by DRF
        if isinstance(exc, Http404):
            response = Response({
                'error': True,
                'message': _('Resource not found'),
                'details': str(exc)
            }, status=status.HTTP_404_NOT_FOUND)
        elif isinstance(exc, PermissionDenied):
            response = Response({
                'error': True,
                'message': _('Permission denied'),
                'details': str(exc)
            }, status=status.HTTP_403_FORBIDDEN)
        elif isinstance(exc, DjangoValidationError):
            response = Response({
                'error': True,
                'message': _('Validation error'),
                'details': str(exc)
            }, status=status.HTTP_400_BAD_REQUEST)
        else:
            # For any other exception, return a generic 500 error
            response = Response({
                'error': True,
                'message': _('Internal server error'),
                'details': str(exc) if settings.DEBUG else _('An unexpected error occurred')
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
    return response


class MediaSecurityError(Exception):
    """Custom exception for media security violations"""
    pass


class ContentNotFoundError(Exception):
    """Custom exception for content not found errors"""
    pass


class InvalidContentTypeError(Exception):
    """Custom exception for invalid content type errors"""
    pass