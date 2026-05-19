"""
Search Settings Service - Manages global search sensitivity configuration
Provides cached access to search threshold settings for optimal performance.
"""
import logging
from django.core.cache import cache
from django.db import transaction

logger = logging.getLogger(__name__)


class SearchSettingsService:
    """
    Singleton service for managing search sensitivity settings.
    Provides cached access with automatic invalidation.
    """
    
    CACHE_KEY = 'search_sensitivity_settings'
    CACHE_TIMEOUT = 300  # 5 minutes
    
    _instance = None
    
    def __new__(cls):
        """Singleton pattern to ensure single instance"""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def get_current_threshold(self):
        """
        Get the current search threshold value.
        Returns cached value if available, otherwise fetches from database.
        
        Returns:
            float: Threshold value between 0.0 and 1.0
        """
        settings = self._get_cached_settings()
        return settings.get('threshold', 0.1)
    
    def get_sensitivity_mode(self):
        """
        Get the current sensitivity mode name.
        
        Returns:
            str: Mode name ('exact', 'strict', 'normal', 'relaxed', 'custom')
        """
        settings = self._get_cached_settings()
        return settings.get('mode', 'normal')
    
    def get_all_settings(self):
        """
        Get all current search settings including metadata.
        
        Returns:
            dict: Complete settings dictionary with mode, threshold, and description
        """
        return self._get_cached_settings()
    
    def update_settings(self, mode, custom_threshold=None, user=None):
        """
        Update search sensitivity settings and invalidate cache.
        
        Args:
            mode (str): New sensitivity mode
            custom_threshold (float, optional): Custom threshold value (only for 'custom' mode)
            user (User, optional): User making the change (for audit logging)
        
        Returns:
            tuple: (success: bool, message: str, settings: dict)
        """
        from apps.media_manager.models import SiteConfiguration
        
        try:
            with transaction.atomic():
                # Get or create site configuration
                config = SiteConfiguration.objects.first()
                if not config:
                    config = SiteConfiguration.objects.create()
                
                # Validate mode
                valid_modes = ['exact', 'strict', 'normal', 'relaxed', 'custom']
                if mode not in valid_modes:
                    return False, f"Invalid mode. Must be one of: {', '.join(valid_modes)}", {}
                
                # Validate custom threshold
                if mode == 'custom':
                    if custom_threshold is None:
                        custom_threshold = config.search_custom_threshold
                    try:
                        custom_threshold = float(custom_threshold)
                        if not 0.0 <= custom_threshold <= 1.0:
                            return False, "Custom threshold must be between 0.0 and 1.0", {}
                    except (ValueError, TypeError):
                        return False, "Invalid custom threshold value", {}
                    config.search_custom_threshold = custom_threshold
                
                # Store old values for audit log
                old_mode = config.search_sensitivity_mode
                old_threshold = config.get_search_threshold()
                
                # Update configuration
                config.search_sensitivity_mode = mode
                config.save()
                
                # Invalidate cache
                self._invalidate_cache()
                
                # Log the change for audit purposes
                new_threshold = config.get_search_threshold()
                self._log_settings_change(
                    old_mode=old_mode,
                    new_mode=mode,
                    old_threshold=old_threshold,
                    new_threshold=new_threshold,
                    user=user
                )
                
                # Return new settings
                new_settings = self._get_cached_settings()
                
                return True, f"Search sensitivity updated to '{mode}' mode", new_settings
                
        except Exception as e:
            logger.error(f"Error updating search settings: {str(e)}", exc_info=True)
            return False, f"Error updating settings: {str(e)}", {}
    
    def get_mode_description(self, mode=None):
        """
        Get human-readable description for a sensitivity mode.
        
        Args:
            mode (str, optional): Mode to describe. If None, uses current mode.
        
        Returns:
            str: Description text
        """
        if mode is None:
            mode = self.get_sensitivity_mode()
        
        descriptions = {
            'exact': 'Returns only results where the search term appears exactly or with 1 character difference. Best for finding specific known content.',
            'strict': 'Only shows highly relevant matches with strong semantic similarity. Reduces noise but may miss some valid results. Ideal for precise research.',
            'normal': 'Balanced approach returning relevant results with good precision. Recommended for most searches.',
            'relaxed': 'More inclusive results, catching partial matches and words with 1-2 character differences. Useful for exploratory searches.',
            'custom': 'Custom threshold allows fine-tuned control. Lower values (closer to 0.0) return more results but may include less relevant matches.'
        }
        return descriptions.get(mode, descriptions['normal'])
    
    def get_threshold_for_mode(self, mode):
        """
        Get the threshold value for a specific mode without changing settings.
        
        Args:
            mode (str): Mode to check
        
        Returns:
            float: Threshold value for that mode
        """
        from apps.media_manager.models import SiteConfiguration
        
        if mode == 'custom':
            config = SiteConfiguration.objects.first()
            return config.search_custom_threshold if config else 0.1
        
        threshold_map = {
            'exact': 0.5,
            'strict': 0.3,
            'normal': 0.1,
            'relaxed': 0.05,
        }
        return threshold_map.get(mode, 0.1)
    
    def _get_cached_settings(self):
        """
        Internal method to get settings from cache or database.
        
        Returns:
            dict: Settings dictionary
        """
        # Try cache first
        cached_settings = cache.get(self.CACHE_KEY)
        if cached_settings:
            return cached_settings
        
        # Fetch from database
        from apps.media_manager.models import SiteConfiguration
        
        try:
            config = SiteConfiguration.objects.first()
            if not config:
                # Create default configuration
                config = SiteConfiguration.objects.create()
            
            settings = {
                'mode': config.search_sensitivity_mode,
                'threshold': config.get_search_threshold(),
                'custom_threshold': config.search_custom_threshold,
                'description': config.get_mode_description(),
                'updated_at': config.updated_at.isoformat() if config.updated_at else None
            }
            
            # Cache the settings
            cache.set(self.CACHE_KEY, settings, self.CACHE_TIMEOUT)
            
            return settings
            
        except Exception as e:
            logger.error(f"Error fetching search settings: {str(e)}", exc_info=True)
            # Return safe defaults
            return {
                'mode': 'normal',
                'threshold': 0.1,
                'custom_threshold': 0.1,
                'description': 'Balanced approach returning relevant results with good precision.',
                'updated_at': None
            }
    
    def _invalidate_cache(self):
        """Invalidate the cached settings"""
        cache.delete(self.CACHE_KEY)
        logger.info("Search sensitivity settings cache invalidated")
    
    def _log_settings_change(self, old_mode, new_mode, old_threshold, new_threshold, user=None):
        """
        Log search sensitivity changes for audit purposes.
        
        Args:
            old_mode (str): Previous mode
            new_mode (str): New mode
            old_threshold (float): Previous threshold
            new_threshold (float): New threshold
            user (User, optional): User who made the change
        """
        username = user.username if user else 'system'
        
        logger.info(
            f"Search sensitivity changed by {username}: "
            f"{old_mode}({old_threshold}) -> {new_mode}({new_threshold})"
        )
        
        # You can extend this to write to a dedicated audit log table if needed
        # For now, we're using the application logger which should be picked up
        # by your logging configuration


# Singleton instance for easy import
_search_settings_service = None

def get_search_settings_service():
    """
    Get the singleton instance of SearchSettingsService.
    
    Returns:
        SearchSettingsService: Singleton service instance
    """
    global _search_settings_service
    if _search_settings_service is None:
        _search_settings_service = SearchSettingsService()
    return _search_settings_service
