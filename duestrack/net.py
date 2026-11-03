from django.conf import settings


def client_ip(request):
    """The visitor's address.

    Behind a proxy REMOTE_ADDR is the proxy, so read the header the proxy sets instead:
    X-Real-IP behind our nginx, or Cloudflare's True-Client-IP / CF-Connecting-IP on Render.
    Only headers listed in CLIENT_IP_HEADERS are trusted, because clients can send any header.
    """
    if request is None:
        return None
    for header in settings.CLIENT_IP_HEADERS:
        value = request.META.get(header, "").strip()
        if value:
            return value
    return request.META.get("REMOTE_ADDR")
