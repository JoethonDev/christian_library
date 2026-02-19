# Database Query Metrics Logging & Export – Implementation Plan

## 📋 Overview

This system provides comprehensive database query monitoring and analysis capabilities for the Christian Library application. It captures detailed metrics about database queries, detects performance issues, and exports structured data for LLM analysis.

## 🎯 Goals

- **Monitor Database Performance**: Track query counts, execution times, and detect performance issues per request
- **Identify Query Problems**: Detect N+1 queries, duplicate queries, and slow operations automatically
- **LLM Analysis Support**: Export structured logs in JSONL/CSV format for AI-powered analysis
- **Development Insights**: Provide actionable data to optimize database queries and application performance

## 🏗️ System Architecture

### Components

1. **Unified Database Metrics Middleware** (`UnifiedDBQueryMetricsMiddleware`)
   - Captures all database queries per request
   - Analyzes queries for performance issues
   - Logs structured data to JSONL files
   - Adds debug headers in development mode

2. **Export Management Command** (`export_db_query_metrics`)
   - Filters logs by time, issue type, or performance thresholds
   - Exports data in JSONL or CSV formats
   - Supports file output or stdout for pipeline integration

3. **Structured Logging System**
   - JSONL format for easy parsing by LLMs
   - Thread-safe file operations
   - Comprehensive error handling

## 📊 Data Structure

Each log entry contains:

```json
{
  "timestamp": "2025-12-26T10:30:45.123456Z",
  "request": {
    "path": "/api/content/",
    "method": "GET",
    "user": "admin",
    "remote_addr": "127.0.0.1",
    "view_func": "frontend_api.views.home"
  },
  "performance": {
    "total_query_count": 15,
    "total_query_time": 0.045,
    "request_duration": 0.123,
    "slow_queries_count": 1
  },
  "issues": {
    "n_plus_one_detected": true,
    "duplicate_queries_count": 3,
    "slow_operation": false,
    "patterns": ["SELECT from media_manager_contentitem"]
  },
  "queries": [
    {
      "sql": "SELECT * FROM media_manager_contentitem WHERE id = %s",
      "time": "0.001",
      "pattern": "SELECT from media_manager_contentitem"
    }
  ],
  "stack_trace": ["...abbreviated stack trace..."]
}
```

## 🔍 Issue Detection

### N+1 Query Detection
- Identifies when the same query pattern is executed multiple times (>3 occurrences)
- Normalizes SQL to detect patterns across different parameter values
- Logs specific patterns and occurrence counts

### Duplicate Query Detection
- Finds exact duplicate SQL statements within a single request
- Helps identify unnecessary repeated queries
- Reports duplicate count and affected queries

### Slow Query Detection
- Identifies requests with total query time >100ms
- Flags individual slow queries
- Provides performance impact analysis

## 🚀 Implementation Steps

### Step 1: Design Unified Database Query Metrics Logging System ✅
- **Status**: Complete
- **Details**: Merged existing `DatabaseOptimizationMiddleware` functionality with new JSONL logging system
- **Result**: Single middleware with comprehensive monitoring and structured logging

### Step 2: Implement Unified Django Middleware
- **File**: `core/middleware/db_query_metrics.py`
- **Features**:
  - Per-request query collection and analysis
  - N+1, duplicate, and slow query detection
  - JSONL logging with thread-safe operations
  - Debug headers in development mode
- **Integration**: Added to `MIDDLEWARE` in Django settings

### Step 3: Store Logs in Structured File (JSONL/CSV)
- **Location**: `logs/db_query_metrics.jsonl`
- **Format**: One JSON object per line for easy parsing
- **Safety**: Thread-safe writes with file locking
- **Rotation**: Manual rotation recommended for production

### Step 4: Add Management Command to Export/Query Logs
- **Command**: `python manage.py export_db_query_metrics`
- **Options**:
  - `--min-time SECONDS`: Filter by minimum query time
  - `--issues-only`: Export only requests with detected issues
  - `--csv`: Export as CSV instead of JSONL
  - `--output FILE`: Output to file instead of stdout
  - `--date-range START END`: Filter by date range
- **Use Cases**:
  - Daily performance review
  - LLM analysis preparation
  - Performance regression detection

### Step 5: Create Local Nginx Config for Development
- **Method**: Docker Compose override files
- **Files**:
  - `docker-compose.yml`: Production configuration
  - `docker-compose.override.yml`: Local development overrides
- **Benefits**: Automatic local/prod switching without code changes

### Step 6: Document Usage for Both Features
- **This Document**: Comprehensive implementation and usage guide
- **Code Comments**: Inline documentation for all components
- **Memory File**: Updated project context and patterns

### Step 7: Test Logging, Export, and Local Nginx Setup
- **Local Testing**: Verify middleware activation and log generation
- **Export Testing**: Validate filtering and output formats
- **Docker Testing**: Confirm local/prod Nginx switching
- **Production Validation**: Monitor performance impact

## 📖 Usage Instructions

### Enabling Database Query Logging

The middleware is automatically active when added to Django's `MIDDLEWARE` setting. No additional configuration required.

### Viewing Raw Logs

```bash
# View recent log entries
tail -f logs/db_query_metrics.jsonl

# View logs with formatting
cat logs/db_query_metrics.jsonl | jq '.'
```

### Exporting for Analysis

```bash
# Export all slow queries (>50ms)
python manage.py export_db_query_metrics --min-time 0.05 --output slow_queries.jsonl

# Export as CSV for spreadsheet analysis
python manage.py export_db_query_metrics --csv --output performance_report.csv

# Export only requests with issues
python manage.py export_db_query_metrics --issues-only

# Date range analysis
python manage.py export_db_query_metrics --date-range "2025-12-01" "2025-12-31"
```

### LLM Analysis Preparation

```bash
# Generate comprehensive analysis dataset
python manage.py export_db_query_metrics --min-time 0.01 --output llm_analysis.jsonl

# Create issue-focused dataset
python manage.py export_db_query_metrics --issues-only --output issues_analysis.jsonl
```

## 🔧 Configuration Options

### Middleware Settings

```python
# In settings.py
DB_QUERY_METRICS_CONFIG = {
    'LOG_PATH': BASE_DIR / 'logs' / 'db_query_metrics.jsonl',
    'N_PLUS_ONE_THRESHOLD': 3,
    'SLOW_QUERY_THRESHOLD': 0.1,  # 100ms
    'MAX_STACK_DEPTH': 10,
    'ENABLE_DEBUG_HEADERS': DEBUG,
}
```

### Log Rotation

```bash
# Rotate logs manually
mv logs/db_query_metrics.jsonl logs/db_query_metrics.jsonl.$(date +%Y%m%d)
touch logs/db_query_metrics.jsonl
```

## 🐳 Docker Compose Local/Prod Configuration

### Method: Override Files (Recommended)

**docker-compose.yml** (Production):
```yaml
services:
  nginx:
    volumes:
      - ./docker/nginx/nginx.conf:/etc/nginx/nginx.conf:ro
```

**docker-compose.override.yml** (Local Development):
```yaml
services:
  nginx:
    ports:
      - "8080:80"  # Different port for local
    volumes:
      - ./docker/nginx/nginx.local.conf:/etc/nginx/nginx.conf:ro
```

**Usage**:
- **Local**: `docker-compose up` (automatically uses override)
- **Production**: `docker-compose -f docker-compose.yml up` (ignores override)

## 📊 Performance Impact

### Middleware Overhead
- **Development**: ~1-2ms per request (acceptable for debugging)
- **Production**: Disable via settings or remove from middleware stack
- **Memory**: Minimal impact, queries are temporarily stored per request

### Log File Growth
- **Estimate**: ~500 bytes per request
- **Daily Volume**: ~50MB for 100k requests
- **Recommendation**: Implement log rotation in production

## 🔍 Troubleshooting

### Common Issues

1. **Log File Not Created**
   - Ensure `logs/` directory exists and is writable
   - Check Django file permissions

2. **Missing Queries in Debug Mode**
   - Verify `DEBUG = True` in settings
   - Confirm middleware is in `MIDDLEWARE` list

3. **Performance Impact**
   - Disable middleware in production if overhead is significant
   - Use sampling for high-traffic applications

### Debug Commands

```bash
# Check middleware is loaded
python manage.py shell -c "from django.conf import settings; print(settings.MIDDLEWARE)"

# Verify log file permissions
ls -la logs/db_query_metrics.jsonl

# Test export functionality
python manage.py export_db_query_metrics --help
```

## 🎯 LLM Analysis Prompts

### Performance Analysis Prompt

```
Analyze this Django database query log and identify:
1. Most common N+1 query patterns
2. Slowest operations and their causes
3. Duplicate query hotspots
4. Optimization recommendations

Data format: JSONL with fields for queries, timing, patterns, and issues.
```

### Optimization Recommendations Prompt

```
Review these database query metrics and suggest:
1. Specific model optimizations (select_related, prefetch_related)
2. Index recommendations
3. Query pattern improvements
4. Caching opportunities

Focus on queries with high frequency or long execution times.
```

## 📝 Future Enhancements

### Planned Features
- [ ] Real-time dashboard for query metrics
- [ ] Automated performance regression detection
- [ ] Integration with APM tools (New Relic, Datadog)
- [ ] Query pattern visualization
- [ ] Automated optimization suggestions

### Advanced Analysis
- [ ] Machine learning-based anomaly detection
- [ ] Query performance trending
- [ ] Correlation with user activity patterns
- [ ] Automated alerting for performance degradation

---

**Last Updated**: December 26, 2025
**Status**: Implementation Complete
**Next Review**: January 2026