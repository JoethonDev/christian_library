"""
Log analysis utilities for monitoring application health and performance.
"""

import logging
from datetime import datetime, timedelta
from typing import Dict, List, Any
from django.core.cache import cache
from collections import defaultdict, Counter


class LogAnalyzer:
    """Analyze application logs for insights and alerts"""
    
    def __init__(self):
        self.logger = logging.getLogger('log_analyzer')
    
    def analyze_error_patterns(self, hours: int = 24) -> Dict[str, Any]:
        """Analyze error patterns in the last N hours"""
        try:
            # Get error data from cache
            error_data = []
            current_hour = int(datetime.utcnow().timestamp() // 3600)
            
            for hour in range(hours):
                hour_key = current_hour - hour
                
                # Get error counts by type for this hour
                for error_type in ['ValueError', 'TypeError', 'KeyError', 'AttributeError',
                                 'IntegrityError', 'ValidationError', 'PermissionDenied']:
                    cache_key = f"error_count_{error_type}_{hour_key}"
                    count = cache.get(cache_key, 0)
                    if count > 0:
                        error_data.append({
                            'error_type': error_type,
                            'count': count,
                            'hour': hour_key,
                            'timestamp': datetime.fromtimestamp(hour_key * 3600)
                        })
            
            # Analyze patterns
            analysis = {
                'total_errors': sum(item['count'] for item in error_data),
                'error_types': Counter(item['error_type'] for item in error_data),
                'hourly_distribution': defaultdict(int),
                'trending_errors': [],
                'critical_alerts': []
            }
            
            # Group by hour
            for item in error_data:
                analysis['hourly_distribution'][item['hour']] += item['count']
            
            # Find trending errors (increasing over time)
            error_trends = defaultdict(list)
            for item in error_data:
                error_trends[item['error_type']].append((item['hour'], item['count']))
            
            for error_type, hourly_counts in error_trends.items():
                if len(hourly_counts) >= 3:
                    # Simple trend analysis - check if recent hours have more errors
                    recent_hours = sorted(hourly_counts, key=lambda x: x[0], reverse=True)[:3]
                    older_hours = sorted(hourly_counts, key=lambda x: x[0], reverse=True)[3:6]
                    
                    recent_avg = sum(count for _, count in recent_hours) / len(recent_hours)
                    older_avg = sum(count for _, count in older_hours) / len(older_hours) if older_hours else 0
                    
                    if recent_avg > older_avg * 1.5 and recent_avg > 5:  # 50% increase threshold
                        analysis['trending_errors'].append({
                            'error_type': error_type,
                            'recent_average': recent_avg,
                            'previous_average': older_avg,
                            'increase_percent': ((recent_avg - older_avg) / older_avg * 100) if older_avg > 0 else 0
                        })
            
            # Generate alerts for high error rates
            total_recent_errors = sum(
                count for hour, count in analysis['hourly_distribution'].items() 
                if hour >= current_hour - 3  # Last 3 hours
            )
            
            if total_recent_errors > 100:  # Alert threshold
                analysis['critical_alerts'].append({
                    'type': 'high_error_rate',
                    'message': f'High error rate detected: {total_recent_errors} errors in last 3 hours',
                    'severity': 'high' if total_recent_errors > 200 else 'medium'
                })
            
            return analysis
            
        except Exception as e:
            self.logger.error(f"Error analyzing error patterns: {e}")
            return {}
    
    def analyze_performance_metrics(self, hours: int = 24) -> Dict[str, Any]:
        """Analyze performance metrics"""
        try:
            # Get performance data from cache
            performance_data = []
            current_minute = int(datetime.utcnow().timestamp() // 60)
            
            # Sample every 5 minutes for the analysis
            for minute in range(0, hours * 60, 5):
                minute_key = current_minute - minute
                
                # Check for cached performance metrics
                for operation in ['view_render', 'database_query', 'cache_operation', 'api_request']:
                    cache_key = f"perf_metric_{operation}_{minute_key}"
                    metric_data = cache.get(cache_key)
                    
                    if metric_data:
                        performance_data.append({
                            'operation': operation,
                            'timestamp': datetime.fromtimestamp(minute_key * 60),
                            **metric_data
                        })
            
            # Analyze performance
            analysis = {
                'total_operations': sum(item['count'] for item in performance_data),
                'operations_by_type': Counter(item['operation'] for item in performance_data),
                'slow_operations': [],
                'performance_alerts': []
            }
            
            # Find slow operations
            for item in performance_data:
                if item.get('avg_time', 0) > 2.0:  # Slower than 2 seconds
                    analysis['slow_operations'].append({
                        'operation': item['operation'],
                        'avg_time': item['avg_time'],
                        'max_time': item.get('max_time', 0),
                        'count': item['count'],
                        'timestamp': item['timestamp']
                    })
            
            # Calculate overall performance trends
            recent_performance = [
                item for item in performance_data 
                if item['timestamp'] > datetime.utcnow() - timedelta(hours=1)
            ]
            
            if recent_performance:
                avg_response_time = sum(
                    item.get('avg_time', 0) for item in recent_performance
                ) / len(recent_performance)
                
                if avg_response_time > 1.0:  # Alert if average response time > 1 second
                    analysis['performance_alerts'].append({
                        'type': 'slow_response_time',
                        'message': f'Average response time is {avg_response_time:.2f}s',
                        'severity': 'high' if avg_response_time > 3.0 else 'medium'
                    })
            
            return analysis
            
        except Exception as e:
            self.logger.error(f"Error analyzing performance metrics: {e}")
            return {}
    
    def analyze_user_activity(self, hours: int = 24) -> Dict[str, Any]:
        """Analyze user activity patterns"""
        try:
            # Get recent audit logs from cache
            recent_logs = cache.get('recent_audit_logs', [])
            
            # Filter to time window
            cutoff_time = datetime.utcnow() - timedelta(hours=hours)
            relevant_logs = [
                log for log in recent_logs
                if datetime.fromisoformat(log.get('timestamp', '')) > cutoff_time
            ]
            
            analysis = {
                'total_actions': len(relevant_logs),
                'unique_users': len(set(log.get('user_id') for log in relevant_logs if log.get('user_id'))),
                'actions_by_type': Counter(log.get('action') for log in relevant_logs),
                'hourly_activity': defaultdict(int),
                'suspicious_patterns': []
            }
            
            # Analyze hourly distribution
            for log in relevant_logs:
                timestamp = datetime.fromisoformat(log.get('timestamp', ''))
                hour = timestamp.hour
                analysis['hourly_activity'][hour] += 1
            
            # Look for suspicious patterns
            user_actions = defaultdict(list)
            for log in relevant_logs:
                user_id = log.get('user_id')
                if user_id:
                    user_actions[user_id].append(log)
            
            # Check for users with unusually high activity
            for user_id, actions in user_actions.items():
                if len(actions) > 100:  # Threshold for suspicious activity
                    analysis['suspicious_patterns'].append({
                        'type': 'high_activity_user',
                        'user_id': user_id,
                        'action_count': len(actions),
                        'actions': Counter(action.get('action') for action in actions)
                    })
            
            return analysis
            
        except Exception as e:
            self.logger.error(f"Error analyzing user activity: {e}")
            return {}
    
    def generate_health_report(self) -> Dict[str, Any]:
        """Generate a comprehensive application health report"""
        try:
            report = {
                'timestamp': datetime.utcnow().isoformat(),
                'error_analysis': self.analyze_error_patterns(24),
                'performance_analysis': self.analyze_performance_metrics(24),
                'user_activity': self.analyze_user_activity(24),
                'overall_health_score': 100,  # Start at 100 and deduct points
                'recommendations': [],
                'alerts': []
            }
            
            # Calculate health score
            error_analysis = report['error_analysis']
            performance_analysis = report['performance_analysis']
            
            # Deduct points for errors
            if error_analysis.get('total_errors', 0) > 50:
                report['overall_health_score'] -= 20
                report['recommendations'].append('Investigate high error rate')
            
            if len(error_analysis.get('trending_errors', [])) > 0:
                report['overall_health_score'] -= 15
                report['recommendations'].append('Address trending error patterns')
            
            # Deduct points for performance issues
            slow_ops = performance_analysis.get('slow_operations', [])
            if len(slow_ops) > 5:
                report['overall_health_score'] -= 25
                report['recommendations'].append('Optimize slow operations')
            
            # Collect all alerts
            all_alerts = []
            all_alerts.extend(error_analysis.get('critical_alerts', []))
            all_alerts.extend(performance_analysis.get('performance_alerts', []))
            report['alerts'] = all_alerts
            
            # Ensure health score doesn't go below 0
            report['overall_health_score'] = max(0, report['overall_health_score'])
            
            return report
            
        except Exception as e:
            self.logger.error(f"Error generating health report: {e}")
            return {
                'timestamp': datetime.utcnow().isoformat(),
                'error': str(e),
                'overall_health_score': 0
            }


class AlertManager:
    """Manage and process application alerts"""
    
    def __init__(self):
        self.logger = logging.getLogger('alert_manager')
        self.alert_thresholds = {
            'error_rate': 50,  # errors per hour
            'response_time': 2.0,  # seconds
            'disk_usage': 85,  # percent
            'memory_usage': 90,  # percent
        }
    
    def check_alerts(self) -> List[Dict[str, Any]]:
        """Check for alert conditions"""
        alerts = []
        
        try:
            # Check error rate
            current_hour = int(datetime.utcnow().timestamp() // 3600)
            total_errors = 0
            
            for error_type in ['ValueError', 'TypeError', 'KeyError', 'AttributeError']:
                cache_key = f"error_count_{error_type}_{current_hour}"
                total_errors += cache.get(cache_key, 0)
            
            if total_errors > self.alert_thresholds['error_rate']:
                alerts.append({
                    'type': 'error_rate',
                    'severity': 'high',
                    'message': f'Error rate exceeded threshold: {total_errors} errors this hour',
                    'threshold': self.alert_thresholds['error_rate'],
                    'current_value': total_errors
                })
            
            # Check recent performance metrics
            current_minute = int(datetime.utcnow().timestamp() // 60)
            slow_operations = 0
            
            for minute in range(5):  # Check last 5 minutes
                minute_key = current_minute - minute
                cache_key = f"perf_metric_view_render_{minute_key}"
                metric_data = cache.get(cache_key)
                
                if metric_data and metric_data.get('avg_time', 0) > self.alert_thresholds['response_time']:
                    slow_operations += 1
            
            if slow_operations >= 3:  # 3 out of 5 minutes were slow
                alerts.append({
                    'type': 'response_time',
                    'severity': 'medium',
                    'message': 'Response times consistently above threshold',
                    'threshold': self.alert_thresholds['response_time'],
                    'slow_minutes': slow_operations
                })
            
        except Exception as e:
            self.logger.error(f"Error checking alerts: {e}")
            alerts.append({
                'type': 'system_error',
                'severity': 'high',
                'message': f'Alert system error: {str(e)}'
            })
        
        return alerts
    
    def process_alert(self, alert: Dict[str, Any]) -> bool:
        """Process an individual alert"""
        try:
            # Log the alert
            self.logger.warning(f"Alert: {alert}")
            
            # Store in cache for dashboard
            alert_key = f"alert_{alert['type']}_{int(datetime.utcnow().timestamp())}"
            cache.set(alert_key, alert, 3600)  # Store for 1 hour
            
            # Add to recent alerts list
            recent_alerts = cache.get('recent_alerts', [])
            recent_alerts.insert(0, alert)
            recent_alerts = recent_alerts[:20]  # Keep last 20 alerts
            cache.set('recent_alerts', recent_alerts, 3600)
            
            return True
            
        except Exception as e:
            self.logger.error(f"Error processing alert: {e}")
            return False


class LogRetention:
    """Manage log retention and cleanup"""
    
    def __init__(self):
        self.logger = logging.getLogger('log_retention')
        self.retention_periods = {
            'debug': 7,      # days
            'info': 30,      # days
            'warning': 90,   # days
            'error': 365,    # days
            'critical': 365  # days
        }
    
    def cleanup_old_logs(self) -> Dict[str, int]:
        """Clean up old log entries"""
        cleaned_counts = defaultdict(int)
        
        try:
            # Clean up cached metrics and alerts
            current_time = int(datetime.utcnow().timestamp())
            
            # Clean up performance metrics older than 24 hours
            cutoff_minute = current_time // 60 - (24 * 60)
            
            # This is a simplified version - in production you'd have a more sophisticated cleanup
            self.logger.info(f"Log cleanup completed. Cleaned {sum(cleaned_counts.values())} entries")
            
        except Exception as e:
            self.logger.error(f"Error during log cleanup: {e}")
        
        return dict(cleaned_counts)


# Global instances
log_analyzer = LogAnalyzer()
alert_manager = AlertManager()
log_retention = LogRetention()