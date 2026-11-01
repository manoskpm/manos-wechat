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


def image_signature(img, size=(48, 48)):
    return list(img.convert("L").resize(size).getdata())


def signature_distance(a, b) -> float:
    if not a or not b or len(a) != len(b):
        return 999.0
    return sum(abs(x - y) for x, y in zip(a, b)) / len(a)


def bubble_side_by_color(img, line, offset_x: float):
    """말풍선 바탕색으로 판단: 초록 = 내가 보낸 것, 흰색/회색 = 업체."""
    x0, x1 = int(line.x0 + offset_x), int(line.x1 + offset_x)
    y0, y1 = int(line.y0), int(line.y1)
    if x1 - x0 < 4 or y1 - y0 < 4:
        return None
    pixels = list(img.crop((x0, y0, x1, y1)).convert("RGB").resize((24, 6)).getdata())
    r = sum(p[0] for p in pixels) / len(pixels)
    g = sum(p[1] for p in pixels) / len(pixels)
    b = sum(p[2] for p in pixels) / len(pixels)
    if g > r + 25 and g > b + 25:
        return "out"
    if abs(r - g) < 15 and abs(g - b) < 15:
        return "in"
    return None


def analyze_window(img, ocr_result, cfg: dict, last_chat_left: float | None = None) -> ScanResult:
    """위챗 창 전체 사진 + 글자 인식 결과 → 거래처 이름과 말풍선."""
    w, h = img.width, img.height
    lines = to_lines(ocr_result, cfg["ocr_min_score"], cfg.get("ocr_min_height", 12))
    chat_left = detect_chat_left(lines, w) or last_chat_left or w * cfg["chat_left_ratio"]
    title_h = cfg.get("title_height") or int(h * 0.12)
    input_h = cfg.get("input_height") or int(h * 0.24)
    vendor, bubbles = parse_chat(
        crop_lines(lines, chat_left), w - chat_left, h, title_h, input_h,
        side_fn=lambda l: bubble_side_by_color(img, l, chat_left))
    title_img = img.crop((int(chat_left), 0, w, title_h))
    return ScanResult(vendor, image_signature(title_img, (96, 12)), bubbles, chat_left)


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
        self.status = "준비 중"
        self.last_image = None

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
        return res

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
        self._log(f"scan vendor={res.vendor!r} chat_left={res.chat_left:.0f} "
                  f"bubbles={[(b.side, b.text[:20]) for b in res.bubbles]}")
        self.on_scan(res)
