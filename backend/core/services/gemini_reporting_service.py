"""
Gemini Reporting Service
ORM-based reporting queries over GeminiGenerationAttempt.
All reports are computed live — no summary tables.
"""
import logging
from datetime import timedelta
from typing import Dict, List, Optional

from django.db import models
from django.db.models.functions import TruncDate, TruncHour
from django.utils import timezone

from apps.media_manager.models import GeminiGenerationAttempt

logger = logging.getLogger(__name__)


class GeminiReportingService:

    def total_calls_by_model(self, days: int = 30) -> List[Dict]:
        since = timezone.now() - timedelta(days=days)
        qs = GeminiGenerationAttempt.objects.filter(created_at__gte=since)
        return list(
            qs.values('resolved_model_key')
            .annotate(total=models.Count('id'))
            .order_by('-total')
        )

    def status_counts_by_model(self, days: int = 30) -> List[Dict]:
        since = timezone.now() - timedelta(days=days)
        qs = GeminiGenerationAttempt.objects.filter(created_at__gte=since)
        return list(
            qs.values('resolved_model_key', 'status')
            .annotate(count=models.Count('id'))
            .order_by('resolved_model_key', 'status')
        )

    def fallback_usage(self, days: int = 30) -> List[Dict]:
        since = timezone.now() - timedelta(days=days)
        qs = GeminiGenerationAttempt.objects.filter(
            created_at__gte=since,
            resolved_model_key__isnull=False,
        ).exclude(
            requested_model_key=models.F('resolved_model_key')
        )
        return list(
            qs.values('requested_model_key', 'resolved_model_key')
            .annotate(count=models.Count('id'))
        )

    def daily_volume(self, days: int = 30) -> List[Dict]:
        since = timezone.now() - timedelta(days=days)
        qs = GeminiGenerationAttempt.objects.filter(created_at__gte=since)
        return list(
            qs.annotate(date=TruncDate('created_at'))
            .values('date')
            .annotate(
                total=models.Count('id'),
                succeeded=models.Sum(
                    models.Case(models.When(status='success', then=1), default=0)
                ),
                failed=models.Sum(
                    models.Case(models.When(status='failure', then=1), default=0)
                ),
                blocked=models.Sum(
                    models.Case(models.When(status='blocked', then=1), default=0)
                ),
                timed_out=models.Sum(
                    models.Case(models.When(status='timeout', then=1), default=0)
                ),
            )
            .order_by('-date')
        )

    def hourly_volume(self, days: int = 7) -> List[Dict]:
        since = timezone.now() - timedelta(days=days)
        qs = GeminiGenerationAttempt.objects.filter(created_at__gte=since)
        return list(
            qs.annotate(hour=TruncHour('created_at'))
            .values('hour')
            .annotate(
                total=models.Count('id'),
                succeeded=models.Sum(
                    models.Case(models.When(status='success', then=1), default=0)
                ),
                failed=models.Sum(
                    models.Case(models.When(status='failure', then=1), default=0)
                ),
            )
            .order_by('-hour')
        )

    def avg_response_time_by_model(self, days: int = 30) -> List[Dict]:
        since = timezone.now() - timedelta(days=days)
        qs = GeminiGenerationAttempt.objects.filter(
            status='success', created_at__gte=since
        )
        return list(
            qs.values('resolved_model_key')
            .annotate(
                avg_response_ms=models.Avg('response_time_ms'),
                max_response_ms=models.Max('response_time_ms'),
                min_response_ms=models.Min('response_time_ms'),
                total_calls=models.Count('id'),
            )
            .order_by('resolved_model_key')
        )

    def per_item_history(self, content_item_id: str) -> List[Dict]:
        return list(
            GeminiGenerationAttempt.objects.filter(
                content_item_id=content_item_id
            ).values(
                'created_at', 'operation_type', 'status',
                'requested_model_key', 'resolved_model_key',
                'response_time_ms', 'error_message',
            ).order_by('-created_at')
        )

    def summary_stats(self, days: int = 30) -> Dict:
        since = timezone.now() - timedelta(days=days)
        qs = GeminiGenerationAttempt.objects.filter(created_at__gte=since)
        agg = qs.aggregate(
            total_calls=models.Count('id'),
            succeeded=models.Sum(
                models.Case(models.When(status='success', then=1), default=0)
            ),
            failed=models.Sum(
                models.Case(models.When(status='failure', then=1), default=0)
            ),
            blocked=models.Sum(
                models.Case(models.When(status='blocked', then=1), default=0)
            ),
            timed_out=models.Sum(
                models.Case(models.When(status='timeout', then=1), default=0)
            ),
            avg_response_ms=models.Avg(
                'response_time_ms',
                filter=models.Q(status='success'),
            ),
            total_fallback=models.Count(
                'id',
                filter=(
                    models.Q(resolved_model_key__isnull=False) &
                    ~models.Q(requested_model_key=models.F('resolved_model_key'))
                ),
            ),
        )
        total = agg['total_calls'] or 0
        agg['success_rate'] = round(
            (agg['succeeded'] or 0) / total * 100, 1
        ) if total > 0 else 0.0
        return agg


# Singleton
_reporting_service = None


def get_gemini_reporting_service() -> GeminiReportingService:
    global _reporting_service
    if _reporting_service is None:
        _reporting_service = GeminiReportingService()
    return _reporting_service
