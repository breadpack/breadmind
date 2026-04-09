/**
 * BreadMind PWA Registration
 * Handles service worker lifecycle, install prompts, and update notifications.
 */
(function() {
  'use strict';

  let deferredInstallPrompt = null;

  // ── Service Worker Registration ──
  if ('serviceWorker' in navigator) {
    window.addEventListener('load', function() {
      navigator.serviceWorker.register('/sw.js', { scope: '/' })
        .then(function(registration) {
          console.log('[PWA] Service worker registered, scope:', registration.scope);

          // Check for updates periodically (every 60 minutes)
          setInterval(function() {
            registration.update();
          }, 60 * 60 * 1000);

          // Listen for new service worker waiting
          registration.addEventListener('updatefound', function() {
            var newWorker = registration.installing;
            if (newWorker) {
              newWorker.addEventListener('statechange', function() {
                if (newWorker.state === 'installed' && navigator.serviceWorker.controller) {
                  showUpdateBanner();
                }
              });
            }
          });
        })
        .catch(function(err) {
          console.warn('[PWA] Service worker registration failed:', err);
        });

      // Listen for SW_UPDATED messages
      navigator.serviceWorker.addEventListener('message', function(event) {
        if (event.data && event.data.type === 'SW_UPDATED') {
          showUpdateBanner();
        }
      });
    });
  }

  // ── Install Prompt ──
  window.addEventListener('beforeinstallprompt', function(event) {
    event.preventDefault();
    deferredInstallPrompt = event;
    showInstallButton();
  });

  window.addEventListener('appinstalled', function() {
    deferredInstallPrompt = null;
    hideInstallButton();
    console.log('[PWA] App installed successfully');
  });

  // ── UI Helpers ──

  function showUpdateBanner() {
    var existing = document.getElementById('pwa-update-banner');
    if (existing) return;

    var banner = document.createElement('div');
    banner.id = 'pwa-update-banner';
    banner.style.cssText = 'position:fixed;top:0;left:0;right:0;z-index:10000;background:#1e293b;border-bottom:2px solid #3b82f6;padding:12px 20px;display:flex;align-items:center;justify-content:space-between;font-size:13px;color:#e2e8f0;';
    banner.innerHTML = '<span>A new version of BreadMind is available.</span>' +
      '<div style="display:flex;gap:8px;">' +
        '<button id="pwa-update-btn" style="padding:6px 16px;background:#3b82f6;color:#fff;border:none;border-radius:6px;cursor:pointer;font-size:12px;">Reload</button>' +
        '<button id="pwa-update-dismiss" style="padding:6px 12px;background:transparent;color:#94a3b8;border:1px solid #334155;border-radius:6px;cursor:pointer;font-size:12px;">Later</button>' +
      '</div>';
    document.body.prepend(banner);

    document.getElementById('pwa-update-btn').addEventListener('click', function() {
      window.location.reload();
    });
    document.getElementById('pwa-update-dismiss').addEventListener('click', function() {
      banner.remove();
    });
  }

  function showInstallButton() {
    // Add install option to header if it exists
    var header = document.querySelector('header');
    if (!header) return;

    var existing = document.getElementById('pwa-install-btn');
    if (existing) return;

    var btn = document.createElement('button');
    btn.id = 'pwa-install-btn';
    btn.textContent = 'Install App';
    btn.style.cssText = 'margin-left:auto;padding:6px 14px;background:transparent;color:#94a3b8;border:1px solid #334155;border-radius:6px;cursor:pointer;font-size:12px;transition:all 0.2s;';
    btn.addEventListener('mouseenter', function() {
      btn.style.borderColor = '#3b82f6';
      btn.style.color = '#e2e8f0';
    });
    btn.addEventListener('mouseleave', function() {
      btn.style.borderColor = '#334155';
      btn.style.color = '#94a3b8';
    });
    btn.addEventListener('click', promptInstall);
    header.appendChild(btn);
  }

  function hideInstallButton() {
    var btn = document.getElementById('pwa-install-btn');
    if (btn) btn.remove();
  }

  function promptInstall() {
    if (!deferredInstallPrompt) return;
    deferredInstallPrompt.prompt();
    deferredInstallPrompt.userChoice.then(function(result) {
      console.log('[PWA] Install prompt result:', result.outcome);
      deferredInstallPrompt = null;
    });
  }

  // Expose for external use
  window.BreadMindPWA = {
    promptInstall: promptInstall,
    isInstallable: function() { return deferredInstallPrompt !== null; },
  };
})();
