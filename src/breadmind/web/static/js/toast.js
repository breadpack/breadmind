// src/breadmind/web/static/js/toast.js
/**
 * Toast notification system
 */
(function() {
    'use strict';

    let container = null;

    function ensureContainer() {
        if (container) return container;
        container = document.createElement('div');
        container.id = 'toast-container';
        container.style.cssText = 'position:fixed;bottom:24px;left:24px;z-index:9999;display:flex;flex-direction:column;gap:8px;';
        document.body.appendChild(container);
        return container;
    }

    window.showToast = function(message, type = 'info', duration = 3000) {
        const c = ensureContainer();
        const toast = document.createElement('div');
        toast.className = `toast toast-${type}`;

        const icons = { success: '\u2705', error: '\u274c', warning: '\u26a0\ufe0f', info: '\u2139\ufe0f' };
        toast.innerHTML = `<span class="toast-icon">${icons[type] || icons.info}</span><span class="toast-msg">${message}</span>`;

        c.appendChild(toast);
        requestAnimationFrame(() => toast.classList.add('toast-show'));

        setTimeout(() => {
            toast.classList.remove('toast-show');
            toast.classList.add('toast-hide');
            setTimeout(() => toast.remove(), 300);
        }, duration);
    };

    // Button loading state helpers
    window.btnLoading = function(btn, text = '\ucc98\ub9ac \uc911...') {
        btn._origText = btn.textContent;
        btn._origDisabled = btn.disabled;
        btn.disabled = true;
        btn.textContent = text;
        btn.classList.add('btn-loading');
    };

    window.btnReset = function(btn) {
        btn.disabled = btn._origDisabled || false;
        btn.textContent = btn._origText || btn.textContent;
        btn.classList.remove('btn-loading');
    };
})();
