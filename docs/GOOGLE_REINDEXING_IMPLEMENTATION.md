# Google Re-indexing Implementation Guide

## Overview

This document provides technical details about the Google Re-indexing feature implementation, including architecture, design decisions, and maintenance guidelines.

## Architecture

### Components

```
┌─────────────────────────────────────────────────────────────────┐
│                        Frontend (Browser)                        │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────┐  │
│  │ UI Template  │  │   Progress   │  │  JavaScript Polling  │  │
│  │ seo_reindex  │  │    Modal     │  │   (every 2 seconds)  │  │
│  └──────────────┘  └──────────────┘  └──────────────────────┘  │
└────────────────────────────┬────────────────────────────────────┘
                             │ HTTP/JSON
┌────────────────────────────▼────────────────────────────────────┐
│                      Django Backend (API)                        │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────┐  │
│  │  API Views   │  │   Service    │  │   Celery Task        │  │
│  │ admin_views  │─▶│ Reindexing   │─▶│ reindex_website_     │  │
│  │              │  │   Service    │  │     google           │  │
│  └──────────────┘  └──────────────┘  └──────────────────────┘  │
└────────────────────────────┬────────────────────────────────────┘
                             │
        ┌────────────────────┼────────────────────┐
        │                    │                    │
┌───────▼────────┐  ┌────────▼────────┐  ┌───────▼──────────┐
│   PostgreSQL   │  │     Redis       │  │  Google Indexing │
│   (Task DB)    │  │  (Lock/Queue)   │  │      API         │
└────────────────┘  └─────────────────┘  └──────────────────┘
```

### Data Flow

1. **User Initiates**: User submits re-indexing request via UI
2. **API Endpoint**: POST request creates `GoogleReindexingTask` in database
3. **Celery Task**: Background task is queued with task ID
4. **URL Collection**: Service collects all active content URLs with language variants
5. **Batch Processing**: URLs processed in batches of 50
6. **Rate Limiting**: Token bucket algorithm ensures 200 req/min limit
7. **Google API**: Each URL submitted to Google Indexing API
8. **Progress Update**: Database updated after each URL submission
9. **Status Polling**: Frontend polls status endpoint every 2 seconds
10. **Completion**: Email sent, task marked complete

## Database Schema

### GoogleReindexingTask Model

```python
class GoogleReindexingTask(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES)
    content_type = models.CharField(max_length=10, choices=CONTENT_TYPE_CHOICES)
    total_urls = models.IntegerField(default=0)
    submitted_urls = models.IntegerField(default=0)
    successful_urls = models.IntegerField(default=0)
    failed_urls = models.IntegerField(default=0)
    error_log = models.TextField(default='[]')  # JSON array
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    initiated_by = models.ForeignKey(User, on_delete=models.SET_NULL)
    sitemap_included = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
```

### Indexes

- Primary: `id` (UUID)
- `created_at` (DESC) - For history queries
- `status, created_at` (DESC) - For active task queries

## Service Layer

### GoogleReindexingService

**Purpose**: Encapsulate all re-indexing business logic

**Key Methods**:
- `initiate_reindexing()`: Create new task, validate no concurrent operations
- `get_active_urls()`: Collect content URLs with language variants
- `submit_url_batch()`: Submit batch of URLs with rate limiting
- `get_task_status()`: Get real-time task information
- `cancel_task()`: Cancel running operation
- `get_reindexing_history()`: Query past operations

**Design Decisions**:
- Stateless service (no instance variables except rate limiter)
- Rate limiter is instance-specific (not shared across requests)
- Direct database access for performance
- Generator-based URL collection for memory efficiency

### Rate Limiter

**Algorithm**: Token Bucket
- Starts with 200 tokens (requests per minute)
- Refills at rate of 200 tokens/minute
- Blocks when insufficient tokens available
- Smooth rate distribution over time

**Implementation**:
```python
class RateLimiter:
    def __init__(self, rate_per_minute=200):
        self.rate_per_minute = rate_per_minute
        self.tokens = rate_per_minute
        self.last_update = time.time()
    
    def acquire(self, tokens=1):
        # Refill tokens based on time passed
        # Block if insufficient tokens
        # Return wait time
```

## Celery Task

### Task Configuration

```python
@shared_task(bind=True, max_retries=0, time_limit=3600)
def reindex_website_google(self, task_id, content_type, include_sitemap):
    # Task implementation
```

**Parameters**:
- `bind=True`: Bind task instance to first argument
- `max_retries=0`: Don't retry failed tasks (idempotent by design)
- `time_limit=3600`: 1 hour maximum execution time

### Task Locking

**Redis-based lock** prevents concurrent operations:
```python
REINDEX_LOCK_KEY = 'google_reindex_lock'
lock_acquired = cache.add(REINDEX_LOCK_KEY, task_id, timeout=3600)
```

**Benefits**:
- Prevents race conditions
- Survives worker restarts
- Automatic expiration

### Task Workflow

1. Acquire Redis lock
2. Mark task as `in_progress`
3. Collect all URLs
4. Process in batches of 50
5. Check for cancellation after each batch
6. Update progress in database
7. Ping sitemap (optional)
8. Send email notification
9. Mark task as `completed`/`failed`
10. Release lock

### Error Handling

**Strategy**: Continue on individual failures, log errors
- Individual URL failures don't stop the batch
- Errors logged to `error_log` field (JSON)
- Task marked `failed` only on critical errors
- Partial results always saved

## API Endpoints

### Design Principles
- RESTful URL structure
- JSON request/response
- Staff-only access
- CSRF protection
- Consistent error format

### Security

**Authentication**:
```python
@login_required
def endpoint(request):
    if not request.user.is_staff:
        return JsonResponse({'error': 'Permission denied'}, status=403)
```

**CSRF Protection**:
- All POST requests require CSRF token
- Token included in form or header
- Django middleware validates

**Rate Limiting**:
- API rate limiting not implemented (staff-only access)
- Google API rate limiting handled by service

## Frontend Implementation

### HTMX Integration

The UI uses HTMX for:
- Form submission
- Status polling
- Dynamic updates
- Modal interactions

### JavaScript Functions

**Core Functions**:
- `startReindexing()`: Initiate operation
- `updateStatus()`: Poll status endpoint
- `cancelReindex()`: Cancel operation
- `loadReindexHistory()`: Refresh history table

**Polling Strategy**:
- Poll every 2 seconds during `in_progress`
- Stop polling on completion/failure/cancellation
- Update progress bar, statistics, error log

### Progress Modal

**Features**:
- Bootstrap modal with backdrop
- Real-time progress bar
- Statistics cards (total, submitted, successful, failed)
- Time estimate
- Error log (last 10 errors)
- Cancel button

## Email Notifications

### Templates

Two templates for multi-part email:
- `emails/reindex_complete.html`: HTML version
- `emails/reindex_complete.txt`: Plain text version

### Context Variables

```python
context = {
    'task': task,
    'user': task.initiated_by,
    'status_text': 'Success|Partial|Failed',
    'error_summary': {...},
    'success_rate': 99.0,
}
```

### Sending

```python
from django.core.mail import send_mail

send_mail(
    subject=subject,
    message=text_message,
    from_email=settings.DEFAULT_FROM_EMAIL,
    recipient_list=[user.email],
    html_message=html_message,
)
```

## Configuration

### Required Settings

```python
# settings.py

# Google API Configuration
GOOGLE_SERVICE_ACCOUNT_FILE = '/path/to/service-account.json'

# Email Configuration
EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
EMAIL_HOST = 'smtp.gmail.com'
EMAIL_PORT = 587
EMAIL_USE_TLS = True
EMAIL_HOST_USER = 'your-email@gmail.com'
EMAIL_HOST_PASSWORD = 'your-password'
DEFAULT_FROM_EMAIL = 'noreply@yourdomain.com'

# Celery Configuration
CELERY_BROKER_URL = 'redis://localhost:6379/0'
CELERY_RESULT_BACKEND = 'redis://localhost:6379/0'

# Redis Configuration (for locking)
CACHES = {
    'default': {
        'BACKEND': 'django_redis.cache.RedisCache',
        'LOCATION': 'redis://localhost:6379/0',
    }
}
```

### Celery Task Routing

Add to task routes:
```python
CELERY_TASK_ROUTES = {
    'apps.frontend_api.tasks.reindex_website_google': {
        'queue': 'default'  # or dedicated 'seo' queue
    },
}
```

## Performance Considerations

### Database

**Optimizations**:
- Indexes on frequently queried fields
- Bulk updates avoided (use individual updates for progress)
- `select_related()` for user lookups
- `iterator()` for large URL collections

**Query Patterns**:
```python
# Efficient URL collection
ContentItem.objects.filter(is_active=True).iterator(chunk_size=500)

# History with user
GoogleReindexingTask.objects.select_related('initiated_by').order_by('-created_at')[:10]
```

### Memory

**Strategies**:
- Iterator for large collections
- Batch processing (50 URLs at a time)
- No in-memory URL storage (stream processing)
- Error log pruning (last 10 errors in API)

### Scalability

**Current Limits**:
- 10,000 URLs: ~60-70 minutes
- Single operation at a time (by design)
- Redis lock prevents scaling to multiple workers

**Future Improvements**:
- Distributed locking for multi-worker support
- Parallel batch processing
- Configurable batch size
- Priority queue for urgent re-indexing

## Monitoring

### Logging

**Log Levels**:
- `INFO`: Task start/completion, batch progress
- `WARNING`: Individual URL failures
- `ERROR`: API errors, task failures
- `DEBUG`: Rate limiter behavior

**Log Locations**:
- Django logs: Task creation, API calls
- Celery logs: Task execution, errors
- Redis logs: Lock acquisition/release

### Metrics

**Track**:
- Task completion rate
- Average success rate
- Processing time per URL
- Error frequency by type
- Queue depth

**Tools**:
- Django Debug Toolbar (development)
- Celery Flower (production)
- Custom dashboard (admin analytics)

## Testing

### Unit Tests

**Coverage**:
- `RateLimiter` class
- `GoogleReindexingService` methods
- `GoogleReindexingTask` model methods
- API endpoint logic

**Run Tests**:
```bash
python manage.py test apps.frontend_api.test_reindexing
```

### Integration Tests

**Scenarios**:
- End-to-end re-indexing flow
- Concurrent operation prevention
- Cancellation mid-process
- Error handling

**Mocking**:
- Mock Google API calls
- Mock Celery task execution
- Mock email sending

### Load Tests

**Scenarios**:
- 10,000 URLs
- Network latency simulation
- API error simulation
- Database connection pool saturation

## Maintenance

### Regular Tasks

**Daily**:
- Monitor error rates
- Check Celery queue depth

**Weekly**:
- Review completed task success rates
- Clean up old task records (optional)

**Monthly**:
- Analyze error patterns
- Review performance metrics
- Update documentation

### Troubleshooting

**Common Issues**:

1. **Task stuck in pending**
   - Check Celery worker is running
   - Check Redis connection
   - Review Celery logs

2. **High failure rate**
   - Verify Google API credentials
   - Check API quota
   - Review error log patterns

3. **Slow processing**
   - Check network latency
   - Review rate limiter settings
   - Optimize URL collection

### Database Maintenance

**Cleanup Old Tasks**:
```sql
-- Keep last 3 months of history
DELETE FROM frontend_api_googlereindexingtask
WHERE created_at < NOW() - INTERVAL '3 months';
```

**Reindex for Performance**:
```sql
REINDEX TABLE frontend_api_googlereindexingtask;
```

## Security

### Threat Model

**Threats**:
- Unauthorized access to re-indexing
- CSRF attacks
- DoS via excessive re-indexing
- Information disclosure in error messages

**Mitigations**:
- Staff-only access enforcement
- CSRF token validation
- Single concurrent operation limit
- Sanitized error messages
- Rate limiting at service level

### Best Practices

1. **Keep credentials secure**
   - Store service account file outside repository
   - Use environment variables
   - Restrict file permissions

2. **Monitor access**
   - Log all re-indexing operations
   - Track initiating user
   - Alert on suspicious patterns

3. **Validate inputs**
   - Whitelist content_type values
   - Validate UUID format
   - Sanitize user inputs

## Future Enhancements

### Planned Features

1. **Selective URL Re-indexing**
   - Re-index specific content items
   - Re-index by date range
   - Re-index failed URLs only

2. **Scheduling**
   - Cron-based automatic re-indexing
   - Configurable schedule
   - Off-peak hour optimization

3. **Analytics**
   - Success rate trends
   - Processing time analytics
   - Error pattern analysis
   - Google indexing confirmation

4. **Advanced Error Handling**
   - Automatic retry for transient errors
   - Smart error categorization
   - Suggested fixes for common errors

### Technical Debt

- Add comprehensive API documentation
- Implement request/response schemas
- Add more granular permissions
- Optimize URL collection query
- Add more comprehensive tests

## Resources

### External Documentation

- [Google Indexing API](https://developers.google.com/search/apis/indexing-api/v3/quickstart)
- [Celery Best Practices](https://docs.celeryproject.org/en/stable/userguide/tasks.html)
- [Django Caching](https://docs.djangoproject.com/en/stable/topics/cache/)
- [Redis Locking Patterns](https://redis.io/topics/distlock)

### Internal Documentation

- `GOOGLE_REINDEXING_ADMIN_GUIDE.md`: User guide
- `GOOGLE_REINDEXING_API_REFERENCE.md`: API documentation
- `GOOGLE_INDEXING_API_SETUP.md`: Initial setup guide
