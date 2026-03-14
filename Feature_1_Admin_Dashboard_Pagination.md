# Feature 1: Admin Dashboard Pagination Enhancement

## Overview
Implement robust, user-friendly pagination for all admin dashboard pages that list content, ensuring seamless navigation, AJAX-based updates (Alpine.js + HTMX), and URL synchronization for refresh/reload consistency.

---

## Phases

### Phase 1: Audit & Planning
**Output:**
- List of all admin dashboard templates that display paginated data.
- Identify which templates lack pagination or have non-AJAX pagination.
- Map backend views that require pagination logic or API endpoints.

**Acceptance Criteria:**
- Markdown table listing each template, current pagination status, and required changes.
- Clear mapping of backend endpoints to templates.

---

### Phase 2: Backend Pagination API Design
**Output:**
- Plan for updating backend views to support paginated responses (JSON/HTML partials).
- Define query parameters for page, filters, and search.
- Specify response structure for AJAX requests.

**Acceptance Criteria:**
- List of endpoints to update or add.
- Sample response structure for paginated data.
- Plan for handling errors and empty states.

---

### Phase 3: Frontend AJAX Pagination Integration
**Output:**
- Plan for integrating Alpine.js and HTMX for AJAX pagination.
- Strategy for updating URL (pushState/replaceState) on page change.
- Fallback for non-JS users (full reload links).

**Acceptance Criteria:**
- UI/UX flow diagrams or descriptions for pagination interaction.
- List of templates/components to update with AJAX logic.
- URL update approach documented.

---

### Phase 4: Testing & Acceptance
**Output:**
- Test plan for pagination (manual and automated).
- Acceptance criteria for UX, performance, and reliability.

**Acceptance Criteria:**
- All paginated lists update via AJAX without full reload.
- URL reflects current page and is reload-safe.
- Pagination works with filters/search.
- No regressions in existing admin features.

---

## Phase 1: Audit Table

| Template                        | Current Pagination | Needs Pagination? | Backend View                  | Notes |
|----------------------------------|--------------------|-------------------|-------------------------------|-------|
| admin/dashboard.html             | No                 | Yes               | admin_dashboard               | Recent content list |
| admin/content_list.html          | Partial/Yes        | AJAX/URL sync     | content_list                  | Main content list |
| admin/content_detail.html        | No                 | No                | content_detail                | Detail page, not list |
| admin/video_management.html      | Partial/Yes        | AJAX/URL sync     | video_management              | Video list |
| admin/audio_management.html      | Partial/Yes        | AJAX/URL sync     | audio_management              | Audio list |
| admin/pdf_management.html        | Partial/Yes        | AJAX/URL sync     | pdf_management                | PDF list |
| admin/bulk_operations.html       | No                 | Maybe             | bulk_operations               | If list present |
| admin/api_queue_list.html        | Partial/Yes        | AJAX/URL sync     | api_queue_list                | API queue list |
| admin/seo_dashboard.html         | No                 | Maybe             | seo_dashboard (class-based)   | If list present |
| admin/analytics_dashboard.html   | No                 | Maybe             | analytics_dashboard           | If list present |
| admin/r2_status_dashboard.html   | No                 | Maybe             | r2_status_dashboard           | If list present |
| admin/partials/content_list.html | Partial            | AJAX/URL sync     | Used in content lists         | Partial template |
| admin/partials/video_table.html  | Partial            | AJAX/URL sync     | Used in video lists           | Partial template |
| admin/partials/audio_table.html  | Partial            | AJAX/URL sync     | Used in audio lists           | Partial template |
| admin/partials/pdf_table.html    | Partial            | AJAX/URL sync     | Used in PDF lists             | Partial template |

---

## Tasks and Sub-tasks per Phase

### Phase 1: Audit & Planning
**Tasks:**
1. Audit all admin dashboard templates for paginated lists
    - Sub-task: List all templates that display lists of content
    - Sub-task: Identify which templates currently lack pagination or use non-AJAX pagination
    - Sub-task: Map each template to its backend view
2. Document findings in the audit table
    - Sub-task: Update audit table with current status and required changes
    - Sub-task: Add notes for any special cases (e.g., partials, conditional lists)
3. Define rules for maintaining the audit
    - Sub-task: Require audit table update for any new admin list page
    - Sub-task: Require audit table update for any pagination logic change

### Phase 2: Backend Pagination API Design
**Tasks:**
1. Design backend API/endpoint changes for pagination
    - Sub-task: Specify query parameters (page, filters, search)
    - Sub-task: Define response structure for AJAX (HTML partials/JSON)
    - Sub-task: Plan for error and empty state handling
2. List all endpoints/views to update or add
    - Sub-task: Map each paginated template to its backend endpoint
    - Sub-task: Note if new endpoints are needed for AJAX partials
3. Define rules for backend pagination
    - Sub-task: All paginated endpoints must accept `page` as a query param
    - Sub-task: All paginated endpoints must support AJAX (HTMX) requests
    - Sub-task: All paginated endpoints must return consistent pagination metadata

### Phase 3: Frontend AJAX Pagination Integration
**Tasks:**
1. Plan Alpine.js/HTMX integration for pagination
    - Sub-task: Identify all templates/components needing AJAX pagination
    - Sub-task: Specify how to trigger AJAX requests for page changes
    - Sub-task: Plan for updating only the relevant DOM region
2. Plan URL synchronization
    - Sub-task: Use pushState/replaceState to update URL on page change
    - Sub-task: Ensure URL reflects current filters/search/page
    - Sub-task: On reload, page state is restored from URL
3. Plan fallback for non-JS users
    - Sub-task: Ensure pagination links work as normal links if JS is disabled
4. Define rules for frontend pagination
    - Sub-task: All paginated lists must update via AJAX without full reload
    - Sub-task: URL must always reflect current page/filters
    - Sub-task: Pagination must degrade gracefully if JS is disabled

### Phase 4: Testing & Acceptance
**Tasks:**
1. Develop test plan for pagination
    - Sub-task: Manual test cases for all paginated lists
    - Sub-task: Automated tests for backend pagination logic
    - Sub-task: Automated UI tests for AJAX pagination (if possible)
2. Define acceptance criteria for UX/performance
    - Sub-task: Pagination is smooth and fast (no full reloads)
    - Sub-task: URL is always in sync with current page
    - Sub-task: Pagination works with filters/search
    - Sub-task: No regressions in admin dashboard features
3. Define rules for ongoing maintenance
    - Sub-task: All new admin lists must follow AJAX pagination pattern
    - Sub-task: All pagination bugs must be tracked and regression tested

---

## Rules for Use and Maintenance
- Any new admin dashboard list page must be added to the audit table and follow the pagination pattern.
- All paginated endpoints must support both AJAX and full reload navigation.
- URL state must always reflect the current page and filters for reload safety.
- All pagination logic changes must be reflected in this plan and the audit table.
- Testing and acceptance criteria must be updated if pagination requirements change.

---

# Feature 2: Infinite Scrolling for Content Listings & Search

## Overview
Implement infinite scrolling ("load more"/auto-fetch) for frontend content listings (audios, videos, pdfs) and search results. Fetch additional items via AJAX requests with a limit, updating the UI without full reload. Ensure correct ordering: by search ranking (if applicable), then by `created_at` (recent to oldest). For search, maintain query and ranking in URL and results.

---

## Phases

### Phase 1: Requirements & Audit
**Output:**
- List of all templates and views requiring infinite scroll.
- Identify current pagination/scrolling logic.
- Map AJAX endpoints and required data structure.

**Acceptance Criteria:**
- Table mapping each template to its infinite scroll requirements.
- Clear backend/frontend responsibilities defined.

---

### Phase 2: Backend API for Infinite Scroll
**Output:**
- Plan for backend endpoints to support limit/offset (or page) AJAX requests.
- Define query params: `limit`, `offset`/`page`, `search`, `ordering`.
- Specify response structure (HTML partials/JSON with items, has_more, etc).
- For search: ensure ordering by ranking, then date; for content: date, then ranking if search.

**Acceptance Criteria:**
- List of endpoints to update/add.
- Sample response payloads.
- Error/empty state handling plan.

---

### Phase 3: Frontend Integration (Alpine.js + HTMX)
**Output:**
- Plan for integrating infinite scroll (auto or button-triggered) in audios.html, videos.html, pdfs.html, and search.html.
- Strategy for updating URL with current query/offset for reload safety.
- Fallback for non-JS users (pagination links).

**Acceptance Criteria:**
- UI/UX flow for infinite scroll interaction.
- List of templates/components to update.
- URL update approach documented.

---

### Phase 4: Testing & Acceptance
**Output:**
- Test plan for infinite scroll (manual/automated).
- Acceptance criteria for UX, performance, and reliability.

**Acceptance Criteria:**
- Additional items load via AJAX as user scrolls or clicks "load more".
- No full page reloads for infinite scroll.
- URL reflects current search/query/offset for reload safety.
- Ordering is correct (ranking, then date for search; date, then ranking for content).
- No regressions in content or search features.

---

## Phase 1: Audit Table (Infinite Scroll)

| Template                  | Needs Infinite Scroll? | Backend View         | Notes |
|---------------------------|-----------------------|----------------------|-------|
| frontend_api/audios.html  | Yes                   | AudioListView        | By date, then ranking if search |
| frontend_api/videos.html  | Yes                   | VideoListView        | By date, then ranking if search |
| frontend_api/pdfs.html    | Yes                   | PdfListView          | By date, then ranking if search |
| frontend_api/search.html  | Yes                   | search (FBV)         | By ranking, then date; maintain query in URL |

---

## Rules for Use and Maintenance (Feature 2)
- All infinite scroll endpoints must support `limit` and `offset` (or `page`) params.
- For search, always order by ranking (similarity), then by `created_at`.
- For content listings, order by `created_at` (recent first), then ranking if search is present.
- AJAX responses must include enough metadata for frontend to update UI and URL.
- URL must always reflect current query/offset for reload safety.
- All new content/search listings must follow infinite scroll pattern if applicable.

---

# [MODIFICATION] Ordering Rule Update
- All infinite scroll and paginated endpoints must order results by **ranking (if available), then by `created_at` (recent to oldest)** for both content listings and search pages.
- This applies to: audios, videos, pdfs, and search results.

---
