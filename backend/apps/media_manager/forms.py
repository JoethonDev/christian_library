from django import forms
from django.core.exceptions import ValidationError
from .models import ContentItem, VideoMeta, AudioMeta, PdfMeta
import os


class ContentItemForm(forms.ModelForm):
    """Enhanced form for ContentItem with validation and JSON support"""
    
    class Meta:
        model = ContentItem
        fields = [
            'title_ar', 'title_en', 
            'description_ar', 'description_en', 
            'seo_title_ar', 'seo_title_en',
            'seo_meta_description_ar', 'seo_meta_description_en',
            'seo_keywords_ar', 'seo_keywords_en',
            'content_type', 'tags', 'is_active', 'structured_data'
        ]
        widgets = {
            'description_ar': forms.Textarea(attrs={'rows': 3}),
            'description_en': forms.Textarea(attrs={'rows': 3}),
            'seo_meta_description_ar': forms.Textarea(attrs={'rows': 2}),
            'seo_meta_description_en': forms.Textarea(attrs={'rows': 2}),
            'tags': forms.CheckboxSelectMultiple(),
            'structured_data': forms.Textarea(attrs={
                'rows': 15, 
                'class': 'vLargeTextField font-monospace',
                'style': 'font-family: monospace;'
            }),
        }
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Add CSS classes for RTL support
        for field_name, field in self.fields.items():
            if 'ar' in field_name:
                field.widget.attrs['dir'] = 'rtl'
                field.widget.attrs['class'] = field.widget.attrs.get('class', '') + ' text-right'
        
        # Pretty-print JSON for the form
        if self.instance and self.instance.pk and self.instance.structured_data:
            import json
            try:
                self.initial['structured_data'] = json.dumps(
                    self.instance.structured_data, 
                    indent=4, 
                    ensure_ascii=False
                )
            except (ValueError, TypeError):
                pass

    def clean_structured_data(self):
        data = self.cleaned_data.get('structured_data')
        if not data:
            return {}
        
        if isinstance(data, str):
            try:
                import json
                parsed_data = json.loads(data)
                if not isinstance(parsed_data, dict):
                    raise ValidationError("Structured data must be a JSON object (dictionary)")
                return parsed_data
            except json.JSONDecodeError as e:
                raise ValidationError(f"Invalid JSON format: {str(e)}")
        return data

    def clean_is_active(self):
        is_active = self.cleaned_data.get('is_active')
        if is_active:
            # Check if processing is completed
            if self.instance and self.instance.pk:
                if self.instance.processing_status != 'completed':
                    raise ValidationError(
                        "This item cannot be activated until background processing is successfully completed."
                    )
        return is_active


class VideoUploadForm(forms.ModelForm):
    """Form for video file uploads with validation"""
    
    class Meta:
        model = VideoMeta
        fields = ['original_file']
        widgets = {
            'original_file': forms.FileInput(attrs={
                'accept': 'video/mp4,video/avi,video/mov,video/mkv,video/webm',
                'class': 'form-control-file'
            })
        }
    
    def clean_original_file(self):
        file = self.cleaned_data['original_file']
        
        if file:
            # Check file extension
            valid_extensions = ['.mp4', '.avi', '.mov', '.mkv', '.webm']
            file_extension = os.path.splitext(file.name)[1].lower()
            
            if file_extension not in valid_extensions:
                raise ValidationError(
                    f'نوع الملف غير مدعوم. الأنواع المدعومة: {", ".join(valid_extensions)}'
                )
            
            # Check file size (max 5GB)
            max_size = 5 * 1024 * 1024 * 1024  # 5GB
            if file.size > max_size:
                raise ValidationError('حجم الملف كبير جداً. الحد الأقصى 5 جيجابايت')
        
        return file


class AudioUploadForm(forms.ModelForm):
    """Form for audio file uploads with validation and metadata extraction"""
    
    class Meta:
        model = AudioMeta
        fields = ['original_file']
        widgets = {
            'original_file': forms.FileInput(attrs={
                'accept': 'audio/mp3,audio/wav,audio/aac,audio/flac,audio/ogg',
                'class': 'form-control-file'
            })
        }
    
    def clean_original_file(self):
        file = self.cleaned_data['original_file']
        
        if file:
            # Check file extension
            valid_extensions = ['.mp3', '.wav', '.aac', '.flac', '.ogg']
            file_extension = os.path.splitext(file.name)[1].lower()
            
            if file_extension not in valid_extensions:
                raise ValidationError(
                    f'نوع الملف غير مدعوم. الأنواع المدعومة: {", ".join(valid_extensions)}'
                )
            
            # Check file size (max 500MB for original, will be compressed to 50MB)
            max_size = 500 * 1024 * 1024  # 500MB
            if file.size > max_size:
                raise ValidationError('حجم الملف كبير جداً. الحد الأقصى 500 ميجابايت')
            
            # Extract metadata for validation
            self._extract_audio_metadata(file)
        
        return file
    
    def _extract_audio_metadata(self, file):
        """Extract audio metadata for validation and processing"""
        try:
            # Use moviepy for basic audio info (already in requirements)
            from moviepy.editor import AudioFileClip
            temp_path = file.temporary_file_path() if hasattr(file, 'temporary_file_path') else None
            
            if temp_path:
                clip = AudioFileClip(temp_path)
                duration = clip.duration
                fps = clip.fps if hasattr(clip, 'fps') else None
                clip.close()
                
                # Store for later use in processing
                self.extracted_duration = int(duration) if duration else None
                
                # Validate duration (max 4 hours)
                if duration and duration > 4 * 60 * 60:
                    raise ValidationError('مدة الملف الصوتي طويلة جداً (أكثر من 4 ساعات)')
        except Exception as e:
            # Don't fail upload if metadata extraction fails
            # Processing task will handle extraction
            pass


class PdfUploadForm(forms.ModelForm):
    """Form for PDF file uploads with validation"""
    
    class Meta:
        model = PdfMeta
        fields = ['original_file']
        widgets = {
            'original_file': forms.FileInput(attrs={
                'accept': 'application/pdf',
                'class': 'form-control-file'
            })
        }
    
    def clean_original_file(self):
        file = self.cleaned_data['original_file']
        
        if file:
            # Check file extension
            if not file.name.lower().endswith('.pdf'):
                raise ValidationError('يجب أن يكون الملف من نوع PDF')
            
            # Check file size (max 100MB)
            max_size = 100 * 1024 * 1024  # 100MB
            if file.size > max_size:
                raise ValidationError('حجم الملف كبير جداً. الحد الأقصى 100 ميجابايت')
            
            # Basic PDF validation - check magic number
            file.seek(0)
            header = file.read(4)
            file.seek(0)
            
            if header != b'%PDF':
                raise ValidationError('الملف تالف أو ليس ملف PDF صحيح')
        
        return file