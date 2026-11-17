from django.conf import settings
from django.contrib.auth.models import User
from django.core.cache import cache

LEARNER_COUNT_CACHE_KEY = 'nav:learner_count'
LEARNER_COUNT_TTL_SECONDS = 300


def brand(request):
    """Site-wide brand values every template can read: the footer, the About
    page and the landing page all link to the YouTube channel."""
    return {
        'YOUTUBE_CHANNEL_URL': settings.YOUTUBE_CHANNEL_URL,
    }


def learner_count(request):
    """Number of registered learners shown in the nav. Staff and superusers
    are excluded, so it counts students only.

    Every page renders the nav, so the count is cached for a few minutes
    rather than queried on each request; a brand-new signup shows up within
    LEARNER_COUNT_TTL_SECONDS.
    """
    count = cache.get_or_set(
        LEARNER_COUNT_CACHE_KEY,
        lambda: User.objects.filter(is_staff=False, is_superuser=False).count(),
        LEARNER_COUNT_TTL_SECONDS,
    )
    return {'LEARNER_COUNT': count}
