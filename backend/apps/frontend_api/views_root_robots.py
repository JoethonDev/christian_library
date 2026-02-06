from django.http import HttpResponse
from django.contrib.sites.models import Site


def robots_txt(request):
    """
    Generate robots.txt dynamically
    - Disallows admin areas and API endpoints
    - Allows all public media and landing pages
    - References master sitemap index (SEO best practice)
    """
    # Get the current site domain
    try:
        current_site = Site.objects.get_current()
        domain = current_site.domain
    except:
        domain = request.get_host()
    
    # Build protocol (HTTPS in production, HTTP in development)
    protocol = 'https' if request.is_secure() else 'http'
    
    # Master sitemap at root (best practice for SEO)
    master_sitemap = f"{protocol}://{domain}/sitemap.xml"
    
    content = (
        "# robots.txt for Christian Library\n"
        "# Auto-generated and managed by Django\n"
        "# Following Google SEO Best Practices (2026)\n\n"
        "User-agent: *\n\n"
        
        "# Disallow admin areas\n"
        "Disallow: /admin/\n"
        "Disallow: /api/auth/\n"
        "Disallow: /dashboard/\n\n"
        
        "# Disallow language selection and API endpoints\n"
        "Disallow: /i18n/\n"
        "Disallow: /api/\n\n"
        
        "# Allow all public content pages\n"
        "Allow: /ar/\n"
        "Allow: /en/\n"
        "Allow: /ar/videos/\n"
        "Allow: /ar/audios/\n"
        "Allow: /ar/pdfs/\n"
        "Allow: /en/videos/\n"
        "Allow: /en/audios/\n"
        "Allow: /en/pdfs/\n\n"
        
        "# Master Sitemap Index\n"
        "# This index contains all segmented sitemaps (by content type and language)\n"
        f"Sitemap: {master_sitemap}\n"
    )
    return HttpResponse(content, content_type="text/plain")