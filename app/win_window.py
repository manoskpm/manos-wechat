"""위챗 창의 '위치와 크기'만 확인하는 부분 (Windows 전용).

위챗 프로그램 내부에는 접근하지 않습니다. 윈도우가 모든 프로그램에 대해
알려주는 창 제목/위치 정보만 읽습니다.
"""
from __future__ import annotations

import sys

WECHAT_TITLES = ("微信", "WeChat", "Weixin")

if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32

    def enable_dpi_awareness() -> None:
        """화면 배율(125%, 150% 등)이 달라도 좌표가 어긋나지 않게 함."""
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except (AttributeError, OSError):
            try:
                user32.SetProcessDPIAware()
            except (AttributeError, OSError):
                pass

    def _title(hwnd) -> str:
        n = user32.GetWindowTextLengthW(hwnd)
        buf = ctypes.create_unicode_buffer(n + 1)
        user32.GetWindowTextW(hwnd, buf, n + 1)
        return buf.value

    def _rect(hwnd):
        r = wintypes.RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(r))
        return r.left, r.top, r.right, r.bottom

    def find_wechat():
        """보이는 위챗 창 중 가장 큰 것의 (hwnd, (left, top, right, bottom))."""
        found = []

        @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        def cb(hwnd, _):
            if user32.IsWindowVisible(hwnd) and not user32.IsIconic(hwnd):
                if _title(hwnd).strip() in WECHAT_TITLES:
                    l, t, r, b = _rect(hwnd)
                    if r - l > 400 and b - t > 300:
                        found.append((hwnd, (l, t, r, b)))
            return True

        user32.EnumWindows(cb, 0)
        if not found:
            return None
        return max(found, key=lambda f: (f[1][2] - f[1][0]) * (f[1][3] - f[1][1]))

    def foreground_hwnd():
        return user32.GetForegroundWindow()

    def toplevel_of(hwnd):
        return user32.GetAncestor(hwnd, 2)  # GA_ROOT

    def window_rect(hwnd):
        return _rect(hwnd) if hwnd else None

    def screen_size():
        return user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)

else:  # 개발용(윈도우가 아닌 환경)에서는 아무것도 찾지 않음
    def enable_dpi_awareness() -> None:
        pass

    def toplevel_of(hwnd):
        return hwnd

    def window_rect(hwnd):
        return None

    def find_wechat():
        return None

    def foreground_hwnd():
        return None

    def screen_size():
        return 1920, 1080
