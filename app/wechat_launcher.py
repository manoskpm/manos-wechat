"""'위챗+번역기' 아이콘으로 켤 때 위챗을 함께 실행하는 부분."""
from __future__ import annotations

import os
import sys


def _registry_paths() -> list[str]:
    paths = []
    if sys.platform != "win32":
        return paths
    import winreg
    for key, exe in ((r"Software\Tencent\Weixin", "Weixin.exe"), (r"Software\Tencent\WeChat", "WeChat.exe")):
        for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
            try:
                with winreg.OpenKey(hive, key) as k:
                    install = winreg.QueryValueEx(k, "InstallPath")[0]
                    paths.append(os.path.join(install, exe))
            except OSError:
                pass
    return paths


def candidate_paths() -> list[str]:
    pf = os.environ.get("ProgramFiles", r"C:\Program Files")
    pf86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
    common = []
    for base in (pf, pf86):
        common += [os.path.join(base, "Tencent", "Weixin", "Weixin.exe"),
                   os.path.join(base, "Tencent", "WeChat", "WeChat.exe")]
    return _registry_paths() + common


def find_wechat_exe(saved: str | None = None) -> str | None:
    for p in ([saved] if saved else []) + candidate_paths():
        if p and os.path.isfile(p):
            return p
    return None


def launch(path: str) -> bool:
    """위챗 실행 (이미 켜져 있으면 위챗이 알아서 기존 창을 보여줌)."""
    try:
        os.startfile(path)  # noqa: S606 - 대표님이 '위챗+번역기' 아이콘을 눌렀을 때만
        return True
    except OSError:
        return False


def is_running() -> bool:
    """위챗이 이미 켜져 있는지 (트레이에 숨어 있어도)."""
    if sys.platform != "win32":
        return False
    import subprocess
    try:
        out = subprocess.run(["tasklist", "/FO", "CSV", "/NH"], capture_output=True, timeout=10,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout
        text = out.decode("mbcs", "replace").lower()
    except (OSError, subprocess.SubprocessError):
        return False
    return '"weixin.exe"' in text or '"wechat.exe"' in text
