"""멀티모달 입력 처리 유틸리티.

이미지 파일 경로를 메시지 텍스트에서 추출하고 base64 인코딩된 Attachment로 변환한다.
"""
from __future__ import annotations

import base64
import mimetypes
import re
from pathlib import Path

from breadmind.core.protocols.provider import Attachment
from breadmind.constants import MAX_IMAGE_SIZE as _MAX_IMAGE_SIZE

SUPPORTED_IMAGE_TYPES = {"image/png", "image/jpeg", "image/gif", "image/webp"}
MAX_IMAGE_SIZE = _MAX_IMAGE_SIZE

# 이미지 파일 경로 패턴: Unix (/path/to/img.png) 및 Windows (C:\path\img.png)
IMAGE_PATH_PATTERN = re.compile(
    r'(?:^|\s)((?:[A-Za-z]:)?[/\\][\w./\\-]+\.(?:png|jpg|jpeg|gif|webp))(?:\s|$)',
    re.IGNORECASE,
)


def extract_image_paths(text: str) -> list[str]:
    """텍스트에서 이미지 파일 경로를 추출한다."""
    return [m.group(1) for m in IMAGE_PATH_PATTERN.finditer(text)]


def load_image_as_attachment(path: str) -> Attachment | None:
    """이미지 파일을 읽어 base64 인코딩된 Attachment로 변환한다.

    파일이 존재하지 않거나 크기 초과 또는 지원하지 않는 형식이면 None을 반환한다.
    """
    p = Path(path)
    if not p.exists():
        return None
    if p.stat().st_size > MAX_IMAGE_SIZE:
        return None
    media_type = mimetypes.guess_type(str(p))[0] or ""
    if media_type not in SUPPORTED_IMAGE_TYPES:
        return None
    data = base64.standard_b64encode(p.read_bytes()).decode("ascii")
    return Attachment(type="image", path=str(p), data=data, media_type=media_type)


def process_message_attachments(text: str) -> tuple[str, list[Attachment]]:
    """메시지 텍스트에서 이미지 경로를 추출하고 Attachment 목록을 반환한다.

    경로를 텍스트에서 제거하고 ``[image: filename]`` 플레이스홀더로 교체한다.
    반환값: (정리된 텍스트, attachments 리스트)
    """
    paths = extract_image_paths(text)
    attachments: list[Attachment] = []
    clean_text = text
    for path in paths:
        att = load_image_as_attachment(path)
        if att:
            attachments.append(att)
            clean_text = clean_text.replace(path, f"[image: {Path(path).name}]")
    return clean_text.strip(), attachments
