from django.db import models
from django.utils.translation import gettext_lazy as _
from django.core.exceptions import ValidationError
from django.urls import reverse
import uuid


class CourseManager(models.Manager):
    """Custom manager for Course with optimized queries"""
    
    def active(self):
        """Return only active courses"""
        return self.filter(is_active=True)
    
    def with_modules_and_content(self):
        """Return courses with modules and content count"""
        return self.prefetch_related('modules__contentitem_set').annotate(
            content_count=models.Count('modules__contentitem')
        )
    
    def by_category(self, category):
        """Return courses by category"""
        return self.filter(category__iexact=category)


class Course(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    title_ar = models.CharField(max_length=200, verbose_name=_('Arabic Title'), db_index=True)
    title_en = models.CharField(max_length=200, blank=True, verbose_name=_('English Title'), db_index=True)
    description_ar = models.TextField(verbose_name=_('Arabic Description'))
    description_en = models.TextField(blank=True, verbose_name=_('English Description'))
    category = models.CharField(max_length=100, verbose_name=_('Category'), db_index=True)
    slug = models.SlugField(max_length=255, unique=True, verbose_name=_('Slug'))
    is_active = models.BooleanField(default=True, verbose_name=_('Active'), db_index=True)
    created_at = models.DateTimeField(auto_now_add=True, verbose_name=_('Created At'), db_index=True)
    updated_at = models.DateTimeField(auto_now=True, verbose_name=_('Updated At'))
    
    # Custom manager
    objects = CourseManager()
    
    class Meta:
        verbose_name = _('Course')
        verbose_name_plural = _('Courses')
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['is_active', '-created_at']),
            models.Index(fields=['category', 'is_active']),
            models.Index(fields=['slug']),
        ]
    
    def __str__(self):
        return self.title_ar
    
    def get_title(self, language='ar'):
        """Get title in specified language"""
        return self.title_ar if language == 'ar' else (self.title_en or self.title_ar)
    
    def get_description(self, language='ar'):
        """Get description in specified language"""
        return self.description_ar if language == 'ar' else (self.description_en or self.description_ar)
    
    def get_absolute_url(self):
        """Get the absolute URL for this course"""
        return reverse('frontend_api:course_detail', kwargs={'slug': self.slug})
    
    def get_modules_count(self):
        """Get the number of active modules"""
        return self.modules.filter(is_active=True).count()
    
    def get_content_count(self):
        """Get the total number of content items"""
        return sum(module.contentitem_set.filter(is_active=True).count() 
                  for module in self.modules.filter(is_active=True))


class ModuleManager(models.Manager):
    """Custom manager for Module with optimized queries"""
    
    def active(self):
        """Return only active modules"""
        return self.filter(is_active=True)
    
    def with_content(self):
        """Return modules with content items"""
        return self.prefetch_related('contentitem_set')
    
    def by_course(self, course_id):
        """Return modules by course"""
        return self.filter(course_id=course_id)
    
    def ordered(self):
        """Return modules ordered by their order field"""
        return self.order_by('order')


class Module(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    course = models.ForeignKey(
        Course, 
        on_delete=models.CASCADE, 
        related_name='modules', 
        verbose_name=_('Course'),
        db_index=True
    )
    title_ar = models.CharField(max_length=200, verbose_name=_('Arabic Title'), db_index=True)
    title_en = models.CharField(max_length=200, blank=True, verbose_name=_('English Title'), db_index=True)
    description_ar = models.TextField(blank=True, verbose_name=_('Arabic Description'))
    description_en = models.TextField(blank=True, verbose_name=_('English Description'))
    order = models.PositiveIntegerField(verbose_name=_('Order'), db_index=True)
    is_active = models.BooleanField(default=True, verbose_name=_('Active'), db_index=True)
    created_at = models.DateTimeField(auto_now_add=True, verbose_name=_('Created At'))
    updated_at = models.DateTimeField(auto_now=True, verbose_name=_('Updated At'))
    
    # Custom manager
    objects = ModuleManager()
    
    class Meta:
        verbose_name = _('Module')
        verbose_name_plural = _('Modules')
        ordering = ['course', 'order']
        unique_together = ['course', 'order']
        indexes = [
            models.Index(fields=['course', 'order']),
            models.Index(fields=['is_active', 'order']),
        ]
    
    def __str__(self):
        return f"{self.course.title_ar} - {self.title_ar}"
    
    def get_title(self, language='ar'):
        """Get title in specified language"""
        return self.title_ar if language == 'ar' else (self.title_en or self.title_ar)
    
    def get_description(self, language='ar'):
        """Get description in specified language"""
        return self.description_ar if language == 'ar' else (self.description_en or self.description_ar)
    
    def get_content_count(self):
        """Get the number of active content items"""
        return self.contentitem_set.filter(is_active=True).count()
    
    def clean(self):
        """Validate the module"""
        super().clean()
        if self.order < 1:
            raise ValidationError(_('Order must be a positive integer'))


class TagManager(models.Manager):
    """Custom manager for Tag with optimized queries"""
    
    def active(self):
        """Return only active tags"""
        return self.filter(is_active=True)
    
    def by_name(self, name, language='ar'):
        """Return tag by name in specific language"""
        if language == 'ar':
            return self.filter(name_ar__iexact=name)
        else:
            return self.filter(name_en__iexact=name)
    
    def popular(self, limit=10):
        """Return most popular tags based on content count"""
        return self.annotate(
            content_count=models.Count('contentitem')
        ).order_by('-content_count')[:limit]


class Tag(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name_ar = models.CharField(max_length=100, unique=True, verbose_name=_('Arabic Name'), db_index=True)
    name_en = models.CharField(max_length=100, blank=True, verbose_name=_('English Name'), db_index=True)
    description_ar = models.TextField(blank=True, verbose_name=_('Arabic Description'))
    color = models.CharField(
        max_length=7, 
        default='#8C1C13', 
        verbose_name=_('Color'),
        help_text=_('Hex color code (e.g., #8C1C13)')
    )
    is_active = models.BooleanField(default=True, verbose_name=_('Active'), db_index=True)
    created_at = models.DateTimeField(auto_now_add=True, verbose_name=_('Created At'))
    
    # Custom manager
    objects = TagManager()
    
    class Meta:
        verbose_name = _('Tag')
        verbose_name_plural = _('Tags')
        ordering = ['name_ar']
        indexes = [
            models.Index(fields=['is_active', 'name_ar']),
        ]
    
    def __str__(self):
        return self.name_ar
    
    def get_name(self, language='ar'):
        """Get name in specified language"""
        return self.name_ar if language == 'ar' else (self.name_en or self.name_ar)
    
    def get_content_count(self):
        """Get the number of content items using this tag"""
        return self.contentitem_set.filter(is_active=True).count()
    
    def clean(self):
        """Validate the tag"""
        super().clean()
        if not self.color.startswith('#') or len(self.color) != 7:
            raise ValidationError(_('Color must be a valid hex color code (e.g., #8C1C13)'))