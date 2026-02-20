# API Upload Examples

This directory contains example scripts for uploading content to the Christian Library API.

## Available Examples

### 1. Python Example (`upload_example.py`)

A complete Python client for the Christian Library API.

**Requirements:**
```bash
pip install requests
```

**Usage:**
```bash
# Minimal upload (file only)
python upload_example.py \
  --api-key YOUR_SECRET_KEY \
  --file sermon.mp3

# Full upload with metadata
python upload_example.py \
  --api-key YOUR_SECRET_KEY \
  --file sermon.mp3 \
  --title-ar "عظة عن المحبة" \
  --title-en "Sermon on Love"
```

### 2. Bash/cURL Example (`upload_example.sh`)

Simple bash script using cURL for quick uploads.

**Usage:**
```bash
# Set API key
export API_KEY="your-secret-key"

# Upload file
./upload_example.sh /path/to/file.mp3

# Or in one line
API_KEY="your-key" ./upload_example.sh sermon.mp3
```

## Quick Start

1. **Get your API key** from the administrator
2. **Set the API key** as an environment variable:
   ```bash
   export API_KEY="your-secret-key-here"
   ```

3. **Upload a file** using any example script:
   ```bash
   # Python
   python upload_example.py --api-key $API_KEY --file sermon.mp3
   
   # Bash
   ./upload_example.sh sermon.mp3
   ```

4. **Check the status**:
   ```bash
   curl -H "X-API-Secret-Key: $API_KEY" \
     "http://localhost:8000/api/v1/queue/status/QUEUE_ID/"
   ```

## Configuration

All examples support the following environment variables:

- `API_KEY`: Your API secret key (required)
- `API_URL`: Base API URL (default: `http://localhost:8000/api/v1`)

## Common Workflows

### Upload and Wait for Completion

```python
#!/usr/bin/env python3
import sys
from upload_example import ChristianLibraryAPI

api = ChristianLibraryAPI(
    api_url="https://your-domain.com/api/v1",
    api_key="your-secret-key"
)

# Upload file
result = api.upload_file("sermon.mp3", 
    title_ar="عظة عن المحبة",
    title_en="Sermon on Love"
)

print(f"Uploaded: {result['queue_id']}")

# Wait for completion
import time
while True:
    status = api.get_queue_status(result['queue_id'])
    print(f"Status: {status['status']}")
    
    if status['status'] == 'completed':
        print(f"Content ID: {status['content_item_id']}")
        break
    elif status['status'] == 'failed':
        print(f"Failed: {status['error_message']}")
        sys.exit(1)
    
    time.sleep(10)
```

### Bulk Upload Multiple Files

```bash
#!/bin/bash
# Upload all MP3 files in a directory

API_KEY="your-secret-key"

for file in *.mp3; do
    echo "Uploading $file..."
    python upload_example.py --api-key "$API_KEY" --file "$file"
    sleep 2  # Rate limit friendly
done
```

## Error Handling

All examples include basic error handling. Common errors:

- **401 Unauthorized**: Invalid or missing API key
- **429 Too Many Requests**: Rate limit exceeded (100/hour)
- **400 Bad Request**: Invalid file type or size

## Support

For more information, see the full [API Documentation](../API_UPLOAD_DOCUMENTATION.md).
