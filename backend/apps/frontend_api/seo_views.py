# SEO Analytics and Monitoring Views
# Add to apps/frontend_api/views.py or create new apps/seo_dashboard/views.py

from django.shortcuts import render
from django.contrib.admin.views.decorators import staff_member_required
from django.http import JsonResponse
from django.db.models import Count, Q, Avg, Max, Min
from django.utils.decorators import method_decorator
from django.views.generic import TemplateView
from apps.media_manager.models import ContentItem, Tag
from collections import Counter
import json


@method_decorator(staff_member_required, name='dispatch')
class SEODashboardView(TemplateView):
    """SEO Analytics Dashboard for Administrators"""
    template_name = 'admin/seo_dashboard.html'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        # Basic SEO coverage statistics
        total_content = ContentItem.objects.filter(is_active=True).count()
        seo_complete = ContentItem.objects.filter(
            is_active=True
        ).exclude(
            Q(seo_keywords_ar__isnull=True) | Q(seo_keywords_ar=''),
            Q(seo_keywords_en__isnull=True) | Q(seo_keywords_en=''),
            Q(seo_meta_description_ar='') | Q(seo_meta_description_ar__isnull=True),
            Q(seo_meta_description_en='') | Q(seo_meta_description_en__isnull=True)
        ).count()
        
        context.update({
            'total_content': total_content,
            'seo_complete': seo_complete,
            'seo_coverage_percent': round((seo_complete / total_content * 100) if total_content > 0 else 0, 1),
            'seo_pending': total_content - seo_complete,
        })
        
        # Content type breakdown
        content_types = ContentItem.objects.filter(is_active=True).values('content_type').annotate(
            total=Count('id'),
            seo_ready=Count('id', filter=~Q(seo_keywords_ar__isnull=True) & ~Q(seo_keywords_ar=''))
        )
        context['content_types'] = list(content_types)
        
        # Recent SEO updates
        recent_seo_updates = ContentItem.objects.filter(
            is_active=True
        ).exclude(
            Q(seo_keywords_ar__isnull=True) | Q(seo_keywords_ar='')
        ).order_by('-updated_at')[:10]
        context['recent_seo_updates'] = recent_seo_updates
        
        return context


@staff_member_required
def seo_analytics_api(request):
    """API endpoint for SEO analytics data (AJAX/Charts)"""
    
    # Top keywords analysis
    all_keywords_ar = []
    all_keywords_en = []
    
    for item in ContentItem.objects.filter(is_active=True).exclude(Q(seo_keywords_ar__isnull=True) | Q(seo_keywords_ar='')):
        if item.seo_keywords_ar:
            all_keywords_ar.extend([k.strip() for k in item.seo_keywords_ar.split(',') if k.strip()])
        if item.seo_keywords_en:
            all_keywords_en.extend([k.strip() for k in item.seo_keywords_en.split(',') if k.strip()])
    
    top_keywords_ar = Counter(all_keywords_ar).most_common(20)
    top_keywords_en = Counter(all_keywords_en).most_common(20)
    
    # SEO quality metrics - calculate manually since __len not supported on TextField
    active_content = ContentItem.objects.filter(is_active=True)
    total_keywords_ar = sum(len([k.strip() for k in item.seo_keywords_ar.split(',') if k.strip()]) 
                           for item in active_content if item.seo_keywords_ar)
    total_keywords_en = sum(len([k.strip() for k in item.seo_keywords_en.split(',') if k.strip()]) 
                           for item in active_content if item.seo_keywords_en)
    content_count = active_content.count()
    
    quality_metrics = {
        'avg_keywords_ar': round(total_keywords_ar / content_count, 2) if content_count > 0 else 0,
        'avg_keywords_en': round(total_keywords_en / content_count, 2) if content_count > 0 else 0,
        'max_keywords_ar': max([len([k.strip() for k in item.seo_keywords_ar.split(',') if k.strip()]) 
                               for item in active_content if item.seo_keywords_ar], default=0),
        'max_keywords_en': max([len([k.strip() for k in item.seo_keywords_en.split(',') if k.strip()]) 
                               for item in active_content if item.seo_keywords_en], default=0),
    }
    
    # Content with missing SEO by type
    missing_seo_by_type = {}
    for content_type in ['video', 'audio', 'pdf']:
        missing_count = ContentItem.objects.filter(
            is_active=True,
            content_type=content_type
        ).filter(
            Q(seo_keywords_ar__isnull=True) | Q(seo_keywords_ar='')
        ).count()
        missing_seo_by_type[content_type] = missing_count
    
    # Meta description quality analysis
    meta_desc_quality = ContentItem.objects.filter(is_active=True).aggregate(
        total_with_meta_ar=Count('id', filter=Q(seo_meta_description_ar__isnull=False) & ~Q(seo_meta_description_ar='')),
        total_with_meta_en=Count('id', filter=Q(seo_meta_description_en__isnull=False) & ~Q(seo_meta_description_en='')),
    )
    
    return JsonResponse({
        'top_keywords': {
            'arabic': top_keywords_ar,
            'english': top_keywords_en
        },
        'quality_metrics': quality_metrics,
        'missing_seo_by_type': missing_seo_by_type,
        'meta_description_coverage': meta_desc_quality,
        'structured_data_coverage': ContentItem.objects.filter(
            is_active=True,
            structured_data__isnull=False
        ).exclude(structured_data={}).count()
    })


@staff_member_required
def seo_content_analysis_api(request):
    """Detailed content analysis for SEO optimization"""
    
    content_analysis = []
    
    # Analyze each content item for SEO completeness
    for item in ContentItem.objects.filter(is_active=True).select_related(
        'videometa', 'audiometa', 'pdfmeta'
    ):
        analysis = {
            'id': str(item.id),
            'title': item.get_title(),
            'content_type': item.content_type,
            'seo_score': 0,
            'issues': [],
            'suggestions': []
        }
        
        # Calculate SEO score (0-100)
        score = 0
        
        # Keywords (30 points)
        if item.seo_keywords_ar:
            score += min(len(item.seo_keywords_ar) * 2, 15)  # Max 15 points for Arabic keywords
        else:
            analysis['issues'].append('Missing Arabic keywords')
            analysis['suggestions'].append('Generate Arabic SEO keywords using Gemini AI')
        
        if item.seo_keywords_en:
            score += min(len(item.seo_keywords_en) * 2, 15)  # Max 15 points for English keywords
        else:
            analysis['issues'].append('Missing English keywords')
            analysis['suggestions'].append('Generate English SEO keywords using Gemini AI')
        
        # Meta descriptions (20 points)
        if item.seo_meta_description_ar:
            score += 10
            if len(item.seo_meta_description_ar) > 160:
                analysis['issues'].append('Arabic meta description too long')
        else:
            analysis['issues'].append('Missing Arabic meta description')
        
        if item.seo_meta_description_en:
            score += 10
            if len(item.seo_meta_description_en) > 160:
                analysis['issues'].append('English meta description too long')
        else:
            analysis['issues'].append('Missing English meta description')
        
        # Structured data (20 points)
        if item.structured_data:
            score += 20
            # Validate structured data completeness
            required_fields = ['@context', '@type', 'name', 'description']
            missing_fields = [f for f in required_fields if f not in item.structured_data]
            if missing_fields:
                analysis['issues'].append(f'Structured data missing: {", ".join(missing_fields)}')
        else:
            analysis['issues'].append('Missing structured data')
            analysis['suggestions'].append('Generate JSON-LD structured data')
        
        # Title optimization (15 points)
        if item.seo_title_suggestions:
            score += 15
        else:
            analysis['issues'].append('No alternative SEO titles')
            analysis['suggestions'].append('Generate alternative SEO titles')
        
        # Content quality (15 points)
        if item.title_ar and item.title_en:
            score += 7.5
        if item.description_ar and item.description_en:
            score += 7.5
        
        analysis['seo_score'] = min(int(score), 100)
        
        # Priority recommendations
        if analysis['seo_score'] < 50:
            analysis['priority'] = 'high'
        elif analysis['seo_score'] < 75:
            analysis['priority'] = 'medium'
        else:
            analysis['priority'] = 'low'
        
        content_analysis.append(analysis)
    
    # Sort by priority and score
    content_analysis.sort(key=lambda x: (
        x['priority'] == 'high',
        x['priority'] == 'medium',
        -x['seo_score']
    ), reverse=True)
    
    return JsonResponse({
        'content_analysis': content_analysis[:50],  # Limit to top 50 items
        'summary': {
            'total_analyzed': len(content_analysis),
            'high_priority': len([x for x in content_analysis if x['priority'] == 'high']),
            'medium_priority': len([x for x in content_analysis if x['priority'] == 'medium']),
            'avg_seo_score': sum(x['seo_score'] for x in content_analysis) / len(content_analysis) if content_analysis else 0
        }
    })


@staff_member_required
def bulk_seo_actions_api(request):
    """API for bulk SEO operations"""
    if request.method != 'POST':
        return JsonResponse({'error': 'POST required'}, status=405)
    
    action = request.POST.get('action')
    content_ids = request.POST.getlist('content_ids')
    
    if not action or not content_ids:
        return JsonResponse({'error': 'Missing action or content_ids'}, status=400)
    
    results = {'success': 0, 'failed': 0, 'messages': []}
    
    if action == 'generate_seo':
        # Queue SEO generation for selected items
        from apps.media_manager.tasks import generate_seo_metadata_task
        
        for content_id in content_ids:
            try:
                item = ContentItem.objects.get(id=content_id, is_active=True)
                generate_seo_metadata_task.delay(content_id)
                results['success'] += 1
            except ContentItem.DoesNotExist:
                results['failed'] += 1
                results['messages'].append(f'Content {content_id} not found')
            except Exception as e:
                results['failed'] += 1
                results['messages'].append(f'Error queuing {content_id}: {str(e)}')
        
        results['messages'].append(f'Queued SEO generation for {results["success"]} items')
    
    elif action == 'clear_seo':
        # Clear SEO metadata for selected items
        updated = ContentItem.objects.filter(
            id__in=content_ids,
            is_active=True
        ).update(
            seo_keywords_ar=[],
            seo_keywords_en=[],
            seo_meta_description_ar='',
            seo_meta_description_en='',
            seo_title_suggestions=[],
            structured_data={}
        )
        results['success'] = updated
        results['messages'].append(f'Cleared SEO metadata for {updated} items')
    
    else:
        return JsonResponse({'error': 'Invalid action'}, status=400)
    
    return JsonResponse(results)