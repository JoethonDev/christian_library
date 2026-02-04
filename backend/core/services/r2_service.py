"""
Modular R2 Service for Cloudflare R2 Storage
Centralized service for all R2 storage operations with unified error handling and logging.
"""
import os
import boto3
import logging
from typing import Optional, Tuple, Dict, Any
from django.conf import settings
from botocore.exceptions import ClientError, NoCredentialsError

logger = logging.getLogger(__name__)


class R2Service:
    """
    Unified service for Cloudflare R2 storage operations.
    Handles file uploads, deletions, presigned URLs, and bucket metrics.
    """
    
    def __init__(self):
        """Initialize R2 service with boto3 client and configuration"""
        self.enabled = getattr(settings, 'R2_ENABLED', False)
        self.client = None
        self.bucket_name = None
        
        if self.enabled:
            self._initialize_client()
    
    def _initialize_client(self):
        """Initialize boto3 S3 client for R2"""
        try:
            # Validate required settings
            required_settings = [
                'R2_BUCKET_NAME', 
                'R2_ACCESS_KEY_ID', 
                'R2_SECRET_ACCESS_KEY', 
                'R2_ENDPOINT_URL'
            ]
            
            for setting in required_settings:
                if not getattr(settings, setting, None):
                    logger.warning(f"R2 setting {setting} not configured")
                    self.enabled = False
                    return
            
            # Initialize boto3 S3 client for R2
            self.client = boto3.client(
                's3',
                endpoint_url=settings.R2_ENDPOINT_URL,
                aws_access_key_id=settings.R2_ACCESS_KEY_ID,
                aws_secret_access_key=settings.R2_SECRET_ACCESS_KEY,
                region_name=getattr(settings, 'R2_REGION_NAME', 'auto')
            )
            self.bucket_name = settings.R2_BUCKET_NAME
            logger.info("R2Service initialized successfully")
            
        except Exception as e:
            logger.error(f"Failed to initialize R2Service: {e}", exc_info=True)
            self.enabled = False
    
    def upload_file(
        self, 
        local_file_path: str, 
        r2_key: str,
        callback: Optional[callable] = None,
        metadata: Optional[Dict[str, str]] = None
    ) -> Tuple[bool, str]:
        """
        Upload a file to R2 storage.
        
        Args:
            local_file_path: Path to the local file to upload
            r2_key: The key (path) for the file in R2
            callback: Optional progress callback function
            metadata: Optional metadata dict to attach to the object
        
        Returns:
            Tuple of (success: bool, message/url: str)
        """
        if not self.enabled or not self.client:
            return False, "R2 storage is not enabled or not properly configured"
        
        if not os.path.exists(local_file_path):
            return False, f"Local file not found: {local_file_path}"
        
        try:
            # Prepare upload arguments
            upload_args = {
                'Bucket': self.bucket_name,
                'Key': r2_key
            }
            
            # Add metadata if provided
            if metadata:
                upload_args['Metadata'] = metadata
            
            # Perform upload
            if callback:
                self.client.upload_file(
                    local_file_path,
                    self.bucket_name,
                    r2_key,
                    Callback=callback
                )
            else:
                self.client.upload_file(
                    local_file_path,
                    self.bucket_name,
                    r2_key
                )
            
            # Generate public URL
            r2_url = self._construct_public_url(r2_key)
            
            logger.info(f"Successfully uploaded {local_file_path} to R2: {r2_key}")
            return True, r2_url
            
        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code', 'Unknown')
            error_msg = f"R2 ClientError ({error_code}): {str(e)}"
            logger.error(f"Failed to upload {local_file_path} to R2: {error_msg}")
            return False, error_msg
            
        except NoCredentialsError as e:
            error_msg = f"R2 credentials not available: {str(e)}"
            logger.error(error_msg)
            return False, error_msg
            
        except Exception as e:
            error_msg = f"Unexpected error uploading to R2: {str(e)}"
            logger.error(f"Failed to upload {local_file_path} to R2: {error_msg}", exc_info=True)
            return False, error_msg
    
    def delete_file(self, r2_key: str) -> Tuple[bool, str]:
        """
        Delete a file from R2 storage.
        
        Args:
            r2_key: The key (path) of the file in R2
        
        Returns:
            Tuple of (success: bool, message: str)
        """
        if not self.enabled or not self.client:
            return False, "R2 storage is not enabled or not properly configured"
        
        try:
            self.client.delete_object(
                Bucket=self.bucket_name,
                Key=r2_key
            )
            
            logger.info(f"Successfully deleted file from R2: {r2_key}")
            return True, f"File deleted successfully: {r2_key}"
            
        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code', 'Unknown')
            
            # Handle NoSuchKey as a success case (file already doesn't exist)
            if error_code == 'NoSuchKey':
                logger.info(f"File not found in R2 (already deleted): {r2_key}")
                return True, f"File not found (already deleted): {r2_key}"
            
            error_msg = f"R2 ClientError ({error_code}): {str(e)}"
            logger.error(f"Failed to delete {r2_key} from R2: {error_msg}")
            return False, error_msg
            
        except Exception as e:
            error_msg = f"Unexpected error deleting from R2: {str(e)}"
            logger.error(f"Failed to delete {r2_key} from R2: {error_msg}", exc_info=True)
            return False, error_msg
    
    def get_presigned_url(
        self, 
        r2_key: str, 
        expiration: int = 3600,
        http_method: str = 'GET'
    ) -> Tuple[bool, str]:
        """
        Generate a presigned URL for temporary access to an R2 object.
        
        Args:
            r2_key: The key (path) of the file in R2
            expiration: URL expiration time in seconds (default: 3600 = 1 hour)
            http_method: HTTP method for the URL (GET or PUT)
        
        Returns:
            Tuple of (success: bool, url/error_message: str)
        """
        if not self.enabled or not self.client:
            return False, "R2 storage is not enabled or not properly configured"
        
        try:
            # Map HTTP method to boto3 client method
            client_method_map = {
                'GET': 'get_object',
                'PUT': 'put_object'
            }
            
            client_method = client_method_map.get(http_method.upper(), 'get_object')
            
            presigned_url = self.client.generate_presigned_url(
                ClientMethod=client_method,
                Params={
                    'Bucket': self.bucket_name,
                    'Key': r2_key
                },
                ExpiresIn=expiration
            )
            
            logger.info(f"Generated presigned URL for {r2_key} (expires in {expiration}s)")
            return True, presigned_url
            
        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code', 'Unknown')
            error_msg = f"R2 ClientError ({error_code}): {str(e)}"
            logger.error(f"Failed to generate presigned URL for {r2_key}: {error_msg}")
            return False, error_msg
            
        except Exception as e:
            error_msg = f"Unexpected error generating presigned URL: {str(e)}"
            logger.error(f"Failed to generate presigned URL for {r2_key}: {error_msg}", exc_info=True)
            return False, error_msg
    
    def get_bucket_metrics(self) -> Dict[str, Any]:
        """
        Get bucket storage metrics including total size and object count.
        
        Returns:
            Dict containing:
                - success: bool
                - total_size_bytes: int (total storage used in bytes)
                - total_size_gb: float (total storage used in GB)
                - object_count: int (number of objects in bucket)
                - error: str (error message if failed)
        """
        if not self.enabled or not self.client:
            return {
                'success': False,
                'error': 'R2 storage is not enabled or not properly configured',
                'total_size_bytes': 0,
                'total_size_gb': 0.0,
                'object_count': 0
            }
        
        try:
            total_size = 0
            object_count = 0
            
            # Use paginator to handle large buckets
            paginator = self.client.get_paginator('list_objects_v2')
            page_iterator = paginator.paginate(Bucket=self.bucket_name)
            
            for page in page_iterator:
                if 'Contents' in page:
                    for obj in page['Contents']:
                        total_size += obj.get('Size', 0)
                        object_count += 1
            
            # Convert bytes to GB
            total_size_gb = total_size / (1024 ** 3)
            
            result = {
                'success': True,
                'total_size_bytes': total_size,
                'total_size_gb': round(total_size_gb, 2),
                'object_count': object_count
            }
            
            logger.info(f"R2 bucket metrics: {total_size_gb:.2f} GB, {object_count} objects")
            return result
            
        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code', 'Unknown')
            error_msg = f"R2 ClientError ({error_code}): {str(e)}"
            logger.error(f"Failed to fetch bucket metrics: {error_msg}")
            return {
                'success': False,
                'error': error_msg,
                'total_size_bytes': 0,
                'total_size_gb': 0.0,
                'object_count': 0
            }
            
        except Exception as e:
            error_msg = f"Unexpected error fetching bucket metrics: {str(e)}"
            logger.error(f"Failed to fetch bucket metrics: {error_msg}", exc_info=True)
            return {
                'success': False,
                'error': error_msg,
                'total_size_bytes': 0,
                'total_size_gb': 0.0,
                'object_count': 0
            }
    
    def _construct_public_url(self, r2_key: str) -> str:
        """
        Construct a public URL for an R2 object.
        
        Args:
            r2_key: The key (path) of the file in R2
        
        Returns:
            Public URL string
        """
        # Try to get custom public URL from environment
        r2_public_url = os.environ.get('R2_PUBLIC_MEDIA_URL')
        if r2_public_url:
            return f"{r2_public_url.rstrip('/')}/{r2_key}"
        
        # Fallback: construct from endpoint URL
        # Format: https://pub-{public-id}.r2.dev/{r2_key}
        endpoint = settings.R2_ENDPOINT_URL
        # This is a simplification - in production, you'd use a custom domain
        return f"{endpoint.replace('https://', 'https://pub-').replace('.r2.cloudflarestorage.com', '.r2.dev')}/{r2_key}"


# Singleton instance
_r2_service = None


def get_r2_service() -> R2Service:
    """Get or create singleton R2Service instance"""
    global _r2_service
    if _r2_service is None:
        _r2_service = R2Service()
    return _r2_service
