# Feature Implementation Plan: Google Re-indexing, RESTful Upload API, and Document Content Support

**Project:** Coptic Orthodox Digital Library  
**Version:** 1.0  
**Date:** February 19, 2026  
**Status:** Planning Phase  

---

## Executive Summary

This document outlines the implementation plan for three major features:

1. **Admin Endpoint for Full Website Re-indexing on Google Search Console** - Manual trigger for bulk URL submission
2. **RESTful API for Content Upload** - Simple secret key authentication for programmatic uploads without CSRF, with intelligent queue management and rate limit handling
3. **Document Content Support for ContentItem** - Support for uploading Word documents (.doc/.docx) as supplementary content that gets vectorized for search

---

## Table of Contents

1. [Feature 1: Google Re-indexing Admin Endpoint](#feature-1-google-re-indexing-admin-endpoint)
2. [Feature 2: RESTful Upload API](#feature-2-restful-upload-api)
3. [Feature 3: Document Content Support](#feature-3-document-content-support)
4. [Implementation Timeline](#implementation-timeline)
5. [Testing & Quality Assurance](#testing--quality-assurance)
6. [Deployment & Rollout](#deployment--rollout)

---

## Feature 1: Google Re-indexing Admin Endpoint

### Overview
Provide admin users with a manual control endpoint to trigger full website re-indexing on Google Search Console. This complements the existing automatic SEO change notifications by allowing bulk submission of all active content URLs.

### Requirements

#### Functional Requirements
- **FR-1.1:** Admin-only endpoint accessible via dashboard
- **FR-1.2:** Trigger re-indexing for all active content (videos, audios, PDFs)
- **FR-1.3:** Support selective re-indexing by content type
- **FR-1.4:** Batch processing to respect Google API rate limits (200 requests/minute)
- **FR-1.5:** Real-time progress tracking with status updates
- **FR-1.6:** Detailed logging of submission results (success/failure per URL)
- **FR-1.7:** Email notification on completion with summary report
- **FR-1.8:** Prevent concurrent re-indexing operations
- **FR-1.9:** Display last re-indexing timestamp and results

#### Non-Functional Requirements
- **NFR-1.1:** Must handle 10,000+ URLs without timeout
- **NFR-1.2:** Rate limiting: 200 requests/minute max
- **NFR-1.3:** Operation must be idempotent (safe to retry)
- **NFR-1.4:** Maximum execution time: 1 hour for full site
- **NFR-1.5:** Must not block other system operations

#### Technical Requirements
- **TR-1.1:** Uses existing Google Indexing API integration
- **TR-1.2:** Celery background task for async processing
- **TR-1.3:** Redis-based task locking to prevent duplicates
- **TR-1.4:** Database persistence of re-indexing history
- **TR-1.5:** RESTful API endpoint for frontend polling

---

### Architecture & Design

#### Backend Components

**1. New Model: `GoogleReindexingTask`**
```
Location: backend/apps/frontend_api/models.py

Fields:
- id (UUID, primary key)
- status (CharField: pending, in_progress, completed, failed, cancelled)
- content_type (CharField: all, video, audio, pdf - nullable)
- total_urls (IntegerField)
- submitted_urls (IntegerField - default: 0)
- successful_urls (IntegerField - default: 0)
- failed_urls (IntegerField - default: 0)
- error_log (TextField - JSON format)
- started_at (DateTimeField)
- completed_at (DateTimeField - nullable)
- initiated_by (ForeignKey to User)
- sitemap_included (BooleanField - whether to ping sitemap)
- created_at (DateTimeField - auto_now_add)
- updated_at (DateTimeField - auto_now)

Methods:
- get_progress_percentage()
- get_estimated_time_remaining()
- get_error_summary()
- mark_as_completed()
- mark_as_failed()
```

**2. New Service: `GoogleReindexingService`**
```
Location: backend/apps/frontend_api/services/google_reindexing_service.py

Class: GoogleReindexingService

Methods:
- initiate_reindexing(user, content_type=None, include_sitemap=True) -> task_id
- get_active_urls(content_type=None) -> List[Dict[str, str]]
- submit_url_batch(urls_batch, task_id) -> Tuple[int, int, List[Dict]]
- get_task_status(task_id) -> Dict
- cancel_task(task_id) -> bool
- get_reindexing_history(limit=10) -> QuerySet
- estimate_duration(total_urls) -> int (seconds)

Rate Limiting:
- Uses token bucket algorithm
- 200 requests/minute (Google limit)
- Automatic retry with exponential backoff on rate limit errors
```

**3. New Celery Task: `reindex_website_google`**
```
Location: backend/apps/frontend_api/tasks.py

Function: reindex_website_google(task_id, content_type=None, include_sitemap=True)

Workflow:
1. Fetch GoogleReindexingTask by ID
2. Mark status as 'in_progress'
3. Get all active content URLs (with language variants)
4. Batch URLs into groups of 50
5. For each batch:
   - Check for cancellation signal
   - Submit batch with rate limiting
   - Update task progress
   - Log errors
   - Sleep if needed to respect rate limits
6. Optionally ping sitemap at completion
7. Mark task as completed/failed
8. Send notification email to initiator

Error Handling:
- Retry failed URLs up to 3 times
- Continue on individual URL failures
- Log all errors with context
- Graceful cancellation support
```

**4. New API Endpoints**
```
Location: backend/apps/frontend_api/admin_views.py

Endpoints:

POST /dashboard/seo/reindex/
- Initiates re-indexing task
- Body: {"content_type": "all|video|audio|pdf", "include_sitemap": true}
- Response: {"task_id": "uuid", "estimated_duration": 3600, "total_urls": 1500}
- Auth: @login_required
- Permission: staff_member_required

GET /dashboard/seo/reindex/status/<task_id>/
- Returns real-time task status
- Response: {
    "status": "in_progress",
    "progress": 45.2,
    "submitted": 678,
    "successful": 670,
    "failed": 8,
    "total": 1500,
    "estimated_remaining": 1200,
    "errors": [...]
  }
- Auth: @login_required

POST /dashboard/seo/reindex/cancel/<task_id>/
- Cancels running task
- Response: {"cancelled": true, "partial_results": {...}}
- Auth: @login_required

GET /dashboard/seo/reindex/history/
- Returns past re-indexing operations
- Response: {"tasks": [...], "pagination": {...}}
- Auth: @login_required
```

**5. URL Configuration**
```
Location: backend/apps/frontend_api/urls.py

Add to urlpatterns:
path('dashboard/seo/reindex/', admin_views.initiate_google_reindexing, name='initiate_google_reindexing'),
path('dashboard/seo/reindex/status/<uuid:task_id>/', admin_views.reindex_status, name='reindex_status'),
path('dashboard/seo/reindex/cancel/<uuid:task_id>/', admin_views.cancel_reindex, name='cancel_reindex'),
path('dashboard/seo/reindex/history/', admin_views.reindex_history, name='reindex_history'),
```

#### Frontend Components

**1. Re-indexing Control Panel**
```
Location: backend/templates/admin/seo_reindex.html

UI Elements:
- Header: "Google Search Console Re-indexing"
- Content Type Selector (Radio buttons: All Content, Videos Only, Audios Only, PDFs Only)
- "Include Sitemap Ping" checkbox
- Estimated URLs count (dynamic based on selection)
- Warning message about Google API rate limits
- "Start Re-indexing" button (large, primary)
- Last re-indexing info card (timestamp, status, results)
- Re-indexing history table

HTMX Integration:
- Real-time progress bar
- Live status updates (every 2 seconds)
- Error log streaming
```

**2. Progress Modal Component**
```
Location: backend/templates/admin/includes/reindex_progress_modal.html

Features:
- Progress bar with percentage
- Submitted/Successful/Failed counters
- Estimated time remaining
- Live error log (scrollable)
- "Cancel Task" button
- "View Details" link to full report
- Auto-refresh via HTMX polling
```

**3. SEO Dashboard Integration**
```
Location: backend/templates/admin/seo_dashboard.html

Add Section:
- "Google Re-indexing" card in dashboard
- Quick action button "Re-index Now"
- Last operation status badge
- Success rate indicator
```

---

### Implementation Phases

#### Phase 1: Backend Foundation (Week 1)

**Deliverables:**
- [ ] Create `GoogleReindexingTask` model
- [ ] Write and apply database migration
- [ ] Implement `GoogleReindexingService` class
- [ ] Add rate limiting logic with token bucket
- [ ] Write unit tests for service methods
- [ ] Create Celery task `reindex_website_google`
- [ ] Add task locking mechanism (Redis)

**Testing:**
- Unit tests: Service methods (URL collection, batching, rate limiting)
- Integration tests: Celery task execution with mock Google API
- Load tests: Handle 10,000 URLs efficiently

**Acceptance Criteria:**
- ✅ Service can collect all active content URLs with language variants
- ✅ Rate limiting stays under 200 req/min
- ✅ Task persists progress and can be resumed
- ✅ Concurrent task prevention works
- ✅ All tests pass with >90% coverage

---

#### Phase 2: API Endpoints (Week 1-2)

**Deliverables:**
- [ ] Implement POST `/dashboard/seo/reindex/` endpoint
- [ ] Implement GET `/dashboard/seo/reindex/status/<task_id>/` endpoint
- [ ] Implement POST `/dashboard/seo/reindex/cancel/<task_id>/` endpoint
- [ ] Implement GET `/dashboard/seo/reindex/history/` endpoint
- [ ] Add permission decorators and validation
- [ ] Write API documentation
- [ ] Add comprehensive error handling

**Testing:**
- API tests: All endpoints with various scenarios
- Permission tests: Unauthorized access attempts
- Edge case tests: Invalid task IDs, cancelled tasks, etc.

**Acceptance Criteria:**
- ✅ All endpoints return correct status codes
- ✅ Non-admin users cannot access endpoints
- ✅ Validation errors return clear messages
- ✅ API documentation is complete
- ✅ Postman/Insomnia collection provided

---

#### Phase 3: Frontend UI (Week 2)

**Deliverables:**
- [ ] Create `seo_reindex.html` template
- [ ] Implement HTMX progress polling
- [ ] Create progress modal component
- [ ] Add to SEO dashboard navigation
- [ ] Implement real-time updates
- [ ] Add error handling and user feedback
- [ ] Mobile responsive design

**Testing:**
- UI tests: All user interactions
- HTMX tests: Polling and updates
- Responsive tests: Mobile, tablet, desktop
- Accessibility tests: ARIA labels, keyboard navigation

**Acceptance Criteria:**
- ✅ Admin can initiate re-indexing from UI
- ✅ Progress updates in real-time without page refresh
- ✅ Errors display clearly to user
- ✅ Cancel button works instantly
- ✅ History displays correctly
- ✅ Mobile UI is usable

---

#### Phase 4: Email Notifications (Week 2)

**Deliverables:**
- [ ] Create email templates (HTML + plain text)
- [ ] Implement notification service
- [ ] Add to Celery task completion
- [ ] Test email delivery

**Email Template:**
```
Subject: Google Re-indexing Complete - [Success/Partial/Failed]

Body:
- Summary: Total, Successful, Failed
- Task Details: Content type, duration
- Error Summary (if any)
- Next Steps recommendations
- Link to view full report
```

**Testing:**
- Email delivery tests
- Template rendering tests
- Different status scenarios

**Acceptance Criteria:**
- ✅ Email sent on task completion
- ✅ Email contains accurate information
- ✅ Links in email work correctly
- ✅ HTML and plain text versions both render well

---

### Output Files & Documentation

**Code Files Created:**
1. `backend/apps/frontend_api/models.py` - Add `GoogleReindexingTask` model
2. `backend/apps/frontend_api/services/google_reindexing_service.py` - New service
3. `backend/apps/frontend_api/tasks.py` - Add `reindex_website_google` task
4. `backend/apps/frontend_api/admin_views.py` - Add 4 new endpoints
5. `backend/apps/frontend_api/urls.py` - Add 4 new URL patterns
6. `backend/templates/admin/seo_reindex.html` - New template
7. `backend/templates/admin/includes/reindex_progress_modal.html` - New component
8. `backend/templates/emails/reindex_complete.html` - Email template
9. `backend/templates/emails/reindex_complete.txt` - Email template (plain)
10. `backend/apps/frontend_api/tests/test_reindexing.py` - Test suite
11. Migration file: `backend/apps/frontend_api/migrations/XXXX_add_google_reindexing_task.py`

**Documentation Files:**
1. `docs/GOOGLE_REINDEXING_ADMIN_GUIDE.md` - Admin user guide
2. `docs/GOOGLE_REINDEXING_API_REFERENCE.md` - API documentation
3. `docs/GOOGLE_REINDEXING_IMPLEMENTATION.md` - Technical implementation details

---

### Acceptance Criteria Summary

**Feature Complete When:**
- ✅ Admin can trigger full site re-indexing from dashboard
- ✅ Admin can select specific content types to re-index
- ✅ Progress displays in real-time with accurate percentages
- ✅ Rate limiting prevents Google API quota violations
- ✅ Failed URLs are logged with detailed error messages
- ✅ Admin receives email notification on completion
- ✅ Re-indexing history is viewable and filterable
- ✅ Operation can be cancelled mid-process
- ✅ System prevents concurrent re-indexing operations
- ✅ All URLs include language variants (en/ar)
- ✅ Sitemap ping can be optionally included
- ✅ Documentation is complete and accurate
- ✅ All tests pass with >85% code coverage

---

## Feature 2: RESTful Upload API

### Overview
Create a simplified RESTful API that allows programmatic content uploads without CSRF tokens using Django REST Framework. This enables external applications, scripts, and automation tools to upload content securely with intelligent queue management and rate limit handling.

### Requirements

#### Functional Requirements
- **FR-2.1:** Simple header-based authentication (X-API-Secret-Key)
- **FR-2.2:** Support single and multiple file uploads in one request
- **FR-2.3:** Accept all existing content types (video, audio, PDF)
- **FR-2.4:** Minimal payload support (file-only uploads accepted)
- **FR-2.5:** Optional doc_file parameter for book_content extraction
- **FR-2.6:** Optional metadata in request payload (all fields optional)
- **FR-2.7:** Return structured JSON responses with upload status
- **FR-2.8:** Support asynchronous processing with status tracking
- **FR-2.9:** Validate file size, type before processing
- **FR-2.10:** Queue management: Prevent concurrent processing of same content type
- **FR-2.11:** Rate limit handling: Auto-delay to next day 3:00 AM when Gemini quota exceeded
- **FR-2.12:** Maximum 7-day delay for rate-limited uploads
- **FR-2.13:** Admin dashboard for queue management (view, promote, cancel)
- **FR-2.14:** API key management from settings/environment

#### Non-Functional Requirements
- **NFR-2.1:** Support uploads up to 2GB per file
- **NFR-2.2:** Rate limiting: 100 requests/hour per API key
- **NFR-2.3:** Response time: <500ms for validation, async for processing
- **NFR-2.4:** Secure key validation
- **NFR-2.5:** HTTPS required for API calls

#### Technical Requirements
- **TR-2.1:** Django REST Framework (DRF) for all API endpoints
- **TR-2.2:** Simple header-based authentication
- **TR-2.3:** Multipart form-data support
- **TR-2.4:** JSON request/response format
- **TR-2.5:** Celery queue management with type-based locking
- **TR-2.6:** Redis for queue management and rate limit tracking
- **TR-2.7:** Scheduled tasks for delayed uploads (3:00 AM execution)

---

### Architecture & Design

#### Backend Components

**1. New Model: `APIUploadQueue`**
```
Location: backend/apps/media_manager/models.py

Fields:
- id (UUID, primary key)
- file_name (CharField)
- file_path (CharField - temp storage path)
- doc_file_path (CharField - nullable, for book_content)
- content_type (CharField - video/audio/pdf)
- file_size_mb (FloatField)
- metadata (JSONField - nullable, optional metadata)
- status (CharField - choices: pending, queued, processing, completed, failed, rate_limited, cancelled)
- queue_status (CharField - choices: waiting, delayed, ready)
- scheduled_for (DateTimeField - nullable, for 3am scheduling)
- delay_count (IntegerField - default: 0, max 7)
- priority (IntegerField - default: 0, higher = more priority)
- gemini_attempts (IntegerField - default: 0)
- content_item (ForeignKey to ContentItem - nullable, set after creation)
- error_message (TextField - nullable)
- created_at (DateTimeField - auto_now_add)
- updated_at (DateTimeField - auto_now)
- processing_started_at (DateTimeField - nullable)
- completed_at (DateTimeField - nullable)

Indexes:
- status, queue_status, scheduled_for
- content_type, status
- created_at

Methods:
- can_process() -> bool (checks if ready and no concurrent processing)
- schedule_for_next_day() (sets scheduled_for to next day 3am)
- promote_to_ready() (admin action to process immediately)
- get_queue_position() -> int
```

**2. New Model: `APIUploadLog`**
```
Location: backend/apps/media_manager/models.py

Fields:
- id (UUID, primary key)
- api_token (ForeignKey to APIToken)
- endpoint (CharField - API endpoint called)
- method (CharField - HTTP method)
- status_code (IntegerField)
- files_count (IntegerField)
- request_size_mb (FloatField)
- response_time_ms (IntegerField)
- error_message (TextField - nullable)
- ip_address (GenericIPAddressField)
- user_agent (CharField)
- created_at (DateTimeField - auto_now_add)

Indexes:
- api_token, created_at
- status_code, created_at
```

**3. Simple Authentication: `APISecretKeyAuthentication`**
```
Location: backend/apps/media_manager/api/authentication.py

Class: APISecretKeyAuthentication(BaseAuthentication)

Methods:
- authenticate(request) -> Tuple[User, None]
  - Extracts key from X-API-Secret-Key header
  - Validates against settings.API_SECRET_KEY
  - Checks rate limit (Redis-based)
  - Returns system user for API requests
  - Logs access attempt

- authenticate_header(request) -> str
  - Returns "X-API-Secret-Key" for header

Configuration:
- API_SECRET_KEY in settings (environment variable)
- Single shared key for simplicity
- Can be rotated by updating environment variable
```

**4. Queue Management Service: `APIUploadQueueService`**
```
Location: backend/apps/media_manager/services/api_upload_queue_service.py

Class: APIUploadQueueService

Methods:
- add_to_queue(file, doc_file, metadata, content_type) -> APIUploadQueue
  - Validates files
  - Saves to temp storage
  - Creates queue entry
  - Determines if can process immediately or needs queuing
  
- can_process_type(content_type) -> bool
  - Checks if any item of same type is currently processing
  - Uses Redis lock for type-based processing
  
- get_next_ready_item(content_type) -> APIUploadQueue
  - Gets next pending item ready for processing
  - Respects scheduling times
  - Checks delay limits
  
- handle_rate_limit_exceeded(queue_item)
  - Increments delay_count
  - Schedules for next day at 3:00 AM
  - Marks as rate_limited
  - Cancels if delay_count reaches 7
  
- process_queue_item(queue_item_id)
  - Locks processing for content type
  - Creates ContentItem
  - Triggers Gemini metadata generation
  - Handles success/failure
  - Releases lock
  
- get_queue_dashboard_data() -> Dict
  - Statistics by status
  - Items by content type
  - Delayed items with schedule times
  - Processing items
  
- promote_item(queue_item_id)
  - Admin action to skip queue
  - Sets priority high
  - Sets scheduled_for to now
  
- cancel_item(queue_item_id)
  - Admin action to cancel
  - Cleans up temp files
  - Marks as cancelled
```

**5. API Serializers (DRF)**
```
Location: backend/apps/media_manager/api/serializers.py

1. ContentItemUploadSerializer (DRF Serializer)
   - Handles single file upload with optional metadata
   - Required Fields: file (FileField)
   - Optional Fields: 
     - doc_file (FileField - for book_content)
     - title_ar, title_en, description_ar, description_en
     - tags (list of UUIDs)
     - seo_* fields
     - transcript, notes
   - Validation: file type, size (max 2GB), content type detection
   - Returns: queue_id, status, estimated_processing_time

2. BulkContentItemUploadSerializer (DRF Serializer)
   - Handles multiple files with optional shared metadata
   - Required Fields: files (list of files)
   - Optional Fields: 
     - doc_files (list, matched by index)
     - shared_metadata (dict)
     - individual_metadata (list of dicts)
   - Validation: file count, file sizes, content type matching
   - Returns: list of queue_ids with statuses

3. QueueStatusSerializer (DRF Serializer)
   - Returns queue item processing status
   - Fields: queue_id, status, queue_status, scheduled_for, 
            queue_position, content_item_id, errors, delay_count
   - Indicates if waiting, delayed, or processing

4. QueueItemSerializer (DRF Serializer)
   - Admin serializer for queue management
   - All fields from APIUploadQueue
   - Read-only for display
```

**6. API Views (DRF ViewSets and APIViews)**
```
Location: backend/apps/media_manager/api/views.py

1. ContentUploadAPIView (DRF APIView - POST)
   - URL: /api/v1/upload/
   - Single file upload with optional doc_file and metadata
   - Authentication: APISecretKeyAuthentication
   - Request: multipart/form-data
     - file: required
     - doc_file: optional (for book_content)
     - metadata: optional (all fields)
   - Response 202: {"queue_id": "uuid", "status": "queued", "queue_position": 3}
   - Response 201: {"queue_id": "uuid", "status": "processing"} (if no queue)
   
2. BulkContentUploadAPIView (DRF APIView - POST)
   - URL: /api/v1/upload/bulk/
   - Multiple files upload (max 20 per request)
   - Authentication: APISecretKeyAuthentication
   - Request: multipart/form-data
   - Response: {"queue_items": [...], "total": 10, "queued": 8, "processing": 2}

3. QueueStatusAPIView (DRF APIView - GET)
   - URL: /api/v1/queue/status/<queue_id>/
   - Returns queue item status
   - Authentication: APISecretKeyAuthentication
   - Response: {
       "queue_id": "uuid",
       "status": "rate_limited",
       "queue_status": "delayed",
       "scheduled_for": "2026-02-20T03:00:00Z",
       "delay_count": 1,
       "queue_position": 5,
       "content_item_id": null
     }

4. QueueListAPIView (DRF APIView - GET)
   - URL: /api/v1/queue/
   - List all queue items with filtering
   - Authentication: APISecretKeyAuthentication
   - Query params: status, content_type, limit, offset
   - Response: paginated list of queue items
```

**7. Celery Tasks for Queue Processing**
```
Location: backend/apps/media_manager/tasks.py

1. process_upload_queue_item(queue_item_id)
   - Main processing task
   - Acquires Redis lock for content_type
   - Creates ContentItem from queue data
   - Triggers Gemini metadata generation
   - Extracts text from doc_file if provided
   - Handles GeminiRateLimitError:
     - Calls schedule_for_next_day()
     - Releases lock
   - On success: marks completed, creates ContentItem
   - On failure: increments attempts, logs error
   - Releases lock

2. process_scheduled_queue_items()
   - Periodic task (runs every hour)
   - Finds items scheduled_for <= now
   - Groups by content_type
   - Processes one item per type (respects concurrency)
   - Scheduled via Celery Beat

3. process_delayed_3am_queue()
   - Scheduled task (runs daily at 3:00 AM)
   - Finds all items with scheduled_for on current day
   - Processes in priority order
   - Respects type-based concurrency
   - Scheduled via Celery Beat

4. cleanup_expired_queue_items()
   - Periodic task (runs daily)
   - Cancels items with delay_count >= 7
   - Cleans up temp files
   - Sends notification
```

**8. URL Configuration (DRF Router)**
```
Location: backend/apps/media_manager/api/urls.py

API Patterns (versioned, using DRF):
/api/v1/upload/                      - Single upload (POST)
/api/v1/upload/bulk/                 - Bulk upload (POST)
/api/v1/queue/                       - List queue items (GET)
/api/v1/queue/status/<uuid>/         - Queue status (GET)
/api/v1/queue/<uuid>/promote/        - Promote queue item (POST, admin)
/api/v1/queue/<uuid>/cancel/         - Cancel queue item (DELETE)
/api/v1/docs/                        - DRF Browsable API / Swagger docs
```

#### Admin Interface Components

**1. API Upload Queue Management Page**
```
Location: backend/templates/admin/api_upload_queue.html

Sections:
- Queue Statistics:
  - Total items by status
  - Items by content type
  - Processing items (real-time)
  - Delayed items count with next scheduled time
  
- Queue Items Table:
  - Columns: File Name, Type, Status, Queue Status, Scheduled For, Delay Count, Actions
  - Filters: Status, Content Type, Queue Status
  - Sorting: Created, Scheduled, Priority
  - Pagination
  
- Item Actions:
  - "Promote" button (move to front, process now)
  - "Cancel" button (remove from queue)
  - "View Details" (metadata, errors)
  - Bulk actions: Promote selected, Cancel selected
  
- Processing Monitor:
  - Currently processing items (by type)
  - Live progress updates via HTMX
  - Type-based locks status
  
- Delayed Items Section:
  - Items scheduled for 3:00 AM
  - Grouped by scheduled date
  - Delay count indicator
  - Warning for items approaching 7-day limit
```

**2. Queue Item Detail Modal**
```
Location: backend/templates/admin/includes/queue_item_detail_modal.html

Displays:
- File information (name, size, type)
- Doc file information (if provided)
- Metadata preview
- Status history timeline
- Error messages (if any)
- Gemini attempts count
- Delay history
- Actions: Promote, Cancel, Download files
```

**3. API Usage Dashboard Widget**
```
Location: backend/templates/admin/includes/api_usage_widget.html

Displays:
- Total API uploads today/week/month
- Queue length by status
- Rate limit violations
- Delayed items count
- Recent API uploads
- Processing success rate
- Add to main admin dashboard
```

---

### Implementation Phases

#### Phase 1: Queue System & Authentication (Week 1)

**Deliverables:**
- [ ] Create `APIUploadQueue` and `APIUploadLog` models
- [ ] Write and apply database migrations
- [ ] Implement `APISecretKeyAuthentication` class (DRF)
- [ ] Implement `APIUploadQueueService` class
- [ ] Add API secret key validation
- [ ] Create rate limiting using Redis
- [ ] Write unit tests for queue management

**Testing:**
- Authentication tests (valid/invalid keys)
- Queue creation tests
- Type-based locking tests
- Rate limiting tests

**Acceptance Criteria:**
- ✅ Authentication validates X-API-Secret-Key header
- ✅ Queue items created successfully
- ✅ Type-based processing lock prevents concurrent same-type processing
- ✅ Rate limiting enforces 100 requests/hour
- ✅ All tests pass with >90% coverage

---

#### Phase 2: Upload API Endpoints & Queue Processing (Week 2)

**Deliverables:**
- [ ] Create DRF serializers for uploads
- [ ] Implement single upload endpoint (ContentUploadAPIView)
- [ ] Implement bulk upload endpoint (BulkContentUploadAPIView)
- [ ] Implement queue status endpoint (QueueStatusAPIView)
- [ ] Create Celery task `process_upload_queue_item`
- [ ] Implement Gemini rate limit handling
- [ ] Add 3:00 AM scheduling logic
- [ ] Add request validation
- [ ] Write integration tests

**Testing:**
- Minimal payload tests (file-only upload)
- Full payload tests (file + doc_file + metadata)
- Bulk upload tests
- Queue processing tests
- Gemini rate limit simulation
- Same-type concurrency prevention

**Acceptance Criteria:**
- ✅ File-only uploads work (minimal payload)
- ✅ File + doc_file uploads work
- ✅ Metadata is optional in all cases
- ✅ Bulk uploads queue correctly
- ✅ No 2 items of same type process simultaneously
- ✅ Rate limit triggers 3:00 AM scheduling
- ✅ Async processing works correctly

---

#### Phase 3: Scheduled Tasks & Delay Management (Week 2-3)

**Deliverables:**
- [ ] Implement `process_scheduled_queue_items` periodic task
- [ ] Implement `process_delayed_3am_queue` scheduled task
- [ ] Configure Celery Beat schedule
- [ ] Add delay_count tracking and 7-day limit
- [ ] Implement automatic cancellation after 7 days
- [ ] Add notification system for delayed items
- [ ] Write integration tests for scheduling

**Testing:**
- 3:00 AM task execution
- Delay count increment
- 7-day cancellation
- Multiple day delays
- Notification delivery

**Acceptance Criteria:**
- ✅ Items scheduled for 3:00 AM execute correctly
- ✅ Delay count increments on each rate limit
- ✅ Items cancelled after 7 delays
- ✅ Admin receives notifications
- ✅ Scheduled tasks don't conflict with regular processing

---

#### Phase 4: Admin Dashboard & Queue Management (Week 3)

**Deliverables:**
- [ ] Create API upload queue management page
- [ ] Implement queue item detail modal
- [ ] Add promote/cancel actions
- [ ] Create real-time processing monitor (HTMX)
- [ ] Add queue statistics widget
- [ ] Implement filtering and sorting
- [ ] Create admin API endpoints for queue management
- [ ] Mobile responsive design

**Testing:**
- UI interaction tests
- Promote action tests
- Cancel action tests
- Real-time updates
- Filtering/sorting

**Acceptance Criteria:**
- ✅ Admin can view all queue items
- ✅ Admin can promote items to skip queue
- ✅ Admin can cancel items
- ✅ Real-time status updates work
- ✅ Delayed items clearly identified
- ✅ Filters and sorting work correctly
- ✅ Mobile UI is usable

---

#### Phase 5: Documentation & Testing (Week 3-4)

**Deliverables:**
- [ ] Generate OpenAPI/Swagger docs via DRF
- [ ] Write comprehensive API guide
- [ ] Create example scripts (Python, cURL, JavaScript)
- [ ] Document queue management process
- [ ] Document rate limit handling
- [ ] Create Postman collection
- [ ] End-to-end testing

**Testing:**
- Documentation accuracy
- Example scripts execution
- Complete workflows
- Edge cases

**Acceptance Criteria:**
- ✅ DRF browsable API works
- ✅ API guide is complete
- ✅ All code examples work
- ✅ Postman collection tests all endpoints
- ✅ Queue management documented
- ✅ Rate limit handling documented

---

### API Documentation Structure

#### Authentication

```http
Authentication Method: Simple Secret Key

All API requests must include:
X-API-Secret-Key: your-secret-key-here

Configuration (settings.py or .env):
API_SECRET_KEY=your-randomly-generated-secret-key-minimum-32-characters

To generate a secure key:
python -c "import secrets; print(secrets.token_urlsafe(32))"

Example:
X-API-Secret-Key: Kx7nP9mQ2vR8tY4wZ6bC1dF3gH5jL0sA
```

#### Minimal File Upload (File Only)

```http
POST /api/v1/upload/
X-API-Secret-Key: Kx7nP9mQ2vR8tY4wZ6bC1dF3gH5jL0sA
Content-Type: multipart/form-data

Minimal Payload:
- file: <binary file data>

Response 202 (Queued):
{
  "queue_id": "uuid",
  "status": "queued",
  "queue_status": "waiting",
  "queue_position": 3,
  "estimated_processing_time": "PT5M"
}

Response 201 (Processing Immediately):
{
  "queue_id": "uuid",
  "status": "processing",
  "queue_status": "ready",
  "content_type": "audio"
}
```

#### Full Upload (With Doc File and Metadata)

```http
POST /api/v1/upload/
X-API-Secret-Key: Kx7nP9mQ2vR8tY4wZ6bC1dF3gH5jL0sA
Content-Type: multipart/form-data

Full Payload:
- file: <binary file data>
- doc_file: <word document for book_content> (optional)
- title_ar: "عظة عن المحبة" (optional)
- title_en: "Sermon on Love" (optional)
- description_ar: "..." (optional)
- description_en: "..." (optional)
- tags: ["uuid1", "uuid2"] (optional)
- seo_keywords_ar: "محبة, قداسة" (optional)
- seo_keywords_en: "love, holiness" (optional)
- transcript: "Full transcript text..." (optional)

Response 202:
{
  "queue_id": "uuid",
  "status": "queued",
  "queue_status": "waiting",
  "queue_position": 1,
  "content_type": "audio",
  "file_name": "sermon.mp3",
  "doc_file_name": "sermon_content.docx"
}
```

#### Bulk Upload

```http
POST /api/v1/upload/bulk/
X-API-Secret-Key: Kx7nP9mQ2vR8tY4wZ6bC1dF3gH5jL0sA
Content-Type: multipart/form-data

Payload:
- files: [<file1>, <file2>, <file3>]
- doc_files: [<doc1>, <doc2>, <doc3>] (optional, matched by index)
- shared_metadata: {"tags": ["uuid1"], "seo_keywords_ar": "روحانية"} (optional)
- individual_metadata: [
    {"title_ar": "...", "title_en": "..."},
    {"title_ar": "...", "title_en": "..."},
    {"title_ar": "...", "title_en": "..."}
  ] (optional)

Response 202:
{
  "queue_items": [
    {"queue_id": "uuid1", "status": "queued", "file_name": "sermon1.mp3"},
    {"queue_id": "uuid2", "status": "processing", "file_name": "sermon2.mp3"},
    {"queue_id": "uuid3", "status": "queued", "file_name": "sermon3.mp3"}
  ],
  "total": 3,
  "queued": 2,
  "processing": 1
}
```

#### Check Queue Status

```http
GET /api/v1/queue/status/uuid/
X-API-Secret-Key: Kx7nP9mQ2vR8tY4wZ6bC1dF3gH5jL0sA

Response 200 (Processing):
{
  "queue_id": "uuid",
  "status": "processing",
  "queue_status": "ready",
  "content_type": "audio",
  "file_name": "sermon.mp3",
  "queue_position": 0,
  "content_item_id": null
}

Response 200 (Completed):
{
  "queue_id": "uuid",
  "status": "completed",
  "queue_status": "ready",
  "content_item": {
    "id": "uuid",
    "title_ar": "عظة عن المحبة",
    "content_type": "audio",
    "url": "https://library.org/ar/audios/uuid/",
    "is_active": true
  },
  "processing_time_seconds": 45,
  "completed_at": "2026-02-19T10:35:00Z"
}

Response 200 (Rate Limited - Delayed):
{
  "queue_id": "uuid",
  "status": "rate_limited",
  "queue_status": "delayed",
  "scheduled_for": "2026-02-20T03:00:00Z",
  "delay_count": 1,
  "message": "Gemini API rate limit exceeded. Scheduled for next day at 3:00 AM.",
  "max_delays": 7
}
```

#### Error Responses

```http
401 Unauthorized
{
  "error": "Invalid or missing API key",
  "code": "INVALID_API_KEY"
}

429 Too Many Requests
{
  "error": "Rate limit exceeded",
  "code": "RATE_LIMIT_EXCEEDED",
  "retry_after": 3600,
  "limit": 100,
  "period": "hour"
}

400 Bad Request
{
  "error": "Validation failed",
  "code": "VALIDATION_ERROR",
  "details": {
    "file": ["File type not supported"],
    "file_size": ["File exceeds 2GB limit"]
  }
}

503 Service Unavailable (Queue Full for Type)
{
  "error": "Too many pending items for this content type",
  "code": "QUEUE_FULL",
  "content_type": "video",
  "queue_length": 50,
  "estimated_wait": "PT2H"
}
```

---

### Code Examples

#### Python Example - Minimal Upload

```python
import requests
import time

API_URL = "https://library.org/api/v1"
API_KEY = "Kx7nP9mQ2vR8tY4wZ6bC1dF3gH5jL0sA"

headers = {
    "X-API-Secret-Key": API_KEY
}

# Minimal upload (file only)
with open("sermon.mp3", "rb") as f:
    files = {"file": f}
    response = requests.post(
        f"{API_URL}/upload/",
        headers=headers,
        files=files
    )
    result = response.json()
    print(f"Queue ID: {result['queue_id']}")
    print(f"Status: {result['status']}")
    print(f"Queue Position: {result.get('queue_position', 0)}")

# Poll for status
queue_id = result['queue_id']
while True:
    status_response = requests.get(
        f"{API_URL}/queue/status/{queue_id}/",
        headers=headers
    )
    status = status_response.json()
    
    print(f"Status: {status['status']}, Queue Status: {status['queue_status']}")
    
    if status['status'] == 'completed':
        print(f"Content Item ID: {status['content_item']['id']}")
        break
    elif status['status'] == 'rate_limited':
        print(f"Rate limited. Scheduled for: {status['scheduled_for']}")
        print(f"Delay count: {status['delay_count']}/7")
        break
    elif status['status'] == 'failed':
        print(f"Failed: {status.get('error_message')}")
        break
    
    time.sleep(10)  # Poll every 10 seconds
```

#### Python Example - Full Upload with Doc File

```python
import requests

API_URL = "https://library.org/api/v1"
API_KEY = "Kx7nP9mQ2vR8tY4wZ6bC1dF3gH5jL0sA"

headers = {
    "X-API-Secret-Key": API_KEY
}

# Full upload with doc file and metadata
with open("sermon.mp3", "rb") as audio_file, \
     open("sermon_content.docx", "rb") as doc_file:
    
    files = {
        "file": audio_file,
        "doc_file": doc_file
    }
    
    data = {
        "title_ar": "عظة عن المحبة",
        "title_en": "Sermon on Love",
        "description_ar": "وصف كامل",
        "tags": ["tag-uuid-1", "tag-uuid-2"],
        "seo_keywords_ar": "محبة, روحانية"
    }
    
    response = requests.post(
        f"{API_URL}/upload/",
        headers=headers,
        files=files,
        data=data
    )
    
    result = response.json()
    print(f"Queue ID: {result['queue_id']}")
    print(f"Status: {result['status']}")
    if 'doc_file_name' in result:
        print(f"Doc file uploaded: {result['doc_file_name']}")
```

#### cURL Example - Minimal Upload

```bash
curl -X POST https://library.org/api/v1/upload/ \
  -H "X-API-Secret-Key: Kx7nP9mQ2vR8tY4wZ6bC1dF3gH5jL0sA" \
  -F "file=@sermon.mp3"
```

#### cURL Example - Full Upload

```bash
curl -X POST https://library.org/api/v1/upload/ \
  -H "X-API-Secret-Key: Kx7nP9mQ2vR8tY4wZ6bC1dF3gH5jL0sA" \
  -F "file=@sermon.mp3" \
  -F "doc_file=@sermon_content.docx" \
  -F "title_ar=عظة عن المحبة" \
  -F "title_en=Sermon on Love" \
  -F "tags[]=tag-uuid-1" \
  -F "tags[]=tag-uuid-2"
```

#### cURL Example - Check Status

```bash
curl -X GET https://library.org/api/v1/queue/status/queue-uuid/ \
  -H "X-API-Secret-Key: Kx7nP9mQ2vR8tY4wZ6bC1dF3gH5jL0sA"
```

#### JavaScript Example

```javascript
const API_URL = "https://library.org/api/v1";
const API_KEY = "Kx7nP9mQ2vR8tY4wZ6bC1dF3gH5jL0sA";

// Minimal upload
async function uploadFile(file) {
  const formData = new FormData();
  formData.append("file", file);

  const response = await fetch(`${API_URL}/upload/`, {
    method: "POST",
    headers: {
      "X-API-Secret-Key": API_KEY
    },
    body: formData
  });

  return response.json();
}

// Full upload with doc file
async function uploadWithDocFile(file, docFile, metadata) {
  const formData = new FormData();
  formData.append("file", file);
  formData.append("doc_file", docFile);
  
  // Add optional metadata
  Object.entries(metadata).forEach(([key, value]) => {
    if (Array.isArray(value)) {
      value.forEach(v => formData.append(`${key}[]`, v));
    } else {
      formData.append(key, value);
    }
  });

  const response = await fetch(`${API_URL}/upload/`, {
    method: "POST",
    headers: {
      "X-API-Secret-Key": API_KEY
    },
    body: formData
  });

  return response.json();
}

// Check status
async function checkStatus(queueId) {
  const response = await fetch(`${API_URL}/queue/status/${queueId}/`, {
    method: "GET",
    headers: {
      "X-API-Secret-Key": API_KEY
    }
  });

  return response.json();
}

// Usage example
const fileInput = document.querySelector('input[type="file"]');
const docFileInput = document.querySelector('input[name="doc_file"]');

const result = await uploadWithDocFile(
  fileInput.files[0], 
  docFileInput.files[0],
  {
    title_ar: "عظة عن المحبة",
    title_en: "Sermon on Love",
    tags: ["tag-uuid-1", "tag-uuid-2"]
  }
);

console.log("Queue ID:", result.queue_id);
console.log("Status:", result.status);

// Poll for completion
const pollStatus = setInterval(async () => {
  const status = await checkStatus(result.queue_id);
  console.log("Current status:", status.status);
  
  if (['completed', 'failed', 'cancelled'].includes(status.status)) {
    clearInterval(pollStatus);
    console.log("Final status:", status);
  } else if (status.status === 'rate_limited') {
    console.log(`Delayed until: ${status.scheduled_for}`);
    clearInterval(pollStatus);
  }
}, 10000);
```

---

### Output Files & Documentation

**Code Files Created:**
1. `backend/apps/media_manager/models.py` - Add `APIUploadQueue`, `APIUploadLog` models
2. `backend/apps/media_manager/api/authentication.py` - Simple secret key authentication
3. `backend/apps/media_manager/services/api_upload_queue_service.py` - Queue management service
4. `backend/apps/media_manager/api/__init__.py` - API package
5. `backend/apps/media_manager/api/serializers.py` - DRF serializers
6. `backend/apps/media_manager/api/views.py` - DRF API views
7. `backend/apps/media_manager/api/urls.py` - API URL patterns
8. `backend/apps/media_manager/tasks.py` - Add queue processing tasks
9. `backend/config/celery.py` - Update with scheduled tasks
10. `backend/config/settings.py` - Add API_SECRET_KEY setting
11. `backend/templates/admin/api_upload_queue.html` - Queue management UI
12. `backend/templates/admin/includes/queue_item_detail_modal.html` - Queue item modal
13. `backend/apps/frontend_api/admin_views.py` - Add queue management endpoints
14. `backend/apps/media_manager/tests/test_api_auth.py` - Authentication tests
15. `backend/apps/media_manager/tests/test_api_upload.py` - Upload API tests
16. `backend/apps/media_manager/tests/test_queue_management.py` - Queue tests
17. Migration files

**Documentation Files:**
1. `docs/API_AUTHENTICATION_GUIDE.md` - Simple authentication setup
2. `docs/API_UPLOAD_REFERENCE.md` - API endpoints reference
3. `docs/API_CLIENT_EXAMPLES.md` - Code examples (Python, cURL, JS)
4. `docs/API_QUEUE_MANAGEMENT.md` - Queue system documentation
5. `docs/API_RATE_LIMIT_HANDLING.md` - Rate limit and scheduling details
6. `API_POSTMAN_COLLECTION.json` - Postman collection for testing

---

### Acceptance Criteria Summary

**Feature Complete When:**
- ✅ API authentication works with X-API-Secret-Key header
- ✅ Secret key configured via environment variable
- ✅ Minimal file-only uploads work (no metadata required)
- ✅ Full uploads with doc_file and metadata work
- ✅ All metadata fields are optional
- ✅ Bulk uploads (up to 20 files) work via API
- ✅ Queue system prevents concurrent processing of same content type
- ✅ Upload status can be checked via queue API
- ✅ Rate limiting enforces 100 requests/hour
- ✅ Gemini rate limit triggers automatic delay to 3:00 AM next day
- ✅ Delayed items tracked with delay_count
- ✅ Items cancelled after 7 days of delays
- ✅ Scheduled tasks execute at 3:00 AM daily
- ✅ Admin can view queue dashboard with all statuses
- ✅ Admin can promote items to skip queue
- ✅ Admin can cancel queued items
- ✅ Real-time queue status updates in admin UI
- ✅ All API responses are in JSON format
- ✅ Validation errors return clear messages
- ✅ DRF browsable API works for development
- ✅ Example scripts work (Python, cURL, JavaScript)
- ✅ Postman collection tests all endpoints
- ✅ Queue management is documented
- ✅ Rate limit handling is documented
- ✅ All tests pass with >85% coverage
- ✅ 2GB file size limit enforced

---

## Feature 3: Document Content Support

### Overview
Add support for uploading Word documents (.doc/.docx) as supplementary "book content" for any ContentItem (video, audio, PDF). The document text is extracted, vectorized, and indexed for full-text search, allowing users to find content based on related documentation.

### Requirements

#### Functional Requirements
- **FR-3.1:** Accept .doc and .docx file uploads
- **FR-3.2:** Associate document with any ContentItem (video, audio, PDF)
- **FR-3.3:** Extract text content from document
- **FR-3.4:** Store extracted text in `book_content` field
- **FR-3.5:** Vectorize content for PostgreSQL full-text search
- **FR-3.6:** Support multiple documents per ContentItem
- **FR-3.7:** Display document name and size in UI
- **FR-3.8:** Allow document download
- **FR-3.9:** Allow document replacement/deletion
- **FR-3.10:** Indicate document presence in content listing

#### Non-Functional Requirements
- **NFR-3.1:** Support documents up to 2GB
- **NFR-3.2:** Extract text within 30 seconds for 100-page document
- **NFR-3.3:** Maintain existing search performance
- **NFR-3.4:** Preserve formatting where possible
- **NFR-3.5:** Handle documents with images/tables

#### Technical Requirements
- **TR-3.1:** Use python-docx for .docx files
- **TR-3.2:** Use textract or similar for .doc files
- **TR-3.3:** Integrate with existing text extraction pipeline
- **TR-3.4:** Update search_vector automatically
- **TR-3.5:** Store document files in R2 storage
- **TR-3.6:** Support Arabic text extraction

---

### Architecture & Design

#### Backend Components

**1. Model Extension: `ContentItem`**
```
Location: backend/apps/media_manager/models.py

Add Field:
- supplementary_document (FileField - path to document in R2)
- supplementary_document_name (CharField - original filename)
- supplementary_document_size (IntegerField - file size in bytes)
- supplementary_document_type (CharField - mime type)
- supplementary_document_uploaded_at (DateTimeField)

Methods to Update:
- save() - Trigger document text extraction if document changed
- extract_text_from_document() - New method
- update_search_vector() - Merge PDF, audio transcript, and document text

Properties:
- has_supplementary_document() -> bool
- get_supplementary_document_url() -> str
```

**2. New Service: `DocumentProcessorService`**
```
Location: backend/apps/media_manager/services/document_processor_service.py

Class: DocumentProcessorService

Methods:
- extract_text_from_docx(file_path: str) -> str
  - Uses python-docx library
  - Extracts paragraphs, tables, headers, footers
  - Preserves section structure
  - Handles Arabic RTL text

- extract_text_from_doc(file_path: str) -> str
  - Uses textract or antiword
  - Fallback to pandoc if available
  - Converts to text format

- extract_text_from_document(file_path: str, mime_type: str) -> str
  - Router method that calls appropriate extractor
  - Handles errors and fallbacks

- clean_and_normalize_text(text: str) -> str
  - Removes excessive whitespace
  - Normalizes line breaks
  - Preserves paragraph structure
  - Applies Arabic cleaning pipeline

- validate_document(file: UploadedFile) -> Tuple[bool, str]
  - Checks file size
  - Validates document format
  - Scans for malicious content
```

**3. Enhanced Upload Service**
```
Location: backend/apps/media_manager/services/upload_service.py

Update MediaUploadService:

Add Method:
- attach_supplementary_document(content_item_id, document_file)
  - Validates document
  - Uploads to R2 storage
  - Saves document metadata to ContentItem
  - Triggers text extraction (async)

Update create_content_item():
- Accept optional supplementary_document parameter
- Process document if provided
```

**4. New Celery Task: `extract_document_text`**
```
Location: backend/apps/media_manager/tasks.py

Function: extract_document_text(content_item_id)

Workflow:
1. Fetch ContentItem
2. Download document from R2 to temp location
3. Determine document type
4. Extract text using appropriate method
5. Clean and normalize text
6. Append to existing book_content (or replace if specified)
7. Update search_vector
8. Save ContentItem
9. Clean up temp files
10. Update processing_status

Error Handling:
- Retry up to 3 times on failure
- Log detailed errors
- Mark document processing as failed
- Notify admin if persistent failure
```

**5. Admin Interface Updates**
```
Location: backend/apps/frontend_api/admin_views.py

Update content_detail view:
- Add document upload widget
- Display existing document info
- Add download button
- Add delete button

Add Endpoints:
POST /dashboard/content/<uuid>/document/upload/
- Upload supplementary document
- Response: {"success": true, "document_name": "...", "status": "processing"}

DELETE /dashboard/content/<uuid>/document/delete/
- Remove supplementary document
- Response: {"success": true}

GET /dashboard/content/<uuid>/document/download/
- Download supplementary document
- Returns file with correct headers
```

**6. Frontend Components**
```
Location: backend/templates/admin/content_detail.html

Add Section: "Supplementary Document"
Elements:
- Document upload form (drag-drop + file picker)
- File type indicator (.doc/.docx)
- Upload progress bar
- Document info card (when exists):
  - Icon based on type
  - File name
  - File size
  - Upload date
  - Download button
  - Delete button (with confirmation)
  - Processing status indicator
  - Text extraction status

HTMX Integration:
- Upload without page reload
- Progress updates
- Success/error messages
```

---

### Implementation Phases

#### Phase 1: Document Processing Backend (Week 1)

**Deliverables:**
- [ ] Add document fields to ContentItem model
- [ ] Write and apply database migration
- [ ] Install document processing libraries (python-docx, textract)
- [ ] Implement `DocumentProcessorService` class
- [ ] Create `extract_document_text` Celery task
- [ ] Write unit tests for extraction methods
- [ ] Test with various document formats

**Testing:**
- Text extraction from .docx files (simple, complex, with tables)
- Text extraction from .doc files
- Arabic text handling
- Large document handling (50MB)
- Malformed document handling
- Error scenarios

**Acceptance Criteria:**
- ✅ Service extracts text from .docx files
- ✅ Service extracts text from .doc files
- ✅ Arabic text is preserved correctly
- ✅ Tables are converted to readable text
- ✅ Paragraph structure is maintained
- ✅ Large documents (100+ pages) process successfully
- ✅ Errors are logged and handled gracefully
- ✅ All tests pass

---

#### Phase 2: Upload & Storage Integration (Week 1-2)

**Deliverables:**
- [ ] Update `MediaUploadService` for document handling
- [ ] Add R2 storage support for documents
- [ ] Create document upload API endpoints
- [ ] Implement document validation
- [ ] Add document deletion functionality
- [ ] Update search_vector integration
- [ ] Write integration tests

**Testing:**
- Document upload flow
- R2 storage and retrieval
- Document deletion
- Search vector updates
- Concurrent uploads
- Edge cases (duplicate names, overwrite)

**Acceptance Criteria:**
- ✅ Documents upload to R2 successfully
- ✅ Document metadata saves to database
- ✅ Text extraction triggers automatically
- ✅ Extracted text merges with book_content
- ✅ Search_vector updates with document text
- ✅ Documents can be deleted
- ✅ R2 cleanup occurs on deletion

---

#### Phase 3: Admin UI Integration (Week 2)

**Deliverables:**
- [ ] Create document upload widget
- [ ] Add to content_detail template
- [ ] Implement HTMX upload flow
- [ ] Create document info display card
- [ ] Add download functionality
- [ ] Add delete with confirmation
- [ ] Update content list to show document indicator
- [ ] Mobile responsive design

**Testing:**
- UI interaction tests
- HTMX upload flow
- Progress updates
- Download functionality
- Delete confirmation
- Responsive layout

**Acceptance Criteria:**
- ✅ Admin can upload document from content detail page
- ✅ Upload progress displays in real-time
- ✅ Success/error messages display clearly
- ✅ Document info displays correctly
- ✅ Admin can download document
- ✅ Admin can delete document with confirmation
- ✅ Content list shows document indicator icon
- ✅ UI works on mobile devices

---

#### Phase 4: Search Integration (Week 2)

**Deliverables:**
- [ ] Update search service to include document content
- [ ] Add search result highlighting for document text
- [ ] Update search UI to indicate document matches
- [ ] Add filter for "has supplementary document"
- [ ] Performance testing with document text
- [ ] Update search documentation

**Testing:**
- Search functionality with document text
- Result relevance
- Highlighting accuracy
- Performance benchmarks
- Large dataset tests

**Acceptance Criteria:**
- ✅ Search finds content based on document text
- ✅ Document text matches are highlighted
- ✅ Search results indicate document match vs content match
- ✅ Filter for "has document" works correctly
- ✅ Search performance remains acceptable (<200ms)
- ✅ Arabic document search works correctly

---

#### Phase 5: API Integration (Week 3)

**Deliverables:**
- [ ] Add document upload to RESTful API
- [ ] Update API serializers for document fields
- [ ] Add document endpoints to API
- [ ] Update API documentation
- [ ] Add to Postman collection
- [ ] Create API usage examples

**API Endpoints:**
```
POST /api/v1/content/<uuid>/document/
- Upload supplementary document
- multipart/form-data

GET /api/v1/content/<uuid>/document/
- Get document metadata

DELETE /api/v1/content/<uuid>/document/
- Remove supplementary document

GET /api/v1/content/<uuid>/document/download/
- Download document file
```

**Testing:**
- API endpoint functionality
- Authentication and permissions
- File upload handling
- Error responses

**Acceptance Criteria:**
- ✅ Document can be uploaded via API
- ✅ Document metadata retrievable via API
- ✅ Document downloadable via API
- ✅ Document deletable via API
- ✅ API documentation updated
- ✅ Postman collection includes document endpoints

---

### Database Schema Changes

**Migration: `add_supplementary_document_support`**

```python
from django.db import migrations, models

class Migration(migrations.Migration):
    dependencies = [
        ('media_manager', 'XXXX_previous_migration'),
    ]

    operations = [
        migrations.AddField(
            model_name='contentitem',
            name='supplementary_document',
            field=models.FileField(
                blank=True,
                null=True,
                upload_to='documents/%Y/%m/',
                verbose_name='Supplementary Document'
            ),
        ),
        migrations.AddField(
            model_name='contentitem',
            name='supplementary_document_name',
            field=models.CharField(
                blank=True,
                max_length=255,
                verbose_name='Document Name'
            ),
        ),
        migrations.AddField(
            model_name='contentitem',
            name='supplementary_document_size',
            field=models.IntegerField(
                blank=True,
                null=True,
                verbose_name='Document Size (bytes)'
            ),
        ),
        migrations.AddField(
            model_name='contentitem',
            name='supplementary_document_type',
            field=models.CharField(
                blank=True,
                max_length=100,
                verbose_name='Document Type'
            ),
        ),
        migrations.AddField(
            model_name='contentitem',
            name='supplementary_document_uploaded_at',
            field=models.DateTimeField(
                blank=True,
                null=True,
                verbose_name='Document Uploaded At'
            ),
        ),
    ]
```

---

### Text Extraction Pipeline

**1. Extraction Flow**
```
Document Upload → R2 Storage → Trigger Task → Download Temp → Extract Text →
Clean & Normalize → Merge with book_content → Update search_vector →
Save to DB → Delete Temp → Update Status
```

**2. Text Merging Strategy**
```python
def merge_document_text(content_item):
    """
    Merge all text sources into book_content field.
    
    Sources:
    1. PDF extracted text (for PDF content type)
    2. Transcript (for video/audio content types)
    3. Supplementary document text
    """
    text_parts = []
    
    # If PDF, include PDF text
    if content_item.content_type == 'pdf' and content_item.book_content:
        text_parts.append(f"[PDF Content]\n{content_item.pdf_text}")
    
    # If has transcript
    if content_item.transcript:
        text_parts.append(f"[Transcript]\n{content_item.transcript}")
    
    # Add supplementary document text
    if content_item.supplementary_document_text:
        text_parts.append(
            f"[Supplementary Document: {content_item.supplementary_document_name}]\n"
            f"{content_item.supplementary_document_text}"
        )
    
    content_item.book_content = "\n\n---\n\n".join(text_parts)
```

**3. Search Vector Update**
```python
def update_search_vector_with_document(content_item):
    """
    Update PostgreSQL search vector with all text sources.
    Uses weighted vectors to prioritize different text types.
    """
    # Weight A: Highest (titles, keywords)
    # Weight B: High (descriptions, transcript)
    # Weight C: Medium (document text)
    # Weight D: Low (notes)
    
    search_vector = (
        SearchVector('title_ar', weight='A', config='arabic') +
        SearchVector('title_en', weight='A', config='english') +
        SearchVector('description_ar', weight='B', config='arabic') +
        SearchVector('transcript', weight='B', config='arabic') +
        SearchVector('supplementary_document_text', weight='C', config='arabic') +
        SearchVector('notes', weight='D', config='arabic')
    )
    
    content_item.search_vector = search_vector
```

---

### Output Files & Documentation

**Code Files Created:**
1. `backend/apps/media_manager/models.py` - Update ContentItem model
2. `backend/apps/media_manager/services/document_processor_service.py` - New service
3. `backend/apps/media_manager/tasks.py` - Add `extract_document_text` task
4. `backend/apps/media_manager/services/upload_service.py` - Update for documents
5. `backend/apps/frontend_api/admin_views.py` - Add document endpoints
6. `backend/apps/frontend_api/urls.py` - Add document URL patterns
7. `backend/templates/admin/content_detail.html` - Update with document section
8. `backend/templates/admin/includes/document_upload_widget.html` - New widget
9. `backend/apps/media_manager/api/serializers.py` - Add document serializers
10. `backend/apps/media_manager/api/views.py` - Add document API views
11. `backend/apps/media_manager/tests/test_document_extraction.py` - Test suite
12. Migration file: `backend/apps/media_manager/migrations/XXXX_add_supplementary_document_support.py`

**Documentation Files:**
1. `docs/DOCUMENT_CONTENT_SUPPORT_GUIDE.md` - Feature overview and usage
2. `docs/DOCUMENT_EXTRACTION_TECHNICAL.md` - Technical implementation details
3. `docs/DOCUMENT_API_REFERENCE.md` - API endpoints for documents

---

### Acceptance Criteria Summary

**Feature Complete When:**
- ✅ Admin can upload .doc/.docx files to any ContentItem
- ✅ Documents stored in R2 with proper naming
- ✅ Text extracts from .docx files correctly
- ✅ Text extracts from .doc files correctly
- ✅ Arabic text preserves correctly
- ✅ Tables convert to readable text format
- ✅ Document text merges with book_content
- ✅ Search_vector updates with document text
- ✅ Search finds content based on document text
- ✅ Document info displays in admin UI
- ✅ Admin can download document
- ✅ Admin can delete document
- ✅ Content list shows document indicator
- ✅ Search results highlight document matches
- ✅ API supports document upload/download/delete
- ✅ Processing happens asynchronously
- ✅ Errors handle gracefully with logging
- ✅ Large documents (50MB) process successfully
- ✅ All tests pass with >85% coverage
- ✅ Documentation is complete

---

## Implementation Timeline

### Overall Schedule: 7-8 Weeks

| Feature | Duration | Dependencies |
|---------|----------|--------------|
| **Feature 1: Google Re-indexing** | 2 weeks | None |
| **Feature 2: RESTful Upload API** | 4 weeks | None |
| **Feature 3: Document Content Support** | 3 weeks | Feature 2 (for API) |

### Detailed Timeline

**Week 1:**
- Feature 1: Backend foundation + API endpoints
- Feature 2: Queue system & authentication (Phase 1)
- Feature 3: Document processing backend

**Week 2:**
- Feature 1: Frontend UI + Email notifications
- Feature 2: Upload API endpoints (Phase 2)
- Feature 3: Upload & storage integration

**Week 3:**
- Feature 2: Queue management & rate limiting (Phase 3)
- Feature 3: Admin UI integration

**Week 4:**
- Feature 2: Admin dashboard & monitoring (Phase 4)
- Feature 3: Search integration

**Week 5:**
- Feature 2: Documentation & client examples (Phase 5)
- Feature 3: API integration

**Week 6:**
- All Features: Integration testing

**Week 7:**
- All Features: User acceptance testing
- All Features: Documentation finalization

**Week 8 (Buffer):**
- Bug fixes
- Performance optimization
- Final deployment preparation

### Parallel Work Opportunities

**Can Be Developed Simultaneously:**
- Feature 1 Phase 1-2 + Feature 2 Phase 1
- Feature 1 Phase 3 + Feature 2 Phase 2
- Feature 3 Phase 1-4 (after Feature 2 Phase 1 complete)

**Must Be Sequential:**
- Feature 3 Phase 5 depends on Feature 2 completion (API infrastructure)
- Frontend work depends on backend APIs being stable

---

## Testing & Quality Assurance

### Testing Strategy

**1. Unit Tests**
- All service methods (including APIUploadQueueService)
- All model methods
- Text extraction functions
- Rate limiting logic
- Secret key authentication
- Queue status transitions
- Delay scheduling logic
- Serializer validation

**Coverage Target:** 90%+

**2. Integration Tests**
- API endpoint workflows
- Celery task execution
- Database transactions
- R2 storage operations
- Search vector updates

**Coverage Target:** 85%+

**3. End-to-End Tests**
- Complete upload workflows
- Re-indexing full cycle
- Document processing pipeline
- Multi-user scenarios

**Test Cases:** 20+ critical paths

**4. Performance Tests**
- 10,000 URL re-indexing
- Concurrent API uploads
- Large document extraction
- Search performance with documents
- Rate limiting under load

**Benchmarks:**
- Re-indexing: <1 hour for 10k URLs
- API response: <500ms (validation)
- Document extraction: <30s (100 pages)
- Search: <200ms with documents

**5. Security Tests**
- Secret key brute force resistance
- Authorization bypass attempts
- File upload vulnerabilities
- XSS/CSRF protection
- Rate limit circumvention
- Queue manipulation attempts

**Tools:** OWASP ZAP, manual penetration testing

**6. Usability Tests**
- Admin interface workflows
- Error message clarity
- Documentation completeness
- Mobile responsiveness

**Method:** User testing with 3-5 admin users

---

### Test Data Requirements

**1. Content Library**
- 100+ videos (various sizes)
- 100+ audios (various durations)
- 100+ PDFs (various page counts)
- Mix of Arabic and English content
- Some with existing SEO metadata

**2. Documents**
- 20+ .docx files (simple)
- 20+ .docx files (complex: tables, images)
- 10+ .doc files (legacy format)
- 10+ large documents (30+ pages)
- 10+ Arabic documents

**3. User Accounts & API**
- 5+ admin users
- API secret key configured
- Queue test data (various statuses and delay scenarios)
- Rate limit test scenarios

---

## Deployment & Rollout

### Pre-Deployment Checklist

**Infrastructure:**
- [ ] Redis capacity sufficient for rate limiting
- [ ] Celery workers scaled for additional tasks
- [ ] R2 bucket permissions for documents
- [ ] PostgreSQL performance tuned for text search
- [ ] Google API credentials configured

**Dependencies:**
- [ ] python-docx installed
- [ ] textract or antiword installed
- [ ] Django REST Framework installed
- [ ] google-auth and google-api-python-client updated

**Configuration:**
- [ ] GOOGLE_SERVICE_ACCOUNT_FILE set
- [ ] API_SECRET_KEY set (environment variable)
- [ ] API_RATE_LIMIT_PER_HOUR configured (default: 100)
- [ ] MAX_DOCUMENT_SIZE configured (default: 2GB)
- [ ] ALLOWED_DOCUMENT_TYPES configured
- [ ] EMAIL_BACKEND configured for notifications
- [ ] CELERY_BEAT_SCHEDULE includes 3:00 AM queue processing task

**Database:**
- [ ] All migrations applied
- [ ] Indexes created
- [ ] Backup taken before migration

**Testing:**
- [ ] All tests passing (unit, integration, E2E)
- [ ] Performance benchmarks met
- [ ] Security scan passed
- [ ] UAT sign-off received

---

### Rollout Plan

**Phase 1: Soft Launch (Week 7)**
- Deploy to staging environment
- Internal testing with admin team
- Monitor logs and performance
- Fix critical issues

**Phase 2: Beta Release (Week 8)**
- Deploy Feature 1 (Google Re-indexing) to production
- Enable for admin users only
- Monitor Google API usage
- Collect feedback

**Phase 3: API Beta (Week 9)**
- Deploy Feature 2 (RESTful API) to production
- Share API secret key with beta testers securely
- Provide documentation and examples
- Monitor API usage, queue status, and errors
- Test 3:00 AM scheduled task in production

**Phase 4: Document Support (Week 10)**
- Deploy Feature 3 (Document Content) to production
- Enable for all content types
- Monitor extraction performance
- Re-index content with new search vectors

**Phase 5: Full Release (Week 11)**
- Announce all features to all users
- Publish complete documentation
- Provide training materials
- Monitor adoption and feedback

---

### Monitoring & Metrics

**Key Metrics to Track:**

**Feature 1 (Google Re-indexing):**
- Re-indexing operations initiated
- Average URLs processed per operation
- Success rate (successful URLs / total URLs)
- Average duration per operation
- Google API error rate
- Rate limit violations

**Feature 2 (RESTful API):**
- API tokens created
**Feature 2 (RESTful API):**
- API requests per hour (total)
- Queue items by status (pending, processing, completed, failed)
- Queue items by queue_status (queued, rate_limited, delayed, cancelled)
- Upload success rate
- Average upload size
- Rate limit hits
- Authentication failures
- API error rates by endpoint
- Queue processing time (average)
- Delayed items count (by delay_count: 1-7)
- 3:00 AM scheduled task execution success rate
- Queue cancellations (manual vs automatic)

**Feature 3 (Document Support):**
- Documents uploaded
- Document types distribution (.doc vs .docx)
- Average extraction time
- Extraction success rate
- Document storage usage (R2)
- Search queries matching document text
- Average document size

**System Health:**
- Celery queue length
- Redis memory usage
- PostgreSQL query performance
- R2 API latency
- Application error rates

---

### Rollback Plan

**If Critical Issues Arise:**

**Feature 1:**
- Disable re-indexing UI (remove button)
- Cancel running tasks
- Revert migration if database issues
- Google API quota unaffected (read-only)

**Feature 2:**
- Change API_SECRET_KEY in environment
- Disable API endpoints via feature flag
- Cancel all queued items
- Existing content upload still works
- Revert to CSRF-protected endpoints
- Queue table can be safely dropped (no impact on ContentItem)

**Feature 3:**
- Disable document upload UI
- Existing documents remain accessible
- Search continues to work (without document text)
- Can revert migration (document fields are nullable)

**Database Rollback:**
- All new fields are nullable/have defaults
- Safe to rollback migrations
- Data loss risk: Minimal (only new feature data)

---

## Risk Assessment & Mitigation

### High-Risk Areas

**1. Google API Rate Limits**
- **Risk:** Exceeding quota blocks re-indexing
- **Impact:** Feature unusable until quota resets
- **Mitigation:**
  - Conservative batching (150/min vs 200 limit)
  - Exponential backoff on 429 errors
  - Admin warning before initiating
  - Monitoring and alerts

**2. API Authentication Security**
- **Risk:** Secret key leakage exposes upload endpoint
- **Impact:** Unauthorized uploads, storage abuse, quota exhaustion
- **Mitigation:**
  - Single shared key stored in environment (not in database)
  - HTTPS required (enforce in production)
  - Rate limiting (100 req/hour)
  - Activity monitoring and alerts
  - Easy key rotation (change environment variable)
  - Request logging with IP tracking
  - File size limits (2GB max)
  - Queue capacity limits

**3. Large Document Processing**
- **Risk:** 50MB documents cause timeouts/memory issues
- **Impact:** Extraction failures, Celery worker crashes
- **Mitigation:**
  - Async processing (non-blocking)
  - Memory limits on Celery workers
  - Timeouts on extraction (5 min max)
  - Chunked file reading
  - Error logging and retry logic

**4. Search Performance Degradation**
- **Risk:** Adding document text slows searches
- **Impact:** Poor user experience
- **Mitigation:**
  - Weighted search vectors (document text lower weight)
  - GIN indexes on search_vector
  - Query optimization
  - Performance benchmarks in tests
  - Monitoring query times

---

### Medium-Risk Areas

**5. Concurrent Re-indexing**
- **Risk:** Multiple admins trigger re-indexing simultaneously
- **Impact:** Duplicate Google API calls, quota waste
- **Mitigation:**
  - Redis-based locking
  - UI shows "in progress" status
  - Disable button during operation

**6. API Abuse**
- **Risk:** Users hammer API endpoints
- **Impact:** Server overload, quota exhaustion
- **Mitigation:**
  - Rate limiting (100/hour)
  - Request size limits
  - Validation before processing
  - Monitoring and automated blocking

**7. Document Format Edge Cases**
- **Risk:** Malformed .doc files crash extraction
- **Impact:** Processing failures, task retries
- **Mitigation:**
  - Multiple extraction methods (fallbacks)
  - Exception handling at each stage
  - Timeout limits
  - Clear error messages to admin

---

## Future Enhancements (Post-Release)

### Potential Improvements

**Feature 1 (Google Re-indexing):**
- Scheduled automatic re-indexing (weekly/monthly)
- Smart re-indexing (only changed URLs)
- Multi-site support (different domains)
- Bing/Yandex indexing APIs

**Feature 2 (RESTful API):**
- OAuth2 support
- Webhooks for upload completion notification
- Batch operations (update/delete multiple items)
- API versioning (v2, v3)
- GraphQL interface
- SDK libraries (Python, JavaScript, PHP)

**Feature 3 (Document Support):**
- Support for more formats (.txt, .rtf, .odt)
- Excel/CSV support (for appendices, data)
- PowerPoint support (for presentations)
- Image OCR from documents
- Document preview in admin UI
- Version history (track document replacements)
- Multiple documents per ContentItem

---

## Appendix

### A. Environment Variables

```bash
# Google Services
GOOGLE_SERVICE_ACCOUNT_FILE=/path/to/credentials.json

# API Configuration
API_RATE_LIMIT_PER_HOUR=100
API_TOKEN_EXPIRY_DAYS=365
API_MAX_UPLOAD_SIZE_MB=1024
API_MAX_BULK_UPLOADS=10

# Document Processing
MAX_DOCUMENT_SIZE_MB=50
ALLOWED_DOCUMENT_TYPES=.doc,.docx
DOCUMENT_EXTRACTION_TIMEOUT_SECONDS=300

# Email Notifications
EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend
EMAIL_HOST=smtp.gmail.com
EMAIL_PORT=587
EMAIL_USE_TLS=True
EMAIL_HOST_USER=notifications@library.org
EMAIL_HOST_PASSWORD=***
ADMIN_EMAIL=admin@library.org
```

---

### B. Required Python Packages

**Add to `backend/requirements/base.txt`:**
```
# Document processing
python-docx>=0.8.11
python-magic>=0.4.27
textract>=1.6.5  # For .doc files
antiword>=0.37  # Alternative for .doc

# REST API
djangorestframework>=3.14.0
drf-yasg>=1.21.7  # Swagger/OpenAPI docs
django-filter>=23.0

# Already exists (verify versions)
google-auth>=2.27.0
google-api-python-client>=2.115.0
celery>=5.3
redis>=4.5
```

---

### C. Database Indexes Summary

**New Indexes Required:**

**1. APIToken:**
- `key` (unique, hashed)
- `user_id, is_active`
- `expires_at`

**2. APIUploadLog:**
- `api_token_id, created_at`
- `status_code, created_at`

**3. GoogleReindexingTask:**
- `status, created_at`
- `initiated_by_id, created_at`

**4. ContentItem (updated):**
- `supplementary_document` (not indexed, FileField)
- Existing `search_vector` GIN index still applies

---

### D. Celery Tasks Summary

**New Tasks:**
1. `reindex_website_google(task_id, content_type, include_sitemap)`
   - Duration: 30-60 minutes
   - Priority: Low
   - Queue: default

2. `extract_document_text(content_item_id)`
   - Duration: 10-30 seconds
   - Priority: Medium
   - Queue: media_processing

**Existing Tasks (updated):**
3. `extract_and_index_contentitem(content_item_id)`
   - Now checks for supplementary_document
   - Merges document text into book_content

---

### E. API Rate Limiting Rules

**Rate Limits:**
- Default: 100 requests/hour per token
- Configurable per token
- Applies to all `/api/v1/` endpoints
- Excludes: Authentication endpoint, token creation (uses session auth)

**Headers in Response:**
```
X-RateLimit-Limit: 100
X-RateLimit-Remaining: 87
X-RateLimit-Reset: 1645456800
```

**429 Response Format:**
```json
{
  "error": "Rate limit exceeded",
  "code": "RATE_LIMIT_EXCEEDED",
  "limit": 100,
  "period": "hour",
  "retry_after": 3600
}
```

---

### F. Google API Quota Management

**Current Limits (as of 2026):**
- Indexing API: 200 requests/minute
- Indexing API: Unlimited daily quota (for verified owners)
- Sitemap ping: No documented limit (reasonable use)

**Our Implementation Limits:**
- Re-indexing: 150 requests/minute (75% of limit for safety)
- Batch size: 50 URLs per batch
- Delay between batches: 20 seconds

**Quota Monitoring:**
- Log all API calls with timestamps
- Calculate requests/minute in real-time
- Dashboard widget showing current quota usage
- Alert if approaching limits (>180 req/min)

---

### G. Security Considerations

**API Token Security:**
- Tokens hashed with bcrypt (cost factor 12)
- Minimum entropy: 128 bits
- Prefix: `clo_live_` for production, `clo_test_` for staging
- Never logged in full (only masked versions)
- HTTPS required (redirect HTTP to HTTPS)

**Document Upload Security:**
- MIME type validation (not just extension)
- Magic number checking (file header validation)
- Virus scanning (if ClamAV available)
- Filename sanitization
- Path traversal prevention
- Size limits enforced at multiple layers

**Re-indexing Security:**
- Admin-only access (staff_member_required)
- CSRF protection (not API endpoint)
- Rate limiting (prevent abuse)
- Logging of all operations with user ID
- Email alerts on completion

---

### H. Documentation Deliverables Checklist

**User Documentation:**
- [ ] Google Re-indexing Admin Guide
- [ ] API Getting Started Guide
- [ ] API Authentication Tutorial
- [ ] API Upload Examples (Python, cURL, JS)
- [ ] Document Content Feature Guide
- [ ] Troubleshooting Guide

**Technical Documentation:**
- [ ] API Reference (OpenAPI/Swagger)
- [ ] Google Re-indexing Technical Implementation
- [ ] Document Extraction Technical Details
- [ ] Database Schema Changes
- [ ] Deployment Guide
- [ ] Monitoring & Alerting Setup

**Developer Documentation:**
- [ ] Code comments (all new classes/methods)
- [ ] README updates
- [ ] CHANGELOG entries
- [ ] Migration notes
- [ ] Testing guide

---

## Conclusion

This implementation plan provides a comprehensive roadmap for adding three major features to the Coptic Orthodox Digital Library:

1. **Google Re-indexing Admin Endpoint** - Empowers admins with full control over search engine visibility
2. **RESTful Upload API** - Enables programmatic content management and automation
3. **Document Content Support** - Enriches content with supplementary documentation and enhances search capabilities

**Total Estimated Effort:** 6-7 weeks with proper resource allocation

**Key Success Factors:**
- ✅ Comprehensive testing at every phase
- ✅ Incremental rollout to catch issues early
- ✅ Clear documentation for users and developers
- ✅ Monitoring and alerting from day one
- ✅ Security-first approach throughout

**Next Steps:**
1. Review and approve this plan
2. Allocate development resources
3. Set up project tracking (Jira, Trello, etc.)
4. Begin Phase 1 implementations in parallel
5. Schedule regular progress reviews

---

**Document Version:** 1.0  
**Last Updated:** February 19, 2026  
**Status:** Ready for Review  
**Approval Required From:** Technical Lead, Product Manager, Security Team
