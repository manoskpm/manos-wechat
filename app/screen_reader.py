"""위챗 화면을 '사진 찍듯' 캡처해서 업체 메시지를 읽는 부분.

- 위챗에 입력하거나 클릭하지 않습니다. 화면에 보이는 그림만 읽습니다.
- 위챗이 맨 앞(또는 번역 패널이 맨 앞)일 때만 읽어서, 다른 창을 잘못 읽지 않게 합니다.
"""
from __future__ import annotations

import threading
import time
from pathlib import Path

from . import win_window
from .chat_parser import parse_chat, to_lines


class ScreenReader:
    def __init__(self, cfg: dict, on_scan, own_hwnd_getter):
        """on_scan(vendor, bubbles) 는 화면이 바뀌고 안정되었을 때 호출됨 (별도 스레드)."""
        self.cfg = cfg
        self.on_scan = on_scan
        self.own_hwnd_getter = own_hwnd_getter
        self.enabled = cfg.get("auto_read", True)
        self._stop = threading.Event()
        self._ocr = None
        self._last_sig = None
        self._pending_sig = None
        self.status = "준비 중"
        self.last_image = None

    # ---- 캡처 ----
    def chat_region(self, rect):
        l, t, r, b = rect
        w = r - l
        return {"left": l + int(w * self.cfg["chat_left_ratio"]), "top": t,
                "width": r - (l + int(w * self.cfg["chat_left_ratio"])), "height": b - t}

    def _grab(self, region):
        import mss
        from PIL import Image
        with mss.mss() as sct:
            shot = sct.grab(region)
            return Image.frombytes("RGB", shot.size, shot.rgb)

    @staticmethod
    def _signature(img):
        small = img.convert("L").resize((48, 48))
        return list(small.getdata())

    @staticmethod
    def _changed(a, b, threshold=3.0) -> bool:
        if a is None or b is None:
            return True
        return sum(abs(x - y) for x, y in zip(a, b)) / len(a) > threshold

    def _get_ocr(self):
        if self._ocr is None:
            from rapidocr_onnxruntime import RapidOCR
            self._ocr = RapidOCR()
        return self._ocr

    def scan_image(self, img):
        import numpy as np
        result, _ = self._get_ocr()(np.array(img))
        lines = to_lines(result, self.cfg["ocr_min_score"])
        return parse_chat(lines, img.width, img.height,
                          self.cfg["title_height"], self.cfg["input_height"])

    def save_debug_image(self, path: Path) -> bool:
        """영역 확인용: 마지막으로 읽은 화면을 저장 (화면 맞춤 조정에 사용)."""
        if self.last_image is None:
            return False
        from PIL import ImageDraw
        img = self.last_image.copy()
        d = ImageDraw.Draw(img)
        d.line([(0, self.cfg["title_height"]), (img.width, self.cfg["title_height"])], fill="red", width=2)
        y = img.height - self.cfg["input_height"]
        d.line([(0, y), (img.width, y)], fill="red", width=2)
        img.save(path)
        return True

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
            self.status = "위챗이 맨 앞에 있을 때 읽습니다"
            return
        img = self._grab(self.chat_region(rect))
        sig = self._signature(img)
        if not self._changed(sig, self._last_sig):
            self.status = "자동 읽기 중"
            return
        # 스크롤 중일 수 있으니 한 번 더 같은 화면일 때(안정됐을 때) 읽음
        if self._changed(sig, self._pending_sig):
            self._pending_sig = sig
            return
        self._last_sig = sig
        self.last_image = img
        self.status = "읽는 중..."
        vendor, bubbles = self.scan_image(img)
        self.status = "자동 읽기 중"
        self.on_scan(vendor, bubbles)
