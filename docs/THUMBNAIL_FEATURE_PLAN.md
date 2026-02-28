# Content Item Thumbnail Generation & Management Plan

## Feature Overview

This feature will ensure that every content item (PDF, video, audio, etc.) in the Christian Library system has an associated thumbnail image. The thumbnail can be uploaded manually or generated automatically if missing. For PDFs, the thumbnail will be an image of the first page; for videos, it will be generated using FFMPEG. Thumbnails will be uploaded to the same R2 storage location as the content item and deleted from local storage after upload. The feature will also consider SEO requirements, ensuring thumbnails are available for schema generation and search engine optimization.

## Current Situation

- Content items (PDF, video, audio) do not have a guaranteed thumbnail.
- Manual upload of thumbnails is possible but not enforced or automated.
- No automatic thumbnail generation for PDFs or videos.
- Thumbnails are not consistently uploaded to R2 or deleted from local storage.
- SEO schema generation does not always include thumbnails.

## Goal

- Ensure every content item has a thumbnail, either uploaded or auto-generated.
- Automate thumbnail generation for PDFs (first page image) and videos (FFMPEG snapshot).
- Upload thumbnails to R2 storage alongside the content item and remove from local storage.
- Integrate thumbnail management with content item save signals and background tasks.
- Enhance SEO schema generation to include thumbnails.

---

## Implementation Phases & Tasks

## Implementation Phases & Detailed Tasks

### Phase 1: Model & Storage Changes
- [ ] Add `thumbnail` field to ContentItem model
	- File: backend/apps/media_manager/models.py
	- Update model, migrations, admin registration
- [ ] Update R2 upload logic to handle thumbnail images
	- File: core/storage_backends/R2Service.py (and related upload logic)
	- File: backend/apps/media_manager/services/upload_service.py
- [ ] Ensure thumbnail deletion from local storage after upload
	- File: backend/apps/media_manager/services/upload_service.py
	- File: core/tasks/media_processing.py

### Phase 2: Thumbnail Generation Logic
- [ ] Implement PDF thumbnail generation (first page image)
	- File: backend/apps/media_manager/services/pdf_processor_service.py
- [ ] Implement video thumbnail generation (FFMPEG snapshot)
	- File: backend/apps/media_manager/services/video_processor_service.py (new or existing)
- [ ] Integrate generation logic with content item save/task
	- File: backend/apps/media_manager/tasks.py
	- File: backend/apps/media_manager/models.py (signals)

### Phase 3: Upload & Cleanup
- [ ] Upload generated thumbnails to R2
	- File: backend/apps/media_manager/services/upload_service.py
	- File: core/tasks/media_processing.py
- [ ] Remove local thumbnail files after upload
	- File: backend/apps/media_manager/services/upload_service.py
- [ ] Update admin and API upload flows to support thumbnail
	- File: backend/apps/frontend_api/admin_views.py
	- File: backend/apps/frontend_api/views.py
	- File: backend/apps/media_manager/services/api_upload_queue_service.py
	- File: backend/apps/media_manager/services/content_service.py
	- Templates: backend/apps/frontend_api/templates/
		- Update item modification/upload forms to allow thumbnail upload

### Phase 4: SEO & Schema Integration
- [ ] Update schema generators to include thumbnail in JSON-LD
	- File: backend/apps/frontend_api/schema_generators.py
- [ ] Ensure SEO metadata references thumbnail
	- File: backend/apps/frontend_api/google_seo_service.py

### Phase 5: Testing & Validation
- [ ] Unit and integration tests for thumbnail generation
	- File: backend/apps/media_manager/tests.py
- [ ] End-to-end tests for upload, cleanup, and SEO
	- File: backend/apps/media_manager/tests.py
	- File: backend/apps/frontend_api/tests.py

---

## Notes
- Tasks are now broken down with file paths and places to update.
- Backend and templates for item modification/upload are included.
- Further refinement will specify function/class names and code regions.
