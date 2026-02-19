# Google Indexing API - Quick Setup Guide

## What This Does
Notifies Google immediately when content SEO changes, so new/updated items appear in search results within hours instead of days/weeks.

## Prerequisites
- Google Cloud Platform account
- Google Search Console access (site owner)
- Server access (to upload credentials)

---

## 5-Minute Setup

### 1. Create Google Cloud Project
1. Go to: https://console.cloud.google.com
2. Click "NEW PROJECT"
3. Name: "Library SEO Bot"
4. Click "CREATE"

### 2. Enable API
1. Go to "APIs & Services" → "Library"
2. Search: "Web Search Indexing API"
3. Click "ENABLE"

### 3. Create Service Account
1. Go to "APIs & Services" → "Credentials"
2. Click "CREATE CREDENTIALS" → "Service account"
3. Name: `library-indexing-bot`
4. Grant role: "Service Account User"
5. Click "DONE"

### 4. Download JSON Key
1. Click on service account name
2. Go to "KEYS" tab
3. Click "ADD KEY" → "Create new key" → "JSON"
4. **SAVE THE FILE** (you can't download it again!)

### 5. Add to Search Console
1. Go to: https://search.google.com/search-console
2. Select your site property
3. Go to "Settings" → "Users and permissions"
4. Click "ADD USER"
5. Email: **Copy `client_email` from JSON file**
   - Example: `library-indexing-bot@project-id.iam.gserviceaccount.com`
6. Permission: **Owner** (required!)
7. Click "ADD"

### 6. Deploy to Server

**Upload credentials:**
```bash
# Create secure directory
mkdir -p /opt/app/credentials
chmod 700 /opt/app/credentials

# Upload JSON file
scp google-service-account.json user@server:/opt/app/credentials/

# Set permissions
chmod 400 /opt/app/credentials/google-service-account.json
chown www-data:www-data /opt/app/credentials/google-service-account.json
```

**Add to environment:**
```bash
# Add to .env file
echo "GOOGLE_SERVICE_ACCOUNT_FILE=/opt/app/credentials/google-service-account.json" >> .env
```

**Or in docker-compose.yml:**
```yaml
services:
  web:
    environment:
      - GOOGLE_SERVICE_ACCOUNT_FILE=/credentials/google-service-account.json
    volumes:
      - ./credentials:/credentials:ro
```

### 7. Install Dependencies
```bash
pip install google-auth google-api-python-client
# Or
pip install -r requirements/base.txt
```

### 8. Restart Application
```bash
# Docker
docker-compose restart web

# Systemd
systemctl restart gunicorn
```

### 9. Verify It Works
```bash
# Check logs
tail -f logs/django.log | grep "Google notified"
```

Expected:
```
✓ Google notified about SEO changes for: {Title} | Type: video
```

---

## Environment Variable

Set ONE of these:

```bash
# Option 1: .env file
GOOGLE_SERVICE_ACCOUNT_FILE=/opt/app/credentials/google-service-account.json

# Option 2: System environment
export GOOGLE_SERVICE_ACCOUNT_FILE=/path/to/credentials.json

# Option 3: Docker Compose
environment:
  - GOOGLE_SERVICE_ACCOUNT_FILE=/credentials/google-service-account.json
```

---

## Testing

### Test 1: Create Content
1. Upload new video/audio/PDF
2. Check logs for: `✓ Google notified about SEO changes`

### Test 2: Update SEO
1. Edit content in admin
2. Change SEO title or description
3. Save
4. Check logs for notification

### Test 3: Delete Content
1. Delete content item
2. Check logs for: `✓ Google notified about content deletion`

---

## Troubleshooting

### "403 Forbidden"
**Problem:** Service account not added to Search Console

**Fix:**
1. Go to Search Console → Settings → Users
2. Add service account email as **Owner**
3. Wait 5 minutes

### "FileNotFoundError"
**Problem:** Credentials file path wrong

**Fix:**
```bash
# Check path
echo $GOOGLE_SERVICE_ACCOUNT_FILE
ls -la $GOOGLE_SERVICE_ACCOUNT_FILE

# Fix permissions
chmod 400 /path/to/file.json
chown www-data:www-data /path/to/file.json
```

### "No module named 'google.auth'"
**Problem:** Dependencies not installed

**Fix:**
```bash
pip install google-auth google-api-python-client
```

### No Notifications Appearing
**Check:**
1. ✅ Credentials file exists and readable
2. ✅ Service account added to Search Console as Owner
3. ✅ Dependencies installed
4. ✅ Application restarted
5. ✅ Environment variable set correctly

---

## What Gets Notified

### ✅ WILL Notify Google:
- New content uploaded
- SEO title changed (AR or EN)
- SEO description changed (AR or EN)
- SEO keywords changed
- Schema.org structured data updated
- Content deleted

### ❌ Won't Notify Google:
- View count updated
- Processing status changed
- Notes field updated
- File metadata changed
- Non-SEO field updates

This smart detection saves API quota and respects Google's rate limits.

---

## Security Checklist

- [ ] JSON key file NOT in version control
- [ ] File permissions: 400 (read-only)
- [ ] Stored outside web root
- [ ] Environment variable used (not hardcoded path)
- [ ] Only accessible to app user

---

## Need Help?

**Error Logs:**
```bash
tail -f /var/log/django/app.log | grep -i "google\|seo"
```

**Check Configuration:**
```bash
# Django shell
python manage.py shell

>>> from django.conf import settings
>>> print(settings.GOOGLE_SERVICE_ACCOUNT_FILE)
>>> import os
>>> print(os.path.exists(settings.GOOGLE_SERVICE_ACCOUNT_FILE))
```

**Reference:** See `docs/PHASE_3_IMPLEMENTATION_SUMMARY.md` for full details

---

## Rate Limits

- **200 requests/minute** (Google limit)
- **Unlimited daily quota** (for verified owners)

Our implementation stays well below limits by only notifying on SEO changes.

---

**Questions?** Contact: [Your Email]
**Documentation:** `docs/PHASE_3_IMPLEMENTATION_SUMMARY.md`
