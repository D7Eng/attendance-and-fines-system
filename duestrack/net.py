from django.conf import settings


def client_ip(request):
    """The visitor's address. Behind nginx, REMOTE_ADDR is the proxy, so use the X-Real-IP header it sets."""
    if request is None:
        return None
    if settings.TRUST_X_REAL_IP and request.META.get("HTTP_X_REAL_IP"):
        return request.META["HTTP_X_REAL_IP"]
    return request.META.get("REMOTE_ADDR")
