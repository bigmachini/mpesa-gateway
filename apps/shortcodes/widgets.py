from django import forms
from django.utils.html import format_html


class AccountCodeWidget(forms.Widget):
    template_name = "shortcodes/account_code_widget.html"  # required by Unfold's template_name check
    """
    Three-state widget for the Shared Paybill account_code field:

      1. Read-only  — editing an existing shortcode; code is locked.
      2. Auto state — creating a new shortcode; code will be auto-generated.
                      Shows a "Suggest my own" button.
      3. Custom state — user clicked "Suggest my own"; text input is visible.
                        A hidden field carries the value on submit.

    States 2 and 3 are toggled by shortcode_admin.js.
    """

    class Media:
        js = ('shortcodes/js/shortcode_admin.js',)

    def __init__(self, is_existing=False, *args, **kwargs):
        self.is_existing = is_existing
        super().__init__(*args, **kwargs)

    def render(self, name, value, attrs=None, renderer=None):
        if self.is_existing and value:
            return format_html(
                '<div class="account-code-widget account-code-locked flex items-center gap-3">'
                '  <span class="account-code-value font-mono text-sm font-semibold'
                '        text-gray-900 dark:text-gray-100 tracking-widest">{}</span>'
                '  <span class="text-xs text-gray-400 dark:text-gray-500 italic">'
                '    Cannot be changed after assignment</span>'
                '  <input type="hidden" name="{}" value="{}">'
                '</div>',
                value, name, value,
            )

        # New shortcode — auto / custom toggle
        return format_html(
            '<div class="account-code-widget" data-field-name="{name}">'

            # ── Auto state (default) ──────────────────────────────────────────
            '  <div class="account-code-auto-state flex items-center gap-3">'
            '    <span class="text-sm text-gray-400 dark:text-gray-500 italic">'
            '      Will be auto-generated'
            '    </span>'
            '    <button type="button" class="account-code-suggest-btn'
            '      cursor-pointer rounded-md border border-gray-300 dark:border-gray-600'
            '      bg-white dark:bg-gray-800'
            '      px-3 py-1.5 text-xs font-medium'
            '      text-gray-700 dark:text-gray-300'
            '      hover:bg-gray-50 dark:hover:bg-gray-700'
            '      transition-colors">'
            '      Suggest my own'
            '    </button>'
            '  </div>'

            # ── Custom input state (hidden until button clicked) ───────────────
            '  <div class="account-code-custom-state flex flex-col gap-2" style="display:none">'
            '    <div class="flex items-center gap-2">'
            '      <input type="text"'
            '             class="account-code-input'
            '               w-28 rounded-md border border-gray-300 dark:border-gray-600'
            '               bg-white dark:bg-gray-800'
            '               px-3 py-1.5 text-sm font-mono tracking-widest'
            '               text-gray-900 dark:text-gray-100'
            '               placeholder-gray-400 dark:placeholder-gray-600'
            '               focus:border-primary-500 dark:focus:border-primary-400'
            '               focus:outline-none focus:ring-1 focus:ring-primary-500'
            '               transition-colors"'
            '             maxlength="6"'
            '             placeholder="000000"'
            '             inputmode="numeric"'
            '             autocomplete="off">'
            '      <button type="button" class="account-code-cancel-btn'
            '        cursor-pointer rounded-md border border-gray-300 dark:border-gray-600'
            '        bg-white dark:bg-gray-800'
            '        px-3 py-1.5 text-xs font-medium'
            '        text-gray-500 dark:text-gray-400'
            '        hover:bg-gray-50 dark:hover:bg-gray-700'
            '        transition-colors">'
            '        ✕ Cancel'
            '      </button>'
            '    </div>'
            '    <p class="text-xs text-gray-400 dark:text-gray-500 m-0">'
            '      Enter a 6-digit number of your choice'
            '    </p>'
            '    <div class="account-code-chips flex flex-wrap gap-1.5"></div>'
            '  </div>'

            # Hidden field carries the value on submit
            '  <input type="hidden" name="{name}" value="" class="account-code-hidden">'
            '</div>',
            name=name,
        )

    def value_from_datadict(self, data, files, name):
        return data.get(name, '')
