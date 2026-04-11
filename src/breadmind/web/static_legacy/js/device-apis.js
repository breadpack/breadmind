/**
 * BreadMind Device APIs
 * Feature-detected wrappers for clipboard, wake lock, web share, vibration.
 */
(function() {
  'use strict';

  // ── Clipboard ──

  /**
   * Copy text to clipboard with fallback.
   * @param {string} text
   * @returns {Promise<boolean>}
   */
  async function copyToClipboard(text) {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      try {
        await navigator.clipboard.writeText(text);
        return true;
      } catch (e) {
        // Fall through to fallback
      }
    }
    // execCommand fallback
    try {
      var textarea = document.createElement('textarea');
      textarea.value = text;
      textarea.style.cssText = 'position:fixed;left:-9999px;top:-9999px;opacity:0;';
      document.body.appendChild(textarea);
      textarea.select();
      var result = document.execCommand('copy');
      document.body.removeChild(textarea);
      return result;
    } catch (e) {
      return false;
    }
  }

  // ── Screen Wake Lock ──

  var wakeLockSentinel = null;

  /**
   * Request screen wake lock to keep display on (for monitoring page).
   * @returns {Promise<boolean>}
   */
  async function requestWakeLock() {
    if (!('wakeLock' in navigator)) return false;
    try {
      wakeLockSentinel = await navigator.wakeLock.request('screen');
      wakeLockSentinel.addEventListener('release', function() {
        wakeLockSentinel = null;
      });
      console.log('[DeviceAPI] Wake lock acquired');
      return true;
    } catch (e) {
      console.debug('[DeviceAPI] Wake lock failed:', e.message);
      return false;
    }
  }

  /**
   * Release screen wake lock.
   * @returns {Promise<boolean>}
   */
  async function releaseWakeLock() {
    if (!wakeLockSentinel) return false;
    try {
      await wakeLockSentinel.release();
      wakeLockSentinel = null;
      console.log('[DeviceAPI] Wake lock released');
      return true;
    } catch (e) {
      return false;
    }
  }

  /**
   * Check if wake lock is currently active.
   * @returns {boolean}
   */
  function isWakeLockActive() {
    return wakeLockSentinel !== null;
  }

  // Re-acquire wake lock when page becomes visible again
  document.addEventListener('visibilitychange', function() {
    if (document.visibilityState === 'visible' && wakeLockSentinel === null && _wakeLockAutoReacquire) {
      requestWakeLock();
    }
  });

  var _wakeLockAutoReacquire = false;

  /**
   * Enable/disable auto re-acquire of wake lock on visibility change.
   */
  function setWakeLockAutoReacquire(enabled) {
    _wakeLockAutoReacquire = enabled;
  }

  // ── Web Share ──

  /**
   * Share content using the Web Share API.
   * @param {string} title
   * @param {string} text
   * @param {string} url
   * @returns {Promise<boolean>}
   */
  async function shareContent(title, text, url) {
    if (!navigator.share) return false;
    try {
      await navigator.share({ title: title, text: text, url: url });
      return true;
    } catch (e) {
      // User cancelled or error
      if (e.name !== 'AbortError') {
        console.debug('[DeviceAPI] Share failed:', e.message);
      }
      return false;
    }
  }

  /**
   * Check if Web Share API is available.
   * @returns {boolean}
   */
  function canShare() {
    return !!navigator.share;
  }

  // ── Vibration ──

  /**
   * Vibrate the device with a pattern.
   * @param {number|number[]} pattern - duration in ms or pattern array
   * @returns {boolean}
   */
  function vibrateAlert(pattern) {
    if (!navigator.vibrate) return false;
    try {
      return navigator.vibrate(pattern || [200, 100, 200]);
    } catch (e) {
      return false;
    }
  }

  // ── Integration: Enhance copy buttons on code blocks ──

  function enhanceCopyButtons() {
    // Override the inline onclick handlers with robust clipboard API
    document.addEventListener('click', function(e) {
      if (!e.target.classList.contains('copy-btn')) return;
      var pre = e.target.closest('pre');
      if (!pre) return;
      var code = pre.querySelector('code');
      if (!code) return;
      e.preventDefault();
      e.stopPropagation();
      var btn = e.target;
      copyToClipboard(code.textContent).then(function(ok) {
        if (ok) {
          btn.textContent = 'Copied!';
          vibrateAlert(50);
        } else {
          btn.textContent = 'Failed';
        }
        setTimeout(function() { btn.textContent = 'Copy'; }, 1500);
      });
    }, true);
  }

  // ── Integration: Wake lock for monitoring tab ──

  function setupMonitoringWakeLock() {
    // Watch for tab switches to monitoring
    var origSwitchTab = window.switchTab;
    if (typeof origSwitchTab !== 'function') return;

    window.switchTab = function(name) {
      origSwitchTab(name);
      if (name === 'monitoring') {
        setWakeLockAutoReacquire(true);
        requestWakeLock();
      } else {
        setWakeLockAutoReacquire(false);
        releaseWakeLock();
      }
    };
  }

  // Init
  window.addEventListener('load', function() {
    enhanceCopyButtons();
    setupMonitoringWakeLock();
  });

  // Expose API
  window.BreadMindDevice = {
    copyToClipboard: copyToClipboard,
    requestWakeLock: requestWakeLock,
    releaseWakeLock: releaseWakeLock,
    isWakeLockActive: isWakeLockActive,
    shareContent: shareContent,
    canShare: canShare,
    vibrateAlert: vibrateAlert,
  };
})();
