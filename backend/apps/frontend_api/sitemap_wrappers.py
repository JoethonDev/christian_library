from django.contrib.sitemaps.views import index as django_sitemap_index, sitemap as django_sitemap

# Custom wrapper to remove X-Robots-Tag header for XML responses

def sitemap_index(request, *args, **kwargs):
    response = django_sitemap_index(request, *args, **kwargs)
    if response.get('Content-Type', '').startswith('application/xml') or request.path.endswith('.xml'):
        # Remove X-Robots-Tag header if set by Django
        if 'X-Robots-Tag' in response:
            del response['X-Robots-Tag']
    return response

def sitemap(request, *args, **kwargs):
    response = django_sitemap(request, *args, **kwargs)
    if response.get('Content-Type', '').startswith('application/xml') or request.path.endswith('.xml'):
        if 'X-Robots-Tag' in response:
            del response['X-Robots-Tag']
    return response
