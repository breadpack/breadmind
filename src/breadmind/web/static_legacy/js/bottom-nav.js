/**
 * BreadMind Bottom Navigation
 * Fixed bottom bar for mobile (<=768px) that syncs with tab navigation.
 */
(function() {
  'use strict';

  var NAV_ITEMS = [
    { id: 'chat', label: 'Chat', icon: '<svg viewBox="0 0 24 24"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>' },
    { id: 'monitoring', label: 'Monitor', icon: '<svg viewBox="0 0 24 24"><path d="M22 12h-4l-3 9L9 3l-3 9H2"/></svg>' },
    { id: 'store', label: 'Explore', icon: '<svg viewBox="0 0 24 24"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>' },
    { id: 'plugins', label: 'Plugins', icon: '<svg viewBox="0 0 24 24"><path d="M12 2L2 7l10 5 10-5-10-5z"/><path d="M2 17l10 5 10-5"/><path d="M2 12l10 5 10-5"/></svg>' },
    { id: 'more', label: 'More', icon: '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="1"/><circle cx="12" cy="5" r="1"/><circle cx="12" cy="19" r="1"/></svg>' },
  ];

  var MORE_TABS = ['skills', 'personal', 'settings'];

  function createBottomNav() {
    // Only show on mobile
    if (window.innerWidth > 768) return;

    var existing = document.getElementById('bottom-nav');
    if (existing) return;

    var nav = document.createElement('nav');
    nav.id = 'bottom-nav';
    nav.className = 'bottom-nav';
    nav.setAttribute('role', 'navigation');
    nav.setAttribute('aria-label', 'Main navigation');

    var items = document.createElement('div');
    items.className = 'bottom-nav-items';

    NAV_ITEMS.forEach(function(item) {
      var el = document.createElement('div');
      el.className = 'bottom-nav-item' + (item.id === 'chat' ? ' active' : '');
      el.dataset.tab = item.id;
      el.setAttribute('role', 'button');
      el.setAttribute('aria-label', item.label);
      el.innerHTML = '<div style="position:relative;">' + item.icon + '<div class="badge"></div></div><span>' + item.label + '</span>';
      el.addEventListener('click', function() { onNavClick(item.id); });
      items.appendChild(el);
    });

    nav.appendChild(items);
    document.body.appendChild(nav);
  }

  function onNavClick(tabId) {
    if (tabId === 'more') {
      showMoreMenu();
      return;
    }

    // Use existing switchTab function
    if (typeof window.switchTab === 'function') {
      window.switchTab(tabId);
    }
    updateActiveState(tabId);
    closeMoreMenu();
  }

  function updateActiveState(tabId) {
    var items = document.querySelectorAll('.bottom-nav-item');
    items.forEach(function(item) {
      var isMore = MORE_TABS.indexOf(tabId) !== -1 && item.dataset.tab === 'more';
      item.classList.toggle('active', item.dataset.tab === tabId || isMore);
    });
  }

  function showMoreMenu() {
    var existing = document.getElementById('more-menu-overlay');
    if (existing) {
      closeMoreMenu();
      return;
    }

    var overlay = document.createElement('div');
    overlay.id = 'more-menu-overlay';
    overlay.style.cssText = 'position:fixed;inset:0;z-index:8999;background:rgba(0,0,0,0.5);';
    overlay.addEventListener('click', closeMoreMenu);

    var menu = document.createElement('div');
    menu.id = 'more-menu';
    menu.style.cssText = 'position:fixed;bottom:57px;left:0;right:0;z-index:9001;background:#1e293b;border-top:1px solid #334155;border-radius:16px 16px 0 0;padding:16px;padding-bottom:calc(16px + env(safe-area-inset-bottom, 0px));';

    var moreItems = [
      { id: 'skills', label: 'Skill Store', icon: '&#x2728;' },
      { id: 'personal', label: 'Assistant', icon: '&#x1F4CB;' },
      { id: 'settings', label: 'Settings', icon: '&#x2699;' },
    ];

    moreItems.forEach(function(item) {
      var btn = document.createElement('div');
      btn.style.cssText = 'display:flex;align-items:center;gap:12px;padding:14px 12px;border-radius:8px;cursor:pointer;color:#e2e8f0;font-size:14px;';
      btn.innerHTML = '<span style="font-size:20px;width:28px;text-align:center;">' + item.icon + '</span>' + item.label;
      btn.addEventListener('click', function() {
        onNavClick(item.id);
      });
      btn.addEventListener('mouseenter', function() { btn.style.background = '#334155'; });
      btn.addEventListener('mouseleave', function() { btn.style.background = 'transparent'; });
      menu.appendChild(btn);
    });

    document.body.appendChild(overlay);
    document.body.appendChild(menu);
  }

  function closeMoreMenu() {
    var overlay = document.getElementById('more-menu-overlay');
    var menu = document.getElementById('more-menu');
    if (overlay) overlay.remove();
    if (menu) menu.remove();
  }

  // Sync with existing tab switches
  var origSwitchTab = window.switchTab;
  if (typeof origSwitchTab === 'function') {
    window.switchTab = function(name) {
      origSwitchTab(name);
      updateActiveState(name);
    };
  }

  // Update monitoring badge
  function updateMonitoringBadge() {
    var countEl = document.getElementById('eventCount');
    var monItem = document.querySelector('.bottom-nav-item[data-tab="monitoring"]');
    if (!countEl || !monItem) return;
    var count = parseInt(countEl.textContent) || 0;
    monItem.classList.toggle('has-badge', count > 0);
  }

  // Init
  window.addEventListener('load', function() {
    createBottomNav();
    setInterval(updateMonitoringBadge, 2000);
  });

  // Recreate on resize
  window.addEventListener('resize', function() {
    var nav = document.getElementById('bottom-nav');
    if (window.innerWidth > 768) {
      if (nav) nav.style.display = 'none';
      closeMoreMenu();
    } else {
      if (nav) {
        nav.style.display = 'block';
      } else {
        createBottomNav();
      }
    }
  });
})();
