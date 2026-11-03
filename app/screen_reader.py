"""위챗 화면을 '사진 찍듯' 캡처해서 업체 메시지를 읽는 부분.

- 위챗에 입력하거나 클릭하지 않습니다. 화면에 보이는 그림만 읽습니다.
- 위챗이 맨 앞(또는 번역 패널이 맨 앞)일 때만 읽어서, 다른 창을 잘못 읽지 않게 합니다.
"""
from __future__ import annotations

import threading
import time

import numpy as np
import traceback
from dataclasses import dataclass, field

from . import win_window
from .chat_parser import Bubble, crop_lines, detect_chat_left, parse_chat, to_lines


@dataclass
class ScanResult:
    vendor: str                     # 제목에서 읽은 거래처 이름 (한국어 메모 이름은 못 읽어 빈 값일 수 있음)
    title_sig: list = field(default_factory=list)  # 제목 부분의 그림 지문 (이름을 못 읽을 때 대화방 구분용)
    bubbles: list[Bubble] = field(default_factory=list)
    chat_left: float = 0
    title_h: int = 0
    title_text: str = ""            # 윈도우 한국어 인식으로 읽은 대화방 이름 (예: 칭펑 핸드메이드)
    title_png: bytes = b""          # 제목 줄 그림 (윈도우 인식이 실패하면 Claude에게 이름을 물어볼 때 사용)
    band_h: int = 0                 # 위챗 맨 위 회색 줄 높이 (화면 픽셀)
    items: list = field(default_factory=list)   # 거울 화면용 덩어리 (segment.Item)
    chat_top: int = 0               # 대화 영역 위쪽 (제목 아래 선)
    chat_bottom: int = 0            # 대화 영역 아래쪽 (입력칸 윗선)
    win_h: int = 0                  # 위챗 창 높이 (화면 픽셀)
    frame_rgb: tuple = ()           # 위챗 바깥 테두리 색 (반투명이라 바탕화면에 따라 바뀜)
    chat_bg: tuple = ()             # 위챗 대화 영역 바탕색
    timing: dict = field(default_factory=dict)   # 걸린 시간 기록 (속도 확인용)
    chat_right: float = 0           # 대화 영역 오른쪽 끝


def image_signature(img, size=(48, 48)):
    return list(img.convert("L").resize(size).getdata())


SAME_TITLE = 8.0  # 제목 지문 차이가 이 값 이하면 같은 대화방 (글자 픽셀이 약 3% 이내로 다름)


def title_signature(title_img) -> list:
    """대화방 제목 지문: 이름이 있는 부분(위챗 창 버튼·오른쪽 아이콘 제외)의 글자만 흑백으로 만든 그림.
    가는 글자 획이 줄이면서 사라지지 않도록, 줄인 뒤 조금만 어두워도 글자로 봄."""
    gray = title_img.convert("L")
    w, h = gray.size
    region = gray.crop((min(10, w - 1), 0, max(11, int(w * 0.62)), h))
    dark = region.point(lambda v: 255 if v < 150 else 0)
    box = dark.getbbox()
    if not box:
        return [0] * (160 * 20)
    from PIL import Image as _Image
    text = dark.crop(box).resize((160, 20), _Image.BOX)
    return [255 if v >= 40 else 0 for v in text.getdata()]


def same_title(a, b) -> bool:
    return signature_distance(a, b) <= SAME_TITLE


def signature_distance(a, b) -> float:
    if not a or not b or len(a) != len(b):
        return 999.0
    return sum(abs(x - y) for x, y in zip(a, b)) / len(a)


def _close(a, b, tol=6) -> bool:
    return all(abs(a[i] - b[i]) <= tol for i in range(3))


def bubble_side_by_color(img, line, offset_x: float, bg=None):
    """글자 왼쪽의 말풍선 여백을 보고 판단.

    진짜 말풍선은 글자 왼쪽에 '짧고 고른 색 띠(말풍선 여백)'가 있고 그 다음이 대화 배경입니다.
    사진 속 글자는 그 띠가 길거나 색이 고르지 않습니다.
    초록 띠 = 내가 보낸 것, 흰색/회색 띠 = 업체.
    """
    rgb = img if img.mode == "RGB" else img.convert("RGB")
    x0 = int(line.x0 + offset_x)
    h = line.y1 - line.y0
    y = int((line.y0 + line.y1) / 2)
    if bg is None or x0 < 3 or h < 4:
        return None
    max_run = int(h * 2.5) + 6
    run = []
    x = x0 - 2
    while x > offset_x and len(run) <= max_run:
        p = rgb.getpixel((x, y))
        if _close(p, bg) and len(run) >= 2:
            break
        run.append(p)
        x -= 1
    else:
        return "photo"  # 대화 배경까지 너무 멀다 = 사진 속 글자
    core = run[1:-1] or run
    spread = max(max(p[c] for p in core) - min(p[c] for p in core) for c in range(3))
    if spread > 24:
        return "photo"
    r = sum(p[0] for p in core) / len(core)
    g = sum(p[1] for p in core) / len(core)
    b = sum(p[2] for p in core) / len(core)
    if _close((r, g, b), bg, 4):
        return "plain"  # 말풍선 없이 배경에 바로 쓴 글 (시간 표시, 안내 문구)
    # 오른쪽 여백도 같은 말풍선 색이 고르게 이어지다 배경으로 끝나야 진짜 말풍선
    # (업체가 보낸 캡처 사진 속 작은 말풍선 글자를 걸러냄)
    right = []
    x = int(line.x1 + offset_x) + 2
    while x < rgb.width - 1 and len(right) <= int(rgb.width * 0.8):
        p = rgb.getpixel((x, y))
        if _close(p, bg) and len(right) >= 2:
            break
        right.append(p)
        x += 1
    else:
        return "photo"
    rcore = right[1:-1] or right
    # 배경 바로 앞(말풍선 오른쪽 안쪽 여백)이 말풍선 색이면 진짜 말풍선
    # (글자 뒤에 붙은 이모지 같은 작은 그림은 허용)
    tail = rcore[-4:]
    if not all(_close(p, (r, g, b), 14) for p in tail):
        return "photo"
    # 왼쪽 여백 세로줄도 위아래로 같은 색이 이어지다 배경으로 끝나야 함 (사진 테두리 걸러냄)
    col = int(line.x0 + offset_x) - 4
    for step in (-1, 1):
        yy, n = y, 0
        while 0 < yy < rgb.height - 1:
            p = rgb.getpixel((col, yy))
            if _close(p, bg):
                break
            if not _close(p, (r, g, b), 14):
                return "photo"
            yy += step
            n += 1
            if n > h * 15:
                return "photo"
        else:
            return "photo"
    if g > r + 25 and g > b + 25:
        return "out"
    if abs(r - g) < 15 and abs(g - b) < 15:
        return "in"
    return "photo"


def background_color(img, chat_left: float, top: int):
    """대화 영역 배경색 (제목선 바로 아래, 왼쪽 가장자리)."""
    rgb = img if img.mode == "RGB" else img.convert("RGB")
    x = int(min(img.width - 1, chat_left + 6))
    ys = range(int(top) + 4, min(img.height - 1, int(top) + 40), 3)
    pixels = [rgb.getpixel((x, y)) for y in ys]
    return max(set(pixels), key=pixels.count) if pixels else None


def _find_divider(img, chat_left: float, y_from: int, y_to: int) -> int | None:
    """대화 영역에서 가로로 쭉 이어진 얇은 선(제목 아래 선, 입력창 테두리)을 위에서부터 찾음."""
    gray = img.convert("L")
    x0 = int(chat_left + (img.width - chat_left) * 0.2)
    x1 = int(chat_left + (img.width - chat_left) * 0.6)
    if x1 - x0 < 20:
        return None
    xs = range(x0, x1, max(1, (x1 - x0) // 40))

    def row(y):
        vals = [gray.getpixel((x, y)) for x in xs]
        return sum(vals) / len(vals), max(vals) - min(vals)

    for y in range(max(2, y_from), min(img.height - 2, y_to)):
        mean, spread = row(y)
        if spread > 4:
            continue
        above, above_spread = row(y - 2)
        # 얇은 선 = 바로 위의 고른 배경보다 어두운 줄 (아래는 사진이 바로 붙어도 됨).
        # 맨 위 회색 줄 → 흰 카드 경계는 아래가 더 밝아서 제외됨.
        if above_spread <= 4 and above - mean >= 5:
            return y
    return None


def detect_header_bottom(img, chat_left: float) -> int | None:
    """대화방 제목 아래의 얇은 구분선 (제목과 대화 내용을 구분)."""
    return _find_divider(img, chat_left, 20, int(img.height * 0.25))


def detect_input_box_top(img, chat_left: float, chat_right: float | None = None) -> int | None:
    """위챗 입력칸 윗선: 대화 영역 가로 거의 전체를 잇는 얇은 회색 선 (입력칸 테두리).
    입력칸이 대화 내용 위에 그려지므로 사진이 걸쳐 있어도 이 선은 끊기지 않음."""
    arr = np.asarray(img.convert("L"), dtype=np.int16)
    h, w = arr.shape
    cr = int(chat_right or w)
    sub = arr[:, int(chat_left) + 20:cr - 20]
    if sub.shape[1] < 50:
        return None
    gray = ((sub >= 200) & (sub <= 243)).mean(axis=1)
    light = (sub >= 245).mean(axis=1)
    for y in range(int(h * 0.45), h - 60):
        if gray[y] >= 0.85 and light[y + 3] >= 0.85:
            return y
    return None


def detect_input_top(img, chat_left: float) -> int | None:
    """메시지 입력창의 윗 테두리 (입력창에 붙여넣은 글은 읽지 않기 위해)."""
    return _find_divider(img, chat_left, int(img.height * 0.6), int(img.height * 0.97))


def detect_chat_left_by_color(img) -> float | None:
    """대화 영역 왼쪽 끝 찾기 (색 기준): 왼쪽 아이콘 줄이나 대화방 목록이 끝나고
    대화 배경색이 시작되는 세로 경계. 위챗을 좁게 써서 대화방 목록이 없는 화면에서도 동작."""
    from collections import Counter
    gray = img.convert("L")
    w, h = gray.size
    ys = range(int(h * 0.15), int(h * 0.85), 5)

    def mode(x):
        c = Counter(gray.getpixel((x, y)) for y in ys).most_common(1)[0]
        return c[0], c[1] / len(ys)

    bg = mode(int(w * 0.8))[0]
    modes = [mode(x) for x in range(int(w * 0.65))]
    for x in range(30, len(modes) - 14):
        near_bg = lambda m: abs(m[0] - bg) <= 2 and m[1] >= 0.6
        if near_bg(modes[x]) and not near_bg(modes[x - 1]) and all(near_bg(m) for m in modes[x:x + 12]):
            return float(x)
    return None


def detect_chat_right_by_color(img, chat_left: float) -> float | None:
    """대화 영역 오른쪽 끝 찾기: 위챗 4.2 에서 모멘트 등 다른 창이 대화창 오른쪽에 붙어 열린 경우,
    대화 배경색이 끝나는 세로 경계. 없으면 None (창 끝까지 대화 영역)."""
    from collections import Counter
    gray = img.convert("L")
    w, h = gray.size
    ys = range(int(h * 0.15), int(h * 0.85), 5)

    def mode(x):
        c = Counter(gray.getpixel((x, y)) for y in ys).most_common(1)[0]
        return c[0], c[1] / len(ys)

    bg = mode(int(chat_left) + 8)[0]
    start = int(chat_left) + 200
    modes = [mode(x) for x in range(start, w - 4)]
    # 대화 배경이 아닌 '한 가지 색으로 꽉 찬' 세로줄이 이어지면 경계 (말풍선이 지나는 줄은 색이 섞여서 제외됨)
    for i in range(len(modes) - 6):
        if all(abs(m[0] - bg) > 2 and m[1] >= 0.85 for m in modes[i:i + 6]):
            return float(start + i)
        # 위챗 4.2: 모멘트 창이 오른쪽에 붙으면 사이에 얇은(3~5픽셀) 진한 경계선만 있음
        if all(abs(m[0] - bg) > 25 and m[1] >= 0.97 for m in modes[i:i + 3]):
            return float(start + i)
    return None


def looks_like_wechat_main(img) -> bool:
    """위챗 대화창(본 창)인지 확인: 왼쪽에 회색 아이콘 줄이 있고, 그 오른쪽에서 대화 영역이 시작됨.
    (위챗 안의 웹페이지 창·모멘트 창·사진 보기 창은 이 모양이 아님)"""
    rgb = img.convert("RGB")
    w, h = rgb.size
    if w < 300 or h < 300:
        return False
    xs = range(6, min(60, int(w * 0.08)), 3)
    ys = range(int(h * 0.2), int(h * 0.8), 6)
    pixels = [rgb.getpixel((x, y)) for x in xs for y in ys]
    # 아이콘 줄 = 대부분 무채색이고 흰색이 아님 (위챗 버전에 따라 단색이거나 살짝 그러데이션)
    navlike = sum(1 for p in pixels if max(p) - min(p) <= 10 and max(p) < 240)
    if navlike / len(pixels) < 0.7:
        return False
    return detect_chat_left_by_color(rgb) is not None


def measure_frame(img, chat_left: float) -> tuple[int, tuple]:
    """위챗 맨 위 회색 줄의 높이와 색을 잼 (번역 패널을 똑같이 맞추기 위해)."""
    rgb = img.convert("RGB")
    x = int(min(rgb.width - 1, chat_left + 30))
    frame = rgb.getpixel((x, 4))
    for y in range(4, min(rgb.height, 120)):
        p = rgb.getpixel((x, y))
        if sum(p) / 3 > sum(frame) / 3 + 12:  # 회색 줄 → 밝은 대화 카드
            return y, frame
    return 0, frame


BASE_BAND = 40   # 시험 화면(기준 크기)의 위챗 맨 위 회색 줄 높이


def estimate_scale(img) -> tuple[float, float | None]:
    """화면 배율 추정: 위챗 맨 위 회색 줄 높이가 배율에 따라 정확히 늘어남 (기준 40 → 150%면 60).
    (배율, 기준 크기에서의 대화 영역 왼쪽 끝)"""
    cl = detect_chat_left_by_color(img)
    if cl is None:
        return 1.0, None
    band = measure_frame(img, cl)[0]
    scale = band / BASE_BAND if band else 1.0
    if scale < 1.15:   # 거의 기준 크기면 그대로
        return 1.0, cl
    return min(scale, 3.0), cl / min(scale, 3.0)


def analyze_window(img, ocr_result, cfg: dict, last_chat_left: float | None = None,
                   chat_left: float | None = None, title_h: int | None = None) -> ScanResult:
    """위챗 창 전체 사진 + 글자 인식 결과 → 거래처 이름과 말풍선.
    chat_left 를 주면(대화 영역만 글자 인식한 경우) 대화방 목록 날짜로 찾는 단계를 건너뜀."""
    w, h = img.width, img.height
    lines = to_lines(ocr_result, cfg["ocr_min_score"], cfg.get("ocr_min_height", 12))
    chat_left = (chat_left or detect_chat_left(lines, w) or detect_chat_left_by_color(img)
                 or last_chat_left or w * cfg["chat_left_ratio"])
    chat_right = detect_chat_right_by_color(img, chat_left) or w
    lines = [l for l in lines if l.x1 <= chat_right + 4]
    title_h = title_h or cfg.get("title_height") or detect_header_bottom(img, chat_left) or int(h * 0.09)
    input_top = detect_input_top(img, chat_left)
    input_h = cfg.get("input_height") or (h - input_top + 4 if input_top else int(h * 0.24))
    rgb = img.convert("RGB")
    bg = background_color(rgb, chat_left, title_h)
    vendor, bubbles = parse_chat(
        crop_lines(lines, chat_left), chat_right - chat_left, h, title_h, input_h,
        side_fn=lambda l: bubble_side_by_color(rgb, l, chat_left, bg))
    # 제목 왼쪽 부분만 (창 크기를 바꿔도 같은 대화방이면 같은 모양이 되도록 고정 폭)
    band_top = measure_frame(img, chat_left)[0]
    title_img = img.crop((int(chat_left), band_top + 2, int(chat_right), max(band_top + 4, title_h - 2)))
    band_h, frame_rgb = measure_frame(img, chat_left)
    res = ScanResult(vendor, title_signature(title_img), bubbles, chat_left, title_h)
    res.band_h, res.frame_rgb = band_h, frame_rgb
    return res


def chat_profile(img, box) -> np.ndarray | None:
    """스크롤 따라가기용: 대화 영역을 세로로 8칸으로 나눠 줄마다 평균 밝기 (줄 수 × 8)."""
    l, t, r, b = (int(v) for v in box)
    if r - l < 40 or b - t < 40:
        return None
    g = np.asarray(img.convert("RGB").crop((l, t, r, b)))[:, :, 1]   # 초록 채널만 (빠르고, 아래 빠른 찍기와 같은 값)
    return _bands(g)


def _bands(g) -> np.ndarray:
    g = g[:, ::2].astype(np.float32)
    w = g.shape[1] // 8 * 8
    return g[:, :w].reshape(g.shape[0], 8, w // 8).mean(axis=2)


def profile_from_bgra(raw: bytes, w: int, h: int) -> np.ndarray:
    """화면 찍기 결과(BGRA)에서 바로 줄별 밝기 (그림으로 바꾸지 않아서 빠름)."""
    return _bands(np.frombuffer(raw, dtype=np.uint8).reshape(h, w, 4)[:, :, 1])


def _shift_err(prev, cur, d):
    h = prev.shape[0]
    x, y = (prev[:h - d], cur[d:]) if d >= 0 else (prev[-d:], cur[:h + d])
    return float(np.abs(x - y).mean())


def estimate_shift(prev: np.ndarray | None, cur: np.ndarray | None, hint: int = 0) -> int | None:
    """위챗을 스크롤했을 때 화면이 위아래로 몇 픽셀 움직였는지 (글자 인식 없이, 0.01초 안팎).
    양수 = 내용이 아래로 내려감(위쪽 옛날 대화를 봄). 확실하지 않으면 None."""
    if prev is None or cur is None or prev.shape != cur.shape:
        return None
    h = prev.shape[0]
    if not (np.abs(prev - prev.mean(axis=0)).mean() > 2):   # 거의 빈 화면이면 판단 안 함
        return None
    # 스크롤 중에는 직전 움직임 근처만 1줄 단위로 찾음 (아주 빠름)
    if hint:
        r = min(int(h * 0.4), abs(hint) * 2 + 60)
        best, best_err = None, 1e9
        for d in range(-r, r + 1):
            err = _shift_err(prev, cur, d)
            if err < best_err:
                best, best_err = d, err
        if best_err <= 2.0:
            return best or None
    # 4줄 간격으로 대충 찾고 → 그 근처를 1줄 단위로 다듬음 (빠르게)
    a, b = prev[::4], cur[::4]
    n = a.shape[0]
    best, best_err = None, 1e9
    for d in range(-int(n * 0.7), int(n * 0.7) + 1):
        x, y = (a[:n - d], b[d:]) if d >= 0 else (a[-d:], b[:n + d])
        err = float(np.abs(x - y).mean())
        if err < best_err:
            best, best_err = d, err
    if best is None or best_err > 3.0:
        return None
    fine, fine_err = None, 1e9
    for dd in range(best * 4 - 4, best * 4 + 5):
        if abs(dd) >= h * 0.9:
            continue
        err = _shift_err(prev, cur, dd)
        if err < fine_err:
            fine, fine_err = dd, err
    if fine_err > 2.5:
        return None
    return fine if fine else None


def shift_result(res, dy: int):
    """스크롤한 만큼 덩어리 위치를 옮긴 사본 (대화 영역 밖으로 나간 것은 뺌)."""
    import copy
    moved = copy.copy(res)
    items = []
    for it in res.items:
        n = copy.copy(it)
        n.y0, n.y1 = it.y0 + dy, it.y1 + dy
        n.extra = dict(it.extra)
        if "avatar" in n.extra:
            ax0, ay0, ax1, ay1 = n.extra["avatar"]
            n.extra["avatar"] = (ax0, ay0 + dy, ax1, ay1 + dy)
        if n.y1 > res.chat_top and n.y0 < res.chat_bottom:
            items.append(n)
    moved.items = items
    return moved


def new_region(prev, dy: int):
    """스크롤로 새로 보이게 된 줄 범위 (걸쳐 있는 덩어리는 통째로 포함). 너무 크면 None(전체 다시 읽기)."""
    top, bottom = prev.chat_top, prev.chat_bottom
    y0, y1 = (top, top + dy) if dy > 0 else (bottom + dy, bottom)
    changed = True
    while changed:
        changed = False
        for it in prev.items:
            if it.y0 < y1 + 3 and it.y1 > y0 - 3 and (it.y0 < y0 or it.y1 > y1):
                y0, y1 = min(y0, it.y0 - 4), max(y1, it.y1 + 4)
                changed = True
    y0, y1 = max(top, y0), min(bottom, y1)
    if y1 - y0 > (bottom - top) * 0.6 or y1 <= y0:
        return None
    return y0, y1


class ScreenReader:
    def __init__(self, cfg: dict, on_scan, own_hwnd_getter, log_path=None, on_shift=None):
        """on_scan(ScanResult) 는 화면이 바뀌고 안정되었을 때 호출됨 (별도 스레드).
        on_shift(dy) 는 스크롤로 화면이 dy 픽셀 움직였을 때 바로 호출됨 (번역 칸을 같이 움직이도록)."""
        self.cfg = cfg
        self.on_scan = on_scan
        self.on_shift = on_shift
        self._chat_box = None      # 마지막으로 읽은 대화 영역 (화면 픽셀)
        self._ref_profile = None   # 번역 칸이 맞춰져 있는 화면의 줄별 밝기
        self._last_profile = None
        self._last_res = None      # 마지막으로 읽은 결과 (스크롤하면 새로 보이는 부분만 읽기 위해)
        self._shift_acc = 0        # 마지막으로 읽은 뒤 스크롤한 거리
        self._moving_until = 0.0   # 이 시각까지는 스크롤 중으로 봄
        self._last_dy = 0
        self._last_full = 0.0
        self._sct = None
        self._sct_thread = None
        self._scan_cache: list = []   # 최근에 읽은 화면 (같은 화면이면 다시 읽지 않음)
        self.own_hwnd_getter = own_hwnd_getter
        self.log_path = log_path
        self.enabled = cfg.get("auto_read", True)
        self._stop = threading.Event()
        self._ocr = None
        self._last_sig = None
        self._pending_sig = None
        self._chat_left = None
        self._title_cache: list = []
        self.status = "준비 중"
        self.last_image = None

    def is_main_window(self, rect) -> bool:
        return looks_like_wechat_main(self._grab(rect))

    def _sct_get(self):
        """화면 찍기 도구는 한 번만 만들어 계속 씀 (매번 만들면 느림)."""
        if self._sct is None or self._sct_thread != threading.get_ident():
            import mss
            self._sct, self._sct_thread = mss.mss(), threading.get_ident()
        return self._sct

    def _grab(self, rect):
        from PIL import Image
        l, t, r, b = rect
        try:
            shot = self._sct_get().grab({"left": l, "top": t, "width": r - l, "height": b - t})
        except Exception:
            self._sct = None
            raise
        return Image.frombytes("RGB", shot.size, shot.rgb)

    def _motion_tick(self, rect) -> bool:
        """스크롤 따라가기 (빠른 길): 대화 영역만 찍어서 움직인 거리만 잼. 움직였거나 움직이는 중이면 True."""
        box = self._chat_box
        if not box or self._ref_profile is None or rect[3] - rect[1] != box[4]:
            return False
        l, t, r, b = (int(v) for v in box[:4])
        try:
            shot = self._sct_get().grab({"left": rect[0] + l, "top": rect[1] + t, "width": r - l, "height": b - t})
        except Exception:
            self._sct = None
            return False
        prof = profile_from_bgra(shot.bgra, shot.width, shot.height)
        if prof.shape != self._ref_profile.shape:
            return False
        dy = estimate_shift(self._ref_profile, prof, hint=self._last_dy)
        if dy:
            self._ref_profile = prof
            self._shift_acc += dy
            self._last_dy = dy
            self.on_shift(dy)
            self._moving_until = time.time() + 0.35
            return True
        if time.time() < self._moving_until:
            return True
        self._last_dy = 0
        return False

    def _get_ocr(self):
        if self._ocr is None:
            from rapidocr_onnxruntime import RapidOCR
            self._ocr = RapidOCR()
            # 속도: 글자 찾기 단계가 작은 화면을 억지로 키우지 않게 (원래 크기 그대로 → 1.5~2배 빠름)
            for op in getattr(getattr(self._ocr, "text_detector", None), "preprocess_op", []) or []:
                if hasattr(op, "limit_type"):
                    op.limit_type, op.limit_side_len = "max", 2000
        return self._ocr

    def scan_image(self, full, roi=None, prev=None) -> ScanResult:
        """위챗 화면 읽기. 속도를 위해 ① 화면 배율이 크면 기준 크기로 줄이고 ② 대화방 목록은 빼고
        대화 영역만 글자 인식. 결과 위치는 다시 실제 화면 크기로 돌려 줌.
        roi=(위, 아래)와 prev(스크롤만큼 옮긴 이전 결과)를 주면 새로 보이게 된 줄만 읽어서 합침."""
        import numpy as np
        from PIL import Image
        t0 = time.perf_counter()
        full = full if full.mode == "RGB" else full.convert("RGB")
        scale, cl = estimate_scale(full)
        img = full if scale == 1.0 else full.resize((round(full.width / scale), round(full.height / scale)),
                                                    Image.BILINEAR)
        if roi is not None and (cl is None or prev is None):
            roi = None
        if cl is not None:
            x0 = max(0, int(cl) - 2)
            ry0, ry1 = (0, img.height) if roi is None else (max(0, int(roi[0] / scale) - 2),
                                                            min(img.height, int(roi[1] / scale) + 2))
            part = np.array(img.crop((x0, ry0, img.width, ry1)))
            # 속도: 위챗 글자는 항상 바로 서 있으므로 글자 방향 확인 단계는 생략
            result, _ = self._get_ocr()(part, use_cls=False)
            result = [[[[p[0] + x0, p[1] + ry0] for p in box], text, score] for box, text, score in (result or [])]
        else:
            result, _ = self._get_ocr()(np.array(img), use_cls=False)
        t1 = time.perf_counter()
        # 얇은 구분선(제목 아래 선, 입력칸 윗선)은 줄인 화면에서 흐려지므로 원래 화면에서 찾음
        head_full = bottom_full = None
        if scale != 1.0 and cl is not None:
            clf = cl * scale
            head_full = detect_header_bottom(full, clf)
            crf = detect_chat_right_by_color(full, clf) or full.width
            bottom_full = detect_input_box_top(full, clf, crf)
        res = analyze_window(img, result, self.cfg, self._chat_left, chat_left=cl,
                             title_h=round(head_full / scale) if head_full else None)
        self._chat_left = res.chat_left
        # 거울 화면: 대화 영역의 모든 덩어리(말풍선·사진·파일·시간 줄 …)를 위챗과 같은 높이로
        from .chat_parser import to_lines
        from .segment import segment_chat
        chat_right = detect_chat_right_by_color(img, res.chat_left) or img.width
        bottom = (round(bottom_full / scale) if bottom_full else
                  detect_input_box_top(img, res.chat_left, chat_right) or int(img.height * 0.76))
        bg = background_color(img, res.chat_left, res.title_h) or (250, 250, 250)
        res.chat_bg = tuple(bg[:3])
        seg_top, seg_bottom = res.title_h, bottom
        if roi is not None:
            seg_top = max(res.title_h, int(roi[0] / scale) - 2)
            seg_bottom = min(bottom, int(roi[1] / scale) + 2)
        items = segment_chat(img, to_lines(result, self.cfg["ocr_min_score"], 10),
                             res.chat_left, chat_right, seg_top, seg_bottom, bg, ocr_fn=self._ocr_piece)
        # 중국어 인식으로 읽은 제목은 중국어가 대부분일 때만 이름으로 씀 ('나무 옷걸이 lyt' → 'l lyt' 방지)
        v = res.vendor.replace(" ", "")
        cjk = sum(1 for ch in v if "\u4e00" <= ch <= "\u9fff")
        if len(v) < 2 or cjk < len(v) * 0.5:
            res.vendor = ""
        # 위치를 실제 화면 크기로 되돌림
        import io
        S = lambda v: int(round(v * scale))
        for it in items:
            it.y0, it.y1, it.x0, it.x1 = S(it.y0), S(it.y1), S(it.x0), S(it.x1)
            if "line_h" in it.extra:
                it.extra["line_h"] *= scale
            if "avatar" in it.extra:   # 프로필 사진은 작게 잘라 둠 (번역창에서 위챗처럼 보이도록)
                box = tuple(S(v) for v in it.extra["avatar"])
                buf = io.BytesIO()
                full.crop(box).save(buf, format="PNG")
                it.extra["avatar"] = box
                it.extra["avatar_png"] = buf.getvalue()
        if roi is not None:   # 새로 읽은 줄 + 스크롤만큼 옮긴 나머지
            keep = [it for it in prev.items if it.y1 <= roi[0] or it.y0 >= roi[1]]
            items = sorted(keep + items, key=lambda it: it.y0)
        res.items = items
        res.chat_left = res.chat_left * scale
        res.title_h, res.band_h = S(res.title_h), S(res.band_h)
        res.chat_top, res.chat_bottom, res.win_h = res.title_h, S(bottom), full.height
        # 화면 위·아래 끝에서 잘린 덩어리 표시는 실제 대화 영역 기준으로 다시 (일부만 읽은 경우 경계 착각 방지)
        edge = 6 * scale
        for it in res.items:
            if it.y0 <= res.chat_top + edge or it.y1 >= res.chat_bottom - edge:
                it.extra["cut"] = True
            else:
                it.extra.pop("cut", None)
        res.chat_right = chat_right * scale
        # 한글 이름은 패널이 따로(기다리지 않고) Claude 로 읽음 → 제목 그림만 넘김
        title = full.crop((int(res.chat_left), res.band_h, int(min(full.width, res.chat_left + 500 * scale)),
                           res.title_h))
        buf = io.BytesIO()
        title.save(buf, format="PNG")
        res.title_png = buf.getvalue()
        if roi is not None and same_title(res.title_sig, prev.title_sig):
            # 제목 줄은 이번에 글자 인식을 안 했으므로 이전 결과의 이름을 그대로
            res.vendor, res.title_text = prev.vendor, prev.title_text
        res.timing = {"scale": round(scale, 2), "read": round(t1 - t0, 2), "part": roi is not None,
                      "total": round(time.perf_counter() - t0, 2)}
        return res

    def _ocr_piece(self, piece) -> str:
        """말풍선 한 칸만 두 배로 키워 다시 글자 인식 (짧은 글이 가끔 빠지는 것 보완)."""
        import numpy as np
        from PIL import Image, ImageOps
        big = ImageOps.expand(piece.resize((piece.width * 2, piece.height * 2), Image.BICUBIC), 20,
                              fill=piece.getpixel((2, piece.height // 2)))
        result, _ = self._get_ocr()(np.array(big), use_cls=False)
        return "".join(t for _, t, sc in (result or []) if float(sc) >= self.cfg["ocr_min_score"])

    def _title_text(self, img, res) -> str:
        """대화방 이름 읽기 (대화방이 바뀌었을 때만 윈도우 글자 인식을 실행하고, 결과는 기억)."""
        for sig, text, png in self._title_cache:
            if same_title(sig, res.title_sig):
                res.title_png = png
                return text
        from . import korean_ocr
        title = img.crop((int(res.chat_left), res.band_h, int(min(img.width, res.chat_left + 500)), res.title_h))
        text = korean_ocr.clean_title(korean_ocr.read_text(title.resize((title.width * 2, title.height * 2))))
        import io
        buf = io.BytesIO()
        title.save(buf, format="PNG")
        res.title_png = buf.getvalue()
        compact = text.replace(" ", "")
        hangul = sum(1 for ch in compact if "\uac00" <= ch <= "\ud7a3")
        # 한국어 인식은 한글 이름에만 씀 (중국어 제목을 억지로 읽으면 '口 A,춚〔星…'처럼 깨짐)
        if len(compact) < 2 or hangul < len(compact) * 0.5:
            text = ""
        if not text and korean_ocr.last_error:
            self._log(f"대화방 이름 읽기 실패: {korean_ocr.last_error}")
        self._title_cache = (self._title_cache + [(res.title_sig, text, res.title_png)])[-100:]
        return text

    def grab_now(self):
        found = win_window.find_wechat()
        if found:
            self.last_image = self._grab(found[1])
        return self.last_image

    def save_debug_image(self, path) -> bool:
        """영역 확인용: 위챗 화면에 '읽는 영역'을 빨간 선으로 표시해 저장."""
        img = self.last_image or self.grab_now()
        if img is None:
            return False
        from PIL import ImageDraw
        img = img.copy()
        d = ImageDraw.Draw(img)
        left = self._chat_left or img.width * self.cfg["chat_left_ratio"]
        top = self.cfg.get("title_height") or int(img.height * 0.12)
        bottom = img.height - (self.cfg.get("input_height") or int(img.height * 0.24))
        d.rectangle([left, top, img.width - 2, bottom], outline="red", width=3)
        img.save(path)
        return True

    @staticmethod
    def _exact_key(img) -> bytes:
        """같은 화면인지 확인용 (거의 그대로일 때만 같음)."""
        import hashlib
        small = np.asarray(img.convert("L").resize((160, 320)), dtype=np.uint8) // 12
        return hashlib.md5(small.tobytes()).digest()

    def _chat_changed(self, img) -> bool:
        """대화 영역 안에서 말풍선 하나 정도 바뀐 것도 알아챔 (입력칸 커서 깜빡임은 무시)."""
        if not self._chat_box or img.height != self._chat_box[4] or self._last_profile is None:
            return False
        prof = chat_profile(img, self._chat_box[:4])
        return prof is not None and prof.shape == self._last_profile.shape and \
            float(np.abs(prof - self._last_profile).max(axis=1).mean()) > 0.4

    def _remember_box(self, img, res):
        box = (res.chat_left + 4, res.chat_top + 2, (res.chat_right or img.width) - 22, res.chat_bottom - 2)
        self._chat_box = box + (img.height,)
        self._ref_profile = chat_profile(img, box)
        self._last_profile = self._ref_profile

    def _mask_own_panel(self, img, rect):
        """번역 패널이 위챗 위에 겹쳐 있으면 그 부분은 지워서 패널 글자를 읽지 않게 함."""
        own = win_window.window_rect(self.own_hwnd_getter())
        if not own:
            return
        from PIL import ImageDraw
        l, t = rect[0], rect[1]
        box = [own[0] - l, own[1] - t, own[2] - l, own[3] - t]
        if box[2] > 0 and box[3] > 0 and box[0] < img.width and box[1] < img.height:
            ImageDraw.Draw(img).rectangle(box, fill="white")

    def _log(self, msg: str):
        if self.log_path:
            try:
                with open(self.log_path, "a", encoding="utf-8") as f:
                    f.write(time.strftime("%Y-%m-%d %H:%M:%S ") + msg + "\n")
            except OSError:
                pass

    # ---- 반복 ----
    def start(self):
        threading.Thread(target=self._loop, daemon=True).start()

    def stop(self):
        self._stop.set()

    def warm_up(self):
        """글자 인식 프로그램을 켜자마자 미리 불러 두고 한 번 돌려 둠 (첫 대화방이 늦게 뜨지 않게)."""
        try:
            t0 = time.perf_counter()
            from PIL import Image, ImageDraw
            img = Image.new("RGB", (240, 60), (250, 250, 250))
            ImageDraw.Draw(img).rectangle([20, 20, 200, 40], fill=(30, 30, 30))
            self._get_ocr()(np.array(img), use_cls=False)
            self._log(f"글자 인식 준비 {time.perf_counter() - t0:.1f}초")
        except Exception as e:
            self._log(f"글자 인식 준비 실패: {e}")

    def _loop(self):
        self.warm_up()
        while not self._stop.is_set():
            try:
                self._tick()
            except Exception as e:  # 화면 읽기 오류로 프로그램 전체가 멈추지 않게
                self.status = f"화면 읽기 오류: {e}"
                self._log(traceback.format_exc())
            # 스크롤 중에는 1초에 약 25번 확인해서 번역 칸이 부드럽게 따라가게, 멈추면 다시 느긋하게
            moving = time.time() < self._moving_until
            time.sleep(0.008 if moving else min(self.cfg.get("poll_seconds", 0.5), 0.12))

    def _tick(self):
        if not self.enabled:
            self.status = "자동 읽기 꺼짐"
            return
        found = win_window.find_wechat()
        if not found:
            self.status = "위챗 창을 찾지 못함"
            return
        hwnd, rect = found
        fg = win_window.foreground_hwnd()
        if fg not in (hwnd, self.own_hwnd_getter()):
            self.status = "위챗을 클릭하면 읽기 시작"
            return
        if self.on_shift and self._motion_tick(rect):
            return   # 스크롤 중 → 번역 칸만 따라 움직이고, 멈춘 뒤에 읽음
        if time.time() - self._last_full < 0.25:
            return   # 전체 화면 확인은 0.25초마다 (스크롤 시작은 위의 빠른 길이 0.12초마다 확인)
        self._last_full = time.time()
        img = self._grab(rect)
        self._mask_own_panel(img, rect)
        sig = image_signature(img)
        if signature_distance(sig, self._last_sig) <= 3.0 and not self._chat_changed(img):
            self.status = "자동 읽기 중"
            return
        # 스크롤: 화면이 위아래로 얼마나 움직였는지만 재서 번역 칸을 바로 같이 움직임 (글자 인식 전에)
        if self._chat_box and self.on_shift and img.height == self._chat_box[4]:
            prof = chat_profile(img, self._chat_box[:4])
            dy = estimate_shift(self._ref_profile, prof)
            if dy:
                self._ref_profile = prof
                self._shift_acc += dy
                self.on_shift(dy)
                self._moving_until = time.time() + 0.4
                return   # 아직 움직이는 중 → 멈춘 뒤에 새로 보인 부분을 읽음
            if time.time() < self._moving_until:
                return   # 스크롤이 막 멈춘 직후 (화면이 아직 흔들릴 수 있음)
        # 스크롤 중일 수 있으니 0.12초 뒤 한 번 더 찍어서 같은 화면일 때(안정됐을 때) 읽음
        if signature_distance(sig, self._pending_sig) > 3.0:
            self._pending_sig = sig
            time.sleep(0.12)
            img = self._grab(rect)
            self._mask_own_panel(img, rect)
            sig = image_signature(img)
            if signature_distance(sig, self._pending_sig) > 3.0:
                self._pending_sig = sig
                return
        self._last_sig = sig
        self.last_image = img
        # 전에 읽은 화면과 같으면(다시 들어온 대화방 등) 글자 인식 없이 바로
        key = self._exact_key(img)
        cached = next((r for k, r in self._scan_cache if k == key), None)
        if cached is not None:
            self._remember_box(img, cached)
            self.on_scan(cached)
            return
        self.status = "읽는 중..."
        roi = prev = None
        if self._last_res is not None and self._shift_acc and self._chat_box and img.height == self._chat_box[4]:
            prev = shift_result(self._last_res, self._shift_acc)
            roi = new_region(prev, self._shift_acc)
        res = self.scan_image(img, roi=roi, prev=prev)
        self._last_res, self._shift_acc = res, 0
        self._scan_cache = (self._scan_cache + [(key, res)])[-30:]
        self._remember_box(img, res)
        self.status = "자동 읽기 중"
        self._log(f"scan vendor={res.vendor!r} 배율={res.timing.get('scale')} 글자읽기={res.timing.get('read')}초 "
                  f"전체={res.timing.get('total')}초 덩어리={[(i.kind, i.side) for i in res.items]}")
        self.on_scan(res)
