from django.db import migrations


def seed_gemini_models(apps, schema_editor):
    GeminiModelSetting = apps.get_model('media_manager', 'GeminiModelSetting')
    models_to_seed = [
        {
            'model_key': 'gemini-3-flash-preview',
            'display_name': 'Gemini 3 Flash Preview',
            'provider': 'google',
            'is_enabled': True,
            'is_default': True,
            'fallback_priority': 0,
            'limit_per_minute': 5,
            'limit_per_day': 20,
        },
        {
            'model_key': 'gemini-2.5-flash',
            'display_name': 'Gemini 2.5 Flash',
            'provider': 'google',
            'is_enabled': True,
            'is_default': False,
            'fallback_priority': 10,
            'limit_per_minute': 5,
            'limit_per_day': 20,
        },
        {
            'model_key': 'gemini-2.5-flash-lite',
            'display_name': 'Gemini 2.5 Flash Lite',
            'provider': 'google',
            'is_enabled': True,
            'is_default': False,
            'fallback_priority': 20,
            'limit_per_minute': 10,
            'limit_per_day': 20,
        },
    ]
    for model_data in models_to_seed:
        GeminiModelSetting.objects.get_or_create(
            model_key=model_data['model_key'],
            defaults=model_data,
        )


def reverse_seed(apps, schema_editor):
    GeminiModelSetting = apps.get_model('media_manager', 'GeminiModelSetting')
    GeminiModelSetting.objects.filter(
        model_key__in=['gemini-3-flash-preview', 'gemini-2.5-flash', 'gemini-2.5-flash-lite']
    ).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("media_manager", "0026_geminigenerationattempt_geminimodelsetting_and_more"),
    ]

    operations = [
        migrations.RunPython(seed_gemini_models, reverse_seed),
    ]
