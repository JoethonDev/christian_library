"""
Simple test to verify Gemini AI service integration
Run this to check if the service can be imported and initialized
"""

# Test imports
try:
    import os
    import sys
    
    # Add the backend path to sys.path
    backend_path = 'd:/Christian_Library/christian_library_project/library_prod/backend'
    if backend_path not in sys.path:
        sys.path.insert(0, backend_path)
    
    # Test Django setup
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.development')
    
    import django
    django.setup()
    
    print("✅ Django setup successful")
    
    # Test Gemini service import
    from apps.media_manager.services.gemini_service import GeminiContentGenerator
    print("✅ Gemini service import successful")
    
    # Test service initialization (without API key)
    service = GeminiContentGenerator()
    print(f"✅ Service initialized, available: {service.is_available()}")
    
    if not service.is_available():
        print("ℹ️  API key not configured - this is expected for testing")
        print("ℹ️  Set GEMINI_API_KEY environment variable to test full functionality")
    
    print("\n🎉 Gemini AI integration is ready!")
    print("📋 Next steps:")
    print("   1. Set GEMINI_API_KEY environment variable")
    print("   2. Run Django server: python manage.py runserver")
    print("   3. Navigate to /admin/upload/ and test AI generation")
    
except ImportError as e:
    print(f"❌ Import error: {e}")
    print("💡 Make sure all dependencies are installed from requirements/base.txt")
    
except Exception as e:
    print(f"❌ Error: {e}")
    print("💡 Check Django settings and project structure")