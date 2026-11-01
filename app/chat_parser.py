"""화면 글자 인식(OCR) 결과를 '말풍선'으로 정리하는 부분.

윈도우나 위챗과 무관한 순수 계산이라 어디서든 테스트할 수 있습니다.
OCR 결과 한 줄 = (네 꼭짓점 좌표, 글자, 신뢰도)
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher

TIME_RE = re.compile(r"^(昨天|今天|星期.|周.|上午|下午|晚上|凌晨)?\s*\d{1,2}[:：]\d{2}$|^\d{4}年|^\d{1,2}月\d{1,2}日")
CJK_RE = re.compile(r"[一-鿿]")
HANGUL_RE = re.compile(r"[가-힣]")


@dataclass
class Line:
    x0: float
    y0: float
    x1: float
    y1: float
    text: str

    @property
    def h(self) -> float:
        return self.y1 - self.y0


@dataclass
class Bubble:
    side: str  # "in" = 업체, "out" = 나
    text: str
    y0: float
    y1: float


def to_lines(ocr_result, min_score: float = 0.6) -> list[Line]:
    lines = []
    for box, text, score in ocr_result or []:
        try:
            score = float(score)
        except (TypeError, ValueError):
            score = 0.0
        if score < min_score or not str(text).strip():
            continue
        xs = [p[0] for p in box]
        ys = [p[1] for p in box]
        lines.append(Line(min(xs), min(ys), max(xs), max(ys), str(text).strip()))
    return lines


def parse_chat(lines: list[Line], width: float, height: float,
               title_height: float, input_height: float) -> tuple[str, list[Bubble]]:
    """대화 영역 이미지의 OCR 줄들을 (거래처 이름, 말풍선 목록)으로 정리."""
    title_parts = [l for l in lines if (l.y0 + l.y1) / 2 < title_height]
    title_parts.sort(key=lambda l: l.x0)
    vendor = " ".join(l.text for l in title_parts)
    vendor = re.sub(r"\s*[(（]\d+[)）]\s*$", "", vendor).strip()  # 단체방 인원수 표시 제거

    body = [l for l in lines if title_height <= (l.y0 + l.y1) / 2 <= height - input_height]
    body.sort(key=lambda l: (l.y0, l.x0))

    mid = width / 2
    bubbles: list[Bubble] = []
    prev: Line | None = None
    for l in body:
        cx = (l.x0 + l.x1) / 2
        # 가운데 정렬된 짧은 글 = 시간 표시나 시스템 안내 → 제외
        if abs(cx - mid) < width * 0.12 and (l.x1 - l.x0) < width * 0.45:
            prev = None
            continue
        if TIME_RE.search(l.text):
            prev = None
            continue
        # 바로 윗줄과 붙어 있고 시작 위치가 같으면 같은 말풍선의 다음 줄
        # (말풍선 마지막 줄은 짧아서 좌우 판단이 틀릴 수 있으므로 윗줄의 좌우를 따름)
        if (prev is not None and bubbles
                and l.y0 - prev.y1 < max(prev.h, l.h) * 0.9
                and abs(l.x0 - prev.x0) < max(20.0, prev.h)):
            bubbles[-1].text += l.text
            bubbles[-1].y1 = l.y1
        else:
            side = "in" if l.x0 < (width - l.x1) else "out"
            bubbles.append(Bubble(side, l.text, l.y0, l.y1))
        prev = l
    return vendor, bubbles


def normalize(text: str) -> str:
    return re.sub(r"\s+", "", text)


def similar(a: str, b: str, threshold: float = 0.85) -> bool:
    a, b = normalize(a), normalize(b)
    if not a or not b:
        return False
    if a == b:
        return True
    return SequenceMatcher(None, a, b).ratio() >= threshold


def find_new_incoming(bubbles: list[Bubble], known_texts: list[str], max_new: int = 3) -> list[str]:
    """아직 번역하지 않은 업체 말풍선만 골라냄 (최근 것 max_new개까지)."""
    new = []
    for b in bubbles:
        if b.side != "in" or not CJK_RE.search(b.text):
            continue
        if any(similar(b.text, k) for k in known_texts):
            continue
        new.append(b.text)
    return new[-max_new:]


def is_chinese_text(text: str) -> bool:
    """복사한 글이 번역할 중국어인지 (한글이 섞여 있으면 아님)."""
    return bool(CJK_RE.search(text)) and not HANGUL_RE.search(text) and len(text.strip()) <= 2000
