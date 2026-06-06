"""
Scored Model Selection Strategy
Implements scoring-based model selection with hard-constraint filtering.
"""
import logging
from typing import List, Optional, Tuple

from apps.media_manager.models import GeminiModelSetting
from .gemini_rate_limit_service import ModelSelectionStrategy, get_gemini_rate_limit_service

logger = logging.getLogger(__name__)


class ScoredModelSelectionStrategy(ModelSelectionStrategy):
    def __init__(self):
        self.rate_limit_service = get_gemini_rate_limit_service()

    def select_model(self, preferred_model, estimated_tokens=0, **context):
        selected, _ = self.select_with_candidates(preferred_model, estimated_tokens, **context)
        return selected

    def select_with_candidates(self, preferred_model, estimated_tokens=0, **context) -> Tuple[str, List[str]]:
        candidates = self._get_candidates(preferred_model, estimated_tokens)
        if not candidates:
            fallback = GeminiModelSetting.objects.filter(
                is_enabled=True, archived_at__isnull=True
            ).order_by('fallback_priority').first()
            if fallback:
                return fallback.model_key, []
            return preferred_model, []

        scored = [(model, self._compute_score(model, estimated_tokens, context)) for model in candidates]
        scored.sort(key=lambda x: x[1], reverse=True)
        selected = scored[0][0]
        fallback_candidates = [m.model_key for m, _ in scored[1:]]
        return selected.model_key, fallback_candidates

    def get_fallback(self, current_model, estimated_tokens=0, **context) -> Optional[str]:
        selected, candidates = self.select_with_candidates(current_model, estimated_tokens, **context)
        if selected != current_model:
            return selected
        if candidates:
            return candidates[0]
        return None

    def _get_candidates(self, preferred_model, estimated_tokens) -> List[GeminiModelSetting]:
        rate_info = None
        try:
            rate_info = self.rate_limit_service.get_rate_limit_info(preferred_model)
        except Exception:
            pass

        if rate_info and self._is_model_eligible(rate_info, preferred_model, estimated_tokens):
            model = GeminiModelSetting.objects.filter(
                model_key=preferred_model, is_enabled=True, archived_at__isnull=True
            ).first()
            if model:
                return [model] + list(self._get_other_enabled_models(preferred_model))

        all_enabled = self._get_other_enabled_models(preferred_model, include_all=True)
        eligible = []
        for setting in all_enabled:
            try:
                info = self.rate_limit_service.get_rate_limit_info(setting.model_key)
                if self._is_model_eligible(info, setting.model_key, estimated_tokens):
                    eligible.append(setting)
            except Exception:
                eligible.append(setting)
        return eligible

    def _get_other_enabled_models(self, exclude_model=None, include_all=False) -> List[GeminiModelSetting]:
        qs = GeminiModelSetting.objects.filter(
            is_enabled=True, archived_at__isnull=True
        ).order_by('fallback_priority', 'model_key')
        if include_all:
            return list(qs)
        return list(qs.exclude(model_key=exclude_model) if exclude_model else qs)

    def _is_model_eligible(self, rate_info, model_key, estimated_tokens) -> bool:
        if rate_info['remaining_requests_minute'] < 1:
            return False
        if rate_info['remaining_requests_day'] < 1:
            return False
        if rate_info['tokens_per_minute'] is not None and estimated_tokens > 0:
            if rate_info['remaining_tokens_minute'] < estimated_tokens:
                return False
        if rate_info['tokens_per_day'] is not None and estimated_tokens > 0:
            if rate_info['remaining_tokens_day'] < estimated_tokens:
                return False
        if rate_info['max_input_tokens'] and estimated_tokens > rate_info['max_input_tokens']:
            return False
        return True

    def _compute_score(self, model: GeminiModelSetting, estimated_tokens: int, context: dict) -> float:
        priority_weight = -float(model.fallback_priority)
        load_penalty = self._load_penalty(model)
        availability_bonus = self._availability_bonus(model)
        return priority_weight - load_penalty + availability_bonus

    def _load_penalty(self, model: GeminiModelSetting) -> float:
        try:
            info = self.rate_limit_service.get_rate_limit_info(model.model_key)
        except Exception:
            return 0.0

        penalties = []
        if info['limit_per_minute'] > 0:
            rpm_usage = info['used_requests_minute'] / max(info['limit_per_minute'], 1)
            penalties.append(rpm_usage)
        if info['tokens_per_minute'] and info['tokens_per_minute'] > 0 and info['used_tokens_minute'] > 0:
            tpm_usage = info['used_tokens_minute'] / info['tokens_per_minute']
            penalties.append(tpm_usage)

        if penalties:
            cost = sum(penalties) / len(penalties)
            return cost * 5.0
        return 0.0

    def _availability_bonus(self, model: GeminiModelSetting) -> float:
        try:
            info = self.rate_limit_service.get_rate_limit_info(model.model_key)
        except Exception:
            return 0.0

        bonus = 0.0
        if info['limit_per_minute'] > 0:
            remaining_ratio = info['remaining_requests_minute'] / max(info['limit_per_minute'], 1)
            if remaining_ratio > 0.5:
                bonus += 2.0
            elif remaining_ratio > 0.25:
                bonus += 1.0
        if info['tokens_per_minute'] and info['tokens_per_minute'] > 0:
            remaining_tokens_ratio = info['remaining_tokens_minute'] / max(info['tokens_per_minute'], 1)
            if remaining_tokens_ratio > 0.5:
                bonus += 1.0
        return bonus
