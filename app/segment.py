"""위챗 대화 영역을 '덩어리(말풍선·사진·파일·시간 줄 등)' 단위로 나누는 부분 (거울 화면용).

글자 인식 결과만 보는 게 아니라 화면의 색 덩어리를 먼저 찾기 때문에,
사진·파일·이모티콘처럼 글자가 없는 칸도 빠짐없이 같은 높이로 잡습니다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

import numpy as np

from .chat_parser import TIME_RE, Line

KO_DAYS = {"monday": "월요일", "tuesday": "화요일", "wednesday": "수요일", "thursday": "목요일",
           "friday": "금요일", "saturday": "토요일", "sunday": "일요일", "yesterday": "어제", "today": "오늘",
           "星期一": "월요일", "星期二": "화요일", "星期三": "수요일", "星期四": "목요일", "星期五": "금요일",
           "星期六": "토요일", "星期日": "일요일", "星期天": "일요일", "昨天": "어제", "今天": "오늘",
           "mon": "월", "tue": "화", "wed": "수", "thu": "목", "fri": "금", "sat": "토", "sun": "일"}
RECALL_RE = re.compile(r"취소했|撤回|recalled|withdrew", re.I)
VOICE_RE = re.compile(r"^\d{1,2}\s*[\"″”'’]{1,2}$")
DURATION_RE = re.compile(r"\b\d{1,2}:\d{2}\b")
MONEY_RE = re.compile(r"[¥￥]\s*([\d,]+(?:\.\d{1,2})?)|([\d,]+\.\d{2})")
FILE_RE = re.compile(r"\.(xlsx?|docx?|pptx?|pdf|zip|rar|7z|txt|csv|mp4|mov|jpg|png)(?![a-z])"
                     r"|(?<![\d.])\d+(\.\d+)?\s?[KMG]B?(?![a-z])|微信电脑版|Weixin PC", re.I)
LINK_RE = re.compile(r"\[Link\]|\[链接\]|小程序|Mini Program|分享|单号[:：]|日期[:：]", re.I)


@dataclass
class Item:
    kind: str          # text / photo / video / sticker / file / link / transfer / voice / time / notice / unknown
    side: str          # in(업체, 왼쪽) / out(나, 오른쪽) / center
    y0: int            # 위챗 창 기준 위쪽 (화면 픽셀)
    y1: int
    x0: int
    x1: int
    text: str = ""     # 글자 인식 결과 (말풍선 글, 파일 이름, 시간 등)
    png: bytes = b""   # 사진 칸은 위챗 화면 그 부분을 잘라 둔 그림
    extra: dict = field(default_factory=dict)


def ko_time(text: str) -> str:
    """'Thursday 11:08' → '목요일 11:08', '昨天 11:08' → '어제 11:08'."""
    out = text
    for k, v in sorted(KO_DAYS.items(), key=lambda kv: -len(kv[0])):
        out = re.sub(rf"\b{re.escape(k)}\b" if k.isascii() else re.escape(k), v, out, flags=re.I)
    out = re.sub(r"(\d{1,2}):(\d{2})\s*AM", r"오전 \1:\2", out, flags=re.I)
    out = re.sub(r"(\d{1,2}):(\d{2})\s*PM", r"오후 \1:\2", out, flags=re.I)
    return out


def _runs(flags, min_gap: int):
    """True 가 이어진 구간 [(시작, 끝)] (min_gap 이하로 끊긴 건 이어 붙임)."""
    runs = []
    start = None
    gap = 0
    for i, f in enumerate(flags):
        if f:
            if start is None:
                start = i
            gap = 0
            end = i
        elif start is not None:
            gap += 1
            if gap > min_gap:
                runs.append((start, end + 1))
                start = None
    if start is not None:
        runs.append((start, end + 1))
    return runs


def _is_green(c) -> bool:
    r, g, b = c[:3]
    return g > r + 25 and g > b + 25 and g > 150


def _is_orange(c) -> bool:
    r, g, b = c[:3]
    return r > 200 and 110 < g < 200 and b < 120


def _is_light(c, bg) -> bool:
    r, g, b = c[:3]
    near_bg = all(abs(c[i] - bg[i]) <= 6 for i in range(3))
    return min(r, g, b) >= 225 and max(r, g, b) - min(r, g, b) <= 10 and not near_bg


CLOCK_RE = re.compile(r"\d{1,2}:\d{2}")


def segment_chat(img, lines: list[Line], chat_left: float, chat_right: float, top: int, bottom: int,
                 bg, ocr_fn=None) -> list[Item]:
    """대화 영역(위챗 창 기준 x: chat_left~chat_right, y: top~bottom)을 덩어리로 나눔.
    lines 는 위챗 창 기준 좌표의 글자 인식 결과."""
    arr = np.asarray(img.convert("RGB"), dtype=np.int16)
    x0, x1 = int(chat_left) + 4, int(chat_right) - 22   # 오른쪽 끝 스크롤바는 제외
    top, bottom = int(top) + 2, int(bottom) - 2
    if x1 - x0 < 50 or bottom - top < 20:
        return []
    region = arr[top:bottom, x0:x1]
    bgv = np.array(bg[:3], dtype=np.int16)
    mask = np.abs(region - bgv).max(axis=2) > 6           # 배경이 아닌 곳
    # 위아래로 길게 이어진 세로줄(스크롤바·창 가장자리·그림자)은 내용이 아니므로 제외
    # (사진이 위아래로 꽉 찬 경우도 있으므로 폭이 좁은 줄만 뺌)
    for c0, c1 in _runs(mask.mean(axis=0) > 0.85, min_gap=0):
        if c1 - c0 <= 14:
            mask[:, c0:c1] = False
    width = x1 - x0
    rows = mask[:, ::2].any(axis=1)
    items: list[Item] = []
    for ry0, ry1 in _runs(rows, min_gap=2):
        if ry1 - ry0 < 6:
            continue
        block = mask[ry0:ry1]
        cols = block.any(axis=0)
        segs = _runs(cols, min_gap=6)
        h = ry1 - ry0
        # 프로필 사진(정사각형, 창 가장자리 쪽)은 빼고 내용 부분만
        content = []
        avatar_side = None
        segs = [sg for sg in segs if sg[1] - sg[0] > 3] or segs   # 1~3픽셀짜리 세로 선 조각은 무시
        for cx0, cx1 in segs:
            w = cx1 - cx0
            sub = block[:, cx0:cx1]
            sh = int(sub.any(axis=1).sum())
            square = 0.75 <= w / max(1, sh) <= 1.33 and w <= 80
            at_edge = cx0 <= width * 0.18 or cx1 >= width * 0.82
            # 맨 위·아래에서 잘린 프로필 사진은 정사각형이 아니어도 프로필 칸 안에만 있으면 프로필로 봄
            in_avatar_col = w <= 80 and (cx1 <= width * 0.14 or cx0 >= width * 0.86)
            if (square and at_edge or in_avatar_col) and len(segs) > 1:
                avatar_side = "in" if cx0 <= width * 0.18 else "out"
                continue
            content.append((cx0, cx1))
        if not content:
            content = segs
        if avatar_side is None:
            # 프로필 사진이 내용과 붙어 보일 때: 칸 맨 위쪽 왼쪽/오른쪽 가장자리에 그림이 있는지로 판단
            top_rows = block[:min(h, 50)]
            lz = top_rows[:, :int(width * 0.13)].mean()
            rz_cols = top_rows[:, int(width * 0.87):]
            strip = block[:, int(width * 0.87):].mean(axis=0) > 0.6   # 길쭉한 세로줄은 제외
            rz = rz_cols[:, ~strip].mean() if (~strip).any() else 0.0
            if lz > 0.15 and rz <= 0.05:
                avatar_side = "in"
            elif rz > 0.15 and lz <= 0.05:
                avatar_side = "out"
        cx0 = min(c[0] for c in content)
        cx1 = max(c[1] for c in content)
        # 내용 부분의 실제 위아래 (프로필 사진 때문에 늘어난 높이는 뺌)
        sub = block[:, cx0:cx1]
        ys = np.where(sub.any(axis=1))[0]
        by0, by1 = ry0 + int(ys[0]), ry0 + int(ys[-1]) + 1
        ax0, ax1, ay0, ay1 = x0 + cx0, x0 + cx1, top + by0, top + by1
        inside = [l for l in lines if ax0 - 4 <= (l.x0 + l.x1) / 2 <= ax1 + 4 and ay0 - 4 <= (l.y0 + l.y1) / 2 <= ay1 + 4]
        inside.sort(key=lambda l: (round(l.y0 / 6), l.x0))
        text = "".join(l.text for l in inside).strip()
        pix = arr[ay0:ay1, ax0:ax1].reshape(-1, 3)
        colors, counts = np.unique(pix // 4 * 4, axis=0, return_counts=True)
        mode = tuple(int(v) for v in colors[counts.argmax()])
        share = counts.max() / len(pix)
        bw, bh = ax1 - ax0, ay1 - ay0
        if not inside and ocr_fn and share >= 0.45 and (_is_light(mode, bg) or _is_green(mode)) \
                and bh <= 200 and _uniform_border(arr, ax0, ay0, ax1, ay1, mode):
            # 말풍선 모양인데 글자를 못 읽은 경우: 그 칸만 크게 키워서 다시 읽음
            text = ocr_fn(img.crop((ax0, ay0, ax1, ay1))).strip()
            if text:
                inside = [Line(ax0 + 8, ay0 + 10, ax1 - 8, ay1 - 10, text)]
        bw, bh = ax1 - ax0, ay1 - ay0
        on_bg = all(abs(mode[i] - bg[i]) <= 6 for i in range(3))   # 말풍선 없이 배경에 바로 쓴 글
        gap_l, gap_r = cx0, width - cx1
        # 좌우: 초록이면 나, 아니면 프로필 사진이 있는 쪽, 그것도 없으면 가까운 쪽
        side = "out" if _is_green(mode) else (avatar_side or ("in" if gap_l < gap_r else "out"))
        if on_bg and abs(gap_l - gap_r) < width * 0.12:
            side = "center"
        it = Item("unknown", side, ay0, ay1, ax0, ax1, text)
        if ay0 <= top + 1 and bh < 24:
            continue  # 맨 위에서 잘려 조금만 보이는 칸은 건너뜀
        if on_bg and side != "center" and bh < 40 and text:
            it.kind = "notice"   # 말풍선 없이 배경에 쓴 작은 글 (위챗 안내 문구 등)
        elif side == "center" and bh < 60:
            # 가운데 회색 글: 시간 줄 또는 안내 (메시지 취소 등)
            is_time = TIME_RE.search(text) or (CLOCK_RE.search(text) and not re.search(r"[\u4e00-\u9fff]", text))
            it.kind = "time" if is_time else "notice"
            if it.kind == "notice" and RECALL_RE.search(text):
                it.extra["recall"] = True
        elif share >= 0.45 and _is_green(mode):
            it.kind = "voice" if VOICE_RE.match(text) else "text"
        elif share >= 0.35 and _is_orange(mode):
            it.kind = "transfer"
            m = MONEY_RE.search(text.replace(" ", ""))
            if m:
                it.extra["amount"] = (m.group(1) or m.group(2)).replace(",", "")
        elif share >= 0.45 and _is_light(mode, bg) and _uniform_border(arr, ax0, ay0, ax1, ay1, mode) \
                and _text_fills(inside, ay0, ay1):
            if FILE_RE.search(text):
                it.kind = "file"
            elif LINK_RE.search(text):
                it.kind = "link"
            elif VOICE_RE.match(text):
                it.kind = "voice"
            elif text:
                it.kind = "text"
        else:
            if DURATION_RE.search(text) and bw > 80:
                it.kind = "video"
                it.extra["duration"] = DURATION_RE.search(text).group(0)
            elif bw <= 160 and bh <= 160 and ay1 < bottom - 3 and ay0 > top + 3:
                it.kind = "sticker"   # 위아래 끝에서 잘린 칸은 이모티콘이 아니라 사진으로 봄
            elif bw > 40 and bh > 40:
                it.kind = "photo"
        if it.kind == "unknown" and (ay0 <= top + 3 or ay1 >= bottom - 3) and not text:
            it.kind = "photo"  # 위아래 끝에서 잘린 사진
        if it.side == "center" and it.kind not in ("time", "notice"):
            it.side = avatar_side or ("in" if gap_l < gap_r else "out")
        if it.kind in ("text", "file", "link", "voice"):
            it.extra["bg"] = mode   # 위챗 말풍선 색 그대로 (업체 회색/흰색, 내 초록)
        items.append(it)
    return items


def _uniform_border(arr, x0, y0, x1, y1, mode) -> bool:
    """말풍선·카드: 안쪽 테두리(모서리 제외)가 거의 같은 색. 사진은 테두리 색이 제각각."""
    if x1 - x0 < 20 or y1 - y0 < 16:
        return True
    m = np.array(mode[:3], dtype=np.int16)
    pts = [arr[y0 + 2, x0 + 10:x1 - 10], arr[y1 - 3, x0 + 10:x1 - 10],
           arr[y0 + 8:y1 - 8, x0 + 2], arr[y0 + 8:y1 - 8, x1 - 3]]
    edge = np.concatenate([p.reshape(-1, 3) for p in pts if p.size])
    if not len(edge):
        return True
    close = (np.abs(edge - m).max(axis=1) <= 14).mean()
    return close >= 0.7


def _text_fills(lines, y0: int, y1: int) -> bool:
    """말풍선·카드는 글자가 칸을 거의 채움 (위아래 여백 합 45픽셀 이내 + 줄 사이).
    휴대폰 캡처 같은 사진은 큰 칸에 작은 글자 몇 줄만 있음."""
    if not lines:
        return False
    text_h = sum(l.y1 - l.y0 for l in lines)
    return (y1 - y0) - text_h <= 45 + 12 * max(0, len(lines) - 1)
