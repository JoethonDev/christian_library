from django.http import HttpResponseRedirect
from django.utils import translation


def smart_root_redirect(request):
    """
    Redirect root (/) to the user's active language prefix.
    Respects the django_language cookie set by set_language view.
    Defaults to Arabic if no language preference is set.
    """
    lang = translation.get_language() or 'ar'
    return HttpResponseRedirect(f'/{lang}/')
