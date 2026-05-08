from django.conf import settings
from django.http import HttpResponseRedirect
from django.urls import is_valid_path
from django.utils import translation

from django.middleware.locale import LocaleMiddleware


class DefaultArabicLocaleMiddleware(LocaleMiddleware):
    response_redirect_class = HttpResponseRedirect

    def process_request(self, request):
        urlconf = getattr(request, "urlconf", settings.ROOT_URLCONF)
        language_from_path = translation.get_language_from_path(request.path_info)

        if not language_from_path:
            default_language = settings.LANGUAGE_CODE
            language_path = f"/{default_language}{request.path_info}"
            path_valid = is_valid_path(language_path, urlconf)
            path_needs_slash = (
                not path_valid
                and settings.APPEND_SLASH
                and not language_path.endswith("/")
                and is_valid_path(f"{language_path}/", urlconf)
            )

            if path_valid or path_needs_slash:
                translation.activate(default_language)
                request.LANGUAGE_CODE = translation.get_language()
                return

        super().process_request(request)