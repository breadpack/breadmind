# Web Menu Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Migrate BreadMind's top-tab navigation to a collapsible sidebar layout, consolidate 3 stores into Explore, decompose Settings overload into Automation/Monitoring/Connections sections.

**Architecture:** Replace the horizontal `<div class="tabs">` with a vertical `<nav class="app-sidebar">`. Restructure `<body>` from column flex to row flex (`sidebar + main`). Existing page content (chat, monitoring, stores, personal, settings) is wrapped in `<div class="page">` containers. New pages (Automation, Connections) aggregate features previously scattered across Settings sub-tabs. All backend APIs remain unchanged.

**Tech Stack:** Vanilla HTML/CSS/JS, CSS custom properties, existing glassmorphism theme variables

---

## File Structure

### New files
| File | Responsibility |
|------|---------------|
| `static/css/sidebar.css` | App sidebar + page layout + page-tabs component |
| `static/js/sidebar.js` | Sidebar toggle, page switching, hash routing, responsive |
| `static/js/automation.js` | Automation page: Scheduler + Swarm + Sub-agent + Container + Webhook endpoints rendering |
| `static/js/monitoring-page.js` | Monitoring page: tabs for Events, Audit Log, Usage, Tool Metrics, Approvals |
| `static/js/connections.js` | Connections page: tabs for Integrations, Messenger |

### Modified files
| File | Changes |
|------|---------|
| `static/index.html` | Replace body layout, remove `.tabs`, rename `.tab-content` → `.page`, add sidebar HTML, rewire `switchTab` → `switchPage`, restructure Settings sub-tabs |
| `static/css/glass-theme.css` | Add `--sidebar-*` CSS variables, update `.header`/`.tabs` overrides |
| `static/js/personal.js:134` | Change `switchTab('settings')` → `switchPage('settings')` |
| `static/js/integrations.js:243` | Change `switchTab('personal')` → `switchPage('assistant')` |
| `static/js/onboarding.js:131` | Change `switchTab('personal')` → `switchPage('assistant')` |
| `static/js/webhook.js` | No API changes — only rendered inside Automation page now |
| `static/js/chat.js` | No changes needed — ChatApp doesn't call switchTab |

---

## Task 1: Create sidebar CSS and layout foundation

**Files:**
- Create: `src/breadmind/web/static/css/sidebar.css`
- Modify: `src/breadmind/web/static/index.html:7-9` (body style), `index.html:425-426` (CSS links)

This task creates the CSS for the entire new layout system. No JS or HTML structure changes yet — just the stylesheet.

- [ ] **Step 1: Create `sidebar.css`**

Create the file at `src/breadmind/web/static/css/sidebar.css` with the complete sidebar layout CSS:

```css
/* =============================================================================
   BreadMind App Sidebar & Page Layout
   ============================================================================= */

/* --- Layout Variables --- */
:root {
    --sidebar-width: 220px;
    --sidebar-width-collapsed: 56px;
    --sidebar-bg: rgba(12, 15, 28, 0.97);
    --sidebar-border: rgba(255, 255, 255, 0.06);
    --sidebar-item-height: 36px;
    --sidebar-item-radius: 8px;
    --sidebar-icon-size: 18px;
    --page-header-height: 0px;
}

/* --- App Layout (row: sidebar + main) --- */
.app-layout {
    display: flex;
    flex-direction: row;
    height: 100vh;
    height: 100dvh;
    overflow: hidden;
    position: relative;
    z-index: 1;
}

/* --- Sidebar --- */
.app-sidebar {
    width: var(--sidebar-width);
    min-width: var(--sidebar-width);
    background: var(--sidebar-bg);
    border-right: 1px solid var(--sidebar-border);
    display: flex;
    flex-direction: column;
    flex-shrink: 0;
    transition: width 0.25s cubic-bezier(0.4, 0, 0.2, 1),
                min-width 0.25s cubic-bezier(0.4, 0, 0.2, 1);
    overflow: hidden;
    z-index: 20;
}

.app-sidebar.collapsed {
    width: var(--sidebar-width-collapsed);
    min-width: var(--sidebar-width-collapsed);
}

/* Sidebar header */
.sidebar-header {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 14px 16px;
    border-bottom: 1px solid var(--sidebar-border);
    flex-shrink: 0;
    min-height: 52px;
}

.sidebar-logo {
    font-size: 22px;
    flex-shrink: 0;
    width: 24px;
    text-align: center;
}

.sidebar-brand {
    font-size: 16px;
    font-weight: 700;
    letter-spacing: -0.03em;
    background: var(--accent-gradient);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    background-clip: text;
    white-space: nowrap;
    overflow: hidden;
}

.app-sidebar.collapsed .sidebar-brand { display: none; }

.sidebar-toggle {
    margin-left: auto;
    background: none;
    border: none;
    color: var(--text-tertiary);
    cursor: pointer;
    font-size: 14px;
    padding: 4px;
    border-radius: 4px;
    transition: var(--transition);
    flex-shrink: 0;
}

.sidebar-toggle:hover {
    color: var(--text-primary);
    background: rgba(255, 255, 255, 0.06);
}

.app-sidebar.collapsed .sidebar-toggle {
    margin-left: 0;
    transform: rotate(180deg);
}

/* Sidebar navigation */
.sidebar-nav {
    flex: 1;
    overflow-y: auto;
    overflow-x: hidden;
    padding: 8px;
}

.sidebar-group {
    margin-bottom: 4px;
}

.sidebar-group-label {
    font-size: 10px;
    font-weight: 600;
    color: var(--text-tertiary);
    text-transform: uppercase;
    letter-spacing: 0.08em;
    padding: 8px 8px 4px;
    white-space: nowrap;
    overflow: hidden;
}

.app-sidebar.collapsed .sidebar-group-label {
    font-size: 0;
    padding: 4px 0;
    border-bottom: 1px solid var(--sidebar-border);
    margin: 0 8px;
}

.sidebar-item {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 0 10px;
    height: var(--sidebar-item-height);
    border-radius: var(--sidebar-item-radius);
    color: var(--text-secondary);
    font-size: 13px;
    font-weight: 500;
    cursor: pointer;
    transition: var(--transition);
    text-decoration: none;
    white-space: nowrap;
    overflow: hidden;
    position: relative;
}

.sidebar-item:hover {
    background: rgba(255, 255, 255, 0.06);
    color: var(--text-primary);
}

.sidebar-item.active {
    background: rgba(99, 102, 241, 0.12);
    color: #a5b4fc;
}

.sidebar-item.active::before {
    content: '';
    position: absolute;
    left: 0;
    top: 6px;
    bottom: 6px;
    width: 3px;
    border-radius: 0 3px 3px 0;
    background: var(--accent);
}

.sidebar-icon {
    width: 20px;
    text-align: center;
    font-size: var(--sidebar-icon-size);
    flex-shrink: 0;
}

.sidebar-label {
    overflow: hidden;
    text-overflow: ellipsis;
}

.app-sidebar.collapsed .sidebar-label { display: none; }

.sidebar-badge {
    margin-left: auto;
    background: rgba(248, 113, 113, 0.15);
    color: var(--error);
    font-size: 10px;
    font-weight: 600;
    padding: 1px 6px;
    border-radius: 8px;
    min-width: 18px;
    text-align: center;
}

.app-sidebar.collapsed .sidebar-badge { display: none; }

/* Sidebar divider */
.sidebar-divider {
    height: 1px;
    background: var(--sidebar-border);
    margin: 6px 8px;
}

/* Sidebar footer */
.sidebar-footer {
    flex-shrink: 0;
    padding: 0 8px 8px;
}

.sidebar-version {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 6px 10px;
    font-size: 11px;
    color: var(--text-tertiary);
}

.app-sidebar.collapsed .sidebar-version .sidebar-label { display: none; }

/* Sidebar tooltip for collapsed mode */
.app-sidebar.collapsed .sidebar-item {
    justify-content: center;
    padding: 0;
}

.app-sidebar.collapsed .sidebar-item[data-tooltip]:hover::after {
    content: attr(data-tooltip);
    position: absolute;
    left: calc(var(--sidebar-width-collapsed) + 6px);
    top: 50%;
    transform: translateY(-50%);
    background: #1e293b;
    color: var(--text-primary);
    padding: 4px 10px;
    border-radius: 6px;
    font-size: 12px;
    white-space: nowrap;
    box-shadow: 0 4px 12px rgba(0, 0, 0, 0.4);
    z-index: 100;
    pointer-events: none;
}

/* --- App Main (right side) --- */
.app-main {
    flex: 1;
    display: flex;
    flex-direction: column;
    overflow: hidden;
    min-width: 0;
}

/* --- Pages (replace tab-content) --- */
.page {
    display: none;
    flex: 1;
    overflow: hidden;
    min-height: 0;
}

.page.active {
    display: flex;
}

/* --- Page Tabs (sub-navigation inside pages) --- */
.page-tabs {
    display: flex;
    gap: 2px;
    padding: 8px 16px;
    background: rgba(30, 41, 59, 0.8);
    border-bottom: 1px solid rgba(255, 255, 255, 0.06);
    flex-shrink: 0;
    overflow-x: auto;
}

.page-tab {
    padding: 6px 14px;
    border: none;
    background: transparent;
    color: var(--text-secondary);
    font-size: 13px;
    font-weight: 500;
    cursor: pointer;
    border-radius: 6px;
    transition: var(--transition);
    white-space: nowrap;
}

.page-tab:hover {
    color: var(--text-primary);
    background: rgba(255, 255, 255, 0.05);
}

.page-tab.active {
    color: #a5b4fc;
    background: rgba(99, 102, 241, 0.12);
}

.page-panel {
    flex: 1;
    overflow-y: auto;
    padding: 16px;
}

/* --- Responsive --- */
@media (max-width: 1200px) {
    .app-sidebar {
        width: var(--sidebar-width-collapsed);
        min-width: var(--sidebar-width-collapsed);
    }
    .app-sidebar .sidebar-brand,
    .app-sidebar .sidebar-label,
    .app-sidebar .sidebar-badge,
    .app-sidebar .sidebar-version .sidebar-label { display: none; }
    .app-sidebar .sidebar-item { justify-content: center; padding: 0; }
    .app-sidebar .sidebar-group-label { font-size: 0; padding: 4px 0; border-bottom: 1px solid var(--sidebar-border); margin: 0 8px; }
    .app-sidebar .sidebar-toggle { transform: rotate(180deg); margin-left: 0; }
}

@media (max-width: 768px) {
    .app-sidebar {
        position: fixed;
        top: 0;
        left: 0;
        bottom: 0;
        width: var(--sidebar-width);
        min-width: var(--sidebar-width);
        transform: translateX(-100%);
        z-index: 100;
        box-shadow: 4px 0 24px rgba(0, 0, 0, 0.5);
    }
    .app-sidebar .sidebar-brand,
    .app-sidebar .sidebar-label,
    .app-sidebar .sidebar-badge { display: initial; }
    .app-sidebar .sidebar-item { justify-content: flex-start; padding: 0 10px; }
    .app-sidebar .sidebar-group-label { font-size: 10px; }
    .app-sidebar .sidebar-toggle { transform: none; margin-left: auto; }

    .app-sidebar.mobile-open {
        transform: translateX(0);
    }

    .mobile-overlay {
        display: none;
        position: fixed;
        top: 0; left: 0; right: 0; bottom: 0;
        background: rgba(0, 0, 0, 0.5);
        z-index: 99;
    }

    .mobile-overlay.visible { display: block; }

    .mobile-menu-btn {
        display: flex !important;
    }
}

.mobile-menu-btn {
    display: none;
    background: none;
    border: none;
    color: var(--text-secondary);
    font-size: 20px;
    cursor: pointer;
    padding: 4px 8px;
}
```

- [ ] **Step 2: Add CSS link to index.html**

In `index.html`, after the line `<link rel="stylesheet" href="/static/css/webhook.css">` (line ~426), add:

```html
    <link rel="stylesheet" href="/static/css/sidebar.css">
```

- [ ] **Step 3: Commit**

```bash
git add src/breadmind/web/static/css/sidebar.css
git add src/breadmind/web/static/index.html
git commit -m "feat(web): add sidebar CSS and layout foundation"
```

---

## Task 2: Create sidebar.js with page switching logic

**Files:**
- Create: `src/breadmind/web/static/js/sidebar.js`
- Modify: `src/breadmind/web/static/index.html` (add script tag)

This creates the core `switchPage()` function and sidebar toggle behavior. It does NOT yet modify the HTML layout — it just defines the functions.

- [ ] **Step 1: Create `sidebar.js`**

Create `src/breadmind/web/static/js/sidebar.js`:

```javascript
/**
 * BreadMind Sidebar Navigation
 *
 * Manages sidebar collapse/expand, page switching, hash routing,
 * and mobile responsive behavior.
 */
(function() {
    'use strict';

    const PAGE_INIT = {
        chat: function() { if (typeof loadSidebarAssistant === 'function') loadSidebarAssistant(); },
        assistant: function() { if (typeof initPersonalTab === 'function') initPersonalTab(); },
        automation: function() { if (typeof initAutomationPage === 'function') initAutomationPage(); },
        monitoring: function() { if (typeof initMonitoringPage === 'function') initMonitoringPage(); },
        explore: function() { if (typeof initExplorePage === 'function') initExplorePage(); },
        connections: function() { if (typeof initConnectionsPage === 'function') initConnectionsPage(); },
        settings: function() { if (typeof loadSettings === 'function') loadSettings(); },
    };

    // Current page
    let _currentPage = 'chat';

    /**
     * Switch to a named page.
     * Replaces the old switchTab() function.
     */
    window.switchPage = function(name) {
        _currentPage = name;

        // Update sidebar active state
        document.querySelectorAll('.sidebar-item[data-page]').forEach(item => {
            item.classList.toggle('active', item.dataset.page === name);
        });

        // Toggle page visibility
        document.querySelectorAll('.page').forEach(p => {
            p.classList.remove('active');
            p.style.display = 'none';
        });
        const page = document.getElementById('page-' + name);
        if (page) {
            page.classList.add('active');
            page.style.display = 'flex';
        }

        // Update URL hash
        location.hash = name;

        // Run page initializer
        if (PAGE_INIT[name]) PAGE_INIT[name]();

        // Close mobile sidebar if open
        closeMobileSidebar();
    };

    /**
     * Keep switchTab as backwards-compatible alias.
     * Maps old tab names to new page names.
     */
    window.switchTab = function(name) {
        const mapping = {
            chat: 'chat',
            monitoring: 'monitoring',
            store: 'explore',
            skills: 'explore',
            plugins: 'explore',
            personal: 'assistant',
            settings: 'settings',
        };
        switchPage(mapping[name] || name);
    };

    /**
     * Toggle sidebar collapsed/expanded.
     */
    window.toggleSidebar = function() {
        const sidebar = document.getElementById('app-sidebar');
        if (!sidebar) return;
        const collapsed = sidebar.classList.toggle('collapsed');
        localStorage.setItem('breadmind_sidebar', collapsed ? 'collapsed' : 'expanded');
    };

    /**
     * Mobile sidebar helpers.
     */
    window.openMobileSidebar = function() {
        const sidebar = document.getElementById('app-sidebar');
        const overlay = document.getElementById('mobile-overlay');
        if (sidebar) sidebar.classList.add('mobile-open');
        if (overlay) overlay.classList.add('visible');
    };

    function closeMobileSidebar() {
        const sidebar = document.getElementById('app-sidebar');
        const overlay = document.getElementById('mobile-overlay');
        if (sidebar) sidebar.classList.remove('mobile-open');
        if (overlay) overlay.classList.remove('visible');
    }
    window.closeMobileSidebar = closeMobileSidebar;

    /**
     * Page-level sub-tab switching (used by Automation, Monitoring, Connections, Settings, Explore).
     */
    window.switchPageTab = function(pageId, tabName) {
        const page = document.getElementById('page-' + pageId);
        if (!page) return;
        page.querySelectorAll('.page-tab').forEach(t => {
            t.classList.toggle('active', t.dataset.subtab === tabName);
        });
        page.querySelectorAll('.page-panel').forEach(p => {
            p.style.display = p.id === ('subtab-' + pageId + '-' + tabName) ? '' : 'none';
        });
        localStorage.setItem('breadmind_ptab_' + pageId, tabName);
    };

    /**
     * Initialize: restore sidebar state, restore page from hash.
     */
    window.initSidebar = function() {
        // Restore sidebar collapsed state
        const savedState = localStorage.getItem('breadmind_sidebar');
        if (savedState === 'collapsed') {
            const sidebar = document.getElementById('app-sidebar');
            if (sidebar) sidebar.classList.add('collapsed');
        }

        // Bind sidebar item clicks
        document.querySelectorAll('.sidebar-item[data-page]').forEach(item => {
            item.addEventListener('click', function() {
                switchPage(this.dataset.page);
            });
        });

        // Restore page from hash
        const hash = location.hash.replace('#', '');
        const validPages = ['chat', 'assistant', 'automation', 'monitoring', 'explore', 'connections', 'settings'];
        // Map old hashes
        const hashMap = { store: 'explore', skills: 'explore', plugins: 'explore', personal: 'assistant' };
        const resolved = hashMap[hash] || hash;
        if (resolved && validPages.includes(resolved)) {
            switchPage(resolved);
        } else {
            switchPage('chat');
        }
    };

})();
```

- [ ] **Step 2: Add script tag to index.html**

In `index.html`, add the sidebar.js script BEFORE toast.js (around line 3379) so it loads early:

```html
    <script src="/static/js/sidebar.js"></script>
    <script src="/static/js/toast.js"></script>
```

- [ ] **Step 3: Commit**

```bash
git add src/breadmind/web/static/js/sidebar.js
git add src/breadmind/web/static/index.html
git commit -m "feat(web): add sidebar.js with page switching and routing"
```

---

## Task 3: Restructure index.html layout (sidebar + pages)

**Files:**
- Modify: `src/breadmind/web/static/index.html`

This is the core structural change. Replace the top-tab layout with sidebar + page layout. All existing tab content moves into `<div class="page">` wrappers.

- [ ] **Step 1: Replace body flex direction**

In `index.html` line 9, change:

```
body { ... display: flex; flex-direction: column; overflow: hidden; ... }
```

to have `flex-direction: row` removed (we'll use `.app-layout` instead). The body itself just needs basic reset. The actual layout is in `.app-layout`.

Replace the body style in line 9 from:
```css
body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #0f172a; color: #e2e8f0; height: 100vh; height: 100dvh; display: flex; flex-direction: column; overflow: hidden; margin: 0; }
```
to:
```css
body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #0f172a; color: #e2e8f0; height: 100vh; height: 100dvh; overflow: hidden; margin: 0; }
```

- [ ] **Step 2: Replace header + tabs + main with app-layout structure**

Find the block from `<div class="tabs">` (line 500) through `<div class="main">` (line 509) and replace the entire outer structure. The content inside each tab-content remains the same — only the wrappers change.

Remove the `<div class="tabs">...</div>` block (lines 500-508).

Wrap everything from the old `<div class="main">` in a new layout:

```html
    <!-- Mobile overlay -->
    <div class="mobile-overlay" id="mobile-overlay" onclick="closeMobileSidebar()"></div>

    <div class="app-layout">
    <!-- Sidebar -->
    <nav class="app-sidebar" id="app-sidebar">
        <div class="sidebar-header">
            <span class="sidebar-logo">🍞</span>
            <span class="sidebar-brand">BreadMind</span>
            <button class="sidebar-toggle" onclick="toggleSidebar()" title="Toggle sidebar">◀</button>
        </div>
        <div class="sidebar-nav">
            <div class="sidebar-group">
                <div class="sidebar-group-label">Main</div>
                <a class="sidebar-item active" data-page="chat" data-tooltip="Chat">
                    <span class="sidebar-icon">💬</span><span class="sidebar-label">Chat</span>
                </a>
                <a class="sidebar-item" data-page="assistant" data-tooltip="Assistant">
                    <span class="sidebar-icon">📋</span><span class="sidebar-label">Assistant</span>
                </a>
                <a class="sidebar-item" data-page="automation" data-tooltip="Automation">
                    <span class="sidebar-icon">⚡</span><span class="sidebar-label">Automation</span>
                </a>
                <a class="sidebar-item" data-page="monitoring" data-tooltip="Monitoring">
                    <span class="sidebar-icon">📊</span><span class="sidebar-label">Monitoring</span>
                    <span class="sidebar-badge" id="sidebar-event-count" style="display:none"></span>
                </a>
                <a class="sidebar-item" data-page="explore" data-tooltip="Explore">
                    <span class="sidebar-icon">🏪</span><span class="sidebar-label">Explore</span>
                </a>
                <a class="sidebar-item" data-page="connections" data-tooltip="Connections">
                    <span class="sidebar-icon">🔌</span><span class="sidebar-label">Connections</span>
                </a>
            </div>
            <div class="sidebar-divider"></div>
            <div class="sidebar-group">
                <div class="sidebar-group-label">System</div>
                <a class="sidebar-item" data-page="settings" data-tooltip="Settings">
                    <span class="sidebar-icon">⚙️</span><span class="sidebar-label">Settings</span>
                </a>
            </div>
        </div>
        <div class="sidebar-footer">
            <div class="sidebar-divider"></div>
            <div class="sidebar-version">
                <span class="sidebar-label" id="sidebar-version-text">v0.0.0</span>
            </div>
        </div>
    </nav>

    <!-- Main content -->
    <div class="app-main">
    <div class="main">
```

The closing `</div>` tags for `app-main` and `app-layout` go at the very end, after the existing `</div>` that closes `.main` (around line 680).

- [ ] **Step 3: Rename tab-content divs to page divs**

Replace all `class="tab-content"` and `id="tab-..."` with new page naming:

| Old | New |
|-----|-----|
| `<div class="tab-content active" id="tab-chat">` | `<div class="page active" id="page-chat">` |
| `<div class="tab-content" id="tab-monitoring">` | `<div class="page" id="page-monitoring">` |
| `<div class="tab-content" id="tab-store">` | `<div class="page" id="page-explore" style="flex-direction:column;">` |
| `<div class="tab-content" id="tab-skills">` | Remove — merged into explore |
| `<div class="tab-content" id="tab-plugins"...>` | Remove — merged into explore |
| `<div class="tab-content" id="tab-personal"...>` | `<div class="page" id="page-assistant" style="flex-direction:column;">` |
| `<div class="tab-content" id="tab-settings">` | `<div class="page" id="page-settings">` |

**New pages to add** (empty containers for now, content in later tasks):

```html
        <!-- Automation Page -->
        <div class="page" id="page-automation" style="display:none;flex-direction:column;">
            <div id="automation-content"></div>
        </div>

        <!-- Connections Page -->
        <div class="page" id="page-connections" style="display:none;flex-direction:column;">
            <div id="connections-content"></div>
        </div>
```

- [ ] **Step 4: Move header inside app-main, add mobile menu button**

Move the existing `<header>` element to be the first child of `.app-main` (before `.main`). Add a mobile menu button:

```html
    <div class="app-main">
        <header>
            <button class="mobile-menu-btn" onclick="openMobileSidebar()">☰</button>
            <h1>🍞 BreadMind</h1>
            <span class="badge" id="header-version">v0.1.1</span>
            <div style="flex:1"></div>
            <div class="status">
                <span class="dot" id="statusDot"></span>
                <span id="statusText">Connecting...</span>
            </div>
        </header>
```

- [ ] **Step 5: Rename chat internal sidebar class**

The chat tab has `<div class="sidebar">` (line 513) which conflicts with the app sidebar. Rename it:

Replace `<div class="sidebar">` (inside page-chat) with `<div class="chat-sidebar">`.

In the inline `<style>` block (line 33-34), change:
```css
.sidebar { width: 260px; background: #1e293b; border-right: 1px solid #334155; padding: 16px; overflow-y: auto; flex-shrink: 0; }
```
to:
```css
.chat-sidebar { width: 260px; background: #1e293b; border-right: 1px solid #334155; padding: 16px; overflow-y: auto; flex-shrink: 0; }
```

Also update `glass-theme.css` if it references `.sidebar` for the chat sidebar (check first).

- [ ] **Step 6: Update the initialization script at the bottom**

In the inline `<script>` near the end of index.html (around line 3370-3374), replace:

```javascript
        // Restore tab from URL hash
        const hashTab = location.hash.replace('#', '');
        if (hashTab && ['chat','monitoring','store','skills','personal','settings'].includes(hashTab)) {
            switchTab(hashTab);
        }
```

with:

```javascript
        // Initialize sidebar navigation
        if (typeof initSidebar === 'function') initSidebar();
```

- [ ] **Step 7: Remove the old switchTab function body (but keep as alias)**

The old `switchTab` function (lines 696-710) is now replaced by `sidebar.js`. Remove the function body from index.html:

```javascript
        // switchTab is now provided by sidebar.js as an alias for switchPage
```

The `switchTab` alias defined in `sidebar.js` will handle backwards compatibility.

- [ ] **Step 8: Verify in browser**

Open `http://localhost:8080` and verify:
- Sidebar appears on the left
- Clicking sidebar items switches pages
- Chat page displays with its internal sidebar
- Settings page loads
- URL hash updates on page switch
- Sidebar collapse/expand works

- [ ] **Step 9: Commit**

```bash
git add src/breadmind/web/static/index.html
git commit -m "feat(web): restructure layout from top tabs to sidebar navigation"
```

---

## Task 4: Merge 3 stores into Explore page

**Files:**
- Modify: `src/breadmind/web/static/index.html`

The MCP Store, Skill Store, and Plugin Store content gets merged into a single Explore page with sub-tabs.

- [ ] **Step 1: Create Explore page with sub-tabs**

Replace the three separate store page divs with a single Explore page that contains sub-tabs:

```html
        <!-- Explore Page (MCP + Skills + Plugins) -->
        <div class="page" id="page-explore" style="display:none;flex-direction:column;">
            <div class="page-tabs">
                <button class="page-tab active" data-subtab="mcp" onclick="switchPageTab('explore','mcp')">MCP Servers</button>
                <button class="page-tab" data-subtab="skills" onclick="switchPageTab('explore','skills')">Skills</button>
                <button class="page-tab" data-subtab="plugins" onclick="switchPageTab('explore','plugins')">Plugins</button>
            </div>
            <!-- MCP panel — contains the old tab-store content -->
            <div class="page-panel" id="subtab-explore-mcp">
                <!-- Paste the INNER content of old #tab-store here (store-search, store-content, etc.) -->
            </div>
            <!-- Skills panel — contains the old tab-skills content -->
            <div class="page-panel" id="subtab-explore-skills" style="display:none">
                <!-- Paste the INNER content of old #tab-skills here -->
            </div>
            <!-- Plugins panel — contains the old tab-plugins content -->
            <div class="page-panel" id="subtab-explore-plugins" style="display:none">
                <!-- Paste the INNER content of old #tab-plugins here -->
            </div>
        </div>
```

Move the inner HTML of each old store tab into its corresponding panel. Do not change the inner structure — just re-parent it.

- [ ] **Step 2: Update the Explore page initializer**

Add `initExplorePage` function in the inline script section of index.html:

```javascript
        function initExplorePage() {
            const saved = localStorage.getItem('breadmind_ptab_explore') || 'mcp';
            switchPageTab('explore', saved);
            if (saved === 'mcp') { loadFeatured(); loadInstalledServers(); }
            else if (saved === 'skills') { loadSkillsFeatured(); }
            else if (saved === 'plugins') { loadPluginsFeatured(); loadPluginsInstalled(); }
        }
```

- [ ] **Step 3: Update sub-tab switch to load data on demand**

Override `switchPageTab` for explore to trigger data loading:

```javascript
        const _origSwitchPageTab = window.switchPageTab;
        window.switchPageTab = function(pageId, tabName) {
            _origSwitchPageTab(pageId, tabName);
            if (pageId === 'explore') {
                if (tabName === 'mcp') { loadFeatured(); loadInstalledServers(); }
                else if (tabName === 'skills') { loadSkillsFeatured(); }
                else if (tabName === 'plugins') { loadPluginsFeatured(); loadPluginsInstalled(); }
            }
        };
```

- [ ] **Step 4: Verify**

Open Explore page → switch between MCP / Skills / Plugins tabs. All three should render correctly.

- [ ] **Step 5: Commit**

```bash
git add src/breadmind/web/static/index.html
git commit -m "feat(web): merge MCP/Skill/Plugin stores into unified Explore page"
```

---

## Task 5: Create Automation page

**Files:**
- Create: `src/breadmind/web/static/js/automation.js`
- Modify: `src/breadmind/web/static/index.html`

Automation page aggregates: Webhooks, Scheduler, Swarm, Jobs, Containers. Webhooks uses the existing `webhook.js`. The other sections extract their HTML from the old Settings > Agents sub-tab.

- [ ] **Step 1: Create `automation.js`**

Create `src/breadmind/web/static/js/automation.js`:

```javascript
/**
 * BreadMind Automation Page
 *
 * Aggregates Webhook automation, Scheduler, Swarm, Jobs, and Containers
 * into a single page with sub-tabs.
 */
(function() {
    'use strict';

    window.initAutomationPage = function() {
        const container = document.getElementById('automation-content');
        if (!container) return;

        const saved = localStorage.getItem('breadmind_ptab_automation') || 'webhooks';

        container.innerHTML = `
            <div class="page-tabs">
                <button class="page-tab ${saved === 'webhooks' ? 'active' : ''}" data-subtab="webhooks" onclick="switchPageTab('automation','webhooks')">Webhooks</button>
                <button class="page-tab ${saved === 'scheduler' ? 'active' : ''}" data-subtab="scheduler" onclick="switchPageTab('automation','scheduler')">Scheduler</button>
                <button class="page-tab ${saved === 'swarm' ? 'active' : ''}" data-subtab="swarm" onclick="switchPageTab('automation','swarm')">Swarm</button>
                <button class="page-tab ${saved === 'jobs' ? 'active' : ''}" data-subtab="jobs" onclick="switchPageTab('automation','jobs')">Jobs</button>
                <button class="page-tab ${saved === 'containers' ? 'active' : ''}" data-subtab="containers" onclick="switchPageTab('automation','containers')">Containers</button>
            </div>
            <div class="page-panel" id="subtab-automation-webhooks" ${saved !== 'webhooks' ? 'style="display:none"' : ''}>
                <div id="webhook-content"></div>
            </div>
            <div class="page-panel" id="subtab-automation-scheduler" ${saved !== 'scheduler' ? 'style="display:none"' : ''}>
                <div id="scheduler-content"></div>
            </div>
            <div class="page-panel" id="subtab-automation-swarm" ${saved !== 'swarm' ? 'style="display:none"' : ''}>
                <div id="swarm-content"></div>
            </div>
            <div class="page-panel" id="subtab-automation-jobs" ${saved !== 'jobs' ? 'style="display:none"' : ''}>
                <div id="jobs-content"></div>
            </div>
            <div class="page-panel" id="subtab-automation-containers" ${saved !== 'containers' ? 'style="display:none"' : ''}>
                <div id="containers-content"></div>
            </div>
        `;

        // Initialize the active tab
        loadAutomationTab(saved);
    };

    function loadAutomationTab(tab) {
        if (tab === 'webhooks') {
            if (typeof initWebhookTab === 'function') initWebhookTab();
        } else if (tab === 'scheduler') {
            renderScheduler();
        } else if (tab === 'swarm') {
            renderSwarm();
        } else if (tab === 'jobs') {
            renderJobs();
        } else if (tab === 'containers') {
            renderContainers();
        }
    }

    // Hook into switchPageTab for automation
    const _origSwitch = window.switchPageTab;
    window.switchPageTab = function(pageId, tabName) {
        _origSwitch(pageId, tabName);
        if (pageId === 'automation') loadAutomationTab(tabName);
    };

    // ── Scheduler ─────────────────────────────────────────────────────

    function renderScheduler() {
        const c = document.getElementById('scheduler-content');
        if (!c) return;
        c.innerHTML = '<div style="color:var(--text-tertiary);padding:20px;">Loading scheduler...</div>';

        Promise.all([
            fetch('/api/scheduler/cron').then(r => r.json()).catch(() => ({jobs:[]})),
            fetch('/api/scheduler/heartbeat').then(r => r.json()).catch(() => ({tasks:[]})),
        ]).then(([cronData, hbData]) => {
            let html = '<h3 style="margin-bottom:12px;">Cron Jobs</h3>';
            html += '<div id="auto-cron-list">';
            const jobs = cronData.jobs || [];
            if (jobs.length === 0) {
                html += '<div style="color:var(--text-tertiary);font-size:13px;">No cron jobs.</div>';
            } else {
                jobs.forEach(j => {
                    html += `<div class="wh-card" style="margin-bottom:6px;"><div class="wh-card-header"><div class="wh-card-title">${esc(j.name || j.id)}</div><div class="wh-card-actions"><button class="wh-card-btn danger" onclick="deleteAutoCron('${j.id}')">Delete</button></div></div><div class="wh-card-meta"><span>Schedule: <code>${esc(j.schedule)}</code></span><span>Task: ${esc(j.task || j.message || '')}</span></div></div>`;
                });
            }
            html += '</div>';
            html += `<div style="display:flex;gap:8px;margin-top:10px;flex-wrap:wrap;">
                <input type="text" class="wh-input" id="auto-cron-name" placeholder="Job name" style="width:120px;" />
                <input type="text" class="wh-input" id="auto-cron-schedule" placeholder="0 9 * * 1" style="width:140px;" />
                <input type="text" class="wh-input" id="auto-cron-task" placeholder="Message to agent" style="flex:1;" />
                <button class="wh-btn wh-btn-primary" onclick="addAutoCron()">Add</button>
            </div>`;

            html += '<h3 style="margin:20px 0 12px;">Heartbeats</h3>';
            html += '<div id="auto-hb-list">';
            const hbs = hbData.tasks || [];
            if (hbs.length === 0) {
                html += '<div style="color:var(--text-tertiary);font-size:13px;">No heartbeat tasks.</div>';
            } else {
                hbs.forEach(h => {
                    html += `<div class="wh-card" style="margin-bottom:6px;"><div class="wh-card-header"><div class="wh-card-title">${esc(h.name || h.id)}</div><div class="wh-card-actions"><button class="wh-card-btn danger" onclick="deleteAutoHb('${h.id}')">Delete</button></div></div><div class="wh-card-meta"><span>Interval: ${h.interval_minutes || h.interval || '?'} min</span><span>Task: ${esc(h.task || h.message || '')}</span></div></div>`;
                });
            }
            html += '</div>';
            html += `<div style="display:flex;gap:8px;margin-top:10px;flex-wrap:wrap;">
                <input type="text" class="wh-input" id="auto-hb-name" placeholder="Name" style="width:120px;" />
                <input type="number" class="wh-input" id="auto-hb-interval" placeholder="30" style="width:80px;" min="1" />
                <span style="color:var(--text-tertiary);font-size:12px;line-height:36px;">min</span>
                <input type="text" class="wh-input" id="auto-hb-task" placeholder="Message to agent" style="flex:1;" />
                <button class="wh-btn wh-btn-primary" onclick="addAutoHb()">Add</button>
            </div>`;

            c.innerHTML = html;
        });
    }

    window.addAutoCron = async function() {
        const name = document.getElementById('auto-cron-name').value.trim();
        const schedule = document.getElementById('auto-cron-schedule').value.trim();
        const task = document.getElementById('auto-cron-task').value.trim();
        if (!name || !schedule || !task) { showToast('Fill all fields', 'warning'); return; }
        try {
            await fetch('/api/scheduler/cron', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({name, schedule, task}) });
            showToast('Cron job added', 'success');
            renderScheduler();
        } catch(e) { showToast(e.message, 'error'); }
    };

    window.deleteAutoCron = async function(id) {
        if (!confirm('Delete this cron job?')) return;
        await fetch('/api/scheduler/cron/' + id, { method: 'DELETE' });
        showToast('Deleted', 'success');
        renderScheduler();
    };

    window.addAutoHb = async function() {
        const name = document.getElementById('auto-hb-name').value.trim();
        const interval = parseInt(document.getElementById('auto-hb-interval').value, 10);
        const task = document.getElementById('auto-hb-task').value.trim();
        if (!name || !interval || !task) { showToast('Fill all fields', 'warning'); return; }
        try {
            await fetch('/api/scheduler/heartbeat', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({name, interval_minutes: interval, task}) });
            showToast('Heartbeat added', 'success');
            renderScheduler();
        } catch(e) { showToast(e.message, 'error'); }
    };

    window.deleteAutoHb = async function(id) {
        if (!confirm('Delete this heartbeat?')) return;
        await fetch('/api/scheduler/heartbeat/' + id, { method: 'DELETE' });
        showToast('Deleted', 'success');
        renderScheduler();
    };

    // ── Swarm ─────────────────────────────────────────────────────────

    function renderSwarm() {
        const c = document.getElementById('swarm-content');
        if (!c) return;
        c.innerHTML = '<div style="color:var(--text-tertiary);padding:20px;">Loading swarm...</div>';

        Promise.all([
            fetch('/api/swarm/status').then(r => r.json()).catch(() => ({})),
            fetch('/api/swarm/list').then(r => r.json()).catch(() => ({swarms:[]})),
            fetch('/api/orchestrator/status').then(r => r.json()).catch(() => ({available:false})),
        ]).then(([status, list, orch]) => {
            let html = '';
            html += `<div style="display:flex;gap:12px;margin-bottom:16px;">
                <div class="wh-card" style="flex:1;"><div class="wh-card-meta"><span>Orchestrator: <strong>${orch.available ? 'Available' : 'Unavailable'}</strong></span></div></div>
                <div class="wh-card" style="flex:1;"><div class="wh-card-meta"><span>Active Swarms: <strong>${status.active || 0}</strong></span></div></div>
            </div>`;

            html += '<h3 style="margin-bottom:12px;">Launch Swarm</h3>';
            html += `<div style="display:flex;gap:8px;margin-bottom:16px;">
                <input type="text" class="wh-input" id="auto-swarm-goal" placeholder="Goal for the swarm team..." style="flex:1;" />
                <button class="wh-btn wh-btn-primary" onclick="launchAutoSwarm()">Launch</button>
            </div>`;

            html += '<h3 style="margin-bottom:12px;">Sub-agent</h3>';
            html += `<div style="display:flex;gap:8px;margin-bottom:16px;">
                <input type="text" class="wh-input" id="auto-subagent-task" placeholder="Task to delegate..." style="flex:1;" />
                <button class="wh-btn wh-btn-primary" onclick="spawnAutoSubagent()">Spawn</button>
            </div>`;

            const swarms = list.swarms || [];
            if (swarms.length > 0) {
                html += '<h3 style="margin-bottom:12px;">Swarm History</h3>';
                swarms.forEach(s => {
                    html += `<div class="wh-card" style="margin-bottom:6px;"><div class="wh-card-header"><div class="wh-card-title">${esc(s.goal || s.id)}</div></div><div class="wh-card-meta"><span>Status: ${s.status || 'unknown'}</span><span>Roles: ${(s.roles || []).join(', ')}</span></div></div>`;
                });
            }
            c.innerHTML = html;
        });
    }

    window.launchAutoSwarm = async function() {
        const goal = document.getElementById('auto-swarm-goal').value.trim();
        if (!goal) { showToast('Enter a goal', 'warning'); return; }
        try {
            await fetch('/api/swarm/spawn', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({goal}) });
            showToast('Swarm launched', 'success');
            renderSwarm();
        } catch(e) { showToast(e.message, 'error'); }
    };

    window.spawnAutoSubagent = async function() {
        const task = document.getElementById('auto-subagent-task').value.trim();
        if (!task) { showToast('Enter a task', 'warning'); return; }
        try {
            await fetch('/api/subagent/spawn', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({task}) });
            showToast('Sub-agent spawned', 'success');
        } catch(e) { showToast(e.message, 'error'); }
    };

    // ── Jobs ──────────────────────────────────────────────────────────

    function renderJobs() {
        const c = document.getElementById('jobs-content');
        if (!c) return;
        c.innerHTML = '<div style="color:var(--text-tertiary);padding:20px;">Loading jobs...</div>';

        Promise.all([
            fetch('/api/coding-jobs').then(r => r.json()).catch(() => []),
            fetch('/api/bg-jobs').then(r => r.json()).catch(() => ({jobs:[]})),
        ]).then(([codingJobs, bgData]) => {
            let html = '<h3 style="margin-bottom:12px;">Coding Jobs</h3>';
            const cjobs = Array.isArray(codingJobs) ? codingJobs : [];
            if (cjobs.length === 0) {
                html += '<div style="color:var(--text-tertiary);font-size:13px;margin-bottom:16px;">No coding jobs.</div>';
            } else {
                cjobs.slice(0, 20).forEach(j => {
                    const statusLabel = {pending:'Pending',decomposing:'Decomposing',running:'Running',completed:'Completed',failed:'Failed',cancelled:'Cancelled'}[j.status] || j.status;
                    html += `<div class="wh-card" style="margin-bottom:6px;"><div class="wh-card-header"><div class="wh-card-title">${esc(j.project?.split(/[/\\]/).pop() || j.job_id)}</div><span class="wh-badge ${j.status === 'completed' ? 'enabled' : j.status === 'failed' ? '' : 'enabled'}" style="${j.status === 'failed' ? 'background:rgba(248,113,113,0.12);color:var(--error)' : ''}">${statusLabel}</span></div><div class="wh-card-meta"><span>${j.completed_phases || 0}/${j.total_phases || 0} phases</span><span>${j.agent || ''}</span></div></div>`;
                });
            }

            html += '<h3 style="margin:20px 0 12px;">Background Jobs</h3>';
            const bjobs = bgData.jobs || [];
            if (bjobs.length === 0) {
                html += '<div style="color:var(--text-tertiary);font-size:13px;">No background jobs.</div>';
            } else {
                bjobs.slice(0, 20).forEach(j => {
                    html += `<div class="wh-card" style="margin-bottom:6px;"><div class="wh-card-header"><div class="wh-card-title">${esc(j.name || j.job_id || j.id)}</div><span class="wh-badge ${j.status === 'completed' ? 'enabled' : ''}">${j.status}</span></div><div class="wh-card-meta"><span>${j.type || ''}</span></div></div>`;
                });
            }
            c.innerHTML = html;
        });
    }

    // ── Containers ────────────────────────────────────────────────────

    function renderContainers() {
        const c = document.getElementById('containers-content');
        if (!c) return;
        c.innerHTML = '<div style="color:var(--text-tertiary);padding:20px;">Loading container status...</div>';

        fetch('/api/container/status').then(r => r.json()).catch(() => ({available:false, containers:[]})).then(data => {
            let html = `<div class="wh-card" style="margin-bottom:16px;"><div class="wh-card-meta"><span>Docker: <strong>${data.available ? 'Available' : 'Unavailable'}</strong></span><span>Running: <strong>${(data.containers || []).length}</strong></span></div></div>`;

            html += '<h3 style="margin-bottom:12px;">Run Command</h3>';
            html += `<div style="display:flex;gap:8px;margin-bottom:16px;">
                <input type="text" class="wh-input" id="auto-container-cmd" placeholder="Command to run in container..." style="flex:1;" />
                <button class="wh-btn wh-btn-primary" onclick="runAutoContainer()">Run</button>
            </div>`;
            html += '<pre id="auto-container-output" style="display:none;background:rgba(0,0,0,0.3);border:1px solid var(--glass-border);border-radius:8px;padding:12px;font-family:var(--font-mono);font-size:12px;max-height:300px;overflow-y:auto;white-space:pre-wrap;"></pre>';

            if ((data.containers || []).length > 0) {
                html += '<h3 style="margin:16px 0 12px;">Running Containers</h3>';
                data.containers.forEach(ct => {
                    html += `<div class="wh-card" style="margin-bottom:6px;"><div class="wh-card-meta"><span>${esc(ct.name || ct.id)}</span><span>${esc(ct.image || '')}</span><span>${ct.status || ''}</span></div></div>`;
                });
            }
            c.innerHTML = html;
        });
    }

    window.runAutoContainer = async function() {
        const cmd = document.getElementById('auto-container-cmd').value.trim();
        if (!cmd) return;
        const output = document.getElementById('auto-container-output');
        if (output) { output.style.display = 'block'; output.textContent = 'Running...'; }
        try {
            const resp = await fetch('/api/container/run', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({command: cmd}) });
            const data = await resp.json();
            if (output) output.textContent = data.output || data.error || JSON.stringify(data);
        } catch(e) {
            if (output) output.textContent = 'Error: ' + e.message;
        }
    };

    function esc(str) {
        if (!str) return '';
        const d = document.createElement('div');
        d.textContent = String(str);
        return d.innerHTML;
    }

})();
```

- [ ] **Step 2: Add script tag and update Automation page HTML in index.html**

Add script tag before `sidebar.js`:

```html
    <script src="/static/js/automation.js"></script>
    <script src="/static/js/sidebar.js"></script>
```

- [ ] **Step 3: Remove old Settings > Agents sections from loadSettings()**

In `index.html` `loadSettings()`, remove the `data-stab="agents"` sections for Scheduler (lines ~1328-1347), Sub-agents (~1350-1358), Swarm (~1361-1370), Container (~1373-1382), and Webhooks (~1385-1399) since these now live in the Automation page.

- [ ] **Step 4: Verify**

Open Automation page → verify Webhooks, Scheduler, Swarm, Jobs, Containers tabs all render and function.

- [ ] **Step 5: Commit**

```bash
git add src/breadmind/web/static/js/automation.js
git add src/breadmind/web/static/index.html
git commit -m "feat(web): add Automation page with Scheduler/Swarm/Jobs/Containers"
```

---

## Task 6: Create expanded Monitoring page

**Files:**
- Create: `src/breadmind/web/static/js/monitoring-page.js`
- Modify: `src/breadmind/web/static/index.html`

The Monitoring page gets sub-tabs: Events (existing), Audit Log, Usage, Tool Metrics, Approvals — all migrated from Settings > General and Settings > Safety.

- [ ] **Step 1: Create `monitoring-page.js`**

Create `src/breadmind/web/static/js/monitoring-page.js`:

```javascript
/**
 * BreadMind Monitoring Page
 *
 * Extends the monitoring page with Audit Log, Usage, Tool Metrics, Approvals
 * tabs alongside the existing Events view.
 */
(function() {
    'use strict';

    window.initMonitoringPage = function() {
        // Insert tabs above the monitoring content if not present
        const page = document.getElementById('page-monitoring');
        if (!page) return;

        let tabBar = page.querySelector('.page-tabs');
        if (!tabBar) {
            const saved = localStorage.getItem('breadmind_ptab_monitoring') || 'events';
            const monDiv = page.querySelector('.monitoring');

            // Wrap existing monitoring content
            const wrapper = document.createElement('div');
            wrapper.className = 'page-panel';
            wrapper.id = 'subtab-monitoring-events';
            if (saved !== 'events') wrapper.style.display = 'none';

            // Move all monitoring children into wrapper
            while (monDiv.firstChild) {
                wrapper.appendChild(monDiv.firstChild);
            }

            // Build tabs
            tabBar = document.createElement('div');
            tabBar.className = 'page-tabs';
            tabBar.innerHTML = `
                <button class="page-tab ${saved === 'events' ? 'active' : ''}" data-subtab="events" onclick="switchPageTab('monitoring','events')">Events</button>
                <button class="page-tab ${saved === 'audit' ? 'active' : ''}" data-subtab="audit" onclick="switchPageTab('monitoring','audit')">Audit Log</button>
                <button class="page-tab ${saved === 'usage' ? 'active' : ''}" data-subtab="usage" onclick="switchPageTab('monitoring','usage')">Usage</button>
                <button class="page-tab ${saved === 'metrics' ? 'active' : ''}" data-subtab="metrics" onclick="switchPageTab('monitoring','metrics')">Tool Metrics</button>
                <button class="page-tab ${saved === 'approvals' ? 'active' : ''}" data-subtab="approvals" onclick="switchPageTab('monitoring','approvals')">Approvals</button>
            `;

            // Create other panels
            const auditPanel = createPanel('monitoring', 'audit', saved);
            const usagePanel = createPanel('monitoring', 'usage', saved);
            const metricsPanel = createPanel('monitoring', 'metrics', saved);
            const approvalsPanel = createPanel('monitoring', 'approvals', saved);

            // Restructure: clear monDiv, add tabs + panels
            monDiv.innerHTML = '';
            monDiv.style.display = 'flex';
            monDiv.style.flexDirection = 'column';
            monDiv.style.flex = '1';
            monDiv.style.overflow = 'hidden';
            monDiv.appendChild(tabBar);
            monDiv.appendChild(wrapper);
            monDiv.appendChild(auditPanel);
            monDiv.appendChild(usagePanel);
            monDiv.appendChild(metricsPanel);
            monDiv.appendChild(approvalsPanel);

            // Load the active tab
            loadMonTab(saved);
        }

        // Always reload events
        if (typeof loadEvents === 'function') loadEvents();
    };

    function createPanel(pageId, tabName, activeTab) {
        const div = document.createElement('div');
        div.className = 'page-panel';
        div.id = 'subtab-' + pageId + '-' + tabName;
        div.style.display = activeTab === tabName ? '' : 'none';
        div.innerHTML = '<div style="color:var(--text-tertiary);padding:20px;">Loading...</div>';
        return div;
    }

    function loadMonTab(tab) {
        if (tab === 'events' && typeof loadEvents === 'function') loadEvents();
        else if (tab === 'audit') loadAudit();
        else if (tab === 'usage') loadUsage();
        else if (tab === 'metrics') loadMetrics();
        else if (tab === 'approvals') loadApprovals();
    }

    // Hook into switchPageTab
    const _orig = window.switchPageTab;
    window.switchPageTab = function(pageId, tabName) {
        _orig(pageId, tabName);
        if (pageId === 'monitoring') loadMonTab(tabName);
    };

    function esc(s) { if (!s) return ''; const d = document.createElement('div'); d.textContent = String(s); return d.innerHTML; }

    function loadAudit() {
        const c = document.getElementById('subtab-monitoring-audit');
        if (!c) return;
        fetch('/api/audit').then(r => r.json()).catch(() => ({entries:[]})).then(data => {
            const entries = data.entries || [];
            if (entries.length === 0) { c.innerHTML = '<div style="color:var(--text-tertiary);font-size:13px;padding:20px;">No audit entries.</div>'; return; }
            let html = '<div style="display:flex;flex-direction:column;gap:4px;">';
            entries.forEach(e => {
                html += `<div class="wh-card" style="padding:8px 12px;"><div class="wh-card-meta"><span>${esc(e.action || e.event || '')}</span><span>${esc(e.user || '')}</span><span style="color:var(--text-tertiary)">${e.timestamp ? new Date(e.timestamp).toLocaleString() : ''}</span></div></div>`;
            });
            html += '</div>';
            c.innerHTML = html;
        });
    }

    function loadUsage() {
        const c = document.getElementById('subtab-monitoring-usage');
        if (!c) return;
        fetch('/api/usage').then(r => r.json()).catch(() => ({usage:{}})).then(data => {
            const u = data.usage || data;
            let html = '<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;">';
            const items = [
                ['Input Tokens', u.input_tokens || u.prompt_tokens || 0],
                ['Output Tokens', u.output_tokens || u.completion_tokens || 0],
                ['Cache Tokens', u.cache_tokens || 0],
                ['Total Cost', '$' + (u.total_cost || u.cost || 0).toFixed(4)],
            ];
            items.forEach(([label, val]) => {
                html += `<div class="wh-card" style="text-align:center;padding:16px;"><div style="font-size:11px;color:var(--text-tertiary);text-transform:uppercase;margin-bottom:4px;">${label}</div><div style="font-size:20px;font-weight:600;color:var(--text-primary);">${val}</div></div>`;
            });
            html += '</div>';
            c.innerHTML = html;
        });
    }

    function loadMetrics() {
        const c = document.getElementById('subtab-monitoring-metrics');
        if (!c) return;
        fetch('/api/metrics').then(r => r.json()).catch(() => ({metrics:{}})).then(data => {
            const m = data.metrics || data;
            const tools = Object.entries(m);
            if (tools.length === 0) { c.innerHTML = '<div style="color:var(--text-tertiary);font-size:13px;padding:20px;">No tool metrics yet.</div>'; return; }
            let html = '<table style="width:100%;border-collapse:collapse;font-size:13px;">';
            html += '<thead><tr style="color:var(--text-tertiary);text-align:left;border-bottom:1px solid var(--glass-border);"><th style="padding:8px;">Tool</th><th style="padding:8px;">Calls</th><th style="padding:8px;">Success</th><th style="padding:8px;">Avg Time</th></tr></thead><tbody>';
            tools.forEach(([name, v]) => {
                const rate = v.total > 0 ? ((v.success || 0) / v.total * 100).toFixed(0) : '—';
                const color = rate >= 90 ? 'var(--success)' : rate >= 70 ? 'var(--warning)' : 'var(--error)';
                html += `<tr style="border-bottom:1px solid var(--glass-border);"><td style="padding:8px;">${esc(name)}</td><td style="padding:8px;">${v.total || 0}</td><td style="padding:8px;color:${color}">${rate}%</td><td style="padding:8px;">${(v.avg_time || 0).toFixed(2)}s</td></tr>`;
            });
            html += '</tbody></table>';
            c.innerHTML = html;
        });
    }

    function loadApprovals() {
        const c = document.getElementById('subtab-monitoring-approvals');
        if (!c) return;
        fetch('/api/approvals').then(r => r.json()).catch(() => ({approvals:[]})).then(data => {
            const items = data.approvals || [];
            if (items.length === 0) { c.innerHTML = '<div style="color:var(--text-tertiary);font-size:13px;padding:20px;">No pending approvals.</div>'; return; }
            let html = '';
            items.forEach(a => {
                html += `<div class="wh-card" style="margin-bottom:8px;border-left:3px solid var(--warning);">
                    <div class="wh-card-header"><div class="wh-card-title">${esc(a.tool || a.name)}</div></div>
                    <div style="font-size:12px;color:var(--text-tertiary);margin:4px 0;">${esc(JSON.stringify(a.args || a.arguments || {}))}</div>
                    <div style="display:flex;gap:6px;margin-top:8px;">
                        <button class="wh-btn wh-btn-primary" style="font-size:12px;padding:4px 12px;" onclick="approveMonItem('${a.id}')">Approve</button>
                        <button class="wh-btn wh-btn-secondary" style="font-size:12px;padding:4px 12px;" onclick="denyMonItem('${a.id}')">Deny</button>
                    </div>
                </div>`;
            });
            c.innerHTML = html;
        });
    }

    window.approveMonItem = async function(id) {
        await fetch('/api/approvals/' + id + '/approve', { method: 'POST' });
        showToast('Approved', 'success');
        loadApprovals();
    };

    window.denyMonItem = async function(id) {
        await fetch('/api/approvals/' + id + '/deny', { method: 'POST' });
        showToast('Denied', 'info');
        loadApprovals();
    };

})();
```

- [ ] **Step 2: Add script tag in index.html**

```html
    <script src="/static/js/monitoring-page.js"></script>
```

- [ ] **Step 3: Remove migrated sections from loadSettings()**

In `loadSettings()`, remove the `data-stab="general"` sections for:
- Token Usage
- Recent Audit Log
- Tool Metrics

And remove the `data-stab="safety"` section for:
- Pending Approvals

These now live in the Monitoring page.

- [ ] **Step 4: Verify**

Open Monitoring page → verify all 5 tabs (Events, Audit Log, Usage, Tool Metrics, Approvals).

- [ ] **Step 5: Commit**

```bash
git add src/breadmind/web/static/js/monitoring-page.js
git add src/breadmind/web/static/index.html
git commit -m "feat(web): expand Monitoring page with Audit/Usage/Metrics/Approvals tabs"
```

---

## Task 7: Create Connections page

**Files:**
- Create: `src/breadmind/web/static/js/connections.js`
- Modify: `src/breadmind/web/static/index.html`

Connections page aggregates Integrations and Messenger into sub-tabs.

- [ ] **Step 1: Create `connections.js`**

Create `src/breadmind/web/static/js/connections.js`:

```javascript
/**
 * BreadMind Connections Page
 *
 * Aggregates Integrations and Messenger into sub-tabs.
 */
(function() {
    'use strict';

    window.initConnectionsPage = function() {
        const container = document.getElementById('connections-content');
        if (!container) return;

        const saved = localStorage.getItem('breadmind_ptab_connections') || 'integrations';

        container.innerHTML = `
            <div class="page-tabs">
                <button class="page-tab ${saved === 'integrations' ? 'active' : ''}" data-subtab="integrations" onclick="switchPageTab('connections','integrations')">Integrations</button>
                <button class="page-tab ${saved === 'messenger' ? 'active' : ''}" data-subtab="messenger" onclick="switchPageTab('connections','messenger')">Messenger</button>
            </div>
            <div class="page-panel" id="subtab-connections-integrations" ${saved !== 'integrations' ? 'style="display:none"' : ''}>
                <div id="connections-integrations-content"></div>
            </div>
            <div class="page-panel" id="subtab-connections-messenger" ${saved !== 'messenger' ? 'style="display:none"' : ''}>
                <div id="connections-messenger-content"></div>
            </div>
        `;

        loadConnectionTab(saved);
    };

    function loadConnectionTab(tab) {
        if (tab === 'integrations') {
            // Reuse existing integrations.js initIntegrationsTab
            // Point it at the new container
            const target = document.getElementById('connections-integrations-content');
            if (target && typeof loadIntegrations === 'function') {
                loadIntegrations(target);
            } else if (typeof initIntegrationsTab === 'function') {
                // Temporarily swap the integrations-content container
                const origContainer = document.getElementById('integrations-content');
                const newContainer = document.getElementById('connections-integrations-content');
                if (newContainer) {
                    newContainer.id = 'integrations-content';
                    initIntegrationsTab();
                    newContainer.id = 'connections-integrations-content';
                }
            }
        } else if (tab === 'messenger') {
            loadMessengerPanel();
        }
    }

    const _orig = window.switchPageTab;
    window.switchPageTab = function(pageId, tabName) {
        _orig(pageId, tabName);
        if (pageId === 'connections') loadConnectionTab(tabName);
    };

    function loadMessengerPanel() {
        const c = document.getElementById('connections-messenger-content');
        if (!c) return;
        c.innerHTML = '<div style="color:var(--text-tertiary);padding:20px;">Loading messenger platforms...</div>';

        fetch('/api/messenger/platforms').then(r => r.json()).catch(() => ({platforms:{}})).then(data => {
            const platforms = data.platforms || {};
            const entries = Object.entries(platforms);
            if (entries.length === 0) {
                c.innerHTML = '<div style="color:var(--text-tertiary);font-size:13px;padding:20px;">No messenger platforms available.</div>';
                return;
            }

            let html = '<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:12px;">';
            entries.forEach(([name, info]) => {
                const connected = info.connected || info.status === 'connected';
                const icon = info.icon || name.charAt(0).toUpperCase();
                html += `<div class="wh-card">
                    <div class="wh-card-header">
                        <div class="wh-card-title">${icon} ${name.charAt(0).toUpperCase() + name.slice(1)}</div>
                        <span class="wh-badge ${connected ? 'enabled' : 'disabled'}"><span class="wh-badge-dot"></span>${connected ? 'Connected' : 'Disconnected'}</span>
                    </div>
                    <div style="margin-top:8px;">
                        ${connected
                            ? `<button class="wh-btn wh-btn-secondary" style="font-size:12px;" onclick="disconnectMessenger('${name}')">Disconnect</button>`
                            : `<button class="wh-btn wh-btn-primary" style="font-size:12px;" onclick="connectMessenger('${name}')">Connect</button>`
                        }
                    </div>
                </div>`;
            });
            html += '</div>';
            c.innerHTML = html;
        });
    }

    window.connectMessenger = async function(platform) {
        try {
            const resp = await fetch('/api/messenger/wizard/start/' + platform, { method: 'POST' });
            const data = await resp.json();
            showToast('Connection wizard started for ' + platform, 'info');
            loadMessengerPanel();
        } catch(e) { showToast(e.message, 'error'); }
    };

    window.disconnectMessenger = async function(platform) {
        if (!confirm('Disconnect ' + platform + '?')) return;
        showToast('Disconnecting ' + platform + '...', 'info');
        loadMessengerPanel();
    };

})();
```

- [ ] **Step 2: Add script tag in index.html and remove old Settings panels**

Add script tag:
```html
    <script src="/static/js/connections.js"></script>
```

Remove from `loadSettings()`:
- The `data-stab="integrations"` panel (now in Connections > Integrations)
- The `data-stab="messenger"` section (now in Connections > Messenger)

Also remove the Integrations and Messenger buttons from Settings sub-tab bar.

- [ ] **Step 3: Simplify Settings sub-tabs**

The Settings sub-tab bar should now only have:
```
[General] [Prompts] [Safety] [System]
```

Remove the `Messenger`, `Agents`, `Integrations`, and `Webhook` sub-tab buttons. Remove the `settings-integrations` and `settings-webhook` special panel divs.

- [ ] **Step 4: Verify**

Open Connections page → verify Integrations and Messenger tabs render. Open Settings → verify it only shows General, Prompts, Safety, System.

- [ ] **Step 5: Commit**

```bash
git add src/breadmind/web/static/js/connections.js
git add src/breadmind/web/static/index.html
git commit -m "feat(web): add Connections page, simplify Settings sub-tabs"
```

---

## Task 8: Fix cross-file references and final cleanup

**Files:**
- Modify: `src/breadmind/web/static/js/personal.js:134`
- Modify: `src/breadmind/web/static/js/integrations.js:243`
- Modify: `src/breadmind/web/static/js/onboarding.js:131`
- Modify: `src/breadmind/web/static/index.html`

- [ ] **Step 1: Update personal.js**

Line 134: change `switchTab('settings'); setTimeout(()=>switchSettingsTab('integrations'),100);` to:

```javascript
switchPage('connections');
```

- [ ] **Step 2: Update integrations.js**

Line 243: change `switchTab('personal')` to `switchPage('assistant')`.

- [ ] **Step 3: Update onboarding.js**

Line 131: change `switchTab('personal')` to `switchPage('assistant')`.

- [ ] **Step 4: Update hash restore in index.html init script**

Ensure the bottom init script calls `initSidebar()` instead of manual hash restoration. Also update the `Coding Jobs` fetchCodingJobs to not depend on the old monitoring tab structure.

- [ ] **Step 5: Update sidebar event badge**

In the monitoring events update function (in index.html), add badge count to sidebar:

```javascript
// After updating eventCount in loadEvents or on WebSocket event:
const badge = document.getElementById('sidebar-event-count');
if (badge) {
    const count = allEvents.length;
    badge.textContent = count;
    badge.style.display = count > 0 ? '' : 'none';
}
```

- [ ] **Step 6: Verify end-to-end**

Test all pages:
1. Chat — message send/receive, sessions, sidebar assistant
2. Assistant — tasks, events, contacts
3. Automation — Webhooks, Scheduler, Swarm, Jobs, Containers
4. Monitoring — Events, Audit Log, Usage, Tool Metrics, Approvals
5. Explore — MCP, Skills, Plugins
6. Connections — Integrations, Messenger
7. Settings — General, Prompts, Safety, System
8. Sidebar collapse/expand, URL hash routing, mobile responsive

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "fix(web): update cross-file references for sidebar navigation migration"
```

---

## Summary

| Task | Description | New Files | Modified Files |
|------|------------|-----------|---------------|
| 1 | Sidebar CSS foundation | `css/sidebar.css` | `index.html` |
| 2 | Sidebar JS + page switching | `js/sidebar.js` | `index.html` |
| 3 | HTML layout restructure | — | `index.html` |
| 4 | Merge stores → Explore | — | `index.html` |
| 5 | Automation page | `js/automation.js` | `index.html` |
| 6 | Monitoring page expansion | `js/monitoring-page.js` | `index.html` |
| 7 | Connections page + Settings cleanup | `js/connections.js` | `index.html` |
| 8 | Cross-file refs + final cleanup | — | `personal.js`, `integrations.js`, `onboarding.js`, `index.html` |
