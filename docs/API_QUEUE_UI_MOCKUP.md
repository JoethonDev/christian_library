# API Upload Queue Dashboard - Visual Overview

## Main Queue List View

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ 📊 API Upload Queue                                           🔄 Refresh    │
│ Monitor and manage API upload requests                                      │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐                  │
│  │ ⏳       │  │ 🔄       │  │ ✅       │  │ ⚠️       │                  │
│  │ In Queue │  │ Process  │  │ Complete │  │ Rate Lmt │                  │
│  │    5     │  │    2     │  │   128    │  │    3     │                  │
│  └──────────┘  └──────────┘  └──────────┘  └──────────┘                  │
│                                                                             │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐                    │
│  │ 🎥 Video: 2  │  │ 🎵 Audio: 3  │  │ 📄 PDF: 1    │                    │
│  └──────────────┘  └──────────────┘  └──────────────┘                    │
│                                                                             │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  Filter: [All Statuses ▼]  [All Types ▼]           Total: 138 items       │
│                                                                             │
│  ┌───────────────────────────────────────────────────────────────────────┐ │
│  │ File Name          │Type│Size │Status   │Queue │Pos│Created │Actions │ │
│  ├───────────────────────────────────────────────────────────────────────┤ │
│  │ sermon_video.mp4   │ 🎥 │125MB│Queued   │Ready │#1 │18:00   │↑ ✕ 👁 │ │
│  │ → عظة عن المحبة    │    │     │         │      │   │        │        │ │
│  ├───────────────────────────────────────────────────────────────────────┤ │
│  │ audio_message.mp3  │ 🎵 │45MB │Process..│Ready │#2 │18:05   │   👁  │ │
│  │                    │    │     │ 🔄      │      │   │        │        │ │
│  ├───────────────────────────────────────────────────────────────────────┤ │
│  │ book_chapter.pdf   │ 📄 │12MB │Pending  │Wait  │#3 │18:10   │↑ ✕ 👁 │ │
│  │ + doc file         │    │     │         │      │   │        │        │ │
│  ├───────────────────────────────────────────────────────────────────────┤ │
│  │ delayed_video.mp4  │ 🎥 │200MB│RateLmt  │Delay │#4 │17:30   │↑ ✕ 👁 │ │
│  │                    │    │     │ ⚠️     │      │ 2/7│→3:00AM │        │ │
│  ├───────────────────────────────────────────────────────────────────────┤ │
│  │ failed_audio.mp3   │ 🎵 │30MB │Failed   │-     │-  │17:00   │   👁  │ │
│  │                    │    │     │ ❌     │      │   │        │        │ │
│  └───────────────────────────────────────────────────────────────────────┘ │
│                                                                             │
│  [← Previous]  [1] [2] [3] ... [8]  [Next →]                              │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘

Auto-refreshing every 30 seconds...
```

## Item Detail View

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ Dashboard > API Queue > sermon_video.mp4                    [← Back to Queue]│
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌──────────────────────────────────────┐  ┌─────────────────────────────┐ │
│  │ 📁 File Information                  │  │ 📊 Status                   │ │
│  │ ──────────────────────────────────── │  │ ───────────────────────────│ │
│  │                                      │  │                             │ │
│  │ File Name: sermon_video.mp4          │  │ Status: Queued              │ │
│  │ Type: 🎥 Video                       │  │         [🔵 Queued]        │ │
│  │ Size: 125.50 MB                      │  │                             │ │
│  │ Position: #1                         │  │ Queue: Ready                │ │
│  │                                      │  │        [✅ Ready]           │ │
│  │ ──────────────────────────────────── │  │                             │ │
│  │                                      │  │ Priority: 0                 │ │
│  │ 📝 Metadata                          │  │ Delays: 0/7                 │ │
│  │ ──────────────────────────────────── │  │ Gemini: 0                   │ │
│  │                                      │  │                             │ │
│  │ Arabic Title:                        │  │ ───────────────────────────│ │
│  │   عظة عن المحبة والرحمة             │  │                             │ │
│  │                                      │  │ Created:                    │ │
│  │ English Title:                       │  │   2026-02-20 18:00:15      │ │
│  │   Sermon on Love and Mercy           │  │                             │ │
│  │                                      │  │ Scheduled: -                │ │
│  │ Arabic Description:                  │  │                             │ │
│  │   عظة رائعة تتحدث عن محبة الله      │  │ ───────────────────────────│ │
│  │   للبشرية...                        │  │                             │ │
│  │                                      │  │ 🎬 Actions                 │ │
│  └──────────────────────────────────────┘  │                             │ │
│                                            │ [↑ Promote]                 │ │
│                                            │                             │ │
│                                            │ [✕ Cancel]                  │ │
│                                            │                             │ │
│                                            └─────────────────────────────┘ │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Status Badge Colors

```
┌────────────────────────────────────────────┐
│ Status Badges                              │
├────────────────────────────────────────────┤
│ [⚪ Pending   ] Gray - Just added          │
│ [🔵 Queued   ] Blue - In queue             │
│ [🔄 Processing] Blue - Being processed     │
│ [✅ Completed ] Green - Success            │
│ [❌ Failed    ] Red - Error                │
│ [⚠️ Rate Lmt  ] Yellow - Delayed           │
│ [⚫ Cancelled ] Dark - Cancelled           │
└────────────────────────────────────────────┘

┌────────────────────────────────────────────┐
│ Queue Status Badges                        │
├────────────────────────────────────────────┤
│ [⏳ Waiting  ] Light - Waiting in line     │
│ [⚠️ Delayed  ] Yellow - Scheduled 3 AM     │
│ [✅ Ready    ] Green - Ready to process    │
└────────────────────────────────────────────┘

┌────────────────────────────────────────────┐
│ Delay Count Colors                         │
├────────────────────────────────────────────┤
│ 0-2 delays: [⚪ 1/7] Gray - OK            │
│ 3-4 delays: [⚠️ 3/7] Yellow - Warning     │
│ 5-6 delays: [🔴 5/7] Red - Critical       │
│ 7 delays:   [⚫ 7/7] Auto-cancelled       │
└────────────────────────────────────────────┘
```

## Mobile View

```
┌───────────────────────────┐
│ ☰ API Upload Queue  🔄   │
├───────────────────────────┤
│                           │
│ ┌───────────────────────┐ │
│ │ ⏳ In Queue           │ │
│ │      5                │ │
│ └───────────────────────┘ │
│                           │
│ ┌───────────────────────┐ │
│ │ 🔄 Processing         │ │
│ │      2                │ │
│ └───────────────────────┘ │
│                           │
│ Filter: [All Statuses ▼] │
│         [All Types    ▼] │
│                           │
├───────────────────────────┤
│ sermon_video.mp4          │
│ 🎥 Video | 125MB          │
│ [🔵 Queued] #1            │
│ [↑][✕][👁]               │
├───────────────────────────┤
│ audio_message.mp3         │
│ 🎵 Audio | 45MB           │
│ [🔄 Processing]           │
│ [👁]                      │
├───────────────────────────┤
│ book_chapter.pdf          │
│ 📄 PDF | 12MB             │
│ [⚪ Pending] #3           │
│ [↑][✕][👁]               │
└───────────────────────────┘
```

## Action Confirmations

### Promote Action
```
┌──────────────────────────────────────┐
│ ✅ Success                            │
├──────────────────────────────────────┤
│ Queue item "sermon_video.mp4" has    │
│ been promoted and will be processed  │
│ immediately.                         │
│                                      │
│ [OK]                                 │
└──────────────────────────────────────┘
```

### Cancel Action
```
┌──────────────────────────────────────┐
│ ⚠️ Confirm Cancellation               │
├──────────────────────────────────────┤
│ Are you sure you want to cancel      │
│ this queue item?                     │
│                                      │
│ File: sermon_video.mp4               │
│                                      │
│ This action cannot be undone.        │
│                                      │
│ [Cancel] [Confirm]                   │
└──────────────────────────────────────┘
```

## Navigation

```
Admin Sidebar:
┌─────────────────────┐
│ 🛡️ Admin            │
├─────────────────────┤
│ 📊 Dashboard        │
│ ☁️  Upload Content   │
├─────────────────────┤
│ Content Management  │
│ 📚 All Content      │
│ 🎥 Videos           │
│ 🎵 Audio            │
│ 📄 PDFs             │
├─────────────────────┤
│ Analytics & System  │
│ ✓ 📋 API Queue ←    │  (NEW!)
│ 📊 Analytics        │
│ 📈 SEO Dashboard    │
│ 💻 System Monitor   │
└─────────────────────┘
```

## Key Features Highlighted

### 1. Real-Time Statistics
Four metric cards show:
- Items waiting in queue
- Currently processing
- Successfully completed
- Rate limited items

### 2. Content Type Breakdown
Three cards show active items by type:
- Video uploads
- Audio uploads
- PDF uploads

### 3. Comprehensive Table
All important information at a glance:
- File name with content link
- Type badge with icon
- File size
- Processing status
- Queue status
- Position in queue
- Timestamps
- Delay count
- Quick actions

### 4. Filtering
Easy dropdown filters for:
- Status (8 options)
- Content type (3 options)

### 5. Action Buttons
Quick access to:
- ↑ Promote (boost priority)
- ✕ Cancel (remove from queue)
- 👁 View Details (full information)

### 6. Auto-Refresh
Page updates every 30 seconds automatically

### 7. Mobile Responsive
Works perfectly on all screen sizes

## Color Coding Guide

| Element | Color | Meaning |
|---------|-------|---------|
| Gray badge | Secondary | Pending, waiting |
| Blue badge | Primary/Info | Queued, processing |
| Green badge | Success | Completed, ready |
| Yellow badge | Warning | Rate limited, delayed |
| Red badge | Danger | Failed, critical delays |
| Dark badge | Dark | Cancelled |

## Summary

The Admin Dashboard provides a complete, user-friendly interface for managing the API upload queue. Administrators can:

✅ **Monitor** all queue items and statistics
✅ **Filter** by status and content type
✅ **Promote** urgent items to skip queue
✅ **Cancel** unwanted items
✅ **View** detailed information and errors
✅ **Track** processing progress in real-time
✅ **Access** from mobile devices

All with a clean, Bootstrap 5-based design that matches the existing admin theme!
