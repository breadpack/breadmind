# Deployment & Installation Design Spec

**Date:** 2026-03-14
**Status:** Approved
**Scope:** Docker Compose, Helm Chart, 네이티브 설치 스크립트 (Linux/macOS/Windows)

## 1. Overview

BreadMind를 다양한 환경에 간편하게 설치할 수 있는 배포 패키지를 제공한다.

### 배포 방식

| 방식 | 대상 환경 | 도구 |
|------|----------|------|
| Docker Compose | 로컬/개발/소규모 서버 | `docker compose up -d` |
| Helm Chart | Kubernetes (Rancher, ArgoCD, Flux) | `helm install` |
| install.sh | Linux (systemd) / macOS (launchd) | curl 원라이너 |
| install.ps1 | Windows (nssm 서비스) | PowerShell 원라이너 |

### 핵심 결정 사항

| 항목 | 결정 |
|------|------|
| K8s 배포 | Helm chart (Rancher/ArgoCD/Flux 모두 호환) |
| 네이티브 설치 | 쉘/PS 스크립트 기반 (패키지 매니저는 향후) |
| PostgreSQL | 기본 Docker 컨테이너, --external-db 옵션 |
| 의존성 미설치 시 | 사용자에게 설치 여부 확인 후 자동 설치 |

## 2. Project Structure

```
deploy/
├── helm/
│   └── breadmind/
│       ├── Chart.yaml
│       ├── values.yaml
│       └── templates/
│           ├── deployment.yaml
│           ├── service.yaml
│           ├── configmap.yaml
│           ├── secret.yaml
│           └── postgres-statefulset.yaml
├── install/
│   ├── install.sh          # Linux/macOS
│   ├── install.ps1         # Windows
│   ├── uninstall.sh
│   └── uninstall.ps1
├── docker-compose.yaml     # (루트의 기존 파일 개선)
└── .env.example
```

## 3. Docker Compose

기존 `docker-compose.yaml` 개선:
- `.env.example` 제공
- healthcheck 완비
- config 볼륨 마운트
- `docker compose up -d` 한 줄로 시작

## 4. Helm Chart

- `values.yaml`로 모든 설정 커스터마이징
- PostgreSQL StatefulSet 내장 (postgres.enabled: false로 비활성화 가능)
- externalDatabase 설정으로 외부 DB 연결
- ConfigMap: config.yaml, safety.yaml
- Secret: API 키, DB 비밀번호
- Ingress 선택적 활성화

## 5. 네이티브 설치 스크립트

### 5.1 설치 흐름

```
설치 스크립트 실행
    │
    ├─ Python 3.12+ 체크
    │   └─ 없으면 → "Python 3.12+를 설치할까요? (y/n)"
    │       ├─ y → 플랫폼별 자동 설치
    │       │   ├─ Linux: apt/dnf/pacman
    │       │   ├─ macOS: Homebrew (brew 없으면 brew도 설치)
    │       │   └─ Windows: winget install Python.Python.3.12
    │       └─ n → 안내 메시지 출력 후 종료
    │
    ├─ Docker 체크 (--external-db가 아닌 경우)
    │   └─ 없으면 → "Docker를 설치할까요? (y/n)"
    │       ├─ y → 플랫폼별 자동 설치
    │       │   ├─ Linux: 공식 get-docker.sh
    │       │   ├─ macOS: brew install --cask docker
    │       │   └─ Windows: winget install Docker.DockerDesktop
    │       └─ n → --external-db 모드로 전환, DB 연결 정보 입력
    │
    ├─ pip install breadmind
    │
    ├─ DB 구성
    │   ├─ Docker 모드 → PostgreSQL 컨테이너 시작
    │   └─ External 모드 → 연결 테스트
    │
    ├─ config 파일 생성 (~/.config/breadmind/ 또는 %APPDATA%\breadmind\)
    ├─ 서비스 등록 + 시작
    └─ 상태 확인 + 완료 메시지
```

### 5.2 Linux (systemd)

- 서비스 파일: `/etc/systemd/system/breadmind.service`
- config: `~/.config/breadmind/`
- `systemctl enable --now breadmind`

### 5.3 macOS (launchd)

- plist: `~/Library/LaunchAgents/dev.breadpack.breadmind.plist`
- config: `~/.config/breadmind/`
- `launchctl load`

### 5.4 Windows (nssm)

- nssm으로 서비스 등록 (없으면 자동 다운로드)
- config: `%APPDATA%\breadmind\`
- sc fallback 지원

### 5.5 언인스톨

- 서비스 중지 + 해제
- DB 컨테이너 중지/삭제 (사용자 확인)
- config 파일 보존 여부 확인
- pip uninstall breadmind
