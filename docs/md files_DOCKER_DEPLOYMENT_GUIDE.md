# 🚀 Christian Library Docker Production Deployment Guide

## Overview

This guide will help you deploy the Christian Library application using Docker with all required dependencies including FFmpeg, Ghostscript, Poppler utilities, and a complete nginx + Django + Celery setup.

## 📋 Prerequisites

- Docker Engine 20.10+ and Docker Compose 2.0+
- At least 4GB RAM and 20GB disk space
- Domain name (for production) or localhost (for testing)

## 🏗️ Architecture

```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│     Nginx       │    │     Django      │    │    PostgreSQL   │
│  Reverse Proxy  │────│   Application   │────│    Database     │
│   Port 80/443   │    │    Port 8000    │    │    Port 5432    │
└─────────────────┘    └─────────────────┘    └─────────────────┘
         │                       │                       │
         │                       │              ┌─────────────────┐
         │                       │              │      Redis      │
         │                       └──────────────│  Cache/Broker   │
         │                                      │    Port 6379    │
         └─────────────────┐                    └─────────────────┘
                           │                             │
                  ┌─────────────────┐                   │
                  │  Celery Worker  │───────────────────┘
                  │ Background Jobs │
                  └─────────────────┘
```

## 🚀 Quick Start

### 1. Clone and Setup

```bash
cd christian_library_project/library_prod
cp .env.example .env
```

### 2. Configure Environment

Edit `.env` file with your settings:

```bash
# Essential settings to change:
SECRET_KEY=your-super-secret-key-change-this
ALLOWED_HOSTS=yourdomain.com,localhost
DB_PASSWORD=secure_database_password
REDIS_PASSWORD=secure_redis_password
```

### 3. Deploy

```bash
# Build and start all services
docker-compose up --build -d

# Check deployment status
docker-compose ps
docker-compose logs -f
```

### 4. Verify Deployment

```bash
# Run health checks
docker-compose exec backend /app/docker/healthcheck.sh

# Check nginx
curl http://localhost/nginx-health/

# Check Django
curl http://localhost/health/

# Access admin interface
open http://localhost/admin/
# Login: admin / admin123
```

## 📁 Project Structure

```
library_prod/
├── docker-compose.yml          # Main orchestration
├── Dockerfile                  # Multi-stage build
├── .env.example               # Environment template
├── docker/
│   ├── nginx/
│   │   └── nginx.conf         # Production nginx config
│   ├── entrypoint.sh          # Container startup script
│   ├── healthcheck.sh         # Health monitoring
│   └── supervisord.conf       # Process management
└── backend/                   # Django application
```

## 🔧 Detailed Configuration

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `DEBUG` | Django debug mode | `False` |
| `SECRET_KEY` | Django secret key | **Required** |
| `DB_PASSWORD` | Database password | **Required** |
| `REDIS_PASSWORD` | Redis password | **Required** |
| `GUNICORN_WORKERS` | Number of web workers | `3` |
| `CELERY_CONCURRENCY` | Celery worker processes | `2` |

### Service Configuration

#### Nginx (Port 80)
- Reverse proxy and static file serving
- Rate limiting for API and media endpoints
- Secure media delivery via X-Accel-Redirect
- Public downloads + authenticated streaming

#### Django Backend (Port 8000)
- Gunicorn WSGI server with gevent workers
- Auto-scaling based on `GUNICORN_WORKERS`
- Media processing with FFmpeg, Ghostscript, Poppler
- Comprehensive error handling and logging

#### PostgreSQL (Port 5432)
- Persistent data storage
- Automated backups via pg_dump
- Connection pooling and optimization

#### Redis (Port 6379)
- Celery broker and result backend
- Django session and cache storage
- Pub/sub for real-time features

#### Celery Worker
- Background media processing
- File compression and optimization
- Email sending and notifications
- Scheduled tasks via Celery Beat

## 🛠️ Development Workflow

### Local Development

```bash
# Start development environment
docker-compose up --build

# Run migrations
docker-compose exec backend python manage.py migrate

# Create admin user
docker-compose exec backend python manage.py createsuperuser

# Access shell
docker-compose exec backend python manage.py shell

# View logs
docker-compose logs -f backend
docker-compose logs -f worker
```

### Database Management

```bash
# Backup database
docker-compose exec db pg_dump -U christian_library_user christian_library_db > backup.sql

# Restore database
docker-compose exec -i db psql -U christian_library_user christian_library_db < backup.sql

# Reset database
docker-compose down -v
docker-compose up -d db
docker-compose exec backend python manage.py migrate
```

### Media Processing Testing

```bash
# Test FFmpeg
docker-compose exec backend ffmpeg -version

# Test Ghostscript
docker-compose exec backend gs --version

# Test PDF utilities
docker-compose exec backend pdfinfo --version

# Test Django media processing
docker-compose exec backend python manage.py shell -c "
from core.utils.media_processing import check_dependencies
print('Missing deps:', check_dependencies() or 'None')
"
```

## 🔐 Security Configuration

### Production Security Checklist

- [ ] Change default passwords in `.env`
- [ ] Set strong `SECRET_KEY`
- [ ] Configure `ALLOWED_HOSTS` with your domain
- [ ] Enable SSL/TLS (see SSL setup below)
- [ ] Set up firewall rules
- [ ] Regular security updates
- [ ] Monitor logs for suspicious activity

### SSL/TLS Setup (Production)

1. **Using Let's Encrypt:**

```bash
# Add SSL configuration to nginx
# Update docker-compose.yml with SSL volumes
# Use certbot for certificate generation
```

2. **Environment Variables for SSL:**

```bash
SECURE_SSL_REDIRECT=True
SESSION_COOKIE_SECURE=True
CSRF_COOKIE_SECURE=True
```

## 📊 Monitoring and Maintenance

### Health Monitoring

```bash
# Manual health check
docker-compose exec backend /app/docker/healthcheck.sh

# Service status
docker-compose ps

# Resource usage
docker stats

# Application logs
docker-compose logs --tail=100 -f backend
```

### Log Management

Logs are stored in:
- `/app/logs/django.log` - Django application logs
- `/app/logs/celery_worker.log` - Background job logs
- `/app/logs/nginx_access.log` - Web access logs
- `/app/logs/nginx_error.log` - Web error logs

### Performance Tuning

**For High Traffic:**

```env
# Increase workers
GUNICORN_WORKERS=6
CELERY_CONCURRENCY=4

# Optimize database connections
DB_CONN_MAX_AGE=600

# Enable caching
CACHE_BACKEND=redis
```

**For Large Files:**

```env
# Increase upload limits
FILE_UPLOAD_MAX_MEMORY_SIZE=104857600  # 100MB
CLIENT_MAX_BODY_SIZE=1G
```

## 🚨 Troubleshooting

### Common Issues

1. **Container won't start:**
```bash
docker-compose logs backend
# Check environment variables and dependencies
```

2. **Database connection issues:**
```bash
docker-compose exec backend python manage.py dbshell
# Verify database credentials and connectivity
```

3. **Media processing failures:**
```bash
docker-compose exec backend /app/docker/healthcheck.sh
# Check FFmpeg, Ghostscript, and Poppler installation
```

4. **Permission errors:**
```bash
docker-compose exec backend chown -R app:app /app/media
docker-compose exec backend chmod -R 755 /app/media
```

5. **Memory issues:**
```bash
# Monitor container memory usage
docker stats

# Adjust worker counts
GUNICORN_WORKERS=2
CELERY_CONCURRENCY=1
```

### Debug Mode

For troubleshooting, you can enable debug mode:

```bash
# Temporarily enable debug
echo "DEBUG=True" >> .env
docker-compose restart backend

# View detailed error pages and logs
docker-compose logs -f backend
```

## 🔄 Updates and Maintenance

### Application Updates

```bash
# Pull latest changes
git pull

# Rebuild and restart
docker-compose down
docker-compose up --build -d

# Run migrations if needed
docker-compose exec backend python manage.py migrate
```

### System Updates

```bash
# Update base images
docker-compose pull
docker-compose up --build -d

# Clean up old images
docker image prune -a
```

## 📈 Scaling

### Horizontal Scaling

```bash
# Scale web workers
docker-compose up -d --scale backend=3

# Scale celery workers
docker-compose up -d --scale worker=2
```

### Load Balancing

For production, consider:
- Multiple nginx instances
- Database read replicas
- Redis cluster for cache
- CDN for static/media files

## 📞 Support

### Getting Help

1. Check logs first: `docker-compose logs -f`
2. Run health checks: `docker-compose exec backend /app/docker/healthcheck.sh`
3. Verify configuration: `docker-compose config`
4. Test dependencies: Individual container tests

### Key Commands Reference

```bash
# Essential commands
docker-compose up -d --build     # Deploy
docker-compose down             # Stop all
docker-compose restart backend  # Restart service
docker-compose logs -f backend  # View logs
docker-compose exec backend sh  # Shell access
docker-compose ps              # Service status

# Maintenance commands
docker-compose exec backend python manage.py migrate
docker-compose exec backend python manage.py collectstatic
docker-compose exec backend python manage.py createsuperuser
```

## ✅ Deployment Checklist

- [ ] Environment configured (`.env`)
- [ ] Secrets changed (passwords, secret key)
- [ ] Domain configured (`ALLOWED_HOSTS`)
- [ ] SSL configured (production)
- [ ] Database backed up
- [ ] Health checks passing
- [ ] Media processing working
- [ ] Admin access verified
- [ ] Monitoring configured
- [ ] Logs accessible

---

**🎉 Congratulations!** Your Christian Library application is now running in a production-ready Docker environment with all media processing capabilities!

For additional help or advanced configuration, refer to the individual component documentation or container logs.