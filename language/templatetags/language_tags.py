from django import template
from django.conf import settings
from django.utils.translation import get_language_info

register = template.Library()


@register.simple_tag
def supported_languages():
    """Return the list of supported languages (code + localized label)."""
    languages = getattr(settings, "LANGUAGES", ())
    normalized = []
    for code, name in languages:
        try:
            info = get_language_info(code)
        except KeyError:
            info = {}

        normalized.append(
            {
                "code": code,
                "name": name,
                "local_name": info.get("name_local") or name,
            }
        )
    return normalized
