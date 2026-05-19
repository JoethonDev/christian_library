#!/usr/bin/env python3
"""
Enhanced Bulk PDF and Word Document Upload Script for Christian Library API.
Scans for PDFs and matching Word documents, tracks progress in JSON.

Requirements:
    pip install requests
"""
import os
import sys
import json
import requests
import time
from typing import List, Dict, Any, Tuple
from datetime import datetime

# ====================== CONFIGURATION ======================
# 1. API Endpoint URL
API_URL = os.environ.get("API_URL", "https://anbaabraamlibrary.org/api/v1")

# 2. Authentication Key
API_SECRET_KEY = os.environ.get("API_SECRET_KEY", "p9FePk3FPIjFsLeHixcaBjRMJBI76NJ3")

# 3. Directory to scan (defaults to current directory)
SCAN_DIRECTORY = os.environ.get("SCAN_DIRECTORY", ".")

# 4. Tracking file to remember processed uploads
TRACKING_FILE = "upload_tracking.json"

# 5. Batch Size (Max 20 per API limitation)
MAX_BATCH_SIZE = 20

# 6. Supported Extensions
PDF_EXTS = ['.pdf']
DOC_EXTS = ['.doc', '.docx']
# ===========================================================

def load_tracking() -> Dict[str, Any]:
    """Load the tracking JSON file."""
    if os.path.exists(TRACKING_FILE):
        try:
            with open(TRACKING_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            print(f"Error loading tracking file: {e}. Starting fresh.")
    return {"processed_files": {}}

def save_tracking(tracking: Dict[str, Any]):
    """Save the tracking JSON file."""
    try:
        with open(TRACKING_FILE, 'w', encoding='utf-8') as f:
            json.dump(tracking, f, indent=4, ensure_ascii=False)
    except Exception as e:
        print(f"Error saving tracking file: {e}")

def get_file_pairs(directory: str) -> List[Dict[str, Any]]:
    """
    Dynamically scan the directory for PDFs and matching Word docs.
    Pairs them based on the filename (without extension).
    """
    print(f"Scanning directory: {os.path.abspath(directory)}...")
    
    all_files = []
    for root, _, files in os.walk(directory):
        for f in files:
            all_files.append(os.path.join(root, f))
            
    # Separate PDFs and DOCs
    pdfs = {} # basename -> full_path
    docs = {} # basename -> full_path
    
    for path in all_files:
        basename, ext = os.path.splitext(os.path.basename(path))
        ext = ext.lower()
        
        if ext in PDF_EXTS:
            pdfs[basename] = path
        elif ext in DOC_EXTS:
            docs[basename] = path
            
    pairs = []
    for basename, pdf_path in pdfs.items():
        doc_path = docs.get(basename)
        pairs.append({
            "name": basename,
            "pdf_path": pdf_path,
            "doc_path": doc_path,
            "has_doc": doc_path is not None
        })
        
    print(f"Found {len(pairs)} PDF candidates.")
    return pairs

def chunk_list(lst: List, n: int):
    """Yield successive n-sized chunks from lst."""
    for i in range(0, len(lst), n):
        yield lst[i:i + n]

def perform_bulk_upload(batch: List[Dict[str, Any]], api_key: str, tracking: Dict[str, Any]):
    """
    Upload a batch of files. 
    To maintain API index alignment, we ensure batches are homogeneous regarding doc_files.
    """
    endpoint = f"{API_URL}/upload/bulk/"
    headers = {"X-API-Secret-Key": api_key}
    
    # We check if this batch is mixed. If so, it should have been split before calling this.
    # But for safety, we'll verify.
    has_docs = [item['has_doc'] for item in batch]
    all_have_docs = all(has_docs)
    none_have_docs = not any(has_docs)
    
    if not (all_have_docs or none_have_docs):
        # This shouldn't happen with our refined main logic, but handle it:
        # Split into two call if mixed
        with_docs = [b for b in batch if b['has_doc']]
        without_docs = [b for b in batch if not b['has_doc']]
        if with_docs: perform_bulk_upload(with_docs, api_key, tracking)
        if without_docs: perform_bulk_upload(without_docs, api_key, tracking)
        return

    files_payload = []
    file_handles = []
    individual_metadata = []
    
    try:
        for item in batch:
            # Main PDF file
            pdf_path = item['pdf_path']
            fh = open(pdf_path, 'rb')
            file_handles.append(fh)
            files_payload.append(('files', (os.path.basename(pdf_path), fh, 'application/pdf')))
            
            # Matching Doc file if applicable
            if all_have_docs:
                doc_path = item['doc_path']
                dfh = open(doc_path, 'rb')
                file_handles.append(dfh)
                # Determine mime type
                mime = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document' if doc_path.endswith('.docx') else 'application/msword'
                files_payload.append(('doc_files', (os.path.basename(doc_path), dfh, mime)))
            
            # Metadata: title_ar is filename
            individual_metadata.append({
                "title_ar": item['name']
            })
            
        # Add metadata to request. For DRF ListField(child=JSONField()), 
        # we must send multiple entries with the same key name, each being a JSON string.
        data = {
            "individual_metadata": [json.dumps(m) for m in individual_metadata]
        }
        
        print(f"Sending batch of {len(batch)} files (Docs included: {all_have_docs})...")
        response = requests.post(
            endpoint, 
            headers=headers, 
            files=files_payload, 
            data=data,
            timeout=300 # 5 minute timeout for large batches
        )
        
        if response.status_code == 202:
            result = response.json()
            queue_items = result.get('queue_items', [])
            
            for i, q_item in enumerate(queue_items):
                pdf_path = batch[i]['pdf_path']
                if 'queue_id' in q_item:
                    print(f"  [OK] {q_item['file_name']} -> {q_item['queue_id']}")
                    tracking["processed_files"][pdf_path] = {
                        "status": "success",
                        "queue_id": q_item['queue_id'],
                        "timestamp": datetime.now().isoformat(),
                        "with_doc": batch[i]['has_doc'],
                        "doc_path": batch[i]['doc_path'],
                        "file_name": q_item['file_name']
                    }
                else:
                    err = q_item.get('error')
                    print(f"  [FAIL] {batch[i]['name']}: {err}")
                    tracking["processed_files"][pdf_path] = {
                        "status": "error",
                        "error": err,
                        "timestamp": datetime.now().isoformat()
                    }
            
            # Small delay between successful batches
            time.sleep(1)
        else:
            print(f"Error: Batch failed with status {response.status_code}")
            print(response.text)
            for item in batch:
                tracking["processed_files"][item['pdf_path']] = {
                    "status": "error",
                    "error": f"Batch failed with status {response.status_code}: {response.text[:200]}",
                    "timestamp": datetime.now().isoformat()
                }

    except requests.exceptions.Timeout:
        print("Error: Request timed out. The server might be busy or the files are too large.")
    except Exception as e:
        print(f"Critical error processing batch: {e}")
        import traceback
        traceback.print_exc()
    finally:
        for fh in file_handles:
            fh.close()
        save_tracking(tracking)

def main():
    if API_SECRET_KEY == "YOUR_API_KEY_HERE":
        print("Warning: API_SECRET_KEY is not set. Please set it in CONFIGURATION or environment variable.")
        
    tracking = load_tracking()
    all_pairs = get_file_pairs(SCAN_DIRECTORY)
    
    # Filter out already processed files
    to_process = [p for p in all_pairs if p['pdf_path'] not in tracking["processed_files"] or tracking["processed_files"][p['pdf_path']].get('status') != 'success']
    
    if not to_process:
        print("All files already successfully processed. Nothing to do.")
        return
        
    print(f"Remaining to process: {len(to_process)} files.")
    
    # Group by presence of doc to avoid mixing in bulk API calls (alignment issue)
    with_docs = [p for p in to_process if p['has_doc']]
    without_docs = [p for p in to_process if not p['has_doc']]
    
    success_count = 0
    
    # Process files WITH docs
    if with_docs:
        print(f"\nProcessing {len(with_docs)} files WITH matching documents...")
        for batch in chunk_list(with_docs, MAX_BATCH_SIZE):
            perform_bulk_upload(batch, API_SECRET_KEY, tracking)
            
    # Process files WITHOUT docs
    if without_docs:
        print(f"\nProcessing {len(without_docs)} files WITHOUT matching documents...")
        for batch in chunk_list(without_docs, MAX_BATCH_SIZE):
            perform_bulk_upload(batch, API_SECRET_KEY, tracking)

    # Summary
    processed = tracking["processed_files"]
    succeeded = sum(1 for p in processed.values() if p.get('status') == 'success')
    failed = sum(1 for p in processed.values() if p.get('status') == 'error')
    
    print("\n" + "="*40)
    print(f"Final Summary:")
    print(f"Total encountered: {len(all_pairs)}")
    print(f"Successfully uploaded: {succeeded}")
    print(f"Failed/Pending:        {failed}")
    print(f"Tracking saved to: {TRACKING_FILE}")
    print("="*40)

if __name__ == "__main__":
    main()
