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
    dwmapi = ctypes.windll.dwmapi

    # 64비트 윈도우에서 창 번호(HWND)가 잘리지 않도록 인자 형식을 지정
    user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.IsIconic.argtypes = [wintypes.HWND]
    user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
    user32.GetAncestor.restype = wintypes.HWND
    user32.GetForegroundWindow.restype = wintypes.HWND
    user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
                                    ctypes.c_int, ctypes.c_int, wintypes.UINT]
    dwmapi.DwmGetWindowAttribute.argtypes = [wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD]

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

    def visible_rect(hwnd):
        """눈에 보이는 창 테두리 (윈도우 10/11의 보이지 않는 여백과 그림자를 뺀 크기)."""
        r = wintypes.RECT()
        if dwmapi.DwmGetWindowAttribute(hwnd, 9, ctypes.byref(r), ctypes.sizeof(r)) == 0:  # EXTENDED_FRAME_BOUNDS
            if r.right > r.left and r.bottom > r.top:
                return r.left, r.top, r.right, r.bottom
        return _rect(hwnd)

    def place_visible(hwnd, x, y, w, h):
        """보이는 테두리 기준으로 (x, y)에서 가로 w, 세로 h가 되도록 창을 배치 (제목줄 포함)."""
        ol, ot, orr, ob = _rect(hwnd)
        vl, vt, vr, vb = visible_rect(hwnd)
        ml, mt, mr, mb = vl - ol, vt - ot, orr - vr, ob - vb
        user32.SetWindowPos(hwnd, None, x - ml, y - mt, w + ml + mr, h + mt + mb,
                            0x0004 | 0x0010)  # SWP_NOZORDER | SWP_NOACTIVATE

    def find_wechat():
        """보이는 위챗 창 중 가장 큰 것의 (hwnd, (left, top, right, bottom))."""
        found = []

        @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        def cb(hwnd, _):
            if user32.IsWindowVisible(hwnd) and not user32.IsIconic(hwnd):
                if _title(hwnd).strip() in WECHAT_TITLES:
                    l, t, r, b = visible_rect(hwnd)
                    if r - l > 400 and b - t > 300:
                        found.append((hwnd, (l, t, r, b)))
            return True

        user32.EnumWindows(cb, 0)
        if not found:
            return None
        return max(found, key=lambda f: (f[1][2] - f[1][0]) * (f[1][3] - f[1][1]))

    def wechat_state() -> str:
        """위챗 창 상태: "visible"(보임), "minimized"(최소화), "gone"(닫힘 또는 트레이로 숨김)."""
        if find_wechat():
            return "visible"
        state = ["gone"]

        @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        def cb(hwnd, _):
            if user32.IsWindowVisible(hwnd) and user32.IsIconic(hwnd) and _title(hwnd).strip() in WECHAT_TITLES:
                state[0] = "minimized"
            return True

        user32.EnumWindows(cb, 0)
        return state[0]

    _mutex = None

    def acquire_single_instance(name: str = "ManosWeChatTranslator.Single") -> bool:
        """번역기가 이미 켜져 있으면 False (두 개가 켜지지 않게)."""
        global _mutex
        kernel32 = ctypes.windll.kernel32
        kernel32.CreateMutexW.restype = wintypes.HANDLE
        _mutex = kernel32.CreateMutexW(None, False, name)
        return kernel32.GetLastError() != 183  # ERROR_ALREADY_EXISTS

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

    def place_visible(hwnd, x, y, w, h):
        pass

    def find_wechat():
        return None

    def wechat_state() -> str:
        return "gone"

    def acquire_single_instance(name: str = "") -> bool:
        return True

    def foreground_hwnd():
        return None

    def screen_size():
        return 1920, 1080
