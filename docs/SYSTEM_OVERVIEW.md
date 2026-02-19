# System Overview

## 1. Architecture Summary

This Django-based web application is a modular, media-heavy platform for a Christian Library. It uses a classic MVC pattern with modular apps for core logic, media management, user management, frontend APIs, and courses. The system supports PDF, audio, and video streaming, full-text search, SEO, and background processing via Celery. Bootstrap and HTMX are used for responsive, interactive frontend components. The project is Dockerized for local and production environments.

## 2. Systems & Modules

### 2.1 Authentication
- **Purpose:** User login, registration, and permissions.
- **Entry Points:** `/users/` URLs, Django admin, login/logout views.
- **Dependencies:** Django auth, users app.
- **Data Flow:** Request → Auth middleware → User model → Response.

### 2.2 Media Management
- **Purpose:** Upload, process, and serve PDF, audio, and video files.
- **Entry Points:** `/media_manager/` URLs, admin upload forms, Celery tasks.
- **Dependencies:** PyMuPDF, pdfminer, Tesseract, FFmpeg, Celery, PostgreSQL.
- **Data Flow:** Upload → Model save → Celery task (compression/extraction) → Storage → Serve via Nginx/static.

### 2.3 Search
- **Purpose:** Full-text search across media content (PDF, audio, video).
- **Entry Points:** `/search/` endpoints, search UI in templates.
- **Dependencies:** PostgreSQL FTS, SearchVectorField, Django ORM.
- **Data Flow:** Query → Search view → FTS lookup → Results → Template render.

### 2.4 SEO & Sitemap
- **Purpose:** Expose sitemap.xml, robots.txt, and SEO meta tags for search engines.
- **Entry Points:** `/sitemap.xml`, `/robots.txt`, dynamic meta tags in templates.
- **Dependencies:** Django sitemaps, custom views.
- **Data Flow:** Request → View → Static/dynamic file or template → Response.

### 2.5 Admin Panel
- **Purpose:** Manage content, users, and system settings.
- **Entry Points:** `/admin/`, custom admin views in `admin_views.py`.
- **Dependencies:** Django admin, custom admin modules.
- **Data Flow:** Admin request → Admin view → Model/form → Template render.

### 2.6 Background Processing
- **Purpose:** Offload heavy tasks (PDF extraction, compression, indexing) to Celery workers.
- **Entry Points:** Model save signals, management commands, admin actions.
- **Dependencies:** Celery, Redis, Tesseract, FFmpeg.
- **Data Flow:** Trigger → Celery task → Worker → Update model/storage/logs.

### 2.7 Monitoring & Metrics
- **Purpose:** Track DB query performance, system health, and export metrics.
- **Entry Points:** Middleware, `/core/views/monitoring.py`, management commands.
- **Dependencies:** Custom middleware, JSONL logs, export commands.
- **Data Flow:** Request → Middleware → Log → Export/analysis.

## 3. Routes & Views Map

### Main Application Routes

| URL Path | HTTP Methods | View | Template | Notes |
|----------|--------------|------|----------|-------|
| `/` | GET | `home` | `frontend_api/home.html` | Home, featured content |
| `/videos/` | GET | `videos` | `frontend_api/videos.html` | Video listing |
| `/videos/<uuid>/` | GET | `video_detail` | `frontend_api/video_detail.html` | Video detail |
| `/audios/` | GET | `audios` | `frontend_api/audios.html` | Audio listing |
| `/audios/<uuid>/` | GET | `audio_detail` | `frontend_api/audio_detail.html` | Audio detail |
| `/pdfs/` | GET | `pdfs` | `frontend_api/pdfs.html` | PDF listing |
| `/pdfs/<uuid>/` | GET | `pdf_detail` | `frontend_api/pdf_detail.html` | PDF detail |
| `/search/` | GET | `search` | `frontend_api/search.html` | Search UI, HTMX/JS |
| `/search/autocomplete/` | GET | `search_autocomplete` | - | AJAX autocomplete |
| `/tags/<uuid>/` | GET | `tag_content` | `frontend_api/tag_content.html` | Tag-based filter |
| `/player/audio/<uuid>/` | GET | `audio_player` | `components/audio_player.html` | Embedded audio |
| `/player/video/<uuid>/` | GET | `video_player` | `components/video_player.html` | Embedded video |
| `/player/pdf/<uuid>/` | GET | `pdf_player` | `components/pdf_viewer.html` | Embedded PDF |

### Admin & Management

| URL Path | HTTP Methods | View | Template | Notes |
|----------|--------------|------|----------|-------|
| `/admin/` | GET | `admin_dashboard` | `admin/dashboard.html` | Custom admin landing |
| `/admin/content/` | GET | `content_list` | `admin/content_list.html` | Content management |
| `/admin/content/<uuid>/` | GET | `content_detail` | `admin/content_detail.html` | Content detail |
| `/admin/upload/` | GET/POST | `upload_content` | `admin/upload_content.html` | Upload form |
| `/admin/upload/handle/` | POST | `handle_content_upload` | - | Handles upload |
| `/admin/upload/generate/` | POST | `generate_content_metadata` | - | Gemini AI integration |
| `/admin/videos/` | GET | `video_management` | `admin/video_management.html` | Video admin |
| `/admin/audios/` | GET | `audio_management` | `admin/audio_management.html` | Audio admin |
| `/admin/pdfs/` | GET | `pdf_management` | `admin/pdf_management.html` | PDF admin |
| `/admin/system/` | GET | `system_monitor` | `admin/system_monitor.html` | System stats |
| `/admin/bulk/` | GET | `bulk_operations` | `admin/bulk_operations.html` | Bulk tools |

### API & System

| URL Path | HTTP Methods | View | Template | Notes |
|----------|--------------|------|----------|-------|
| `/api/health/` | GET | `api_health` | - | Health check (JSON) |
| `/api/home-data/` | GET | `api_home_data` | - | Home stats (JSON) |
| `/api/search/` | GET | `api_global_search` | - | Search API (JSON) |
| `/api/stats/` | GET | `api_content_stats` | - | Content stats (JSON) |
| `/api/toggle-status/` | POST | `api_toggle_content_status` | - | Admin toggle |

### System/Monitoring

| URL Path | HTTP Methods | View | Template | Notes |
|----------|--------------|------|----------|-------|
| `/health/` | GET | core monitoring | - | Health endpoints |
| `/core/monitoring/` | GET | MonitoringDashboardView | `admin/monitoring/dashboard.html` | System dashboard |
| `/api/system-metrics/` | GET | system_metrics_api | - | System metrics (JSON) |
| `/api/performance-metrics/` | GET | performance_metrics_api | - | Perf metrics (JSON) |
| `/api/error-analysis/` | GET | error_analysis_api | - | Error analysis (JSON) |
| `/api/alerts/` | POST | alerts_api | - | Alert ingest (JSON) |
| `/api/query-analysis/` | GET | query_analysis_api | - | Query analysis (JSON) |
| `/api/health-check/` | GET | health_check_api | - | Health check (JSON) |

### SEO & Static

| URL Path | HTTP Methods | View | Template | Notes |
|----------|--------------|------|----------|-------|
| `/sitemap.xml` | GET | sitemap | - | XML sitemap |
| `/robots.txt` | GET | robots_txt | - | Robots.txt |

### Media (Legacy/Deprecated)

| URL Path | HTTP Methods | View | Template | Notes |
|----------|--------------|------|----------|-------|
| `/media_manager/serve/<type>/<uuid>/` | GET | DirectMediaServeView | - | Deprecated, replaced by Nginx X-Accel |
| `/media_manager/secure/<type>/<uuid>/` | GET | SecureMediaView | - | Deprecated |
| `/media_manager/hls/<uuid>/` | GET | HLSStreamView | - | Deprecated |
| `/media_manager/player/<type>/<uuid>/` | GET | MediaPlayerView | - | Deprecated |

### User/Auth

| URL Path | HTTP Methods | View | Template | Notes |
|----------|--------------|------|----------|-------|
| `/users/` | ... | users app | registration/*, users/* | User auth/profile |

### Error Pages

| URL Path | HTTP Methods | View | Template | Notes |
|----------|--------------|------|----------|-------|
| `/400/` | GET | bad_request | errors/400.html | Dev only |
| `/403/` | GET | permission_denied | errors/403.html | Dev only |
| `/404/` | GET | page_not_found | errors/404.html | Dev only |
| `/500/` | GET | server_error | errors/500.html | Dev only |

---

## 4. Templates Map

### Main Layouts
- `base.html`: Root layout, includes Bootstrap, navigation, static assets.
- `layouts/admin_base.html`: Admin layout, used by all admin templates.

### Main Content Templates
- `frontend_api/home.html`: Home page (home view)
- `frontend_api/videos.html`, `audios.html`, `pdfs.html`: Listing pages
- `frontend_api/video_detail.html`, `audio_detail.html`, `pdf_detail.html`: Detail pages (use unified metadata)
- `frontend_api/search.html`: Search UI (HTMX/JS, includes `components/media_card.html`)
- `frontend_api/tag_content.html`: Tag-based filter

### Components/Partials
- `components/media_card.html`: Used in listings/search, displays media summary
- `components/video_player.html`, `audio_player.html`, `pdf_viewer.html`: Embedded players/viewers for detail pages and `/player/` endpoints

### Admin Templates
- `admin/dashboard.html`: Admin dashboard (stats, upload button)
- `admin/content_list.html`: Content management (HTMX search/filter)
- `admin/content_detail.html`: Content detail
- `admin/upload_content.html`: Upload form (AI integration)
- `admin/video_management.html`, `audio_management.html`, `pdf_management.html`: Type-specific admin
- `admin/system_monitor.html`: System stats
- `admin/bulk_operations.html`: Bulk tools
- `admin/partials/content_list.html`: Table partial for content list

### Error & Misc
- `errors/400.html`, `403.html`, `404.html`, `500.html`: Error pages
- `includes/navbar.html`, `footer.html`: Navigation/footer
- `registration/*`, `users/*`: User auth/profile

### Template Relationships
- Most detail/listing templates include `components/media_card.html` for media display.
- Detail pages use embedded player partials (`video_player.html`, etc.).
- Admin templates extend `layouts/admin_base.html` and use partials for tables/forms.
- Search UI uses HTMX for live updates.

### Unused/Legacy Templates
- Some templates in `admin/` and `components/` may be unused (see Potential Dead Code).

---

## 5. Static & JS Interaction Map

### Static Assets
- `static/js/pdf.min.js`, `pdf.worker.min.js`: PDF.js for PDF viewing (used in `pdf_detail.html`, `pdf_viewer.html`)
- Bootstrap, custom CSS for theming and layout

### JS/HTMX Interactions
- **HTMX**: Used in admin/content_list.html and search.html for live search/filter (hx-get, hx-target)
- **JS fetch/AJAX**: Used for admin upload, Gemini AI integration, and some API endpoints
- **PDF.js**: Used for PDF rendering in detail and player views

### Endpoints Called by JS/HTMX
- `/search/autocomplete/`: AJAX autocomplete (search box)
- `/admin/upload/generate/`: Gemini AI content generation (fetch)
- `/api/*`: Health, stats, search, toggle-status (admin dashboard, stats cards)
- `/core/monitoring/` APIs: System metrics (admin/system_monitor.html)

### Endpoints Not Called by JS
- Most guest-facing views (home, detail, listing) are rendered server-side

### Unused/Legacy Static
- Some JS/CSS files may not be referenced in any template (see Potential Dead Code)

---

## 6. Background & Media Processing

### PDF Processing
- Upload triggers compression (Ghostscript), text extraction (pdfminer, PyMuPDF), and OCR fallback (Tesseract, Arabic/English)
- Extraction/indexing handled by Celery task `extract_and_index_contentitem` (triggered on ContentItem.save or via bulk_extract_index command)
- Extracted text saved to `book_content`, indexed in PostgreSQL FTS
- Management command `bulk_extract_index` for batch processing

### Audio/Video Processing
- Audio: Compressed to 192kbps MP3 (FFmpeg), size-limited, metadata extracted
- Video: HLS streaming generated (FFmpeg), multiple resolutions, thumbnails
- All media stored in organized directories (`original/`, `compressed/`, `hls/`, etc.)

### Queue/Worker Logic
- Celery tasks for all heavy processing (PDF, audio, video)
- Redis as broker, logs progress/errors
- Management commands for bulk/batch jobs

### Monitoring & Metrics
- UnifiedDBQueryMetricsMiddleware logs all DB queries, detects N+1, slow queries, duplicates
- Export via `export_db_query_metrics` management command (JSONL/CSV)
- Admin/system_monitor uses metrics APIs for real-time stats

---

## 7. Potential Dead Code (NOT REMOVED YET)

---



## 8. Removed Components & Rationale

### 8.2 Legacy/Backup Files (2026-01-29)

- **What was removed:**
	- All legacy/backup files: `admin_backup.py`, `admin_new.py`, `admin_refactored.py`, `views_new.py`, `views_refactored.py` in `media_manager/`, `courses/`, `users/`, `frontend_api/` (only those that existed)
- **Why it was removed:**
	- Not referenced or imported anywhere in the codebase, not called by any route, view, template, or JS/API consumer.
	- Confirmed as legacy/backup by audit and SYSTEM_OVERVIEW.md.
- **What remains:**
	- All primary, production, and referenced files remain.

### 8.3 Deprecated Service Modules (2026-01-29)

- **What was removed:**
	- `services_legacy.py` in `media_manager/`
	- `services.py` in `media_manager/` (deprecated, all usage migrated to new modules)
- **Why it was removed:**
	- Not referenced by any current code, all usage is via new service modules.
- **What remains:**
	- All active service modules in `services/` directories remain.

### 8.4 Deprecated Endpoints in media_manager/urls.py (2026-01-29)

- **What was removed:**
	- All deprecated endpoints: `DirectMediaServeView`, `SecureMediaView`, `HLSStreamView`, `MediaPlayerView` (and related URL patterns)
- **Why it was removed:**
	- No longer referenced by any template, JS, or API consumer; all media serving is now handled by Nginx or frontend_api.
- **What remains:**
	- Only current, referenced endpoints remain in media_manager/urls.py.


### 8.1 File: md files/test_gemini_integration.py

- **What was removed:**
	- `md files/test_gemini_integration.py`
- **Why it was removed:**
	- This file was not referenced or imported anywhere in the codebase (confirmed by codebase search and SYSTEM_OVERVIEW.md audit).
	- It was not called by any route, view, template, or JS/API consumer.
	- It was already marked as deleted and safe to remove in the previous audit summary.
- **What remains:**
	- All other files, templates, routes, and logic remain unchanged.
	- No business logic, admin, or user-facing functionality was affected.
	- All removals are reference-based and fully auditable.

---

## 9. Possibly Unused (Audit Needed)


The following files are not referenced by any view, included partial, or template, and are only marked for audit. They are NOT deleted:

- **Templates not referenced by any view or included partials**
- **JS/CSS files not included in any template**

These require further manual or automated audit before any removal. If any doubt exists, these files are retained for now.



// All items above have been permanently removed as of 2026-01-29. See Section 8 for rationale and audit trail.
- Templates and static files not referenced by any view or included partials are only marked as “Possibly Unused” (audit needed), not deleted.
- Management commands or Celery tasks not triggered by any workflow (audit needed)

**Note:** This section only documents potential dead code for review in Phase 2. No code has been removed or modified except for files that are provably unused and safe to delete (see summary below).


### Deletion/Marking Summary (Phase 2, ongoing)

- **Deleted:**
	- `md files/test_gemini_integration.py` (provably unused, not referenced anywhere, safe per audit rules; see Section 8)
- **Marked as Possibly Unused (audit needed, not deleted):**
	- Templates not referenced by any view or included partials
	- JS/CSS files not included in any template

Further deletions will proceed one file or logical unit at a time, always re-checking references after each deletion. All removals are explicitly documented in Section 8.
