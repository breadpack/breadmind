(function() {
    'use strict';

    const STORAGE_KEY_SIDEBAR = 'breadmind_sidebar';
    const STORAGE_KEY_PTAB_PREFIX = 'breadmind_ptab_';

    const PAGE_INIT = {
        chat: function() { if (typeof loadSidebarAssistant === 'function') loadSidebarAssistant(); },
        assistant: function() { if (typeof initPersonalTab === 'function') initPersonalTab(); },
        automation: function() { if (typeof initAutomationPage === 'function') initAutomationPage(); },
        monitoring: function() { if (typeof initMonitoringPage === 'function') initMonitoringPage(); },
        explore: function() { if (typeof initExplorePage === 'function') initExplorePage(); },
        connections: function() { if (typeof initConnectionsPage === 'function') initConnectionsPage(); },
        settings: function() { if (typeof loadSettings === 'function') loadSettings(); },
    };

    // Hash aliases for backwards compatibility
    const HASH_ALIASES = {
        store: 'explore',
        skills: 'explore',
        plugins: 'explore',
        personal: 'assistant',
    };

    window.switchPage = function(name) {
        // Update sidebar active state
        document.querySelectorAll('.sidebar-item[data-page]').forEach(function(item) {
            item.classList.toggle('active', item.dataset.page === name);
        });

        // Hide all pages
        document.querySelectorAll('.page').forEach(function(page) {
            page.classList.remove('active');
            page.style.display = 'none';
        });

        // Show target page
        var target = document.getElementById('page-' + name);
        if (target) {
            target.classList.add('active');
            target.style.display = 'flex';
        }

        // Update URL hash
        location.hash = name;

        // Call page initializer if registered
        if (PAGE_INIT[name]) {
            PAGE_INIT[name]();
        }

        closeMobileSidebar();
    };

    window.switchTab = function(name) {
        var aliases = {
            chat: 'chat',
            monitoring: 'monitoring',
            store: 'explore',
            skills: 'explore',
            plugins: 'explore',
            personal: 'assistant',
            settings: 'settings',
        };
        var resolved = aliases.hasOwnProperty(name) ? aliases[name] : name;
        switchPage(resolved);
    };

    window.toggleSidebar = function() {
        var sidebar = document.getElementById('app-sidebar');
        if (!sidebar) return;
        sidebar.classList.toggle('collapsed');
        var collapsed = sidebar.classList.contains('collapsed');
        try {
            localStorage.setItem(STORAGE_KEY_SIDEBAR, collapsed ? 'collapsed' : 'expanded');
        } catch (e) {}
    };

    window.openMobileSidebar = function() {
        var sidebar = document.getElementById('app-sidebar');
        var overlay = document.getElementById('mobile-overlay');
        if (sidebar) sidebar.classList.add('mobile-open');
        if (overlay) overlay.classList.add('visible');
    };

    window.closeMobileSidebar = function() {
        var sidebar = document.getElementById('app-sidebar');
        var overlay = document.getElementById('mobile-overlay');
        if (sidebar) sidebar.classList.remove('mobile-open');
        if (overlay) overlay.classList.remove('visible');
    };

    window.switchPageTab = function(pageId, tabName) {
        var pageEl = document.getElementById('page-' + pageId);
        if (!pageEl) return;

        // Toggle active state on tab buttons
        pageEl.querySelectorAll('.page-tab[data-subtab]').forEach(function(btn) {
            btn.classList.toggle('active', btn.dataset.subtab === tabName);
        });

        // Toggle display on panels
        pageEl.querySelectorAll('.page-panel').forEach(function(panel) {
            var isTarget = panel.id === 'subtab-' + pageId + '-' + tabName;
            panel.style.display = isTarget ? '' : 'none';
        });

        try {
            localStorage.setItem(STORAGE_KEY_PTAB_PREFIX + pageId, tabName);
        } catch (e) {}
    };

    window.initSidebar = function() {
        // Restore sidebar collapsed state
        var sidebar = document.getElementById('app-sidebar');
        if (sidebar) {
            try {
                var saved = localStorage.getItem(STORAGE_KEY_SIDEBAR);
                if (saved === 'collapsed') {
                    sidebar.classList.add('collapsed');
                }
            } catch (e) {}
        }

        // Bind click handlers on sidebar items
        document.querySelectorAll('.sidebar-item[data-page]').forEach(function(item) {
            item.addEventListener('click', function() {
                switchPage(item.dataset.page);
            });
        });

        // Restore page from URL hash
        var hash = location.hash.replace('#', '');
        if (hash) {
            var resolved = HASH_ALIASES.hasOwnProperty(hash) ? HASH_ALIASES[hash] : hash;
            if (PAGE_INIT.hasOwnProperty(resolved) || document.getElementById('page-' + resolved)) {
                switchPage(resolved);
                return;
            }
        }

        // Default to chat
        switchPage('chat');
    };

})();
