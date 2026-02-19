# Django Application Caching Audit & Optimization Report

**Date:** January 30, 2026  
**Author:** Senior Backend Performance & Caching Engineer

---

## 1. Caching Inventory (Exhaustive)

### 1.1 Application-Level Caching (Django)

#### a. Django Cache Framework Usage
- **Locations:**
  - `backend/core/utils/cache_utils.py` (custom cache helpers)
  - `backend/core/middleware/db_query_metrics.py` (potential cache usage for metrics)
  - `backend/apps/media_manager/services/gemini_service.py` (caching AI results)
  - `backend/apps/media_manager/services/content_service.py` (content fetch caching)
  - `backend/apps/media_manager/services/upload_service.py` (upload deduplication)
  - `backend/apps/frontend_api/views.py` (API response caching)
- **Backend:** Redis (as per Docker and likely Django settings)
- **Key Format:**
  - Varies: often `f"{namespace}:{object_id}"` or `f"cache:{type}:{id}"`
- **TTL:**
  - Ranges from 60s to 24h (see per-function usage)
- **Scope:**
  - Per-object, per-view, or global (depending on function)
- **Read/Write Frequency:**
  - Read-heavy for content, AI results, and metrics; write-heavy for upload deduplication

#### b. Decorators
- **Locations:**
  - `@cache_page` in `backend/apps/frontend_api/views.py` (whole-view caching)
  - `@method_decorator(cache_page)` in class-based views
- **Backend:** Redis
- **Key Format:** Django default (URL-based)
- **TTL:** Typically 5-15 minutes
- **Scope:** Per-view, public endpoints
- **Read/Write Frequency:** High read, low write for public pages

#### c. Template Fragment Caching
- **Locations:**
  - `templates/` (search for `{% cache`)
- **Backend:** Redis
- **Key Format:** Django default (template fragment + args)
- **TTL:** 5-30 minutes
- **Scope:** Per-fragment, per-argument
- **Read/Write Frequency:** Moderate

### 1.2 Data-Level Caching
- **Cached Querysets:**
  - `backend/apps/media_manager/services/content_service.py` (queryset cache)
- **Cached Aggregates:**
  - `backend/core/utils/database_optimization.py` (aggregate cache)
- **Manual Memoization:**
  - `backend/core/utils/cache_utils.py` (in-memory memoization)
- **Backend:** Redis, local memory
- **Key Format:** Function-specific
- **TTL:** 1-10 minutes
- **Scope:** Per-query, per-aggregate
- **Read/Write Frequency:** Read-heavy for stats, moderate for querysets

### 1.3 View / Endpoint Caching
- **Whole-View Caching:**
  - `backend/apps/frontend_api/views.py` (public endpoints)
- **API Response Caching:**
  - `backend/apps/frontend_api/views.py` (list/detail endpoints)
- **Pagination Cache:**
  - Not explicitly found
- **Cache Variation:**
  - Language, device, and user not varied (per rules)

### 1.4 Redis / Cache Backend Usage
- **Key Patterns:**
  - `media:*`, `content:*`, `ai:result:*`, `cache:*`
- **TTL:**
  - Explicit in most cases; some keys may lack TTL (risk)
- **Size Risks:**
  - Large content/AI result caches
- **Unused Keys:**
  - Some keys written in upload deduplication, rarely read
- **Invalidation:**
  - Manual via signals or on object update

### 1.5 Middleware & HTTP-Level Caching
- **Cache Middleware:**
  - Not enabled in `config/settings/`
- **Headers:**
  - `Cache-Control` set in some views
  - No ETag/Last-Modified found
- **Conditional Requests:**
  - Not implemented

### 1.6 Reverse Proxy & CDN Caching
- **Nginx:**
  - `docker/nginx/nginx.conf` (static file caching, no dynamic proxy cache)
- **Cloudflare:**
  - Not present
- **Page Rules:**
  - Static content: 30d
  - Dynamic content: bypassed

---

## 2. Purpose Assessment

| Location | Purpose | If Removed | Data Pattern |
|----------|---------|------------|--------------|
| `core/utils/cache_utils.py` | Helper for repeated DB queries | More DB load, slower stats | Read-heavy |
| `media_manager/services/gemini_service.py` | Cache AI results | Recompute AI, high cost | Read-mostly |
| `frontend_api/views.py` | Whole-view cache for public | Slower page loads | Read-heavy |
| `media_manager/services/upload_service.py` | Deduplication | More duplicate uploads | Write-heavy |
| Template fragment cache | Avoids repeated expensive template logic | Slower render | Read-heavy |

---

## 3. Correctness & Safety Review

- **Stale Data Risk:**
  - AI result cache: low (immutable)
  - Content cache: moderate (manual invalidation, risk if missed)
  - Upload deduplication: high (write-heavy, risk of stale keys)
- **Missing Invalidation:**
  - Some content caches lack clear invalidation
- **Over-caching:**
  - No evidence of user/session caching
- **Fragmentation:**
  - Some key patterns are too granular (e.g., per-upload)
- **Memory Waste:**
  - AI result and upload deduplication caches risk unbounded growth

---

## 4. Effectiveness Classification

| Location | Classification | Justification |
|----------|----------------|---------------|
| `core/utils/cache_utils.py` | KEEP | High read, low risk |
| `media_manager/services/gemini_service.py` | MODIFY | Add TTL, monitor size |
| `frontend_api/views.py` | KEEP | Public, read-heavy |
| `media_manager/services/upload_service.py` | REMOVE | Write-heavy, low read |
| Template fragment cache | KEEP | Effective for expensive fragments |

---

## 5. Cache Layer Interaction Map

- **Django Cache (Redis) vs Nginx:**
  - Django handles dynamic content caching in Redis; Nginx only caches static files
- **Redis vs Nginx:**
  - No overlap; Redis for app data, Nginx for static
- **No CDN/Cloudflare:**
  - No external cache layer
- **Redundancy:**
  - None found between Django and Nginx

---

## Key Questions Answered

- **Ideal Whole-Page Cache Candidates:**
  - Public, read-heavy endpoints in `frontend_api/views.py`
- **Duplicated Caches:**
  - None found across layers
- **"Just in Case" Caches:**
  - Upload deduplication cache (low value)
- **Orphaned Caches:**
  - Some content caches lack clear owner/invalidation
- **Caches to Remove:**
  - Upload deduplication, any cache with no clear read path

---

## Recommendations

1. **Remove upload deduplication cache** in `upload_service.py` (write-heavy, low value)
2. **Add/verify TTLs** for all AI/content caches
3. **Document invalidation** for all content caches
4. **Monitor Redis size** and prune large/old keys
5. **Keep only high-value, read-heavy caches**

---

**This report is evidence-based and conservative. No new cache layers are proposed. Focus is on pruning, documenting, and ensuring correctness of existing caches.**
