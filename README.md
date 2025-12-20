# Christian Library - Coptic Orthodox Digital Library

[![Django](https://img.shields.io/badge/Django-5.2.9-green.svg)](https://djangoproject.com/)
[![Python](https://img.shields.io/badge/Python-3.11+-blue.svg)](https://python.org/)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-15+-blue.svg)](https://postgresql.org/)
[![Gemini AI](https://img.shields.io/badge/Gemini-2.5--Flash-purple.svg)](https://ai.google.dev/)

A modern, bilingual (Arabic/English) digital library system specifically designed for the **Coptic Orthodox Church of Egypt**, featuring AI-powered content generation, full-text search, and comprehensive media management.

## ✨ Key Features

### 🎯 **Coptic Orthodox Specialized**
- **Denominational Safety**: AI content generation uses only Coptic Orthodox terminology
- **Source Grounding**: Extracts metadata only from actual content, no theological inference
- **Arabic-First**: RTL support with proper Arabic typographic handling
- **Orthodox-Safe**: Avoids Protestant, Evangelical, or Catholic terminology

### 🤖 **AI-Powered Content Generation**
- **Gemini AI Integration**: Automatic metadata generation for uploaded content
- **Consistent Output**: Deterministic generation with enhanced configuration (temperature=0.1)
- **Multilingual**: Arabic and English content generation with semantic alignment
- **Content-Grounded**: Uses only terms explicitly found in uploaded files

### 🔍 **Advanced Search & SEO**
- **Full-Text Search**: PostgreSQL-powered search with Arabic support
- **SEO Optimization**: Dynamic meta tags, OpenGraph, JSON-LD schema
- **Search Highlights**: HTML highlighting of search results
- **Sitemap Generation**: Automatic XML sitemaps for search engines

### 📱 **Modern Architecture**
- **Responsive Design**: Bootstrap-based responsive layout
- **Performance**: Redis caching, database optimization, CDN-ready
- **Security**: HTTPS-ready, secure media handling, CSRF protection
- **Scalability**: Celery background tasks, Docker deployment

## 🚀 Quick Start

### Prerequisites
- Python 3.11+
- PostgreSQL 15+
- Redis 6+
- Google Gemini API key ([Get API Key](https://aistudio.google.com/apikey))

### 1. Environment Setup
```bash
# Clone repository
git clone <repository-url>
cd library_prod

# Set environment variables
export GEMINI_API_KEY="your-gemini-api-key"
export DB_NAME="christian_library"
export DB_USER="postgres"
export DB_PASSWORD="your-password"
export SECRET_KEY="your-secret-key"
```

### 2. Install Dependencies
```bash
# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install requirements
pip install -r backend/requirements/base.txt
```

### 3. Database Setup
```bash
cd backend

# Run migrations
python manage.py migrate

# Create superuser
python manage.py createsuperuser

# Load initial data (optional)
python manage.py loaddata fixtures/initial_data.json
```

### 4. Start the Server
```bash
# Development server
python manage.py runserver

# Visit http://localhost:8000
```

## 🎨 AI Content Generation

The **Gemini AI integration** is the flagship feature, providing intelligent metadata generation specifically designed for Coptic Orthodox content:

### Key Features:
- **📖 Source-Grounded**: Uses only terms from uploaded content, no theological inference
- **⛪ Denomination-Safe**: Coptic Orthodox terminology only, avoids Western theological terms
- **🎯 Consistent**: Enhanced configuration (temperature=0.1, top_p=0.9, top_k=20) for deterministic outputs
- **🌐 Bilingual**: Arabic and English generation with semantic alignment

### Usage:
1. Navigate to `/admin/upload/`
2. Select content type (Video, Audio, Document)
3. Upload your file
4. Click **"Generate with AI" ✨** button
5. Review and edit the generated metadata

### Generated Output:
- **Titles**: 3-6 words using actual content terms
- **Descriptions**: 140-160 words extracted from content vocabulary
- **Tags**: 5-6 Arabic tags derived from repeated keywords and explicit themes

## 📋 Table of Contents

1. [Overview](#overview)
2. [Features](#features)
3. [Technology Stack](#technology-stack)
4. [Architecture](#architecture)
5. [Quick Start](#quick-start)
6. [Development Setup](#development-setup)
7. [Production Deployment](#production-deployment)
8. [API Documentation](#api-documentation)
9. [Configuration](#configuration)
10. [Troubleshooting](#troubleshooting)
11. [Contributing](#contributing)
12. [License](#license)

## 🎯 Overview

Christian Library is a comprehensive Django-based platform designed for managing, uploading, and serving Coptic Orthodox educational content. The platform supports multilingual content (Arabic/English) with RTL support, advanced media processing (HLS streaming, audio compression, PDF optimization), and a robust admin interface.

### Key Capabilities

- **Secure Media Delivery**: HLS video streaming, optimized audio, and secure PDF access
- **Multilingual Support**: Full Arabic/English localization with RTL layout support  
- **Content Management**: Advanced admin dashboard with bulk operations and analytics
- **API-First Design**: RESTful APIs for all content operations
- **Production Ready**: Docker-based deployment with monitoring and backup systems

## ✨ Features

### Content Management
- 📹 **Video Processing**: Automatic HLS generation (720p, 480p), thumbnail extraction
- 🎵 **Audio Optimization**: Compression to 192k bitrate with duration analysis
- 📄 **PDF Management**: Secure storage, optimization, and metadata extraction
- 📚 **Course Organization**: Hierarchical course and module structure
- 🏷️ **Tagging System**: Advanced content categorization and search

### User Experience
- 🌐 **Multilingual Interface**: Arabic (RTL) and English (LTR) support
- 📱 **Responsive Design**: Mobile-first with Bootstrap 5
- ⚡ **HTMX Integration**: Dynamic content loading without page refresh
- 🔍 **Advanced Search**: Real-time search with autocomplete suggestions
- 🎨 **Modern UI**: Clean, accessible design with Coptic Orthodox branding

### Security & Performance
- 🔐 **Secure Media Delivery**: Signed URLs with nginx authorization
- 🚀 **Redis Caching**: Multi-layer caching for optimal performance
- 📊 **Real-time Monitoring**: Health checks and performance metrics
- 🔄 **Background Processing**: Celery-based async media processing
- 💾 **Automated Backups**: Scheduled database and media backups

### Admin Features
- 📈 **Analytics Dashboard**: Content statistics and usage metrics
- 🔧 **Bulk Operations**: Mass content management and processing
- 👥 **User Management**: Role-based access control
- 🎛️ **System Monitoring**: Real-time health and performance tracking
- 📋 **Content Workflow**: Upload, review, and publish pipeline

## 🛠️ Technology Stack

### Backend
- **Framework**: Django 5.0+ with Django REST Framework
- **Database**: PostgreSQL 14+ with connection pooling
- **Cache**: Redis 7+ for session storage and caching
- **Task Queue**: Celery with Redis broker
- **Media Processing**: FFmpeg, Ghostscript

### Frontend
- **Templates**: Django templates with inheritance
- **CSS**: Bootstrap 5
- **JavaScript**: Alpine.js 3+ and HTMX for interactivity
- **Fonts**: Cairo (Arabic), Inter (English)
- **Icons**: Heroicons SVG library

### Infrastructure
- **Web Server**: Nginx with SSL termination
- **Containerization**: Docker & Docker Compose
- **Monitoring**: Custom health checks and metrics
- **Backup**: Automated PostgreSQL and media backups
- **Deployment**: Production-ready Docker orchestration

## 🏗️ Architecture

```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│    Frontend     │    │     Backend     │    │   Background    │
│                 │    │                 │    │                 │
│  • TailwindCSS  │────│  • Django REST  │────│  • Celery       │
│  • PostgreSQL   │    │  • PostgreSQL   │    │  • Redis        │
│  • Redis Cache  │    │  • Redis Cache  │    │  • Media Tasks  │
└─────────────────┘    └─────────────────┘    └─────────────────┘
         │                       │                       │
         └───────────────────────┼───────────────────────┘
                                 │
                    ┌─────────────────┐
                    │   Nginx Proxy   │
                    │                 │
                    │  • SSL/HTTPS    │
                    │  • Media Serve  │
                    │  • Load Balance │
                    └─────────────────┘
```

### Application Structure

```
christian_library_project/
├── backend/                 # Django application
│   ├── apps/               # Django apps
│   │   ├── frontend_api/   # Main frontend views & admin
│   │   ├── media_manager/  # Content & media handling
│   │   ├── courses/        # Course management
│   │   ├── users/          # User management
│   │   └── core/           # Health checks & utilities
│   ├── config/             # Django configuration
│   ├── templates/          # Django templates
│   ├── static/             # Static assets (Bootstrap 5, images, etc.)
│   └── locale/             # Translation files
├── docker/                 # Docker configuration
├── nginx/                  # Nginx configuration
├── docs/                   # Documentation
└── scripts/                # Deployment scripts
```

## 🚀 Quick Start

### Prerequisites

- **Docker & Docker Compose**: Latest stable versions
- **Git**: For cloning the repository
- **Domain/SSL**: For production deployment (Let's Encrypt supported)


### 1. Clone Repository

```bash
git clone https://github.com/JoethonDev/christian_library.git
cd christian_library
```

### 2. Environment Setup

```bash
# Copy environment template
cp .env.development.template .env

# Edit configuration (see Configuration section)
nano .env
```

### 3. Start Development Environment

```bash
# Build and start services
docker-compose up -d

# Run initial setup
docker-compose exec web python manage.py migrate
docker-compose exec web python manage.py collectstatic --noinput
docker-compose exec web python manage.py createsuperuser
```

### 4. Access Application

- **Frontend**: http://localhost:8000
- **Admin**: http://localhost:8000/admin/
- **API Docs**: http://localhost:8000/api/
- **Health Check**: http://localhost:8000/health/

## 💻 Development Setup

### Local Development (Without Docker)

1. **Python Environment**
   ```bash
   python -m venv venv
   source venv/bin/activate  # Windows: venv\Scripts\activate
   pip install -r backend/requirements/development.txt
   ```

2. **Database Setup**
   ```bash
   cd backend
   python manage.py migrate
   python manage.py loaddata fixtures/initial_data.json
   python manage.py createsuperuser
   ```

3. **Redis & Celery**
   ```bash
   # Start Redis (requires Redis server)
   redis-server

   # Start Celery worker (new terminal)
   cd backend
   celery -A config worker -l info

   # Start Celery beat (optional, for scheduled tasks)
   celery -A config beat -l info
   ```

4. **Frontend Assets**
   ```bash
   cd frontend
   npm install
   npm run build-dev
   ```

5. **Start Django Development Server**
   ```bash
   cd backend
   python manage.py runserver 0.0.0.0:8000
   ```

### Development Commands

```bash
# Generate translation files
python manage.py makemessages -l ar -l en
python manage.py compilemessages

# Collect static files
python manage.py collectstatic --noinput

# Run tests
python manage.py test

# Create database migrations
python manage.py makemigrations

# Reset database (development only)
python manage.py flush --noinput
python manage.py migrate
```

## 🌐 Production Deployment

### Quick Production Deployment

1. **Server Requirements**
   - Ubuntu 20.04+ or similar Linux distribution
   - 4GB+ RAM, 20GB+ storage
   - Docker & Docker Compose installed
   - Domain name configured

2. **SSL Setup**
   ```bash
   # Setup Let's Encrypt SSL (see docs/SSL_SETUP.md)
   sudo certbot certonly --webroot --webroot-path=/var/www/letsencrypt -d your-domain.com
   ```

3. **Environment Configuration**
   ```bash
   cp .env.production.template .env.production
   # Edit with production values
   nano .env.production
   ```

4. **Deploy**
   ```bash
   # Deploy application
   docker-compose -f docker-compose.production.yml --env-file .env.production up -d

   # Verify deployment
   curl https://your-domain.com/health/
   ```

### Production Environment Variables

```bash
# Domain and Security
ALLOWED_HOSTS=your-domain.com,www.your-domain.com
SECRET_KEY=generate-a-very-secure-secret-key-here
MONITORING_TOKEN=generate-a-secure-monitoring-token

# Database
DB_NAME=christian_library
DB_USER=christian_library
DB_PASSWORD=generate-secure-password
DB_HOST=db
DB_PORT=5432

# Email Configuration
EMAIL_HOST=smtp.gmail.com
EMAIL_PORT=587
EMAIL_HOST_USER=your-email@gmail.com
EMAIL_HOST_PASSWORD=your-app-password
DEFAULT_FROM_EMAIL=noreply@your-domain.com

# Optional: AWS S3 Backup
AWS_S3_BUCKET=your-backup-bucket
AWS_ACCESS_KEY_ID=your-aws-key
AWS_SECRET_ACCESS_KEY=your-aws-secret

# Optional: Slack Notifications
BACKUP_WEBHOOK_URL=https://hooks.slack.com/your-webhook
```

For complete deployment instructions, see [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md).

## 📖 API Documentation

### Authentication

The API uses session-based authentication for admin interface and token-based authentication for API endpoints.

```bash
# Login via API
curl -X POST https://your-domain.com/api/auth/login/ \
  -H "Content-Type: application/json" \
  -d '{"username": "admin", "password": "password"}'

# Access protected endpoint
curl -H "Authorization: Token your-token-here" \
  https://your-domain.com/api/content/
```

### Key API Endpoints

#### Content Management
```bash
# Get content list
GET /api/content/
GET /api/content/?type=video&page=1

# Get content details  
GET /api/content/{id}/

# Upload content
POST /api/content/upload/
Content-Type: multipart/form-data

# Update content
PUT /api/content/{id}/
```

#### Course Management
```bash
# Get courses
GET /api/courses/

# Get course details with modules
GET /api/courses/{id}/

# Get modules for course
GET /api/courses/{id}/modules/
```

#### Search & Statistics
```bash
# Global search
GET /api/search/?q=query&type=all&language=ar

# Content statistics
GET /api/stats/

# Home page data
GET /api/home-data/
```

For complete API documentation, see [BACKEND_API_DOCUMENTATION.md](BACKEND_API_DOCUMENTATION.md).

## ⚙️ Configuration

### Environment Configuration

The application uses environment-specific configuration files:

- `backend/config/settings/base.py` - Base settings
- `backend/config/settings/development.py` - Development overrides
- `backend/config/settings/production.py` - Production settings
- `backend/config/settings/local.py` - Local overrides (optional)

### Media Processing Configuration

```python
# Video processing settings
VIDEO_QUALITIES = ['720p', '480p']
VIDEO_CODECS = ['h264', 'vp9']
HLS_SEGMENT_DURATION = 10

# Audio processing settings  
AUDIO_BITRATE = 192000  # 192k bitrate
AUDIO_MAX_SIZE = 50 * 1024 * 1024  # 50MB limit

# PDF optimization settings
PDF_MAX_SIZE = 100 * 1024 * 1024  # 100MB limit
PDF_QUALITY = 85
```

### Caching Configuration

```python
# Redis caching
CACHES = {
    'default': {
        'BACKEND': 'django_redis.cache.RedisCache',
        'LOCATION': 'redis://localhost:6379/1',
        'TIMEOUT': 300,
        'OPTIONS': {
            'CLIENT_CLASS': 'django_redis.client.DefaultClient',
        }
    }
}

# Cache timeouts
CACHE_TIMEOUTS = {
    'content_list': 300,      # 5 minutes
    'course_detail': 600,     # 10 minutes  
    'user_profile': 1800,     # 30 minutes
    'navigation': 3600,       # 1 hour
}
```

### Security Configuration

```python
# Production security settings
SECURE_SSL_REDIRECT = True
SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SECURE_CONTENT_TYPE_NOSNIFF = True

# CSRF & Session security
CSRF_COOKIE_SECURE = True
SESSION_COOKIE_SECURE = True
SESSION_COOKIE_HTTPONLY = True
```

## 🔧 Troubleshooting

### Common Issues

#### 1. Media Processing Failures
```bash
# Check Celery worker status
docker-compose exec celery celery -A config inspect active

# View processing logs
docker-compose logs -f celery

# Restart media processing
docker-compose restart celery
```

#### 2. SSL Certificate Issues
```bash
# Verify certificate
openssl x509 -in ssl/fullchain.pem -text -noout

# Test SSL configuration
curl -I https://your-domain.com

# Restart nginx
docker-compose restart nginx
```

#### 3. Database Connection Issues
```bash
# Check database logs
docker-compose logs db

# Test database connection
docker-compose exec web python manage.py dbshell

# Reset database connections
docker-compose restart web
```

#### 4. Cache Issues
```bash
# Clear Redis cache
docker-compose exec redis redis-cli FLUSHALL

# Restart Redis
docker-compose restart redis

# Check cache status
docker-compose exec web python manage.py shell
>>> from django.core.cache import cache
>>> cache.get('test')
```

### Performance Optimization

#### Database Performance
```sql
-- Monitor slow queries
SELECT query, mean_time, calls 
FROM pg_stat_statements 
ORDER BY mean_time DESC 
LIMIT 10;

-- Check database connections
SELECT count(*) FROM pg_stat_activity;
```

#### Cache Performance
```bash
# Monitor Redis performance
docker-compose exec redis redis-cli info stats

# Check cache hit ratios
docker-compose exec redis redis-cli info keyspace
```

#### Media Processing Performance
```bash
# Monitor processing queue
docker-compose exec celery celery -A config inspect stats

# Check disk usage
df -h
du -sh backend/media/
```

## 🤝 Contributing

We welcome contributions to improve the Christian Library platform!

### Development Workflow

1. **Fork the repository**
2. **Create a feature branch**
   ```bash
   git checkout -b feature/your-feature-name
   ```
3. **Make your changes**
4. **Add tests** for new functionality
5. **Run the test suite**
   ```bash
   python manage.py test
   ```
6. **Submit a pull request**

### Code Standards

- **Python**: Follow PEP 8, use Black formatter
- **JavaScript**: Follow ESLint configuration  
- **HTML/CSS**: Follow BEM methodology for CSS classes
- **Documentation**: Update README and docstrings for new features

### Testing

```bash
# Run full test suite
python manage.py test

# Run specific app tests
python manage.py test apps.media_manager

# Run with coverage
coverage run --source='.' manage.py test
coverage report
```

### Translation

Help us improve translations:

```bash
# Extract new translatable strings
python manage.py makemessages -l ar -l en

# Update translations in locale/*/LC_MESSAGES/django.po
# Compile translations
python manage.py compilemessages
```

## 📄 License

This project is licensed under the MIT License. See [LICENSE](LICENSE) file for details.

## 📞 Support

- **Documentation**: See `docs/` directory for detailed guides
- **Issues**: Report bugs via GitHub Issues
- **Security**: Report security issues privately via email
- **Community**: Join our discussions in GitHub Discussions

## 🙏 Acknowledgments

- **Coptic Orthodox Community** for inspiration and requirements
- **Django Community** for the excellent framework
- **TailwindCSS** for the utility-first CSS framework
- **HTMX** for dynamic HTML capabilities
- **Contributors** who help maintain and improve this project

---

---

**Beta Version**: This is an early release for testing and feedback. Please report issues or suggestions via GitHub Issues.

**Built with ❤️ for the Coptic Orthodox community**