"""
Gemini Reporting Service
ORM-based reporting queries over GeminiGenerationAttempt and GeminiModelConsumption.
All reports are computed live — no summary tables.
Daily token totals are computed via SQL SUM (no separate daily aggregation model).
"""
import logging
from datetime import timedelta
from typing import Dict, List, Optional

from django.db import models
from django.db.models.functions import TruncDate, TruncHour
from django.utils import timezone

from apps.media_manager.models import GeminiGenerationAttempt, GeminiModelConsumption

logger = logging.getLogger(__name__)


class GeminiReportingService:

    def total_calls_by_model(self, days: int = 30) -> List[Dict]:
        since = timezone.now() - timedelta(days=days)
        qs = GeminiGenerationAttempt.objects.filter(created_at__gte=since)
        results = list(
            qs.values('resolved_model_key')
            .annotate(total_calls=models.Count('id'))
            .order_by('-total_calls')
        )
        for r in results:
            r['model_key'] = r.pop('resolved_model_key')
        return results

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
        results = list(
            qs.values('requested_model_key', 'resolved_model_key')
            .annotate(count=models.Count('id'))
        )
        for r in results:
            r['requested_model'] = r.pop('requested_model_key')
            r['resolved_model'] = r.pop('resolved_model_key')
        return results

    def daily_volume(self, days: int = 30) -> List[Dict]:
        since = timezone.now() - timedelta(days=days)
        qs = GeminiGenerationAttempt.objects.filter(created_at__gte=since)
        return list(
            qs.annotate(date=TruncDate('created_at'))
            .values('date')
            .annotate(
                total_calls=models.Count('id'),
                success_count=models.Sum(
                    models.Case(models.When(status='success', then=1), default=0)
                ),
                failure_count=models.Sum(
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
        results = list(
            qs.values('resolved_model_key')
            .annotate(
                avg_response_time_ms=models.Avg('response_time_ms'),
                max_response_ms=models.Max('response_time_ms'),
                min_response_ms=models.Min('response_time_ms'),
                total_calls=models.Count('id'),
            )
            .order_by('resolved_model_key')
        )
        for r in results:
            r['model_key'] = r.pop('resolved_model_key')
        return results

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

    def daily_token_usage(self, days=30):
        """Return daily token consumption per model via SQL aggregation."""
        return list(
            GeminiModelConsumption.objects.filter(
                date__gte=timezone.now() - timedelta(days=days)
            ).values('model_key', 'date').annotate(
                tokens__sum=models.Sum('tokens_consumed'),
                requests__sum=models.Sum('requests_consumed'),
            ).order_by('-date')
        )

    def minute_token_usage(self, model_key, date):
        """Return per-minute token consumption for a model on a given date."""
        return GeminiModelConsumption.objects.filter(
            model_key=model_key,
            date=date,
        ).values('minute_slot', 'tokens_consumed', 'requests_consumed'
        ).order_by('minute_slot')

    def summary_stats(self, days: int = 30) -> Dict:
        since = timezone.now() - timedelta(days=days)
        qs = GeminiGenerationAttempt.objects.filter(created_at__gte=since)
        agg = qs.aggregate(
            total_calls=models.Count('id'),
            success_count=models.Sum(
                models.Case(models.When(status='success', then=1), default=0)
            ),
            failure_count=models.Sum(
                models.Case(models.When(status='failure', then=1), default=0)
            ),
            blocked=models.Sum(
                models.Case(models.When(status='blocked', then=1), default=0)
            ),
            timed_out=models.Sum(
                models.Case(models.When(status='timeout', then=1), default=0)
            ),
            avg_response_time_ms=models.Avg(
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
            (agg['success_count'] or 0) / total * 100, 1
        ) if total > 0 else 0.0
        return agg


# Singleton
_reporting_service = None


def get_gemini_reporting_service() -> GeminiReportingService:
    global _reporting_service
    if _reporting_service is None:
        _reporting_service = GeminiReportingService()
    return _reporting_service
