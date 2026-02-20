# API Upload Queue Admin Dashboard

## Overview

The Admin Dashboard now includes a comprehensive UI for managing the API upload queue. This allows administrators to monitor, promote, and cancel API upload requests directly from the web interface.

## Access

Navigate to: **Dashboard → API Upload Queue** from the admin sidebar

Direct URL: `/en/dashboard/api-queue/` (or `/ar/dashboard/api-queue/` for Arabic)

## Features

### Queue List View

The main queue list displays all API upload queue items with the following features:

#### Statistics Dashboard
- **In Queue**: Shows total pending + queued items
- **Processing**: Currently processing items
- **Completed**: Successfully completed uploads
- **Rate Limited**: Items waiting for 3 AM processing

#### Content Type Breakdown
- Video uploads count
- Audio uploads count  
- PDF uploads count

#### Queue Items Table

Each row shows:
- **File Name**: Name of the uploaded file
  - If completed, shows link to created content item
- **Type**: Badge indicating video/audio/pdf
- **Size**: File size in MB
- **Status**: Current processing status
  - Pending (gray)
  - Queued (blue)
  - Processing (blue with spinner)
  - Completed (green)
  - Failed (red)
  - Rate Limited (yellow)
  - Cancelled (dark)
- **Queue Status**: waiting/delayed/ready
- **Position**: Queue position (for pending/queued items)
- **Created**: When item was added to queue
- **Scheduled**: Next scheduled processing time (for rate-limited items)
- **Delays**: Delay count out of 7 maximum
  - Color coded: 0-2 (gray), 3-4 (yellow), 5+ (red)
- **Actions**: Quick action buttons
  - Promote (arrow up) - Process immediately
  - Cancel (X) - Cancel queue item
  - View Details (eye) - See full details

#### Filtering

Filter queue items by:
- **Status**: All, Pending, Queued, Processing, Completed, Failed, Rate Limited, Cancelled
- **Content Type**: All Types, Video, Audio, PDF

#### Auto-Refresh

The page automatically refreshes every 30 seconds to show latest queue status.

### Queue Item Detail View

Click the eye icon or file name to see detailed information:

#### File Information
- File name
- Content type (with icon)
- File size
- Queue position
- Document file (if provided for PDF)

#### Metadata
- Arabic title
- English title
- Arabic description
- English description
- Other optional fields

#### Status Information
- Current status (with badge)
- Queue status
- Priority level
- Delay count
- Gemini attempts
- Timestamps:
  - Created at
  - Scheduled for (if delayed)
  - Processing started at
  - Completed at

#### Error Messages
If the item failed, shows the full error message in a red-bordered box.

#### Actions
- **Promote**: Boost priority to process immediately
- **Cancel**: Remove from queue

#### Content Link
If processing completed successfully, shows a link to view the created content item.

### Admin Actions

#### Promote Queue Item

**Purpose**: Move an item to the front of the queue for immediate processing

**When to use**:
- Urgent content needs to be published quickly
- An important upload is stuck in queue
- Testing queue processing

**How**:
1. Click the up arrow button on the queue list
2. Or click "Promote" button on the detail page
3. Confirmation message will appear
4. Item priority is set to 1000 (highest)
5. Item is marked as ready for processing

**Note**: Promotes item within its content type only (respects type-based locking)

#### Cancel Queue Item

**Purpose**: Remove an item from the queue without processing

**When to use**:
- Wrong file was uploaded
- Upload no longer needed
- Item has been failing repeatedly
- Delay count approaching limit (7 days)

**How**:
1. Click the X button on the queue list
2. Or click "Cancel" button on the detail page
3. Confirm the cancellation
4. Item status changes to "cancelled"
5. Temporary files are cleaned up

**Note**: Cannot be undone - file must be re-uploaded if needed

## Queue Management Best Practices

### Monitoring

1. **Check the queue regularly** - Look for items stuck in pending/queued
2. **Watch delay counts** - Items with 5+ delays need attention
3. **Review failed items** - Check error messages and fix issues
4. **Monitor processing items** - Ensure they complete in reasonable time

### Rate Limit Management

When Gemini API rate limit is hit:
1. Items automatically scheduled for next day 3:00 AM
2. Delay count increments
3. After 7 delays, items are auto-cancelled
4. Manual promotion can force processing if needed

### Priority Management

- Default priority: 0
- Promoted items: 1000
- Higher priority items process first within their type
- Use sparingly to avoid queue bottlenecks

### Content Type Concurrency

The system processes one item per content type at a time:
- 1 video processing
- 1 audio processing  
- 1 PDF processing

This prevents resource contention and ensures stable processing.

## Troubleshooting

### Item Stuck in "Pending"

**Cause**: Another item of same type is processing

**Solution**: 
- Wait for current item to complete
- Or promote if urgent

### Item in "Rate Limited" for Multiple Days

**Cause**: Gemini API quota repeatedly exceeded

**Options**:
1. Wait for automatic 3 AM processing
2. Promote to try immediately
3. Cancel if no longer needed
4. Check Gemini quota limits

### Item Failed with Error

**Cause**: Processing error (check error message)

**Solutions**:
1. Review error message in detail view
2. Fix any file format issues
3. Re-upload file if corrupted
4. Check Gemini API availability

### Queue Growing Too Large

**Causes**: 
- Too many uploads
- Processing slower than uploads
- Rate limits being hit frequently

**Solutions**:
1. Promote urgent items
2. Cancel unnecessary items
3. Spread uploads over time
4. Increase Gemini quota if needed

## Statistics Interpretation

### Healthy Queue
- In Queue: < 10 items
- Processing: 1-3 items
- Rate Limited: 0-2 items
- Failed: 0 items

### Needs Attention
- In Queue: > 20 items
- Processing: Items not moving
- Rate Limited: > 5 items
- Failed: > 3 items

## Integration with API

The dashboard displays items created via the API endpoints:
- `POST /api/v1/upload/` - Single upload
- `POST /api/v1/upload/bulk/` - Bulk upload

All queue actions (promote, cancel) can also be done via API:
- `POST /api/v1/queue/<id>/promote/`
- `DELETE /api/v1/queue/<id>/cancel/`

## Screenshots

### Queue List View
[Screenshot of main queue list with statistics and table]

### Queue Item Detail
[Screenshot of detailed view with all information]

### Mobile View
[Screenshot showing responsive design on mobile]

## Related Documentation

- [API Upload Documentation](../API_UPLOAD_DOCUMENTATION.md) - API reference
- [Implementation Summary](../RESTFUL_API_IMPLEMENTATION_SUMMARY.md) - Technical details
- [Example Scripts](../api_examples/) - API usage examples

## Support

For issues or questions:
1. Check queue error messages
2. Review API logs at `/admin/tasks/`
3. Contact system administrator
