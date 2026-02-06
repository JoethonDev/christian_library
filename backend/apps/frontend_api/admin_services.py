"""
Admin Service Layer for Frontend API
Optimized administrative operations with zero N+1 queries.
"""
from typing import Dict, List, Optional, Tuple, Any
from django.db.models import QuerySet, Q, Count
from django.db import models
from django.core.paginator import Paginator
from django.utils.translation import get_language
from django.conf import settings
import os
import shutil
from pathlib import Path

from apps.media_manager.models import ContentItem, VideoMeta, AudioMeta, PdfMeta, Tag
from apps.frontend_api.services import ContentLanguageProcessor


from apps.core.task_monitor import TaskMonitor
from core.services.gemini_manager import get_gemini_manager


class AdminService:
    """Service for administrative operations with optimized queries"""
    
    def __init__(self):
        self.language_processor = ContentLanguageProcessor()
        self.gemini_manager = get_gemini_manager()
    
    def get_dashboard_data(self) -> Dict[str, Any]:
        """Get admin dashboard data with minimal queries (3-4 total) + task monitoring"""
        # Query 1: Get comprehensive statistics
        content_stats = ContentItem.objects.get_statistics()
        
        # Query 2: Get tag count
        tag_count = Tag.objects.active().count()
        
        # Query 3: Get recent content with all relations
        recent_content = ContentItem.objects.select_related(
            'videometa', 'audiometa', 'pdfmeta'
        ).prefetch_related('tags').order_by('-created_at')[:10]
        
        # Query 4: Get processing videos count
        processing_videos = VideoMeta.objects.filter(
            processing_status__in=['pending', 'processing', 'queued']
        ).count()
        
        # Query 5: Get PDF indexing statistics
        from django.db.models import Sum
        pdf_stats = ContentItem.objects.filter(
            content_type='pdf', is_active=True
        ).aggregate(
            total_pdfs=Count('id'),
            indexed_pdfs=Count('id', filter=~Q(book_content__isnull=True) & ~Q(book_content='')),
            total_indexed_chars=Sum(
                models.functions.Length('book_content'),
                filter=~Q(book_content__isnull=True) & ~Q(book_content='')
            ) or 0
        )
        
        # Process recent content in memory
        current_language = get_language()
        processed_recent = self.language_processor.process_content_list(
            recent_content, current_language
        )
        
        # Combine statistics
        stats = {
            **content_stats,
            'total_tags': tag_count,
            'processing_videos': processing_videos,
            **pdf_stats
        }
        
        # Add task monitoring data
        task_data = self._get_live_task_data()
        
        # Add Gemini rate limit data
        gemini_rate_limits = self._get_gemini_rate_limits()
        
        return {
            'stats': stats,
            'recent_content': processed_recent,
            'processing_videos': processing_videos,
            'current_language': current_language,
            **task_data,
            **gemini_rate_limits,
        }
    
    def _get_live_task_data(self) -> Dict[str, Any]:
        """Get real-time task monitoring data (not cached)"""
        try:
            task_stats = TaskMonitor.get_task_stats()
            active_tasks = TaskMonitor.get_active_tasks()
            
            return {
                'task_stats': task_stats,
                'active_tasks': active_tasks[:10],  # Latest 10 tasks
                'has_tasks': len(active_tasks) > 0,
            }
        except Exception as e:
            import logging
            logging.getLogger(__name__).error(f"Error getting task data: {e}")
            return {
                'task_stats': {},
                'active_tasks': [],
                'has_tasks': False,
            }
    
    def _get_gemini_rate_limits(self) -> Dict[str, Any]:
        """Get Gemini rate limit information for all models"""
        try:
            rate_limits = self.gemini_manager.get_rate_limit_status()
            
            return {
                'gemini_rate_limits': rate_limits,
                'gemini_metadata_available': self.gemini_manager.check_metadata_availability()[0],
                'gemini_seo_available': self.gemini_manager.check_seo_availability()[0],
            }
        except Exception as e:
            import logging
            logging.getLogger(__name__).error(f"Failed to get Gemini rate limits: {e}")
            return {
                'gemini_rate_limits': {},
                'gemini_metadata_available': False,
                'gemini_seo_available': False,
            }
    
    def get_content_list(
        self,
        content_type: str = '',
        search_query: str = '',
        page: int = 1,
        per_page: int = 20,
        language: str = None
    ) -> Dict[str, Any]:
        """Get paginated content list for admin with optimized queries (1-2 total)"""
        if not language:
            language = get_language()
        
        # Single optimized query with all relations
        content_qs = ContentItem.objects.select_related(
            'videometa', 'audiometa', 'pdfmeta'
        ).prefetch_related('tags').order_by('-created_at')
        
        # Apply filters
        if content_type:
            content_qs = content_qs.filter(content_type=content_type)
        
        if search_query:
            search_conditions = (
                Q(title_ar__icontains=search_query) |
                Q(title_en__icontains=search_query) |
                Q(description_ar__icontains=search_query) |
                Q(description_en__icontains=search_query)
            )
            content_qs = content_qs.filter(search_conditions)
        
        # Pagination
        paginator = Paginator(content_qs, per_page)
        content_page = paginator.get_page(page)
        
        # Process content items in memory
        processed_content = self.language_processor.process_content_list(
            content_page, language
        )
        
        # Attach live task data if processing
        try:
            active_tasks = TaskMonitor.get_active_tasks()
            task_map = {str(t['metadata'].get('content_id')): t for t in active_tasks if 'metadata' in t and t['metadata']}
            for item in processed_content:
                if item.processing_status == 'processing':
                    item.live_task = task_map.get(str(item.id))
        except Exception as e:
            pass
        
        return {
            'content_items': processed_content,
            'pagination': {
                'page': content_page,
                'total_count': paginator.count,
                'num_pages': paginator.num_pages,
                'has_previous': content_page.has_previous(),
                'has_next': content_page.has_next(),
                'has_pagination': paginator.num_pages > 1,
                'previous_page_number': content_page.previous_page_number() if content_page.has_previous() else None,
                'next_page_number': content_page.next_page_number() if content_page.has_next() else None,
            }
        }
    
    def get_content_detail(self, content_id: str) -> ContentItem:
        """Get single content item with all relations for admin editing"""
        from django.shortcuts import get_object_or_404
        
        return get_object_or_404(
            ContentItem.objects.select_related(
                'videometa', 'audiometa', 'pdfmeta'
            ).prefetch_related('tags'),
            id=content_id
        )
    
    def get_content_statistics_by_type(self) -> Dict[str, Any]:
        """Get detailed statistics by content type - single query"""
        # Get all stats with conditional aggregation
        stats = ContentItem.objects.aggregate(
            # Active content by type
            active_videos=Count('id', filter=Q(content_type='video', is_active=True)),
            active_audios=Count('id', filter=Q(content_type='audio', is_active=True)),
            active_pdfs=Count('id', filter=Q(content_type='pdf', is_active=True)),
            
            # Inactive content by type
            inactive_videos=Count('id', filter=Q(content_type='video', is_active=False)),
            inactive_audios=Count('id', filter=Q(content_type='audio', is_active=False)),
            inactive_pdfs=Count('id', filter=Q(content_type='pdf', is_active=False)),
            
            # Total counts
            total_videos=Count('id', filter=Q(content_type='video')),
            total_audios=Count('id', filter=Q(content_type='audio')),
            total_pdfs=Count('id', filter=Q(content_type='pdf')),
            total_content=Count('id'),
            total_active=Count('id', filter=Q(is_active=True)),
            total_inactive=Count('id', filter=Q(is_active=False))
        )
        
        return stats
    
    def get_type_specific_content(
        self, 
        content_type: str, 
        page: int = 1, 
        per_page: int = 20,
        filters: Dict[str, Any] = None
    ) -> Dict[str, Any]:
        """Get content for type-specific management pages"""
        if not filters:
            filters = {}
        
        # Optimized query based on content type
        if content_type == 'video':
            content_qs = ContentItem.objects.filter(
                content_type='video'
            ).select_related('videometa').prefetch_related('tags')
        elif content_type == 'audio':
            content_qs = ContentItem.objects.filter(
                content_type='audio'
            ).select_related('audiometa').prefetch_related('tags')
        elif content_type == 'pdf':
            content_qs = ContentItem.objects.filter(
                content_type='pdf'
            ).select_related('pdfmeta').prefetch_related('tags')
        else:
            raise ValueError(f"Invalid content type: {content_type}")
        
        # Apply additional filters
        if filters.get('status'):
            if filters['status'] == 'active':
                content_qs = content_qs.filter(is_active=True)
            elif filters['status'] == 'inactive':
                content_qs = content_qs.filter(is_active=False)
        
        if filters.get('search'):
            search_query = filters['search']
            search_mode = filters.get('search_mode', 'title')
            
            if content_type == 'pdf' and search_mode == 'content':
                # Search within PDF content using PostgreSQL FTS
                from django.contrib.postgres.search import SearchQuery, SearchRank
                from django.db import connection
                
                if 'postgresql' in connection.settings_dict['ENGINE']:
                    # Use PostgreSQL FTS with Arabic config
                    search_query_obj = SearchQuery(search_query, config='arabic')
                    content_qs = content_qs.filter(
                        search_vector__isnull=False
                    ).annotate(
                        rank=SearchRank(models.F('search_vector'), search_query_obj)
                    ).filter(
                        rank__gte=0.1
                    ).order_by('-rank')
                else:
                    # Fallback to simple content search
                    content_qs = content_qs.filter(book_content__icontains=search_query)
            else:
                # Search in titles and descriptions
                content_qs = content_qs.filter(
                    Q(title_ar__icontains=search_query) |
                    Q(title_en__icontains=search_query)
                )
        
        # Add processing status filter for videos
        if content_type == 'video' and filters.get('processing_status'):
            content_qs = content_qs.filter(
                videometa__processing_status=filters['processing_status']
            )
        
        # Add missing data filter
        if filters.get('missing_data'):
            missing_filter = filters['missing_data']
            if missing_filter == 'no_seo':
                # Match items where ALL SEO fields are missing (consistent with has_seo property)
                content_qs = content_qs.filter(
                    (Q(seo_keywords_ar__isnull=True) | Q(seo_keywords_ar='')) &
                    (Q(seo_keywords_en__isnull=True) | Q(seo_keywords_en='')) &
                    (Q(seo_meta_description_ar__isnull=True) | Q(seo_meta_description_ar='')) &
                    (Q(seo_meta_description_en__isnull=True) | Q(seo_meta_description_en=''))
                )
            elif missing_filter == 'no_metadata':
                # Filter based on content type - use annotation for tag count
                if content_type == 'video':
                    content_qs = content_qs.annotate(tag_count=Count('tags')).filter(
                        Q(videometa__duration_seconds__isnull=True) |
                        Q(description_ar__isnull=True) | Q(description_ar='') |
                        Q(tag_count=0)
                    )
                elif content_type == 'audio':
                    content_qs = content_qs.annotate(tag_count=Count('tags')).filter(
                        Q(audiometa__duration_seconds__isnull=True) |
                        Q(description_ar__isnull=True) | Q(description_ar='') |
                        Q(tag_count=0)
                    )
                elif content_type == 'pdf':
                    content_qs = content_qs.annotate(tag_count=Count('tags')).filter(
                        Q(pdfmeta__page_count__isnull=True) |
                        Q(description_ar__isnull=True) | Q(description_ar='') |
                        Q(tag_count=0)
                    )
        
        content_qs = content_qs.order_by('-created_at')
        
        # Pagination
        paginator = Paginator(content_qs, per_page)
        content_page = paginator.get_page(page)
        
        # Process content in memory
        current_language = get_language()
        processed_content = self.language_processor.process_content_list(
            content_page, current_language
        )
        
        # Attach live task data if processing
        try:
            active_tasks = TaskMonitor.get_active_tasks()
            task_map = {str(t['metadata'].get('content_id')): t for t in active_tasks if 'metadata' in t and t['metadata']}
            for item in processed_content:
                if item.processing_status == 'processing':
                    item.live_task = task_map.get(str(item.id))
        except Exception as e:
            pass
        
        return {
            'content_items': processed_content,
            'pagination': {
                'page': content_page,
                'total_count': paginator.count,
                'num_pages': paginator.num_pages,
                'has_previous': content_page.has_previous(),
                'has_next': content_page.has_next(),
            }
        }
    
    def get_bulk_operation_data(self) -> Dict[str, Any]:
        """Get data for bulk operations - optimized queries"""        
        # Get counts by status and type in single query
        bulk_stats = ContentItem.objects.aggregate(
            total_items=Count('id'),
            active_items=Count('id', filter=Q(is_active=True)),
            inactive_items=Count('id', filter=Q(is_active=False)),
            
            # Items without SEO metadata
            missing_seo_ar=Count('id', filter=Q(
                Q(seo_keywords_ar__isnull=True) | Q(seo_keywords_ar=''),
                is_active=True
            )),
            missing_seo_en=Count('id', filter=Q(
                Q(seo_keywords_en__isnull=True) | Q(seo_keywords_en=''),
                is_active=True
            )),
            
            # Items without tags
            untagged_items=Count('id', filter=Q(tags__isnull=True, is_active=True)),
            
            # Processing status for videos
            pending_processing=Count('id', filter=Q(
                content_type='video',
                videometa__processing_status='pending'
            )),
            failed_processing=Count('id', filter=Q(
                content_type='video', 
                videometa__processing_status='failed'
            ))
        )
        
        return bulk_stats
    
    def get_system_monitor_data(self) -> Dict[str, Any]:
        """Get system monitoring data with optimized queries + task monitoring"""        
        # Get processing status counts
        processing_stats = VideoMeta.objects.aggregate(
            pending_videos=Count('id', filter=Q(processing_status='pending')),
            processing_videos=Count('id', filter=Q(processing_status='processing')),
            completed_videos=Count('id', filter=Q(processing_status='completed')),
            failed_videos=Count('id', filter=Q(processing_status='failed'))
        )
        
        # Get content statistics
        content_stats = self.get_content_statistics_by_type()
        
        # Get recent activity (last 10 items)
        recent_activity = ContentItem.objects.select_related(
            'videometa', 'audiometa', 'pdfmeta'
        ).order_by('-updated_at')[:10]
        
        current_language = get_language()
        processed_activity = self.language_processor.process_content_list(
            recent_activity, current_language
        )
        
        # Get live task monitoring data
        task_data = self._get_live_task_data()
        
        # Get disk usage information
        disk_usage = self._get_disk_usage()
        
        # Get storage breakdown by type
        storage_breakdown = self._get_storage_breakdown()
        
        # Get R2 storage stats
        r2_enabled = getattr(settings, 'R2_ENABLED', False)
        r2_stats = self._get_r2_stats() if r2_enabled else {}
        
        return {
            'processing_stats': processing_stats,
            'content_stats': content_stats,
            'recent_activity': processed_activity,
            'task_monitor': task_data,
            'disk_usage': disk_usage,
            'storage_breakdown': storage_breakdown,
            'r2_enabled': r2_enabled,
            'r2_stats': r2_stats,
        }
    
    def _get_disk_usage(self) -> Dict[str, Any]:
        """Get disk usage statistics for media root"""
        try:
            media_root = settings.MEDIA_ROOT
            if not os.path.exists(media_root):
                return {
                    'total': 0,
                    'used': 0,
                    'free': 0,
                    'percentage': 0
                }
            
            # Get disk usage for the media root partition
            stat = shutil.disk_usage(media_root)
            
            return {
                'total': stat.total,
                'used': stat.used,
                'free': stat.free,
                'percentage': int((stat.used / stat.total) * 100) if stat.total > 0 else 0
            }
        except Exception as e:
            import logging
            logging.getLogger(__name__).error(f"Error getting disk usage: {e}")
            return {
                'total': 0,
                'used': 0,
                'free': 0,
                'percentage': 0
            }
    
    def _get_storage_breakdown(self) -> Dict[str, Any]:
        """Get storage breakdown by media type with file counts"""
        try:
            media_root = Path(settings.MEDIA_ROOT)
            
            breakdown = {
                'original': {'size': 0, 'count': 0},
                'hls': {'size': 0, 'count': 0},
                'optimized': {'size': 0, 'count': 0},
                'compressed': {'size': 0, 'count': 0},
            }
            
            # Calculate original files
            original_dirs = ['original/videos', 'original/audio', 'original/pdf']
            for dir_path in original_dirs:
                full_path = media_root / dir_path
                if full_path.exists():
                    size, count = self._get_directory_size_and_count(full_path)
                    breakdown['original']['size'] += size
                    breakdown['original']['count'] += count
            
            # Calculate HLS files
            hls_path = media_root / 'hls'
            if hls_path.exists():
                size, count = self._get_directory_size_and_count(hls_path)
                breakdown['hls']['size'] = size
                breakdown['hls']['count'] = count
            
            # Calculate optimized files
            optimized_dirs = ['optimized/pdf']
            for dir_path in optimized_dirs:
                full_path = media_root / dir_path
                if full_path.exists():
                    size, count = self._get_directory_size_and_count(full_path)
                    breakdown['optimized']['size'] += size
                    breakdown['optimized']['count'] += count
            
            # Calculate compressed files
            compressed_dirs = ['compressed/audio']
            for dir_path in compressed_dirs:
                full_path = media_root / dir_path
                if full_path.exists():
                    size, count = self._get_directory_size_and_count(full_path)
                    breakdown['compressed']['size'] += size
                    breakdown['compressed']['count'] += count
            
            return breakdown
            
        except Exception as e:
            import logging
            logging.getLogger(__name__).error(f"Error getting storage breakdown: {e}")
            return {
                'original': {'size': 0, 'count': 0},
                'hls': {'size': 0, 'count': 0},
                'optimized': {'size': 0, 'count': 0},
                'compressed': {'size': 0, 'count': 0},
            }
    
    def _get_directory_size_and_count(self, directory: Path) -> Tuple[int, int]:
        """Get total size and file count for a directory recursively"""
        total_size = 0
        file_count = 0
        
        try:
            for entry in directory.rglob('*'):
                if entry.is_file():
                    total_size += entry.stat().st_size
                    file_count += 1
        except Exception as e:
            import logging
            logging.getLogger(__name__).error(f"Error calculating directory size for {directory}: {e}")
        
        return total_size, file_count
    
    def _get_r2_stats(self) -> Dict[str, Any]:
        """Get R2 storage statistics including size and file count"""
        try:
            from core.services.r2_storage_service import get_r2_storage_service
            
            # Get R2 storage usage
            r2_service = get_r2_storage_service()
            usage_data = r2_service.get_bucket_usage(use_cache=True)
            
            # Get R2 upload status counts from database
            video_stats = VideoMeta.objects.aggregate(
                completed=Count('id', filter=Q(r2_upload_status='completed')),
                pending=Count('id', filter=Q(r2_upload_status='pending')),
                uploading=Count('id', filter=Q(r2_upload_status='uploading')),
                failed=Count('id', filter=Q(r2_upload_status='failed'))
            )
            
            audio_stats = AudioMeta.objects.aggregate(
                completed=Count('id', filter=Q(r2_upload_status='completed')),
                pending=Count('id', filter=Q(r2_upload_status='pending')),
                uploading=Count('id', filter=Q(r2_upload_status='uploading')),
                failed=Count('id', filter=Q(r2_upload_status='failed'))
            )
            
            pdf_stats = PdfMeta.objects.aggregate(
                completed=Count('id', filter=Q(r2_upload_status='completed')),
                pending=Count('id', filter=Q(r2_upload_status='pending')),
                uploading=Count('id', filter=Q(r2_upload_status='uploading')),
                failed=Count('id', filter=Q(r2_upload_status='failed'))
            )
            
            # Combine stats
            total_stats = {
                'completed': (video_stats['completed'] or 0) + (audio_stats['completed'] or 0) + (pdf_stats['completed'] or 0),
                'pending': (video_stats['pending'] or 0) + (audio_stats['pending'] or 0) + (pdf_stats['pending'] or 0),
                'uploading': (video_stats['uploading'] or 0) + (audio_stats['uploading'] or 0) + (pdf_stats['uploading'] or 0),
                'failed': (video_stats['failed'] or 0) + (audio_stats['failed'] or 0) + (pdf_stats['failed'] or 0),
            }
            
            return {
                'total': total_stats,
                'video': video_stats,
                'audio': audio_stats,
                'pdf': pdf_stats,
                'storage': usage_data,  # Contains total_size_gb, object_count, etc.
            }
            
        except Exception as e:
            import logging
            logging.getLogger(__name__).error(f"Error getting R2 stats: {e}")
            return {
                'total': {'completed': 0, 'pending': 0, 'uploading': 0, 'failed': 0},
                'storage': {'success': False, 'total_size_gb': 0, 'object_count': 0},
            }
    
    def toggle_content_status(self, content_id: str) -> Tuple[bool, str]:
        """Toggle content active status - single query"""        
        try:
            content = ContentItem.objects.select_related(
                'videometa', 'audiometa', 'pdfmeta'
            ).get(id=content_id)
            
            old_status = content.is_active
            target_status = not old_status
            
            # If activating, perform model-level validation (clean)
            if target_status:
                content.is_active = True
                try:
                    content.clean()
                except Exception as e:
                    # Capture validation error and prevent activation
                    error_msg = str(e)
                    # Strip standard Django ValidationError wrapping if present
                    if "['" in error_msg:
                         error_msg = error_msg.split("['")[1].split("']")[0]
                    return False, f"Validation failed: {error_msg}"
            else:
                content.is_active = False

            content.save(update_fields=['is_active', 'updated_at'])
            
            new_status = "active" if content.is_active else "inactive"
            return True, f"Content status changed to {new_status}"
            
        except ContentItem.DoesNotExist:
            return False, "Content not found"
        except Exception as e:
            return False, f"Error updating status: {str(e)}"
    
    def get_content_for_seo_dashboard(self) -> Dict[str, Any]:
        """Get content data for SEO dashboard - optimized queries"""        
        # Get SEO coverage statistics in single query
        seo_stats = ContentItem.objects.filter(is_active=True).aggregate(
            total_content=Count('id'),
            
            # Content with complete SEO metadata
            seo_complete_ar=Count('id', filter=~Q(
                Q(seo_keywords_ar__isnull=True) | Q(seo_keywords_ar='') |
                Q(seo_meta_description_ar='') | Q(seo_meta_description_ar__isnull=True)
            )),
            seo_complete_en=Count('id', filter=~Q(
                Q(seo_keywords_en__isnull=True) | Q(seo_keywords_en='') |
                Q(seo_meta_description_en='') | Q(seo_meta_description_en__isnull=True)
            )),
            
            # Content with any SEO metadata
            has_seo_ar=Count('id', filter=~Q(
                Q(seo_keywords_ar__isnull=True) | Q(seo_keywords_ar='')
            )),
            has_seo_en=Count('id', filter=~Q(
                Q(seo_keywords_en__isnull=True) | Q(seo_keywords_en='')
            )),
            
            # By content type
            videos_total=Count('id', filter=Q(content_type='video')),
            audios_total=Count('id', filter=Q(content_type='audio')),
            pdfs_total=Count('id', filter=Q(content_type='pdf')),
            
            videos_seo=Count('id', filter=Q(
                content_type='video',
                seo_keywords_ar__isnull=False
            ) & ~Q(seo_keywords_ar='')),
            audios_seo=Count('id', filter=Q(
                content_type='audio',
                seo_keywords_ar__isnull=False
            ) & ~Q(seo_keywords_ar='')),
            pdfs_seo=Count('id', filter=Q(
                content_type='pdf',
                seo_keywords_ar__isnull=False
            ) & ~Q(seo_keywords_ar=''))
        )
        
        # Calculate percentages
        total = seo_stats['total_content']
        if total > 0:
            seo_stats['seo_coverage_percent_ar'] = round((seo_stats['seo_complete_ar'] / total) * 100, 1)
            seo_stats['seo_coverage_percent_en'] = round((seo_stats['seo_complete_en'] / total) * 100, 1)
        else:
            seo_stats['seo_coverage_percent_ar'] = 0
            seo_stats['seo_coverage_percent_en'] = 0
        
        # Get recent SEO updates
        recent_seo_updates = ContentItem.objects.filter(
            is_active=True
        ).exclude(
            Q(seo_keywords_ar__isnull=True) | Q(seo_keywords_ar=''),
            Q(seo_keywords_en__isnull=True) | Q(seo_keywords_en='')
        ).select_related(
            'videometa', 'audiometa', 'pdfmeta'
        ).order_by('-updated_at')[:10]
        
        current_language = get_language()
        processed_updates = self.language_processor.process_content_list(
            recent_seo_updates, current_language
        )
        
        return {
            'seo_stats': seo_stats,
            'recent_seo_updates': processed_updates
        }