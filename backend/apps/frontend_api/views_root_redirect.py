from django.http import HttpResponseRedirect
from django.utils import translation
from django.urls import reverse
from django.conf import settings


def smart_root_redirect(request):
    # Try to get language from cookie, then Accept-Language header, then settings.LANGUAGE_CODE
    lang = request.COOKIES.get(settings.LANGUAGE_COOKIE_NAME)
    if not lang:
        lang = translation.get_language_from_request(request, check_path=False)
    if not lang:
        lang = settings.LANGUAGE_CODE
    # Normalize to short code (e.g., 'en', 'ar')
    lang = lang.split('-')[0]
    # Build redirect URL
    return HttpResponseRedirect(f'/{lang}/')
