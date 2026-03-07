# Translation Plan — En/Ar Full Coverage
> Scope: English ↔ Arabic only. Frontend + backend display text, messages, and AJAX responses.  
> Exclusions: SEO metadata (`<head>`, schema.org), model content fields that already carry `_ar`/`_en` versions, admin-only internal labels not user-facing.

---

## Current State Snapshot

| Layer | Status |
|---|---|
| Django i18n enabled | ✅ `USE_I18N=True`, `LocaleMiddleware` active, `LANGUAGE_CODE='ar'` |
| Locale files | `backend/locale/ar/` and `backend/locale/en/` — **~502 msgids**, **8 empty msgstrs** |
| Frontend templates (`frontend_api/`, `includes/`, `registration/`, `users/`, `errors/`) | ✅ All load `{% load i18n %}`, most strings already wrapped |
| Admin templates (`admin/`, `admin_django/`, `layouts/`) | ✅ All load `{% load i18n %}`, good coverage |
| `includes/messages.html` | ⚠️ Missing `{% load i18n %}` — messages render but tag is absent |
| `emails/reindex_complete.html` | ⚠️ Missing `{% load i18n %}` |
| Python flash messages (`messages.success/error/warning`) | ⚠️ ~18 calls in `admin_views.py` use raw strings or f-strings without `_()` |
| Python AJAX `JsonResponse` error strings | ⚠️ ~40+ hardcoded English strings in `admin_views.py`, `views.py`, `core/views.py` |
| Form `ValidationError` strings | ✅ Most use `_()`, one in `api/serializers.py` does not |
| JavaScript inline strings (toast/DOM injections) | ⚠️ Inline JS in admin templates injects English text via `innerHTML` without `{% trans %}` data attributes |
| JS i18n catalog (`JavaScriptCatalog`) | ❌ Not configured — no Django JS i18n endpoint |

---

## Rules (Non-Negotiable)

1. **Never translate model content fields** — `title_ar`, `title_en`, `description_ar`, `description_en` carry their own bilingual versions. Selection logic already in `services.py`. Do not wrap these in `{% trans %}`.
2. **Use `gettext_lazy` (`_`) in models, forms, validators, and serializers** — these are evaluated at import time. Use `gettext` (non-lazy) only in view functions and management commands.
3. **Use `{% trans %}` for short static strings** in templates. Use `{% blocktrans %}` only when you need variable interpolation inside the string (e.g., `{% blocktrans with count=obj.count %}{{ count }} items found{% endblocktrans %}`).
4. **Never concatenate translated strings** — `_("Hello") + name` is wrong. Use `_("Hello %(name)s") % {"name": name}` or `{% blocktrans %}`.
5. **AJAX `JsonResponse` messages that are user-visible must be wrapped in `_()`** — API-only keys like `{"success": true}` or `{"id": 42}` are data, not messages; leave them as-is.
6. **Every `.po` file change requires `compilemessages`** before taking effect in production.
7. **`makemessages` must be run from `backend/` directory** using the command below — it will extract all `{% trans %}`, `gettext`, `gettext_lazy`, and `ngettext` calls automatically.
8. **Do not translate technical error details** sent to `str(e)` in exception catches when those strings come from third-party libraries (e.g., Python exceptions, database errors). Wrap only the human-readable prefix.
9. **JavaScript user-visible strings** — prefer data-attribute injection from Django template context (`data-i18n-*`) over Django JS catalog, unless the JS file is too large to be inline.
10. **RTL layout** is handled by CSS/HTML `dir` attribute. Translation plan does not cover layout changes.

---

## CLI Commands Reference

```bash
# Run all commands from backend/

# 1. Extract all translatable strings into .po files
python manage.py makemessages -l ar -l en --ignore=staticfiles/* --ignore=node_modules/*

# 2. Compile .po → .mo (required after any .po edit)
python manage.py compilemessages

# 3. Check for untranslated strings (fuzzy + empty)
msgfmt --statistics locale/ar/LC_MESSAGES/django.po -o /dev/null

# 4. Find all translatable calls not yet wrapped in Python files
grep -rn "messages\.success\|messages\.error\|messages\.warning\|messages\.info\|JsonResponse" apps/ \
  | grep -v ".pyc" | grep -v "_(" | grep -v "test"

# 5. Find HTML template lines with visible English text not inside {% trans %}
grep -rn ">[A-Z][a-z]" templates/ | grep -v "{% trans\|{% blocktrans\|{%\|{{" | grep -v ".pyc"

# 6. Find templates missing {% load i18n %}
grep -rL "{% load i18n" templates/**/*.html

# 7. Show all empty (untranslated) entries in Arabic .po
grep -B2 'msgstr ""' locale/ar/LC_MESSAGES/django.po | grep "msgid"
```

---

## Phases

---

### Phase 1 — Foundation Fixes (Breaking / Quick Wins)
> **Priority: Critical — do these first.**  
> No new translations needed. Just structural fixes that unblock everything else.

#### Checklist

- [x] **1.1** Add `{% load i18n %}` to `templates/includes/messages.html`
  - File: `backend/templates/includes/messages.html`
  - Fix: Add `{% load i18n %}` as line 2 (after the comment)
  - Why: Flash messages rendered here are passed as translated strings from Python — but if a template tag is ever needed in this file, the tag won't be found.

- [x] **1.2** Add `{% load i18n %}` to `templates/emails/reindex_complete.html`
  - File: `backend/templates/emails/reindex_complete.html`
  - Fix: Add `{% load i18n %}` at top of file

- [x] **1.3** Add `{% load i18n %}` to `templates/base.html` (already has `{% load static i18n %}` — **verify it is before any `{% trans %}` call**)
  - File: `backend/templates/base.html` — currently only 1 `{% trans %}` instance; confirm `{% load static i18n %}` is line 2

- [x] **1.4** Verify `LocaleMiddleware` position in `MIDDLEWARE` setting
  - File: `backend/config/settings/base.py`
  - Rule: `LocaleMiddleware` must come **after** `SessionMiddleware` and **before** `CommonMiddleware`
  - Command: `grep -n "LocaleMiddleware\|SessionMiddleware\|CommonMiddleware" backend/config/settings/base.py`

- [x] **1.5** Confirm `LOCALE_PATHS` points to correct directory
  - Current: `BASE_DIR / 'locale'` → `backend/locale/` ✅

---

### Phase 2 — Python Backend: Flash Messages & Validation
> **Scope:** All `messages.success/error/warning/info` calls and `ValidationError` that are displayed to the user.

#### Checklist

- [x] **2.1** Wrap all bare flash messages in `admin_views.py`
  - File: `backend/apps/frontend_api/admin_views.py`
  - Pattern to fix:
    ```python
    # BEFORE — untranslated
    messages.error(request, f"Error processing delete request: {str(e)}")
    messages.error(request, 'No document attached to this content')
    messages.error(request, 'Error downloading document')
    messages.error(request, f'Error promoting item: {str(e)}')
    messages.error(request, f'Error cancelling item: {str(e)}')
    
    # AFTER — translated (import already exists: from django.utils.translation import gettext_lazy as _)
    messages.error(request, _("Error processing delete request: %(error)s") % {"error": str(e)})
    messages.error(request, _("No document attached to this content"))
    messages.error(request, _("Error downloading document"))
    messages.error(request, _("Error promoting item: %(error)s") % {"error": str(e)})
    messages.error(request, _("Error cancelling item: %(error)s") % {"error": str(e)})
    ```
  - Lines: 240, 294, 2329, 2370, 2452, 2471
  - Note: Lines 87, 89, 217, 220, 264, 274, 2305, 2346 already pass a `message` variable — verify the source of that variable is already wrapped in `_()` at its origin point.

- [x] **2.2** Fix `ValidationError` in API serializer
  - File: `backend/apps/media_manager/api/serializers.py`
  - Line: 81
  - Before: `raise serializers.ValidationError('One or more tags not found or inactive')`
  - After: `raise serializers.ValidationError(_('One or more tags not found or inactive'))`
  - Add import: `from django.utils.translation import gettext_lazy as _`

- [x] **2.3** Audit all `views.py` flash messages
  - Files: `apps/users/views.py`, `apps/media_manager/views.py`, `apps/frontend_api/views.py`
  - Command:
    ```bash
    grep -n "messages\." apps/users/views.py apps/media_manager/views.py apps/frontend_api/views.py | grep -v "_("
    ```
  - Fix any bare string flash messages the same way as 2.1

- [x] **2.4** Audit `admin.py` files for untranslated messages
  - Files: `apps/media_manager/admin.py` (line 428), `apps/users/admin.py` (lines 198, 216)
  - Command: `grep -n "messages\." apps/*/admin.py | grep -v "_( " | grep -v ".pyc"`

---

### Phase 3 — Python Backend: AJAX JsonResponse Messages
> **Scope:** Only `error`, `message`, and `detail` keys in `JsonResponse` that are shown to the user in the browser UI.  
> **Skip:** Internal keys like `success` (boolean), `id`, `count`, `data`, `results` — these are not displayed as text.

#### Checklist

- [x] **3.1** Wrap user-visible error strings in `core/views.py`
  - File: `backend/apps/core/views.py`
  - Lines: 51, 173
  - Pattern:
    ```python
    # Before
    return JsonResponse({'error': 'Unauthorized'}, status=401)
    # After
    return JsonResponse({'error': _('Unauthorized')}, status=401)
    ```
  - `gettext as _` is already imported in this file (line 14)

- [x] **3.2** Wrap all user-visible AJAX error strings in `admin_views.py`
  - File: `backend/apps/frontend_api/admin_views.py`
  - The import `from django.utils.translation import gettext_lazy as _` is already present (line 15)
  - Strings to wrap (pattern: find all `'error': '...'` and `'message': '...'` with raw strings):
    ```bash
    grep -n "JsonResponse.*'error'.*'" apps/frontend_api/admin_views.py | grep -v "_("
    ```
  - Key strings found:
    - `'POST method required'` (lines 311, 387, 771)
    - `'No file provided'` (line 319)
    - `'Content ID required'` (lines 392, 615)
    - `'Invalid JSON'` (line 638)
    - `'No content IDs provided'` (lines 654, 697, 726)
    - `'File required'` (line 776)
    - `'Unsupported file type'` (line 790)
    - `'AI service not available'` (line 795)
    - `'Permission denied'` (lines 877, 1009)
    - `'Invalid content type'` (line 1016)

- [x] **3.3** Wrap user-visible AJAX error strings in `frontend_api/views.py`
  - File: `backend/apps/frontend_api/views.py`
  - Lines: 437, 449, 456, 468, 485, 504
  - Import `gettext_lazy as _` is already present via line 509 (but only inside a function — move import to top-level)
  - Strings: `'Query parameter required'`

- [ ] **3.4** Run `makemessages` to extract all newly wrapped strings
  ```bash
  cd backend && python manage.py makemessages -l ar -l en
  ```

---

### Phase 4 — Template: Remaining Hardcoded Strings
> Run `makemessages` after this phase to extract new strings.

#### Checklist

- [ ] **4.1** Audit `templates/admin/` for any hardcoded English visible text not wrapped in `{% trans %}`
  - Command:
    ```bash
    grep -rn ">[A-Z][a-z ]\{3,\}<" backend/templates/admin/ | grep -v "{% trans\|{% blocktrans\|{%\|{{"
    ```
  - Focus areas: button labels, headings, table headers, status badges, empty-state messages

- [ ] **4.2** Audit `templates/frontend_api/` for any remaining hardcoded strings
  - Command:
    ```bash
    grep -rn ">[A-Z][a-z ]\{3,\}<" backend/templates/frontend_api/ | grep -v "{% trans\|{% blocktrans\|{%\|{{"
    ```

- [ ] **4.3** Audit `templates/includes/navbar.html` and `templates/includes/footer.html`
  - Pay attention to: navigation link labels, language switcher text, copyright text

- [ ] **4.4** Audit `templates/registration/` and `templates/users/`
  - Check: form field labels, button text, helper text, error messages

- [ ] **4.5** Audit `placeholder=`, `title=`, `aria-label=` attributes across all templates
  - Command:
    ```bash
    grep -rn "placeholder=\"[A-Z]\|title=\"[A-Z]\|aria-label=\"[A-Z]" backend/templates/ | grep -v "{% trans\|{% blocktrans"
    ```
  - Fix pattern:
    ```html
    <!-- Before -->
    <input placeholder="Search...">
    <!-- After -->
    <input placeholder="{% trans 'Search...' %}">
    ```

- [ ] **4.6** Check `templates/emails/reindex_complete.html` and `reindex_complete.txt` for body text
  - These go to users — must be translated

---

### Phase 5 — JavaScript Inline Strings
> **Scope:** JavaScript code inside `<script>` tags in templates that injects user-visible text via `innerHTML`, `textContent`, `toast`, `.text()`, etc.  
> **Strategy:** Inject translated strings from Django template context using `data-*` attributes or inline JS variables using `{% trans %}` before the `<script>` block.

#### Checklist

- [ ] **5.1** Audit all `innerHTML = \`` template literal blocks in admin templates for visible English text
  - Files: `admin/dashboard.html`, `admin/seo_reindex.html`, `admin/r2_status_dashboard.html`, `admin/partials/gemini_rate_limits.html`, `admin/partials/r2_storage_info.html`, `admin/content_detail.html`, `admin/upload_content.html`

- [ ] **5.2** Use Django `{% trans %}` to inject translated strings into a JS variable block at the top of each `<script>` that needs them
  - Pattern:
    ```html
    <!-- At top of <script> block or just before it -->
    <script>
    const i18n = {
        errorOccurred: "{% trans 'An error occurred' %}",
        successSaved: "{% trans 'Saved successfully' %}",
        confirmDelete: "{% trans 'Are you sure you want to delete?' %}",
        loading: "{% trans 'Loading...' %}",
        noResults: "{% trans 'No results found' %}",
        permissionDenied: "{% trans 'Permission denied' %}",
        postRequired: "{% trans 'POST method required' %}",
        fileRequired: "{% trans 'File required' %}",
    };
    </script>
    ```
  - Then reference: `toast.innerHTML = i18n.errorOccurred;` instead of `toast.innerHTML = 'An error occurred';`
  - **Restrict** this block to strings that are actually used in that template's JS — do not create a bloated global dictionary.

- [ ] **5.3** Wrap button loading spinners that contain English text
  - Pattern found: `button.innerHTML = '<span ...></span> Loading...'`
  - Fix: `button.innerHTML = '<span ...></span> ' + "{% trans 'Loading...' %}";`
  - Or use `data-loading-text="{% trans 'Loading...' %}"` attribute on the button and read it from JS

- [ ] **5.4** For `static/js/analytics-tracking.js` — since it is a static file (cannot use Django template tags), any user-visible strings should be passed via `data-*` attributes from the HTML and read by JS. Audit this file for any `alert()` or injected text.

---

### Phase 6 — Complete Arabic Translations in `.po` File
> After running `makemessages` (Phase 3.4 + end of Phase 4), fill in translations.

#### Checklist

- [ ] **6.1** Run `makemessages` to pick up all new strings
  ```bash
  cd backend && python manage.py makemessages -l ar -l en --ignore=staticfiles/*
  ```

- [ ] **6.2** Open `backend/locale/ar/LC_MESSAGES/django.po` and search for:
  - Empty `msgstr ""` entries (untranslated)
  - New entries without `msgstr` (added by `makemessages`)
  - Command to find them:
    ```bash
    grep -n "msgstr \"\"" locale/ar/LC_MESSAGES/django.po
    ```

- [ ] **6.3** Translate each untranslated entry — currently 8 empty + all new ones from Phases 2–5
  - Focus on user-facing categories in order:
    1. Flash messages (success/error/warning/info)
    2. Form validation errors
    3. AJAX error messages
    4. Button labels and navigation
    5. Page headings and section titles
    6. Empty states and placeholders
    7. Email body text

- [ ] **6.4** Remove any `#, fuzzy` entries after reviewing them (currently 0 fuzzy entries)

- [ ] **6.5** Compile translations
  ```bash
  cd backend && python manage.py compilemessages
  ```

- [ ] **6.6** Verify statistics
  ```bash
  msgfmt --statistics locale/ar/LC_MESSAGES/django.po -o /dev/null
  # Should show: X translated messages, 0 untranslated messages.
  ```

---

### Phase 7 — Quality Check & Regression Testing
> After all translation work is complete.

#### Checklist

- [ ] **7.1** Switch browser language preference to English and test all pages in `/en/` prefix
  - Verify: flash messages appear in English
  - Verify: AJAX error toasts appear in English
  - Verify: form validation errors appear in English

- [ ] **7.2** Switch to Arabic (`/ar/`) and repeat the same test
  - Verify: flash messages appear in Arabic
  - Verify: AJAX toasts appear in Arabic
  - Verify: form validation errors appear in Arabic
  - Verify: RTL layout is consistent (not in scope but check it didn't break)

- [ ] **7.3** Test the language switcher (`/i18n/setlang/`) to confirm it persists properly

- [ ] **7.4** Run Django system checks
  ```bash
  cd backend && python manage.py check --deploy
  ```

- [ ] **7.5** Run existing test suite to catch regressions
  ```bash
  cd backend && python manage.py test apps.frontend_api apps.media_manager apps.users
  ```

- [ ] **7.6** Grep for any remaining obvious untranslated English in templates
  ```bash
  # Strings that appear between > and < without any trans tag on that line
  grep -rn ">[A-Z][a-z ]\{4,\}<" backend/templates/ | grep -v "{% trans\|{% blocktrans\|{%\|{{\|<!--"
  ```

- [ ] **7.7** Check admin panel renders correctly — `{% trans %}` in admin templates should not break Django admin's own i18n

---

## File Index — Files Requiring Changes

### Templates

| File | Issue | Phase |
|------|-------|-------|
| `templates/includes/messages.html` | Missing `{% load i18n %}` | 1.1 |
| `templates/emails/reindex_complete.html` | Missing `{% load i18n %}` | 1.2 |
| `templates/admin/dashboard.html` | JS `innerHTML` with English strings | 5.2 |
| `templates/admin/content_detail.html` | JS `innerHTML` with English strings | 5.2 |
| `templates/admin/seo_reindex.html` | JS `innerHTML` with English strings | 5.2 |
| `templates/admin/r2_status_dashboard.html` | JS `innerHTML` with English strings | 5.2 |
| `templates/admin/upload_content.html` | JS `innerHTML` with English strings | 5.2 |
| `templates/admin/partials/gemini_rate_limits.html` | JS `innerHTML` with English strings | 5.2 |
| `templates/admin/partials/r2_storage_info.html` | JS `innerHTML` with English strings | 5.2 |
| `templates/admin/partials/content_list.html` | JS button loading state | 5.3 |

### Python Files

| File | Issue | Phase |
|------|-------|-------|
| `apps/frontend_api/admin_views.py` | ~18 flash messages + ~25 AJAX strings not in `_()` | 2.1, 3.2 |
| `apps/frontend_api/views.py` | `_` import inside function (not top-level) + bare AJAX strings | 3.3 |
| `apps/core/views.py` | 2 AJAX `'Unauthorized'` strings | 3.1 |
| `apps/media_manager/api/serializers.py` | 1 `ValidationError` bare string | 2.2 |
| `apps/media_manager/admin.py` | Flash message at line 428 | 2.4 |
| `apps/users/admin.py` | Flash messages at lines 198, 216 | 2.4 |
| `apps/users/views.py` | Line 120 — verify if `error` variable is already `_()` wrapped | 2.3 |

### Locale Files

| File | Issue | Phase |
|------|-------|-------|
| `locale/ar/LC_MESSAGES/django.po` | 8 empty + new strings from Phases 2–5 | 6.2–6.5 |
| `locale/en/LC_MESSAGES/django.po` | Sync with new strings from Phases 2–5 | 6.1 |

---

## Commit Strategy

Each phase should be a separate commit:

```
feat(i18n): Phase 1 - load i18n tag fixes in templates
feat(i18n): Phase 2 - wrap flash messages and ValidationError in gettext
feat(i18n): Phase 3 - wrap AJAX JsonResponse error strings in gettext
feat(i18n): Phase 4 - wrap remaining hardcoded template strings
feat(i18n): Phase 5 - JS inline string i18n via data attributes
feat(i18n): Phase 6 - complete Arabic translations in .po file
feat(i18n): Phase 7 - verify and compile all translations
```

---

## Quick Reference: What NOT to Translate

- `{{ item.title }}`, `{{ item.title_ar }}`, `{{ item.description }}` — model content fields
- `{{ item.slug }}`, `{{ item.id }}`, `{{ item.created_at }}` — technical fields
- `{% url '...' %}`, `{% static '...' %}` — URL/static references
- `{{ form.as_p }}` — Django auto-renders form field labels (those are translated at model/form level separately)
- AJAX payload keys: `{"success": true}`, `{"id": 5}`, `{"results": [...]}` — data structure keys
- HTTP status codes and internal log messages — these are for developers
- Exception `str(e)` details from third-party libraries
- JavaScript variable names, CSS class names, HTML attribute technical values
