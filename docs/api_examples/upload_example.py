#!/usr/bin/env python3
"""
Example Python script for uploading content to Christian Library API.

Requirements:
    pip install requests

Usage:
    python upload_example.py --file sermon.mp3 --title-ar "عظة عن المحبة" --title-en "Sermon on Love" --api-key YOUR_KEY
"""
import argparse
import os
import sys
import time
import requests


class ChristianLibraryAPI:
    """Client for Christian Library Upload API."""
    
    def __init__(self, api_url, api_key):
        """Initialize API client."""
        self.api_url = api_url
        self.headers = {'X-API-Secret-Key': api_key}
    
    def upload_file(self, file_path, **metadata):
        """Upload a single file with optional metadata."""
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"File not found: {file_path}")
        
        with open(file_path, 'rb') as f:
            files = {'file': f}
            response = requests.post(
                f'{self.api_url}/upload/',
                headers=self.headers,
                files=files,
                data=metadata
            )
        
        response.raise_for_status()
        return response.json()
    
    def get_queue_status(self, queue_id):
        """Get status of a queue item."""
        response = requests.get(
            f'{self.api_url}/queue/status/{queue_id}/',
            headers=self.headers
        )
        response.raise_for_status()
        return response.json()


def main():
    parser = argparse.ArgumentParser(description='Upload content to Christian Library API')
    parser.add_argument('--api-url', default='http://localhost:8000/api/v1', help='API base URL')
    parser.add_argument('--api-key', required=True, help='API secret key')
    parser.add_argument('--file', required=True, help='File to upload')
    parser.add_argument('--title-ar', help='Arabic title')
    parser.add_argument('--title-en', help='English title')
    
    args = parser.parse_args()
    
    # Initialize API client
    api = ChristianLibraryAPI(args.api_url, args.api_key)
    
    # Prepare metadata
    metadata = {}
    if args.title_ar:
        metadata['title_ar'] = args.title_ar
    if args.title_en:
        metadata['title_en'] = args.title_en
    
    try:
        # Upload file
        print(f"Uploading {args.file}...")
        result = api.upload_file(args.file, **metadata)
        
        print(f"\nUpload successful!")
        print(f"Queue ID: {result['queue_id']}")
        print(f"Status: {result['status']}")
        print(f"Queue Position: {result['queue_position']}")
    
    except requests.exceptions.HTTPError as e:
        print(f"Error: {e.response.status_code} - {e.response.text}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
