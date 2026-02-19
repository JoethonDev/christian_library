# Cloudflare R2 Migration & Monitoring Plan (as of 2026-01-31)

## Executive Summary
This document details the phased migration of Django media storage from local server to Cloudflare R2 using boto3, with full backward compatibility, status/progress tracking, and robust monitoring. All findings, decisions, and implementation steps are included for review and confirmation.

---

## 1. Research & Context Gathering
- **Technologies:** Django, Celery, PostgreSQL, boto3, Cloudflare R2 (S3-compatible), HTML5, Bootstrap, HTMX.
- **Patterns:** Service layer for uploads, background processing, model-driven status, admin/API views, custom templates.
- **Key Requirements:**
  - All processing on server before upload to R2.
  - Backward compatibility: local storage fallback.
  - Status/progress fields (human-readable).
  - Monitoring (frontend/backend).
  - Phased, non-breaking migration.

---

## 2. Phased Migration Plan

### **Phase 1: Foundation & Settings**
- [x] Research best practices for Django + boto3 + R2 integration.
- [x] Add `boto3` and `django-storages` to requirements and install.
- [x] Add R2 config to Django settings (env-based, backward compatible).
- [x] Create custom storage backend for R2/local fallback.
- [x] Add R2 path/status/progress fields to all media meta models.

### **Phase 2: Core Integration**
- [x] Implement R2-aware upload logic in service layer (PDF, video, audio flows).
- [x] Update upload/processing services to use R2 backend if enabled.
- [x] Ensure all file handling (save, url, exists, delete) is R2/local aware.
- [x] Add status/progress updates during upload (model fields, Celery events).
- [x] Maintain local fallback for all flows.

### **Phase 3: Monitoring & Status**
- [x] Expose status/progress fields in admin and API views.
- [x] Update monitoring dashboard (system_monitor.html) to show R2 status/progress.
- [x] Add backend monitoring endpoints for R2 upload/processing status.
- [x] Add error logging and alerting for R2 failures.

### **Phase 4: Concurrency & Robustness ✅**
- [x] Fix method signature issues in MediaUploadService (use self instead of creating instances).
- [x] Implement Celery tasks for R2 uploads with proper error handling.
- [x] Add retry logic and error handling for R2 operations.
- [x] Update MediaUploadService to use Celery task scheduling for R2 uploads.
- [x] Implement specific upload methods for each media type (video, audio, PDF).
- [x] Add concurrency safety with atomic database operations.
- [x] Create comprehensive test script for validation.

### **Phase 5: Testing & Validation**
- [ ] Test all flows (local and R2) for all media types.
- [ ] Validate backward compatibility (local fallback works if R2 disabled).
- [ ] Test admin and frontend monitoring for all status/progress scenarios.
- [ ] Final code review and production readiness check.

---

## 3. Implementation Details (Completed)
### **Phase 1: Foundation & Settings ✅**
- **Settings:**
  - R2 config (env-based, backward compatible) added to `base.py`.
  - `DEFAULT_FILE_STORAGE` set to custom backend if R2 enabled.
- **Requirements:**
  - `boto3` and `django-storages` added to requirements and installed.
- **Storage Backend:**
  - `core/storage_backends.py` created for R2/local fallback logic.
  - Robust error handling and progress tracking implemented.
- **Models:**
  - `VideoMeta`, `AudioMeta`, `PdfMeta` updated with R2 path/status/progress fields.
  - Migration created for new fields.

### **Phase 2: Core Integration ✅**
- **Upload Service:**
  - `MediaUploadService` updated with R2Service integration.
  - All upload methods (video, audio, PDF) now include R2 upload queueing.
  - Status tracking and progress updates implemented.
  - Local fallback maintained for all flows.
- **Model Methods:**
  - Added R2 helper methods to all meta models.
  - Status display and best URL selection implemented.
  - File handling covers both local and R2 files.

### **Phase 3: Monitoring & Status ✅**
- **Admin Interface:**
  - All meta model admin inlines updated to show R2 status/progress.
  - Real-time status display with human-readable messages.
- **System Monitor:**
  - `system_monitor.html` updated with comprehensive R2 dashboard.
  - Backend view provides R2 statistics across all content types.
  - Visual status indicators for uploads (pending, uploading, completed, failed).
- **Error Handling:**
  - Comprehensive logging throughout R2 service.
  - Graceful fallback to local storage on R2 failures.
  - Status tracking for failed uploads.

---

## 4. Next Steps (Implementation Complete - Testing Phase)

**Phase 4: Concurrency & Robustness** - Ready for implementation
- [ ] Ensure concurrency safety for parallel uploads/processing.
- [ ] Add retry logic and error handling for R2 operations.
- [ ] Test edge cases: large files, network failures, partial uploads.
- [ ] Validate all monitoring and status reporting.

**Phase 5: Testing & Validation** - Ready for execution
- [ ] Test all flows (local and R2) for all media types.
- [ ] Validate backward compatibility (local fallback works if R2 disabled).
- [ ] Test admin and frontend monitoring for all status/progress scenarios.
- [ ] Final code review and production readiness check.

---

## 5. Todo List (Current State)
- [x] Research relevant libraries/frameworks on Context7
- [x] Fetch provided URLs and gather information
- [x] Search codebase to understand current structure
- [x] Research additional information on internet (if needed)
- [x] Analyze existing integration points
- [x] Implement core functionality incrementally
- [x] Add comprehensive error handling
- [ ] Test implementation thoroughly with edge cases
- [ ] Debug and fix any issues found
- [ ] Validate solution against original requirements
- [ ] Check for problems and ensure robustness

---

## 6. Testing Instructions

To test the R2 integration:

1. **Environment Setup:**
   ```bash
   export R2_ENABLED=true
   export R2_BUCKET_NAME=your-bucket-name
   export R2_ACCESS_KEY_ID=your-access-key
   export R2_SECRET_ACCESS_KEY=your-secret-key
   export R2_ENDPOINT_URL=https://your-account-id.r2.cloudflarestorage.com
   ```

2. **Database Migration:**
   ```bash
   python manage.py migrate
   ```

3. **Test Upload Process:**
   - Upload video/audio/PDF through admin interface
   - Check admin interface for R2 status display
   - Monitor system dashboard for R2 statistics
   - Verify fallback to local storage if R2 disabled

4. **Monitoring Verification:**
   - Visit `/admin/system-monitor/` to see R2 dashboard
   - Check individual content items in admin for R2 status
   - Verify progress tracking during uploads

---

**Core Implementation Complete ✅** - Ready for testing and final validation.

---

## Testing Instructions and Validation

### Phase 4 & 5 Validation Steps

#### 1. Environment Setup
```bash
# Set R2 credentials (if testing with real R2)
export R2_ENABLED=true
export R2_BUCKET_NAME=your-bucket-name
export R2_ACCESS_KEY_ID=your-access-key
export R2_SECRET_ACCESS_KEY=your-secret-key
export R2_ENDPOINT_URL=https://your-account-id.r2.cloudflarestorage.com

# Apply migrations
python manage.py migrate
```

#### 2. Local Testing (R2 Disabled)
```bash
# Disable R2 for local-only testing
export R2_ENABLED=false

# Test uploads work normally without R2
# All content should save locally with r2_upload_status = ''
```

#### 3. R2 Integration Testing
```bash
# Enable R2 for integration testing  
export R2_ENABLED=true

# Test sequence:
# 1. Upload video -> should queue process_video_to_hls + upload_video_to_r2 
# 2. Upload audio -> should queue process_audio_compression + upload_audio_to_r2
# 3. Upload PDF -> should queue process_pdf_optimization + upload_pdf_to_r2
```

#### 4. Monitoring Dashboard Validation
- Visit `/admin/system-monitor/` for R2 statistics dashboard
- Check individual content items show R2 status and links
- Verify progress indicators work during uploads

#### 5. Celery Task Testing
```bash
# Monitor Celery tasks
celery -A config worker --loglevel=info

# Check task execution:
# - R2 upload tasks should execute after processing completes
# - Retry logic should handle temporary failures
# - Status updates should be atomic and consistent
```

#### 6. Concurrency Testing  
```bash
# Test parallel uploads
# Upload multiple files simultaneously
# Verify no race conditions in status updates
# Check all files process correctly in parallel
```

#### 7. Error Handling Validation
- Test network interruptions during upload
- Verify failed uploads marked as 'failed' status
- Test retry logic with temporary R2 unavailability
- Confirm graceful fallback to local storage

---
