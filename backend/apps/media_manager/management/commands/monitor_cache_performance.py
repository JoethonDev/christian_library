"""
Management command to monitor and analyze Phase 4 cache performance.
Usage: python manage.py monitor_cache_performance
"""

from django.core.management.base import BaseCommand
from django.core.cache import caches
from core.utils.cache_utils import cache_invalidator
import json
from datetime import datetime


class Command(BaseCommand):
    help = 'Monitor Phase 4 cache performance and statistics'
    
    def add_arguments(self, parser):
        parser.add_argument(
            '--format',
            choices=['table', 'json'],
            default='table',
            help='Output format (default: table)'
        )
        
        parser.add_argument(
            '--clear',
            action='store_true',
            help='Clear all caches before monitoring'
        )
    
    def handle(self, *args, **options):
        """Monitor cache performance"""
        
        if options['clear']:
            self.stdout.write(self.style.WARNING('Clearing all caches...'))
            cache_invalidator.clear_all_caches()
            self.stdout.write(self.style.SUCCESS('All caches cleared'))
            return
        
        self.stdout.write(
            self.style.SUCCESS('=== Phase 4 Cache Performance Monitor ===\n')
        )
        
        # Get cache statistics
        cache_stats = cache_invalidator.get_cache_stats()
        
        if options['format'] == 'json':
            self._output_json(cache_stats)
        else:
            self._output_table(cache_stats)
    
    def _output_table(self, stats):
        """Output cache statistics in table format"""
        
        self.stdout.write(f"{'Cache Backend':<15} {'Keys':<8} {'Memory':<12} {'Hit Ratio':<10} {'Status'}")
        self.stdout.write("-" * 60)
        
        for cache_name, cache_data in stats.items():
            if 'error' in cache_data:
                self.stdout.write(
                    f"{cache_name:<15} {'ERROR':<8} {cache_data['error']:<12} {'N/A':<10}"
                )
            else:
                keys = cache_data.get('keys', 0)
                memory = cache_data.get('memory_usage', 'N/A')
                hit_ratio = f"{cache_data.get('hit_ratio', 0):.1f}%"
                
                # Color code based on hit ratio
                if cache_data.get('hit_ratio', 0) > 80:
                    status = self.style.SUCCESS('EXCELLENT')
                elif cache_data.get('hit_ratio', 0) > 60:
                    status = self.style.WARNING('GOOD')
                elif cache_data.get('hit_ratio', 0) > 40:
                    status = 'FAIR'
                else:
                    status = self.style.ERROR('POOR')
                
                self.stdout.write(
                    f"{cache_name:<15} {keys:<8} {memory:<12} {hit_ratio:<10} {status}"
                )
        
        # Cache recommendations
        self.stdout.write("\n=== Recommendations ===")
        
        total_keys = sum(cache_data.get('keys', 0) for cache_data in stats.values() if 'error' not in cache_data)
        valid_caches = [cd for cd in stats.values() if 'error' not in cd]
        avg_hit_ratio = sum(cache_data.get('hit_ratio', 0) for cache_data in valid_caches) / len(valid_caches) if valid_caches else 0
        
        if total_keys == 0:
            self.stdout.write(self.style.WARNING("• No cache keys found - Redis may not be running or caches need warming up"))
        elif len(valid_caches) == 0:
            self.stdout.write(self.style.ERROR("• No cache backends accessible - check Redis connection"))
        elif avg_hit_ratio < 50:
            self.stdout.write(self.style.WARNING("• Low hit ratio - consider increasing cache timeouts"))
        elif avg_hit_ratio > 90:
            self.stdout.write(self.style.SUCCESS("• Excellent cache performance - consider decreasing timeouts to save memory"))
        else:
            self.stdout.write(self.style.SUCCESS("• Good cache performance"))
        
        # Memory usage warning
        for cache_name, cache_data in stats.items():
            if 'error' not in cache_data:
                memory_str = cache_data.get('memory_usage', '')
                if 'M' in memory_str and float(memory_str.replace('M', '')) > 100:
                    self.stdout.write(self.style.WARNING(f"• {cache_name} using high memory: {memory_str}"))
    
    def _output_json(self, stats):
        """Output cache statistics in JSON format"""
        valid_caches = [cd for cd in stats.values() if 'error' not in cd]
        output = {
            'timestamp': datetime.now().isoformat(),
            'cache_backends': stats,
            'summary': {
                'total_keys': sum(cache_data.get('keys', 0) for cache_data in stats.values() if 'error' not in cache_data),
                'avg_hit_ratio': sum(cache_data.get('hit_ratio', 0) for cache_data in valid_caches) / len(valid_caches) if valid_caches else 0
            }
        }
        
        self.stdout.write(json.dumps(output, indent=2))