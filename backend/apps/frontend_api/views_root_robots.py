from django.http import HttpResponse

def robots_txt(request):
    content = (
        "User-agent: *\n"
        "Disallow: /admin/\n"
        "Allow: /\n"
    )
    return HttpResponse(content, content_type="text/plain")