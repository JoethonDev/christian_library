#!/bin/bash
# Example bash script for uploading content to Christian Library API using cURL

API_URL="${API_URL:-http://localhost:8000/api/v1}"
API_KEY="${API_KEY}"

if [ -z "$API_KEY" ]; then
    echo "Error: API_KEY environment variable not set"
    echo "Usage: API_KEY=your-key ./upload_example.sh /path/to/file.mp3"
    exit 1
fi

if [ -z "$1" ]; then
    echo "Error: No file specified"
    echo "Usage: API_KEY=your-key ./upload_example.sh /path/to/file.mp3"
    exit 1
fi

FILE_PATH="$1"

if [ ! -f "$FILE_PATH" ]; then
    echo "Error: File not found: $FILE_PATH"
    exit 1
fi

echo "Uploading $FILE_PATH..."

# Minimal upload (file only)
RESPONSE=$(curl -X POST "$API_URL/upload/" \
  -H "X-API-Secret-Key: $API_KEY" \
  -F "file=@$FILE_PATH" \
  -w "\n%{http_code}" \
  -s)

HTTP_CODE=$(echo "$RESPONSE" | tail -n1)
BODY=$(echo "$RESPONSE" | head -n-1)

if [ "$HTTP_CODE" -ge 200 ] && [ "$HTTP_CODE" -lt 300 ]; then
    echo "✓ Upload successful!"
    echo "$BODY" | python3 -m json.tool
    
    # Extract queue ID
    QUEUE_ID=$(echo "$BODY" | python3 -c "import sys, json; print(json.load(sys.stdin)['queue_id'])" 2>/dev/null)
    
    if [ -n "$QUEUE_ID" ]; then
        echo ""
        echo "Check status with:"
        echo "  curl -H \"X-API-Secret-Key: $API_KEY\" \"$API_URL/queue/status/$QUEUE_ID/\""
    fi
else
    echo "✗ Upload failed with HTTP $HTTP_CODE"
    echo "$BODY"
    exit 1
fi
