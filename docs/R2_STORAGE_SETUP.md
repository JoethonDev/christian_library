# R2 Storage Configuration Guide

This document provides instructions for setting up and configuring Cloudflare R2 storage for the Christian Library application.

## Overview

Cloudflare R2 is an S3-compatible object storage service that provides cost-effective storage for media files (videos, audio, PDFs). The application uses R2 to:

- Store processed media files (HLS video streams, compressed audio, optimized PDFs)
- Reduce local server storage requirements
- Provide fast CDN delivery for media content
- Display storage usage statistics in the admin dashboard

## Prerequisites

- Active Cloudflare account
- R2 storage enabled on your Cloudflare account
- R2 bucket created

## Configuration Steps

### 1. Create an R2 Bucket

1. Log in to your Cloudflare dashboard
2. Navigate to **R2 Object Storage**
3. Click **Create bucket**
4. Enter a bucket name (e.g., `christian-library-media`)
5. Click **Create bucket**

### 2. Generate R2 API Credentials

1. In the Cloudflare R2 dashboard, click **Manage R2 API Tokens**
2. Click **Create API Token**
3. Configure token permissions:
   - **Token name**: `christian-library-api`
   - **Permissions**: Read and Write
   - **Bucket scope**: Select your bucket or "All buckets"
4. Click **Create API Token**
5. **Important**: Copy and save the following credentials:
   - Access Key ID
   - Secret Access Key
   - Endpoint URL (format: `https://<account-id>.r2.cloudflarestorage.com`)

### 3. Configure Environment Variables

Add the following environment variables to your `.env` file or deployment configuration:

```bash
# Enable R2 storage
R2_ENABLED=true

# R2 bucket name
R2_BUCKET_NAME=christian-library-media

# R2 API credentials (from step 2)
R2_ACCESS_KEY_ID=your_access_key_id_here
R2_SECRET_ACCESS_KEY=your_secret_access_key_here

# R2 endpoint URL (from step 2)
R2_ENDPOINT_URL=https://<your-account-id>.r2.cloudflarestorage.com

# Optional: R2 region (default: auto)
R2_REGION_NAME=auto
```

### 4. Restart the Application

After configuring the environment variables, restart your Django application.

## Verifying R2 Configuration

### Check R2 Status in Admin Dashboard

1. Log in to the admin dashboard
2. Navigate to **Dashboard** (main page)
3. Scroll to the **R2 Storage Usage** section
4. You should see:
   - Total storage used (in GB)
   - Total number of objects
   - Last updated timestamp
   - Refresh button

## Storage Usage Reporting

### API Endpoint

The R2 storage usage data is available via REST API:

```
GET /api/admin/r2-storage-usage/
```

**Query Parameters:**
- `refresh=true` - Force refresh (bypass 5-minute cache)

**Response Format:**
```json
{
  "success": true,
  "total_size_bytes": 1234567890,
  "total_size_gb": 1.15,
  "object_count": 42,
  "last_updated": "2026-02-03T22:00:00Z"
}
```

### Caching

Storage usage data is cached for **5 minutes** to reduce API calls to Cloudflare R2.

## Troubleshooting

### R2 Storage Not Showing

**Solutions:**
1. Verify `R2_ENABLED=true` in environment variables
2. Check that all required R2 settings are configured
3. Restart the application after configuration changes
4. Check application logs for R2 initialization errors

## Security Best Practices

1. **Never commit API credentials** to version control
2. Use environment variables for all sensitive configuration
3. Restrict API token permissions to specific buckets
4. Rotate API tokens periodically
5. Use HTTPS for all R2 communication

## Related Documentation

- [Cloudflare R2 Documentation](https://developers.cloudflare.com/r2/)
- [AWS S3 API Compatibility](https://developers.cloudflare.com/r2/api/s3/)
