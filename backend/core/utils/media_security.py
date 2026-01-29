import hashlib
import hmac
import time
from urllib.parse import urlencode
from django.conf import settings
import secrets


class MediaURLSigner:
    """
    Secure media URL signing for authenticated access to files
    Implements time-limited tokens with HMAC validation
    """
    
    def __init__(self):
        self.secret_key = getattr(settings, 'MEDIA_SIGNING_KEY', settings.SECRET_KEY)
        self.default_expiry = getattr(settings, 'MEDIA_URL_EXPIRY_HOURS', 24)
    
    def generate_signed_url(self, media_path, expiry_hours=None, user_id=None):
        """
        Generate a signed URL for secure media access
        
        Args:
            media_path (str): Path to media file relative to MEDIA_ROOT
            expiry_hours (int): Hours until URL expires (default: 24)
            user_id (str): Optional user ID for additional security
            
        Returns:
            str: Signed URL with token and expiry parameters
        """
        if expiry_hours is None:
            expiry_hours = self.default_expiry
            
        # Calculate expiry timestamp
        expiry_time = int(time.time() + (expiry_hours * 3600))
        
        # Create base URL components
        base_url = f"/secure-media/{media_path.lstrip('/')}"
        
        # Create signature data
        signature_data = {
            'path': media_path,
            'expires': expiry_time,
            'user_id': user_id or '',
            'nonce': secrets.token_hex(8)
        }
        
        # Generate HMAC signature
        message = f"{signature_data['path']}:{signature_data['expires']}:{signature_data['user_id']}:{signature_data['nonce']}"
        signature = hmac.new(
            self.secret_key.encode('utf-8'),
            message.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()
        
        # Build query parameters
        params = {
            'token': signature,
            'expires': expiry_time,
            'nonce': signature_data['nonce']
        }
        
        if user_id:
            params['user'] = user_id
            
        # Construct final URL
        query_string = urlencode(params)
        return f"{base_url}?{query_string}"
    
    def verify_signed_url(self, url_path, query_params):
        """
        Verify a signed URL is valid and not expired
        
        Args:
            url_path (str): The URL path
            query_params (dict): Query parameters from the request
            
        Returns:
            tuple: (is_valid: bool, error_message: str)
        """
        try:
            token = query_params.get('token')
            expires = query_params.get('expires')
            nonce = query_params.get('nonce')
            user_id = query_params.get('user', '')
            
            if not all([token, expires, nonce]):
                return False, "Missing required parameters"
            
            # Check expiration
            try:
                expiry_time = int(expires)
                if expiry_time < time.time():
                    return False, "URL has expired"
            except ValueError:
                return False, "Invalid expiry time"
            
            # Extract media path from URL
            media_path = url_path.replace('/secure-media/', '', 1)
            
            # Recreate signature
            message = f"{media_path}:{expiry_time}:{user_id}:{nonce}"
            expected_signature = hmac.new(
                self.secret_key.encode('utf-8'),
                message.encode('utf-8'),
                hashlib.sha256
            ).hexdigest()
            
            # Verify signature
            if not hmac.compare_digest(token, expected_signature):
                return False, "Invalid signature"
                
            return True, "Valid"
            
        except Exception as e:
            return False, f"Validation error: {str(e)}"
    
    def generate_hls_token(self, video_uuid, user_id=None, expiry_hours=2):
        """
        Generate special token for HLS streaming access
        
        Args:
            video_uuid (str): UUID of the video
            user_id (str): User ID for access control
            expiry_hours (int): Hours until token expires (default: 2)
            
        Returns:
            str: HLS access token
        """
        expiry_time = int(time.time() + (expiry_hours * 3600))
        
        message = f"hls:{video_uuid}:{user_id or ''}:{expiry_time}"
        token = hmac.new(
            self.secret_key.encode('utf-8'),
            message.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()
        
        return f"{token}:{expiry_time}"
    
    def verify_hls_token(self, token, video_uuid, user_id=None):
        """
        Verify HLS streaming token
        
        Args:
            token (str): HLS token to verify
            video_uuid (str): UUID of the video
            user_id (str): User ID for access control
            
        Returns:
            bool: True if token is valid
        """
        try:
            token_hash, expiry_str = token.rsplit(':', 1)
            expiry_time = int(expiry_str)
            
            if expiry_time < time.time():
                return False
                
            message = f"hls:{video_uuid}:{user_id or ''}:{expiry_time}"
            expected_hash = hmac.new(
                self.secret_key.encode('utf-8'),
                message.encode('utf-8'),
                hashlib.sha256
            ).hexdigest()
            
            return hmac.compare_digest(token_hash, expected_hash)
            
        except (ValueError, IndexError):
            return False


# Global instance
media_signer = MediaURLSigner()


def get_secure_media_url(media_path, expiry_hours=None, user_id=None):
    """
    Convenience function to generate signed media URLs
    """
    return media_signer.generate_signed_url(media_path, expiry_hours, user_id)


def get_hls_token(video_uuid, user_id=None, expiry_hours=2):
    """
    Convenience function to generate HLS tokens
    """
    return media_signer.generate_hls_token(video_uuid, user_id, expiry_hours)