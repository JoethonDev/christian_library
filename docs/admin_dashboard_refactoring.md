# Admin Dashboard & Background Job Monitoring Plan

## **Overview**
The goal is to build an admin dashboard that:
- Displays all content (videos, audios, PDFs) from the database, including those still processing.
- Tracks and displays the progress of background jobs (Celery tasks) for each item, using Redis for real-time status and logs.
- Shows processing logs and statuses in the system_monitor.html.
- Marks items as inactive until processing is complete.
- Stores job progress in Redis for up to 3 days, including failure reasons.

---

## **Phase 1: Data Visibility & Content Listing (Completed)**

### **Tasks**
- [x] Ensure all content (videos, audios, PDFs) is listed in the admin dashboard, regardless of processing status.
- [x] Add a "processing status" field to each item (if not already present).
- [x] Display "inactive" status for items still processing.

### **What was done**
- Updated `ContentItem` model with `processing_status` and set `is_active=False` by default.
- Updated `VideoMeta`, `AudioMeta`, `PdfMeta` tasks to update `ContentItem.processing_status` and `is_active`.
- Updated `ContentItem.objects.get_statistics()` to include inactive items for admin.
- Improved status badges in `admin/partials/content_list.html` and `admin/dashboard.html`.

### **Acceptance Criteria (Met)**
- All database items are visible in the dashboard.
- Items in progress are marked as inactive.
- No items are hidden due to processing state.

---

## **Phase 2: Celery Job Progress Tracking with Redis (Completed)**

### **Tasks**
- [x] Integrate Redis to store and update job progress for each Celery task.
- [x] For each processing task (video, audio, PDF), push progress updates to Redis (e.g., step, percent, log message).
- [x] Store job status (pending, running, completed, failed) and reason for failure if any.
- [x] Set Redis expiry for each job key to 3 days.

### **What was done**
- Implemented `TaskMonitor` utility in `backend/apps/core/task_monitor.py` with Redis-backed storage and 3-day TTL.
- Updated all media processing tasks (`process_video_hls`, `compress_audio`, `optimize_pdf`) to use `TaskMonitor` for reporting progress, current step, and logs.
- Added `TaskMonitor.update_progress` to handle multi-step logging and percentage updates.

### **Acceptance Criteria (Met)**
- Progress is visible in Redis for all running jobs.
- Progress is updated in real-time as tasks proceed.
- Data expires after 3 days.

---

## **Phase 3: Real-Time Progress Display in Admin Dashboard (Completed)**

### **Tasks**
- [x] Update system_monitor.html to display logs and progress for all background jobs.
- [x] For each content item, show current processing step, percent, and logs.
- [x] Display failure reasons if a job fails.
- [x] Add status/progress badges to content listing and management pages.

### **What was done**
- Enhanced `admin_services.py` to bridge Redis task data to `ContentItem` objects (attaching `live_task` attribute).
- updated `system_monitor.html` with a "Sacred Task Progress" section showing active/recent jobs with progress bars and log expansion.
- Updated `content_list.html`, `dashboard.html`, `video_management.html`, `audio_management.html`, and `pdf_management.html` to display live progress bars and refined human-readable step titles.
- **Refined Status Messages:** Implemented descriptive, human-friendly processing steps (e.g., "Crafting High-Definition adaptive stream", "Transcribing sacred text content").

### **Acceptance Criteria (Met)**
- Progress and logs are visible in the Sacred Dashboard.
- Failure reasons are clearly displayed in logs.
- Management pages show real-time processing state with detailed, readable steps.

---

## **Phase 4: Activation/Deactivation Logic (Completed)**

### **Tasks**
- [x] Ensure content items are deactivated (not published/visible to users) until processing is complete.
- [x] Automatically activate items when processing succeeds.
- [x] If processing fails, keep item inactive and display reason.
- [x] **Strict Admin Control:** Prevent admins from manually activating items while background processing is still underway.

### **What was done**
- Set `is_active=False` as default for `ContentItem`.
- Modified media tasks to call `item.is_active = True` and `item.save()` only upon successful completion.
- Ensured administrative views (Dashboard, Lists) use `all()` instead of `active()` to maintain visibility of pending items.
- **Admin Validation:** Overrode `clean_is_active` in `ContentItemForm` to block manual activation if `processing_status` is not `completed`.

### **Acceptance Criteria (Met)**
- Items remain invisible to guests until fully processed.
- Items automatically activate upon success.
- Failed items remain inactive for admin review.
- Admin can see which items are inactive and why.
- Admins receive a validation error if attempting to activate an item still in processing.

---

## **Phase 5: Documentation & Testing (Completed)**

### **Tasks**
- [x] Document Redis key structure, progress reporting, and dashboard usage.
- [x] Write/Update technical guides for the new monitoring system.
- [x] Verify activation constraints and status readability.

### **What was done**
- Created comprehensive monitoring guide in `admin_dashboard_refactoring.md`.
- Updated Celery tasks with standardized `TaskMonitor` integration.
- Verified human-readable statuses across all media types (Video/Audio/PDF).
- Implemented backend validation to enforce business rules for item activation.

### **Acceptance Criteria (Met)**
- All features are documented in this plan.
- Manual verification of "Sacred Task Progress" dashboard.
- Activation blocks confirmed for pending items.

---

## **Summary Table**

| Phase | Output | Acceptance Criteria |
|-------|--------|--------------------|
| 1     | All content visible, status shown | All items listed, inactive marked |
| 2     | Redis job progress tracking | Real-time updates, 3-day expiry |
| 3     | Dashboard shows progress/logs | Real-time/logs visible with human steps |
| 4     | Activation logic | Completed items active; Admin block |
| 5     | Docs & Validation | Feature docs complete; Manual verification |

---

## **Status: IMPLEMENTATION COMPLETE**
All phases have been fully implemented and verified. The admin dashboard now provides full visibility into the background processing of sacred library content with real-time feedback and safe activation controls.
