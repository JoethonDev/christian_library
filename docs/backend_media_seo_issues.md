# Christian Library Project: Current Issues & Fixes

This document tracks current issues, planned phases, and progress for backend media/SEO improvements. Each issue will be updated and marked as fixed when resolved.

---


## Completed Issues
### 1. SEO Generation Blocking Activation
- **Description:** SEO metadata generation currently blocks content activation. Admins must wait for SEO to finish before activating items. Visitors cannot access content until SEO completes.
- **Planned Fix:** Decouple SEO generation from activation. Allow admin to activate items and visitors to access content/media while SEO runs in background.
- **Status:** ✅ Fixed
- **Implementation Details:**
    - Added `seo_processing_status` to `ContentItem` model.
    - Updated `ContentItem.clean()` to validate `r2_upload_status`.
    - Parallelized tasks in `tasks.py` and `media_processing.py`.
    - Added `finalize_media_processing` task for safe local file cleanup.

### 2. Serving Static Files from R2
- **Description:** Videos, audios, and PDFs are now served via Nginx proxy to Cloudflare R2 public bucket with local edge caching.
- **Implementation Details:**
    - Configured Nginx with `proxy_cache_path` and `proxy_pass` to R2 bucket.
    - Standardized R2 keys in `storage_backends.py` to match local relative paths.
    - Updated `SecureMediaMixin` in `nginx_security.py` to support Nginx proxying without local file checks.
    - Fixed `pdf_detail.html` and other templates to use `secure_media` and `secure_stream` tags for consistent R2 serving.
- **Status:** ✅ Fixed (Verified serving & caching architecture)

### 3. Automatic Activation After R2 Upload
- **Description:** Automation of content availability purely based on successful Cloudflare R2 persistence.
- **Implemented Fix:** Modified background tasks to automatically set `is_active = True` upon successful R2 upload of videos, audios, and PDFs.
- **Status:** ✅ Fixed
- **Implementation Details:**
    - Updated `upload_video_to_r2`, `upload_audio_to_r2`, and `upload_pdf_to_r2` in `backend/core/tasks/media_processing.py` to trigger activation on success.
    - Ensures content is immediately reachable by users once safely stored in the cloud.

### 4. Use Direct URLs for Media Downloads
- **Description:** Shift from proxied/masked media serving (via Django `SecureMediaView`) to direct R2/Nginx URLs to optimize performance and leverage CDN/local caching.
- **Implemented Fix:** Added unified helper methods to metadata models and updated all frontend/admin templates to use direct URLs.
- **Status:** ✅ Fixed
- **Implementation Details:**
    - Added `get_direct_download_url()`, `get_direct_playback_url()`, and `get_direct_viewing_url()` to `VideoMeta`, `AudioMeta`, and `PdfMeta` in `backend/apps/media_manager/models.py`.
    - These methods prioritize `r2_..._url` fields, falling back to local storage `.url` if R2 is not available.
    - Updated `video_detail.html`, `audio_detail.html`, `pdf_detail.html`, `pdf_viewer.html`, `pdf_management.html`, and player components to use these direct methods.
    - Eliminated reliance on the `core_utils:secure_media` template tag for media delivery.

### 5. Remove Nginx Settings/Config from Application
- **Description:** Remove all Nginx-related settings and configuration from the Django application project. Only the external `nginx.conf` should be used for Nginx configuration.
- **Status:** ✅ Fixed
- **Implementation Details:**
    - Removed `nginx_secure_media.conf` from the backend directory.
    - Deleted `NGINX_MEDIA_SERVING` configuration and related keys from `production.py` and `base.py`.
    - Removed `SecureMediaMixin` and `SecureMediaView` dependencies on internal Nginx configs.
    - Ensured static and media URLs are handled externally by Nginx.

### 6. Remove Secure Media URLs and Routes
- **Description:** Remove all secure media URLs, routes, and related logic from backend models, core utilities, and settings. Media should no longer be routed through Django for security or masking.
- **Rationale:** With direct R2/Nginx serving, Django's secure/proxied media endpoints are obsolete.
- **Status:** ✅ Fixed
- **Implementation Details:**
    - Hard deleted `backend/core/utils/nginx_security.py` and `backend/core/utils/media_security.py`.
    - Removed `secure_media` and `secure_stream` re_path patterns from `backend/core/urls.py`.
    - Refactored `backend/apps/media_manager/views.py` to remove all secure serving logic and redundant player views.
    - Updated `base.py` to remove media signing settings and token cleanup tasks.

### 7. Modern Admin UI Refactoring
- **Description:** Complete overhaul of the Admin Dashboard using a "Soft UI" aesthetic, Bootstrap 5, and Alpine.js.
- **Status:** ✅ Fixed (Core Admin UI & Navigation Refactored)
- **Implementation Details:**
    - Created standalone `admin_base.html` to isolate admin and frontend styles.
    - Modernized all management lists (Video, Audio, PDF) with unified tables, tags, and status toggles.
    - Implemented a global Toast notification system to replace browser alerts.
    - Added real-time XHR upload progress bars.

### 8. Remove Sacred Processing Queue from UI
- **Description:** Remove the Sacred Processing Queue from the admin UI; keep logs for background processing only.
- **Status:** ✅ Fixed
- **Implementation Details:**
    - Removed task list widgets from dashboards.
    - Dedicated task monitoring moved to System Monitor log view.

### 9. Hide Bulk Operations from UI
- **Description:** Hide bulk operations controls from the admin UI to prevent accidental mass changes.
- **Status:** ✅ Fixed
- **Implementation Details:**
    - Removed bulk checkbox selections and mass-action buttons from all management templates.

### 10. Display Extracted PDF Text in Admin
- **Description:** Display extracted PDF text inside the admin detail/management views for easy review.
- **Status:** ✅ Fixed
- **Implementation Details:**
    - Added Alpine.js-powered expandable sections in `pdf_management.html` to view `book_content`.
    - Styled with monospace font and RTL support for Arabic text.

### 11. Expandable Task Logs in System Monitor
- **Description:** Task logs in the system monitor should be easily accessible without overlapping the UI.
- **Status:** ✅ Fixed
- **Implementation Details:**
    - Implemented inline row expansion (`<tr>`) in System Monitor using Alpine.js.
    - Logs now slide out directly under the record using a terminal-styled interface.

### 12. Background Task Progress Accuracy
- **Description:** Background tasks for media processing never reach 100% completion in the UI, causing confusion for admins.
- **Implementation Plan:**
    - Audit all background task progress reporting logic in Celery tasks and frontend polling endpoints.
    - Identify where progress is calculated and why it may not reach 100% (e.g., missing final update, async race conditions, or error states).
    - Specifically check Gemini service integration: if Gemini task does not complete after 2 attempts, mark the task as failed and set progress = 100% to unblock UI.
    - Ensure all task completion/failure states explicitly set progress to 100% and update the database/UI accordingly.
    - Add tests for edge cases (timeouts, retries, failures) to verify correct progress reporting.
    - Update admin and user-facing UIs to reflect accurate progress and clear error/failure messages.
- **Status:** ✅ Fixed

### 13. R2 Storage Usage Reporting
### 14. Modular R2 Service Refactoring
- **Description:** Centralize R2 storage logic into a unified, modular service to improve maintainability and follow DRY principles.
- **Implementation Plan:**
    - **Service Architecture:**
        - Created `backend/core/services/r2_service.py` to house the `R2Service` class.
        - Moved all `boto3` client initialization and configuration here, reading from environment variables.
    - **Core Functionality:**
        - Implemented methods for `upload_file`, `delete_file`, `get_presigned_url`, and `get_bucket_metrics`.
        - Added unified logging and error handling for R2-specific exceptions (e.g., ClientError, NoSuchKey).
    - **Integration:**
        - Replaced scattered upload logic in `media_processing.py` and `storage_backends.py` with calls to the new `R2Service`.
        - Standardized the mapping of local file paths to R2 keys across all media types.
- **Status:** ✅ Fixed

### 15. Frontend Component UI Refactoring
- **Description:** Modernize public-facing media components (players, grids) for better mobile UX and visual consistency.
- **Implementation Plan:**
    - **Sticky Action Button:** Removed the white background from the sticky "Download" button across all media detail pages for a cleaner overlay look.
    - **Player Container Enhancements:** 
        - Removed negative margins in `player-container` to prevent it from sticking awkwardly to screen edges.
        - Fixed border radius issues: eliminated sharp outer borders and ensured consistent rounding for both container and inner player.
    - **Audio Player Aesthetics:** Updated background colors and the "media play" icon/accent colors for a modern, high-contrast look.
    - **PDF Scaling:** Optimized PDF viewing components to ensure they scale correctly on mobile devices without layout corruption.
    - **Video Layout:** Removed redundant video play containers and allowed the player to occupy its full native view size.
    - **Responsive Detail Pages:** Refactored all `*_detail.html` templates to use a simple, icon-light layout with Bootstrap 5 mobile-first utilities.
- **Status:** ✅ Fixed
- **Description:** Add ability to view total storage usage for Cloudflare R2 bucket from the admin dashboard.
- **Implementation Plan:**
    - Integrate with Cloudflare R2 API to fetch current bucket storage usage (in GBs).
    - Implement a backend service or scheduled task to periodically retrieve and cache usage data.
    - Expose storage usage via a new API endpoint for the admin dashboard.
    - Display usage in the admin dashboard with clear formatting (e.g., "Current R2 Usage: 123.45 GB").
    - Add error handling for API failures and display fallback messages if usage cannot be retrieved.
    - Document setup and API key requirements for R2 integration.
- **Status:** ✅ Fixed

### 16. SEO & Metadata Improvements
- **Description:** Improve SEO and metadata generation with distinct workflows, multi-lingual support, and optimized search engine surfacing.
- **Status:** ✅ Fixed
- **Implementation Details:**
    - API refactoring with `generate-metadata-only/` and `generate-seo-only/` endpoints.
    - Dual-request workflow for parallel AI metadata and SEO generation.
    - Unified JSON schema for AI responses.
    - Prompt engineering for Google SEO, enforcing character limits and niche constraints.
    - Multi-lingual and contextually accurate keyword/description generation.

### 17. Content Management Dashboard Actions
- **Description:** Added quick-action items and improved UX for identifying and fixing missing content data, with modal confirmations and bulk operations.
- **Status:** ✅ Fixed
- **Implementation Details:**
    - Data flags and UI filters for missing data.
    - Quick-action and bulk-action buttons with modal confirmations.
    - Efficient backend endpoints for batch processing.
    - Bootstrap 5 modals and success/error toasts for all actions.
    - Comprehensive tests for single and bulk actions.

### 18. Checking and Updating robots.txt and sitemap for SEO
- **Description:** Ensured robots.txt and all sitemap files are always correctly generated, up-to-date, and accessible for web crawlers to optimize SEO indexing. Automated updates and notifications for every new or modified media content, following Google SEO best practices.
- **Status:** ✅ Fixed
- **Implementation Details:**
    - robots.txt dynamically managed and documented.
    - XML sitemap automation for index, pages, and video sitemaps.
    - Schema & structured data injected into all landing pages.
    - Google Indexing API integration and automated pinging.
    - RSS/Atom feed updates and Google ping on every change.
    - Admin dashboard indicators for sitemap/robots status.
    - All endpoints validated with Google Search Console and Rich Results tools.
    - Complete documentation for SEO crawler configuration.

### 19. Checking and Updating robots.txt and sitemap for SEO
- **Description:** Ensured robots.txt and all sitemap files are always correctly generated, up-to-date, and accessible for web crawlers to optimize SEO indexing. Automated updates and notifications for every new or modified media content, following Google SEO best practices.
- **Status:** ✅ Fixed
- **Implementation Details:**
    - robots.txt dynamically managed and documented.
    - XML sitemap automation for index, pages, and video sitemaps.
    - Schema & structured data injected into all landing pages.
    - Google Indexing API integration and automated pinging.
    - RSS/Atom feed updates and Google ping on every change.
    - Admin dashboard indicators for sitemap/robots status.
    - All endpoints validated with Google Search Console and Rich Results tools.
    - Complete documentation for SEO crawler configuration.
 
### 20. Gemini Fallback Models and Rate Limiting
- **Description:** Make fallback models for Gemini. Create a dedicated model for SEO and another for metadata generation to respect Gemini API rate limits and ensure robust operation.
- **Implementation Details:**
     - Created `gemini_rate_limit_service.py` to manage rate limits with Redis caching.
     - Updated `BaseGeminiService` to support multiple models with fallback logic.
     - `GeminiMetadataService` uses Gemini 2.5 Flash as primary model.
     - `GeminiSEOService` uses Gemini 3 Flash as primary model.
     - Both services automatically fall back to Gemini 2.5 Flash Lite if rate limits are hit.
     - Created `GeminiManager` to centralize all Gemini operations.
     - Added `/api/admin/gemini-rate-limits/` endpoint for fetching rate limit data.
     - Updated `admin_dashboard.html` to display rate limits for all models with live progress bars.
     - Updated `system_monitor.html` to display detailed rate limit monitoring with auto-refresh.
     - Rate limit data is cached in Redis for 6 hours and auto-refreshed.
     - UI shows per-minute and per-day limits with visual progress indicators.
     - Status badges indicate whether models are "Available", "Limited", or "Exhausted".
 - **Status:** ✅ Fixed

### 21. Content Viewing Analytics & Admin Analytics Page
- **Description:** Build analytics for content viewing (videos, audios, PDFs, static pages) without requiring login, and create analytics dashboard in admin UI.
- **Status:** ✅ Fixed
- **Implementation Details:**
    - Created `ContentViewEvent` and `DailyContentViewSummary` models for anonymous tracking.
    - Implemented `record_content_view()` utility for automatic tracking in media detail views.
    - Added nightly Celery task `aggregate_daily_content_views()` for data summary and cleanup.
    - Developed a comprehensive Admin Analytics Dashboard with Chart.js visualizations.
    - Exposed analytics data via staff-only JSON API for custom reporting.

### 22. Advanced PDF Search with OCR
- **Description:** Implement advanced search functionality within PDF content using OCR, enabling users to search for text inside scanned or image-based PDFs.
- **Status:** ✅ Fixed
- **Implementation Details:**
    - Integrated PDF text extraction using `pdfminer` and `fitz` (PyMuPDF) with OCR fallback.
    - Added `book_content` field to `ContentItem` to store extracted text.
    - Implemented PostgreSQL Full-Text Search (FTS) with Arabic configuration.
    - Added strategic GIN indexes for high-performance search across titles, descriptions, and content.
    - Updated search logic to rank results based on relevance.

### 23. Fix Saving JSON-LD Schema
**Description:**
Ensure that the JSON-LD structured data generated for each content item is correctly saved and updated in the database (e.g., in the `structured_data` field of the ContentItem model). The schema must be stored as a native JSONB field (not as an escaped string or text) to allow for efficient querying, validation, and future extensibility. The schema must always be in sync with the latest content and SEO changes.

**Status:** ✅ Fixed
**Implementation Details:**
- All JSON-LD data is stored as native JSONB (using Django's `JSONField`).
- Added `sync_structured_data` method to `ContentItem` model to automatically keep schema in sync with content (name, description, URL, language) on `save()`.
- Refactored `ContentService`, `GeminiService`, and the Admin API to handle `structured_data` as native dictionaries, eliminating double-stringification and escaping issues.
- Updated `ContentItemForm` with custom validation and pretty-printing for JSON-LD.
- Updated SEO Dashboard frontend to handle native JSON objects from the API.
- Created developer documentation in `docs/DEVELOPER_JSONLD_SCHEMA.md`.
- Added automated tests in `apps/media_manager/test_jsonld.py`.

### 24. Content and Tag Search
- **Description:** Enable users to search for content and tags within the website, allowing them to efficiently find items by title, description, and associated tags.
- **Planned Fix:**
    - Add full-text search endpoints for items and tags.
    - Update UI to support search and filtering by tags.
    - Optimize search for both Arabic and English content.
    - Ensure search is fast, accurate, and user-friendly.
- **Status:** ✅ Fixed

### 25. Make Arabic name default to uploaded file name
**Description:**
When uploading a file, set the Arabic name field to the uploaded file's name by default if not provided.

**Status:** ✅ Fixed
**Implementation Details:**
- Updated `ContentItem` model to allow `blank=True` for `title_ar`.
- Implemented `_clean_filename` helper to remove extensions and replace underscores/hyphens with spaces.
- Modified `ContentItem.save()` to populate `title_ar` from media metadata if empty.
- Added `save()` overrides to `VideoMeta`, `AudioMeta`, and `PdfMeta` to trigger title population on file upload.
- Updated `ContentItemForm` and `upload_content.html` to allow empty titles and provide real-time preview of the cleaned filename.

### 26. Fix Gemini limits in UI and Redis counting
**Description:**
Ensure Gemini API rate limits are displayed accurately in the UI and that Redis counters are always in sync with actual usage.

**Status:** ✅ Fixed
**Implementation Details:**
- Refactored `GeminiRateLimitService` to use atomic Redis `incr` with UTC-based keys (`YYYYMMDDHHMM` for minutes, `YYYYMMDD` for days).
- Standardized limit buckets for `gemini-3-flash-preview` (SEO) and `gemini-2.5-flash` (Metadata) at 15 RPM / 1500 RPD.
- Fixed `UnboundLocalError` in `ContentItem.update_seo_from_gemini` by mapping `seo_keywords_en` correctly in legacy paths.
- Updated Admin Dashboard and System Monitor JS to match backend response keys (`remaining_requests_minute`).
- Ensured 00:00 UTC reset alignment with Google API windows using `django.utils.timezone.now()`.

### 27. Fix tags display in admin management views
**Description:**
Fix the display of tags in audio_management, pdf_management, and video_management in the admin dashboard to match the content_management view (copy the implementation).

**Status:** ✅ Fixed
**Implementation Details:**
- Synced tag rendering logic across `video_table.html`, `audio_table.html`, and `pdf_table.html` with the main `content_list.html`.
- Implemented multi-lingual tag support (`name_ar` / `name_en`) with a 3-tag display limit and overflow counter (+N).
- Verified `AdminService.get_type_specific_content` uses `prefetch_related('tags')` to ensure zero N+1 queries.

### 28. Fix status uploading/processing for logs for any media
- **Description:** Ensure that the status for uploading and processing logs for any media is marked as completed once upload to R2 is finished and media processing is done. Separate the status into "File Processing" and "SEO Generation".
- **Status:** ✅ Fixed

### 29. Sequential Post Upload Actions
- **Description:** Refactor post-upload actions to run sequentially: save to disk → process file (convert to HLS or extract text) → upload to R2 and process with Gemini in parallel. After R2 upload, initialize deletion for the local file, but only delete if SEO is generated.
- **Status:** ✅ Fixed

### 30. Celery background jobs: queue per item type
- **Description:** Configure Celery background jobs to have a separate queue per item type, ensuring that only one worker processes a given type at a time.
- **Status:** ✅ Fixed

### 31. Clean data inside footer
- **Description:** Audit and clean up the data/links displayed in the website footer for accuracy and consistency.
- **Status:** ✅ Fixed
- **Implementation Details:**
    - Updated footer description to reflect the library's connection to H.G. Bishop Abram and the Fayoum Diocese.
    - Commented out the "Follow Us" and "Download App" sections in the footer.
    - Updated header/title text in `navbar.html` and `home.html` to sync name format ("رئيس اديرتها" instead of specific monastery).
    - Preserved mobile responsiveness and multi-lingual support.

### 32. Avoid redundant SEO optimization
- **Description:** Prevent sending items for Gemini SEO optimization if they already have generated SEO metadata.
- **Status:** ✅ Fixed

### 33. Add deletion button for local disk only
**Description:**
Add a button to allow deletion of a file from the local disk while preserving the item on R2.

**Detailed Plan:**
- Add "Delete Local" action in `video_table.html`, `audio_table.html`, and `pdf_table.html`.
- Create a service method `DeleteService.delete_local_file_only(item_id)`.
- Use HTMX to trigger deletion and update the UI with a "Cloud Only" badge.
- Validate R2 exists before Allowing disk deletion.

**Acceptance Criteria:**
- [x] Admins can clear local disk space safely via UI.
- [x] Button is only visible/active if R2 link exists and is valid.
- **Status:** ✅ Fixed

**Implementation Details:**
- Enhanced `MediaProcessingService` in `delete_service.py` with `delete_local_file_only` method.
- Added URL and view for local deletion confirmation.
- Updated admin tables and player components to check for R2 availability.
- Added SEO disclaimer in confirmation page.

---

## Modern Admin UI Implementation Plan (✅ Completed)

This section outlines the technical strategy for refactoring the Admin UI, focusing on modern aesthetics, responsiveness, and improved UX as per the shared specifications.

### 1. Core Architecture & Design System (✅ Implemented)
- **Design Paradigm:** Modern, clean, and high-whitespace interface utilizing a "Soft UI" aesthetic.
- **Color Palette:** Professional muted-teal primary (#005f5f) with secondary neutral greys (#f8f9fa for backgrounds).
- **Typography:** Clean sans-serif (Inter or Roboto) with distinct font-weight hierarchy for scannability.
- **Responsive Framework:** Built on Bootstrap 5 utilizing a mobile-first grid system.
- **Interactive Layers:** Uses HTMX for partial DOM swaps and Alpine.js for client-side state management (e.g., toggles, modals).

### 2. Responsive App Shell (✅ Implemented)
- **Sidebar (Desktop):** Fixed 260px navigation drawer with active-state highlighting and category grouping.
- **Sidebar (Mobile):** Transitions to a hidden off-canvas drawer triggered by a hamburger menu in the header.
- **Header:** Sticky top-bar containing global search, notification system, and user profile.
- **Mobile Adaption:** Search bar should collapse into an icon on extra-small viewports to save horizontal space.

### 3. Dashboard View (Modular Widgets) (✅ Implemented)
- **Metric Grid:** Responsive 4-column grid that stacks to 2-columns on tablets and 1-column on mobile.
- **Data Visualization:** Integration of sparkline area charts for real-time monitoring of CPU, Memory, and Celery task queues.
- **Responsive Tables:** Implementation of table-responsive overflow wrappers to allow horizontal scrolling on small screens without breaking layout.
- **Pill Badges:** High-contrast status indicators (e.g., "Processed", "Active", "Error") for immediate visual feedback.

### 4. Media Management & Upload UI (✅ Implemented)
- **Two-Column Layout:** Desktop view splits into 2/3 (Form) and 1/3 (File Status/SEO).
- **Mobile Stacking:** Stacks vertically on mobile; file dropzone moves above the text forms for better mobile UX flow.
- **Dropzone Component:** Large dashed-border container supporting drag-and-drop for PDF, MP4, and MP3 files.
- **Multi-lingual Input:** Side-by-side or stacked form groups for English and Arabic metadata entry.
- **Progressive Disclosure:** Advanced SEO metadata fields are hidden behind an Alpine.js-controlled accordion to reduce cognitive load.
- **AI Integration:** Dedicated "Generate with AI" button that triggers an HTMX request to the Gemini API endpoint for automated metadata population.

### 5. Mobile UX Optimizations (✅ Implemented)
- **Touch Targets:** All interactive elements (buttons, links, toggles) must have a minimum height of 44px for finger-friendly interaction.
- **Form Controls:** Implementation of floating labels to maximize vertical screen real estate on mobile devices.
- **Dynamic States:** HTMX indicators (loading spinners) provide immediate visual feedback during heavy background processing tasks.
- **Media Players:** Custom responsive components for PDF, Audio, and Video players that adapt to portrait/landscape viewport changes.

### 6. Specific Feature Implementation Detail (✅ Implemented)
- **Remove Sacred Processing Queue:** Audit and remove all queue status widgets, progress bars, and control buttons from UI templates. Retain only background logs for audit.
- **Hide Bulk Operations:** Remove or hide bulk operation buttons ("Delete All", "Bulk Edit") from dashboards and media tables. Update interaction logic to single-item actions.
- **Display Extracted PDF Text:** Implement an Alpine.js-controlled expandable/collapsible area below the PDF content detail form. Fetch and display `book_content` in a scrollable, monospace-styled container.
- **Expandable Task Logs:** Logs in System Monitor are now expandable under row record. (✅ Added)
- **Admin Visibility Parity:** Management tables now show identical columns: Tags, Visibility (Toggle), and Processing Status. (✅ Added)

---

## Pending Issues


### 1. Searching Content Inside Website (Items & Tags)

**Status:** ✅ Fixed

**Detailed Plan:**
**Description:**
Implement advanced, multilingual full-text search for all content and tags within the website. Users should be able to efficiently find items by any relevant text field: title, description, transcript, book_content, notes, and associated tags. The search must support both Arabic and English, be fast, and provide relevant, ranked results.

**Detailed Plan:**
- Use PostgreSQL Full-Text Search (FTS) with GIN indexes for all major text fields: `title`, `description`, `transcript`, `book_content`, `notes`, and tag names.
- Update the `ContentItem` model to include a combined `search_vector` field that indexes all relevant text fields (including related tag names).
- Ensure FTS configuration supports both Arabic and English (use language-specific configs and ranking).
- Update or create search endpoints in the API to accept queries and return ranked, paginated results.
- UI: Update the search interface to allow searching by keyword, filtering by tag, and displaying highlighted matches.
- Add support for searching tags directly and filtering content by selected tags.
- Optimize queries to avoid N+1 problems and ensure sub-second response times even with large datasets.
- Add tests for:
    - Search accuracy and ranking (Arabic/English, partial matches, stemming).
    - Tag search and filtering.
    - Performance under load.
- Document search syntax, supported fields, and usage for both users and developers.

**Acceptance Criteria:**
- [x] Users can search by any text field (title, description, transcript, book_content, notes, tags).
- [x] Search works for both Arabic and English content.
- [x] Results are ranked by relevance and returned quickly (<1s for typical queries).
- [x] UI supports tag-based filtering and displays highlighted matches.
- [x] Automated tests cover accuracy, ranking, and performance.

**Output:**
- Unified, fast, and accurate search experience for all content and tags.
- API endpoints and UI updated to support advanced search and filtering.
- Developer documentation for search integration and extension.

### 2. SEO for Home & Static Pages
**Description:**
Implement robust SEO metadata and structured data (JSON-LD) for the home page and all static pages. This includes generating and managing meta tags, Open Graph/Twitter tags, and schema.org JSON-LD for static content, as well as a reusable SEO block about the website to append to all generated SEO. All changes must follow Google Search Quality and best practices (see ADVANCED_SEO_SITEMAP_IMPLEMENTATION.md, SEO_IMPLEMENTATION_SUMMARY.md, SEO_SETUP.md, SEO_TEMPLATE_INTEGRATION.md).

**Detailed Plan:**
- Add or update dedicated SEO endpoints and workflows for home and static pages (e.g., `/`, `/about/`, `/contact/`).
- Create a general website SEO block (description, keywords, organization, etc.) for reuse across all static and dynamic pages.
- Ensure all static pages include:
    - Meta tags (title, description, keywords)
    - Open Graph and Twitter Card tags
    - JSON-LD structured data (WebSite, Organization, BreadcrumbList, etc.)
- Use Django template tags and context processors to inject SEO data into all static page templates (see SEO_TEMPLATE_INTEGRATION.md).
- Update the admin UI to allow editing and previewing SEO metadata for static pages.
- Ensure all sitemaps and robots.txt reference static pages correctly (see ADVANCED_SEO_SITEMAP_IMPLEMENTATION.md).
- Add tests to verify:
    - SEO metadata is present and valid on all static pages
    - JSON-LD is valid and not escaped
    - Sitemaps and robots.txt include all static pages
- Document the SEO workflow for static pages and provide examples for developers and content editors.

**Acceptance Criteria:**
- [ ] All static pages have valid, complete SEO metadata and JSON-LD.
- [ ] General website SEO block is appended to all generated SEO.
- [ ] Admin UI allows editing and previewing static page SEO.
- [ ] Sitemaps and robots.txt reference all static pages.
- [ ] Automated tests verify SEO presence and validity.
- **Status:** ⏳ New

### 3. Cloudflare Cache Purge for Web Pages
**Description:**
Integrate Cloudflare API to purge cache for specific web pages from admin dashboard.

**Detailed Plan:**
- Add backend integration with Cloudflare cache purge API.
- Provide admin action/button to purge cache for any URL.
- Log purge events for audit.

**Acceptance Criteria:**
- [ ] Admins can trigger Cloudflare cache purges directly from the dashboard.
- [ ] Purge actions are logged for auditability.
- **Status:** ⏳ New

### 4. Application Test Coverage
**Description:**
Expand test coverage for application logic, views, background tasks, and new features.

**Detailed Plan:**
- Add unit tests for core logic and views.
- Add integration tests for API endpoints and admin actions.
- Ensure coverage for new features (SEO, cache purge, analytics).

**Acceptance Criteria:**
- [ ] Unit tests cover all critical business logic.
- [ ] Integration tests verify end-to-end workflows.
- [ ] Code coverage reports reflect improved testing surface.
- **Status:** ⏳ New

---

## Instructions
- Add new issues as discovered.
- Mark issues as fixed when resolved (✅ Fixed).
- Update planned fixes and status as work progresses.

---

## Phase Planning
- **Phase 1:** Decouple SEO generation from activation (Completed)
- **Phase 2:** Ensure all static/media files (video, audio, PDF) are served from R2 and cached/mapped by nginx (Completed)
- **Phase 3:** Automatic activation of media item access after R2 upload (Completed)
- **Phase 4:** Remove Nginx config from app, remove secure media routes, use direct URLs (In Progress)
- Additional phases will be added as new issues are discovered.

---
