from django.conf import settings


def brand(request):
    """Site-wide brand values every template can read: the footer, the About
    page and the landing page all link to the YouTube channel."""
    return {
        'YOUTUBE_CHANNEL_URL': settings.YOUTUBE_CHANNEL_URL,
    }
