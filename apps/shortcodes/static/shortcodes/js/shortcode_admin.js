'use strict';

document.addEventListener('DOMContentLoaded', function () {

  // ─── Account code widget ────────────────────────────────────────────────

  document.querySelectorAll('.account-code-widget:not(.account-code-locked)').forEach(function (widget) {
    var autoState   = widget.querySelector('.account-code-auto-state');
    var customState = widget.querySelector('.account-code-custom-state');
    var hiddenInput = widget.querySelector('.account-code-hidden');
    var textInput   = widget.querySelector('.account-code-input');
    var suggestBtn  = widget.querySelector('.account-code-suggest-btn');
    var cancelBtn   = widget.querySelector('.account-code-cancel-btn');
    var chipsEl     = widget.querySelector('.account-code-chips');

    suggestBtn.addEventListener('click', function () {
      autoState.style.display   = 'none';
      customState.style.display = 'block';
      textInput.focus();
    });

    cancelBtn.addEventListener('click', function () {
      customState.style.display = 'none';
      autoState.style.display   = 'block';
      textInput.value     = '';
      hiddenInput.value   = '';
      chipsEl.innerHTML   = '';
    });

    // Numeric-only; sync to hidden field
    textInput.addEventListener('input', function () {
      this.value        = this.value.replace(/\D/g, '').slice(0, 6);
      hiddenInput.value = this.value;
    });

    // ── Parse suggestion chips from server error ─────────────────────────
    // Error format: "Account code 123456 is already taken.
    //                Available suggestions: 123457, 123455, 123458."
    var fieldRow  = widget.closest('[class*="field-account_code"]');
    if (!fieldRow) fieldRow = widget.closest('div');
    var errorEl   = fieldRow && fieldRow.querySelector('.errorlist li, .help-block');

    if (errorEl) {
      var match = errorEl.textContent.match(/Available suggestions:\s*([\d,\s]+)/);
      if (match) {
        var codes = match[1].split(',').map(function (s) { return s.trim(); }).filter(Boolean);
        if (codes.length) {
          // Show the custom input state since we had a preference
          autoState.style.display   = 'none';
          customState.style.display = 'block';

          chipsEl.innerHTML = '<span class="text-xs text-gray-400 dark:text-gray-500 self-center">Try: </span>';
          codes.forEach(function (code) {
            var chip = document.createElement('button');
            chip.type        = 'button';
            chip.textContent = code;
            chip.className   = [
              'account-code-chip',
              'cursor-pointer', 'rounded', 'border',
              'border-gray-300', 'dark:border-gray-600',
              'bg-white', 'dark:bg-gray-800',
              'px-2.5', 'py-1',
              'text-xs', 'font-mono', 'tracking-wider',
              'text-gray-700', 'dark:text-gray-300',
              'hover:border-primary-500', 'hover:text-primary-600', 'dark:hover:text-primary-400',
              'transition-colors',
            ].join(' ');
            chip.addEventListener('click', function () {
              textInput.value   = code;
              hiddenInput.value = code;
              chipsEl.querySelectorAll('.account-code-chip').forEach(function (c) {
                c.classList.remove(
                  'border-primary-500', 'bg-primary-50', 'dark:bg-primary-900',
                  'text-primary-600', 'dark:text-primary-400'
                );
              });
              chip.classList.add(
                'border-primary-500', 'bg-primary-50', 'dark:bg-primary-900',
                'text-primary-600', 'dark:text-primary-400'
              );
            });
            chipsEl.appendChild(chip);
          });
        }
      }
    }
  });

});
