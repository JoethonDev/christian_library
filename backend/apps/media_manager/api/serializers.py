"""
DRF Serializers for RESTful Upload API.
"""
import os
import logging
from rest_framework import serializers
from django.core.files.uploadedfile import UploadedFile
from apps.media_manager.models import APIUploadQueue, ContentItem, Tag

logger = logging.getLogger(__name__)


class ContentItemUploadSerializer(serializers.Serializer):
    """
    Serializer for single file upload with optional metadata.
    Supports minimal payload (file-only) and full payload (file + metadata).
    """
    # Required field
    file = serializers.FileField(required=True, help_text='Media file (video/audio/pdf)')
    
    # Optional fields
    doc_file = serializers.FileField(
        required=False, 
        allow_null=True,
        help_text='Word document for book content extraction (for PDFs only)'
    )
    title_ar = serializers.CharField(max_length=200, required=False, allow_blank=True)
    title_en = serializers.CharField(max_length=200, required=False, allow_blank=True)
    description_ar = serializers.CharField(required=False, allow_blank=True)
    description_en = serializers.CharField(required=False, allow_blank=True)
    tags = serializers.ListField(
        child=serializers.UUIDField(),
        required=False,
        allow_empty=True,
        help_text='List of tag UUIDs'
    )
    seo_keywords_ar = serializers.CharField(required=False, allow_blank=True)
    seo_keywords_en = serializers.CharField(required=False, allow_blank=True)
    transcript = serializers.CharField(required=False, allow_blank=True)
    notes = serializers.CharField(required=False, allow_blank=True)
    
    def validate_file(self, value):
        """Validate file size and type."""
        # Check file size (max 2GB)
        max_size = 2 * 1024 * 1024 * 1024  # 2GB in bytes
        if value.size > max_size:
            raise serializers.ValidationError(
                f'File size {value.size / (1024*1024):.2f}MB exceeds maximum of 2048MB'
            )
        
        # Detect content type from file extension
        file_ext = os.path.splitext(value.name)[1].lower()
        valid_extensions = {
            'video': ['.mp4', '.mov', '.avi', '.mkv', '.webm'],
            'audio': ['.mp3', '.wav', '.m4a', '.aac', '.ogg'],
            'pdf': ['.pdf']
        }
        
        content_type = None
        for ctype, extensions in valid_extensions.items():
            if file_ext in extensions:
                content_type = ctype
                break
        
        if not content_type:
            raise serializers.ValidationError(
                f'Unsupported file type: {file_ext}. '
                f'Supported: {", ".join([ext for exts in valid_extensions.values() for ext in exts])}'
            )
        
        # Store content type for later use
        self.context['detected_content_type'] = content_type
        
        return value
    
    def validate_tags(self, value):
        """Validate that tag UUIDs exist."""
        if value:
            existing_tags = Tag.objects.filter(id__in=value, is_active=True)
            if existing_tags.count() != len(value):
                raise serializers.ValidationError('One or more tags not found or inactive')
        return value
    
    def validate(self, data):
        """Cross-field validation."""
        # If doc_file provided, must be for PDF content
        if data.get('doc_file') and self.context.get('detected_content_type') != 'pdf':
            raise serializers.ValidationError({
                'doc_file': 'Document file can only be provided for PDF uploads'
            })
        
        return data


class BulkContentItemUploadSerializer(serializers.Serializer):
    """
    Serializer for bulk file uploads with optional shared metadata.
    Supports up to 20 files per request.
    """
    files = serializers.ListField(
        child=serializers.FileField(),
        required=True,
        min_length=1,
        max_length=20,
        help_text='List of media files (max 20)'
    )
    doc_files = serializers.ListField(
        child=serializers.FileField(),
        required=False,
        allow_empty=True,
        help_text='List of document files matched by index to files'
    )
    shared_metadata = serializers.JSONField(
        required=False,
        allow_null=True,
        help_text='Metadata to apply to all files'
    )
    individual_metadata = serializers.ListField(
        child=serializers.JSONField(),
        required=False,
        allow_empty=True,
        help_text='List of metadata dicts matched by index to files'
    )
    
    def validate_files(self, value):
        """Validate all files."""
        max_size = 2 * 1024 * 1024 * 1024  # 2GB
        
        for i, file in enumerate(value):
            if file.size > max_size:
                raise serializers.ValidationError(
                    f'File {i+1} ({file.name}) size exceeds maximum of 2048MB'
                )
        
        return value
    
    def validate(self, data):
        """Cross-field validation."""
        files_count = len(data['files'])
        
        # Validate doc_files count if provided
        if data.get('doc_files'):
            if len(data['doc_files']) != files_count:
                raise serializers.ValidationError({
                    'doc_files': f'Must provide same number of doc_files as files ({files_count})'
                })
        
        # Validate individual_metadata count if provided
        if data.get('individual_metadata'):
            if len(data['individual_metadata']) != files_count:
                raise serializers.ValidationError({
                    'individual_metadata': f'Must provide same number of metadata items as files ({files_count})'
                })
        
        return data


class QueueStatusSerializer(serializers.ModelSerializer):
    """
    Serializer for queue item status response.
    """
    queue_id = serializers.UUIDField(source='id', read_only=True)
    content_item_id = serializers.UUIDField(source='content_item.id', read_only=True, allow_null=True)
    queue_position = serializers.SerializerMethodField()
    
    class Meta:
        model = APIUploadQueue
        fields = [
            'queue_id',
            'file_name',
            'content_type',
            'file_size_mb',
            'status',
            'queue_status',
            'scheduled_for',
            'delay_count',
            'priority',
            'queue_position',
            'content_item_id',
            'error_message',
            'created_at',
            'processing_started_at',
            'completed_at',
        ]
        read_only_fields = fields
    
    def get_queue_position(self, obj):
        """Get queue position for this item."""
        return obj.get_queue_position()


class QueueItemSerializer(serializers.ModelSerializer):
    """
    Admin serializer for queue management.
    """
    queue_position = serializers.SerializerMethodField()
    content_item_title = serializers.CharField(
        source='content_item.title_ar',
        read_only=True,
        allow_null=True
    )
    
    class Meta:
        model = APIUploadQueue
        fields = '__all__'
        read_only_fields = [
            'id', 'created_at', 'updated_at', 'processing_started_at',
            'completed_at', 'content_item'
        ]
    
    def get_queue_position(self, obj):
        """Get queue position for this item."""
        return obj.get_queue_position()


class UploadResponseSerializer(serializers.Serializer):
    """
    Response serializer for upload endpoints.
    """
    queue_id = serializers.UUIDField(read_only=True)
    status = serializers.CharField(read_only=True)
    queue_status = serializers.CharField(read_only=True)
    queue_position = serializers.IntegerField(read_only=True)
    content_type = serializers.CharField(read_only=True)
    file_name = serializers.CharField(read_only=True)
    doc_file_name = serializers.CharField(read_only=True, allow_null=True)
    estimated_processing_time = serializers.CharField(read_only=True, allow_null=True)


class BulkUploadResponseSerializer(serializers.Serializer):
    """
    Response serializer for bulk upload endpoint.
    """
    queue_items = UploadResponseSerializer(many=True, read_only=True)
    total = serializers.IntegerField(read_only=True)
    queued = serializers.IntegerField(read_only=True)
    processing = serializers.IntegerField(read_only=True)
