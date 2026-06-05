"""
System Monitor & File Manager — shared helpers.

Used by:
  - The custom admin dashboard (frontend_api.admin_views) at /en/dashboard/system/
  - The Django default admin site views at /admin/system/ (legacy)

Public API (imported by admin_views.py):
  - ALLOWED_BASES
  - resolve_safe_path(base_key, rel_path) -> Path | None
  - fmt_bytes(n) -> str
  - get_system_stats() -> dict        (CPU, RAM, disk, volumes)
  - get_database_stats() -> dict      (PostgreSQL info)
  - get_redis_stats() -> dict         (Redis info + keyspace)
  - get_media_counts() -> dict        (ContentItem counts)
  - list_directory(base_key, rel_path) -> dict   (entries + crumbs)
  - execute_file_action(action, base_key, rel_path, **kwargs) -> dict
  - scan_orphaned_files() -> dict
  - delete_orphan(rel_path) -> dict
  - get_cache_stats() -> dict
  - execute_cache_action(action, pattern=None) -> dict
"""

import json
import logging
import os
import shutil
import time
from pathlib import Path

import psutil
from django.conf import settings
from django.contrib.admin.views.decorators import staff_member_required
from django.core.cache import cache
from django.db import connection
from django.http import JsonResponse
from django.shortcuts import render
from django.utils.decorators import method_decorator
from django.views import View

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────
# ALLOWED BASE DIRECTORIES (restrict all file ops to these paths)
# ──────────────────────────────────────────────────────────────────
_MEDIA_ROOT = Path(settings.MEDIA_ROOT).resolve()
_STATIC_ROOT = Path(getattr(settings, "STATIC_ROOT", settings.BASE_DIR / "staticfiles")).resolve()
_LOGS_ROOT = Path(settings.BASE_DIR / "logs").resolve()

ALLOWED_BASES = {
    "media": _MEDIA_ROOT,
    "static": _STATIC_ROOT,
    "logs": _LOGS_ROOT,
}


# ──────────────────────────────────────────────────────────────────
# MODULE-LEVEL PUBLIC HELPERS  (imported by admin_views.py)
# ──────────────────────────────────────────────────────────────────

def resolve_safe_path(base_key: str, rel_path: str) -> "Path | None":
    """Public alias – safe path resolver."""
    return _resolve_safe_path(base_key, rel_path)


def fmt_bytes(n: int) -> str:
    """Human-readable byte size."""
    return _fmt_bytes(n)


def get_system_stats() -> dict:
    """Return CPU, RAM, disk(/), and per-volume stats."""
    return {
        "cpu": _cpu_stats(),
        "memory": _memory_stats(),
        "disk": _disk_stats(),
        "volumes": _volume_stats(),
    }


def get_database_stats() -> dict:
    """Return PostgreSQL size, top tables, connection count."""
    return _database_stats()


def get_redis_stats() -> dict:
    """Return Redis INFO dict or {error: ...}."""
    return _redis_stats()


def get_media_counts() -> dict:
    """Return ContentItem / meta counts from the DB."""
    return _media_counts()


def list_directory(base_key: str, rel_path: str) -> dict:
    """
    List a directory inside *base_key*.
    Returns {entries, crumbs, current_path, is_root, error?}.
    """
    if base_key not in ALLOWED_BASES:
        base_key = "media"
    target = _resolve_safe_path(base_key, rel_path)
    if target is None or not target.exists():
        target = ALLOWED_BASES[base_key]
        rel_path = ""

    entries = []
    error = None
    if target.is_dir():
        try:
            for entry in sorted(target.iterdir(), key=lambda e: (not e.is_dir(), e.name.lower())):
                stat = entry.stat(follow_symlinks=False)
                entries.append({
                    "name": entry.name,
                    "is_dir": entry.is_dir(),
                    "size": _fmt_bytes(stat.st_size) if entry.is_file() else "",
                    "size_bytes": stat.st_size if entry.is_file() else 0,
                    "modified": time.strftime("%Y-%m-%d %H:%M", time.localtime(stat.st_mtime)),
                    "rel_path": str((Path(rel_path) / entry.name) if rel_path else Path(entry.name)).replace("\\", "/"),
                })
        except PermissionError as exc:
            error = str(exc)

    crumbs = [{"label": base_key, "path": ""}]
    parts = Path(rel_path).parts if rel_path else []
    for i, part in enumerate(parts):
        crumbs.append({"label": part, "path": "/".join(parts[: i + 1])})

    return {
        "entries": entries,
        "crumbs": crumbs,
        "current_path": str(target),
        "is_root": rel_path == "",
        "error": error,
    }


def execute_file_action(action: str, base_key: str, rel_path: str, **kwargs) -> dict:
    """
    Execute a single file operation.
    actions: mkdir | delete | rename | move
    Returns {"ok": bool, "message": str, "error": str (on failure)}
    """
    if base_key not in ALLOWED_BASES:
        return {"ok": False, "error": "Invalid base directory"}

    if action == "mkdir":
        return _fm_mkdir(base_key, rel_path, kwargs.get("name", ""))
    if action == "delete":
        return _fm_delete(base_key, rel_path)
    if action == "rename":
        return _fm_rename(base_key, rel_path, kwargs.get("new_name", ""))
    if action == "move":
        return _fm_move(base_key, rel_path, kwargs.get("dest_path", ""))
    return {"ok": False, "error": f"Unknown action: {action}"}


def scan_orphaned_files() -> dict:
    """
    Walk MEDIA_ROOT and find files not referenced by any DB FileField.
    Returns {orphans, orphan_count, orphan_size, total_files, elapsed}.
    """
    return _scan_orphans()


def delete_orphan(rel_path: str) -> dict:
    """Delete a single file from MEDIA_ROOT by rel_path. Returns {ok, message|error}."""
    target = _resolve_safe_path("media", rel_path)
    if target is None or not target.exists():
        return {"ok": False, "error": "File not found"}
    try:
        target.unlink()
        return {"ok": True, "message": f"Deleted {target.name}"}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def get_cache_stats() -> dict:
    """Return Redis INFO structured for the cache manager page."""
    return _cache_stats()


def execute_cache_action(action: str, pattern: str = None) -> dict:
    """
    clear_all  — flush entire cache
    clear_pattern — delete keys matching *pattern*
    """
    if action == "clear_all":
        try:
            cache.clear()
            return {"ok": True, "message": "All cache cleared"}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}
    if action == "clear_pattern":
        if not pattern:
            return {"ok": False, "error": "Pattern required"}
        try:
            client = cache.client.get_client()
            keys = client.keys(f"*{pattern}*")
            if keys:
                client.delete(*keys)
            return {"ok": True, "message": f"Deleted {len(keys)} keys matching '{pattern}'"}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}
    return {"ok": False, "error": f"Unknown action: {action}"}


# ──────────────────────────────────────────────────────────────────
# PRIVATE IMPLEMENTATION HELPERS
# ──────────────────────────────────────────────────────────────────

def _resolve_safe_path(base_key: str, rel_path: str) -> "Path | None":
    """
    Resolve *rel_path* inside *base_key* directory and return the real path
    only if it stays within the allowed base. Returns None on traversal attempt.
    """
    base = ALLOWED_BASES.get(base_key)
    if base is None:
        return None
    # Join and resolve
    try:
        target = (base / rel_path.lstrip("/")).resolve()
    except Exception:
        return None
    # Guard against path traversal
    try:
        target.relative_to(base)
    except ValueError:
        return None
    return target


def _dir_size(path: Path) -> int:
    """Return total byte size of a directory tree (best-effort)."""
    total = 0
    try:
        for entry in os.scandir(path):
            try:
                if entry.is_dir(follow_symlinks=False):
                    total += _dir_size(Path(entry.path))
                else:
                    total += entry.stat(follow_symlinks=False).st_size
            except OSError:
                pass
    except PermissionError:
        pass
    return total


def _fmt_bytes(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} PB"


# ──────────────────────────────────────────────────────────────────
# MODULE-LEVEL STAT HELPERS  (called by public API above)
# ──────────────────────────────────────────────────────────────────

def _cpu_stats() -> dict:
    try:
        percent = psutil.cpu_percent(interval=0.5)
        count = psutil.cpu_count()
        load = os.getloadavg() if hasattr(os, "getloadavg") else (0, 0, 0)
        return {"percent": percent, "count": count, "load": list(load)}
    except Exception as exc:
        return {"error": str(exc)}


def _memory_stats() -> dict:
    try:
        vm = psutil.virtual_memory()
        return {
            "total_bytes": vm.total,
            "used_bytes": vm.used,
            "available_bytes": vm.available,
            "percent": vm.percent,
        }
    except Exception as exc:
        return {"error": str(exc)}


def _disk_stats() -> dict:
    """Disk stats for the root / (or C:\ on Windows)."""
    try:
        path = "/" if os.name != "nt" else "C:\\"
        usage = psutil.disk_usage(path)
        return {
            "total_bytes": usage.total,
            "used_bytes": usage.used,
            "free_bytes": usage.free,
            "percent": usage.percent,
        }
    except Exception as exc:
        return {"error": str(exc)}


def _volume_stats() -> list:
    rows = []
    for name, path in ALLOWED_BASES.items():
        row: dict = {"name": name, "path": str(path), "exists": path.exists()}
        if path.exists():
            try:
                usage = psutil.disk_usage(str(path))
                row["disk_total_bytes"] = usage.total
                row["disk_used_bytes"] = usage.used
                row["disk_free_bytes"] = usage.free
                row["disk_percent"] = usage.percent
            except Exception:
                pass
            row["size_bytes"] = _dir_size(path)
            try:
                row["file_count"] = sum(1 for _ in path.rglob("*") if _.is_file())
            except Exception:
                row["file_count"] = "?"
        rows.append(row)
    return rows


def _database_stats() -> dict:
    try:
        with connection.cursor() as cur:
            cur.execute(
                "SELECT pg_database_size(current_database()), current_database()"
            )
            row = cur.fetchone()
            cur.execute(
                "SELECT schemaname, tablename, "
                "pg_total_relation_size(schemaname||'.'||tablename) "
                "FROM pg_tables WHERE schemaname NOT IN ('pg_catalog','information_schema') "
                "ORDER BY 3 DESC LIMIT 10"
            )
            tables = []
            for schema_name, table_name, size_bytes in cur.fetchall():
                tables.append({
                    "schema": schema_name,
                    "table": table_name,
                    "label": table_name if schema_name == "public" else f"{schema_name}.{table_name}",
                    "size_bytes": size_bytes,
                })
            cur.execute(
                "SELECT count(*) FROM pg_stat_activity WHERE datname = current_database()"
            )
            conn_count = cur.fetchone()[0]
        return {"size_bytes": row[0], "name": row[1], "tables": tables, "connections": conn_count}
    except Exception as exc:
        logger.warning("DB stats failed: %s", exc)
        return {"error": str(exc)}


def _redis_stats() -> dict:
    try:
        client = cache.client.get_client()
        info = client.info()
        return {
            "used_memory_bytes": info.get("used_memory", 0),
            "used_memory_peak_bytes": info.get("used_memory_peak", 0),
            "connected_clients": info.get("connected_clients", 0),
            "total_commands_processed": info.get("total_commands_processed", 0),
            "keyspace_hits": info.get("keyspace_hits", 0),
            "keyspace_misses": info.get("keyspace_misses", 0),
            "uptime_in_seconds": info.get("uptime_in_seconds", 0),
            "redis_version": info.get("redis_version", "?"),
            "total_keys": sum(
                v.get("keys", 0) if isinstance(v, dict) else 0
                for k, v in info.items()
                if k.startswith("db")
            ),
        }
    except Exception as exc:
        logger.warning("Redis stats failed: %s", exc)
        return {"error": str(exc)}


def _media_counts() -> dict:
    try:
        from apps.media_manager.models import AudioMeta, ContentItem, PdfMeta, VideoMeta

        return {
            "content_items": ContentItem.objects.count(),
            "active_items": ContentItem.objects.filter(is_active=True).count(),
            "videos": VideoMeta.objects.count(),
            "audios": AudioMeta.objects.count(),
            "pdfs": PdfMeta.objects.count(),
        }
    except Exception as exc:
        logger.warning("Media counts failed: %s", exc)
        return {"error": str(exc)}


def _scan_orphans() -> dict:
    """
    Walk MEDIA_ROOT and find files not referenced by any FileField in the DB.
    """
    from apps.media_manager.models import AudioMeta, ContentItem, PdfMeta, VideoMeta

    t0 = time.time()
    # Collect all known file names (relative to MEDIA_ROOT)
    known: set[str] = set()
    try:
        for field_val in ContentItem.objects.values_list("thumbnail", flat=True):
            if field_val:
                known.add(field_val)
        for field_val in ContentItem.objects.values_list("supplementary_document", flat=True):
            if field_val:
                known.add(field_val)
        for field_val in VideoMeta.objects.values_list("original_file", flat=True):
            if field_val:
                known.add(field_val)
        for field_val in AudioMeta.objects.values_list("original_file", flat=True):
            if field_val:
                known.add(field_val)
        for field_val in AudioMeta.objects.values_list("compressed_file", flat=True):
            if field_val:
                known.add(field_val)
        for field_val in PdfMeta.objects.values_list("original_file", flat=True):
            if field_val:
                known.add(field_val)
    except Exception as exc:
        logger.warning("Orphan scan DB query failed: %s", exc)

    # Normalise known paths
    known_norm = {str(Path(k)).replace("\\", "/") for k in known}

    orphans = []
    total_files = 0
    orphan_size = 0
    skip_dirs = {"chunked_uploads"}  # staging area — not real orphans

    media_root = _MEDIA_ROOT
    if not media_root.exists():
        return {"orphans": [], "orphan_count": 0, "orphan_size": "0 B", "total_files": 0, "elapsed": 0}

    for fpath in media_root.rglob("*"):
        if not fpath.is_file():
            continue
        if any(part in skip_dirs for part in fpath.parts):
            continue
        total_files += 1
        try:
            rel = str(fpath.relative_to(media_root)).replace("\\", "/")
        except ValueError:
            continue
        if rel not in known_norm:
            sz = fpath.stat().st_size
            orphan_size += sz
            orphans.append({
                "name": fpath.name,
                "rel_path": rel,
                "size": _fmt_bytes(sz),
                "size_bytes": sz,
                "modified": time.strftime("%Y-%m-%d %H:%M", time.localtime(fpath.stat().st_mtime)),
            })

    return {
        "orphans": sorted(orphans, key=lambda x: -x["size_bytes"]),
        "orphan_count": len(orphans),
        "orphan_size": _fmt_bytes(orphan_size),
        "total_files": total_files,
        "elapsed": round(time.time() - t0, 2),
    }


def _cache_stats() -> dict:
    try:
        client = cache.client.get_client()
        info = client.info()
        keys_raw = client.keys("*")
        return {
            "used_memory_bytes": info.get("used_memory", 0),
            "used_memory_peak_bytes": info.get("used_memory_peak", 0),
            "total_keys": len(keys_raw),
            "connected_clients": info.get("connected_clients", 0),
            "keyspace_hits": info.get("keyspace_hits", 0),
            "keyspace_misses": info.get("keyspace_misses", 0),
            "redis_version": info.get("redis_version", "?"),
            "uptime_in_seconds": info.get("uptime_in_seconds", 0),
        }
    except Exception as exc:
        logger.warning("Cache stats failed: %s", exc)
        return {"error": str(exc)}


# ── File operation helpers (module-level) ─────────────────────────

def _fm_mkdir(base_key: str, rel_path: str, name: str) -> dict:
    name = (name or "").strip()
    if not name or "/" in name or "\\" in name or name in (".", ".."):
        return {"ok": False, "error": "Invalid directory name"}
    parent = _resolve_safe_path(base_key, rel_path)
    if parent is None or not parent.is_dir():
        return {"ok": False, "error": "Parent path not found"}
    new_dir = parent / name
    if new_dir.exists():
        return {"ok": False, "error": "Already exists"}
    try:
        new_dir.mkdir(parents=False)
        return {"ok": True, "message": f"Directory '{name}' created"}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def _fm_delete(base_key: str, rel_path: str) -> dict:
    if not rel_path:
        return {"ok": False, "error": "Cannot delete root"}
    target = _resolve_safe_path(base_key, rel_path)
    if target is None or not target.exists():
        return {"ok": False, "error": "Path not found"}
    try:
        if target.is_dir():
            shutil.rmtree(target)
        else:
            target.unlink()
        return {"ok": True, "message": f"'{target.name}' deleted"}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def _fm_rename(base_key: str, rel_path: str, new_name: str) -> dict:
    if not rel_path:
        return {"ok": False, "error": "Cannot rename root"}
    new_name = (new_name or "").strip()
    if not new_name or "/" in new_name or "\\" in new_name or new_name in (".", ".."):
        return {"ok": False, "error": "Invalid new name"}
    target = _resolve_safe_path(base_key, rel_path)
    if target is None or not target.exists():
        return {"ok": False, "error": "Path not found"}
    dest = target.parent / new_name
    if dest.exists():
        return {"ok": False, "error": "Name already taken"}
    try:
        target.rename(dest)
        return {"ok": True, "message": f"Renamed to '{new_name}'"}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def _fm_move(base_key: str, rel_path: str, dest_path: str) -> dict:
    if not rel_path:
        return {"ok": False, "error": "Cannot move root"}
    dest_rel = (dest_path or "").strip()
    if not dest_rel:
        return {"ok": False, "error": "Destination path required"}
    source = _resolve_safe_path(base_key, rel_path)
    dest_dir = _resolve_safe_path(base_key, dest_rel)
    if source is None or not source.exists():
        return {"ok": False, "error": "Source not found"}
    if dest_dir is None or not dest_dir.is_dir():
        return {"ok": False, "error": "Destination not a valid directory"}
    dest = dest_dir / source.name
    if dest.exists():
        return {"ok": False, "error": "Name already exists in destination"}
    try:
        dest_dir.relative_to(source)
        return {"ok": False, "error": "Cannot move directory into itself"}
    except ValueError:
        pass
    try:
        shutil.move(str(source), str(dest))
        return {"ok": True, "message": f"Moved '{source.name}' to '{dest_rel}'"}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


# ──────────────────────────────────────────────────────────────────
# SYSTEM DASHBOARD (Django admin CBVs — legacy)
# ──────────────────────────────────────────────────────────────────

@method_decorator(staff_member_required, name="dispatch")
class SystemDashboardView(View):
    template_name = "admin_django/system_dashboard.html"

    def get(self, request):
        ctx = {
            "title": "System Monitor",
            "cpu": self._cpu(),
            "memory": self._memory(),
            "disk": self._disk(),
            "volumes": self._volumes(),
            "database": self._database(),
            "redis_info": self._redis(),
            "media_counts": self._media_counts(),
        }
        return render(request, self.template_name, ctx)

    # ── helpers ──────────────────────────────────────────────────

    def _cpu(self) -> dict:
        try:
            percent = psutil.cpu_percent(interval=0.5)
            count = psutil.cpu_count()
            load = os.getloadavg() if hasattr(os, "getloadavg") else (0, 0, 0)
            return {"percent": percent, "count": count, "load": load}
        except Exception as exc:
            logger.warning("CPU stats failed: %s", exc)
            return {"error": str(exc)}

    def _memory(self) -> dict:
        try:
            vm = psutil.virtual_memory()
            return {
                "total": _fmt_bytes(vm.total),
                "used": _fmt_bytes(vm.used),
                "available": _fmt_bytes(vm.available),
                "percent": vm.percent,
            }
        except Exception as exc:
            return {"error": str(exc)}

    def _disk(self) -> dict:
        try:
            usage = psutil.disk_usage("/")
            return {
                "total": _fmt_bytes(usage.total),
                "used": _fmt_bytes(usage.used),
                "free": _fmt_bytes(usage.free),
                "percent": usage.percent,
            }
        except Exception as exc:
            return {"error": str(exc)}

    def _volumes(self) -> list[dict]:
        rows = []
        for name, path in ALLOWED_BASES.items():
            row: dict = {"name": name, "path": str(path), "exists": path.exists()}
            if path.exists():
                try:
                    usage = psutil.disk_usage(str(path))
                    row["disk_total"] = _fmt_bytes(usage.total)
                    row["disk_used"] = _fmt_bytes(usage.used)
                    row["disk_free"] = _fmt_bytes(usage.free)
                    row["disk_percent"] = usage.percent
                except Exception:
                    pass
                row["size"] = _fmt_bytes(_dir_size(path))
                # Count files
                try:
                    row["file_count"] = sum(1 for _ in path.rglob("*") if _.is_file())
                except Exception:
                    row["file_count"] = "?"
            rows.append(row)
        return rows

    def _database(self) -> dict:
        try:
            with connection.cursor() as cur:
                cur.execute(
                    "SELECT pg_size_pretty(pg_database_size(current_database())) AS size, "
                    "current_database() AS name"
                )
                row = cur.fetchone()
                cur.execute(
                    "SELECT schemaname, tablename, "
                    "pg_size_pretty(pg_total_relation_size(schemaname||'.'||tablename)) AS size, "
                    "pg_total_relation_size(schemaname||'.'||tablename) AS raw_size "
                    "FROM pg_tables WHERE schemaname NOT IN ('pg_catalog','information_schema') "
                    "ORDER BY raw_size DESC LIMIT 10"
                )
                tables = [
                    {"schema": r[0], "table": r[1], "size": r[2]} for r in cur.fetchall()
                ]
                # Connection count
                cur.execute(
                    "SELECT count(*) FROM pg_stat_activity WHERE datname = current_database()"
                )
                conn_count = cur.fetchone()[0]
            return {
                "size": row[0],
                "name": row[1],
                "tables": tables,
                "connections": conn_count,
            }
        except Exception as exc:
            logger.warning("DB stats failed: %s", exc)
            return {"error": str(exc)}

    def _redis(self) -> dict:
        try:
            client = cache.client.get_client()  # django-redis
            info = client.info()
            return {
                "used_memory": _fmt_bytes(info.get("used_memory", 0)),
                "used_memory_peak": _fmt_bytes(info.get("used_memory_peak", 0)),
                "connected_clients": info.get("connected_clients", 0),
                "total_commands_processed": info.get("total_commands_processed", 0),
                "keyspace_hits": info.get("keyspace_hits", 0),
                "keyspace_misses": info.get("keyspace_misses", 0),
                "uptime_in_seconds": info.get("uptime_in_seconds", 0),
                "redis_version": info.get("redis_version", "?"),
                "total_keys": sum(
                    v.get("keys", 0) if isinstance(v, dict) else 0
                    for k, v in info.items()
                    if k.startswith("db")
                ),
            }
        except Exception as exc:
            logger.warning("Redis stats failed: %s", exc)
            return {"error": str(exc)}

    def _media_counts(self) -> dict:
        try:
            from apps.media_manager.models import ContentItem, VideoMeta, AudioMeta, PdfMeta

            return {
                "content_items": ContentItem.objects.count(),
                "active_items": ContentItem.objects.filter(is_active=True).count(),
                "videos": VideoMeta.objects.count(),
                "audios": AudioMeta.objects.count(),
                "pdfs": PdfMeta.objects.count(),
                "pending_processing": ContentItem.objects.filter(
                    processing_status="pending"
                ).count(),
                "failed_processing": ContentItem.objects.filter(
                    processing_status="failed"
                ).count(),
            }
        except Exception as exc:
            logger.warning("Media counts failed: %s", exc)
            return {"error": str(exc)}


# ──────────────────────────────────────────────────────────────────
# FILE MANAGER
# ──────────────────────────────────────────────────────────────────

@method_decorator(staff_member_required, name="dispatch")
class FileManagerView(View):
    template_name = "admin_django/file_manager.html"

    def get(self, request):
        base_key = request.GET.get("base", "media")
        rel_path = request.GET.get("path", "")

        if base_key not in ALLOWED_BASES:
            base_key = "media"

        target = _resolve_safe_path(base_key, rel_path)
        if target is None or not target.exists():
            target = ALLOWED_BASES[base_key]
            rel_path = ""

        entries = []
        if target.is_dir():
            try:
                for entry in sorted(target.iterdir(), key=lambda e: (not e.is_dir(), e.name.lower())):
                    stat = entry.stat(follow_symlinks=False)
                    entries.append(
                        {
                            "name": entry.name,
                            "is_dir": entry.is_dir(),
                            "size": _fmt_bytes(stat.st_size) if entry.is_file() else "",
                            "size_bytes": stat.st_size if entry.is_file() else 0,
                            "modified": time.strftime(
                                "%Y-%m-%d %H:%M", time.localtime(stat.st_mtime)
                            ),
                            "rel_path": str(
                                (Path(rel_path) / entry.name)
                                if rel_path
                                else Path(entry.name)
                            ).replace("\\", "/"),
                        }
                    )
            except PermissionError as exc:
                logger.warning("Cannot list %s: %s", target, exc)

        # Build breadcrumbs
        crumbs = [{"label": base_key, "path": ""}]
        parts = Path(rel_path).parts if rel_path else []
        for i, part in enumerate(parts):
            crumbs.append(
                {
                    "label": part,
                    "path": "/".join(parts[: i + 1]),
                }
            )

        ctx = {
            "title": "File Manager",
            "base_key": base_key,
            "rel_path": rel_path,
            "entries": entries,
            "crumbs": crumbs,
            "bases": list(ALLOWED_BASES.keys()),
            "current_path": str(target),
            "is_root": rel_path == "",
        }
        return render(request, self.template_name, ctx)


@method_decorator(staff_member_required, name="dispatch")
class FileManagerActionView(View):
    """AJAX endpoint for all file operations. Returns JSON."""

    def post(self, request):
        try:
            data = json.loads(request.body)
        except Exception:
            return JsonResponse({"ok": False, "error": "Invalid JSON body"}, status=400)

        action = data.get("action", "")
        base_key = data.get("base", "media")
        rel_path = data.get("path", "")

        if base_key not in ALLOWED_BASES:
            return JsonResponse({"ok": False, "error": "Invalid base directory"}, status=400)

        dispatch = {
            "mkdir": self._mkdir,
            "delete": self._delete,
            "rename": self._rename,
            "move": self._move,
        }
        handler = dispatch.get(action)
        if handler is None:
            return JsonResponse({"ok": False, "error": f"Unknown action: {action}"}, status=400)

        return handler(data, base_key, rel_path)

    # ── action handlers ──────────────────────────────────────────

    def _mkdir(self, data, base_key, rel_path):
        name = (data.get("name") or "").strip()
        if not name or "/" in name or "\\" in name or name in (".", ".."):
            return JsonResponse({"ok": False, "error": "Invalid directory name"}, status=400)
        parent = _resolve_safe_path(base_key, rel_path)
        if parent is None or not parent.is_dir():
            return JsonResponse({"ok": False, "error": "Parent path not found"}, status=404)
        new_dir = parent / name
        if new_dir.exists():
            return JsonResponse({"ok": False, "error": "Already exists"}, status=409)
        try:
            new_dir.mkdir(parents=False)
            return JsonResponse({"ok": True, "message": f"Directory '{name}' created"})
        except Exception as exc:
            return JsonResponse({"ok": False, "error": str(exc)}, status=500)

    def _delete(self, data, base_key, rel_path):
        if not rel_path:
            return JsonResponse({"ok": False, "error": "Cannot delete root"}, status=400)
        target = _resolve_safe_path(base_key, rel_path)
        if target is None or not target.exists():
            return JsonResponse({"ok": False, "error": "Path not found"}, status=404)
        try:
            if target.is_dir():
                shutil.rmtree(target)
            else:
                target.unlink()
            return JsonResponse({"ok": True, "message": f"'{target.name}' deleted"})
        except Exception as exc:
            return JsonResponse({"ok": False, "error": str(exc)}, status=500)

    def _rename(self, data, base_key, rel_path):
        if not rel_path:
            return JsonResponse({"ok": False, "error": "Cannot rename root"}, status=400)
        new_name = (data.get("new_name") or "").strip()
        if not new_name or "/" in new_name or "\\" in new_name or new_name in (".", ".."):
            return JsonResponse({"ok": False, "error": "Invalid new name"}, status=400)
        target = _resolve_safe_path(base_key, rel_path)
        if target is None or not target.exists():
            return JsonResponse({"ok": False, "error": "Path not found"}, status=404)
        dest = target.parent / new_name
        if dest.exists():
            return JsonResponse({"ok": False, "error": "Name already taken"}, status=409)
        try:
            target.rename(dest)
            return JsonResponse({"ok": True, "message": f"Renamed to '{new_name}'"})
        except Exception as exc:
            return JsonResponse({"ok": False, "error": str(exc)}, status=500)

    def _move(self, data, base_key, rel_path):
        if not rel_path:
            return JsonResponse({"ok": False, "error": "Cannot move root"}, status=400)
        dest_rel = (data.get("dest_path") or "").strip()
        if not dest_rel:
            return JsonResponse({"ok": False, "error": "Destination path required"}, status=400)
        source = _resolve_safe_path(base_key, rel_path)
        dest_dir = _resolve_safe_path(base_key, dest_rel)
        if source is None or not source.exists():
            return JsonResponse({"ok": False, "error": "Source not found"}, status=404)
        if dest_dir is None or not dest_dir.is_dir():
            return JsonResponse({"ok": False, "error": "Destination not a valid directory"}, status=400)
        dest = dest_dir / source.name
        if dest.exists():
            return JsonResponse({"ok": False, "error": "A file with that name already exists in destination"}, status=409)
        # Prevent moving a dir into itself
        try:
            dest_dir.relative_to(source)
            return JsonResponse({"ok": False, "error": "Cannot move directory into itself"}, status=400)
        except ValueError:
            pass
        try:
            shutil.move(str(source), str(dest))
            return JsonResponse({"ok": True, "message": f"Moved '{source.name}' to '{dest_rel}'"})
        except Exception as exc:
            return JsonResponse({"ok": False, "error": str(exc)}, status=500)


# ──────────────────────────────────────────────────────────────────
# ORPHANED FILES
# ──────────────────────────────────────────────────────────────────

@method_decorator(staff_member_required, name="dispatch")
class OrphanedFilesView(View):
    template_name = "admin_django/orphaned_files.html"

    def get(self, request):
        scan = request.GET.get("scan") == "1"
        result = self._find_orphans() if scan else None
        ctx = {
            "title": "Orphaned Files",
            "result": result,
            "scanned": scan,
        }
        return render(request, self.template_name, ctx)

    def post(self, request):
        """Delete a single orphan. Expects JSON body with {path: 'rel_path'}."""
        try:
            data = json.loads(request.body)
        except Exception:
            return JsonResponse({"ok": False, "error": "Invalid JSON"}, status=400)
        rel = (data.get("path") or "").strip()
        if not rel:
            return JsonResponse({"ok": False, "error": "Path required"}, status=400)
        target = _resolve_safe_path("media", rel)
        if target is None or not target.exists():
            return JsonResponse({"ok": False, "error": "File not found"}, status=404)
        try:
            target.unlink()
            return JsonResponse({"ok": True, "message": f"Deleted {target.name}"})
        except Exception as exc:
            return JsonResponse({"ok": False, "error": str(exc)}, status=500)

    def _find_orphans(self) -> dict:
        """
        Collect all file-field values from DB, then walk MEDIA_ROOT and find
        files not referenced by any DB record.
        """
        from apps.media_manager.models import ContentItem, VideoMeta, AudioMeta, PdfMeta

        start = time.monotonic()
        db_paths: set[str] = set()

        def _add(qs, *fields):
            for obj in qs.values(*fields):
                for f in fields:
                    val = obj.get(f) or ""
                    if val:
                        # Normalize to forward slashes
                        db_paths.add(val.replace("\\", "/"))

        _add(ContentItem.objects.all(), "thumbnail", "supplementary_document")
        _add(VideoMeta.objects.all(), "original_file")
        _add(AudioMeta.objects.all(), "original_file", "compressed_file")
        _add(PdfMeta.objects.all(), "original_file")

        orphans = []
        total_size = 0
        total_files = 0
        base = _MEDIA_ROOT

        for root, dirs, files in os.walk(base):
            # Skip chunked upload staging dirs
            dirs[:] = [d for d in dirs if d != "chunked_uploads"]
            for fname in files:
                total_files += 1
                abs_path = Path(root) / fname
                try:
                    rel = abs_path.relative_to(base).as_posix()
                except ValueError:
                    continue
                if rel not in db_paths:
                    try:
                        size = abs_path.stat().st_size
                    except OSError:
                        size = 0
                    total_size += size
                    orphans.append(
                        {
                            "rel_path": rel,
                            "name": fname,
                            "size": _fmt_bytes(size),
                            "size_bytes": size,
                        }
                    )

        elapsed = time.monotonic() - start
        return {
            "orphans": orphans,
            "orphan_count": len(orphans),
            "orphan_size": _fmt_bytes(total_size),
            "total_files": total_files,
            "elapsed": f"{elapsed:.2f}s",
        }


# ──────────────────────────────────────────────────────────────────
# CACHE MANAGER
# ──────────────────────────────────────────────────────────────────

@method_decorator(staff_member_required, name="dispatch")
class CacheManagerView(View):
    template_name = "admin_django/cache_manager.html"

    def get(self, request):
        ctx = {
            "title": "Cache Manager",
            "redis_info": self._redis_info(),
            "cache_backend": str(
                settings.CACHES.get("default", {}).get("BACKEND", "?")
            ),
        }
        return render(request, self.template_name, ctx)

    def post(self, request):
        """AJAX: clear all cache or specific pattern."""
        try:
            data = json.loads(request.body)
        except Exception:
            return JsonResponse({"ok": False, "error": "Invalid JSON"}, status=400)

        action = data.get("action", "")
        if action == "clear_all":
            try:
                cache.clear()
                return JsonResponse({"ok": True, "message": "All cache cleared"})
            except Exception as exc:
                return JsonResponse({"ok": False, "error": str(exc)}, status=500)

        if action == "clear_pattern":
            pattern = (data.get("pattern") or "").strip()
            if not pattern:
                return JsonResponse({"ok": False, "error": "Pattern required"}, status=400)
            try:
                client = cache.client.get_client()
                keys = client.keys(f"*{pattern}*")
                if keys:
                    client.delete(*keys)
                return JsonResponse(
                    {"ok": True, "message": f"Deleted {len(keys)} keys matching '{pattern}'"}
                )
            except Exception as exc:
                return JsonResponse({"ok": False, "error": str(exc)}, status=500)

        return JsonResponse({"ok": False, "error": f"Unknown action: {action}"}, status=400)

    def _redis_info(self) -> dict:
        try:
            client = cache.client.get_client()
            info = client.info()
            keyspace = {k: v for k, v in info.items() if k.startswith("db")}
            total_keys = sum(
                v.get("keys", 0) if isinstance(v, dict) else 0
                for v in keyspace.values()
            )
            return {
                "version": info.get("redis_version", "?"),
                "used_memory": _fmt_bytes(info.get("used_memory", 0)),
                "used_memory_peak": _fmt_bytes(info.get("used_memory_peak", 0)),
                "maxmemory": _fmt_bytes(info.get("maxmemory", 0)),
                "connected_clients": info.get("connected_clients", 0),
                "keyspace_hits": info.get("keyspace_hits", 0),
                "keyspace_misses": info.get("keyspace_misses", 0),
                "total_keys": total_keys,
                "keyspace": keyspace,
                "uptime_days": info.get("uptime_in_days", 0),
                "evicted_keys": info.get("evicted_keys", 0),
                "mem_fragmentation_ratio": info.get("mem_fragmentation_ratio", 0),
            }
        except Exception as exc:
            logger.warning("Redis info failed: %s", exc)
            return {"error": str(exc)}
