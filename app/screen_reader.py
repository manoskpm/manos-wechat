"""위챗 화면을 '사진 찍듯' 캡처해서 업체 메시지를 읽는 부분.

- 위챗에 입력하거나 클릭하지 않습니다. 화면에 보이는 그림만 읽습니다.
- 위챗이 맨 앞(또는 번역 패널이 맨 앞)일 때만 읽어서, 다른 창을 잘못 읽지 않게 합니다.
"""
from __future__ import annotations

import threading
import time
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
    frame_rgb: tuple = ()           # 위챗 바깥 테두리 색 (반투명이라 바탕화면에 따라 바뀜)


def image_signature(img, size=(48, 48)):
    return list(img.convert("L").resize(size).getdata())


SAME_TITLE = 8.0  # 제목 지문 차이가 이 값 이하면 같은 대화방 (글자 픽셀이 약 3% 이내로 다름)


def title_signature(title_img) -> list:
    """대화방 제목 지문: 제목 줄에서 글자(어두운 부분)만 정확히 잘라 흑백으로 만든 120x16 그림.
    빈 배경이 대부분이라 그냥 비교하면 다른 방도 같아 보이므로, 글자 부분만 비교함."""
    gray = title_img.convert("L")
    w, h = gray.size
    region = gray.crop((min(10, w - 1), 0, min(w, 340), h))
    dark = region.point(lambda v: 255 if v < 150 else 0)
    box = dark.getbbox()
    if not box:
        return [0] * (120 * 16)
    text = dark.crop(box).resize((120, 16))
    return [255 if v >= 128 else 0 for v in text.getdata()]


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
    if max(max(p[c] for p in rcore) - min(p[c] for p in rcore) for c in range(3)) > 24:
        return "photo"
    rmean = tuple(sum(p[c] for p in rcore) / len(rcore) for c in range(3))
    if not _close(rmean, (r, g, b), 12):
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


def analyze_window(img, ocr_result, cfg: dict, last_chat_left: float | None = None) -> ScanResult:
    """위챗 창 전체 사진 + 글자 인식 결과 → 거래처 이름과 말풍선."""
    w, h = img.width, img.height
    lines = to_lines(ocr_result, cfg["ocr_min_score"], cfg.get("ocr_min_height", 12))
    chat_left = (detect_chat_left(lines, w) or detect_chat_left_by_color(img)
                 or last_chat_left or w * cfg["chat_left_ratio"])
    chat_right = detect_chat_right_by_color(img, chat_left) or w
    lines = [l for l in lines if l.x1 <= chat_right + 4]
    title_h = cfg.get("title_height") or detect_header_bottom(img, chat_left) or int(h * 0.09)
    input_top = detect_input_top(img, chat_left)
    input_h = cfg.get("input_height") or (h - input_top + 4 if input_top else int(h * 0.24))
    rgb = img.convert("RGB")
    bg = background_color(rgb, chat_left, title_h)
    vendor, bubbles = parse_chat(
        crop_lines(lines, chat_left), chat_right - chat_left, h, title_h, input_h,
        side_fn=lambda l: bubble_side_by_color(rgb, l, chat_left, bg))
    # 제목 왼쪽 부분만 (창 크기를 바꿔도 같은 대화방이면 같은 모양이 되도록 고정 폭)
    title_img = img.crop((int(chat_left), 0, int(min(chat_right, chat_left + 360)), title_h))
    band_h, frame_rgb = measure_frame(img, chat_left)
    res = ScanResult(vendor, title_signature(title_img), bubbles, chat_left, title_h)
    res.band_h, res.frame_rgb = band_h, frame_rgb
    return res


class ScreenReader:
    def __init__(self, cfg: dict, on_scan, own_hwnd_getter, log_path=None):
        """on_scan(ScanResult) 는 화면이 바뀌고 안정되었을 때 호출됨 (별도 스레드)."""
        self.cfg = cfg
        self.on_scan = on_scan
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

    def _grab(self, rect):
        import mss
        from PIL import Image
        l, t, r, b = rect
        with mss.mss() as sct:
            shot = sct.grab({"left": l, "top": t, "width": r - l, "height": b - t})
            return Image.frombytes("RGB", shot.size, shot.rgb)

    def _get_ocr(self):
        if self._ocr is None:
            from rapidocr_onnxruntime import RapidOCR
            self._ocr = RapidOCR()
        return self._ocr

    def scan_image(self, img) -> ScanResult:
        import numpy as np
        result, _ = self._get_ocr()(np.array(img))
        res = analyze_window(img, result, self.cfg, self._chat_left)
        self._chat_left = res.chat_left
        res.title_text = self._title_text(img, res)
        return res

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
        if len(text.replace(" ", "")) < 2:
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

    def _loop(self):
        while not self._stop.is_set():
            try:
                self._tick()
            except Exception as e:  # 화면 읽기 오류로 프로그램 전체가 멈추지 않게
                self.status = f"화면 읽기 오류: {e}"
                self._log(traceback.format_exc())
            time.sleep(self.cfg.get("poll_seconds", 1.5))

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
        img = self._grab(rect)
        self._mask_own_panel(img, rect)
        sig = image_signature(img)
        if signature_distance(sig, self._last_sig) <= 3.0:
            self.status = "자동 읽기 중"
            return
        # 스크롤 중일 수 있으니 한 번 더 같은 화면일 때(안정됐을 때) 읽음
        if signature_distance(sig, self._pending_sig) > 3.0:
            self._pending_sig = sig
            return
        self._last_sig = sig
        self.last_image = img
        self.status = "읽는 중..."
        res = self.scan_image(img)
        self.status = "자동 읽기 중"
        self._log(f"scan title={res.title_text!r} vendor={res.vendor!r} chat_left={res.chat_left:.0f} "
                  f"bubbles={[(b.side, b.text[:20]) for b in res.bubbles]}")
        self.on_scan(res)
