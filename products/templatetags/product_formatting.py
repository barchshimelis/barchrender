from django import template

from products.utils import format_product_code

register = template.Library()


@register.filter(name="format_product_code")
def format_product_code_filter(value: str | None) -> str:
    """Render product identifiers as triad codes (e.g., ABC-123-XYZ)."""
    if not value:
        return ""
    return format_product_code(str(value))
