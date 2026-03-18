# External Credential Input Design

## Summary

BreadMind의 메신저 채널(Slack, Discord, Telegram 등 9개)에서 인증 관련 민감한 정보가 필요할 때, 임시 URL 기반 독립 HTML 페이지를 통해 안전하게 입력받는 기능.

**Goal:** 메신저 채널에서 평문 비밀번호가 메시지로 노출되지 않도록, 일회용 URL을 통해 브라우저에서 자격증명을 입력받고 CredentialVault에 암호화 저장한다.

## 전체 흐름

```
메신저 사용자 → "OpenWrt에 SSH 접속해줘"
    ↓
에이전트가 router_manage 호출 → 비밀번호 필요 감지
    ↓
[REQUEST_INPUT] 폼 생성 → 메신저 채널 감지
    ↓
에이전트가 ExternalInputTokenStore.create() 직접 호출 (내부 Python 호출, HTTP 아님)
    → 일회용 토큰 생성 (secrets.token_urlsafe(32))
    → 5분 TTL, 인메모리 dict 저장
    ↓
메신저에 URL 전송: "아래 링크에서 자격증명을 입력해주세요: https://breadmind:8080/credential-input/{token}"
    ↓
사용자가 브라우저에서 URL 접속
    ↓
GET /credential-input/{token}
    → 토큰 검증 (존재 + 만료 + 미사용)
    → 독립 HTML 페이지로 폼 렌더링 (폼 JSON 기반 동적 생성)
    → CSRF 토큰을 hidden field로 삽입
    ↓
사용자가 폼 작성 후 제출
    ↓
POST /api/vault/submit-external/{token}
    → 토큰 + CSRF 토큰 재검증
    → password 필드 → CredentialVault에 Fernet 암호화 저장
    → credential_ref 토큰 생성
    → 토큰 무효화 (1회용)
    → 원래 메신저 채널에 완료 알림 전송
    ↓
메신저에서: "자격증명이 입력되었습니다."
```

## 메신저 채널 감지

현재 `CoreAgent.handle_message()`는 `user`, `channel` 문자열만 받는다.
`MessageRouter`가 `IncomingMessage(platform="slack", channel_id="C0123")` 형태로 전달하지만,
에이전트 호출 시 platform 정보가 소실된다.

**해결:** `handle_message()`에 `platform: str | None = None` 파라미터 추가.
- `platform`이 None → 웹 UI → 기존 인라인 `[REQUEST_INPUT]` 폼 동작
- `platform`이 있음 → 메신저 → `ExternalInputTokenStore.create()` 호출 → URL 전송

호출 경로:
```
MessageRouter._message_handler(IncomingMessage)
    → CoreAgent.handle_message(msg.text, msg.user_id, msg.channel_id, platform=msg.platform)
```

## API 엔드포인트

### `GET /credential-input/{token}`

- 토큰 유효 → 독립 HTML 페이지 (폼 렌더링 + CSRF 토큰 삽입)
- 토큰 무효/만료 → 에러 페이지 ("링크가 만료되었습니다", HTTP 410 Gone)

### `POST /api/vault/submit-external/{token}`

요청:
```json
{
  "csrf_token": "...",
  "fields": [
    {"name": "username", "value": "root", "type": "text"},
    {"name": "password", "value": "secret", "type": "password"}
  ]
}
```

성공 응답 (200):
```json
{
  "success": true,
  "refs": {"password": "credential_ref:ext:ssh-10.0.0.1:password"}
}
```

에러 응답:
- `410 Gone` — 토큰 만료 또는 이미 사용됨: `{"error": "token_expired"}`
- `400 Bad Request` — 필드 누락/불일치: `{"error": "invalid_fields", "detail": "..."}`
- `403 Forbidden` — CSRF 토큰 불일치: `{"error": "csrf_mismatch"}`
- `500` — vault 저장 실패: `{"error": "storage_error"}`

콜백 알림 실패 시: 로그만 기록, 사용자에게는 성공 반환 (credential은 이미 저장됨).

## 컴포넌트 구조

### 새 파일
- **`src/breadmind/web/routes/credential_input.py`** — 외부 입력 전용 라우트 + HTML 렌더링 + `ExternalInputTokenStore` 클래스

### 수정 파일
- **`src/breadmind/core/agent.py`** — `handle_message()`에 `platform` 파라미터 추가, 메신저 채널에서 `[REQUEST_INPUT]` 감지 시 URL 변환
- **`src/breadmind/messenger/router.py`** — `_message_handler` 호출 시 `platform` 전달
- **`src/breadmind/main.py`** — 새 라우터 등록

### `ExternalInputTokenStore` 클래스

```python
class ExternalInputTokenStore:
    _tokens: dict[str, TokenEntry]  # {token: {form, callback, created_at, used, csrf_token}}
    MAX_PENDING = 100  # 최대 동시 대기 토큰 수

    def create(form, callback) -> tuple[str, str]:  # (token, url)
    def validate(token) -> TokenEntry | None:
    def mark_used(token) -> None:
    def _cleanup_expired() -> None:  # create() 호출 시마다 실행
```

- 인메모리 `dict` 관리 (5분 TTL이므로 영속성 불필요)
- `create()` 호출 시마다 만료 토큰 정리
- `MAX_PENDING` 초과 시 가장 오래된 토큰부터 제거

### credential_id 명명 규칙

외부 폼 제출 credential: `ext:{form_id}:{field_name}`
- 예: `ext:ssh-10.0.0.1:password`
- `credential_ref:ext:ssh-10.0.0.1:password` (full ref)

### URL 구성

`BREADMIND_BASE_URL` 환경변수 사용. 미설정 시 요청의 `Host` 헤더 + scheme으로 구성.
- 예: `https://breadmind.local:8080/credential-input/{token}`

### 독립 HTML 페이지
- Python `HTMLResponse`로 반환 (별도 파일 불필요)
- 기존 dynform CSS 스타일 인라인 포함
- JavaScript: 폼 JSON 기반 동적 필드 생성 + fetch 호출
- CSRF 토큰을 hidden field로 포함

## 보안 요구사항

- 토큰: `secrets.token_urlsafe(32)` — 256비트 엔트로피
- TTL: 5분, 1회용 — 사용 후 즉시 무효화
- CSRF: 페이지 렌더링 시 `secrets.token_urlsafe(16)` 생성, submit 시 검증
- HTTPS: 기존 `config.py`의 HTTPS enforcement 정책을 따름 (`BREADMIND_HTTPS_ONLY`)
- password 필드만 vault에 Fernet 암호화 저장
- 평문 비밀번호는 메모리에서만 존재, 응답에 credential_ref만 포함
- Rate limiting: 기존 인프라의 rate limiter 적용 (`submit-external` 엔드포인트)
- 최대 동시 대기 토큰: 100개 (DoS 방지)

## 플랫폼별 URL 전송 방식

| 플랫폼 | 전송 방식 |
|--------|----------|
| Slack | Block Kit 버튼 + URL |
| Discord | 텍스트 링크 |
| Telegram | InlineKeyboardButton + URL |
| WhatsApp | 텍스트 링크 |
| Gmail | 이메일 본문 링크 |
| Signal | 텍스트 링크 |
| Teams | 텍스트 링크 |
| LINE | 텍스트 링크 |
| Matrix | 텍스트 링크 |

버튼 지원 플랫폼(Slack, Telegram)은 클릭 가능한 버튼으로, 나머지는 텍스트 URL로 전송.

## 완료 후 동작

자격증명 입력 완료 시 메신저 채널에 단순 완료 알림만 전송.
에이전트가 자동으로 원래 작업을 재개하지 않음 — 사용자가 다시 명령해야 함.
