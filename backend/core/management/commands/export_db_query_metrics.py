import os
import json
import csv
from datetime import datetime
from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils.dateparse import parse_date

LOG_PATH = os.path.join(settings.BASE_DIR, 'logs', 'db_query_metrics.jsonl')


class Command(BaseCommand):
    help = 'Export or filter DB query metrics logs for LLM analysis and performance monitoring.'

    def add_arguments(self, parser):
        # Filtering options
        parser.add_argument(
            '--min-time',
            type=float,
            default=0.0,
            help='Only export queries slower than this (seconds)'
        )
        parser.add_argument(
            '--issues-only',
            action='store_true',
            help='Only export requests with detected issues (N+1, duplicates, slow queries)'
        )
        parser.add_argument(
            '--date-range',
            nargs=2,
            metavar=('START', 'END'),
            help='Filter by date range (YYYY-MM-DD format)'
        )
        parser.add_argument(
            '--view-pattern',
            type=str,
            help='Filter by view function pattern (case-insensitive substring match)'
        )
        parser.add_argument(
            '--path-pattern',
            type=str,
            help='Filter by request path pattern (case-insensitive substring match)'
        )
        
        # Output options
        parser.add_argument(
            '--csv',
            action='store_true',
            help='Export as CSV instead of JSONL'
        )
        parser.add_argument(
            '--output',
            type=str,
            default=None,
            help='Output file (default: stdout)'
        )
        parser.add_argument(
            '--summary',
            action='store_true',
            help='Show summary statistics instead of raw data'
        )
        parser.add_argument(
            '--limit',
            type=int,
            help='Limit number of exported entries'
        )

    def handle(self, *args, **options):
        if not os.path.exists(LOG_PATH):
            self.stdout.write(
                self.style.ERROR(f'Log file not found: {LOG_PATH}')
            )
            return

        # Load and parse log entries
        try:
            with open(LOG_PATH, 'r', encoding='utf-8') as f:
                entries = [json.loads(line) for line in f if line.strip()]
        except Exception as e:
            self.stdout.write(
                self.style.ERROR(f'Failed to read log file: {str(e)}')
            )
            return

        # Apply filters
        filtered_entries = self._apply_filters(entries, options)
        
        if options['summary']:
            self._show_summary(filtered_entries)
        else:
            self._export_data(filtered_entries, options)

    def _apply_filters(self, entries, options):
        """Apply all specified filters to the log entries"""
        filtered = entries
        
        # Filter by minimum query time
        if options['min_time'] > 0:
            filtered = [
                entry for entry in filtered
                if entry.get('performance', {}).get('total_query_time', 0) >= options['min_time']
            ]
        
        # Filter by issues
        if options['issues_only']:
            filtered = [
                entry for entry in filtered
                if self._has_issues(entry)
            ]
        
        # Filter by date range
        if options['date_range']:
            start_date = parse_date(options['date_range'][0])
            end_date = parse_date(options['date_range'][1])
            if start_date and end_date:
                filtered = [
                    entry for entry in filtered
                    if start_date <= parse_date(entry['timestamp'][:10]) <= end_date
                ]
        
        # Filter by view pattern
        if options['view_pattern']:
            pattern = options['view_pattern'].lower()
            filtered = [
                entry for entry in filtered
                if pattern in entry.get('request', {}).get('view_func', '').lower()
            ]
        
        # Filter by path pattern
        if options['path_pattern']:
            pattern = options['path_pattern'].lower()
            filtered = [
                entry for entry in filtered
                if pattern in entry.get('request', {}).get('path', '').lower()
            ]
        
        # Apply limit
        if options['limit']:
            filtered = filtered[:options['limit']]
        
        return filtered
    
    def _has_issues(self, entry):
        """Check if an entry has any detected issues"""
        issues = entry.get('issues', {})
        return (
            issues.get('n_plus_one_detected', False) or
            issues.get('duplicate_queries_count', 0) > 0 or
            issues.get('slow_operation', False)
        )
    
    def _show_summary(self, entries):
        """Display summary statistics"""
        if not entries:
            self.stdout.write(self.style.WARNING('No entries match the filters.'))
            return
        
        total_entries = len(entries)
        total_queries = sum(entry.get('performance', {}).get('total_query_count', 0) for entry in entries)
        total_time = sum(entry.get('performance', {}).get('total_query_time', 0) for entry in entries)
        
        n_plus_one_count = sum(1 for entry in entries if entry.get('issues', {}).get('n_plus_one_detected', False))
        duplicate_count = sum(1 for entry in entries if entry.get('issues', {}).get('duplicate_queries_count', 0) > 0)
        slow_count = sum(1 for entry in entries if entry.get('issues', {}).get('slow_operation', False))
        
        # Calculate averages
        avg_queries_per_request = total_queries / total_entries if total_entries > 0 else 0
        avg_time_per_request = total_time / total_entries if total_entries > 0 else 0
        
        # Find top views by query count
        view_stats = {}
        for entry in entries:
            view = entry.get('request', {}).get('view_func', 'unknown')
            queries = entry.get('performance', {}).get('total_query_count', 0)
            if view not in view_stats:
                view_stats[view] = {'count': 0, 'queries': 0}
            view_stats[view]['count'] += 1
            view_stats[view]['queries'] += queries
        
        top_views = sorted(
            view_stats.items(),
            key=lambda x: x[1]['queries'],
            reverse=True
        )[:5]
        
        self.stdout.write(self.style.SUCCESS('\n=== DATABASE QUERY METRICS SUMMARY ==='))
        self.stdout.write(f'Total Entries: {total_entries}')
        self.stdout.write(f'Total Queries: {total_queries}')
        self.stdout.write(f'Total Query Time: {total_time:.3f}s')
        self.stdout.write(f'Average Queries per Request: {avg_queries_per_request:.1f}')
        self.stdout.write(f'Average Time per Request: {avg_time_per_request:.3f}s')
        
        self.stdout.write(self.style.WARNING('\n--- Issues Detected ---'))
        self.stdout.write(f'N+1 Queries: {n_plus_one_count} requests ({n_plus_one_count/total_entries*100:.1f}%)')
        self.stdout.write(f'Duplicate Queries: {duplicate_count} requests ({duplicate_count/total_entries*100:.1f}%)')
        self.stdout.write(f'Slow Operations: {slow_count} requests ({slow_count/total_entries*100:.1f}%)')
        
        self.stdout.write(self.style.SUCCESS('\n--- Top Views by Query Count ---'))
        for view, stats in top_views:
            self.stdout.write(f'{view}: {stats["queries"]} queries across {stats["count"]} requests')
    
    def _export_data(self, entries, options):
        """Export filtered data in the specified format"""
        if not entries:
            self.stdout.write(self.style.WARNING('No entries match the filters.'))
            return
        
        if options['csv']:
            self._export_csv(entries, options['output'])
        else:
            self._export_jsonl(entries, options['output'])
        
        self.stdout.write(
            self.style.SUCCESS(f'Exported {len(entries)} log entries.')
        )
    
    def _export_csv(self, entries, output_file):
        """Export entries as CSV"""
        fieldnames = [
            'timestamp', 'path', 'method', 'user', 'view_func',
            'total_query_count', 'total_query_time', 'request_duration',
            'n_plus_one_detected', 'duplicate_queries_count', 'slow_operation'
        ]
        
        rows = []
        for entry in entries:
            request_info = entry.get('request', {})
            performance = entry.get('performance', {})
            issues = entry.get('issues', {})
            
            rows.append({
                'timestamp': entry.get('timestamp', ''),
                'path': request_info.get('path', ''),
                'method': request_info.get('method', ''),
                'user': request_info.get('user', ''),
                'view_func': request_info.get('view_func', ''),
                'total_query_count': performance.get('total_query_count', 0),
                'total_query_time': performance.get('total_query_time', 0),
                'request_duration': performance.get('request_duration', 0),
                'n_plus_one_detected': issues.get('n_plus_one_detected', False),
                'duplicate_queries_count': issues.get('duplicate_queries_count', 0),
                'slow_operation': issues.get('slow_operation', False),
            })
        
        if output_file:
            with open(output_file, 'w', newline='', encoding='utf-8') as out:
                writer = csv.DictWriter(out, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(rows)
        else:
            writer = csv.DictWriter(self.stdout, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
    
    def _export_jsonl(self, entries, output_file):
        """Export entries as JSONL"""
        if output_file:
            with open(output_file, 'w', encoding='utf-8') as out:
                for entry in entries:
                    out.write(json.dumps(entry, ensure_ascii=False, default=str) + '\n')
        else:
            for entry in entries:
                self.stdout.write(json.dumps(entry, ensure_ascii=False, default=str))
