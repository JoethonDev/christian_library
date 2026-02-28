from django.http import HttpResponseRedirect
from django.utils import translation
from django.urls import reverse
from django.conf import settings


def smart_root_redirect(request):
    """
    Optimized root redirect:
    1. If Accept-Language or existing session/cookie favors 'en', redirect to /en/
    2. Default to /ar/ as requested by library administration
    """
    # Prefer explicit language selection from cookie/headers
    lang = request.COOKIES.get(settings.LANGUAGE_COOKIE_NAME)
    if not lang:
        lang = translation.get_language_from_request(request, check_path=False)
    
    # If explicitly English, go to English
    if lang and lang.startswith('en'):
        return HttpResponseRedirect('/en/')
        
    # Default to Arabic for everything else
    return HttpResponseRedirect('/ar/')
