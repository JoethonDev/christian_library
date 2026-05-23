# Refactor Execution Plan 23-05-2026

## Scope
This document converts the refactor blueprint into an execution runbook.

Each phase includes:
1. Exact code areas affected
2. Detailed implementation tasks
3. Failure modes and mitigation
4. Validation gates and pass criteria
5. Rollback trigger and fallback actions

## Immediate Bug Fix: Custom Admin Login Page Not Found
Status: Completed on 2026-05-23

### Root Cause
Dashboard and SEO endpoints used staff guards that redirected to Django admin login instead of the custom dashboard login route.

### Implemented Fix
1. Added custom admin login route at dashboard/login/ using users login view.
2. Rebound staff decorators in dashboard and SEO views to frontend_api:admin_login.
3. Redirected accounts/login to frontend_api:admin_login by route name.

### Files Updated
1. backend/apps/frontend_api/admin_views.py
2. backend/apps/frontend_api/seo_views.py
3. backend/apps/frontend_api/urls.py
4. backend/config/urls.py

### Verification
1. /en/dashboard/ redirects anonymous users to /en/dashboard/login/?next=...
2. /en/dashboard/seo/ redirects anonymous users to /en/dashboard/login/?next=...
3. /accounts/login/ redirects to localized dashboard login
4. Login form renders templates/registration/login.html

## Global Non-Break Rules (Hard Constraints)
1. Keep these routes and behavior unchanged:
   1. dashboard/upload/bulk/
   2. dashboard/upload/bulk/init/
   3. dashboard/upload/bulk/chunk/
   4. dashboard/upload/bulk/status/
   5. dashboard/analytics/ and analytics APIs
   6. dashboard/search-settings/* APIs
2. Keep i18n-prefixed URL behavior under config i18n_patterns.
3. Do not keep backward compatibility routes for deprecated standalone admin pages.
4. Prefer feature-flagged template switches before hard removal.
5. Preserve existing JSON payload keys for admin APIs unless explicitly versioned.
6. Keep staff-only authorization checks in both view guard and action handler.

## Branching and Execution Protocol
1. Create one feature branch per phase.
2. Keep commits small and grouped by concern:
   1. tests first
   2. routes and views
   3. templates
   4. docs
3. Run targeted tests after each commit group and full smoke tests before merge.
4. Do not start the next phase until current exit criteria are fully met.

## Pre-Flight Checklist (Run Before Phase 1)
1. Confirm containers and services are healthy.
2. Confirm database migrations are applied.
3. Confirm baseline tests for upload, analytics, and search settings pass.
4. Capture baseline screenshots for:
   1. dashboard main page
   2. jobs page
   3. content list
   4. SEO page (for deprecation comparison)
5. Capture baseline redirect map for:
   1. /accounts/login/
   2. /en/dashboard/
   3. /en/dashboard/seo/
   4. /en/dashboard/jobs/

## Phase 1: Auth and Route Hardening

### Primary Objective
Finalize login and staff-access behavior so all dashboard entry points are deterministic and language-safe.

### Affected Surfaces
1. backend/apps/frontend_api/urls.py
2. backend/config/urls.py
3. backend/apps/frontend_api/admin_views.py
4. backend/apps/frontend_api/seo_views.py
5. backend/apps/frontend_api/tests_admin.py

### Detailed Implementation Tasks
1. Centralize login target:
   1. define one canonical target name: frontend_api:admin_login
   2. remove any hardcoded /admin/login/ fallback in custom dashboard views
2. Normalize guard usage:
   1. ensure all dashboard staff views use same decorator or permission mixin path
   2. ensure API views return proper unauthorized/forbidden semantics without leaking admin login URL
3. Add regression tests for anonymous and non-staff users on:
   1. dashboard
   2. SEO
   3. jobs
   4. API queue list/detail endpoints
4. Add accounts/login compatibility tests:
   1. redirect status code
   2. location header includes language prefix when applicable
5. Add loop-prevention assertion:
   1. redirected URL must not redirect back to itself

### Test Matrix
1. User types:
   1. anonymous
   2. authenticated non-staff
   3. authenticated staff
2. Languages:
   1. default language route
   2. /en/ prefixed route
3. Assertions:
   1. status code correctness
   2. redirect destination correctness
   3. view accessibility for staff only

### Break Risk
1. Mixed decorator behavior can produce route loops or inconsistent login endpoints.
2. Tests can pass on one language but fail on localized prefixes.
3. API views may unintentionally return HTML redirect for clients expecting JSON.

### Safe Handling
1. Keep login target centralized at frontend_api:admin_login.
2. Test both /accounts/login and /en/dashboard/* flows.
3. Validate response code and Location header for each protected endpoint.
4. Keep one compatibility redirect in config urls for accounts/login.

### Exit Criteria
1. All admin-protected URLs redirect consistently for anonymous users.
2. Non-staff users are blocked from admin endpoints.
3. No protected endpoint redirects to Django admin login.
4. Phase 1 tests pass in full.

### Rollback Trigger and Fallback
1. Trigger: login loop or staff unable to access dashboard.
2. Fallback:
   1. restore previous route mapping for accounts/login
   2. keep only tested guard path on critical dashboard URLs
   3. re-run auth regression suite before reattempt

## Phase 2: Remove Standalone Queue/R2/SEO Pages (Hard Cut)

Status: Completed on 2026-05-23

### Primary Objective
Remove standalone dashboard pages (API queue, R2 status, SEO dashboard) from primary navigation and route table with no compatibility redirects.

### Affected Surfaces
1. backend/apps/frontend_api/urls.py
2. backend/apps/frontend_api/admin_views.py
3. backend/apps/frontend_api/seo_views.py
4. backend/templates/layouts/admin_base.html
5. backend/templates/admin/dashboard.html
6. backend/templates/admin/system_monitor.html
7. backend/templates/admin/partials/r2_storage_info.html
8. backend/templates/admin/api_queue_list.html (deleted)
9. backend/templates/admin/api_queue_detail.html (deleted)
10. backend/templates/admin/r2_status_dashboard.html (deleted)
11. backend/templates/admin/seo_dashboard.html (deleted)
12. backend/templates/admin/partials/api_queue_list.html (deleted)

### Detailed Implementation Tasks
1. Navigation updates:
   1. remove sidebar links to api_queue_list, r2_status_dashboard, seo_dashboard
   2. keep jobs_dashboard link as primary operations hub
   3. add placeholder link for admin logs if route exists, otherwise hide behind feature flag
2. Route and view hard removal:
   1. remove named routes for standalone api-queue list/detail, r2 dashboard, and seo dashboard
   2. remove legacy admin alias routes for deprecated dashboard entry points
   3. remove standalone view implementations no longer reachable from URL config
3. Template cleanup:
   1. remove references from dashboard cards and quick links
   2. delete deprecated standalone templates and partials
4. Documentation:
   1. add removal notes and migration guidance in release notes
   2. list removed URLs and surviving operational destinations

### Break Risk
1. Direct URL hardcoding in templates can break if route names are removed immediately.
2. Existing bookmarks or integrations may depend on old page URLs.
3. Permanent redirects too early can lock browsers to wrong destination.

### Safe Handling
1. Update template URL tags first, remove dead routes second.
2. Restrict media management route matching to explicit media types only.
3. Remove stale template references before deleting files.
4. Add release note for removed links and replacement flows.

### Validation Gates
1. Admin sidebar contains no links to deprecated standalone pages.
2. Removed URLs are unresolved (404 path behavior).
3. No removed route is accidentally matched by generic route patterns.
4. Jobs and content workflows remain discoverable in two clicks or less.

### Exit Criteria
1. No primary navigation points to standalone API queue, R2, or SEO pages.
2. Deprecated standalone route names and templates are fully removed.
3. Staff can complete same operations from surviving pages.

### Rollback Trigger and Fallback
1. Trigger: critical operation no longer reachable from admin navigation.
2. Fallback:
   1. patch missing replacement links and re-test
   2. restore only strictly required endpoint handlers, not broad compatibility windows
   3. re-run Phase 2 removal regression suite before reattempt

## Phase 3: Unified DB-to-Queue Dispatch Pipeline

### Primary Objective
Standardize queue lifecycle across ProcessingJob and APIUploadQueue so every dispatched task has a consistent database lifecycle.

### Affected Surfaces
1. backend/apps/media_manager/models.py
2. backend/apps/media_manager/services/api_upload_queue_service.py
3. backend/apps/frontend_api/utils/jobs_dashboard.py
4. backend/apps/frontend_api/admin_views.py
5. backend/templates/admin/jobs_dashboard.html
6. backend/apps/frontend_api/tests_admin.py
7. backend/apps/media_manager/test_api_upload.py

### Canonical Status Transition Contract
1. Allowed lifecycle:
   1. pending -> processing
   2. processing -> completed
   3. processing -> failed
   4. pending -> canceled
   5. failed -> pending (retry)
2. Forbidden transitions:
   1. completed -> processing
   2. canceled -> processing
   3. completed -> failed (without explicit repair workflow)
3. Required metadata per transition:
   1. actor or system source
   2. timestamp
   3. reason or error message when failed or canceled

### Detailed Implementation Tasks
1. Model-level consistency:
   1. add/align status constants in both models
   2. normalize helper methods for can_retry, can_cancel, can_promote
2. Service-layer dispatch guard:
   1. create or sync DB row before Celery dispatch
   2. use transaction.atomic around create-and-dispatch metadata mutation
   3. store task id and source type consistently
3. Dashboard aggregation consistency:
   1. unify counting logic in jobs_dashboard utility
   2. ensure totals and status buckets are from canonical statuses only
4. Action API alignment:
   1. promote, cancel, retry endpoints must enforce same transition rules
   2. return stable response schema used by existing JS
5. Tests:
   1. transition success and rejection tests
   2. duplicate dispatch protection
   3. jobs total and bucket accuracy tests

### Break Risk
1. Divergent status states can make jobs dashboard counts inaccurate.
2. Dispatch paths can duplicate jobs if DB record creation is non-atomic.
3. Mixed source rows can make retries target wrong backend object.

### Safe Handling
1. Keep dispatch mutations transactional where possible.
2. Preserve existing API response keys from jobs endpoints.
3. Validate jobs counts against both models before and after migration.
4. Add explicit assertions for forbidden transitions.

### Validation Gates
1. All defined valid transitions succeed.
2. All forbidden transitions fail with clear response.
3. Retry, cancel, and promote work for processing_job and api_queue sources.
4. Dashboard counts match direct DB query totals.

### Exit Criteria
1. Jobs dashboard totals match real DB rows.
2. Promote/cancel/retry actions work for both sources.
3. No duplicate rows created by repeated dispatch call.

### Rollback Trigger and Fallback
1. Trigger: duplicate job creation or broken retry/cancel semantics.
2. Fallback:
   1. revert to previous service dispatch path
   2. keep read-only jobs dashboard while patching transition logic
   3. replay failed tests and reintroduce changes incrementally

## Phase 4: Content Lifecycle Audit Logging

### Primary Objective
Add persistent item-level lifecycle logs and expose them in a dedicated admin logs page.

### Affected Surfaces
1. backend/apps/media_manager/models.py
2. backend/apps/media_manager/migrations/
3. backend/apps/media_manager/signals.py
4. backend/apps/frontend_api/admin_views.py
5. backend/apps/frontend_api/urls.py
6. backend/templates/admin/ (new logs template)
7. backend/apps/frontend_api/tests_admin.py

### Audit Log Schema Contract
1. Required fields:
   1. content item reference
   2. action type
   3. actor (nullable for system)
   4. previous state
   5. new state
   6. message or payload summary
   7. created_at timestamp
2. Indexes:
   1. item + created_at
   2. action + created_at
   3. actor + created_at
   4. state + created_at
3. Data retention policy:
   1. keep full detail for active retention period
   2. allow archive strategy if row volume grows beyond target

### Detailed Implementation Tasks
1. Create model and migration with indexes aligned to filter patterns.
2. Create logging helper service to avoid scattered ad-hoc log writes.
3. Instrument lifecycle events:
   1. UI upload initiated
   2. R2 upload attempt
   3. R2 upload completed
   4. Gemini processing started
   5. Gemini processing completed
   6. SEO generated
   7. AI title mutated
   8. manual admin edit persisted
4. Build admin logs page:
   1. server-side pagination
   2. filters by action, actor, state, date range
   3. text search on message/content fields
5. Add tests for:
   1. event creation per lifecycle trigger
   2. filter correctness
   3. pagination behavior

### Break Risk
1. Heavy logging can impact write throughput.
2. Poor indexing can slow logs page and admin DB performance.
3. Signal recursion or duplicate log emission can inflate rows.

### Safe Handling
1. Keep log writes lightweight and asynchronous-safe.
2. Add composite indexes aligned with filter queries.
3. Paginate server-side and cap page size.
4. Use idempotent guards for signal-driven write paths.

### Validation Gates
1. Core lifecycle events emit exactly one expected log row each.
2. Logs page filter queries remain responsive under seeded high row count.
3. Admin logs page is staff-protected and inaccessible to non-staff.

### Exit Criteria
1. Lifecycle events are captured automatically for critical flows.
2. Logs page remains performant under large row count.
3. Operational debugging can be done from logs page without DB shell access.

### Rollback Trigger and Fallback
1. Trigger: measurable write slowdown or query regression.
2. Fallback:
   1. disable non-critical event logging behind flag
   2. keep critical security/action events only
   3. optimize indexes and re-enable gradually

## Phase 5: Inline R2 and SEO Controls in Content Surfaces

### Primary Objective
Move operational controls from standalone dashboards into content list/detail and media management views.

### Affected Surfaces
1. backend/apps/frontend_api/admin_views.py
2. backend/apps/frontend_api/admin_services.py
3. backend/templates/admin/content_list.html
4. backend/templates/admin/content_detail.html
5. backend/templates/admin/media_management_base.html
6. backend/templates/admin/partials/ (status/action partials)
7. backend/apps/frontend_api/urls.py
8. backend/apps/frontend_api/tests_admin.py

### Detailed Implementation Tasks
1. Add inline status chips:
   1. r2_upload_status
   2. seo_processing_status
   3. optional timestamp tooltip (last update)
2. Add conditional actions with dual guard:
   1. UI guard: show button only for allowed states
   2. server guard: enforce same rule in endpoint
3. Map actions:
   1. Retry R2 upload only for failed and retryable pending states
   2. Regenerate SEO only for failed or missing SEO states
4. Preserve API compatibility:
   1. same route names
   2. same request contract
   3. same response payload shape for frontend JS
5. Remove residual UI dependency on standalone R2/SEO pages.

### Break Risk
1. Status chips can desync from backend state if context assembly misses relations.
2. Action buttons can allow invalid transitions if status guards are incomplete.
3. Partial template rendering can silently fail if context keys are absent.

### Safe Handling
1. Reuse existing backend APIs in admin_views.py for actions.
2. Gate button rendering by status and enforce same checks server-side.
3. Preserve response payload shape expected by existing JS.
4. Add template tests for missing/edge status values.

### Validation Gates
1. Staff can execute valid actions from content list and content detail.
2. Invalid action attempts return clear error and do not mutate state.
3. No operational dependence on old standalone R2/SEO pages.

### Exit Criteria
1. Staff users can run required R2 and SEO recovery actions from content list/detail.
2. Standalone R2/SEO pages are not required for operations.
3. Existing frontend scripts continue to function without payload changes.

### Rollback Trigger and Fallback
1. Trigger: inline actions fail in common staff workflows.
2. Fallback:
   1. restore temporary links to compatibility routes
   2. keep new backend action endpoints active
   3. patch template context and guards, then re-enable inline-only flow

## Cross-Phase Validation Checklist

### Auth and Security
1. Anonymous dashboard access redirects to frontend_api:admin_login.
2. Non-staff users cannot access admin APIs or dashboards.
3. No endpoint leaks Django admin login destination.

### Functional Stability
1. Bulk upload and chunk upload endpoints remain unchanged and working.
2. Analytics dashboard and search sensitivity APIs continue to return expected payloads.
3. Document upload/download/delete for content items remains stable.
4. Jobs dashboard totals and item rows stay accurate after each phase.

### Performance
1. Jobs list remains DB paginated and memory safe.
2. Audit logs queries use indexed filters and pagination.
3. No significant latency regression on dashboard entry pages.

### Regression Smoke Targets
1. /en/dashboard/
2. /en/dashboard/jobs/
3. /en/dashboard/analytics/
4. /en/dashboard/content/
5. /en/dashboard/upload/bulk/
6. /accounts/login/

## Test Execution Plan
1. Per phase:
   1. run targeted tests for changed modules
   2. run auth and dashboard smoke tests
2. Before merge:
   1. run frontend_api test suite
   2. run media_manager queue-related tests
3. After deploy to staging:
   1. manual staff workflow pass
   2. redirect map verification
   3. jobs and logs data sanity checks

## Deployment and Rollout Notes
1. Deploy phases independently when possible.
2. Prefer low-traffic deployment window for Phase 3 and Phase 4.
3. Do not reintroduce compatibility redirects for removed Phase 2 standalone pages.
4. Announce deprecated URLs to internal admin users before final removal.

## Suggested Execution Order
1. Complete Phase 1 tests first.
2. Do Phase 2 hard removal and template/route cleanup.
3. Implement Phase 3 status pipeline unification.
4. Add Phase 4 logs model and UI.
5. Finish Phase 5 inline controls and remove remaining standalone dependencies.

## Final Definition of Done
1. All phase exit criteria met.
2. Cross-phase validation checklist fully green.
3. No regression on protected non-break routes and APIs.
4. Deprecated pages are no longer part of primary operations flow.
5. Documentation updated with deprecations, redirects, and operator guidance.

## Phase-by-Phase Task Board

Owner role legend:
1. Backend Engineer: Django views, services, models, migrations
2. Frontend Engineer: templates, UI controls, JS compatibility
3. QA Engineer: test design, regression and smoke verification
4. DevOps Engineer: rollout timing, deploy validation, observability
5. Tech Lead: cross-phase decisions, signoff, rollback approval

### Phase 2 Task Board: Deprecate Standalone Queue/R2/SEO Pages

- [x] Remove deprecated standalone links from admin navigation and dashboard cards
   - Owner: Frontend Engineer
   - Estimate: 3 hours
   - Dependencies: Phase 1 merged
- [x] Remove standalone route names and legacy alias routes from URL config
   - Owner: Backend Engineer
   - Estimate: 3 hours
   - Dependencies: Phase 1 merged
- [x] Restrict generic media route matching to explicit media types only
   - Owner: Backend Engineer
   - Estimate: 2 hours
   - Dependencies: URL cleanup
- [x] Remove deprecated templates and active references
   - Owner: Frontend Engineer
   - Estimate: 2 hours
   - Dependencies: Navigation cleanup
- [x] Validate removed routes fail fast and are not accidentally resolved
   - Owner: QA Engineer
   - Estimate: 2 hours
   - Dependencies: Route removal
- [x] Add removal notes and URL deprecation mapping to release documentation
   - Owner: Tech Lead
   - Estimate: 1 hour
   - Dependencies: Route validation
- [x] Approve hard-cut removal and merge
   - Owner: Tech Lead
   - Estimate: 30 minutes
   - Dependencies: All phase 2 tasks

### Phase 3 Task Board: Unified DB-to-Queue Dispatch Pipeline

- [x] Align status constants and transition helpers between ProcessingJob and APIUploadQueue
   - Owner: Backend Engineer
   - Estimate: 4 hours
   - Dependencies: Phase 2 merged
- [x] Implement transactional create-or-sync DB behavior before Celery dispatch
   - Owner: Backend Engineer
   - Estimate: 5 hours
   - Dependencies: Status alignment
- [x] Standardize task metadata persistence including task id and source type
   - Owner: Backend Engineer
   - Estimate: 2 hours
   - Dependencies: Transactional dispatch update
- [x] Unify jobs dashboard aggregation logic for canonical statuses
   - Owner: Backend Engineer
   - Estimate: 3 hours
   - Dependencies: Metadata standardization
- [x] Align promote, cancel, and retry endpoint behavior with forbidden/allowed transition contract
   - Owner: Backend Engineer
   - Estimate: 4 hours
   - Dependencies: Aggregation unification
- [x] Add transition validation tests, duplicate-dispatch protection tests, and totals accuracy tests
   - Owner: QA Engineer
   - Estimate: 6 hours
   - Dependencies: Endpoint behavior alignment
- [x] Run phase performance sanity checks on jobs dashboard query and mutation flows
   - Owner: QA Engineer
   - Estimate: 2 hours
   - Dependencies: Phase 3 test completion
- [x] Approve merge after transition matrix compliance review
   - Owner: Tech Lead
   - Estimate: 1 hour
   - Dependencies: All phase 3 tasks

Phase 3 sanity evidence (2026-05-23):
1. Targeted transition and source-persistence tests passed: 3/3.
2. Broader Phase 3 jobs suite passed: 7/7.
3. Query/mutation-read sanity timings from shell probe:
   1. get_jobs_counts: 3.14 ms
   2. get_all_jobs (pending, page=1): 3.45 ms
   3. api_jobs_stats: 3.05 ms (HTTP 200)
   4. api_jobs_list HTMX render path: 16250.07 ms (HTTP 200)

### Phase 4 Task Board: Content Lifecycle Audit Logging

- [ ] Implement audit log model and migration with required indexes
   - Owner: Backend Engineer
   - Estimate: 5 hours
   - Dependencies: Phase 3 merged
- [ ] Create centralized audit logging helper service
   - Owner: Backend Engineer
   - Estimate: 3 hours
   - Dependencies: Audit model in place
- [ ] Instrument lifecycle events for upload, R2, Gemini, SEO, title mutation, and manual edits
   - Owner: Backend Engineer
   - Estimate: 6 hours
   - Dependencies: Logging helper service
- [ ] Build admin logs view, filters, and pagination
   - Owner: Backend Engineer
   - Estimate: 4 hours
   - Dependencies: Event instrumentation
- [ ] Create admin logs template and wire staff-only access in dashboard navigation
   - Owner: Frontend Engineer
   - Estimate: 3 hours
   - Dependencies: Logs view available
- [ ] Add event emission tests, filter correctness tests, and pagination tests
   - Owner: QA Engineer
   - Estimate: 5 hours
   - Dependencies: Logs UI and endpoint wiring
- [ ] Run seeded high-volume query performance check for logs page
   - Owner: QA Engineer
   - Estimate: 3 hours
   - Dependencies: Audit tests completed
- [ ] Approve rollout strategy for logging volume and retention
   - Owner: Tech Lead
   - Estimate: 1 hour
   - Dependencies: Performance check results

### Phase 5 Task Board: Inline R2 and SEO Controls

- [ ] Add inline status chips in content list/detail and media surfaces
   - Owner: Frontend Engineer
   - Estimate: 4 hours
   - Dependencies: Phase 4 merged
- [ ] Add conditional action buttons for retry R2 and regenerate SEO by status
   - Owner: Frontend Engineer
   - Estimate: 4 hours
   - Dependencies: Inline status chips
- [ ] Enforce server-side transition guard parity for all inline actions
   - Owner: Backend Engineer
   - Estimate: 3 hours
   - Dependencies: Conditional actions designed
- [ ] Preserve existing endpoint contracts and response payload shape
   - Owner: Backend Engineer
   - Estimate: 2 hours
   - Dependencies: Server-side guard parity
- [ ] Remove residual operational dependency on deprecated standalone R2/SEO pages
   - Owner: Frontend Engineer
   - Estimate: 2 hours
   - Dependencies: Inline actions fully wired
- [ ] Add template and endpoint tests for valid and invalid inline transitions
   - Owner: QA Engineer
   - Estimate: 4 hours
   - Dependencies: Endpoint contract preservation
- [ ] Execute final admin workflow smoke pass across list/detail/jobs/logs
   - Owner: QA Engineer
   - Estimate: 3 hours
   - Dependencies: Phase 5 tests
- [ ] Final signoff and deprecation completion approval
   - Owner: Tech Lead
   - Estimate: 1 hour
   - Dependencies: Full smoke pass

### Cross-Phase Release Board

- [ ] Confirm non-break endpoints remain behaviorally unchanged
   - Owner: QA Engineer
   - Estimate: 2 hours per phase
   - Dependencies: End of each phase implementation
- [ ] Confirm auth policy consistency and no leak to Django admin login
   - Owner: QA Engineer
   - Estimate: 1 hour per phase
   - Dependencies: End of each phase implementation
- [ ] Confirm rollback readiness before each production deployment
   - Owner: DevOps Engineer
   - Estimate: 1 hour per phase
   - Dependencies: Phase release candidate ready
- [ ] Confirm release notes and migration notes are up to date per phase
   - Owner: Tech Lead
   - Estimate: 30 minutes per phase
   - Dependencies: Phase QA signoff

### Estimated Timeline Summary

3. Phase 2: 1 day
4. Phase 3: 2 to 3 days
5. Phase 4: 2 to 3 days
6. Phase 5: 1 to 2 days
7. Total estimated elapsed time: 8 to 12 working days (excluding external blockers)
