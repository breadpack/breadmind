"""멀티모달 입력 처리 유틸리티 테스트."""
from __future__ import annotations

import base64
from pathlib import Path
from unittest.mock import patch


from breadmind.core.protocols.provider import Attachment
from breadmind.plugins.builtin.tools.multimodal import (
    MAX_IMAGE_SIZE,
    extract_image_paths,
    load_image_as_attachment,
    process_message_attachments,
)


# ---------------------------------------------------------------------------
# extract_image_paths
# ---------------------------------------------------------------------------

class TestExtractImagePaths:
    def test_unix_path(self):
        text = "analyze this /home/user/photo.png please"
        assert extract_image_paths(text) == ["/home/user/photo.png"]

    def test_windows_path(self):
        text = "look at C:/Users/milen/img.jpg now"
        assert extract_image_paths(text) == ["C:/Users/milen/img.jpg"]

    def test_windows_backslash_path(self):
        text = r"check C:\Users\milen\screenshot.jpeg end"
        assert extract_image_paths(text) == [r"C:\Users\milen\screenshot.jpeg"]

    def test_multiple_paths(self):
        text = "/tmp/a.png some text /tmp/b.webp"
        result = extract_image_paths(text)
        assert "/tmp/a.png" in result
        assert "/tmp/b.webp" in result

    def test_no_paths(self):
        assert extract_image_paths("hello world") == []

    def test_gif_extension(self):
        text = "see /images/anim.gif here"
        assert extract_image_paths(text) == ["/images/anim.gif"]

    def test_path_at_start(self):
        text = "/data/img.png is the file"
        assert extract_image_paths(text) == ["/data/img.png"]

    def test_path_at_end(self):
        text = "file is /data/img.webp"
        # 패턴은 뒤에 공백이나 끝이 필요하므로 끝에서도 매치
        assert extract_image_paths(text) == ["/data/img.webp"]

    def test_unsupported_extension_not_matched(self):
        text = "open /tmp/doc.pdf now"
        assert extract_image_paths(text) == []


# ---------------------------------------------------------------------------
# load_image_as_attachment
# ---------------------------------------------------------------------------

class TestLoadImageAsAttachment:
    def test_existing_png(self, tmp_path: Path):
        img = tmp_path / "test.png"
        img.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)

        att = load_image_as_attachment(str(img))

        assert att is not None
        assert att.type == "image"
        assert att.media_type == "image/png"
        assert att.path == str(img)
        # data는 standard base64 인코딩이어야 한다
        decoded = base64.standard_b64decode(att.data)
        assert decoded == img.read_bytes()

    def test_existing_jpeg(self, tmp_path: Path):
        img = tmp_path / "photo.jpg"
        img.write_bytes(b"\xff\xd8\xff" + b"\x00" * 50)

        att = load_image_as_attachment(str(img))

        assert att is not None
        assert att.media_type == "image/jpeg"

    def test_nonexistent_file(self):
        att = load_image_as_attachment("/nonexistent/path/img.png")
        assert att is None

    def test_unsupported_format(self, tmp_path: Path):
        bmp = tmp_path / "image.bmp"
        bmp.write_bytes(b"BM" + b"\x00" * 50)

        att = load_image_as_attachment(str(bmp))
        assert att is None

    def test_file_too_large(self, tmp_path: Path):
        img = tmp_path / "huge.png"
        img.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 10)

        with patch.object(
            Path, "stat",
            return_value=type("StatResult", (), {"st_size": MAX_IMAGE_SIZE + 1})(),
        ):
            att = load_image_as_attachment(str(img))

        assert att is None


# ---------------------------------------------------------------------------
# process_message_attachments
# ---------------------------------------------------------------------------

class TestProcessMessageAttachments:
    def test_text_with_image(self, tmp_path: Path):
        img = tmp_path / "cat.png"
        img.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 50)

        text = f"analyze this {img} please"
        clean, attachments = process_message_attachments(text)

        assert len(attachments) == 1
        assert attachments[0].media_type == "image/png"
        assert "[image: cat.png]" in clean
        assert str(img) not in clean

    def test_no_images(self):
        text = "just a normal message"
        clean, attachments = process_message_attachments(text)

        assert clean == text
        assert attachments == []

    def test_nonexistent_image_path_kept(self):
        text = "check /nonexistent/img.png ok"
        clean, attachments = process_message_attachments(text)

        assert attachments == []
        # 존재하지 않는 경로는 텍스트에서 제거되지 않는다
        assert "/nonexistent/img.png" in clean

    def test_multiple_images(self, tmp_path: Path):
        a = tmp_path / "a.png"
        b = tmp_path / "b.jpeg"
        a.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 10)
        b.write_bytes(b"\xff\xd8\xff" + b"\x00" * 10)

        text = f"compare {a} and {b} please"
        clean, attachments = process_message_attachments(text)

        assert len(attachments) == 2
        assert "[image: a.png]" in clean
        assert "[image: b.jpeg]" in clean


# ---------------------------------------------------------------------------
# Claude content block 변환 검증
# ---------------------------------------------------------------------------

class TestClaudeContentBlockConversion:
    """ClaudeAdapter.transform_messages()가 attachments를 올바르게 변환하는지 검증."""

    def test_message_with_attachments(self):
        from breadmind.core.protocols.provider import Message

        att = Attachment(
            type="image",
            data="iVBORw0KGgo=",
            media_type="image/png",
        )
        msg = Message(role="user", content="what is this?", attachments=[att])

        from breadmind.plugins.builtin.providers.claude_adapter import ClaudeAdapter
        adapter = ClaudeAdapter(api_key="test-key")
        result = adapter.transform_messages([msg])

        assert len(result) == 1
        content = result[0]["content"]
        assert isinstance(content, list)
        assert content[0]["type"] == "image"
        assert content[0]["source"]["type"] == "base64"
        assert content[0]["source"]["media_type"] == "image/png"
        assert content[0]["source"]["data"] == "iVBORw0KGgo="
        assert content[1]["type"] == "text"
        assert content[1]["text"] == "what is this?"

    def test_message_without_attachments(self):
        from breadmind.core.protocols.provider import Message

        msg = Message(role="user", content="hello")

        from breadmind.plugins.builtin.providers.claude_adapter import ClaudeAdapter
        adapter = ClaudeAdapter(api_key="test-key")
        result = adapter.transform_messages([msg])

        assert len(result) == 1
        assert result[0]["content"] == "hello"
        assert isinstance(result[0]["content"], str)
