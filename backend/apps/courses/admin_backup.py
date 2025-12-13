from django.contrib import admin
from .models import Course, Module, Tag


class ModuleInline(admin.TabularInline):
    model = Module
    extra = 0
    fields = ['title_ar', 'title_en', 'order', 'is_active']


@admin.register(Course)
class CourseAdmin(admin.ModelAdmin):
    list_display = ['title_ar', 'category', 'is_active', 'created_at']
    list_filter = ['category', 'is_active', 'created_at']
    search_fields = ['title_ar', 'title_en', 'description_ar']
    ordering = ['-created_at']
    inlines = [ModuleInline]
    
    fieldsets = (
        ('المعلومات الأساسية', {
            'fields': ('title_ar', 'title_en', 'category', 'is_active')
        }),
        ('الوصف', {
            'fields': ('description_ar', 'description_en'),
            'classes': ('collapse',)
        })
    )


@admin.register(Module)
class ModuleAdmin(admin.ModelAdmin):
    list_display = ['title_ar', 'course', 'order', 'is_active', 'created_at']
    list_filter = ['course', 'is_active', 'created_at']
    search_fields = ['title_ar', 'title_en', 'course__title_ar']
    ordering = ['course', 'order']
    

@admin.register(Tag)
class TagAdmin(admin.ModelAdmin):
    list_display = ['name_ar', 'name_en', 'color', 'is_active']
    list_filter = ['is_active', 'created_at']
    search_fields = ['name_ar', 'name_en']
    ordering = ['name_ar']