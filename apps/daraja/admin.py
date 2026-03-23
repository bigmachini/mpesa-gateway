"""
Daraja has no models of its own.
C2B URL registration is surfaced as an admin action on PaybillShortcodeAdmin.
"""
from django.contrib import messages

from apps.shortcodes.admin import PaybillShortcodeAdmin
from apps.shortcodes.models import PaybillShortcode
from .c2b import register_c2b_urls


def _register_c2b_urls_action(modeladmin, request, queryset):
    success = 0
    for shortcode in queryset:
        try:
            register_c2b_urls(shortcode)
            success += 1
        except Exception as exc:
            modeladmin.message_user(
                request,
                f'Failed to register URLs for {shortcode}: {exc}',
                level=messages.ERROR,
            )
    if success:
        modeladmin.message_user(
            request,
            f'Successfully registered C2B URLs for {success} shortcode(s).',
            level=messages.SUCCESS,
        )


_register_c2b_urls_action.short_description = 'Register C2B callback URLs with Safaricom'

# Attach the action to the Paybill admin
PaybillShortcodeAdmin.actions = list(PaybillShortcodeAdmin.actions or []) + [_register_c2b_urls_action]
