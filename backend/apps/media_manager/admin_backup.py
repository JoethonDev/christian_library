from django.contrib import admin
from django.utils.safestring import mark_safe
from django.urls import reverse
from django.http import HttpResponseRedirect
from django.contrib import messages
from .models import ContentItem, VideoMeta, AudioMeta, PdfMeta
from .forms import ContentItemForm, VideoUploadForm, AudioUploadForm, PdfUploadForm
from core.tasks.media_processing import (
    process_video_to_hls, process_audio_compression, process_pdf_optimization
)


class VideoMetaInline(admin.StackedInline):
    model = VideoMeta
    form = VideoUploadForm
    extra = 0
    fields = ['original_file', 'duration_seconds', 'processing_status', 'hls_paths']
    readonly_fields = ['duration_seconds', 'processing_status', 'hls_paths']
    
    def hls_paths(self, obj):
        if obj.hls_720p_path and obj.hls_480p_path:
            return mark_safe(f"""
                <strong>720p:</strong> {obj.hls_720p_path}<br>
                <strong>480p:</strong> {obj.hls_480p_path}
            """)
        return "لم يتم إنشاء ملفات HLS بعد"
    hls_paths.short_description = "مسارات HLS"


class AudioMetaInline(admin.StackedInline):
    model = AudioMeta
    form = AudioUploadForm
    extra = 0
    fields = ['original_file', 'compressed_file', 'duration_seconds', 'bitrate', 'processing_status']
    readonly_fields = ['compressed_file', 'duration_seconds', 'bitrate', 'processing_status']


class PdfMetaInline(admin.StackedInline):
    model = PdfMeta
    form = PdfUploadForm
    extra = 0
    fields = ['original_file', 'optimized_file', 'file_size', 'page_count', 'processing_status']
    readonly_fields = ['optimized_file', 'file_size', 'page_count', 'processing_status']


@admin.register(ContentItem)
class ContentItemAdmin(admin.ModelAdmin):
    form = ContentItemForm
    list_display = ['title_ar', 'content_type', 'module', 'processing_status', 'is_active', 'created_at']
    list_filter = ['content_type', 'is_active', 'created_at', 'module__course']
    search_fields = ['title_ar', 'title_en', 'description_ar']
    ordering = ['-created_at']
    filter_horizontal = ['tags']
    
    fieldsets = (
        ('المعلومات الأساسية', {
            'fields': ('title_ar', 'title_en', 'content_type', 'module', 'is_active')
        }),
        ('الوصف', {
            'fields': ('description_ar', 'description_en'),
            'classes': ('collapse',)
        }),
        ('العلامات', {
            'fields': ('tags',),
            'classes': ('collapse',)
        })
    )
    
    def get_inlines(self, request, obj):
        """Return appropriate inline based on content type"""
        if obj and obj.content_type == 'video':
            return [VideoMetaInline]
        elif obj and obj.content_type == 'audio':
            return [AudioMetaInline]
        elif obj and obj.content_type == 'pdf':
            return [PdfMetaInline]
        return []
    
    def processing_status(self, obj):
        """Show processing status with colored indicator"""
        if obj.content_type == 'video':
            try:
                status = obj.videometa.processing_status
            except:
                status = 'pending'
        elif obj.content_type == 'audio':
            try:
                status = obj.audiometa.processing_status
            except:
                status = 'pending'
        elif obj.content_type == 'pdf':
            try:
                status = obj.pdfmeta.processing_status
            except:
                status = 'pending'
        else:
            status = 'unknown'
        
        colors = {
            'pending': '#ffc107',
            'processing': '#17a2b8',
            'completed': '#28a745',
            'failed': '#dc3545',
            'unknown': '#6c757d'
        }
        
        status_text = {
            'pending': 'في الانتظار',
            'processing': 'قيد المعالجة',
            'completed': 'مكتمل',
            'failed': 'فشل',
            'unknown': 'غير معروف'
        }
        
        return mark_safe(
            f'<span style="color: {colors.get(status, "#000")}; font-weight: bold;">'
            f'{status_text.get(status, status)}</span>'
        )
    processing_status.short_description = "حالة المعالجة"
    
    def save_related(self, request, form, formsets, change):
        """Trigger processing after saving related objects"""
        super().save_related(request, form, formsets, change)
        
        # Get the content item
        content_item = form.instance
        
        # Trigger appropriate processing task
        if content_item.content_type == 'video':
            try:
                video_meta = content_item.videometa
                if video_meta.original_file and video_meta.processing_status == 'pending':
                    process_video_to_hls.delay(video_meta.id)
                    messages.success(request, f'تم بدء معالجة الفيديو: {content_item.title_ar}')
            except VideoMeta.DoesNotExist:
                pass
                
        elif content_item.content_type == 'audio':
            try:
                audio_meta = content_item.audiometa
                if audio_meta.original_file and audio_meta.processing_status == 'pending':
                    process_audio_compression.delay(audio_meta.id)
                    messages.success(request, f'تم بدء معالجة الصوت: {content_item.title_ar}')
            except AudioMeta.DoesNotExist:
                pass
                
        elif content_item.content_type == 'pdf':
            try:
                pdf_meta = content_item.pdfmeta
                if pdf_meta.original_file and pdf_meta.processing_status == 'pending':
                    process_pdf_optimization.delay(pdf_meta.id)
                    messages.success(request, f'تم بدء معالجة PDF: {content_item.title_ar}')
            except PdfMeta.DoesNotExist:
                pass


@admin.register(AudioMeta)
class AudioMetaAdmin(admin.ModelAdmin):
    list_display = ['content_item', 'processing_status', 'duration_display', 'bitrate_display', 'file_size_display', 'process_button']
    list_filter = ['processing_status']
    form = AudioUploadForm
    actions = ['reprocess_audio']
    
    def duration_display(self, obj):
        if obj.duration_seconds:
            minutes = obj.duration_seconds // 60
            seconds = obj.duration_seconds % 60
            return f"{minutes}:{seconds:02d}"
        return "غير محدد"
    duration_display.short_description = "المدة"
    
    def bitrate_display(self, obj):
        return f"{obj.bitrate} kbps" if obj.bitrate else "غير محدد"
    bitrate_display.short_description = "معدل البت"
    
    def file_size_display(self, obj):
        if obj.original_file:
            try:
                size_mb = obj.original_file.size / (1024 * 1024)
                return f"{size_mb:.1f} MB"
            except:
                return "غير محدد"
        return "لا يوجد ملف"
    file_size_display.short_description = "حجم الملف"
    
    def process_button(self, obj):
        if obj.processing_status == 'pending' and obj.original_file:
            return mark_safe('<button onclick="processAudio({})" class="button default">معالجة الآن</button>'.format(obj.pk))
        elif obj.processing_status == 'processing':
            return "قيد المعالجة..."
        elif obj.processing_status == 'completed':
            return "✅ مكتمل"
        return "غير جاهز"
    process_button.short_description = "الإجراءات"
    
    def reprocess_audio(self, request, queryset):
        count = 0
        for audio_meta in queryset:
            if audio_meta.original_file:
                audio_meta.processing_status = 'pending'
                audio_meta.save()
                process_audio_compression.delay(audio_meta.pk)
                count += 1
        self.message_user(request, f"تم إعادة معالجة {count} ملف صوتي")
    reprocess_audio.short_description = "إعادة معالجة الملفات المحددة"

@admin.register(PdfMeta)
class PdfMetaAdmin(admin.ModelAdmin):
    list_display = ['content_item', 'file_size_mb', 'page_count', 'processing_status', 'has_optimized']
    list_filter = ['processing_status']
    search_fields = ['content_item__title_ar']
    readonly_fields = ['file_size', 'page_count', 'optimized_file']
    
    def file_size_mb(self, obj):
        if obj.file_size:
            return f"{obj.file_size / 1024 / 1024:.1f} MB"
        return "غير محدد"
    file_size_mb.short_description = "حجم الملف"
    
    def has_optimized(self, obj):
        return bool(obj.optimized_file)
    has_optimized.boolean = True
    has_optimized.short_description = "يحتوي على ملف محسن"
    
    actions = ['reprocess_pdfs']
    
    def reprocess_pdfs(self, request, queryset):
        """Action to reprocess selected PDFs"""
        count = 0
        for pdf_meta in queryset:
            if pdf_meta.original_file:
                pdf_meta.processing_status = 'pending'
                pdf_meta.save()
                process_pdf_optimization.delay(pdf_meta.id)
                count += 1
        
        messages.success(request, f'تم بدء إعادة معالجة {count} ملف PDF')
    reprocess_pdfs.short_description = "إعادة معالجة ملفات PDF المحددة"