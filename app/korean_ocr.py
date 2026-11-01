"""윈도우에 기본으로 들어 있는 글자 인식(OCR)으로 한국어 대화방 이름을 읽는 부분.

한국어 윈도우에는 한국어 글자 인식이 기본으로 설치되어 있습니다.
쓸 수 없는 환경이면 None 을 돌려주고, 프로그램은 제목 모양으로 대화방을 구분합니다.
"""
from __future__ import annotations

import asyncio
import re
import sys

_engine = None
_unavailable = False


def _get_engine():
    global _engine, _unavailable
    if _engine is not None or _unavailable:
        return _engine
    try:
        from winrt.windows.globalization import Language
        from winrt.windows.media.ocr import OcrEngine
        lang = Language("ko")
        if OcrEngine.is_language_supported(lang):
            _engine = OcrEngine.try_create_from_language(lang)
        if _engine is None:
            _unavailable = True
    except Exception:
        _unavailable = True
    return _engine


async def _await(op):
    return await op


def read_text(img) -> str | None:
    """그림 속 글자를 한국어 인식으로 읽음 (실패하면 None)."""
    if sys.platform != "win32":
        return None
    engine = _get_engine()
    if engine is None:
        return None
    try:
        from winrt.windows.graphics.imaging import BitmapPixelFormat, SoftwareBitmap
        from winrt.windows.storage.streams import DataWriter
        img = img.convert("RGBA")
        writer = DataWriter()
        writer.write_bytes(img.tobytes())
        bitmap = SoftwareBitmap.create_copy_from_buffer(
            writer.detach_buffer(), BitmapPixelFormat.RGBA8, img.width, img.height)
        result = asyncio.run(_await(engine.recognize_async(bitmap)))
        return result.text or None
    except Exception:
        return None


def clean_title(text: str | None) -> str:
    """대화방 제목 정리: 줄바꿈·인원수 표시·앞뒤 기호 제거."""
    if not text:
        return ""
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"\s*[(（]\d+[)）]\s*$", "", text)
    return text.strip(" .·-_|")
