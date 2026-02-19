# RESTful Upload API Documentation

## Overview

The Christian Library RESTful Upload API allows programmatic content uploads without CSRF tokens. It supports video, audio, and PDF files with intelligent queue management and rate limit handling.

## Authentication

All API requests require authentication using the `X-API-Secret-Key` header.

### Configuration

Set the API secret key in your environment:

```bash
# Generate a secure key
python -c "import secrets; print(secrets.token_urlsafe(32))"

# Set in environment
export API_SECRET_KEY="your-generated-secret-key"
```

### Request Headers

```
X-API-Secret-Key: your-secret-key-here
Content-Type: multipart/form-data
```

## Rate Limiting

- **Limit**: 100 requests per hour per API key
- **Response**: 429 Too Many Requests when exceeded

## Endpoints

### 1. Single File Upload

Upload a single file with optional metadata.

**Endpoint**: `POST /api/v1/upload/`

**Request (Minimal - File Only)**:
```bash
curl -X POST https://your-domain.com/api/v1/upload/ \
  -H "X-API-Secret-Key: your-secret-key" \
  -F "file=@/path/to/video.mp4"
```

**Request (Full - With Metadata)**:
```bash
curl -X POST https://your-domain.com/api/v1/upload/ \
  -H "X-API-Secret-Key: your-secret-key" \
  -F "file=@/path/to/sermon.mp3" \
  -F "title_ar=عظة عن المحبة" \
  -F "title_en=Sermon on Love" \
  -F "description_ar=عظة رائعة" \
  -F "description_en=Wonderful sermon" \
  -F "transcript=Full transcript text..."
```

**Request (PDF with Book Content)**:
```bash
curl -X POST https://your-domain.com/api/v1/upload/ \
  -H "X-API-Secret-Key: your-secret-key" \
  -F "file=@/path/to/book.pdf" \
  -F "doc_file=@/path/to/content.docx" \
  -F "title_ar=كتاب الحياة الروحية"
```

**Response (202 Accepted - Queued)**:
```json
{
  "queue_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "queued",
  "queue_status": "waiting",
  "queue_position": 3,
  "content_type": "audio",
  "file_name": "sermon.mp3",
  "doc_file_name": null,
  "estimated_processing_time": "PT5M"
}
```

**Response (201 Created - Processing Immediately)**:
```json
{
  "queue_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "processing",
  "queue_status": "ready",
  "queue_position": 1,
  "content_type": "audio",
  "file_name": "sermon.mp3",
  "doc_file_name": null,
  "estimated_processing_time": "PT5M"
}
```

### 2. Bulk Upload

Upload multiple files (up to 20) in one request.

**Endpoint**: `POST /api/v1/upload/bulk/`

**Request**:
```bash
curl -X POST https://your-domain.com/api/v1/upload/bulk/ \
  -H "X-API-Secret-Key: your-secret-key" \
  -F "files=@/path/to/file1.mp3" \
  -F "files=@/path/to/file2.mp3" \
  -F "files=@/path/to/file3.mp3"
```

**Response (202 Accepted)**:
```json
{
  "queue_items": [
    {
      "queue_id": "550e8400-e29b-41d4-a716-446655440000",
      "status": "queued",
      "queue_status": "waiting",
      "queue_position": 1,
      "content_type": "audio",
      "file_name": "file1.mp3",
      "doc_file_name": null,
      "estimated_processing_time": "PT5M"
    },
    {
      "queue_id": "660e8400-e29b-41d4-a716-446655440001",
      "status": "queued",
      "queue_status": "waiting",
      "queue_position": 2,
      "content_type": "audio",
      "file_name": "file2.mp3",
      "doc_file_name": null,
      "estimated_processing_time": "PT5M"
    }
  ],
  "total": 3,
  "queued": 2,
  "processing": 1
}
```

### 3. Queue Status

Check the status of a queued upload.

**Endpoint**: `GET /api/v1/queue/status/<queue_id>/`

**Request**:
```bash
curl -X GET https://your-domain.com/api/v1/queue/status/550e8400-e29b-41d4-a716-446655440000/ \
  -H "X-API-Secret-Key: your-secret-key"
```

**Response**:
```json
{
  "queue_id": "550e8400-e29b-41d4-a716-446655440000",
  "file_name": "sermon.mp3",
  "content_type": "audio",
  "file_size_mb": 12.5,
  "status": "processing",
  "queue_status": "ready",
  "scheduled_for": null,
  "delay_count": 0,
  "priority": 0,
  "queue_position": 1,
  "content_item_id": null,
  "error_message": null,
  "created_at": "2026-02-19T17:00:00Z",
  "processing_started_at": "2026-02-19T17:05:00Z",
  "completed_at": null
}
```

### 4. Queue List

List all queue items with filtering.

**Endpoint**: `GET /api/v1/queue/`

**Request**:
```bash
curl -X GET "https://your-domain.com/api/v1/queue/?status=queued&limit=20" \
  -H "X-API-Secret-Key: your-secret-key"
```

**Query Parameters**:
- `status`: Filter by status (pending, queued, processing, completed, failed, rate_limited, cancelled)
- `content_type`: Filter by content type (video, audio, pdf)
- `limit`: Results per page (default 20, max 100)
- `offset`: Pagination offset

**Response**:
```json
{
  "total": 150,
  "limit": 20,
  "offset": 0,
  "results": [
    {
      "id": "550e8400-e29b-41d4-a716-446655440000",
      "file_name": "sermon.mp3",
      "content_type": "audio",
      "status": "queued",
      "queue_status": "waiting",
      "queue_position": 1,
      "created_at": "2026-02-19T17:00:00Z"
    }
  ]
}
```

### 5. Promote Queue Item (Admin)

Promote a queue item to skip the queue and process immediately.

**Endpoint**: `POST /api/v1/queue/<queue_id>/promote/`

**Request**:
```bash
curl -X POST https://your-domain.com/api/v1/queue/550e8400-e29b-41d4-a716-446655440000/promote/ \
  -H "X-API-Secret-Key: your-secret-key"
```

**Response**:
```json
{
  "message": "Queue item promoted",
  "item": {
    "queue_id": "550e8400-e29b-41d4-a716-446655440000",
    "status": "queued",
    "priority": 1000,
    "queue_position": 1
  }
}
```

### 6. Cancel Queue Item (Admin)

Cancel a queued upload.

**Endpoint**: `DELETE /api/v1/queue/<queue_id>/cancel/`

**Request**:
```bash
curl -X DELETE https://your-domain.com/api/v1/queue/550e8400-e29b-41d4-a716-446655440000/cancel/ \
  -H "X-API-Secret-Key: your-secret-key"
```

**Response**: `204 No Content`

## Queue Management

### Status Workflow

```
pending → queued → processing → completed
         ↓
    rate_limited (scheduled for 3:00 AM)
         ↓
    cancelled (after 7 delays)
```

### Queue Statuses

- **waiting**: Waiting in queue
- **delayed**: Scheduled for later (rate limit)
- **ready**: Ready to process

### Concurrency Control

Only one item per content type processes at a time:
- One video processing
- One audio processing
- One PDF processing

This prevents resource contention and ensures stable processing.

### Rate Limit Handling

When Gemini API rate limit is exceeded:
1. Item is marked as `rate_limited`
2. Scheduled for next day at 3:00 AM
3. `delay_count` incremented
4. After 7 delays, item is automatically cancelled

## Supported File Types

### Video
- `.mp4`, `.mov`, `.avi`, `.mkv`, `.webm`
- Max size: 2GB

### Audio
- `.mp3`, `.wav`, `.m4a`, `.aac`, `.ogg`
- Max size: 2GB

### PDF
- `.pdf`
- Max size: 2GB
- Optional: `.docx` for book content extraction

## Optional Metadata Fields

All metadata fields are optional:

- `title_ar`: Arabic title (max 200 characters)
- `title_en`: English title (max 200 characters)
- `description_ar`: Arabic description
- `description_en`: English description
- `tags`: List of tag UUIDs
- `seo_keywords_ar`: Arabic SEO keywords
- `seo_keywords_en`: English SEO keywords
- `transcript`: Full transcript text
- `notes`: Additional notes

## Error Responses

### 400 Bad Request
```json
{
  "errors": {
    "file": ["File size exceeds maximum of 2048MB"]
  }
}
```

### 401 Unauthorized
```json
{
  "detail": "Authentication credentials were not provided."
}
```

### 403 Forbidden
```json
{
  "detail": "Invalid API key"
}
```

### 429 Too Many Requests
```json
{
  "detail": "Rate limit exceeded (100 requests/hour)"
}
```

### 500 Internal Server Error
```json
{
  "error": "Internal server error during upload"
}
```

## Example Scripts

### Python

```python
import requests

API_URL = "https://your-domain.com/api/v1"
API_KEY = "your-secret-key"

headers = {
    "X-API-Secret-Key": API_KEY
}

# Single upload
with open("sermon.mp3", "rb") as f:
    files = {"file": f}
    data = {
        "title_ar": "عظة عن المحبة",
        "title_en": "Sermon on Love"
    }
    response = requests.post(
        f"{API_URL}/upload/",
        headers=headers,
        files=files,
        data=data
    )
    print(response.json())
    queue_id = response.json()["queue_id"]

# Check status
response = requests.get(
    f"{API_URL}/queue/status/{queue_id}/",
    headers=headers
)
print(response.json())
```

### JavaScript (Node.js)

```javascript
const axios = require('axios');
const FormData = require('form-data');
const fs = require('fs');

const API_URL = 'https://your-domain.com/api/v1';
const API_KEY = 'your-secret-key';

async function uploadFile() {
  const form = new FormData();
  form.append('file', fs.createReadStream('sermon.mp3'));
  form.append('title_ar', 'عظة عن المحبة');
  form.append('title_en', 'Sermon on Love');

  const response = await axios.post(`${API_URL}/upload/`, form, {
    headers: {
      'X-API-Secret-Key': API_KEY,
      ...form.getHeaders()
    }
  });

  console.log(response.data);
  return response.data.queue_id;
}

async function checkStatus(queueId) {
  const response = await axios.get(
    `${API_URL}/queue/status/${queueId}/`,
    {
      headers: {
        'X-API-Secret-Key': API_KEY
      }
    }
  );

  console.log(response.data);
}

// Usage
uploadFile().then(queueId => {
  setTimeout(() => checkStatus(queueId), 5000);
});
```

## Best Practices

1. **Always check queue status** after upload to track processing
2. **Handle rate limits gracefully** - wait for 3:00 AM processing
3. **Use bulk upload** for multiple files to reduce API calls
4. **Set appropriate timeouts** - processing can take 5-15 minutes
5. **Monitor queue position** to estimate wait time
6. **Keep API key secure** - rotate periodically
7. **Validate files client-side** before upload to save quota

## Monitoring

Use the admin dashboard to:
- View queue statistics
- Monitor processing status
- Promote urgent items
- Cancel failed items
- Track rate limit delays

## Support

For issues or questions, contact the system administrator or check the logs at `/admin/tasks/`.
