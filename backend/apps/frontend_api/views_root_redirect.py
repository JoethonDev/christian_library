from django.http import HttpResponseRedirect
from django.utils import translation
from django.urls import reverse
from django.conf import settings


def smart_root_redirect(request):
    """
    Optimized root redirect:
    Always default to Arabic (/ar/) as the primary language for the library,
    ignoring browser 'Accept-Language' headers to ensure consistent entry.
    """
    # Simply redirect everything to /ar/ as requested
    return HttpResponseRedirect('/ar/')
