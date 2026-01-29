"""
Advanced logging utilities for structured logging and monitoring.
"""

import json
import logging
import time
from datetime import datetime
from typing import Dict, Any, Optional
import traceback
import functools
from django.core.cache import cache
import uuid


class StructuredLogger:
    """Structured logger for consistent log formatting"""
    
    def __init__(self, name: str):
        self.logger = logging.getLogger(name)
        self.name = name
    
    def log_event(self, level: str, event_type: str, message: str, 
                  context: Dict[str, Any] = None, **kwargs):
        """Log a structured event"""
        log_data = {
            'timestamp': datetime.utcnow().isoformat(),
            'level': level.upper(),
            'logger': self.name,
            'event_type': event_type,
            'message': message,
            'context': context or {},
            **kwargs
        }
        
        # Add request context if available
        try:
            from django.contrib.auth import get_user
            from django.test import RequestFactory
            # This is a simplified version - in practice you'd get this from middleware
        except ImportError:
            pass
        
        log_message = json.dumps(log_data, default=str)
        
        # Log at appropriate level
        if level.lower() == 'debug':
            self.logger.debug(log_message)
        elif level.lower() == 'info':
            self.logger.info(log_message)
        elif level.lower() == 'warning':
            self.logger.warning(log_message)
        elif level.lower() == 'error':
            self.logger.error(log_message)
        elif level.lower() == 'critical':
            self.logger.critical(log_message)
    
    def log_performance(self, operation: str, duration: float, 
                       context: Dict[str, Any] = None):
        """Log performance metrics"""
        self.log_event(
            level='info',
            event_type='performance',
            message=f"Operation '{operation}' completed in {duration:.3f}s",
            context=context,
            operation=operation,
            duration_seconds=duration
        )
    
    def log_error(self, error: Exception, context: Dict[str, Any] = None):
        """Log an error with full context"""
        self.log_event(
            level='error',
            event_type='error',
            message=str(error),
            context=context,
            error_type=error.__class__.__name__,
            traceback=traceback.format_exc()
        )
    
    def log_user_action(self, user_id: Optional[int], action: str, 
                       resource: str = None, context: Dict[str, Any] = None):
        """Log user actions for audit trail"""
        self.log_event(
            level='info',
            event_type='user_action',
            message=f"User {user_id or 'anonymous'} performed {action}",
            context=context,
            user_id=user_id,
            action=action,
            resource=resource
        )
    
    def log_security_event(self, event_type: str, severity: str, 
                          details: Dict[str, Any] = None):
        """Log security events"""
        self.log_event(
            level='warning' if severity == 'medium' else 'error',
            event_type='security',
            message=f"Security event: {event_type}",
            context=details or {},
            security_event_type=event_type,
            severity=severity
        )


class PerformanceMonitor:
    """Monitor and track performance metrics"""
    
    def __init__(self):
        self.logger = StructuredLogger('performance')
    
    def __call__(self, operation_name: str = None):
        """Decorator for monitoring function performance"""
        def decorator(func):
            @functools.wraps(func)
            def wrapper(*args, **kwargs):
                operation = operation_name or f"{func.__module__}.{func.__name__}"
                
                start_time = time.time()
                try:
                    result = func(*args, **kwargs)
                    duration = time.time() - start_time
                    
                    # Log performance
                    self.logger.log_performance(
                        operation=operation,
                        duration=duration,
                        context={
                            'function': func.__name__,
                            'module': func.__module__,
                            'args_count': len(args),
                            'kwargs_keys': list(kwargs.keys())
                        }
                    )
                    
                    # Store metrics for monitoring dashboard
                    self._store_metric(operation, duration)
                    
                    return result
                    
                except Exception as e:
                    duration = time.time() - start_time
                    
                    # Log error with performance context
                    self.logger.log_error(
                        error=e,
                        context={
                            'operation': operation,
                            'duration_before_error': duration,
                            'function': func.__name__,
                            'module': func.__module__
                        }
                    )
                    
                    raise
            
            return wrapper
        return decorator
    
    def _store_metric(self, operation: str, duration: float):
        """Store performance metric for dashboard"""
        try:
            # Store in cache for real-time monitoring
            cache_key = f"perf_metric_{operation}_{int(time.time() // 60)}"
            current_data = cache.get(cache_key, {
                'count': 0,
                'total_time': 0,
                'min_time': float('inf'),
                'max_time': 0,
                'operation': operation
            })
            
            current_data['count'] += 1
            current_data['total_time'] += duration
            current_data['min_time'] = min(current_data['min_time'], duration)
            current_data['max_time'] = max(current_data['max_time'], duration)
            current_data['avg_time'] = current_data['total_time'] / current_data['count']
            
            cache.set(cache_key, current_data, 300)  # 5 minute TTL
            
        except Exception as e:
            # Don't let monitoring break the application
            logging.getLogger('performance').warning(f"Failed to store metric: {e}")


class ErrorTracker:
    """Track and analyze application errors"""
    
    def __init__(self):
        self.logger = StructuredLogger('errors')
    
    def track_error(self, error: Exception, context: Dict[str, Any] = None,
                   severity: str = 'error', tags: Dict[str, str] = None):
        """Track an error with context"""
        error_id = str(uuid.uuid4())
        
        error_data = {
            'error_id': error_id,
            'error_type': error.__class__.__name__,
            'error_message': str(error),
            'severity': severity,
            'context': context or {},
            'tags': tags or {},
            'traceback': traceback.format_exc(),
            'timestamp': datetime.utcnow().isoformat()
        }
        
        # Log the error
        self.logger.log_event(
            level=severity,
            event_type='tracked_error',
            message=f"Error tracked: {error.__class__.__name__}",
            context=error_data
        )
        
        # Store for error analysis
        self._store_error_for_analysis(error_data)
        
        return error_id
    
    def _store_error_for_analysis(self, error_data: Dict[str, Any]):
        """Store error data for analysis"""
        try:
            # Count error frequency
            error_type = error_data['error_type']
            cache_key = f"error_count_{error_type}_{int(time.time() // 3600)}"  # hourly buckets
            current_count = cache.get(cache_key, 0)
            cache.set(cache_key, current_count + 1, 7200)  # 2 hour TTL
            
            # Store recent errors for dashboard
            recent_errors_key = "recent_errors"
            recent_errors = cache.get(recent_errors_key, [])
            recent_errors.insert(0, error_data)
            recent_errors = recent_errors[:50]  # Keep last 50 errors
            cache.set(recent_errors_key, recent_errors, 3600)  # 1 hour TTL
            
        except Exception as e:
            logging.getLogger('errors').warning(f"Failed to store error for analysis: {e}")


class AuditLogger:
    """Log user actions for audit trail"""
    
    def __init__(self):
        self.logger = StructuredLogger('audit')
    
    def log_action(self, user_id: Optional[int], action: str, resource_type: str = None,
                   resource_id: str = None, details: Dict[str, Any] = None,
                   ip_address: str = None, user_agent: str = None):
        """Log a user action"""
        audit_data = {
            'user_id': user_id,
            'action': action,
            'resource_type': resource_type,
            'resource_id': resource_id,
            'details': details or {},
            'ip_address': ip_address,
            'user_agent': user_agent,
            'timestamp': datetime.utcnow().isoformat()
        }
        
        self.logger.log_event(
            level='info',
            event_type='audit',
            message=f"User {user_id or 'anonymous'} performed {action}",
            context=audit_data
        )
    
    def log_login(self, user_id: int, success: bool, ip_address: str = None,
                  failure_reason: str = None):
        """Log login attempts"""
        action = 'login_success' if success else 'login_failure'
        details = {'success': success}
        
        if not success and failure_reason:
            details['failure_reason'] = failure_reason
        
        self.log_action(
            user_id=user_id if success else None,
            action=action,
            details=details,
            ip_address=ip_address
        )
    
    def log_content_access(self, user_id: Optional[int], content_type: str,
                          content_id: str, action: str = 'view'):
        """Log content access"""
        self.log_action(
            user_id=user_id,
            action=f"content_{action}",
            resource_type=content_type,
            resource_id=content_id
        )
    
    def log_admin_action(self, user_id: int, action: str, target_user_id: int = None,
                        resource_type: str = None, resource_id: str = None,
                        changes: Dict[str, Any] = None):
        """Log administrative actions"""
        details = {'is_admin_action': True}
        if target_user_id:
            details['target_user_id'] = target_user_id
        if changes:
            details['changes'] = changes
        
        self.log_action(
            user_id=user_id,
            action=f"admin_{action}",
            resource_type=resource_type,
            resource_id=resource_id,
            details=details
        )


class SecurityLogger:
    """Log security-related events"""
    
    def __init__(self):
        self.logger = StructuredLogger('security')
    
    def log_suspicious_activity(self, activity_type: str, severity: str = 'medium',
                               details: Dict[str, Any] = None,
                               ip_address: str = None, user_id: int = None):
        """Log suspicious activity"""
        self.logger.log_security_event(
            event_type=activity_type,
            severity=severity,
            details={
                'ip_address': ip_address,
                'user_id': user_id,
                **(details or {})
            }
        )
    
    def log_failed_authentication(self, username: str, ip_address: str = None,
                                 failure_reason: str = 'invalid_credentials'):
        """Log failed authentication attempts"""
        self.log_suspicious_activity(
            activity_type='failed_authentication',
            severity='medium',
            details={
                'username': username,
                'failure_reason': failure_reason
            },
            ip_address=ip_address
        )
    
    def log_access_denied(self, user_id: Optional[int], resource: str,
                         required_permission: str = None,
                         ip_address: str = None):
        """Log access denied events"""
        self.log_suspicious_activity(
            activity_type='access_denied',
            severity='medium',
            details={
                'resource': resource,
                'required_permission': required_permission
            },
            ip_address=ip_address,
            user_id=user_id
        )


# Global logger instances
performance_monitor = PerformanceMonitor()
error_tracker = ErrorTracker()
audit_logger = AuditLogger()
security_logger = SecurityLogger()

# Convenience decorators
monitor_performance = performance_monitor
track_errors = error_tracker.track_error