# Database Query Metrics - Quick Start Guide

## 🚀 Getting Started

The database query metrics logging system is now active and monitoring all database operations.

### View Live Logs
```bash
# Watch logs in real-time
tail -f backend/logs/db_query_metrics.jsonl

# View formatted logs
cat backend/logs/db_query_metrics.jsonl | jq '.'
```

### Generate Performance Reports
```bash
# Quick performance summary
python backend/manage.py export_db_query_metrics --summary

# Export slow queries (>50ms)
python backend/manage.py export_db_query_metrics --min-time 0.05 --output slow_queries.jsonl

# Issues-only report for optimization
python backend/manage.py export_db_query_metrics --issues-only --csv --output optimization_report.csv
```

### Local Development
```bash
# Start with local configuration (automatic)
docker-compose up

# Start with production configuration (manual)
docker-compose -f docker-compose.yml up
```

### LLM Analysis
```bash
# Generate comprehensive dataset for AI analysis
python backend/manage.py export_db_query_metrics --min-time 0.01 --output llm_analysis.jsonl
```

**Example LLM Prompt:**
> Analyze this Django database query log and identify: 1) Most common N+1 query patterns, 2) Slowest operations and their causes, 3) Duplicate query hotspots, 4) Optimization recommendations. Focus on actionable insights for Django model optimization.

## 📊 Key Metrics Monitored

- **N+1 Queries**: Same query pattern executed >3 times
- **Duplicate Queries**: Exact same SQL within one request  
- **Slow Operations**: Total request query time >100ms
- **Query Patterns**: Normalized SQL for pattern analysis

## 🔧 Configuration

All settings are optional with sensible defaults:

```python
# In settings.py (optional)
DB_QUERY_N_PLUS_ONE_THRESHOLD = 3    # N+1 detection threshold
DB_QUERY_SLOW_THRESHOLD = 0.1        # 100ms slow query threshold  
DB_QUERY_MAX_STACK_DEPTH = 10        # Stack trace depth
```

## 📈 Production Usage

**Performance Impact**: ~1-2ms per request in development mode
**Log Growth**: ~500 bytes per request (~50MB/day for 100k requests)  
**Recommendation**: Consider log rotation for high-traffic applications

---
**Status**: Production Ready ✅  
**Documentation**: See `DATABASE_QUERY_METRICS.md` for complete details