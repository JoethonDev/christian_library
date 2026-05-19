# Celery Background Tasks — Refactor Plan

> Branch: `refactor/normalize-background-tasks`  
> Date: 2026-05-16  
> Status: **Phase 3 code cleanup complete; validation passed**

---

## Root Cause: Why R2 Retry in Admin Dashboard Is Broken

`retry_r2_upload` (and `bulk_retry_r2_uploads`) live in `admin_views.py`.  
At the **very top** of that file (lines 29–35) there are hard imports of Google Indexing modules:

```python
from apps.frontend_api.models_indexing import GoogleIndexingQueue, GoogleIndexingQuota
from apps.frontend_api.services.google_indexing_queue_service import GoogleIndexingQueueService
from apps.frontend_api.services.google_reindexing_service import GoogleReindexingService
from apps.frontend_api.tasks import (
    process_google_indexing_queue, reindex_website_google, ...
)
```

If any of these modules raise an `ImportError` or `ModuleNotFoundError` at startup (e.g. a missing
credential file, a broken model, or a missing dependency), the **entire `admin_views.py` fails to
load**. This silently breaks every admin view including `retry_r2_upload`, returning 500s with no
obvious cause. **Removing Google Indexing (Phase 1) will fix R2 retry as a direct side-effect.**

---

## Part 1 — Full Task Inventory

### `core/tasks/media_processing.py` — 8 tasks

| Task | Queue (current) | Purpose |
|---|---|---|
| `delete_files_task` | default | Async filesystem cleanup |
| `process_video_to_hls` | videos | HLS encode (720p + 480p) + thumbnail |
| `process_audio_compression` | audios | Compress to 192k + extract duration |
| `process_pdf_optimization` | pdfs | Optimize >10 MB PDFs + thumbnail |
| `cleanup_failed_uploads` | default | **Beat/hourly** — marks stale 'processing' as failed |
| `upload_video_to_r2` | uploads | Push HLS + original to R2 |
| `upload_audio_to_r2` | uploads | Push compressed audio to R2 |
| `upload_pdf_to_r2` | uploads | Push PDF to R2 (concurrency-controlled) |

### `apps/media_manager/tasks.py` — 10 tasks

| Task | Queue (current) | Purpose |
|---|---|---|
| `extract_and_index_contentitem` | default | PDF OCR → `book_content` → search vector |
| `generate_seo_metadata_task` | gemini | Gemini AI → SEO fields |
| `finalize_media_processing` | default | Sync gate: R2 done **and** SEO done → delete local files |
| `bulk_generate_seo_metadata` | gemini | Utility: queue SEO for items missing it |
| `aggregate_daily_content_views` | default | **Beat/midnight** — aggregate view stats |
| `process_upload_queue_item` | default | Dequeue API upload → call `MediaUploadService` |
| `process_scheduled_queue_items` | default | **Beat/hourly** — trigger ready queue items |
| `process_delayed_3am_queue` | default | **Beat/3 AM** — resume rate-limited items |
| `cleanup_expired_queue_items` | default | **Beat/4 AM** — cancel items with 7+ delays |
| `extract_document_text` | default | Extract text from supplementary documents |

### `apps/frontend_api/tasks.py` — 5 tasks  ⚠ ENTIRE GROUP MARKED FOR REMOVAL

| Task | Status | Reason |
|---|---|---|
| `reindex_website_google` | **REMOVE** | Google Indexing API feature being dropped |
| `process_google_indexing_queue` | **REMOVE** | Google Indexing API feature being dropped |
| `revalidate_invalid_indexing_items` | **REMOVE** | Google Indexing API feature being dropped |
| `retry_failed_indexing_items` | **REMOVE** | Google Indexing API feature being dropped |
| `cleanup_old_indexing_queue_items` | **REMOVE** | Google Indexing API feature being dropped |

**Scope of Google Indexing removal** also includes:
- `apps/frontend_api/tasks.py` — entire file can be deleted after removal
- `apps/frontend_api/models_indexing.py` — models for `GoogleIndexingQueue`, `GoogleIndexedUrl`
- `apps/frontend_api/google_seo_service.py` — `ping_google_sitemap` and related
- `apps/frontend_api/services/google_reindexing_service.py`
- `apps/frontend_api/services/url_generator_service.py` (if only used by indexing)
- All `admin_views.py` endpoints that call these tasks
- All beat schedule entries for these tasks in `config/settings/base.py`
- Migration for `GoogleIndexingQueue` / `GoogleIndexedUrl` / `GoogleReindexingTask` models (keep migration history, just add data migration to drop data gracefully)

---

## Part 2 — Trigger Map

```
Template / Custom Admin Upload
  └─> MediaUploadService.create_content_item()
        ├─> transaction.on_commit → process_[video|audio|pdf] task      ← KEEP
        ├─> upload_service.py L593-599 → upload_*_to_r2.delay()          ← REMOVE (P1)
        └─> upload_service.py L675 → extract_document_text.delay()       ← KEEP

API Upload  (POST /api/v1/upload/)
  └─> APIUploadQueueService.add_to_queue()
        └─> process_upload_queue_item
              └─> APIUploadQueueService.process_queue_item()
                    └─> MediaUploadService  (same path above)

Django signals (VideoMeta/AudioMeta/PdfMeta post_save)
  └─> trigger_video_processing / trigger_audio_processing / trigger_pdf_processing
        └─> process_[video|audio|pdf].apply_async()                       ← REMOVE (P6)

Django signals (ContentItem post_save — CREATE only)
  └─> create_content_meta                                                  ← KEEP

Django Admin action "reprocess_media"
  └─> process_[video|audio|pdf].delay()                                   ← KEEP

Django Admin action "force_regenerate_seo"
  └─> generate_seo_metadata_task.delay()                                  ← KEEP

Custom Admin Dashboard (admin_views.py)
  └─> upload_*_to_r2 (retry R2 upload)                                    ← KEEP
  └─> generate_seo_metadata_task (bulk SEO)                               ← KEEP
  └─> reindex_website_google / indexing tasks                              ← REMOVE
```

### Current Pipeline Chains

**Video / Audio:**
```
process_[video|audio]
  └─> generate_seo_metadata_task   (parallel)
  └─> upload_[video|audio]_to_r2   (parallel)
        └─> finalize_media_processing  (called by BOTH when each completes)
              └─> delete_files_task
```

**PDF (longer chain):**
```
process_pdf_optimization
  └─> extract_and_index_contentitem
        ├─> generate_seo_metadata_task   (parallel)  ← KEEP
        ├─> upload_pdf_to_r2             (parallel)  ← KEEP here ONLY (remove duplicate)
        └─> finalize_media_processing
              └─> delete_files_task
```

---

## Part 3 — Problems Found

### P1 — Duplicate R2 trigger for template uploads  ⚡ HIGH PRIORITY

**Location:** `apps/media_manager/services/upload_service.py` lines 593–599  
**Problem:** `upload_service.py` calls `upload_*_to_r2.delay()` immediately after creating the
meta object. But the processing task (e.g. `process_pdf_optimization`) **also** calls `upload_pdf_to_r2`
after it finishes. Result: R2 upload is triggered twice (or more) before the file is even ready.

**Fix:** Delete the `upload_*_to_r2.delay()` block in `upload_service.py` lines 593–599 entirely.
R2 upload must only be dispatched from inside the processing task once processing is confirmed complete.

---

### P2 — `extract_and_index_contentitem` also triggers R2 for PDFs  ⚡ HIGH PRIORITY

**Location:** `apps/media_manager/tasks.py` lines 124–135  
**Problem:** After text extraction completes, this task again calls `upload_pdf_to_r2.delay()`.
Combined with P1 this can create 3+ R2 upload attempts queued simultaneously.

**Fix:** Remove the R2 dispatch block (lines 124–135) from `extract_and_index_contentitem`.
The canonical R2 trigger for PDFs must live **only** in `process_pdf_optimization` (after it calls
`extract_and_index_contentitem` and that completes). Chain order becomes:
```
process_pdf_optimization
  → extract_and_index_contentitem   (await/chain, NOT parallel for PDFs)
  → upload_pdf_to_r2               (only once, from process_pdf_optimization)
  → generate_seo_metadata_task     (parallel with R2, from process_pdf_optimization)
```

---

### P3 — No explicit queue routing on most `.delay()` calls  🔵 LOW PRIORITY

**Problem:** `.delay()` calls without `queue=` parameter all land in `default` queue.

**Decision (user):** Queue routing is low priority. More important is keeping
**no more than 2 global workers total**, each with `concurrency=1`.

**Approach:**
- Reduce docker-compose workers from 6 containers to **2 worker containers**
- Each worker listens on **all queues**: `-Q videos,audios,pdfs,gemini,uploads,default`
- Each worker has `concurrency=1` → only one task runs per worker at any time → max 2 parallel tasks globally
- Per-type serialization is enforced via **Redis locks** already present in `APIUploadQueueService.can_process_type()`. Extend same lock pattern to template-upload processing tasks.
- The `gemini` worker distinction can remain as a named worker label but no longer needs its own container

**docker-compose change:**
```yaml
# BEFORE: 6 workers
celery_worker_videos  (concurrency=1)
celery_worker_audios  (concurrency=1)
celery_worker_pdfs    (concurrency=1)
celery_worker_gemini  (concurrency=4)
celery_worker_uploads (concurrency=3)
celery_worker_default (concurrency=2)

# AFTER: 2 workers
celery_worker_1:  -Q videos,audios,pdfs,gemini,uploads,default -c 1
celery_worker_2:  -Q videos,audios,pdfs,gemini,uploads,default -c 1
```

---

### P4 — Two beat tasks doing the same thing  ⚡ MEDIUM PRIORITY

**Tasks:** `process_scheduled_queue_items` (hourly) and `process_delayed_3am_queue` (3 AM)  
**Problem:** Both scan `APIUploadQueue` and dispatch `process_upload_queue_item`. The only
difference is the 3 AM version filters `status='rate_limited'` / `queue_status='delayed'`.

**Fix:** Merge into one task:
```python
@shared_task
def process_pending_queue_items(include_rate_limited=False):
    """Single entry point for queue scanning."""
    ...
```

Beat schedule becomes:
```python
'process-pending-queue': {
    'task': 'apps.media_manager.tasks.process_pending_queue_items',
    'schedule': 3600.0,
    'kwargs': {'include_rate_limited': False},
},
'process-3am-queue': {
    'task': 'apps.media_manager.tasks.process_pending_queue_items',
    'schedule': crontab(hour=3, minute=0),
    'kwargs': {'include_rate_limited': True},
},
```

Delete `process_scheduled_queue_items` and `process_delayed_3am_queue` functions.

---

### P5 — No failure reason stored at the model level  ⚡ HIGH PRIORITY

**Problem:** When a task fails, `processing_status='failed'` is set but the **reason** is only
stored in Redis via `TaskMonitor` which has an expiry. Once Redis evicts the key, failure context
is lost permanently. The Admin Dashboard retry has no idea what stage failed or why.

**Fix — Add a `ProcessingJob` model** (new migration in `media_manager`):

```python
class ProcessingJob(models.Model):
    STAGE_CHOICES = [
        ('file_processing', 'File Processing'),
        ('text_extraction', 'Text Extraction'),   # PDF only
        ('r2_upload',       'R2 Upload'),
        ('seo_generation',  'SEO Generation'),
        ('completed',       'Completed'),
    ]
    STATUS_CHOICES = [
        ('pending',    'Pending'),
        ('processing', 'Processing'),
        ('failed',     'Failed'),
        ('completed',  'Completed'),
    ]

    content_item   = models.OneToOneField(
        'ContentItem', on_delete=models.CASCADE, related_name='processing_job'
    )
    current_stage  = models.CharField(max_length=30, choices=STAGE_CHOICES, default='file_processing')
    status         = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    failure_stage  = models.CharField(max_length=30, blank=True)
    failure_reason = models.TextField(blank=True)   # full error message / traceback snippet
    retry_count    = models.PositiveSmallIntegerField(default=0)
    celery_task_id = models.CharField(max_length=255, blank=True)
    created_at     = models.DateTimeField(auto_now_add=True)
    updated_at     = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=['status', 'current_stage']),
            models.Index(fields=['status', 'updated_at']),
        ]
```

**How each task uses it:**
- Task START → set `current_stage`, `status='processing'`, `celery_task_id`
- Task SUCCESS → set `status='completed'` (or advance to next stage)
- Task FAILURE → set `status='failed'`, `failure_stage=current_stage`, `failure_reason=str(exc)[:2000]`

`ProcessingJob` is created automatically when a `ContentItem` is created (via `post_save` signal
that already creates meta objects — extend `create_content_meta` to also create `ProcessingJob`).

---

### P6 — Signals AND upload service both trigger processing  ⚡ HIGH PRIORITY

**Problem:** Both `apps/media_manager/signals.py` (`trigger_video_processing`,
`trigger_audio_processing`, `trigger_pdf_processing`) and `upload_service.py`
(via `transaction.on_commit`) can fire the same processing task. For a template upload this
creates a race condition (signal fires on meta save, on_commit fires after the transaction).
The `processing_status == 'pending'` guard is fragile.

**Decision — Best Practice:**

> Use the **service layer** as the single trigger point. Signals should only handle
> *reactive model construction* (creating related objects), not business logic dispatch.

**Fix:**
1. **REMOVE** the three processing-trigger signals from `signals.py`:
   - `trigger_video_processing`
   - `trigger_audio_processing`
   - `trigger_pdf_processing`
2. **KEEP** the meta-creation signal `create_content_meta` (it only creates VideoMeta/AudioMeta/PdfMeta)
3. **KEEP** the file-deletion signals (`delete_video_files`, `delete_audio_files`, `delete_pdf_files`, `delete_content_item_files`)
4. `MediaUploadService` (via `transaction.on_commit`) remains the **only** trigger for processing tasks
5. For the **Django admin** inline save path (where a VideoMeta is saved directly in admin without going through `MediaUploadService`): The `reprocess_media` admin action already handles this explicitly. The signal was a shortcut for that case — it can be replaced by a cleaner check in `VideoMetaInline.save_model()` / `AudioMetaInline.save_model()` / `PdfMetaInline.save_model()` in `admin.py`.

---

### P7 — `cleanup_failed_uploads` beat task only marks, never retries  🔵 LOW PRIORITY

**Current behaviour:** Marks items stuck in `processing_status='processing'` for >1 hour as `failed`.
Does not re-queue them.

**Future fix (after P5 is done):** After `ProcessingJob` model exists, enhance this task to:
- Mark the job as failed with `failure_reason='Stale: exceeded 1h processing limit'`
- Optionally auto-retry once (increment `retry_count`, re-dispatch the task) if `retry_count == 0`
- After `retry_count >= 1`, leave as failed for manual Admin retry

---

### P8 — Gemini failure must NOT block R2 upload or content activation  ⚡ HIGH PRIORITY

**Problem:** `generate_seo_metadata_task` has up to 10 retries spread over multiple days.
While retries are pending, `seo_processing_status` stays `'processing'`.
`finalize_media_processing` checks `seo_done = seo_processing_status in ['completed', 'failed']`
— so as long as SEO is still retrying, local file cleanup never happens and `is_active` depends
on R2 upload completing independently (which it does since R2 sets `is_active=True`).

However, if R2 is also slow or disabled, the item may never become active.

**Fix — One targeted change:**

In `generate_seo_metadata_task`, when the attempt count crosses the threshold and the task
schedules a 3 AM retry, also immediately set `seo_processing_status = 'failed'`.  
This allows `finalize_media_processing` to proceed without waiting for the 3 AM run.  
The 3 AM retry can still succeed and update SEO fields — the `force_regenerate=True` path handles that.

```python
# In the retry-at-3am branch of generate_seo_metadata_task:
item.seo_processing_status = 'failed'   # ← ADD THIS before scheduling 3am retry
item.save(update_fields=['seo_processing_status'])
raise self.retry(exc=exc, countdown=next_3am_delay)
```

`is_active = True` is set inside `upload_*_to_r2` tasks on R2 upload success — that is the
**only** activation path. No fallback is added to `finalize_media_processing`.

---

## Part 4 — Background Jobs Monitoring Dashboard (New Feature)

> **Requires Phase 4** (`ProcessingJob` model) to be complete before this phase starts.

### 4.1 — Overview

Replace the fragmented ad-hoc job visibility scattered across `system_monitor`, `r2_status_dashboard`,
and `api_queue_list` with a single, unified **Background Jobs Dashboard** at `/dashboard/jobs/`.

**Key actions the admin must be able to perform:**
- View all jobs grouped by status (Active / Pending / Canceled / Completed)
- **Cancel** any in-progress or pending job (revoke Celery task + mark record canceled)
- **Promote** a queued/pending job (move it to the front of the queue for next execution)
- **Dispatch a new job** for any `ContentItem` (choose stage: full reprocess / R2 only / SEO only)

### 4.2 — Data Model

The dashboard draws from two sources unified in one view:

| Source | Covers |
|---|---|
| `ProcessingJob` | Template uploads + admin reprocess actions |
| `APIUploadQueue` | API uploads (external clients) |

Both models must expose enough overlap to be shown in the same table:
- content title, content type, job status, current stage, created_at, updated_at

A view-level helper function `get_all_jobs(status_filter, page, per_page)` merges them.

### 4.3 — Status Definitions

| Status Tab | `ProcessingJob.status` values | `APIUploadQueue.status` values |
|---|---|---|
| **Active** | `processing` | `processing` |
| **Pending** | `pending` | `pending`, `queued`, `rate_limited` |
| **Canceled** | `canceled` (new choice) | `cancelled` |
| **Completed** | `completed` | `completed` |
| **Failed** | `failed` | `failed` |

Add `canceled` to `ProcessingJob.STATUS_CHOICES`.

### 4.4 — URL Structure

```
/dashboard/jobs/                          → jobs_dashboard (main list with status tabs)
/dashboard/jobs/api/list/                 → api_jobs_list (HTMX JSON partial, paginated)
/dashboard/jobs/api/cancel/               → api_job_cancel (POST, JSON body: {job_id, job_source})
/dashboard/jobs/api/promote/              → api_job_promote (POST, JSON body: {job_id, job_source})
/dashboard/jobs/api/dispatch/             → api_job_dispatch (POST, form: content_id, stage)
/dashboard/jobs/api/stats/                → api_jobs_stats (GET, returns counts per status for header badges)
```

### 4.5 — View Specifications

#### `jobs_dashboard(request)` — main page
- Renders `admin/jobs_dashboard.html`
- Context: status counts (active/pending/canceled/completed/failed), current tab (default: `active`)
- HTMX polls `/dashboard/jobs/api/list/?status=active` every 5 seconds for the active tab
- Other tabs load on click (no auto-poll)

#### `api_jobs_list(request)` — HTMX partial
- Query params: `status` (required), `page`, `per_page` (default 20), `search`, `type` (video/audio/pdf/all)
- Returns JSON (or HTMX partial `admin/partials/jobs_table.html`)
- Row data per job:

```json
{
  "id": "uuid",
  "source": "processing_job | api_queue",
  "content_id": "uuid",
  "title": "...",
  "content_type": "video | audio | pdf",
  "status": "active | pending | ...",
  "stage": "file_processing | r2_upload | seo_generation | ...",
  "celery_task_id": "...",
  "retry_count": 0,
  "failure_reason": "...",
  "created_at": "ISO8601",
  "updated_at": "ISO8601",
  "can_cancel": true,
  "can_promote": true
}
```

#### `api_job_cancel(request)` — POST JSON
- Body: `{"job_id": "uuid", "source": "processing_job|api_queue"}`
- For `processing_job`:
  1. Fetch `ProcessingJob` by id
  2. Revoke Celery task: `celery_app.control.revoke(job.celery_task_id, terminate=True)`
  3. Set `job.status = 'canceled'` and save
  4. Set related `ContentItem.processing_status = 'canceled'`
- For `api_queue`:
  1. Fetch `APIUploadQueue` by id
  2. Call existing `APIUploadQueueService.cancel_queue_item(queue_item)` (already exists)
- Returns `{"success": true, "message": "..."}`

#### `api_job_promote(request)` — POST JSON
- Body: `{"job_id": "uuid", "source": "processing_job|api_queue"}`
- For `processing_job` with `status='pending'`:
  1. Re-dispatch the processing task immediately with highest priority
  2. Update `ProcessingJob.celery_task_id` with new task id
- For `api_queue`:
  1. Set `queue_item.priority = 0` (highest) and `queue_item.scheduled_at = now()`
  2. Trigger `process_upload_queue_item.delay(str(queue_item.id))`
- Only pending/queued items can be promoted; active items return a "already running" message

#### `api_job_dispatch(request)` — POST JSON
- Body: `{"content_id": "uuid", "stage": "full|r2_upload|seo_only|text_extraction"}`
- Requires `content_id` to exist as a `ContentItem`
- Creates or resets `ProcessingJob` for the content item, then dispatches task:

```python
STAGE_DISPATCH_MAP = {
    'full':             lambda item: _dispatch_file_processing(item),
    'r2_upload':        lambda item: _dispatch_r2_upload(item),
    'seo_only':         lambda item: generate_seo_metadata_task.apply_async(
                            args=[str(item.id)], kwargs={'force_regenerate': True}, queue='gemini'),
    'text_extraction':  lambda item: extract_and_index_contentitem.delay(str(item.id)),
}
```

- Returns `{"success": true, "task_id": "...", "message": "..."}`

#### `api_jobs_stats(request)` — GET
- Returns live counts per status tab (for badge numbers in navigation):

```json
{
  "active":    3,
  "pending":  12,
  "canceled":  0,
  "completed": 98,
  "failed":    2
}
```

### 4.6 — Frontend Template Structure

```
templates/admin/
├── jobs_dashboard.html          ← main page; status tabs + table container
└── partials/
    ├── jobs_table.html          ← HTMX swap target; renders job rows
    └── jobs_stats_badge.html    ← tiny partial for badge count update
```

The main page uses a tab UI (same pattern as `api_queue_list.html` already in the project).
The active tab auto-refreshes with:

```html
<div id="jobs-table"
     hx-get="/dashboard/jobs/api/list/?status=active"
     hx-trigger="load, every 5s"
     hx-swap="innerHTML">
  {% include "admin/partials/jobs_table.html" %}
</div>
```

Per-row action buttons send HTMX POST to cancel/promote endpoints and re-trigger the list refresh.

### 4.7 — Navigation Integration

Add "Background Jobs" link to the admin sidebar navigation template  
(`templates/admin/includes/sidebar.html` or equivalent). Badge with count of `active + failed` jobs.

---

## Part 5 — Implementation Phases

Each phase ends with a **git commit** to branch `refactor/normalize-background-tasks`.  
Each phase must pass its acceptance criteria before the next phase begins.

---

### Phase 1 — Remove Google Indexing

**Goal:** Eliminate all Google Indexing code. This immediately unblocks the broken
`retry_r2_upload` endpoint (the import error in `admin_views.py` will be gone).

**Files to delete:**
- `apps/frontend_api/tasks.py` (entirely)
- `apps/frontend_api/models_indexing.py`
- `apps/frontend_api/google_seo_service.py`
- `apps/frontend_api/services/google_reindexing_service.py`
- `apps/frontend_api/services/url_generator_service.py` ← verify no other users first
- Remove `GoogleReindexingTask` model from `apps/frontend_api/models.py` (keep migration history)

**Files to edit:**
- `apps/frontend_api/admin_views.py`:
  - Remove the 5 Google Indexing imports (lines 29–35)
  - Remove views: `initiate_google_reindexing`, `seo_reindex_page`, `reindex_status`,
    `cancel_reindex`, `reindex_history`, `indexing_queue_dashboard`, `api_indexing_queue_stats`,
    `api_indexing_queue_items`, `api_process_indexing_queue`, `api_revalidate_invalid_items`,
    `api_retry_failed_items`
  - All R2 views (`r2_status_dashboard`, `retry_r2_upload`, `bulk_retry_r2_uploads`) stay intact
- `apps/frontend_api/urls.py`: remove all 9 Google Indexing URL patterns
- `config/settings/base.py`: remove beat schedule entries and `GOOGLE_*` settings used only by indexing
- `apps/frontend_api/apps.py`: remove any signal connections related to indexing

**Migration:**
- Create data migration `0xxx_remove_google_indexing` to drop data gracefully before structural migration

**Acceptance Criteria:**
- [ ] `python manage.py check` passes with no errors
- [ ] `python manage.py migrate` runs successfully
- [ ] `python -c "from apps.frontend_api import admin_views"` imports without error
- [ ] GET `/en/dashboard/r2/` returns HTTP 200 (not 500)
- [ ] POST `/api/admin/r2/retry/video/<uuid>/` returns HTTP 200 or 400 (not 500)
- [ ] No `GoogleIndexing*` or `GoogleReindexing*` names remain in codebase (`grep -r` confirms)
- [ ] Beat dry-run lists no Google Indexing tasks

**Commit:** `feat: remove Google Indexing API feature — fixes R2 admin retry`

---

### Phase 2 — Fix Duplicate Triggers (P1, P2, P6)

**Goal:** Ensure every content item triggers exactly one file-processing task and exactly one R2
upload task. Eliminate the signal/service race condition.

**Task 2a — Remove processing signals (P6):**
- `signals.py`: delete `trigger_video_processing`, `trigger_audio_processing`,
  `trigger_pdf_processing` and their `@receiver` decorators. Keep all other signals.

**Task 2b — Add Django admin inline save_model overrides (P6):**
- `apps/media_manager/admin.py`: in `VideoMetaInline`, add `save_model()` that calls
  `process_video_to_hls.apply_async(...)` when `instance.original_file` changes and
  `instance.processing_status not in ('processing', 'completed')`.
  Same for `AudioMetaInline` → `process_audio_compression` and `PdfMetaInline` → `process_pdf_optimization`.

**Task 2c — Remove premature R2 trigger in upload_service (P1):**
- `upload_service.py`: delete lines 593–599 (the `upload_*_to_r2.delay()` block after meta creation).

**Task 2d — Remove duplicate R2 dispatch from extract_and_index_contentitem (P2):**
- `apps/media_manager/tasks.py`: delete lines 124–135 (R2 dispatch inside
  `extract_and_index_contentitem`).

**Task 2e — Verify PDF pipeline chain:**
- Confirm `process_pdf_optimization` dispatches both R2 and SEO tasks after calling
  `extract_and_index_contentitem`, not inside `extract_and_index_contentitem` itself.

**Acceptance Criteria:**
- [ ] Upload video via Admin Dashboard: `process_video_to_hls` fires exactly once,
  `upload_video_to_r2` fires exactly once (confirmed in Celery logs)
- [ ] Upload PDF: `process_pdf_optimization` → `extract_and_index_contentitem` → `upload_pdf_to_r2`
  fires exactly once (not from extract task)
- [ ] Direct save of `VideoMeta` in Django admin with new file → `process_video_to_hls` fires once
- [ ] No `trigger_video_processing` / `trigger_audio_processing` / `trigger_pdf_processing` in codebase
- [ ] No `upload_*_to_r2.delay()` in `upload_service.py`
- [ ] No `upload_pdf_to_r2.delay()` inside `extract_and_index_contentitem`

**Commit:** `fix: eliminate duplicate task triggers — single trigger per upload`

---

### Phase 3 — Fix Gemini Failure Blocking (P8)

**Goal:** Ensure a slow or failing Gemini SEO task does not block local file cleanup or content activation.

**Task 3a — Set seo_processing_status='failed' before scheduling 3AM retry:**
- `apps/media_manager/tasks.py`: find the 3 AM retry branch in `generate_seo_metadata_task`.
  Before `raise self.retry(...)`, add:
  ```python
  item.seo_processing_status = 'failed'
  item.save(update_fields=['seo_processing_status'])
  ```

**Task 3b — Verify finalize_media_processing gate:**
- Confirm `seo_done = seo_processing_status in ('completed', 'failed')` — update if needed.

**Acceptance Criteria:**
- [ ] When `generate_seo_metadata_task` schedules a 3 AM retry, `seo_processing_status='failed'`
  is set immediately (not `'processing'`)
- [ ] With `seo_processing_status='failed'` + R2 complete, `finalize_media_processing` runs
  and local files are cleaned up
- [ ] Content item has `is_active=True` after R2 upload completes even if SEO never succeeded
- [ ] 3 AM retry can still set `seo_processing_status='completed'` if it succeeds later

**Commit:** `fix: seo failure no longer blocks file finalization or content activation`

---

### Phase 4 — Add ProcessingJob Model

**Goal:** Persistent, database-backed record of every processing job. Data backbone for Phase 5.

**Task 4a — Define ProcessingJob model** (in `apps/media_manager/models.py`):
```python
class ProcessingJob(models.Model):
    STAGE_CHOICES = [
        ('file_processing', 'File Processing'),
        ('text_extraction', 'Text Extraction'),
        ('r2_upload',       'R2 Upload'),
        ('seo_generation',  'SEO Generation'),
        ('completed',       'Completed'),
    ]
    STATUS_CHOICES = [
        ('pending',    'Pending'),
        ('processing', 'Processing'),
        ('canceled',   'Canceled'),
        ('failed',     'Failed'),
        ('completed',  'Completed'),
    ]
    content_item   = models.OneToOneField('ContentItem', on_delete=models.CASCADE, related_name='processing_job')
    current_stage  = models.CharField(max_length=30, choices=STAGE_CHOICES, default='file_processing')
    status         = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    failure_stage  = models.CharField(max_length=30, blank=True)
    failure_reason = models.TextField(blank=True)
    retry_count    = models.PositiveSmallIntegerField(default=0)
    celery_task_id = models.CharField(max_length=255, blank=True)
    created_at     = models.DateTimeField(auto_now_add=True)
    updated_at     = models.DateTimeField(auto_now=True)
    class Meta:
        indexes = [
            models.Index(fields=['status', 'current_stage']),
            models.Index(fields=['status', 'updated_at']),
        ]
```

**Task 4b — Create and run migration:**
`python manage.py makemigrations media_manager -n add_processing_job_model && python manage.py migrate`

**Task 4c — Auto-create ProcessingJob on ContentItem creation:**
- Extend `create_content_meta` signal to also call `ProcessingJob.objects.get_or_create(content_item=instance)`.

**Task 4d — Add job_tracker helper** (`apps/media_manager/services/job_tracker.py`):
```python
def job_start(content_item_id, stage, celery_task_id=''):
    ProcessingJob.objects.filter(content_item_id=content_item_id).update(
        current_stage=stage, status='processing', celery_task_id=celery_task_id)

def job_fail(content_item_id, stage, reason):
    ProcessingJob.objects.filter(content_item_id=content_item_id).update(
        status='failed', failure_stage=stage, failure_reason=str(reason)[:2000])

def job_advance(content_item_id, next_stage):
    ProcessingJob.objects.filter(content_item_id=content_item_id).update(
        current_stage=next_stage, status='pending')

def job_complete(content_item_id):
    ProcessingJob.objects.filter(content_item_id=content_item_id).update(
        status='completed', current_stage='completed')
```

**Task 4e — Instrument all 9 processing tasks** with `job_start` / `job_fail` / `job_advance` / `job_complete` calls.

**Task 4f — Backfill management command** `backfill_processing_jobs`: create `ProcessingJob` for all existing `ContentItem` records.

**Acceptance Criteria:**
- [ ] `python manage.py migrate` runs without error
- [ ] Creating `ContentItem` via upload creates `ProcessingJob` automatically
- [ ] After successful video upload: `ProcessingJob.status='completed'`, `current_stage='completed'`
- [ ] After a failed task: `ProcessingJob.status='failed'`, `failure_stage` and `failure_reason` populated
- [ ] `ProcessingJob.objects.filter(status='processing')` shows only currently running tasks
- [ ] `backfill_processing_jobs` management command creates records for all existing items
- [ ] `python manage.py check` passes

**Commit:** `feat: add ProcessingJob model for persistent task tracking`

---

### Phase 5 — Background Jobs Monitoring Dashboard

**Goal:** Unified dashboard to monitor and control all background jobs (see Part 4 spec).

**Task 5a — Add URL patterns** (6 new entries in `apps/frontend_api/urls.py`):
```
/dashboard/jobs/
/dashboard/jobs/api/list/
/dashboard/jobs/api/cancel/
/dashboard/jobs/api/promote/
/dashboard/jobs/api/dispatch/
/dashboard/jobs/api/stats/
```

**Task 5b — Implement views** in `apps/frontend_api/admin_views.py`:
- `jobs_dashboard(request)` — renders main page, passes status counts
- `api_jobs_list(request)` — filtered/paginated HTMX JSON list (merges `ProcessingJob` + `APIUploadQueue`)
- `api_job_cancel(request)` — revokes Celery task + sets status `'canceled'`
- `api_job_promote(request)` — re-dispatches pending job at priority
- `api_job_dispatch(request)` — manual dispatch for content_id + chosen stage
- `api_jobs_stats(request)` — returns JSON counts per status tab

**Task 5c — Create templates:**
- `templates/admin/jobs_dashboard.html`: tab bar (Active / Pending / Canceled / Completed / Failed),
  HTMX table container with 5-second auto-refresh on Active tab, filter bar (type, search)
- `templates/admin/partials/jobs_table.html`: table rows with Cancel / Promote / Dispatch buttons,
  empty state message, retry button for Failed tab

**Task 5d — Sidebar navigation:**
- Add "Background Jobs" link to admin sidebar template
- Badge showing `active_count + failed_count` via HTMX poll of `/dashboard/jobs/api/stats/`

**Acceptance Criteria:**
- [ ] GET `/dashboard/jobs/` returns HTTP 200 with 5-tab interface
- [ ] Active tab shows currently processing jobs and auto-refreshes every 5 seconds
- [ ] Pending tab shows jobs with status `pending` / `queued` / `rate_limited`
- [ ] Cancel action: job moves to Canceled tab on next refresh; `celery_app.control.revoke` called
- [ ] Promote action: pending job is re-dispatched; appears in Active tab within 5 seconds
- [ ] Dispatch form with `stage='r2_upload'` triggers correct R2 task for content type
- [ ] Dispatch form with `stage='seo_only'` triggers `generate_seo_metadata_task`
- [ ] Stats API returns correct counts as JSON
- [ ] Sidebar badge shows correct active + failed count
- [ ] Type filter (video/audio/pdf) works in list view
- [ ] All views return HTTP 403 for non-staff users

**Commit:** `feat: add Background Jobs Monitoring Dashboard`

---

### Phase 6 — Worker Reduction + Beat Task Merge (P3, P4, P7)

**Goal:** Reduce from 6 worker containers to 2 and eliminate duplicate beat tasks.

**Task 6a — Merge queue scanning tasks (P4):**
- Rename `process_scheduled_queue_items` → `process_pending_queue_items(include_rate_limited=False)`
- Delete `process_delayed_3am_queue`; merge its logic under the `include_rate_limited=True` flag
- Update beat schedule:
  ```python
  'process-pending-queue': {
      'task': 'apps.media_manager.tasks.process_pending_queue_items',
      'schedule': 3600.0, 'kwargs': {'include_rate_limited': False},
  },
  'process-3am-queue': {
      'task': 'apps.media_manager.tasks.process_pending_queue_items',
      'schedule': crontab(hour=3, minute=0), 'kwargs': {'include_rate_limited': True},
  },
  ```

**Task 6b — Reduce docker-compose workers (P3):**
```yaml
# docker-compose.yml — replace 6 worker services with:
celery_worker_1:
  command: celery -A config worker -Q videos,audios,pdfs,gemini,uploads,default -c 1 -n worker1@%h
celery_worker_2:
  command: celery -A config worker -Q videos,audios,pdfs,gemini,uploads,default -c 1 -n worker2@%h
```

**Task 6c — Enhance cleanup_failed_uploads (P7):**
- After marking `processing_status='failed'`, also call `job_fail(...)` from `job_tracker`
- If `ProcessingJob.retry_count == 0`: auto-retry once (dispatch correct task, increment `retry_count`)

**Acceptance Criteria:**
- [ ] `docker-compose up` starts exactly 2 worker containers
- [ ] All 6 original queue names still work (workers listen on all queues)
- [ ] `process_scheduled_queue_items` function no longer exists in codebase
- [ ] `process_delayed_3am_queue` function no longer exists in codebase
- [ ] `process_pending_queue_items` function exists with `include_rate_limited` parameter
- [ ] Beat schedule has 2 entries for `process_pending_queue_items` (hourly + 3 AM)
- [ ] `cleanup_failed_uploads` updates `ProcessingJob.failure_reason` for stale items
- [ ] Stale items with `retry_count==0` are auto-retried once

**Commit:** `refactor: 2-worker setup + merge beat queue tasks + auto-retry stale jobs`

---

### Phase Summary Table

| Phase | Fixes | New Features | Risk | Depends On |
|---|---|---|---|---|
| 1 — Remove Google Indexing | R2 Retry broken (import error) | — | Low | — |
| 2 — Fix Duplicate Triggers | P1, P2, P6 | — | Medium | — |
| 3 — Fix Gemini Blocking | P8 | — | Low | — |
| 4 — ProcessingJob Model | P5 | New model | Medium | — |
| 5 — Jobs Dashboard | — | Full dashboard | Medium | Phase 4 |
| 6 — Workers + Beat Merge | P3, P4, P7 | — | Low | — |

---

## Part 6 — What Stays Unchanged

| Item | Reason |
|---|---|
| `extract_document_text` task | Legitimate separate concern — supplementary docs only |
| `aggregate_daily_content_views` beat task | Analytics, no issues found |
| `cleanup_expired_queue_items` beat task | Needed to cancel zombie queue items |
| `bulk_generate_seo_metadata` utility task | Useful for backfill operations |
| `delete_files_task` | Clean simple utility |
| `APIUploadQueue` model and queue service | Keep — API rate-limit management is valid |
| `TaskMonitor` Redis tracking | Keep as real-time view; `ProcessingJob` is the persistent record |
| All file-deletion signals in `signals.py` | Correct reactive model cleanup |
| `create_content_meta` signal in `signals.py` | Correct reactive meta-object creation |

---

## Part 7 — Notes / Decisions Log

| # | Decision | Rationale |
|---|---|---|
| 1 | Remove all Google Indexing API tasks and their models | Feature is being dropped; removes ~5 tasks, 3 models, 2 services |
| 2 | Service layer is canonical trigger for processing tasks, not signals | Best practice: signals handle reactive model events, services handle business logic dispatch |
| 3 | `ProcessingJob` model over relying on `TaskMonitor` Redis | Redis keys expire; persistent DB record required for Admin retry and audit |
| 4 | SEO failure → mark `seo_processing_status='failed'` immediately even when scheduling 3 AM retry | Prevents `finalize_media_processing` from being blocked indefinitely |
| 5 | R2 upload activates content (`is_active=True`) — no fallback added | Content activates when media is delivered via R2; SEO is an enhancement not a prerequisite. No alternative activation path added. |
| 6 | Reduce to 2 global workers (concurrency=1 each) | Limited RAM/CPU; per-type serialization via Redis locks compensates |
| 7 | Keep `APIUploadQueue` for API path, template path remains direct | Two legitimate paths with different rate-limit requirements |
| 8 | Root cause of broken R2 admin retry: Google Indexing import failure | When `apps.frontend_api.tasks` or `models_indexing` fail to import, entire `admin_views.py` fails to load, making every admin endpoint return 500 |
| 9 | Background Jobs Dashboard reads from both `ProcessingJob` and `APIUploadQueue` | Two sources needed: template uploads tracked in `ProcessingJob`, API uploads tracked in `APIUploadQueue` |
| 10 | Cancel action uses `celery_app.control.revoke(terminate=True)` | Hard-stops running tasks; terminate=True sends SIGTERM to the worker process executing the task |

---

## Progress Update

- [x] Removed Google Indexing imports from `apps/frontend_api/admin_views.py`
- [x] Removed Google Indexing URL patterns from `apps/frontend_api/urls.py`
- [x] Removed the Google Indexing Celery route from `config/settings/base.py`
- [x] Deleted the Google Indexing task and service modules
- [x] Removed Google Indexing queueing from `apps/media_manager/signals_seo.py`
- [x] Removed the Google Indexing API implementation from `apps/frontend_api/google_seo_service.py`
- [x] Replaced `apps/frontend_api/models.py` with a minimal module
- [x] `python manage.py check` passes in the backend virtual environment
- [x] Removed processing-trigger signals from `apps/media_manager/signals.py`
- [x] Removed premature R2 dispatch from `apps/media_manager/services/upload_service.py`
- [x] Removed duplicate PDF R2 dispatch from `apps/media_manager/tasks.py`
- [x] Added admin inline save hook for direct media edits in `apps/media_manager/admin.py`
- [x] Set `seo_processing_status='failed'` before the 3 AM Gemini retry in `apps/media_manager/tasks.py`
