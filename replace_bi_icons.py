#!/usr/bin/env python3
"""
replace_bi_icons.py
-------------------
Replaces Bootstrap Icons <i class="bi bi-xxx ..."> tags with inline
<svg><use href="#bi-xxx"/></svg> across all HTML templates.

Also handles:
 - Alpine.js dynamic :class patterns  → :href on <use>
 - <i> with both static class + Alpine :class binding
 - Icon substitutions for icons not in Bootstrap Icons 1.11.3:
     bi-book-open  → bi-book
     bi-sparkles   → bi-magic

Run from the project root:
    python replace_bi_icons.py
"""

import re
import os
import sys

# ── Icon name substitutions (icons that don't exist in BI 1.11.3) ──────────
SUBSTITUTIONS = {
    'book-open': 'book',
    'sparkles':  'magic',
}

# Auto-detect templates directory:
#   - Local dev:  <project-root>/backend/templates/
#   - Docker:     /app/templates/  (backend/ is copied to /app/)
_here = os.path.dirname(os.path.abspath(__file__))
_local_path     = os.path.join(_here, 'backend', 'templates')
_container_path = os.path.join(_here, 'templates')
TEMPLATES_DIR = _local_path if os.path.isdir(_local_path) else _container_path


# ── Regex patterns ─────────────────────────────────────────────────────────

# Pattern 1: standard <i class="bi bi-ICON [extra]" [other_attrs]></i>
# Captures: (icon-name)(extra-classes-in-quoting)(other attributes before >)
BI_ICON_RE = re.compile(
    r'<i\s+class="bi\s+bi-([a-z0-9-]+)([^"]*)"([^>]*)>\s*</i>',
    re.DOTALL,
)

# Pattern 2: Alpine.js dynamic icon:
#   <i class="bi [extra]" :class="SOME_EXPR containing bi-X and/or bi-Y"></i>
#   We convert the :class expression  →  :href on <use>
# e.g. :class="loading ? 'bi-hourglass-split' : 'bi-sparkles'"
#   →  <svg...><use :href="loading ? '#bi-hourglass-split' : '#bi-magic'"></use></svg>
ALPINE_ICON_RE = re.compile(
    r'<i\s+class="bi([^"]*?)"\s+:class="([^"]+)"([^>]*)>\s*</i>',
    re.DOTALL,
)


def apply_substitutions(text: str) -> str:
    """Replace known missing icon names with available alternatives."""
    for old, new in SUBSTITUTIONS.items():
        text = text.replace(old, new)
    return text


def replace_standard(match) -> str:
    icon_name   = apply_substitutions(match.group(1).strip())
    extra_class = match.group(2).strip()          # e.g. "text-golden me-2"
    other_attrs = match.group(3).strip()          # e.g. style="font-size:2rem;"

    cls = 'bi'
    if extra_class:
        cls = f'bi {extra_class}'

    parts = [f'<svg class="{cls}"']
    if other_attrs:
        parts.append(f' {other_attrs}')
    parts.append(' aria-hidden="true" focusable="false">')
    parts.append(f'<use href="#bi-{icon_name}"/>')
    parts.append('</svg>')
    return ''.join(parts)


def replace_alpine(match) -> str:
    extra_class  = match.group(1).strip()         # classes after "bi" in static class attr
    alpine_expr  = match.group(2).strip()         # the :class expression body
    other_attrs  = match.group(3).strip()

    # Apply substitutions inside the Alpine.js expression string
    alpine_expr = apply_substitutions(alpine_expr)

    # Convert 'bi-xxx' → '#bi-xxx' inside the Alpine expression
    href_expr = re.sub(r"'bi-([a-z0-9-]+)'", r"'#bi-\1'", alpine_expr)
    # Also handle double-quoted variants:
    href_expr = re.sub(r'"bi-([a-z0-9-]+)"', r'"#bi-\1"', href_expr)

    cls = 'bi'
    if extra_class:
        cls = f'bi {extra_class}'

    parts = [f'<svg class="{cls}"']
    if other_attrs:
        parts.append(f' {other_attrs}')
    parts.append(' aria-hidden="true" focusable="false">')
    parts.append(f'<use :href="{href_expr}"></use>')
    parts.append('</svg>')
    return ''.join(parts)


def process_file(file_path: str) -> bool:
    with open(file_path, 'r', encoding='utf-8') as fh:
        original = fh.read()

    content = original

    # Apply Alpine pattern first (it's more specific)
    content = ALPINE_ICON_RE.sub(replace_alpine, content)

    # Apply standard pattern
    content = BI_ICON_RE.sub(replace_standard, content)

    # Ensure the icons-sprite template include is NOT processed itself
    if 'icons-sprite' in file_path:
        return False

    if content != original:
        with open(file_path, 'w', encoding='utf-8') as fh:
            fh.write(content)
        return True
    return False


def main():
    changed = []
    skipped = []

    for root, _, files in os.walk(TEMPLATES_DIR):
        for fname in files:
            if not fname.endswith('.html'):
                continue
            full_path = os.path.join(root, fname)
            if 'icons-sprite' in fname:
                continue
            try:
                if process_file(full_path):
                    rel = os.path.relpath(full_path, os.path.dirname(__file__))
                    changed.append(rel)
            except Exception as exc:
                print(f'ERROR processing {full_path}: {exc}', file=sys.stderr)

    print(f'\n✅ {len(changed)} template(s) updated:')
    for path in sorted(changed):
        print(f'    {path}')

    if skipped:
        print(f'\n⚠️  {len(skipped)} file(s) skipped:')
        for path in skipped:
            print(f'    {path}')

    # Sanity check: any remaining <i class="bi bi- patterns?
    remaining = []
    for root, _, files in os.walk(TEMPLATES_DIR):
        for fname in files:
            if not fname.endswith('.html'):
                continue
            fp = os.path.join(root, fname)
            if 'icons-sprite' in fname:
                continue
            with open(fp, 'r', encoding='utf-8') as fh:
                txt = fh.read()
            if re.search(r'<i\s+class="bi\s+bi-', txt):
                remaining.append(os.path.relpath(fp, os.path.dirname(__file__)))

    if remaining:
        print(f'\n⚠️  Files still containing <i class="bi bi-> (manual review needed):')
        for path in remaining:
            print(f'    {path}')
    else:
        print('\n✅  No remaining <i class="bi bi-> tags found.')


if __name__ == '__main__':
    main()
