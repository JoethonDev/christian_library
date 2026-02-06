/**
 * Content Analytics Tracking Script
 * Sends AJAX requests to track content views after page load
 * Uses sendBeacon API for reliability and non-blocking tracking
 */

(function() {
    'use strict';
    
    /**
     * Track a content view via AJAX
     * @param {string} contentType - Type of content (video, audio, pdf)
     * @param {string} contentId - UUID of the content
     * @param {string} trackingUrl - The endpoint URL to send the tracking data
     */
    function trackContentView(contentType, contentId, trackingUrl) {
        // Validate inputs
        if (!contentType || !contentId || !trackingUrl) {
            console.warn('Analytics: Missing content type, ID, or URL');
            return;
        }
        
        // Prepare tracking data
        const trackingData = {
            content_type: contentType,
            content_id: contentId,
            timestamp: new Date().toISOString()
        };
        
        // Get CSRF token if available
        const csrfToken = getCsrfToken();
        
        // Try sendBeacon first (most reliable, doesn't block page)
        if (navigator.sendBeacon) {
            try {
                const blob = new Blob([JSON.stringify(trackingData)], {
                    type: 'application/json'
                });
                const success = navigator.sendBeacon(trackingUrl, blob);
                if (success) {
                    console.debug('Analytics: View tracked via sendBeacon');
                    return;
                }
            } catch (e) {
                console.debug('Analytics: sendBeacon failed, falling back to fetch');
            }
        }
        
        // Fallback to fetch API
        fetch(trackingUrl, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-Requested-With': 'XMLHttpRequest'
            },
            body: JSON.stringify(trackingData),
            keepalive: true // Keep request alive even if page unloads
        })
        .then(response => {
            if (response.ok) {
                console.debug('Analytics: View tracked via fetch');
            } else {
                console.warn('Analytics: Tracking failed with status', response.status);
            }
        })
        .catch(error => {
            // Silently fail - don't interrupt user experience
            console.debug('Analytics: Tracking error', error);
        });
    }
    
    /**
     * Get CSRF token from cookies or meta tag
     * @returns {string|null}
     */
    function getCsrfToken() {
        // Try meta tag first
        const metaTag = document.querySelector('meta[name="csrf-token"]');
        if (metaTag) {
            return metaTag.getAttribute('content');
        }
        
        // Try cookie
        const cookieMatch = document.cookie.match(/csrftoken=([^;]+)/);
        if (cookieMatch) {
            return cookieMatch[1];
        }
        
        return null;
    }
    
    /**
     * Initialize tracking when DOM is ready
     */
    function initTracking() {
        // Check if we're on a content detail page
        const trackingElement = document.querySelector('[data-analytics-track]');
        
        if (trackingElement) {
            const contentType = trackingElement.getAttribute('data-content-type');
            const contentId = trackingElement.getAttribute('data-content-id');
            const trackingUrl = trackingElement.getAttribute('data-tracking-url');
            
            if (contentType && contentId && trackingUrl) {
                // Add a small delay to ensure page is fully loaded
                // This prevents tracking bot/crawler visits
                setTimeout(function() {
                    trackContentView(contentType, contentId, trackingUrl);
                }, 500);
            }
        }
    }
    
    // Initialize when DOM is ready
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initTracking);
    } else {
        // DOM already loaded
        initTracking();
    }
    
    // Expose function globally for manual tracking if needed
    window.trackContentView = trackContentView;
})();
