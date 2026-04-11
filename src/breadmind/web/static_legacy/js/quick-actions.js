// src/breadmind/web/static/js/quick-actions.js
/**
 * Quick Actions — / command autocomplete in chat input
 */
(function() {
    'use strict';

    const COMMANDS = [
        { cmd: '/task', args: '<제목>', desc: '할 일 추가', example: '/task 보고서 작성' },
        { cmd: '/done', args: '<ID>', desc: '할 일 완료', example: '/done abc12345' },
        { cmd: '/event', args: '<제목> --at <시간>', desc: '일정 추가', example: '/event 회의 --at 15:00' },
        { cmd: '/remind', args: '<메시지> --at <시간>', desc: '리마인더', example: '/remind 약 먹기 --at 18:00' },
        { cmd: '/agenda', args: '', desc: '오늘 일정 보기', example: '/agenda' },
        { cmd: '/tasks', args: '', desc: '할 일 목록', example: '/tasks' },
        { cmd: '/contacts', args: '<검색어>', desc: '연락처 검색', example: '/contacts 김철수' },
        { cmd: '/free', args: '[시간]', desc: '빈 시간대 찾기', example: '/free 60' },
    ];

    let dropdownEl = null;
    let selectedIndex = -1;

    window.initQuickActions = function(inputEl) {
        if (!inputEl) return;

        // Create dropdown
        dropdownEl = document.createElement('div');
        dropdownEl.className = 'quick-actions-dropdown hidden';
        inputEl.parentNode.style.position = 'relative';
        inputEl.parentNode.appendChild(dropdownEl);

        inputEl.addEventListener('input', (e) => onInput(e.target));
        inputEl.addEventListener('keydown', (e) => onKeydown(e));
        document.addEventListener('click', () => hideDropdown());
    };

    function onInput(input) {
        const text = input.value;
        if (!text.startsWith('/')) {
            hideDropdown();
            return;
        }

        const query = text.split(' ')[0].toLowerCase();
        const matches = COMMANDS.filter(c => c.cmd.startsWith(query));

        if (matches.length === 0 || text.includes(' ')) {
            hideDropdown();
            return;
        }

        selectedIndex = 0;
        renderDropdown(matches);
    }

    function onKeydown(e) {
        if (dropdownEl.classList.contains('hidden')) return;

        const items = dropdownEl.querySelectorAll('.quick-action-item');
        if (e.key === 'ArrowDown') {
            e.preventDefault();
            selectedIndex = Math.min(selectedIndex + 1, items.length - 1);
            updateSelection(items);
        } else if (e.key === 'ArrowUp') {
            e.preventDefault();
            selectedIndex = Math.max(selectedIndex - 1, 0);
            updateSelection(items);
        } else if (e.key === 'Tab' || (e.key === 'Enter' && !e.shiftKey && selectedIndex >= 0)) {
            if (items.length > 0 && selectedIndex >= 0) {
                e.preventDefault();
                selectCommand(items[selectedIndex].dataset.cmd);
            }
        } else if (e.key === 'Escape') {
            hideDropdown();
        }
    }

    function renderDropdown(matches) {
        let html = '';
        matches.forEach((m, i) => {
            const selected = i === selectedIndex ? 'selected' : '';
            html += `<div class="quick-action-item ${selected}" data-cmd="${m.cmd}" onclick="selectQuickAction('${m.cmd}')">
                <span class="qa-cmd">${m.cmd}</span>
                <span class="qa-args">${m.args}</span>
                <span class="qa-desc">${m.desc}</span>
            </div>`;
        });
        dropdownEl.innerHTML = html;
        dropdownEl.classList.remove('hidden');
    }

    function updateSelection(items) {
        items.forEach((item, i) => {
            item.classList.toggle('selected', i === selectedIndex);
        });
    }

    function hideDropdown() {
        if (dropdownEl) dropdownEl.classList.add('hidden');
        selectedIndex = -1;
    }

    function selectCommand(cmd) {
        const input = document.getElementById('messageInput');
        if (input) {
            input.value = cmd + ' ';
            input.focus();
        }
        hideDropdown();
    }

    window.selectQuickAction = selectCommand;

    // Intercept quick action messages before sending to WebSocket
    window.processQuickAction = function(message) {
        if (!message.startsWith('/')) return null;

        const parts = message.trim().split(/\s+/);
        const cmd = parts[0];
        const rest = parts.slice(1).join(' ');

        switch (cmd) {
            case '/task':
                return `할 일에 추가해줘: ${rest}`;
            case '/done':
                return `할 일 ${rest} 완료 처리해줘`;
            case '/event': {
                const atMatch = rest.match(/(.+?)\s*--at\s+(.+)/);
                if (atMatch) return `${atMatch[2]}에 ${atMatch[1]} 일정 잡아줘`;
                return `${rest} 일정 잡아줘`;
            }
            case '/remind': {
                const atMatch = rest.match(/(.+?)\s*--at\s+(.+)/);
                if (atMatch) return `${atMatch[2]}에 "${atMatch[1]}" 리마인더 설정해줘`;
                return `"${rest}" 리마인더 설정해줘`;
            }
            case '/agenda':
                return '오늘 일정과 할 일 보여줘';
            case '/tasks':
                return '할 일 목록 보여줘';
            case '/contacts':
                return rest ? `${rest} 연락처 찾아줘` : '연락처 목록 보여줘';
            case '/free':
                return rest ? `${rest}분 이상 빈 시간대 찾아줘` : '빈 시간대 찾아줘';
            default:
                return null; // Not a quick action, send as-is
        }
    };
})();
