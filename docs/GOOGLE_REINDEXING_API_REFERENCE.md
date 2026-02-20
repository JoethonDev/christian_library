# Google Re-indexing API Reference

## Base URL
All endpoints are relative to: `/dashboard/seo/reindex/`

## Authentication
All endpoints require:
- User authentication (`@login_required`)
- Staff permission (`is_staff=True`)

## Endpoints

### 1. Initiate Re-indexing

**POST** `/dashboard/seo/reindex/`

Initiates a new Google Search Console re-indexing operation.

#### Request Body
```json
{
  "content_type": "all|video|audio|pdf",  // optional, default: "all"
  "include_sitemap": true|false            // optional, default: true
}
```

#### Response (Success)
```json
{
  "success": true,
  "task_id": "uuid-string",
  "total_urls": 1500,
  "estimated_duration": 900,  // seconds
  "message": "Re-indexing task initiated successfully"
}
```

#### Response (Error)
```json
{
  "success": false,
  "error": "Error message"
}
```

#### Status Codes
- `200`: Success
- `400`: Bad request (invalid content_type or concurrent operation)
- `403`: Permission denied
- `500`: Server error

#### Example
```bash
curl -X POST https://example.com/dashboard/seo/reindex/ \
  -H "Content-Type: application/json" \
  -H "X-CSRFToken: <csrf-token>" \
  -d '{"content_type": "video", "include_sitemap": true}'
```

---

### 2. Get Task Status

**GET** `/dashboard/seo/reindex/status/<task_id>/`

Retrieves real-time status of a re-indexing task.

#### URL Parameters
- `task_id` (UUID): The task identifier returned from initiate endpoint

#### Response
```json
{
  "success": true,
  "task_id": "uuid-string",
  "status": "pending|in_progress|completed|failed|cancelled",
  "content_type": "all|video|audio|pdf",
  "progress": 45.5,              // percentage (0-100)
  "total": 1500,
  "submitted": 683,
  "successful": 670,
  "failed": 13,
  "estimated_remaining": 750,     // seconds, null if not available
  "error_summary": {
    "api_error": 10,
    "rate_limit": 3
  },
  "success_rate": 98.1,           // percentage
  "started_at": "2024-01-15T10:30:00Z",
  "completed_at": null,           // or ISO timestamp if completed
  "created_at": "2024-01-15T10:29:45Z",
  "errors": [                     // Last 10 errors
    {
      "url": "https://example.com/video/123",
      "type": "api_error",
      "message": "URL not found",
      "timestamp": "2024-01-15T10:35:22Z"
    }
  ]
}
```

#### Status Codes
- `200`: Success
- `403`: Permission denied
- `404`: Task not found
- `500`: Server error

#### Example
```bash
curl -X GET https://example.com/dashboard/seo/reindex/status/abc-123-def/ \
  -H "X-CSRFToken: <csrf-token>"
```

---

### 3. Cancel Task

**POST** `/dashboard/seo/reindex/cancel/<task_id>/`

Cancels a running re-indexing task.

#### URL Parameters
- `task_id` (UUID): The task identifier

#### Response (Success)
```json
{
  "success": true,
  "cancelled": true,
  "message": "Re-indexing task cancelled successfully",
  "partial_results": {
    "submitted": 250,
    "successful": 240,
    "failed": 10
  }
}
```

#### Response (Error)
```json
{
  "success": false,
  "error": "Task cannot be cancelled (already completed or not found)"
}
```

#### Status Codes
- `200`: Success
- `400`: Cannot cancel (task completed/failed/not found)
- `403`: Permission denied
- `500`: Server error

#### Notes
- Can only cancel tasks in 'pending' or 'in_progress' status
- Partial results are saved
- Task status is updated to 'cancelled'

#### Example
```bash
curl -X POST https://example.com/dashboard/seo/reindex/cancel/abc-123-def/ \
  -H "X-CSRFToken: <csrf-token>"
```

---

### 4. Get History

**GET** `/dashboard/seo/reindex/history/`

Retrieves history of past re-indexing operations.

#### Query Parameters
- `limit` (integer): Maximum tasks to return (default: 10, max: 50)

#### Response
```json
{
  "success": true,
  "tasks": [
    {
      "task_id": "uuid-string",
      "status": "completed",
      "content_type": "all",
      "total_urls": 1500,
      "successful_urls": 1485,
      "failed_urls": 15,
      "success_rate": 99.0,
      "initiated_by": "admin_username",
      "started_at": "2024-01-15T10:30:00Z",
      "completed_at": "2024-01-15T11:45:00Z",
      "created_at": "2024-01-15T10:29:45Z"
    }
  ],
  "count": 1
}
```

#### Status Codes
- `200`: Success
- `403`: Permission denied
- `500`: Server error

#### Example
```bash
curl -X GET "https://example.com/dashboard/seo/reindex/history/?limit=20" \
  -H "X-CSRFToken: <csrf-token>"
```

---

### 5. Re-indexing Page (UI)

**GET** `/dashboard/seo/reindex/page/`

Renders the Google re-indexing control panel HTML page.

#### Response
HTML page with re-indexing controls and history.

#### Status Codes
- `200`: Success
- `302`: Redirect if not staff (with error message)

---

## Data Models

### GoogleReindexingTask

| Field | Type | Description |
|-------|------|-------------|
| id | UUID | Primary key |
| status | String | pending, in_progress, completed, failed, cancelled |
| content_type | String | all, video, audio, pdf |
| total_urls | Integer | Total URLs to process |
| submitted_urls | Integer | URLs submitted so far |
| successful_urls | Integer | Successfully submitted URLs |
| failed_urls | Integer | Failed URL submissions |
| error_log | Text (JSON) | Array of error objects |
| started_at | DateTime | When task started processing |
| completed_at | DateTime | When task finished |
| initiated_by | ForeignKey | User who started the task |
| sitemap_included | Boolean | Whether sitemap ping is included |
| created_at | DateTime | When task was created |
| updated_at | DateTime | Last update timestamp |

### Error Log Format

```json
[
  {
    "url": "https://example.com/content/123",
    "type": "api_error|rate_limit|exception|task_failure",
    "message": "Error description",
    "timestamp": "2024-01-15T10:35:22Z"
  }
]
```

---

## Rate Limiting

- **Google API Limit**: 200 requests per minute
- **Implementation**: Token bucket algorithm
- **Automatic**: Rate limiting is enforced automatically by the service
- **Retry Logic**: Automatic retry with exponential backoff on rate limit errors

---

## Webhooks / Callbacks

The system does not support webhooks. Instead:
- Poll the status endpoint for updates (recommended: every 2-5 seconds)
- Email notifications are sent on completion
- Frontend can use HTMX or JavaScript polling for real-time updates

---

## Error Codes

| Error Type | Description | Possible Causes |
|------------|-------------|-----------------|
| api_error | Google API returned error | Invalid URL, URL not accessible, API quota exceeded |
| rate_limit | Rate limit exceeded | Too many concurrent requests (rare with built-in limiting) |
| exception | Unexpected error | Network issues, server errors |
| task_failure | Task-level failure | Database error, Redis connection failed |

---

## Best Practices

### Polling
- Poll status endpoint every 2-5 seconds during active operation
- Stop polling when status is 'completed', 'failed', or 'cancelled'
- Implement exponential backoff if polling too frequently

### Error Handling
- Check `success` field in all responses
- Display user-friendly error messages
- Log detailed errors for debugging
- Implement retry logic for transient errors

### Performance
- Use content_type filters to reduce processing time
- Schedule during off-peak hours for large operations
- Monitor error rates and adjust accordingly

### Security
- Always include CSRF token in POST requests
- Validate staff permission on frontend
- Don't expose sensitive information in error messages
- Use HTTPS for all API calls

---

## Code Examples

### JavaScript (Frontend)

```javascript
// Initiate re-indexing
async function startReindexing(contentType, includeSitemap) {
  const response = await fetch('/dashboard/seo/reindex/', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-CSRFToken': getCsrfToken()
    },
    body: JSON.stringify({
      content_type: contentType,
      include_sitemap: includeSitemap
    })
  });
  
  const data = await response.json();
  if (data.success) {
    return data.task_id;
  } else {
    throw new Error(data.error);
  }
}

// Poll status
async function pollStatus(taskId) {
  const response = await fetch(`/dashboard/seo/reindex/status/${taskId}/`);
  const data = await response.json();
  
  if (data.success) {
    updateUI(data);
    
    // Continue polling if in progress
    if (data.status === 'in_progress' || data.status === 'pending') {
      setTimeout(() => pollStatus(taskId), 2000);
    }
  }
}

// Cancel task
async function cancelTask(taskId) {
  const response = await fetch(`/dashboard/seo/reindex/cancel/${taskId}/`, {
    method: 'POST',
    headers: {
      'X-CSRFToken': getCsrfToken()
    }
  });
  
  return await response.json();
}
```

### Python (Backend/Testing)

```python
from apps.frontend_api.services.google_reindexing_service import GoogleReindexingService

# Initialize service
service = GoogleReindexingService()

# Initiate re-indexing
task_id = service.initiate_reindexing(
    user=request.user,
    content_type='video',
    include_sitemap=True
)

# Get status
status = service.get_task_status(task_id)

# Cancel task
cancelled = service.cancel_task(task_id)

# Get history
history = service.get_reindexing_history(limit=10)
```

---

## Support

For API issues:
1. Check response `success` and `error` fields
2. Review task error_log for details
3. Verify Google API configuration
4. Check Celery worker status
5. Contact system administrator if issues persist

For feature requests or bug reports, please contact the development team.
