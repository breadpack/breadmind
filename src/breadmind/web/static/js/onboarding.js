// src/breadmind/web/static/js/onboarding.js
/**
 * First-visit onboarding tour and contextual guides
 */
(function() {
    'use strict';

    const STORAGE_KEY = 'breadmind_onboarding_done';
    const INTEGRATION_GUIDE_KEY = 'breadmind_integration_guide_shown';

    window.checkOnboarding = function() {
        if (localStorage.getItem(STORAGE_KEY)) return;
        showOnboardingModal();
    };

    function showOnboardingModal() {
        const steps = [
            {
                title: '🎉 BreadMind에 오신 것을 환영합니다!',
                content: 'BreadMind는 인프라 관리와 개인 비서 기능을 결합한 AI 에이전트입니다.',
                highlight: null,
            },
            {
                title: '💬 채팅으로 모든 것을 시작하세요',
                content: '자연어로 명령하세요. "할 일 추가해줘", "내일 회의 잡아줘", "서버 상태 확인해줘" 등 무엇이든 가능합니다.\n\n/ 명령어로 빠른 실행도 가능합니다: /task, /event, /remind',
                highlight: 'chat',
            },
            {
                title: '📋 비서 탭에서 직접 관리하세요',
                content: '할 일, 일정, 연락처를 칸반보드와 리스트로 관리할 수 있습니다. 채팅에서 만든 항목도 여기에 표시됩니다.',
                highlight: 'personal',
            },
            {
                title: '🔗 서비스를 연결하세요',
                content: 'Settings → Integrations에서 Google Calendar, Notion, Jira, GitHub 등을 원클릭으로 연결할 수 있습니다.',
                highlight: 'settings',
            },
        ];

        let currentStep = 0;

        function render() {
            const step = steps[currentStep];
            const isLast = currentStep === steps.length - 1;
            const isFirst = currentStep === 0;

            let overlay = document.getElementById('onboarding-overlay');
            if (!overlay) {
                overlay = document.createElement('div');
                overlay.id = 'onboarding-overlay';
                document.body.appendChild(overlay);
            }

            overlay.innerHTML = `
                <div class="onboarding-backdrop"></div>
                <div class="onboarding-modal">
                    <div class="onboarding-step-indicator">
                        ${steps.map((_, i) => `<span class="step-dot ${i === currentStep ? 'active' : i < currentStep ? 'done' : ''}"></span>`).join('')}
                    </div>
                    <h2 class="onboarding-title">${step.title}</h2>
                    <p class="onboarding-content">${step.content.replace(/\n/g, '<br>')}</p>
                    <div class="onboarding-actions">
                        <button class="btn-secondary onboarding-skip" onclick="skipOnboarding()">건너뛰기</button>
                        <div>
                            ${!isFirst ? '<button class="btn-secondary onboarding-prev" onclick="onboardingPrev()">이전</button>' : ''}
                            <button class="btn-primary onboarding-next" onclick="onboardingNext()">${isLast ? '시작하기' : '다음'}</button>
                        </div>
                    </div>
                </div>
            `;

            // Highlight tab if specified
            if (step.highlight) {
                document.querySelectorAll('.tab').forEach(btn => {
                    const tabName = btn.getAttribute('onclick');
                    const match = tabName && tabName.includes(`'${step.highlight}'`);
                    btn.classList.toggle('onboarding-highlight', !!match);
                });
            } else {
                document.querySelectorAll('.tab').forEach(btn => btn.classList.remove('onboarding-highlight'));
            }
        }

        window.onboardingNext = function() {
            currentStep++;
            if (currentStep >= steps.length) {
                completeOnboarding();
            } else {
                render();
            }
        };

        window.onboardingPrev = function() {
            if (currentStep > 0) {
                currentStep--;
                render();
            }
        };

        window.skipOnboarding = function() {
            completeOnboarding();
        };

        function completeOnboarding() {
            localStorage.setItem(STORAGE_KEY, 'true');
            const overlay = document.getElementById('onboarding-overlay');
            if (overlay) overlay.remove();
            document.querySelectorAll('.tab').forEach(btn => btn.classList.remove('onboarding-highlight'));
        }

        render();
    }

    // Integration connection success guide
    window.showIntegrationGuide = function(serviceName) {
        const modal = document.getElementById('personal-modal') || document.createElement('div');
        modal.id = 'personal-modal';
        modal.className = 'modal';
        modal.innerHTML = `
            <div class="modal-backdrop" onclick="closeModal()"></div>
            <div class="modal-content">
                <h3>✅ ${serviceName} 연결 완료!</h3>
                <p class="guide-text">이제 다음을 할 수 있습니다:</p>
                <ul class="guide-list">
                    <li>💬 채팅에서 "${serviceName} 데이터 가져와줘" 명령</li>
                    <li>📋 비서 탭에서 동기화된 항목 확인</li>
                    <li>🔄 자동 동기화로 항상 최신 상태 유지</li>
                </ul>
                <div class="modal-actions">
                    <button class="btn-secondary" onclick="closeModal()">닫기</button>
                    <button class="btn-primary" onclick="closeModal(); switchPage('assistant');">비서 탭으로 이동</button>
                </div>
            </div>
        `;
        if (!modal.parentNode) document.body.appendChild(modal);
    };
})();
